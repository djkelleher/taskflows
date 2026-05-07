from taskflows.dashboard import Dashboard, LogsPanelConfig, _logql_string
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
