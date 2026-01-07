import csv
import pickle
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime
from enum import Enum, auto
from io import StringIO
from typing import Any, Dict
from typing import List as ListType
from typing import Literal, Optional, Sequence, Tuple, Union

from dominate import tags as d
from prettytable import PrettyTable
from rich.box import ROUNDED
from rich.columns import Columns
from rich.console import Console
from rich.json import JSON as RichJSON
from rich.panel import Panel
from rich.table import Table as RichTable
from rich.text import Text as RichText
from rich.tree import Tree
from xxhash import xxh32

from .utils import AttachmentFile, as_code_block


class FontSize(Enum):
    SMALL = auto()
    MEDIUM = auto()
    LARGE = auto()


class ContentType(Enum):
    IMPORTANT = auto()
    INFO = auto()
    WARNING = auto()
    ERROR = auto()


def level_css_color(level: ContentType, theme: str = "dark") -> str:
    """Get an appropriate CSS color for a given `ContentType` and theme."""
    colors = get_theme_colors(theme)
    level_map = {
        ContentType.INFO: colors["info"],
        ContentType.WARNING: colors["warning"],
        ContentType.ERROR: colors["error"],
        ContentType.IMPORTANT: colors["important"],
    }
    return level_map.get(level, colors["info"])


def font_size_css(font_size: FontSize) -> str:
    """Get an appropriate CSS font size for a given `FontSize`."""
    fonts = {
        FontSize.SMALL: "16px",
        FontSize.MEDIUM: "18px",
        FontSize.LARGE: "20px",
    }
    return fonts.get(font_size, fonts[FontSize.MEDIUM])


def get_theme_colors(theme: str = "dark") -> dict:
    """Get theme-specific colors for backgrounds and text."""
    if theme == "light":
        return {
            "page_bg": "#ffffff",
            "container_bg": "#f9fafb",
            "text_primary": "#111827",
            "text_secondary": "#4b5563",
            "border": "#e5e7eb",
            "code_bg": "#f3f4f6",
            "accent": "#2563EB",
            # Content type colors
            "info": "#059669",
            "warning": "#D97706",
            "error": "#DC2626",
            "important": "#2563EB",
            # Status colors
            "success": "#059669",
            "neutral": "#6B7280",
            # Additional colors
            "table_alt_row": "#e5e7eb",
            "card_border": "#E5E7EB",
        }
    else:  # dark theme
        return {
            "page_bg": "#f9fafb",
            "container_bg": "#2a2a2a",
            "text_primary": "#f9fafb",
            "text_secondary": "#9ca3af",
            "border": "#4b5563",
            "code_bg": "#1a1a1a",
            "accent": "#B4EC51",
            # Content type colors
            "info": "#B4EC51",
            "warning": "#FF8C00",
            "error": "#DC2626",
            "important": "#60A5FA",
            # Status colors
            "success": "#10B981",
            "neutral": "#9CA3AF",
            # Additional colors
            "table_alt_row": "#333333",
            "card_border": "#4b5563",
        }


class Component(ABC):
    """A structured component of a message."""

    @abstractmethod
    def html(self, theme: str = "dark") -> d.html_tag:
        """Render the component's content as a `dominate` HTML element.

        Returns:
            d.html_tag: The HTML element with text.
        """
        pass

    def md(self, slack_format: bool = False, discord_format: bool = False) -> str:
        """Render the component's content as Markdown.

        Args:
            slack_format (bool): Use Slack's subset of Markdown features.
            discord_format (bool): Use Discord's markdown features.

        Returns:
            str: The rendered Markdown.
        """
        if discord_format:
            return self.discord_md()
        elif slack_format:
            return self.slack_md()
        return self.classic_md()

    @abstractmethod
    def classic_md(self) -> str:
        """Render the component's content as traditional Markdown.

        Returns:
            str: The rendered Markdown.
        """
        pass

    @abstractmethod
    def slack_md(self) -> str:
        """Render the component's content using Slack's subset of Markdown features.

        Returns:
            str: The rendered Markdown.
        """
        pass

    @abstractmethod
    def discord_md(self) -> str:
        """Render the component's content using Discord's markdown features.

        Returns:
            str: The rendered Markdown.
        """
        pass

    @abstractmethod
    def console(self, console: Optional[Console] = None) -> None:
        """Render the component to the console using Rich.

        Args:
            console (Optional[Console]): The Rich console to use. If None, creates a new one.
        """
        pass


class Text(Component):
    """A component that displays formatted text."""

    _content_tags = {
        ContentType.INFO: d.div,
        ContentType.WARNING: d.p,
        ContentType.ERROR: d.h2,
        ContentType.IMPORTANT: d.h1,
    }

    def __init__(
        self,
        value: str,
        level: ContentType = ContentType.INFO,
        font_size: FontSize = FontSize.MEDIUM,
        max_length: Optional[int] = None,
        preview_suffix: str = "... (see attachment for full message)",
    ):
        """
        Args:
            content (str): The text that should be displayed in the component.
            level (ContentType, optional): Type of text. Defaults to ContentType.INFO.
            font_size (FontSize, optional): Size of font. Defaults to FontSize.MEDIUM.
            max_length (Optional[int], optional): Maximum length before creating attachment. Defaults to None.
            preview_suffix (str, optional): Text to append when message is truncated. Defaults to "... (see attachment for full message)".
        """
        self.original_value = str(value)
        self.level = level
        self.font_size = font_size
        self.max_length = max_length
        self.preview_suffix = preview_suffix
        self._attachment_info: Optional[Tuple[str, StringIO]] = None

        # Handle message truncation and attachment creation
        if max_length and len(self.original_value) > max_length:
            # Create preview text
            truncate_at = max_length - len(self.preview_suffix)
            self.value = self.original_value[:truncate_at] + self.preview_suffix
            # Create attachment will be called by the parent when needed
        else:
            self.value = self.original_value

    def create_attachment_if_needed(self) -> Optional[Tuple[str, StringIO]]:
        """Create a text file attachment if the message was truncated.

        Returns:
            Optional[Tuple[str, StringIO]]: Filename and file object if attachment created, None otherwise.
        """
        if self._attachment_info:
            return self._attachment_info

        if self.max_length and len(self.original_value) > self.max_length:
            # Generate filename based on content type and hash
            content_type_name = self.level.name.lower()
            content_hash = xxh32(self.original_value.encode()).hexdigest()[:8]
            filename = f"{content_type_name}_message_{content_hash}.txt"

            # Create file content
            file_obj = StringIO()
            file_obj.write(self.original_value)
            file_obj.seek(0)

            self._attachment_info = (filename, file_obj)
            return self._attachment_info
        return None

    def html(self, theme: str = "dark") -> d.html_tag:
        tag = self._content_tags[self.level]
        return tag(
            self.value,
            style=f"font-size:{font_size_css(self.font_size)};color:{level_css_color(self.level, theme)};",
        )

    def classic_md(self) -> str:
        # Use consistent heading levels based on font size and content type
        if self.level == ContentType.ERROR:
            return f"## **{self.value}**"
        elif self.level == ContentType.IMPORTANT or self.font_size == FontSize.LARGE:
            return f"## {self.value}"
        elif self.level == ContentType.WARNING:
            return f"#### *{self.value}*"
        elif self.font_size == FontSize.MEDIUM:
            return f"#### {self.value}"
        else:
            return self.value

    def slack_md(self) -> str:
        # slack is a bit disabled.
        if self.level in (ContentType.IMPORTANT, ContentType.ERROR):
            return f"*{self.value}*"
        return self.value

    def discord_md(self) -> str:
        # Simplified logic: prioritize content type over font size
        return self.classic_md()

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        # Enhanced Rich markup with emoji support
        text = RichText()

        # Add emoji based on content type
        emoji_map = {
            ContentType.INFO: "ℹ️ ",
            ContentType.WARNING: "⚠️ ",
            ContentType.ERROR: "❌ ",
            ContentType.IMPORTANT: "⭐ ",
        }

        if self.level in emoji_map:
            text.append(emoji_map[self.level])

        # Apply font size styling
        if self.font_size == FontSize.LARGE:
            text.append(self.value, style="bold bright_white")
        elif self.font_size == FontSize.SMALL:
            text.append(self.value, style="dim")
        else:
            text.append(self.value)

        # Apply content type coloring
        style_map = {
            ContentType.INFO: "bright_blue",
            ContentType.WARNING: "bright_yellow",
            ContentType.ERROR: "bright_red",
            ContentType.IMPORTANT: "bright_magenta",
        }

        final_style = style_map.get(self.level, "default")
        console.print(text, style=final_style)


