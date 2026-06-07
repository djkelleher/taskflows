from taskflows.dashboard import Dashboard, LogsCountPlot, LogsPanelConfig, LogsTextSearch, _logql_string
from taskflows.serialization import load_dashboards_from_yaml
from taskflows.service import Service


def test_logql_string_escapes_quotes_and_backslashes():
    assert _logql_string('error in "worker\\job"') == '"error in \\"worker\\\\job\\""'


def test_dashboard_log_query_escapes_service_label_value():
    service = Service(name="worker-prod", start_command="python -V")
    service.name = 'worker"\\prod'
    dashboard = Dashboard(
        title="Escaped Logs",
        panels_grid=[LogsPanelConfig(service=service)],
    )

    gl_dashboard = dashboard._create_gl_dashboard("loki")
    expr = gl_dashboard.panels[0].targets[0]["expr"]

    assert expr == '{service_name="worker\\"\\\\prod"}'


def test_dashboard_layout_does_not_mutate_panel_widths():
    service = Service(name="worker-prod", start_command="python -V")
    panel = LogsPanelConfig(service=service)
    dashboard = Dashboard(title="Pure Layout", panels_grid=[panel])

    dashboard._create_gl_dashboard("loki")

    assert panel.width_fr is None


def test_dashboard_from_yaml():
    dashboard = Dashboard.from_yaml(
        """
        title: Worker Dashboard
        panels_grid:
          - type: LogsPanelConfig
            service:
              name: worker
              start_command: python worker.py
          - - type: LogsTextSearch
              service:
                name: api
                start_command: uvicorn app:app
              text: ERROR
              height: lg
            - type: LogsCountPlot
              service:
                name: scheduler
                start_command: python scheduler.py
              text: retrying
              period: "1m"
        """
    )

    assert dashboard.title == "Worker Dashboard"
    assert isinstance(dashboard.panels_grid[0], LogsPanelConfig)
    assert dashboard.panels_grid[0].service.name == "worker"
    assert isinstance(dashboard.panels_grid[1][0], LogsTextSearch)
    assert dashboard.panels_grid[1][0].title == "api: ERROR"
    assert dashboard.panels_grid[1][0].height == "lg"
    assert isinstance(dashboard.panels_grid[1][1], LogsCountPlot)
    assert dashboard.panels_grid[1][1].title == "scheduler: retrying Counts"


def test_load_dashboards_from_yaml(tmp_path):
    path = tmp_path / "dashboards.yaml"
    path.write_text(
        """
        dashboards:
          - title: Ops
            panels_grid:
              - type: LogsPanelConfig
                service:
                  name: worker
                  start_command: python worker.py
        """
    )

    dashboards = load_dashboards_from_yaml(path)

    assert len(dashboards) == 1
    assert dashboards[0].title == "Ops"
    assert dashboards[0].panels_grid[0].service.name == "worker"
