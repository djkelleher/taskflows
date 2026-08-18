"""Focused tests for cloud packaging and deployment orchestration."""

import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from taskflows.cloud import PULUMI_AVAILABLE
from taskflows.cloud.aws_lambda import AWSLambdaEnvironment
from taskflows.cloud.base import CloudDeploymentResult, CloudFunctionConfig
from taskflows.cloud.dependencies import DependencyManager
from taskflows.cloud.manager import DeploymentManager
from taskflows.cloud.utils import (
    _calendar_to_cron,
    _periodic_to_rate,
    create_lambda_deployment_package,
    validate_lambda_constraints,
)
from taskflows.schedule import Calendar, Periodic


def packaged_function():
    return {"answer": 42}


def test_optional_pulumi_import_reports_unavailable_without_dependency():
    if PULUMI_AVAILABLE:
        pytest.importorskip("pulumi")
    else:
        with pytest.raises(ImportError, match=r"taskflows\[pulumi\]"):
            from taskflows.cloud import PulumiAWSEnvironment

            PulumiAWSEnvironment()


def test_lambda_package_contains_runnable_handler_and_cloudpickle():
    package = create_lambda_deployment_package(packaged_function)

    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        names = set(archive.namelist())
        handler_source = archive.read("index.py").decode()

    assert "cloudpickle/__init__.py" in names
    namespace = {}
    exec(compile(handler_source, "index.py", "exec"), namespace)
    assert namespace["handler"]({}, None)["result"] == "{'answer': 42}"


def test_boto_backend_deploys_with_mocked_aws_clients():
    lambda_client = MagicMock()
    lambda_client.update_function_configuration.return_value = {
        "FunctionArn": "arn:aws:lambda:us-east-1:123:function:demo"
    }
    clients = [lambda_client, MagicMock(), MagicMock(), MagicMock()]

    with patch("taskflows.cloud.aws_lambda.boto3.client", side_effect=clients):
        environment = AWSLambdaEnvironment(execution_role_arn="arn:aws:iam::123:role/lambda")

    result = environment.deploy_function(
        packaged_function,
        CloudFunctionConfig(function_name="demo", auto_create_role=False),
    )

    assert result.success
    assert result.resource_id.endswith(":function:demo")
    lambda_client.update_function_code.assert_called_once()


@pytest.mark.asyncio
async def test_pulumi_backend_accepts_generated_function_archive(tmp_path):
    pulumi = pytest.importorskip("pulumi")

    class Mocks(pulumi.runtime.Mocks):
        def new_resource(self, args):
            return f"{args.name}_id", args.inputs

        def call(self, args):
            return args.args

    pulumi.runtime.set_mocks(Mocks())

    from taskflows.cloud.pulumi_aws import PulumiAWSEnvironment

    environment = PulumiAWSEnvironment.__new__(PulumiAWSEnvironment)
    environment.project_name = "test-project"
    environment.work_dir = tmp_path
    config = CloudFunctionConfig(
        function_name="demo",
        execution_role_arn="arn:aws:iam::123:role/lambda",
        auto_create_role=False,
    )
    package = create_lambda_deployment_package(packaged_function)

    resources = environment._create_lambda_infrastructure(config, package, use_s3=False)

    assert "function" in resources
    assert list(tmp_path.glob("demo-*.zip"))


def test_dependency_package_places_modules_at_archive_root(monkeypatch, tmp_path):
    manager = DependencyManager()

    def fake_install(_requirements: list[str], target: Path) -> None:
        (target / "example_dependency.py").write_text("VALUE = 1\n")
        (target / ".lock").write_text("")

    monkeypatch.setattr(manager, "_install_requirements", fake_install)
    package = manager.build_deployment_package(["example-dependency"])

    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        assert "example_dependency.py" in archive.namelist()
        assert "python/example_dependency.py" not in archive.namelist()
        assert ".lock" not in archive.namelist()


@pytest.mark.parametrize(
    ("schedule", "message"),
    [
        (Calendar(schedule="Foo 09:00"), "Invalid day of week"),
        (Calendar(schedule="Mon 25:00"), "Invalid calendar schedule time"),
        (Calendar(schedule="Mon"), "Invalid calendar schedule format"),
    ],
)
def test_calendar_translation_rejects_unsupported_specs(schedule, message):
    with pytest.raises(ValueError, match=message):
        _calendar_to_cron(schedule)


def test_periodic_translation_rejects_partial_minutes():
    schedule = Periodic(start_on="boot", period=61, relative_to="finish")
    with pytest.raises(ValueError, match="whole-minute"):
        _periodic_to_rate(schedule)


@pytest.mark.parametrize(
    ("timeout", "memory", "name"),
    [(0, 128, "valid"), (901, 128, "valid"), (60, 127, "valid"), (60, 128, "bad name")],
)
def test_lambda_constraints_reject_invalid_values(timeout, memory, name):
    with pytest.raises(ValueError):
        validate_lambda_constraints(timeout, memory, name)


def test_deploy_multiple_does_not_mutate_inputs(monkeypatch):
    manager = DeploymentManager.__new__(DeploymentManager)
    deploy = MagicMock(
        side_effect=lambda name, function, **_kwargs: CloudDeploymentResult(True, name)
    )
    monkeypatch.setattr(manager, "deploy_function", deploy)
    functions = [
        {"name": "one", "function": packaged_function, "memory_mb": 128},
        {"name": "two", "function": packaged_function},
    ]
    original = [dict(item) for item in functions]

    results = manager.deploy_multiple(functions, parallel=True)

    assert functions == original
    assert [result.resource_id for result in results] == ["one", "two"]


def test_parse_schedule_accepts_string_object_and_list():
    manager = DeploymentManager.__new__(DeploymentManager)
    periodic = Periodic(start_on="boot", period=60, relative_to="finish")

    assert manager._parse_schedule(periodic) == [periodic]
    assert manager._parse_schedule([periodic]) == [periodic]
    assert manager._parse_schedule("Mon-Fri 09:00") == [Calendar(schedule="Mon-Fri 09:00")]