class Map(Component):
    """A component that displays formatted key/value pairs."""

    def __init__(
        self,
        data: Dict[str, Any],
        inline: Union[bool, Literal["yes", "no", "auto"]] = "auto",
        length_threshold: int = 80,
    ):
        """
        Args:
            data (Dict[str, Any]): The key/value pairs that should be displayed.
            inline (Union[bool, Literal["yes", "no", "auto"]], optional):
                Whether to display inline. Can be:
                - True or "yes": Always inline
                - False or "no": Never inline (vertical format)
                - "auto": Automatically decide based on total length
                Defaults to "auto".
            length_threshold (int, optional): Character threshold for auto-inline decision.
                If total length of all key-value pairs is less than this, display inline.
                Defaults to 80.
        """
        self.data = data
        self.length_threshold = length_threshold

        # Normalize inline parameter
        if inline is True or inline == "yes":
            self._should_inline = True
        elif inline is False or inline == "no":
            self._should_inline = False
        else:  # "auto"
            # Calculate total length of key-value pairs
            total_length = sum(
                len(str(k)) + len(str(v)) + 4  # +4 for ": " and spacing
                for k, v in data.items()
            )
            # Add separator length: " | " between items
            if len(data) > 1:
                total_length += (len(data) - 1) * 3

            # Decide based on threshold
            self._should_inline = total_length <= length_threshold

        self.inline = self._should_inline

    def html(self, theme: str = "dark") -> d.html_tag:
        colors = get_theme_colors(theme)
        key_color = colors["accent"]
        value_color = colors["text_primary"]

        with (container := d.div()):
            if self.inline:
                # Inline format with | separator
                for i, (k, v) in enumerate(self.data.items()):
                    if i > 0:
                        d.span(
                            " | ",
                            style=f"font-size:{font_size_css(FontSize.LARGE)};color:{get_theme_colors(theme)['text_secondary']};margin:0 8px;",
                        )
                    d.span(
                        f"{k}: ",
                        style=f"font-weight:bold;font-size:{font_size_css(FontSize.LARGE)};color:{key_color};",
                    )
                    d.span(
                        str(v),
                        style=f"font-size:{font_size_css(FontSize.LARGE)};color:{value_color};",
                    )
            else:
                # Vertical format
                for k, v in self.data.items():
                    with d.div(style="margin-bottom:5px;"):
                        d.span(
                            f"{k}: ",
                            style=f"font-weight:bold;font-size:{font_size_css(FontSize.LARGE)};color:{key_color};",
                        )
                        d.span(
                            str(v),
                            style=f"font-size:{font_size_css(FontSize.LARGE)};color:{value_color};",
                        )
        return container

    def classic_md(self) -> str:
        if self.inline:
            # Inline format with | separator
            return " | ".join([f"**{k}:** {v}" for k, v in self.data.items()])
        else:
            # Table format
            rows = ["|||", "|---:|:---|"]
            for k, v in self.data.items():
                rows.append(f"|**{k}:**|{v}|")
            rows.append("|||")
            return "\n".join(rows)

    def slack_md(self) -> str:
        if self.inline:
            return " | ".join([f"*{k}:* {v}" for k, v in self.data.items()])
        else:
            return "\n".join([f"*{k}:* {v}" for k, v in self.data.items()])

    def discord_md(self) -> str:
        if self.inline:
            return " | ".join([f"**{k}:** {v}" for k, v in self.data.items()])
        else:
            return "\n".join([f"**{k}:** {v}" for k, v in self.data.items()])

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        # Use Rich Columns for better layout
        accent_color = get_theme_colors("dark")["accent"]

        if self.inline:
            # Use Rich Columns for inline display
            items = []
            for k, v in self.data.items():
                item_text = RichText()
                item_text.append(f"{k}: ", style=f"bold {accent_color}")
                item_text.append(str(v), style="default")
                items.append(Panel(item_text, expand=False, padding=(0, 1)))

            columns = Columns(items, equal=True, expand=True)
            console.print(columns)
        else:
            # Use Panel for vertical format with better spacing
            content = RichText()
            for i, (k, v) in enumerate(self.data.items()):
                if i > 0:
                    content.append("\n")
                content.append(f"{k}: ", style=f"bold {accent_color}")
                content.append(str(v), style="default")

            panel = Panel(
                content, title="Data", border_style=accent_color, padding=(1, 2)
            )
            console.print(panel)


class Table(Component):
    """A component that displays tabular data."""

    def __init__(
        self,
        rows: Sequence[Dict[str, Any]],
        title: Optional[str] = None,
        columns: Optional[Sequence[str]] = None,
    ):
        """
        Args:
            rows (Sequence[Dict[str, Any]]): Iterable of row dicts (column: value).
            title (Optional[str], optional): A title to display above the table body. Defaults to None.
            columns (Optional[Sequence[str]], optional): A list of column names. Defaults to None (will be inferred from body rows).
        """
        self.rows = [{k: str(v) for k, v in row.items()} for row in rows]
        self.title = (
            Text(title, ContentType.IMPORTANT, FontSize.LARGE) if title else None
        )
        self.columns = (
            list(dict.fromkeys([c for row in self.rows for c in row.keys()]))
            if columns is None
            else columns
        )
        self._attachment: Map = None

    def attach_rows_as_file(self, filename_stem_max_length=100) -> AttachmentFile:
        """Create a CSV file containing the table rows.

        Returns:
            AttachmentFile: Attachment file object containing the CSV data.
        """
        stem = (
            self.title.value[:filename_stem_max_length].replace(" ", "_")
            if self.title
            else "table"
        )
        rows_id = xxh32(pickle.dumps(self.rows)).hexdigest()
        filename = f"{stem}_{rows_id}.csv"
        file = StringIO()
        writer = csv.DictWriter(file, fieldnames=self.columns)
        writer.writeheader()
        writer.writerows(self.rows)
        file.seek(0)

        # Create AttachmentFile object
        attachment_file = AttachmentFile(content=file, filename=filename)

        self._attachment = Map({"Attachment": filename})
        # Don't render rows now that they're attached in a file.
        self.rows = None
        return attachment_file

    def html(self, theme: str = "dark"):
        with (container := d.div()):
            if self.title:
                d.h1(
                    self.title.value,
                    style=f"color: {get_theme_colors(theme)['accent']};",
                )
            if self._attachment:
                self._attachment.html()
            if self.rows:
                with d.div():
                    with d.table(
                        style=f"font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; font-size: 13px; border-collapse: collapse; table-layout: auto; margin: 0; background-color: {get_theme_colors(theme)['code_bg']}; border: 2px solid {get_theme_colors(theme)['accent']};"
                    ):
                        # Header row
                        with d.tr():
                            for column in self.columns:
                                d.th(
                                    column,
                                    style=f"border: 1px solid {get_theme_colors(theme)['accent']}; padding: 0.5em; text-align: center; vertical-align: middle; white-space: nowrap; background-color: {get_theme_colors(theme)['accent']}; font-weight: bold; font-size: 14px; color: {get_theme_colors(theme)['container_bg']};",
                                )
                        # Data rows
                        for i, row in enumerate(self.rows):
                            colors = get_theme_colors(theme)
                            row_bg = (
                                colors["code_bg"]
                                if i % 2 == 0
                                else colors["table_alt_row"]
                            )
                            with d.tr(style=f"background-color: {row_bg};"):
                                for column in self.columns:
                                    d.td(
                                        row.get(column, ""),
                                        style=f"border: 1px solid {get_theme_colors(theme)['accent']}; padding: 0.33em 0.5em 0.33em 0.5em; text-align: center; vertical-align: middle; white-space: nowrap; color: {get_theme_colors(theme)['accent']};",
                                    )
        return container

    def classic_md(self) -> str:
        data = []
        if self.title:
            data.append(self.title.classic_md())
        if self._attachment:
            data.append(self._attachment.classic_md())
        if self.rows:
            table_rows = [
                self.columns,
                [":----:" for _ in range(len(self.columns))],
            ] + [[row[col] for col in self.columns] for row in self.rows]
            data.append("\n".join(["|".join(row) for row in table_rows]))
        return "\n\n".join(data).strip()

    def slack_md(self, float_format: str = ".3") -> str:
        if not self.rows:
            return ""
        columns = defaultdict(list)
        for row in self.rows:
            for k, v in row.items():
                columns[k].append(v)
        # Slack can't render very many rows in a single table.
        max_rows = 15
        table_slices = defaultdict(PrettyTable)
        for column, values in columns.items():
            for i in range(0, len(values), max_rows):
                table = table_slices[i]
                table.add_column(column, values[i : i + max_rows])
        data = []
        if self.title:
            data.append(table_slices.pop(0).get_string(title=self.title.value))
        for table in table_slices.values():
            if float_format:
                table.float_format = float_format
            data.append(table.get_string())
        data = [as_code_block(d) for d in data]
        if self._attachment:
            data.append(self._attachment.slack_md())
        return "\n\n".join(data).strip()

    def discord_md(self) -> str:
        """Render table as Discord markdown with proper formatting."""
        data = []
        if self.title:
            data.append(self.title.discord_md())
        if self._attachment:
            data.append(self._attachment.discord_md())
        if self.rows:
            # Discord supports proper markdown tables
            table_rows = [
                "|" + "|".join(self.columns) + "|",
                "|" + "|".join([":---:" for _ in self.columns]) + "|",
            ]
            for row in self.rows:
                table_rows.append(
                    "|"
                    + "|".join([str(row.get(col, "")) for col in self.columns])
                    + "|"
                )
            data.append("\n".join(table_rows))
        return "\n\n".join(data).strip()

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        if self._attachment:
            self._attachment.console(console)

        if self.rows:
            accent_color = get_theme_colors("dark")["accent"]

            # Enhanced table with better styling
            table = RichTable(
                show_header=True,
                header_style=f"bold {accent_color}",
                box=ROUNDED,  # Use rounded box style
                row_styles=["none"],  # Single light row style
                title_style=f"bold {accent_color}",
                border_style=accent_color,
            )

            # Set the title
            if self.title:
                table.title = self.title.value
                table.title_justify = "center"

            # Add columns with better justification
            for column in self.columns:
                # Numeric columns right-aligned, others left-aligned
                justify = (
                    "right"
                    if any(
                        str(row.get(column, ""))
                        .replace(".", "")
                        .replace(",", "")
                        .replace("-", "")
                        .isdigit()
                        for row in self.rows
                    )
                    else "left"
                )
                table.add_column(column, justify=justify)

            # Add rows with enhanced formatting
            for row in self.rows:
                formatted_row = []
                for col in self.columns:
                    value = str(row.get(col, ""))
                    # Highlight numeric values
                    if (
                        value.replace(".", "")
                        .replace(",", "")
                        .replace("-", "")
                        .isdigit()
                    ):
                        value = f"[bright_cyan]{value}[/bright_cyan]"
                    formatted_row.append(value)
                table.add_row(*formatted_row)

            console.print(table)


