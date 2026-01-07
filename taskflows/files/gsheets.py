import re
from dataclasses import asdict, dataclass
from functools import cached_property
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

import gspread
import numpy as np
import pandas as pd
from gspread import Spreadsheet, Worksheet
from gspread.utils import ValueInputOption
from requests.exceptions import JSONDecodeError

from .utils import logger

COLUMN_CHARS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
COLUMN_CHARS += [f"A{c}" for c in COLUMN_CHARS]


class RetryGetattributeMixin:
    """Mixin that wraps callable attributes with retry logic via __getattribute__.

    - Retries up to _retry_max_attempts (default: 3) on _retry_exceptions (default: Exception).
    - Exponential backoff based on _retry_base_delay (default: 0.5s).
    - Skips names starting with '_' and non-callables.
    - Caches wrapped callables per-instance to avoid re-wrapping.
    """

    _retry_max_attempts: int = 3
    _retry_base_delay: float = 0.5
    _retry_exceptions = (Exception,)

    def __getattribute__(self, name):  # type: ignore[override]
        # Avoid intercepting private/dunder and our internal cache accesses
        if name.startswith("_"):
            return object.__getattribute__(self, name)

        attr = object.__getattribute__(self, name)

        # Only wrap callables (e.g., bound methods). Leave data attrs/properties alone.
        if not callable(attr):
            return attr

        # Access or create per-instance cache for wrapped attributes
        dct = object.__getattribute__(self, "__dict__")
        cache = dct.get("_retry_wrapped_cache")
        if cache is None:
            cache = dct["_retry_wrapped_cache"] = {}

        wrapped = cache.get(name)
        if wrapped is not None:
            return wrapped

        # Only wrap functions/methods; skip classes/other callables
        import inspect
        if not (inspect.ismethod(attr) or inspect.isfunction(attr)):
            return attr

        import time
        from functools import wraps

        max_attempts = object.__getattribute__(self, "_retry_max_attempts")
        base_delay = object.__getattribute__(self, "_retry_base_delay")
        retry_excs = object.__getattribute__(self, "_retry_exceptions")

        @wraps(attr)
        def _wrapped(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return attr(*args, **kwargs)
                except retry_excs as exc:  # type: ignore[misc]
                    last_exc = exc
                    # Log and backoff if we have remaining attempts
                    try:
                        logger.warning(
                            f"Retrying {self.__class__.__name__}.{name} after error (attempt {attempt}/{max_attempts}): {exc}"
                        )
                    except Exception:
                        pass
                    if attempt >= max_attempts:
                        raise
                    time.sleep(base_delay * (2 ** (attempt - 1)))
            # Should not reach here; re-raise last exception defensively
            if last_exc is not None:
                raise last_exc
            return attr(*args, **kwargs)

        cache[name] = _wrapped
        return _wrapped


@dataclass
class ChartLine:
    x: str
    y: str


@dataclass
class CellPadding:
    """Padding around cell content."""

    top: int
    bottom: int
    left: int
    right: int


@dataclass
class RGBColor:
    """RGB color. Values should be between in range [0,1]."""

    red: int
    green: int
    blue: int

    @classmethod
    def from_0_255(cls, red: int, green: int, blue: int):
        """RGB color using [0,255] range values."""
        return cls(red=red / 255, green=green / 255, blue=blue / 255)


white = RGBColor(red=1, green=1, blue=1)
orange = RGBColor.from_0_255(red=255, green=153, blue=0)
dark_orange = RGBColor.from_0_255(red=255, green=109, blue=1)


class SheetBot(RetryGetattributeMixin):
    def __init__(
        self,
        srv_acct_file: str,
        gdrive_folder_id: Optional[str] = None,
    ):
        self.srv_acct_file = srv_acct_file
        self.gdrive_folder_id = gdrive_folder_id
        self.spreadsheets = {}
        self.worksheets = {}

    def share_spreadsheet(
        self,
        spreadsheet: str,
        email_address: str,
        perm_type: Literal["user", "group", "domain", "anyone"] = "user",
        role: Literal["owner", "writer", "reader"] = "writer",
    ):
        """Share a spreadsheet with a user."""
        logger.info(
            f"Sharing spreadsheet {spreadsheet} with {email_address} (role={role})"
        )
        spreadsheet = self.get_spreadsheet(spreadsheet)
        spreadsheet.share(email_address, perm_type=perm_type, role=role)

    def append_to_sheet(
        self,
        data: pd.DataFrame,
        worksheet: str,
        spreadsheet: str,
        include_header: bool = False,
    ):
        """Append data to a worksheet."""
        logger.info("Appending data to sheet")
        worksheet = self.get_worksheet(spreadsheet, worksheet)
        worksheet.append_rows(data.values.tolist(), include_header=include_header)

    def clear_worksheet(self, spreadsheet: str, worksheet: str):
        """Clear a worksheet."""
        logger.info(f"Clearing worksheet {worksheet} in spreadsheet {spreadsheet}")
        ws = self.get_worksheet(spreadsheet, worksheet)
        ws.clear()

    def find_cell(
        self, spreadsheet: str, worksheet: str, query: str
    ) -> Optional[gspread.Cell]:
        """Find a cell in a worksheet."""
        logger.info(f"Finding cell with query '{query}' in worksheet {worksheet}")
        ws = self.get_worksheet(spreadsheet, worksheet)
        try:
            return ws.find(query)
        except gspread.exceptions.CellNotFound:
            return None

    def get_sheet_df(self, spreadsheet: str, worksheet: str) -> pd.DataFrame:
        worksheet = self.get_worksheet(spreadsheet=spreadsheet, worksheet=worksheet)
        data = worksheet.get_all_values()
        # Convert the data to a Pandas DataFrame
        df = pd.DataFrame(data[1:], columns=data[0])
        # strip all string values.
        for column in df.select_dtypes(include="object").columns:
            col = df[column]
            if hasattr(col, "str"):
                df[column] = col.str.strip()
        return df

    def delete_sheet(self, spreadsheet: str, worksheet: str) -> bool:
        spreadsheet = self.get_spreadsheet(spreadsheet)
        try:
            ws = spreadsheet.worksheet(worksheet)
            logger.info(f"Deleting worksheet {worksheet} ({ws})")
            spreadsheet.del_worksheet(ws)
            return True
        except gspread.exceptions.WorksheetNotFound:
            return False

    def update_sheet(
        self,
        data: pd.DataFrame,
        worksheet: str,
        spreadsheet: str,
        has_index: bool = True,
    ):
        """Set sheet data and format it."""
        logger.info("Setting sheet data")
        worksheet = self.get_worksheet(spreadsheet, worksheet)
        # delete sheet1 if it exists
        self.delete_sheet(spreadsheet=spreadsheet, worksheet="Sheet1")
        # get spreadsheet object.
        spreadsheet = self.get_spreadsheet(spreadsheet)
        data = data.copy()
        worksheet.clear()
        columns = [str(c) for c in data.columns]
        columns_fmt = [self._format_column_name(c) for c in columns]
        # set header.
        worksheet.update(
            f"A1:{COLUMN_CHARS[len(columns) - 1]}1",
            [columns_fmt],
        )
        # strings need to be 'raw' format so they don't get converted to other types (e.g. number or links)
        raw_cols = [str(c) for c in data.select_dtypes(include="object").columns]
        user_entered_cols = [c for c in columns if c not in raw_cols]
        datetime_cols = data.select_dtypes(
            include=["datetime", "datetimetz"]
        ).columns.to_list()
        # format datetimes so they will be parsable by Google.
        for col in datetime_cols:
            data[col] = data[col].dt.strftime("%Y-%m-%d %H:%M:%S %Z")

        data = data.replace({np.nan: None})
        # data = data.astype("object").fillna("")

        def set_columns_data(col_names, raw=None):
            logger.info(f"Setting sheet columns (raw={raw}): {col_names}")
            if not len(col_names):
                return
            kwargs = {}
            if raw is not None:
                kwargs["value_input_option"] = (
                    ValueInputOption.raw if raw else ValueInputOption.user_entered
                )
            for start, end in self._column_ranges(col_names, columns):
                df_cols = data.iloc[:, start:end]
                values = df_cols.values.tolist()
                try:
                    worksheet.update(
                        f"{COLUMN_CHARS[start]}2:{COLUMN_CHARS[end]}{len(df_cols)+1}",
                        values,
                        **kwargs,
                    )
                except JSONDecodeError:
                    logger.exception(
                        f"Error updating columns {df_cols}. Values: {values}",
                        exc_info=True,
                        stack_info=True,
                        extra=True,
                    )

        set_columns_data(raw_cols, True)
        set_columns_data(user_entered_cols, False)

        sheet_id = worksheet.id
        end_row_idx = len(data) + 1
        requests = []

        def set_values_format(
            col_name_or_row_idx: str | int,
            font_size: int = 10,
            h_align: Literal["LEFT", "CENTER", "RIGHT"] = "CENTER",
            v_align: Literal["TOP", "MIDDLE", "BOTTOM"] = "MIDDLE",
            bold: bool = False,
            bg_color: Optional[RGBColor] = None,
            text_color: Optional[RGBColor] = None,
            padding: Optional[CellPadding] = None,
        ):
            if isinstance(col_name_or_row_idx, str):
                col_idx = columns.index(col_name_or_row_idx)
                rng = {
                    # skip header.
                    "startRowIndex": 1,
                    "endRowIndex": end_row_idx,
                    "startColumnIndex": col_idx,
                    "endColumnIndex": col_idx + 1,
                }
            else:
                assert isinstance(col_name_or_row_idx, int)
                rng = {
                    "startRowIndex": col_name_or_row_idx,
                    "endRowIndex": col_name_or_row_idx + 1,
                }
            text_fmt = {
                "fontSize": font_size,
                "bold": bold,
            }
            if text_color is not None:
                text_fmt["foregroundColor"] = asdict(text_color)

            user_entered_fmt = {
                "horizontalAlignment": h_align,
                "verticalAlignment": v_align,
                "textFormat": text_fmt,
            }
            if bg_color is not None:
                user_entered_fmt["backgroundColor"] = asdict(bg_color)
            if padding is not None:
                user_entered_fmt["padding"] = asdict(padding)
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            **rng,
                        },
                        "cell": {"userEnteredFormat": user_entered_fmt},
                        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,padding)",
                    }
                }
            )

        ## FORMAT HEADER
        set_values_format(
            col_name_or_row_idx=0,
            font_size=10,
            bold=True,
        )
        ## FORMAT COLUMNS VALUES
        # pct_columns = [c for c, cf in zip(columns, columns_fmt) if "(%)" in cf]
        dollar_columns = [c for c, cf in zip(columns, columns_fmt) if "($)" in cf]
        numeric_cols = data.select_dtypes(include="number").columns.tolist()
        numeric_cols_no_unit = [c for c in numeric_cols if c not in dollar_columns]
        for cols, col_type, pattern in (
            (numeric_cols_no_unit, "NUMBER", "#,##0.000"),
            # (pct_columns, "NUMBER", "0.00%"),
            (dollar_columns, "CURRENCY", "$#,##0.00"),
            (datetime_cols, "DATE", "yyyy-mm-dd hh:mm:ss Z"),
        ):
            for start_col, end_col in self._column_ranges(cols, columns):
                requests.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": 1,
                                "endRowIndex": end_row_idx,
                                "startColumnIndex": start_col,
                                "endColumnIndex": end_col,
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "numberFormat": {
                                        "type": col_type,
                                        "pattern": pattern,
                                    }
                                }
                            },
                            "fields": "userEnteredFormat.numberFormat",
                        },
                    }
                )
        for col in columns:
            set_values_format(col, h_align="CENTER")

        ## SET VALUE COLORS
        for col in numeric_cols + datetime_cols:
            col_idx = columns.index(col)
            requests.append(
                {
                    "addConditionalFormatRule": {
                        "rule": {
                            "ranges": [
                                {
                                    "sheetId": sheet_id,
                                    "startColumnIndex": col_idx,
                                    "endColumnIndex": col_idx + 1,
                                }
                            ],
                            "gradientRule": {
                                "minpoint": {
                                    "color": asdict(white),
                                    "type": "MIN",
                                },
                                "maxpoint": {"color": asdict(orange), "type": "MAX"},
                            },
                        },
                        "index": 0,
                    }
                }
            )
        # auto resize column widths.
        requests.append(
            {
                "autoResizeDimensions": {
                    "dimensions": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": 0,
                        "endIndex": len(columns),
                    }
                }
            }
        )
        # freeze first row.
        grid_props = {"frozenRowCount": 1}
        fields = "gridProperties.frozenRowCount"
        if has_index:
            # freeze first column.
            grid_props["frozenColumnCount"] = 1
            fields += ",gridProperties.frozenColumnCount"
        requests.append(
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": grid_props,
                    },
                    "fields": fields,
                }
            }
        )
        # execute requests.
        spreadsheet.batch_update({"requests": requests})

    def create_line_plot(
        self,
        df: pd.DataFrame,
        chart_lines: Sequence[ChartLine],
        spreadsheet: Spreadsheet,
        worksheet: Worksheet,
        title: str,
        left_axis: str,
        bottom_axis: str,
        delete_plots: bool = True,
    ):
        logger.info("Creating line plot.")
        columns = df.columns.values.tolist()
        sheet_id = worksheet.id
        end_row_idx = len(df)
        domain = {c.x for c in chart_lines}
        assert len(domain) == 1
        domain_sources = [
            {
                "startRowIndex": 1,
                "endRowIndex": end_row_idx,
                "startColumnIndex": start_idx,
                "endColumnIndex": end_idx,
                "sheetId": sheet_id,
            }
            for start_idx, end_idx in self._column_ranges(
                col_names=list(domain), columns=columns
            )
        ]
        series_sources = [
            {
                "startRowIndex": 1,
                "endRowIndex": end_row_idx,
                "startColumnIndex": start_idx,
                "endColumnIndex": end_idx,
                "sheetId": sheet_id,
            }
            for c in chart_lines
            for start_idx, end_idx in self._column_ranges(
                col_names=[c.y], columns=columns
            )
        ]

        def axis(axis_name: str, position: Literal["left", "bottom"]):
            return {
                "position": f"{position.upper()}_AXIS",
                "title": axis_name,
                "format": {
                    "fontSize": 14,
                    "bold": True,
                    "italic": False,
                },
            }

        requests = [
            {
                "addChart": {
                    "chart": {
                        "spec": {
                            "title": title,
                            "altText": "ALT text",
                            # "titleTextFormat": {object(TextFormat)},
                            "titleTextPosition": {"horizontalAlignment": "CENTER"},
                            "basicChart": {
                                "chartType": "LINE",
                                "legendPosition": "RIGHT_LEGEND",
                                "domains": [
                                    {
                                        "domain": {
                                            "sourceRange": {
                                                "sources": domain_sources,
                                            }
                                        }
                                    }
                                ],
                                "series": [
                                    {
                                        "series": {
                                            "sourceRange": {
                                                "sources": ss,
                                            }
                                        },
                                        # "dataLabel": {},
                                    }
                                    for ss in series_sources
                                ],
                                # https://developers.google.com/sheets/api/reference/rest/v4/spreadsheets/charts#basicchartaxis
                                "axis": [
                                    axis(bottom_axis, "bottom"),
                                    axis(left_axis, "left"),
                                ],
                            },
                        },
                        # place at top of sheet to the right of data.
                        "position": {
                            "overlayPosition": {
                                "anchorCell": {
                                    "sheetId": sheet_id,
                                    "rowIndex": 2,
                                    "columnIndex": len(columns) - 1,
                                },
                                "offsetXPixels": 700,
                                "offsetYPixels": 0,
                                "widthPixels": 800,
                                "heightPixels": 600,
                            }
                        },
                    }
                }
            }
        ]
        if delete_plots:
            pass
            # worksheet.charts()
            # ws_chart_ids = self._worksheet_chart_ids(spreadsheet)
            # for cid in ws_chart_ids[worksheet.id]:
            #    requests.append({"deleteEmbeddedObject": {"objectId": cid}})

        spreadsheet.batch_update({"requests": requests})

    @cached_property
    def gspread_client(self):
        if self.srv_acct_file:
            return gspread.service_account(filename=self.srv_acct_file)
        return gspread.service_account()

    def get_spreadsheet(self, spreadsheet: str) -> Spreadsheet:
        if spreadsheet in self.spreadsheets:
            return self.spreadsheets[spreadsheet]
        try:
            sheet = self.gspread_client.open(
                spreadsheet, folder_id=self.gdrive_folder_id
            )
            logger.info(f"Using existing spreadsheet: {spreadsheet}")
        except gspread.exceptions.SpreadsheetNotFound:
            logger.info(f"Creating new spreadsheet: {spreadsheet}")
            sheet = self.gspread_client.create(
                spreadsheet, folder_id=self.gdrive_folder_id
            )
        self.spreadsheets[spreadsheet] = sheet
        return sheet


    def get_worksheets(self, spreadsheet: str) -> Dict[str, Worksheet]:
        spreadsheet = self.get_spreadsheet(spreadsheet)
        return {ws.title: ws for ws in spreadsheet.worksheets()}

    def get_worksheet(
        self, spreadsheet: str, worksheet: str, rows=1000, cols=26
    ) -> Worksheet:
        spreadsheet = self.get_spreadsheet(spreadsheet)
        try:
            # Try to get the worksheet by its name.
            return spreadsheet.worksheet(worksheet)
        except gspread.exceptions.WorksheetNotFound:
            # If not found, create a new one
            logger.info(f"Creating new worksheet: {worksheet}")
            return spreadsheet.add_worksheet(title=worksheet, rows=rows, cols=cols)

    def _column_ranges(
        self, col_names: Sequence[str], columns: Sequence[str]
    ) -> List[Tuple[int, int]]:
        """Get index ranges of `col_names` in `columns`."""
        if (not columns) or (not col_names):
            return []
        col_idxs = sorted([columns.index(c) for c in col_names])
        ranges = []
        start = col_idx = col_idxs[0]
        for prev, col_idx in enumerate(col_idxs[1:]):
            prev_col_idx = col_idxs[prev]
            if col_idx > (prev_col_idx + 1):
                ranges.append((start, prev_col_idx + 1))
                start = col_idx
        ranges.append((start, col_idx + 1))
        return ranges

    def _worksheet_chart_ids(
        self, sheet: Spreadsheet
    ) -> Dict[Worksheet, List[Dict[str, Any]]]:
        resp = self.gspread_client.request(
            "get",
            f"https://sheets.googleapis.com/v4/spreadsheets/{sheet.id}?fields=sheets%2Fcharts%2FchartId",
        )
        data = resp.json()
        chart_ids = [
            [chart["chartId"] for chart in s.get("charts", [])] for s in data["sheets"]
        ]
        ws_ids = [ws.id for ws in sheet.worksheets()]
        return dict(zip(ws_ids, chart_ids))

    def _format_column_name(self, column: str):
        for unit, symbol in (("pct", "%"), ("dollars", "$")):
            column = re.sub(f"_{unit}$", f"({symbol})", column)
            column = re.sub(
                r"(^|[^a-zA-Z])" + unit + r"($|[^a-zA-Z])",
                lambda m: m.group(1) + symbol + m.group(2),
                column,
            )
        for unit in ("hours", "mins"):
            column = re.sub(f"_{unit}$", f"\n({unit})", column)
        return column.replace("_", " ").title().replace("Pnl", "PnL")
