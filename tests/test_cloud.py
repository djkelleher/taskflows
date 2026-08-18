"""Focused tests for cloud packaging and deployment orchestration."""

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from taskflows.cloud import PULUMI_AVAILABLE
from taskflows.cloud.aws_lambda import AWSLambdaEnvironment
from taskflows.cloud.base import (
    CloudDeploymentResult,
    CloudFunctionConfig,
    MonitoringConfig,
    RetryConfig,
)
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


def client_error(code: str, operation: str = "operation") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


def boto_environment(**lambda_overrides):
    lambda_client = MagicMock()
    lambda_client.get_function.return_value = {
        "Configuration": {"FunctionArn": "arn:aws:lambda:us-east-1:123:function:demo"}
    }
    lambda_client.update_function_code.return_value = {"CodeSha256": "digest"}
    lambda_client.update_function_configuration.return_value = {
        "FunctionArn": "arn:aws:lambda:us-east-1:123:function:demo"
    }
    lambda_client.publish_version.return_value = {"Version": "2"}
    lambda_client.update_alias.side_effect = client_error("ResourceNotFoundException")
    lambda_client.create_alias.return_value = {
        "AliasArn": "arn:aws:lambda:us-east-1:123:function:demo:live"
    }
    lambda_client.remove_permission.side_effect = client_error("ResourceNotFoundException")
    for name, value in lambda_overrides.items():
        getattr(lambda_client, name).side_effect = None
        getattr(lambda_client, name).return_value = value

    events_client = MagicMock()
    events_client.list_rules.return_value = {"Rules": []}
    events_client.put_rule.return_value = {"RuleArn": "arn:aws:events:rule/demo"}
    events_client.put_targets.return_value = {"FailedEntryCount": 0}
    logs_client = MagicMock()
    iam_client = MagicMock()
    clients = {
        "lambda": lambda_client,
        "events": events_client,
        "logs": logs_client,
        "iam": iam_client,
    }
    environment = AWSLambdaEnvironment(
        execution_role_arn="arn:aws:iam::123:role/lambda",
        clients=clients,
    )
    return environment, clients


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
    environment, clients = boto_environment()

    result = environment.deploy_function(
        packaged_function,
        CloudFunctionConfig(function_name="demo", auto_create_role=False),
    )

    assert result.success
    assert result.resource_id.endswith(":function:demo")
    clients["lambda"].update_function_code.assert_called_once()
    clients["lambda"].publish_version.assert_called_once()
    update = clients["lambda"].update_function_configuration.call_args.kwargs
    assert "Tags" not in update
    assert update["Handler"] == "index.handler"


def test_boto_backend_creates_and_publishes_a_new_function():
    environment, clients = boto_environment()
    clients["lambda"].get_function.side_effect = client_error("ResourceNotFoundException")
    clients["lambda"].create_function.return_value = {
        "FunctionArn": "arn:aws:lambda:us-east-1:123:function:demo",
        "Version": "1",
    }

    result = environment.deploy_function(
        packaged_function,
        CloudFunctionConfig(
            function_name="demo",
            auto_create_role=False,
            tags={"ManagedBy": "Taskflows"},
        ),
    )

    assert result.success
    assert result.version == "1"
    create = clients["lambda"].create_function.call_args.kwargs
    assert create["Publish"] is True
    assert create["Architectures"] == ["x86_64"]
    assert create["Tags"] == {"ManagedBy": "Taskflows"}
    assert "ZipFile" in create["Code"]


def test_boto_backend_reconciles_alias_schedule_retry_and_empty_payload():
    environment, clients = boto_environment()
    config = CloudFunctionConfig(
        function_name="demo",
        auto_create_role=False,
        create_alias="live",
        schedules=[Calendar(schedule="Mon-Fri 09:00")],
        retry_config=RetryConfig(max_retry_attempts=1, max_event_age_seconds=600),
    )

    result = environment.deploy_function(packaged_function, config)
    response_stream = io.BytesIO(json.dumps({"ok": True}).encode())
    clients["lambda"].invoke.return_value = {"StatusCode": 200, "Payload": response_stream}
    invocation = environment.invoke_function("demo", {})

    assert result.success
    assert result.version == "2"
    assert result.rollback_id == "live"
    assert invocation["Payload"] == {"ok": True}
    assert clients["lambda"].invoke.call_args.kwargs["Payload"] == b"{}"
    clients["lambda"].put_function_event_invoke_config.assert_called_once_with(
        FunctionName="demo",
        Qualifier="live",
        MaximumRetryAttempts=1,
        MaximumEventAgeInSeconds=600,
    )
    assert clients["events"].put_targets.call_args.kwargs["Targets"][0]["Arn"].endswith(":live")


def test_boto_backend_removes_stale_managed_schedules():
    environment, clients = boto_environment()
    prefix = environment._schedule_prefix("demo")
    clients["events"].list_rules.return_value = {
        "Rules": [{"Name": f"{prefix}0"}, {"Name": f"{prefix}1"}]
    }
    clients["events"].list_targets_by_rule.return_value = {"Targets": [{"Id": "lambda"}]}

    result = environment.deploy_function(
        packaged_function,
        CloudFunctionConfig(
            function_name="demo",
            auto_create_role=False,
            schedules=[Calendar(schedule="Mon 09:00")],
        ),
    )

    assert result.success
    clients["events"].delete_rule.assert_called_once_with(Name=f"{prefix}1")
    clients["events"].remove_targets.assert_called_once_with(Rule=f"{prefix}1", Ids=["lambda"])