class List(Component):
    """A component that displays a list of text strings as bullet points."""

    def __init__(self, items: Sequence[str], ordered: bool = False):
        """
        Args:
            items (Sequence[str]): The list of text strings to display.
            ordered (bool, optional): Whether to use ordered (numbered) list. Defaults to False (bullet points).
        """
        self.items = [str(item) for item in items]
        self.ordered = ordered

    def html(self, _theme: str = "dark") -> d.html_tag:
        list_tag = d.ol if self.ordered else d.ul
        with (container := list_tag()):
            for item in self.items:
                d.li(item)
        return container

    def classic_md(self) -> str:
        if self.ordered:
            return "\n".join([f"{i+1}. {item}" for i, item in enumerate(self.items)])
        else:
            return "\n".join([f"- {item}" for item in self.items])

    def slack_md(self) -> str:
        # Slack supports bullet points with •
        if self.ordered:
            return "\n".join([f"{i+1}. {item}" for i, item in enumerate(self.items)])
        else:
            return "\n".join([f"• {item}" for item in self.items])

    def discord_md(self) -> str:
        # Discord supports standard markdown lists
        if self.ordered:
            return "\n".join([f"{i+1}. {item}" for i, item in enumerate(self.items)])
        else:
            return "\n".join([f"- {item}" for item in self.items])

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        # Enhanced list display with Tree structure for better hierarchy
        accent_color = get_theme_colors("dark")["accent"]

        if len(self.items) > 5:  # Use Tree for longer lists
            tree = Tree("List Items", style=accent_color)
            for i, item in enumerate(self.items):
                if self.ordered:
                    tree.add(f"[bold]{i+1}.[/bold] {item}")
                else:
                    tree.add(item)
            console.print(tree)
        else:  # Use enhanced bullets for shorter lists
            lines = []
            for i, item in enumerate(self.items):
                if self.ordered:
                    lines.append(
                        f"[bold {accent_color}]{i+1}.[/bold {accent_color}] [bright_white]{item}[/bright_white]"
                    )
                else:
                    lines.append(
                        f"[{accent_color}]•[/{accent_color}] [bright_white]{item}[/bright_white]"
                    )

            # Wrap in a subtle panel
            content = "\n".join(lines)
            panel = Panel(
                content,
                border_style="dim",
                padding=(1, 2),
            )
            console.print(panel)


class LineBreak(Component):
    """A line beak (to be inserted between components)."""

    def __init__(self, n_break: int = 1) -> None:
        self.n_break = n_break

    def html(self, _theme: str = "dark") -> d.html_tag:
        with (container := d.div()):
            for _ in range(self.n_break):
                d.br()
        return container

    def classic_md(self) -> str:
        return "".join(["\n" for _ in range(self.n_break)])

    def slack_md(self) -> str:
        return self.classic_md()

    def discord_md(self) -> str:
        return self.classic_md()

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        # Just print newlines
        for _ in range(self.n_break):
            console.print()


class Divider(Component):
    """A divider component for visual separation."""

    def __init__(self, text: Optional[str] = None, style: str = "solid"):
        """
        Args:
            text (Optional[str], optional): Optional text to display in the divider. Defaults to None.
            style (str, optional): Line style (solid, dashed, dotted). Defaults to "solid".
        """
        self.text = text
        self.style = style

    def html(self, theme: str = "dark") -> d.html_tag:
        border_style = {"solid": "solid", "dashed": "dashed", "dotted": "dotted"}.get(
            self.style, "solid"
        )

        if self.text:
            with (
                container := d.div(
                    style="display: flex; align-items: center; margin: 24px 0;"
                )
            ):
                d.div(
                    style=f"flex: 1; height: 1px; background-color: {get_theme_colors(theme)['border']}; border-top: 1px {border_style} {get_theme_colors(theme)['border']};"
                )
                d.div(
                    self.text,
                    style=f"margin: 0 16px; color: {get_theme_colors(theme)['text_secondary']}; font-size: 14px; font-weight: 500;",
                )
                d.div(
                    style=f"flex: 1; height: 1px; background-color: {get_theme_colors(theme)['border']}; border-top: 1px {border_style} {get_theme_colors(theme)['border']};"
                )
        else:
            with (
                container := d.div(
                    style=f"margin: 24px 0; height: 1px; background-color: {get_theme_colors(theme)['border']}; border-top: 1px {border_style} {get_theme_colors(theme)['border']};"
                )
            ):
                pass
        return container

    def classic_md(self) -> str:
        if self.text:
            return f"--- {self.text} ---"
        else:
            return "---"

    def slack_md(self) -> str:
        if self.text:
            return f"─ {self.text} ─"
        else:
            return "─" * 20

    def discord_md(self) -> str:
        if self.text:
            return f"─ {self.text} ─"
        else:
            return "─" * 20

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        from rich.rule import Rule

        # Create a rule (horizontal line)
        accent_color = get_theme_colors("dark")["accent"]
        if self.text:
            rule = Rule(self.text, style=accent_color)
        else:
            rule = Rule(style=accent_color)

        console.print(rule)


class Image(Component):
    """A component that displays images."""

    def __init__(
        self,
        src: str,
        alt: str = "",
        width: Optional[int] = None,
        height: Optional[int] = None,
    ):
        """
        Args:
            src (str): The image source URL or base64 data.
            alt (str, optional): Alt text for the image. Defaults to "".
            width (Optional[int], optional): Image width in pixels. Defaults to None.
            height (Optional[int], optional): Image height in pixels. Defaults to None.
        """
        self.src = src
        self.alt = alt
        self.width = width
        self.height = height

    def html(self, _theme: str = "dark") -> d.html_tag:
        style_parts = []
        if self.width:
            style_parts.append(f"max-width:{self.width}px;width:100%;")
        if self.height:
            style_parts.append(f"height:{self.height}px;object-fit:cover;")

        # Add basic styling for email compatibility
        style_parts.extend(
            ["border-radius: 4px;", "box-shadow: 0 2px 4px rgba(0,0,0,0.1);"]
        )

        style = ";".join(style_parts) if style_parts else None

        return d.img(
            src=self.src,
            alt=self.alt or "Image",
            style=style,
            title=self.alt or "Image",
        )

    def classic_md(self) -> str:
        return f"![{self.alt}]({self.src})"

    def slack_md(self) -> str:
        # Slack doesn't support inline images in markdown, just show the URL
        return self.src

    def discord_md(self) -> str:
        return f"![{self.alt}]({self.src})"

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        # For console, just show the alt text and URL
        accent_color = get_theme_colors("dark")["accent"]
        console.print(
            f"[{accent_color}]Image:[/{accent_color}] {self.alt or 'No description'}"
        )
        console.print(f"    [dim]{self.src}[/dim]")


