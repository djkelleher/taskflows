from taskflows.common import _SYSTEMD_FILE_PREFIX, logql_string, sort_service_names
from taskflows.common import extract_service_name, load_service_files


def test_logql_string_escapes_quotes_and_backslashes():
    assert logql_string('error in "worker\\job"') == '"error in \\"worker\\\\job\\""'


def test_sort_service_names_keeps_first_service_stop_pair():
    service = "etl"
    stop_service = f"stop-{_SYSTEMD_FILE_PREFIX}{service}"

    assert sort_service_names([service, stop_service]) == [service, stop_service]


def test_sort_service_names_preserves_unmatched_stop_services():
    stop_service = f"stop-{_SYSTEMD_FILE_PREFIX}orphan"

    assert sort_service_names(["api", stop_service]) == ["api", stop_service]


def test_extract_service_name_strips_taskflows_auxiliary_prefixes():
    assert extract_service_name(f"{_SYSTEMD_FILE_PREFIX}etl.service") == "etl"
    assert extract_service_name(f"stop-{_SYSTEMD_FILE_PREFIX}etl.service") == "etl"
    assert extract_service_name(f"restart-{_SYSTEMD_FILE_PREFIX}etl.service") == "etl"


def test_load_service_files_groups_auxiliary_units_by_base_service(tmp_path):
    start_file = tmp_path / f"{_SYSTEMD_FILE_PREFIX}etl.service"
    stop_file = tmp_path / f"stop-{_SYSTEMD_FILE_PREFIX}etl.service"
    restart_file = tmp_path / f"restart-{_SYSTEMD_FILE_PREFIX}etl.service"
    for file in (start_file, stop_file, restart_file):
        file.write_text("[Service]\nExecStart=true\n")

    grouped = load_service_files([start_file, stop_file, restart_file])

    assert set(grouped) == {"etl"}
    assert {entry["name"] for entry in grouped["etl"]} == {
        start_file.name,
        stop_file.name,
        restart_file.name,
    }
