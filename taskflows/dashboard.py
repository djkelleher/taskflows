import json
import uuid
from typing import List, Literal, Optional

import requests
from grafanalib._gen import DashboardEncoder
from grafanalib.core import Annotations
from grafanalib.core import Dashboard as GLDashboard
from grafanalib.core import Graph, GridPos, Logs, Templating, Time, TimePicker
from pydantic import BaseModel

from .common import config, logger, sort_service_names
from .service import Service


class LogsPanelConfig(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    service: Service
    height: Literal["sm", "md", "lg", "xl"] = "md"
    width_fr: Optional[float] = (
        None  # Fraction of the width (e.g., 0.5 for half-width, 1.0 for full-width)
    )
    time_from: Optional[str] = None  # e.g., "now-1h", "now-7d", "now-30m"
    time_shift: Optional[str] = None  # e.g., "1d" to compare with yesterday

    @property
    def height_no(self) -> int:
        if self.height == "sm":
            return 5
        if self.height == "md":
            return 10
        if self.height == "lg":
            return 15
        if self.height == "xl":
            return 20
        raise ValueError(f"Invalid height: {self.height}")


class LogsTextSearch(LogsPanelConfig):
    text: str
    title: Optional[str] = None

    def model_post_init(self, __context):
        if self.title is None:
            self.title = f"{self.service.name}: {self.text}"


class LogsCountPlot(LogsPanelConfig):
    text: str
    period: str = "5m"  # e.g., "1m", "5m", etc.
    title: Optional[str] = None

    def model_post_init(self, __context):
        if self.title is None:
            self.title = f"{self.service.name}: {self.text} Counts"


class Dashboard:
    def __init__(
        self, title: str, panels_grid: List[LogsPanelConfig | List[LogsPanelConfig]]
    ):
        # Validate panels_grid structure
        for panels_row in panels_grid:
            if isinstance(panels_row, LogsPanelConfig):
                continue
            if not all(isinstance(p, LogsPanelConfig) for p in panels_row):
                raise ValueError(
                    "panels_grid must be list[LogsPanelConfig | List[LogsPanelConfig]]."
                )
            if len(panels_row) > 24:
                raise ValueError("Each row in panels_grid can have at most 24 panels.")
        self.title = title
        self.panels_grid = panels_grid
        # generate a unique (and repeatable) id from the title.
        self.uid = str(uuid.uuid5(uuid.NAMESPACE_DNS, title))

    @classmethod
    def from_service_registries(
        cls, service_registries, title: str, n_columns: int = 2
    ):
        if not isinstance(service_registries, (list, tuple)):
            service_registries = [service_registries]
        srv_names = []
        for reg in service_registries:
            srv_names.extend(sort_service_names(reg.names))
        name_to_srv = {s.name: s for reg in service_registries for s in reg.services}
        panels_grid = []
        for i in range(0, len(srv_names), n_columns):
            row_services = srv_names[i : i + n_columns]
            panels_grid.append(
                [LogsPanelConfig(service=name_to_srv[name]) for name in row_services]
            )
        return cls(title=title, panels_grid=panels_grid)

    def create(self):
        # Get Loki datasource UID dynamically
        loki_uid = self._get_loki_datasource_uid()
        if not loki_uid:
            logger.error("Loki datasource not found in Grafana")
            return

        # Check if dashboard already exists and get its version
        search_resp = requests.get(
            f"http://{config.grafana}/api/search",
            params={"query": self.title},
            headers={"Authorization": f"Bearer {self._api_key}"},
        )

        existing_version = None
        if search_resp.status_code == 200:
            dashboards = search_resp.json()
            for db in dashboards:
                if db.get("title") == self.title:
                    # Get the existing dashboard to find its version
                    existing_resp = requests.get(
                        f"http://{config.grafana}/api/dashboards/uid/{db['uid']}",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                    )
                    if existing_resp.status_code == 200:
                        existing_version = existing_resp.json()["dashboard"]["version"]
                    break

        dashboard = self._create_gl_dashboard(loki_uid)

        # Set version if dashboard exists
        if existing_version is not None:
            dashboard.version = existing_version

        # Prepare the dashboard data
        dashboard_data = {"dashboard": dashboard}
        if existing_version is not None:
            dashboard_data["overwrite"] = True

        resp = requests.post(
            f"http://{config.grafana}/api/dashboards/db",
            data=json.dumps(dashboard_data, cls=DashboardEncoder, indent=2).encode(
                "utf-8"
            ),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        if resp.status_code == 200:
            logger.info(f"{self.title} dashboard created/updated successfully")
        else:
            logger.error(
                f"Error creating/updating dashboard: {resp.status_code} - {resp.text}"
            )

    @property
    def _api_key(self):
        if api_key := config.grafana_api_key:
            return api_key
        raise RuntimeError("TASKFLOWS_GRAFANA_API_KEY is not set")

    def _get_loki_datasource_uid(self):
        """Get the UID of the Loki datasource from Grafana"""
        resp = requests.get(
            f"http://{config.grafana}/api/datasources",
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        if resp.status_code == 401:
            logger.error(
                "Grafana API authentication failed. The API key may be invalid or expired. "
                "Please create a new API key and update TASKFLOWS_GRAFANA_API_KEY"
            )
            return None
        elif resp.status_code != 200:
            logger.error(
                f"Failed to get datasources from Grafana: {resp.status_code} - {resp.text}"
            )
            return None

        datasources = resp.json()
        for ds in datasources:
            if ds.get("type") == "loki":
                logger.debug(f"Found Loki datasource with UID: {ds.get('uid')}")
                return ds.get("uid")

        logger.warning(
            "Loki datasource not found in Grafana. "
            "Make sure the datasource is provisioned or create it manually in Grafana."
        )

    def _create_gl_dashboard(self, loki_uid: str) -> GLDashboard:

        gl_panels = []
        y_pos = 0

        for panels_row in self.panels_grid:
            if not isinstance(panels_row, (tuple, list)):
                panels_row = [panels_row]

            default_width_fr = 1 / len(panels_row)
            x_pos = 0
            max_height = 0

            for panel in panels_row:
                if panel.width_fr is None:
                    panel.width_fr = default_width_fr

                # Build the base query for simplified log setup
                expr = '{service_name="' + panel.service.name + '"}'

                title = panel.service.name

                if isinstance(panel, (LogsCountPlot, LogsTextSearch)):
                    title = panel.title
                    expr += f' |= "{panel.text}"'

                # All logs now use the same simplified format with proper Unicode characters
                # With Drop_Single_Key On, the log line is just the MESSAGE content
                # Add service name as prefix (timestamps are shown by Grafana UI)
                # expr += ' | line_format "[{{.service_name}}] {{__line__}}"'
                # expr += ' | line_format "[{{.service_name}}] {{.MESSAGE}}"'

                width = int(panel.width_fr * 24)

                if isinstance(panel, LogsCountPlot):
                    # Create a proper grafanalib Graph panel
                    graph_panel = Graph(
                        title=title,
                        targets=[
                            {
                                "expr": f"count_over_time({expr}[{panel.period}])",
                                "legendFormat": "Count",
                                "refId": "A",
                                "datasource": {"type": "loki", "uid": loki_uid},
                            }
                        ],
                        gridPos=GridPos(h=panel.height_no, w=width, x=x_pos, y=y_pos),
                        dataSource=loki_uid,
                        timeFrom=panel.time_from,
                        timeShift=panel.time_shift,
                    )
                    gl_panels.append(graph_panel)
                else:
                    # Create a proper grafanalib Logs panel
                    logs_panel = Logs(
                        title=title,
                        dataSource=loki_uid,
                        targets=[
                            {
                                "expr": expr,
                                "refId": "A",
                                "datasource": {"type": "loki", "uid": loki_uid},
                            }
                        ],
                        gridPos=GridPos(h=panel.height_no, w=width, x=x_pos, y=y_pos),
                        showLabels=False,
                        showCommonLabels=False,
                        showTime=True,
                        wrapLogMessages=True,
                        sortOrder="Descending",
                        dedupStrategy="none",
                        enableLogDetails=True,
                        prettifyLogMessage=False,
                        timeFrom=panel.time_from,
                        timeShift=panel.time_shift,
                        extraJson={"options": {"infiniteScrolling": True}},
                    )
                    gl_panels.append(logs_panel)

                x_pos += width
                max_height = max(max_height, panel.height_no)

            y_pos += max_height

        return GLDashboard(
            title=self.title,
            uid=self.uid,
            editable=True,
            graphTooltip=0,
            id=None,
            links=[],
            panels=gl_panels,
            refresh="10s",
            schemaVersion=40,
            tags=[],
            templating=Templating(list=[]),
            time=Time("now-24h", "now"),
            timePicker=TimePicker(
                refreshIntervals=["5s", "10s", "30s", "1m", "5m", "15m", "30m", "1h"],
                timeOptions=["5m", "15m", "1h", "6h", "12h", "24h", "2d", "7d", "30d"],
            ),
            timezone="browser",
            version=20,
            annotations=Annotations(
                list=[
                    {
                        "builtIn": 1,
                        "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                        "enable": True,
                        "hide": True,
                        "iconColor": "rgba(0, 211, 255, 1)",
                        "name": "Annotations & Alerts",
                        "type": "dashboard",
                    }
                ]
            ),
        ).auto_panel_ids()