class Timeline(Component):
    """A component that displays chronological events."""

    def __init__(self, events: Sequence[Dict[str, Any]]):
        """
        Args:
            events (Sequence[Dict[str, Any]]): List of events with 'time', 'title', and optional 'description'.
        """
        self.events = events

    def html(self, theme: str = "dark") -> d.html_tag:
        with (container := d.div(style="position: relative; padding-left: 32px;")):
            # Timeline line
            d.div(
                style=f"position: absolute; left: 16px; top: 0; bottom: 0; width: 2px; background: linear-gradient(to bottom, {get_theme_colors(theme)['accent']}, {get_theme_colors(theme)['accent']});"
            )

            for event in self.events:
                with d.div(style="position: relative; margin-bottom: 24px;"):
                    # Timeline dot
                    d.div(
                        style=f"""
                            position: absolute;
                            left: -24px;
                            top: 4px;
                            width: 12px;
                            height: 12px;
                            background-color: {get_theme_colors(theme)['accent']};
                            border-radius: 50%;
                            border: 3px solid white;
                            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                        """
                    )

                    # Event content
                    with d.div(
                        style=f"background-color: {get_theme_colors(theme)['code_bg']}; padding: 16px; border-radius: 8px; border: 1px solid {get_theme_colors(theme)['border']}; box-shadow: 0 1px 3px rgba(0,0,0,0.1);"
                    ):
                        d.div(
                            event.get("time", ""),
                            style=f"color: {get_theme_colors(theme)['text_secondary']}; font-size: 14px; font-weight: 500; margin-bottom: 4px;",
                        )
                        d.div(
                            event.get("title", ""),
                            style=f"font-weight: 600; font-size: 16px; color: {get_theme_colors(theme)['accent']}; margin-bottom: 8px;",
                        )
                        if "description" in event:
                            d.div(
                                event["description"],
                                style=f"color: {get_theme_colors(theme)['text_primary']}; line-height: 1.5;",
                            )
        return container

    def classic_md(self) -> str:
        lines = []
        for event in self.events:
            lines.append(f"**{event.get('time', '')}** - {event.get('title', '')}")
            if "description" in event:
                lines.append(f"  {event['description']}")
            lines.append("")
        return "\n".join(lines).strip()

    def slack_md(self) -> str:
        return self.classic_md()

    def discord_md(self) -> str:
        return self.classic_md()

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        # Enhanced timeline with Rich Tree structure
        accent_color = get_theme_colors("dark")["accent"]

        tree = Tree("Timeline", style=f"bold {accent_color}")

        for event in self.events:
            time_info = event.get("time", "")
            title_info = event.get("title", "")

            # Create main event node with enhanced styling
            event_text = RichText()
            event_text.append(f"{time_info} ", style=f"dim {accent_color}")
            event_text.append(title_info, style="bold bright_white")

            event_node = tree.add(event_text)

            # Add description as child if present
            if "description" in event:
                description_text = RichText(event["description"], style="italic dim")
                event_node.add(description_text)

        console.print(tree)


class Badge(Component):
    """A component that displays small labels for status or categories."""

    def __init__(
        self,
        text: str,
        color: Optional[str] = None,
        background_color: Optional[str] = None,
    ):
        """
        Args:
            text (str): The text to display in the badge.
            color (str, optional): Text color. Defaults to theme important color.
            background_color (str, optional): Background color. Defaults to light variant.
        """
        self.text = text
        self.color = color
        self.background_color = background_color

    def html(self, theme: str = "dark") -> d.html_tag:
        colors = get_theme_colors(theme)
        text_color = self.color or colors["important"]
        bg_color = self.background_color or (
            "#EFF6FF" if theme == "light" else "#1E3A8A"
        )

        return d.span(
            self.text,
            style=f"""
                display: inline-block;
                padding: 4px 12px;
                background-color: {bg_color};
                color: {text_color};
                border-radius: 16px;
                font-size: 12px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                border: 1px solid {text_color}20;
                box-shadow: 0 1px 2px rgba(0,0,0,0.1);
            """,
        )

    def classic_md(self) -> str:
        return f"`{self.text}`"

    def slack_md(self) -> str:
        return f"[{self.text}]"

    def discord_md(self) -> str:
        return f"`{self.text}`"

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        # Create a styled badge
        console.print(
            f"[{self.color} on {self.background_color}] {self.text.upper()} [/{self.color} on {self.background_color}]"
        )


class StatusIndicator(Component):
    """A component that displays status with colored indicators."""

    def __init__(self, status: str, color: str = "green", show_icon: bool = True):
        """
        Args:
            status (str): The status text to display.
            color (str, optional): Color for the indicator. Defaults to "green".
            show_icon (bool, optional): Whether to show a status icon. Defaults to True.
        """
        self.status = status
        self.color = color
        self.show_icon = show_icon

    def _get_color_hex(self, color: str, theme: str = "dark") -> str:
        """Convert color name to hex."""
        colors = get_theme_colors(theme)
        color_map = {
            "green": colors["success"],
            "red": colors["error"],
            "yellow": colors["warning"],
            "blue": colors["important"],
            "orange": "#EA580C" if theme == "light" else "#FB923C",
            "gray": colors["neutral"],
        }
        return color_map.get(color.lower(), color)

    def _get_icon(self, color: str) -> str:
        """Get appropriate icon for color."""
        icon_map = {
            "green": "✓",  # Checkmark for success
            "red": "✗",  # X for error/failure
            "yellow": "⚠",  # Warning triangle
            "blue": "ℹ",  # Info circle
            "orange": "⚡",  # Lightning for urgent
            "gray": "●",  # Dot for neutral
        }
        return icon_map.get(color.lower(), "●")

    def html(self, theme: str = "dark") -> d.html_tag:
        color_hex = self._get_color_hex(self.color, theme)
        icon = self._get_icon(self.color)

        with (
            container := d.div(
                style=f"display:flex;align-items:center;gap:8px;padding: 8px 12px;background-color: {get_theme_colors(theme)['container_bg']};border-radius: 6px;border-left: 4px solid "
                + color_hex
                + ";"
            )
        ):
            if self.show_icon:
                d.span(
                    icon, style=f"color:{color_hex};font-size:16px;font-weight:bold;"
                )
            d.span(
                self.status,
                style=f"font-weight:600;color: {get_theme_colors(theme)['accent']};",
            )
        return container

    def classic_md(self) -> str:
        icon = self._get_icon(self.color) if self.show_icon else ""
        return f"{icon} **{self.status}**".strip()

    def slack_md(self) -> str:
        return self.classic_md()

    def discord_md(self) -> str:
        return self.classic_md()

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        # Console doesn't need theme as terminal has its own color scheme
        icon = self._get_icon(self.color)

        # Map colors to Rich styles
        style_map = {
            "green": "bright_green",
            "red": "bright_red",
            "yellow": "bright_yellow",
            "blue": "bright_cyan",
            "orange": "bright_magenta",
            "gray": "bright_black",
        }

        style = style_map.get(self.color.lower(), "default")

        if self.show_icon:
            console.print(f"[{style}]{icon} {self.status}[/{style}]")
        else:
            console.print(f"[{style}]{self.status}[/{style}]")