def test_boto_backend_auto_creates_execution_role():
    environment, clients = boto_environment()
    environment.config.execution_role_arn = None
    clients["iam"].get_role.side_effect = client_error("NoSuchEntity")
    clients["iam"].create_role.return_value = {"Role": {"Arn": "arn:aws:iam::123:role/demo-role"}}

    result = environment.deploy_function(
        packaged_function,
        CloudFunctionConfig(function_name="demo", auto_create_role=True),
    )

    assert result.success
    clients["iam"].create_role.assert_called_once()
    clients["iam"].attach_role_policy.assert_called()


def test_boto_backend_uses_s3_for_large_package(monkeypatch):
    environment, clients = boto_environment()
    environment.config.deployment_bucket = "deployments"
    clients["s3"] = MagicMock()
    environment._clients["s3"] = clients["s3"]
    clients["s3"].put_object.return_value = {"VersionId": "v1"}
    monkeypatch.setattr("taskflows.cloud.aws_lambda.DIRECT_UPLOAD_LIMIT", 1)

    result = environment.deploy_function(
        packaged_function,
        CloudFunctionConfig(function_name="demo", auto_create_role=False),
    )

    assert result.success
    update = clients["lambda"].update_function_code.call_args.kwargs
    assert update["S3Bucket"] == "deployments"
    assert update["S3ObjectVersion"] == "v1"


def test_boto_backend_rolls_alias_back_to_previous_version():
    environment, clients = boto_environment()
    clients["lambda"].list_aliases.return_value = {"Aliases": [{"Name": "live"}]}
    clients["lambda"].list_versions_by_function.return_value = {
        "Versions": [{"Version": "$LATEST"}, {"Version": "1"}, {"Version": "2"}]
    }
    clients["lambda"].get_alias.return_value = {"FunctionVersion": "2"}
    clients["lambda"].update_alias.side_effect = None
    clients["lambda"].update_alias.return_value = {
        "AliasArn": "arn:aws:lambda:us-east-1:123:function:demo:live"
    }

    result = environment.rollback_function("demo")

    assert result.success
    assert result.version == "1"
    clients["lambda"].update_alias.assert_called_once_with(
        FunctionName="demo", Name="live", FunctionVersion="1"
    )


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
        create_alias="live",
        provisioned_concurrency=1,
        retry_config=RetryConfig(max_retry_attempts=1),
        schedules=[Calendar(schedule="Mon 09:00")],
        monitoring=MonitoringConfig(enable_cloudwatch_alarms=True),
    )
    package = create_lambda_deployment_package(packaged_function)

    resources = environment._create_lambda_infrastructure(config, package, use_s3=False)

    assert "function" in resources
    assert "alias" in resources
    assert "event_invoke_config" in resources
    assert "provisioned_concurrency" in resources
    assert "schedule_rules" in resources
    assert "alarms" in resources
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
    "schedule",
    [
        Calendar(schedule="Mon 09:00:01"),
        Calendar(schedule="Mon 09:00 America/New_York"),
    ],
)
def test_calendar_translation_rejects_lossy_schedules(schedule):
    with pytest.raises(ValueError):
        _calendar_to_cron(schedule)


@pytest.mark.parametrize(
    ("timeout", "memory", "name"),
    [(0, 128, "valid"), (901, 128, "valid"), (60, 127, "valid"), (60, 128, "bad name")],
)
def test_lambda_constraints_reject_invalid_values(timeout, memory, name):
    with pytest.raises(ValueError):
        validate_lambda_constraints(timeout, memory, name)


@pytest.mark.parametrize(
    "overrides",
    [
        {"ephemeral_storage_mb": 511},
        {"architecture": "sparc"},
        {"provisioned_concurrency": 0},
        {"enable_versioning": False, "provisioned_concurrency": 1},
        {"retry_config": RetryConfig(max_retry_attempts=3)},
    ],
)
def test_cloud_function_config_rejects_invalid_values(overrides):
    with pytest.raises(ValueError):
        CloudFunctionConfig(function_name="demo", **overrides)


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


def test_parse_schedule_rejects_invalid_list_item():
    manager = DeploymentManager.__new__(DeploymentManager)
    with pytest.raises(ValueError, match="Schedule objects"):
        manager._parse_schedule(["Mon 09:00"])


def test_pulumi_uses_a_distinct_stable_stack_per_function():
    pytest.importorskip("pulumi")
    from taskflows.cloud.pulumi_aws import PulumiAWSEnvironment

    environment = PulumiAWSEnvironment.__new__(PulumiAWSEnvironment)
    environment.stack_name = "production"

    first = environment._function_stack_name("first")
    assert first == environment._function_stack_name("first")
    assert first != environment._function_stack_name("second")