class ProgressBar(Component):
    """A progress bar component for showing completion percentages."""

    def __init__(
        self,
        value: float,
        max_value: float = 100,
        color: str = "blue",
        show_percentage: bool = True,
        width: int = 300,
    ):
        """
        Args:
            value (float): Current progress value.
            max_value (float, optional): Maximum value. Defaults to 100.
            color (str, optional): Color of the progress bar. Defaults to "blue".
            show_percentage (bool, optional): Whether to show percentage text. Defaults to True.
            width (int, optional): Width of the progress bar in pixels. Defaults to 300.
        """
        self.value = min(value, max_value)
        self.max_value = max_value
        self.color = color
        self.show_percentage = show_percentage
        self.width = width

    def _get_color_hex(self, color: str, theme: str = "dark") -> str:
        """Get hex color for the progress bar."""
        colors = get_theme_colors(theme)
        color_map = {
            "blue": colors["important"],
            "green": colors["success"],
            "red": colors["error"],
            "yellow": colors["warning"],
            "purple": "#7C3AED" if theme == "light" else "#A78BFA",
            "gray": colors["neutral"],
        }
        return color_map.get(color.lower(), color)

    def html(self, theme: str = "dark") -> d.html_tag:
        percentage = (self.value / self.max_value) * 100
        color_hex = self._get_color_hex(self.color, theme)

        with (container := d.div(style=f"width: {self.width}px;")):
            if self.show_percentage:
                d.div(
                    f"{percentage:.1f}%",
                    style=f"text-align: center; margin-bottom: 8px; font-weight: 600; color: {get_theme_colors(theme)['accent']};",
                )

            with d.div(
                style=f"background-color: {get_theme_colors(theme)['border']}; border-radius: 8px; height: 12px; overflow: hidden;"
            ):
                d.div(
                    style=f"background-color: {color_hex}; height: 100%; width: {percentage}%; border-radius: 8px;"
                )
        return container

    def classic_md(self) -> str:
        percentage = (self.value / self.max_value) * 100
        return f"**Progress:** {percentage:.1f}% ({self.value}/{self.max_value})"

    def slack_md(self) -> str:
        percentage = (self.value / self.max_value) * 100
        return f"*Progress:* {percentage:.1f}% ({self.value}/{self.max_value})"

    def discord_md(self) -> str:
        percentage = (self.value / self.max_value) * 100
        return f"**Progress:** {percentage:.1f}% ({self.value}/{self.max_value})"

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        from rich.progress import BarColumn, MofNCompleteColumn, Progress

        # Enhanced progress bar with more information
        color_map = {
            "blue": "bright_blue",
            "green": "bright_green",
            "red": "bright_red",
            "yellow": "bright_yellow",
            "purple": "bright_magenta",
            "gray": "dim",
        }

        style = color_map.get(self.color, "bright_blue")

        # Create enhanced progress display
        with Progress(
            "[progress.description]{task.description}",
            BarColumn(bar_width=50, style=style, complete_style=f"bold {style}"),
            "[progress.percentage]{task.percentage:>3.1f}%",
            MofNCompleteColumn(),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task("Progress", total=self.max_value)
            progress.update(task, completed=self.value)

            # Add a brief pause to show the progress bar
            import time

            time.sleep(0.1)


class Alert(Component):
    """An alert/notification component for important messages."""

    def __init__(
        self, message: str, alert_type: str = "info", title: Optional[str] = None
    ):
        """
        Args:
            message (str): The alert message.
            alert_type (str, optional): Type of alert (info, success, warning, error). Defaults to "info".
            title (Optional[str], optional): Optional title for the alert. Defaults to None.
        """
        self.message = message
        self.alert_type = alert_type
        self.title = title

    def _get_alert_styles(self, alert_type: str, theme: str = "dark") -> tuple:
        """Get styles for alert type."""
        colors = get_theme_colors(theme)
        if theme == "light":
            styles = {
                "info": ("#DBEAFE", colors["important"], "#1E3A8A", "ℹ"),
                "success": ("#D1FAE5", colors["success"], "#065F46", "✓"),
                "warning": ("#FEF3C7", colors["warning"], "#92400E", "⚠"),
                "error": ("#FEE2E2", colors["error"], "#991B1B", "✗"),
            }
        else:  # dark theme
            styles = {
                "info": ("#1E3A8A", colors["important"], "#93C5FD", "ℹ"),
                "success": ("#065F46", colors["success"], "#86EFAC", "✓"),
                "warning": ("#92400E", colors["warning"], "#FDE68A", "⚠"),
                "error": ("#991B1B", colors["error"], "#FCA5A5", "✗"),
            }
        return styles.get(alert_type.lower(), styles["info"])

    def html(self, theme: str = "dark") -> d.html_tag:
        bg_color, border_color, text_color, icon = self._get_alert_styles(
            self.alert_type, theme
        )

        with (
            container := d.div(
                style=f"background-color: {bg_color}; border: 1px solid {border_color}; border-radius: 8px; padding: 16px; margin: 16px 0;"
            )
        ):
            with d.div(style="display: flex; align-items: flex-start; gap: 12px;"):
                d.span(
                    icon,
                    style=f"color: {text_color}; font-size: 18px; font-weight: bold; flex-shrink: 0;",
                )
                with d.div(style="flex: 1;"):
                    if self.title:
                        d.div(
                            self.title,
                            style=f"font-weight: 600; color: {text_color}; margin-bottom: 4px;",
                        )
                    d.div(self.message, style=f"color: {text_color}; line-height: 1.5;")
        return container

    def classic_md(self) -> str:
        icon = self._get_alert_styles(self.alert_type)[3]
        title_text = f"**{self.title}**\n" if self.title else ""
        return f"{icon} **{self.alert_type.upper()}**\n{title_text}{self.message}"

    def slack_md(self) -> str:
        return self.classic_md()

    def discord_md(self) -> str:
        return self.classic_md()

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        # Console doesn't need theme as terminal has its own color scheme
        # Using light theme colors for console output readability
        _, _, _, icon = self._get_alert_styles(self.alert_type, "light")

        # Map alert types to Rich styles
        style_map = {
            "info": "bright_cyan",
            "success": "bright_green",
            "warning": "bright_yellow",
            "error": "bright_red",
        }

        style = style_map.get(self.alert_type.lower(), "bright_cyan")

        # Build alert content
        content = ""
        if self.title:
            content = f"[bold]{self.title}[/bold]\n"
        content += self.message

        # Create panel with icon in title
        title = f"{icon} {self.alert_type.upper()}"
        panel = Panel(content, title=title, border_style=style, padding=(1, 2))
        console.print(panel)


class CodeBlock(Component):
    """A code block component for displaying code snippets."""

    def __init__(
        self, code: str, language: str = "text", show_line_numbers: bool = False
    ):
        """
        Args:
            code (str): The code to display.
            language (str, optional): Programming language for syntax context. Defaults to "text".
            show_line_numbers (bool, optional): Whether to show line numbers. Defaults to False.
        """
        self.code = code
        self.language = language
        self.show_line_numbers = show_line_numbers

    def html(self, theme: str = "dark") -> d.html_tag:
        with (
            container := d.div(
                style=f"background-color: {get_theme_colors(theme)['code_bg']}; border-radius: 8px; padding: 16px; margin: 16px 0; overflow-x: auto;"
            )
        ):
            if self.language != "text":
                d.div(
                    self.language.upper(),
                    style=f"color: {get_theme_colors(theme)['text_secondary']}; font-size: 12px; font-weight: 600; text-transform: uppercase; margin-bottom: 8px;",
                )

            if self.show_line_numbers:
                lines = self.code.split("\n")
                with d.div(
                    style="font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace; font-size: 14px; line-height: 1.5;"
                ):
                    for i, line in enumerate(lines, 1):
                        with d.div(style="display: flex;"):
                            d.span(
                                f"{i:3d}",
                                style=f"color: {get_theme_colors(theme)['text_secondary']}; margin-right: 16px; user-select: none;",
                            )
                            d.span(
                                line,
                                style=f"color: {get_theme_colors(theme)['text_primary']}; flex: 1;",
                            )
            else:
                d.pre(
                    self.code,
                    style=f"color: {get_theme_colors(theme)['text_primary']}; font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace; font-size: 14px; line-height: 1.5; margin: 0; white-space: pre-wrap;",
                )
        return container

    def classic_md(self) -> str:
        return f"```{self.language}\n{self.code}\n```"

    def slack_md(self) -> str:
        return self.classic_md()

    def discord_md(self) -> str:
        return self.classic_md()

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        from rich.syntax import Syntax

        # Enhanced syntax highlighting with better themes and panel
        syntax = Syntax(
            self.code,
            self.language,
            theme="github-dark",  # Better theme
            line_numbers=self.show_line_numbers,
            word_wrap=True,
            background_color="default",
            highlight_lines=set() if not self.show_line_numbers else None,
        )
        panel = Panel(
            syntax,
            title=self.language.upper(),
            border_style="bright_blue",
            padding=(0, 1),
        )

        console.print(panel)


class PriceChange(Component):
    """A component that displays price movements with appropriate colors."""

    def __init__(
        self,
        current: float,
        previous: Optional[float] = None,
        currency: str = "$",
    ):
        """
        Args:
            current (float): Current price.
            previous (Optional[float], optional): Previous price. If provided, shows change and percentage. Defaults to None.
            currency (str, optional): Currency symbol. Defaults to "$".
        """
        self.current = current
        self.previous = previous
        self.currency = currency
        if previous is not None:
            self.change = current - previous
            self.change_pct = (self.change / previous * 100) if previous != 0 else 0
        else:
            self.change = None
            self.change_pct = None

    def html(self, theme: str = "dark") -> d.html_tag:
        with (container := d.div()):
            if self.previous is not None:
                # Show current with change information
                colors = get_theme_colors(theme)
                color = colors["success"] if self.change >= 0 else colors["error"]
                symbol = "▲" if self.change >= 0 else "▼"
                d.span(
                    f"{self.currency}{self.current:.2f}",
                    style="font-size:18px;font-weight:bold;",
                )
                d.span(" ")
                change_text = f"{symbol} {self.currency}{abs(self.change):.2f} ({self.change_pct:+.1f}%)"
                d.span(change_text, style=f"color:{color};font-weight:bold;")
            else:
                # Show current with directional symbol based on positive/negative
                colors = get_theme_colors(theme)
                symbol = "▲" if self.current >= 0 else "▼"
                color = colors["success"] if self.current >= 0 else colors["error"]
                d.span(
                    f"{symbol} {self.currency}{abs(self.current):.2f}",
                    style=f"font-size:18px;font-weight:bold;color:{color};",
                )
        return container

    def classic_md(self) -> str:
        if self.previous is not None:
            symbol = "▲" if self.change >= 0 else "▼"
            change_text = f"{symbol} {self.currency}{abs(self.change):.2f} ({self.change_pct:+.1f}%)"
            return f"**{self.currency}{self.current:.2f}** {change_text}"
        else:
            symbol = "▲" if self.current >= 0 else "▼"
            return f"**{symbol} {self.currency}{abs(self.current):.2f}**"

    def slack_md(self) -> str:
        return self.classic_md()

    def discord_md(self) -> str:
        return self.classic_md()

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        accent_color = get_theme_colors("dark")["accent"]

        if self.previous is not None:
            color = "green" if self.change >= 0 else "red"
            symbol = "▲" if self.change >= 0 else "▼"
            change_text = f"[{accent_color}]{symbol}[/{accent_color}] {self.currency}{abs(self.change):.2f} ({self.change_pct:+.1f}%)"
            console.print(
                f"[bold]{self.currency}{self.current:.2f}[/bold] [{color}]{change_text}[/{color}]"
            )
        else:
            symbol = "▲" if self.current >= 0 else "▼"
            color = "green" if self.current >= 0 else "red"
            console.print(
                f"[bold {color}][{accent_color}]{symbol}[/{accent_color}] {self.currency}{abs(self.current):.2f}[/bold {color}]"
            )


class MetricCard(Component):
    """A metric card component for displaying key performance indicators."""

    def __init__(
        self,
        title: str,
        value: str,
        change: Optional[str] = None,
        trend: Optional[str] = None,
        period: Optional[str] = None,
    ):
        """
        Args:
            title (str): The metric title.
            value (str): The metric value.
            change (Optional[str], optional): Change indicator (e.g., "+12.5%"). Defaults to None.
            trend (Optional[str], optional): Trend direction ("up", "down", "neutral"). Defaults to None.
            period (Optional[str], optional): Time period for comparison. Defaults to None.
        """
        self.title = title
        self.value = value
        self.change = change
        self.trend = trend
        self.period = period

    def _get_trend_icon(self, trend: str) -> str:
        """Get trend icon."""
        icons = {"up": "↗", "down": "↘", "neutral": "→"}
        return icons.get(trend.lower(), "")

    def _get_change_color(self, change: str, theme: str = "dark") -> str:
        """Get color for change indicator."""
        colors = get_theme_colors(theme)
        if change.startswith("+"):
            return colors["success"]
        elif change.startswith("-"):
            return colors["error"]
        else:
            return colors["text_secondary"]

    def html(self, theme: str = "dark") -> d.html_tag:
        with (
            container := d.div(
                style=f"background-color: {get_theme_colors(theme)['code_bg']}; border: 1px solid {get_theme_colors(theme)['border']}; border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);"
            )
        ):
            d.div(
                self.title,
                style=f"font-size: 14px; color: {get_theme_colors(theme)['text_secondary']}; font-weight: 500; margin-bottom: 8px;",
            )

            d.div(
                self.value,
                style=f"font-size: 24px; font-weight: 700; color: {get_theme_colors(theme)['accent']}; margin-bottom: 8px;",
            )

            if self.change:
                change_color = self._get_change_color(self.change, theme)
                trend_icon = self._get_trend_icon(self.trend) if self.trend else ""

                with d.div(style="display: flex; align-items: center; gap: 4px;"):
                    d.span(trend_icon, style=f"color: {change_color}; font-size: 14px;")
                    d.span(
                        self.change,
                        style=f"color: {change_color}; font-size: 14px; font-weight: 600;",
                    )
                    if self.period:
                        d.span(
                            f" {self.period}",
                            style=f"color: {get_theme_colors(theme)['text_secondary']}; font-size: 12px;",
                        )
        return container

    def classic_md(self) -> str:
        result = f"**{self.title}**\n{self.value}"
        if self.change:
            result += f"\n{self.change}"
            if self.period:
                result += f" {self.period}"
        return result

    def slack_md(self) -> str:
        result = f"*{self.title}*\n{self.value}"
        if self.change:
            result += f"\n{self.change}"
            if self.period:
                result += f" {self.period}"
        return result

    def discord_md(self) -> str:
        result = f"**{self.title}**\n{self.value}"
        if self.change:
            result += f"\n{self.change}"
            if self.period:
                result += f" {self.period}"
        return result

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        # Create a metric card panel
        content = f"[dim]{self.title}[/dim]\n[bold bright_white]{self.value}[/bold bright_white]"

        if self.change:
            # Use default terminal colors for console output
            style = (
                "green"
                if self.change.startswith("+")
                else "red" if self.change.startswith("-") else "dim"
            )

            trend_icon = self._get_trend_icon(self.trend) if self.trend else ""
            change_line = f"\n[{style}]{trend_icon} {self.change}[/{style}]"
            if self.period:
                change_line += f" [dim]{self.period}[/dim]"
            content += change_line

        panel = Panel(content, border_style="bright_cyan", padding=(1, 2), expand=False)
        console.print(panel)


class Breadcrumb(Component):
    """A breadcrumb component for navigation context."""

    def __init__(self, items: Sequence[str]):
        """
        Args:
            items (Sequence[str]): List of breadcrumb items.
        """
        self.items = items

    def html(self, theme: str = "dark") -> d.html_tag:
        with (container := d.div(style="margin: 16px 0;")):
            for i, item in enumerate(self.items):
                if i > 0:
                    d.span(
                        " > ",
                        style=f"color: {get_theme_colors(theme)['text_secondary']}; margin: 0 8px;",
                    )
                d.span(
                    item,
                    style=f"color: {get_theme_colors(theme)['text_secondary']}; font-size: 14px;",
                )
        return container

    def classic_md(self) -> str:
        return " > ".join(self.items)

    def slack_md(self) -> str:
        return " > ".join(self.items)

    def discord_md(self) -> str:
        return " > ".join(self.items)

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        # Create breadcrumb with separators
        accent_color = get_theme_colors("dark")["accent"]
        parts = []
        for i, item in enumerate(self.items):
            if i > 0:
                parts.append(f"[{accent_color}] > [/{accent_color}]")
            parts.append(f"[{accent_color}]{item}[/{accent_color}]")

        console.print("".join(parts))


class Card(Component):
    """A container component with header, body, and optional footer."""

    def __init__(
        self,
        body: Sequence[Component],
        header: Optional[str] = None,
        footer: Optional[str] = None,
        border_color: Optional[str] = None,
    ):
        """
        Args:
            body (Sequence[Component]): The main content components.
            header (Optional[str], optional): Header text. Defaults to None.
            footer (Optional[str], optional): Footer text. Defaults to None.
            border_color (Optional[str], optional): Border color for the card. Defaults to theme border.
        """
        self.body = body if isinstance(body, (list, tuple)) else [body]
        self.header = (
            Text(header, ContentType.IMPORTANT, FontSize.LARGE) if header else None
        )
        self.footer = Text(footer, ContentType.INFO, FontSize.SMALL) if footer else None
        self.border_color = border_color

    def html(self, theme: str = "dark") -> d.html_tag:
        colors = get_theme_colors(theme)
        border_color = self.border_color or colors["border"]

        with (
            container := d.div(
                style=f"""
            border: 1px solid {border_color};
            border-radius: 8px;
            padding: 20px;
            margin: 16px 0;
            background-color: {colors['code_bg']};
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        """
            )
        ):
            if self.header:
                d.div(
                    self.header.html(),
                    style=f"border-bottom: 2px solid {get_theme_colors(theme)['border']}; padding-bottom: 12px; margin-bottom: 16px; font-size: 18px; font-weight: 600; color: {get_theme_colors(theme)['accent']};",
                )
            for component in self.body:
                d.div(component.html(), style="margin: 12px 0;")
            if self.footer:
                d.div(
                    self.footer.html(),
                    style=f"border-top: 1px solid {get_theme_colors(theme)['border']}; padding-top: 12px; margin-top: 16px; font-size: 14px; color: {get_theme_colors(theme)['text_secondary']};",
                )
        return container

    def classic_md(self) -> str:
        parts = []
        if self.header:
            parts.append(self.header.classic_md())
            parts.append("---")
        for component in self.body:
            parts.append(component.classic_md())
        if self.footer:
            parts.append("---")
            parts.append(self.footer.classic_md())
        return "\n\n".join(parts)

    def slack_md(self) -> str:
        parts = []
        if self.header:
            parts.append(self.header.slack_md())
            parts.append("─" * 20)
        for component in self.body:
            parts.append(component.slack_md())
        if self.footer:
            parts.append("─" * 20)
            parts.append(self.footer.slack_md())
        return "\n\n".join(parts)

    def discord_md(self) -> str:
        parts = []
        if self.header:
            parts.append(self.header.discord_md())
            parts.append("─" * 20)
        for component in self.body:
            parts.append(component.discord_md())
        if self.footer:
            parts.append("─" * 20)
            parts.append(self.footer.discord_md())
        return "\n\n".join(parts)

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        # Build content
        if self.header:
            # We'll print header separately as panel title
            pass

        buffer = StringIO()
        capture_console = Console(file=buffer, force_terminal=True)

        for component in self.body:
            component.console(capture_console)

        body_content = buffer.getvalue().strip()

        if self.footer:
            buffer = StringIO()
            capture_console = Console(file=buffer, force_terminal=True)
            self.footer.console(capture_console)
            footer_content = buffer.getvalue().strip()
            body_content += f"\n\n[dim]{footer_content}[/dim]"

        # Create panel with header as title
        title = self.header.value if self.header else None
        panel = Panel(
            body_content, title=title, border_style="bright_cyan", padding=(1, 2)
        )
        console.print(panel)


class Grid(Component):
    """A component that arranges other components in a grid layout."""

    def __init__(self, components: Sequence[Sequence[Component]], gap: int = 16):
        """
        Args:
            components (Sequence[Sequence[Component]]): 2D array of components (rows and columns).
            gap (int, optional): Gap between grid items in pixels. Defaults to 16.
        """
        self.components = components
        self.gap = gap

    def html(self, theme: str = "dark") -> d.html_tag:
        with (container := d.div()):
            for row in self.components:
                with d.div(
                    style=f"display: flex; gap: {self.gap}px; margin-bottom: {self.gap}px;"
                ):
                    for component in row:
                        d.div(
                            component.html(),
                            style=f"flex: 1; border: 1px solid {get_theme_colors(theme)['border']}; padding: 16px; border-radius: 6px; background-color: {get_theme_colors(theme)['code_bg']}; box-shadow: 0 1px 3px rgba(0,0,0,0.1); display: flex; align-items: center; justify-content: center;",
                        )
        return container

    def classic_md(self) -> str:
        # Render as a table for markdown
        if not self.components:
            return ""

        # Create table headers (empty for grid)
        cols = len(self.components[0])
        headers = [f"Col {i+1}" for i in range(cols)]
        separator = [":---:" for _ in range(cols)]

        rows = [
            "|" + "|".join(headers) + "|",
            "|" + "|".join(separator) + "|",
        ]

        for row in self.components:
            row_text = (
                "|"
                + "|".join([comp.classic_md().replace("\n", " ") for comp in row])
                + "|"
            )
            rows.append(row_text)

        return "\n".join(rows)

    def slack_md(self) -> str:
        # Render as sections for Slack
        sections = []
        for i, row in enumerate(self.components):
            section = []
            for j, component in enumerate(row):
                section.append(f"*Row {i+1}, Col {j+1}:*\n{component.slack_md()}")
            sections.append("\n".join(section))
        return "\n\n".join(sections)

    def discord_md(self) -> str:
        # Render as sections for Discord
        sections = []
        for i, row in enumerate(self.components):
            section = []
            for j, component in enumerate(row):
                section.append(f"**Row {i+1}, Col {j+1}:**\n{component.discord_md()}")
            sections.append("\n".join(section))
        return "\n\n".join(sections)

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        # Enhanced grid using Rich Columns for better layout
        accent_color = get_theme_colors("dark")["accent"]

        for row_idx, row in enumerate(self.components):
            # Create panels for each component in the row
            row_panels = []
            for col_idx, component in enumerate(row):
                # Capture component output
                buffer = StringIO()
                capture_console = Console(file=buffer, force_terminal=True, width=30)
                component.console(capture_console)
                content = buffer.getvalue().strip()

                # Create a panel for each grid cell
                panel = Panel(
                    content,
                    title=f"Cell ({row_idx+1},{col_idx+1})",
                    border_style=accent_color,
                    padding=(1, 2),
                )
                row_panels.append(panel)

            # Use Columns to display the row
            if row_panels:
                columns = Columns(row_panels, equal=True, expand=True)
                console.print(columns)

                # Add spacing between rows
                if row_idx < len(self.components) - 1:
                    console.print()


class JSONComponent(Component):
    """A component for displaying formatted JSON data."""

    def __init__(self, data: Any, indent: int = 2, sort_keys: bool = False):
        """
        Args:
            data: The data to display as JSON
            indent: JSON indentation level
            sort_keys: Whether to sort keys
        """
        self.data = data
        self.indent = indent
        self.sort_keys = sort_keys

    def html(self, theme: str = "dark") -> d.html_tag:
        import json

        json_str = json.dumps(self.data, indent=self.indent, sort_keys=self.sort_keys)
        return d.pre(
            json_str,
            style=f"color: {get_theme_colors(theme)['text_primary']}; background: {get_theme_colors(theme)['code_bg']}; padding: 16px; border-radius: 8px; font-family: monospace;",
        )

    def classic_md(self) -> str:
        import json

        json_str = json.dumps(self.data, indent=self.indent, sort_keys=self.sort_keys)
        return f"```json\n{json_str}\n```"

    def slack_md(self) -> str:
        return self.classic_md()

    def discord_md(self) -> str:
        return self.classic_md()

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        # Use Rich JSON rendering
        rich_json = RichJSON.from_data(
            self.data, indent=self.indent, sort_keys=self.sort_keys
        )
        panel = Panel(rich_json, title="JSON Data", border_style="bright_yellow")
        console.print(panel)


class SpinnerComponent(Component):
    """A component for displaying loading spinners."""

    def __init__(
        self,
        text: str = "Loading...",
        spinner_style: str = "dots",
        duration: float = 2.0,
    ):
        """
        Args:
            text: Text to display with spinner
            spinner_style: Style of spinner (dots, line, etc.)
            duration: How long to show spinner
        """
        self.text = text
        self.spinner_style = spinner_style
        self.duration = duration

    def html(self, theme: str = "dark") -> d.html_tag:
        return d.div(self.text, style=f"color: {get_theme_colors(theme)['accent']};")

    def classic_md(self) -> str:
        return self.text

    def slack_md(self) -> str:
        return self.text

    def discord_md(self) -> str:
        return self.text

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        import time

        with console.status(
            f"[bold green]{self.text}[/bold green]", spinner=self.spinner_style
        ):
            time.sleep(self.duration)


class TreeView(Component):
    """A component that renders nested dict/list structures as a tree."""

    def __init__(
        self,
        data: Union[Dict[str, Any], ListType[Any]],
        title: Optional[str] = None,
        max_depth: Optional[int] = None,
        show_types: bool = False,
        expanded: bool = True,
    ):
        """
        Args:
            data: The nested dict/list structure to display
            title: Optional title for the tree
            max_depth: Maximum depth to display (None for unlimited)
            show_types: Whether to show type information
            expanded: Whether tree starts expanded or collapsed
        """
        self.data = data
        self.title = title or "Tree View"
        self.max_depth = max_depth
        self.show_types = show_types
        self.expanded = expanded

    def _render_value(self, value: Any, include_type: bool = False) -> str:
        """Render a leaf value as a string."""
        if value is None:
            result = "null"
        elif isinstance(value, bool):
            result = str(value).lower()
        elif isinstance(value, (int, float)):
            result = str(value)
        elif isinstance(value, str):
            result = f'"{value}"' if len(value) <= 50 else f'"{value[:47]}..."'
        else:
            result = str(type(value).__name__)

        if include_type and self.show_types:
            return f"{result} ({type(value).__name__})"
        return result

    def _build_tree_dict(
        self, data: Union[Dict, ListType], depth: int = 0
    ) -> Dict[str, Any]:
        """Build a nested dictionary representation for HTML/MD rendering."""
        if self.max_depth is not None and depth >= self.max_depth:
            return {"...": f"(depth limit reached)"}

        result = {}

        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    result[str(key)] = self._build_tree_dict(value, depth + 1)
                else:
                    result[str(key)] = self._render_value(value)
        elif isinstance(data, list):
            for i, value in enumerate(data):
                if isinstance(value, (dict, list)):
                    result[f"[{i}]"] = self._build_tree_dict(value, depth + 1)
                else:
                    result[f"[{i}]"] = self._render_value(value)

        return result

    def _render_tree_html(
        self, data: Dict[str, Any], theme: str, depth: int = 0
    ) -> str:
        """Recursively render tree structure as HTML."""
        html_parts = []
        colors = get_theme_colors(theme)

        for key, value in data.items():
            # Create collapsible section for nested structures
            if isinstance(value, dict):
                html_parts.append(
                    f"""
                    <details {"open" if self.expanded or depth == 0 else ""}>
                        <summary style="cursor: pointer; color: {colors['accent']}; font-weight: 600; margin: 4px 0;">
                            ▶ {key}
                        </summary>
                        <div style="margin-left: 20px; border-left: 2px solid {colors['border']}; padding-left: 12px;">
                            {self._render_tree_html(value, theme, depth + 1)}
                        </div>
                    </details>
                """
                )
            else:
                # Leaf node
                html_parts.append(
                    f"""
                    <div style="margin: 4px 0; color: {colors['text_primary']};">
                        <span style="color: {colors['accent']}; font-weight: 500;">{key}:</span>
                        <span style="color: {colors['text_secondary']}; font-family: monospace;"> {value}</span>
                    </div>
                """
                )

        return "".join(html_parts)

    def html(self, theme: str = "dark") -> d.html_tag:
        colors = get_theme_colors(theme)
        tree_data = self._build_tree_dict(self.data)

        with (
            container := d.div(
                style=f"background-color: {colors['code_bg']}; border: 1px solid {colors['border']}; border-radius: 8px; padding: 16px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;"
            )
        ):
            # Title
            d.div(
                self.title,
                style=f"font-size: 16px; font-weight: 600; color: {colors['accent']}; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 2px solid {colors['border']};",
            )
            # Tree content
            d.div(d.raw(self._render_tree_html(tree_data, theme)))

        return container

    def _render_tree_text(
        self,
        data: Union[Dict, ListType],
        prefix: str = "",
        is_last: bool = True,
        depth: int = 0,
    ) -> ListType[str]:
        """Recursively render tree structure as text."""
        if self.max_depth is not None and depth >= self.max_depth:
            return [f"{prefix}{'└── ' if is_last else '├── '}... (depth limit reached)"]

        lines = []
        items = []

        if isinstance(data, dict):
            items = list(data.items())
        elif isinstance(data, list):
            items = list(enumerate(data))

        for i, (key, value) in enumerate(items):
            is_last_item = i == len(items) - 1
            connector = "└── " if is_last_item else "├── "

            if isinstance(value, (dict, list)):
                lines.append(f"{prefix}{connector}{key}")
                extension = "    " if is_last_item else "│   "
                lines.extend(
                    self._render_tree_text(value, prefix + extension, True, depth + 1)
                )
            else:
                lines.append(f"{prefix}{connector}{key}: {self._render_value(value)}")

        return lines

    def classic_md(self) -> str:
        lines = [f"**{self.title}**", ""]
        lines.append("```")
        lines.extend(self._render_tree_text(self.data))
        lines.append("```")
        return "\n".join(lines)

    def slack_md(self) -> str:
        lines = [f"*{self.title}*", ""]
        lines.append("```")
        lines.extend(self._render_tree_text(self.data))
        lines.append("```")
        return "\n".join(lines)

    def discord_md(self) -> str:
        return self.classic_md()

    def console(self, console: Optional[Console] = None) -> None:
        if console is None:
            console = Console()

        from rich.tree import Tree

        accent_color = get_theme_colors("dark")["accent"]

        # Create root tree
        tree = Tree(f"[bold {accent_color}]{self.title}[/bold {accent_color}]")

        def add_branch(node: Tree, data: Union[Dict, ListType], depth: int = 0):
            """Recursively add branches to the tree."""
            if self.max_depth is not None and depth >= self.max_depth:
                node.add("[dim]... (depth limit reached)[/dim]")
                return

            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, (dict, list)):
                        # Branch node
                        child = node.add(f"[{accent_color}]{key}[/{accent_color}]")
                        add_branch(child, value, depth + 1)
                    else:
                        # Leaf node
                        rendered = self._render_value(
                            value, include_type=self.show_types
                        )
                        node.add(
                            f"[{accent_color}]{key}:[/{accent_color}] [dim]{rendered}[/dim]"
                        )
            elif isinstance(data, list):
                for i, value in enumerate(data):
                    if isinstance(value, (dict, list)):
                        # Branch node
                        child = node.add(f"[bright_cyan][{i}][/bright_cyan]")
                        add_branch(child, value, depth + 1)
                    else:
                        # Leaf node
                        rendered = self._render_value(
                            value, include_type=self.show_types
                        )
                        node.add(
                            f"[bright_cyan][{i}]:[/bright_cyan] [dim]{rendered}[/dim]"
                        )

        # Build the tree
        add_branch(tree, self.data)

        # Print with panel for better presentation
        panel = Panel(tree, border_style=accent_color, padding=(1, 2))
        console.print(panel)


class LogEntry(Component):
    """A structured log message with timestamp, level, and source."""

    def __init__(
        self,
        message: str,
        level: ContentType = ContentType.INFO,
        source: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ):
        """
        Args:
            message (str): The log message content.
            level (ContentType, optional): The log level. Defaults to ContentType.INFO.
            source (Optional[str], optional): The source component/module that generated the log. Defaults to None.
            timestamp (Optional[datetime], optional): The log timestamp. Defaults to current time.
        """
        self.message = str(message)
        self.level = level
        self.source = source
        self.timestamp = timestamp or datetime.now()

    def html(self, theme: str = "dark") -> d.html_tag:
        """Render the log entry as HTML."""
        colors = get_theme_colors(theme)
        level_color = level_css_color(self.level, theme)

        container = d.div(
            style=f"margin: 8px 0; padding: 12px; background-color: {colors['secondary']}; border-left: 4px solid {level_color}; border-radius: 4px;"
        )

        header = d.div(
            style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 12px; opacity: 0.8;"
        )

        # Timestamp
        timestamp_str = self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        header.add(d.span(timestamp_str, style="font-family: monospace;"))

        # Source and level
        meta_info = []
        if self.source:
            meta_info.append(f"[{self.source}]")
        meta_info.append(self.level.name)
        header.add(
            d.span(
                " ".join(meta_info), style=f"color: {level_color}; font-weight: bold;"
            )
        )

        container.add(header)

        # Message content
        message_div = d.div(
            self.message, style="font-family: monospace; white-space: pre-wrap;"
        )
        container.add(message_div)

        return container

    def md(self, slack_format: bool = False, discord_format: bool = False) -> str:
        """Render the log entry as Markdown."""
        timestamp_str = self.timestamp.strftime("%Y-%m-%d %H:%M:%S")

        # Build header parts
        header_parts = [f"`{timestamp_str}`"]
        if self.source:
            header_parts.append(f"`[{self.source}]`")
        header_parts.append(f"**{self.level.name}**")

        # Format the message
        if slack_format or discord_format:
            # Use code formatting for the message
            message_formatted = f"```\n{self.message}\n```"
        else:
            # Use inline code for shorter messages, code blocks for longer
            if len(self.message) <= 100 and "\n" not in self.message:
                message_formatted = f"`{self.message}`"
            else:
                message_formatted = f"```\n{self.message}\n```"

        return f"{' '.join(header_parts)}\n{message_formatted}"

    def rich_text(self) -> RichText:
        """Render the log entry for Rich console output."""
        timestamp_str = self.timestamp.strftime("%Y-%m-%d %H:%M:%S")

        # Color mapping for levels
        level_colors = {
            ContentType.INFO: "blue",
            ContentType.WARNING: "yellow",
            ContentType.ERROR: "red",
            ContentType.IMPORTANT: "magenta",
        }
        level_color = level_colors.get(self.level, "white")

        # Build the formatted text
        text = RichText()
        text.append(f"[{timestamp_str}] ", style="dim")

        if self.source:
            text.append(f"[{self.source}] ", style="cyan")

        text.append(f"{self.level.name}: ", style=f"bold {level_color}")
        text.append(self.message)

        return text
