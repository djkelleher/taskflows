"""AWS Lambda deployment environment backed directly by boto3."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    import boto3
    from botocore.exceptions import ClientError

    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    boto3 = None
    ClientError = Exception

from ..common import logger
from .base import (
    CloudDeploymentResult,
    CloudEnvironment,
    CloudFunctionConfig,
    LayerConfig,
)
from .utils import (
    create_lambda_deployment_package,
    schedule_to_eventbridge_expression,
    validate_aws_lambda_config,
    validate_lambda_package,
)

DIRECT_UPLOAD_LIMIT = 50 * 1024 * 1024
_MANAGED_ALIAS_TAG = "taskflows:managed-alias"
_MANAGED_TAG_KEYS_TAG = "taskflows:managed-tag-keys"
_MANAGED_ROLE_TAG = "taskflows:managed-role"
_MANAGED_POLICY_ARNS_TAG = "taskflows:managed-policy-arns"


@dataclass
class AWSLambdaConfig:
    """AWS-specific configuration for Lambda deployment."""

    region: str = "us-east-1"
    execution_role_arn: str | None = None
    deployment_bucket: str | None = None
    kms_key_arn: str | None = None
    # KMS controls for Lambda environment variables and S3 deployment objects
    # are separate AWS features. ``kms_key_arn`` is retained as a compatibility
    # fallback for callers of the initial beta API.
    lambda_kms_key_arn: str | None = None
    deployment_kms_key_arn: str | None = None
    vpc_config: dict[str, list[str]] | None = None


def _error_code(error: Exception) -> str | None:
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        return str(code) if code is not None else None
    return None


class AWSLambdaEnvironment(CloudEnvironment):
    """Create and manage scheduled AWS Lambda functions.

    The backend owns Lambda configuration, Taskflows-prefixed EventBridge
    rules, optional aliases, async retry settings, and CloudWatch alarms. AWS
    clients can be injected for testing or custom botocore configuration.
    """

    def __init__(
        self,
        aws_config: AWSLambdaConfig | None = None,
        *,
        clients: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if not BOTO3_AVAILABLE:
            raise ImportError(
                "boto3 is required for AWS Lambda deployment. "
                "Install it with: pip install 'taskflows[aws]'"
            )
        self.config = aws_config or AWSLambdaConfig(**kwargs)
        self._clients = dict(clients or {})
        # Preserve these attributes for compatibility while keeping less common
        # clients lazy (and avoiding unnecessary credential lookups).
        self.lambda_client = self._client("lambda")
        self.events_client = self._client("events")
        self.logs_client = self._client("logs")
        self.iam_client = self._client("iam")

    def _client(self, service: str) -> Any:
        if service not in self._clients:
            self._clients[service] = boto3.client(service, region_name=self.config.region)
        return self._clients[service]

    def deploy_function(
        self,
        function: Callable[[], None],
        config: CloudFunctionConfig,
        dependencies: list[str] | None = None,
    ) -> CloudDeploymentResult:
        """Deploy or reconcile a Lambda function and its managed resources."""
        try:
            self._validate_config(config)
            package = create_lambda_deployment_package(
                function,
                dependencies,
                runtime=config.runtime,
                architecture=config.architecture,
                use_docker=config.build_dependencies_in_docker,
            )
            compressed_size, extracted_size = validate_lambda_package(package)
            code, package_location = self._prepare_code(config, package)
            dlq_arn = self._resolve_dlq(config)
            role_arn = self._get_execution_role_arn(config, dlq_arn)
            function_arn, version = self._create_or_update_function(config, code, role_arn, dlq_arn)

            previous_alias = self._managed_alias(function_arn)
            alias_arn = self._reconcile_alias(
                config.function_name,
                function_arn,
                config.create_alias,
                version,
                previous_alias,
            )

            invoke_arn = alias_arn or function_arn
            rule_arns = self._reconcile_eventbridge_schedules(
                config.function_name,
                invoke_arn,
                config.schedules or [],
                qualifier=config.create_alias,
                previous_qualifier=previous_alias,
            )
            self._configure_async_invocation(
                config,
                qualifier=config.create_alias,
                previous_qualifier=previous_alias,
            )
            self._configure_concurrency(
                config,
                qualifier=config.create_alias or version,
                previous_qualifier=previous_alias,
            )
            self._configure_log_retention(config)
            self._configure_alarms(config)
            self._reconcile_tags(
                function_arn,
                config.tags or {},
                managed_alias=config.create_alias,
            )

            return CloudDeploymentResult(
                success=True,
                resource_id=function_arn,
                version=version,
                rollback_id=config.create_alias,
                endpoint=alias_arn,
                metadata={
                    "function_name": config.function_name,
                    "region": self.config.region,
                    "runtime": config.runtime,
                    "schedule_rules": rule_arns,
                    "package_location": package_location,
                    "package_size_mb": round(compressed_size / 1024 / 1024, 2),
                    "extracted_size_mb": round(extracted_size / 1024 / 1024, 2),
                },
            )
        except Exception as error:
            logger.error(f"Failed to deploy function {config.function_name}: {error}")
            return CloudDeploymentResult(False, "", error=str(error))

    def _validate_config(self, config: CloudFunctionConfig) -> None:
        validate_aws_lambda_config(config)
        external_role = config.execution_role_arn or self.config.execution_role_arn
        if external_role and config.additional_iam_policies:
            raise ValueError(
                "additional_iam_policies can only be attached to an auto-created execution role"
            )
        if external_role and config.dead_letter_config and config.dead_letter_config.auto_create:
            raise ValueError(
                "auto_create DLQ requires an auto-created role; otherwise provide a target ARN "
                "and grant the role permission to publish to it"
            )

    def _prepare_code(
        self, config: CloudFunctionConfig, package: bytes
    ) -> tuple[dict[str, Any], str]:
        if len(package) <= DIRECT_UPLOAD_LIMIT:
            return {"ZipFile": package}, "direct"
        if not config.use_s3_for_large_packages:
            raise ValueError("deployment package exceeds Lambda's 50 MB direct-upload limit")
        if not self.config.deployment_bucket:
            raise ValueError(
                "deployment_bucket is required for packages above the 50 MB direct-upload limit"
            )
        digest = hashlib.sha256(package).hexdigest()
        key = f"taskflows/lambda/{config.function_name}/{digest}.zip"
        put_args: dict[str, Any] = {
            "Bucket": self.config.deployment_bucket,
            "Key": key,
            "Body": package,
        }
        if self.config.deployment_kms_key_arn:
            put_args.update(
                ServerSideEncryption="aws:kms",
                SSEKMSKeyId=self.config.deployment_kms_key_arn,
            )
        response = self._client("s3").put_object(**put_args)
        code: dict[str, Any] = {"S3Bucket": self.config.deployment_bucket, "S3Key": key}
        if response.get("VersionId"):
            code["S3ObjectVersion"] = response["VersionId"]
        return code, f"s3://{self.config.deployment_bucket}/{key}"

    def _resolve_dlq(self, config: CloudFunctionConfig) -> str | None:
        dlq = config.dead_letter_config
        if not dlq:
            return None
        if dlq.target_arn:
            return dlq.target_arn
        if not dlq.auto_create:
            return None
        queue_name = f"{config.function_name}-dlq"
        sqs = self._client("sqs")
        queue_url = sqs.create_queue(
            QueueName=queue_name,
            Attributes={
                "MessageRetentionPeriod": "1209600",
                **({"KmsMasterKeyId": dlq.kms_key_arn} if dlq.kms_key_arn else {}),
            },
            tags=config.tags or {},
        )["QueueUrl"]
        arn = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])[
            "Attributes"
        ]["QueueArn"]
        return str(arn)

    def _get_execution_role_arn(
        self, config: CloudFunctionConfig, dlq_arn: str | None = None
    ) -> str:
        if config.execution_role_arn:
            return config.execution_role_arn
        if self.config.execution_role_arn:
            return self.config.execution_role_arn
        if not config.auto_create_role:
            raise ValueError("execution_role_arn is required when auto_create_role=False")

        role_name = config.role_name or f"{config.function_name}-role"
        role_created = False
        try:
            role = self.iam_client.get_role(RoleName=role_name)["Role"]
        except ClientError as error:
            if _error_code(error) != "NoSuchEntity":
                raise
            assume_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "lambda.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            }
            args: dict[str, Any] = {
                "RoleName": role_name,
                "AssumeRolePolicyDocument": json.dumps(assume_policy),
                "Description": f"Execution role for Taskflows function {config.function_name}",
            }
            if config.tags:
                args["Tags"] = [{"Key": key, "Value": value} for key, value in config.tags.items()]
            args.setdefault("Tags", []).append({"Key": _MANAGED_ROLE_TAG, "Value": "true"})
            role = self.iam_client.create_role(**args)["Role"]
            role_created = True

        if not role_created and not self._role_is_managed(role_name):
            raise ValueError(
                f"execution role {role_name!r} exists but is not managed by Taskflows; "
                "provide execution_role_arn or tag the role for Taskflows ownership"
            )

        policy_arns = [
            "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
            *(config.additional_iam_policies or []),
        ]
        if self._vpc_config(config):
            policy_arns.append(
                "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
            )
        policy_arns = list(dict.fromkeys(policy_arns))
        for policy_arn in self._managed_role_policies(role_name) - set(policy_arns):
            self.iam_client.detach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
        for policy_arn in policy_arns:
            self.iam_client.attach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
        dlq_kms_key_arn = (
            config.dead_letter_config.kms_key_arn if config.dead_letter_config and dlq_arn else None
        )
        if dlq_arn:
            statements: list[dict[str, Any]] = [
                {
                    "Effect": "Allow",
                    "Action": "sqs:SendMessage" if ":sqs:" in dlq_arn else "sns:Publish",
                    "Resource": dlq_arn,
                }
            ]
            if dlq_kms_key_arn:
                statements.append(
                    {
                        "Effect": "Allow",
                        "Action": ["kms:Decrypt", "kms:GenerateDataKey"],
                        "Resource": dlq_kms_key_arn,
                    }
                )
            self.iam_client.put_role_policy(
                RoleName=role_name,
                PolicyName="TaskflowsDeadLetterQueue",
                PolicyDocument=json.dumps(
                    {
                        "Version": "2012-10-17",
                        "Statement": statements,
                    }
                ),
            )
        elif not role_created:
            try:
                self.iam_client.delete_role_policy(
                    RoleName=role_name,
                    PolicyName="TaskflowsDeadLetterQueue",
                )
            except ClientError as error:
                if _error_code(error) != "NoSuchEntity":
                    raise
        self.iam_client.tag_role(
            RoleName=role_name,
            Tags=[
                {"Key": _MANAGED_ROLE_TAG, "Value": "true"},
                {
                    "Key": _MANAGED_POLICY_ARNS_TAG,
                    "Value": json.dumps(policy_arns, separators=(",", ":")),
                },
            ],
        )
        return str(role["Arn"])

    def _role_is_managed(self, role_name: str) -> bool:
        response = self.iam_client.list_role_tags(RoleName=role_name)
        tags = response.get("Tags", []) if isinstance(response, dict) else []
        return any(
            tag.get("Key") == _MANAGED_ROLE_TAG and tag.get("Value") == "true"
            for tag in tags
            if isinstance(tag, dict)
        )

    def _managed_role_policies(self, role_name: str) -> set[str]:
        response = self.iam_client.list_role_tags(RoleName=role_name)
        tags = response.get("Tags", []) if isinstance(response, dict) else []
        for tag in tags:
            if isinstance(tag, dict) and tag.get("Key") == _MANAGED_POLICY_ARNS_TAG:
                try:
                    values = json.loads(str(tag.get("Value", "[]")))
                except json.JSONDecodeError:
                    return set()
                return {str(value) for value in values} if isinstance(values, list) else set()
        return set()

    def _vpc_config(self, config: CloudFunctionConfig) -> dict[str, Any] | None:
        if config.vpc_config:
            return config.vpc_config
        if config.security_group_ids or config.subnet_ids:
            if not config.security_group_ids or not config.subnet_ids:
                raise ValueError("both security_group_ids and subnet_ids are required for a VPC")
            return {
                "SecurityGroupIds": config.security_group_ids,
                "SubnetIds": config.subnet_ids,
            }
        return self.config.vpc_config

    def _layer_arns(self, config: CloudFunctionConfig) -> list[str]:
        arns = []
        for layer in config.layers or []:
            if layer.layer_arn:
                arns.append(layer.layer_arn)
            else:
                arns.append(self.create_layer(layer))
        return arns

    def _function_configuration(
        self,
        config: CloudFunctionConfig,
        role_arn: str,
        dlq_arn: str | None,
        *,
        for_update: bool = False,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {
            "FunctionName": config.function_name,
            "Description": config.description or "",
            "Runtime": config.runtime,
            "Role": role_arn,
            "Handler": config.handler,
            "Timeout": config.timeout_seconds,
            "MemorySize": config.memory_mb,
            "Environment": {"Variables": config.environment_variables or {}},
            "TracingConfig": {"Mode": "Active" if config.enable_xray_tracing else "PassThrough"},
            "Layers": self._layer_arns(config),
            "EphemeralStorage": {"Size": config.ephemeral_storage_mb},
        }
        vpc = self._vpc_config(config)
        if vpc:
            args["VpcConfig"] = vpc
        elif for_update:
            # Lambda treats omitted fields as "leave unchanged". Empty
            # collections are required to detach a previous VPC or EFS mount.
            args["VpcConfig"] = {"SecurityGroupIds": [], "SubnetIds": []}
        if dlq_arn:
            args["DeadLetterConfig"] = {"TargetArn": dlq_arn}
        elif for_update:
            args["DeadLetterConfig"] = {}
        lambda_kms_key_arn = self.config.lambda_kms_key_arn or self.config.kms_key_arn
        if lambda_kms_key_arn:
            args["KMSKeyArn"] = lambda_kms_key_arn
        elif for_update:
            args["KMSKeyArn"] = ""
        if config.file_system_configs:
            args["FileSystemConfigs"] = config.file_system_configs
        elif for_update:
            args["FileSystemConfigs"] = []
        return args

    def _create_or_update_function(
        self,
        config: CloudFunctionConfig,
        code: dict[str, Any],
        role_arn: str,
        dlq_arn: str | None,
    ) -> tuple[str, str]:
        common = self._function_configuration(config, role_arn, dlq_arn)
        try:
            existing = self.lambda_client.get_function(FunctionName=config.function_name)
        except ClientError as error:
            if _error_code(error) != "ResourceNotFoundException":
                raise
            existing = None

        if existing is None:
            create_args = {
                **common,
                "Code": code,
                "Publish": config.enable_versioning,
                "Architectures": [config.architecture],
            }
            if config.tags:
                create_args["Tags"] = config.tags
            if config.code_signing_config_arn:
                create_args["CodeSigningConfigArn"] = config.code_signing_config_arn
            # Newly created IAM roles can take a few seconds to propagate to
            # Lambda even after IAM returns the role ARN.
            for attempt in range(7):
                try:
                    response = self.lambda_client.create_function(**create_args)
                    break
                except ClientError as error:
                    role_not_ready = (
                        _error_code(error) == "InvalidParameterValueException"
                        and "role" in str(error).lower()
                        and "assum" in str(error).lower()
                    )
                    if not role_not_ready or attempt == 6:
                        raise
                    time.sleep(5)
            self._wait_for_update(config.function_name, waiter_name="function_active_v2")
            version = response.get("Version", "$LATEST")
            function_arn = response["FunctionArn"]
        else:
            if config.code_signing_config_arn:
                self.lambda_client.put_function_code_signing_config(
                    FunctionName=config.function_name,
                    CodeSigningConfigArn=config.code_signing_config_arn,
                )
            elif existing.get("Configuration", {}).get("CodeSigningConfigArn"):
                self.lambda_client.delete_function_code_signing_config(
                    FunctionName=config.function_name,
                )
            code_response = self.lambda_client.update_function_code(
                FunctionName=config.function_name,
                Architectures=[config.architecture],
                Publish=False,
                **code,
            )
            self._wait_for_update(config.function_name)
            response = self.lambda_client.update_function_configuration(
                **self._function_configuration(config, role_arn, dlq_arn, for_update=True)
            )
            self._wait_for_update(config.function_name)
            function_arn = response.get("FunctionArn") or existing["Configuration"]["FunctionArn"]
            if config.enable_versioning:
                version = self.lambda_client.publish_version(
                    FunctionName=config.function_name,
                    CodeSha256=code_response.get("CodeSha256", ""),
                )["Version"]
            else:
                version = "$LATEST"
            if config.tags:
                self.lambda_client.tag_resource(Resource=function_arn, Tags=config.tags)
        return function_arn, version

    def _wait_for_update(
        self, function_name: str, waiter_name: str = "function_updated_v2"
    ) -> None:
        try:
            waiter = self.lambda_client.get_waiter(waiter_name)
        except ValueError:
            waiter = self.lambda_client.get_waiter(waiter_name.removesuffix("_v2"))
        waiter.wait(FunctionName=function_name)

    def _set_alias(self, function_name: str, alias_name: str, version: str) -> str:
        try:
            response = self.lambda_client.update_alias(
                FunctionName=function_name,
                Name=alias_name,
                FunctionVersion=version,
            )
        except ClientError as error:
            if _error_code(error) != "ResourceNotFoundException":
                raise
            response = self.lambda_client.create_alias(
                FunctionName=function_name,
                Name=alias_name,
                FunctionVersion=version,
            )
        return str(response["AliasArn"])

    def _managed_alias(self, function_arn: str) -> str | None:
        """Read the alias recorded by the function's persistent management tag."""
        try:
            response = self.lambda_client.list_tags(Resource=function_arn)
        except ClientError:
            return None
        tags = response.get("Tags", {}) if isinstance(response, dict) else {}
        alias = tags.get(_MANAGED_ALIAS_TAG) if isinstance(tags, dict) else None
        return str(alias) if alias else None

    def _reconcile_alias(
        self,
        function_name: str,
        function_arn: str,
        desired_alias: str | None,
        version: str,
        previous_alias: str | None,
    ) -> str | None:
        """Move the managed alias and remove its old qualifier resources.

        Lambda aliases are not taggable, so the function tag is the durable
        ownership record. Unmarked aliases are intentionally left untouched.
        """
        if previous_alias and previous_alias != desired_alias:
            self._clear_async_invocation(function_name, previous_alias)
            self._clear_provisioned_concurrency(function_name, previous_alias)
            try:
                self.lambda_client.delete_alias(FunctionName=function_name, Name=previous_alias)
            except ClientError as error:
                if _error_code(error) != "ResourceNotFoundException":
                    raise
        if desired_alias:
            return self._set_alias(function_name, desired_alias, version)
        return None

    @staticmethod
    def _schedule_prefix(function_name: str) -> str:
        digest = hashlib.sha256(function_name.encode()).hexdigest()[:8]
        return f"tf-{function_name[:40]}-{digest}-schedule-"

    def _reconcile_eventbridge_schedules(
        self,
        function_name: str,
        function_arn: str,
        schedules: list[Any],
        *,
        qualifier: str | None,
        previous_qualifier: str | None,
    ) -> list[str]:
        prefix = self._schedule_prefix(function_name)
        desired_names = {f"{prefix}{index}" for index in range(len(schedules))}
        existing_names = set(self._list_rule_names(prefix))

        for stale_name in existing_names - desired_names:
            self._delete_rule(function_name, stale_name, qualifier=previous_qualifier)

        rule_arns = []
        for index, schedule in enumerate(schedules):
            rule_name = f"{prefix}{index}"
            response = self.events_client.put_rule(
                Name=rule_name,
                ScheduleExpression=schedule_to_eventbridge_expression(schedule),
                State="ENABLED",
                Description=f"Taskflows schedule for {function_name}",
            )
            rule_arn = response["RuleArn"]
            statement_id = f"{rule_name}-invoke"
            permission_args = {
                "FunctionName": function_name,
                "StatementId": statement_id,
            }
            old_permission_args = dict(permission_args)
            if previous_qualifier:
                old_permission_args["Qualifier"] = previous_qualifier
            self._remove_permission(old_permission_args)
            new_permission_args = dict(permission_args)
            if qualifier:
                new_permission_args["Qualifier"] = qualifier
            self._remove_permission(new_permission_args)
            self.lambda_client.add_permission(
                **new_permission_args,
                Action="lambda:InvokeFunction",
                Principal="events.amazonaws.com",
                SourceArn=rule_arn,
            )
            failed = self.events_client.put_targets(
                Rule=rule_name,
                Targets=[{"Id": "lambda", "Arn": function_arn}],
            ).get("FailedEntryCount", 0)
            if failed:
                raise RuntimeError(
                    f"failed to attach Lambda target to EventBridge rule {rule_name}"
                )
            rule_arns.append(rule_arn)
        return rule_arns

    def _remove_permission(self, args: dict[str, Any]) -> None:
        try:
            self.lambda_client.remove_permission(**args)
        except ClientError as error:
            if _error_code(error) != "ResourceNotFoundException":
                raise

    def _list_rule_names(self, prefix: str) -> list[str]:
        names: list[str] = []
        token = None
        while True:
            args = {"NamePrefix": prefix}
            if token:
                args["NextToken"] = token
            response = self.events_client.list_rules(**args)
            names.extend(rule["Name"] for rule in response.get("Rules", []))
            token = response.get("NextToken")
            if not token:
                return names

    def _delete_rule(
        self, function_name: str, rule_name: str, *, qualifier: str | None = None
    ) -> None:
        target_ids: list[str] = []
        token = None
        while True:
            args = {"Rule": rule_name}
            if token:
                args["NextToken"] = token
            response = self.events_client.list_targets_by_rule(**args)
            target_ids.extend(target["Id"] for target in response.get("Targets", []))
            token = response.get("NextToken")
            if not token:
                break
        if target_ids:
            self.events_client.remove_targets(Rule=rule_name, Ids=target_ids)
        self.events_client.delete_rule(Name=rule_name)
        permission_args = {
            "FunctionName": function_name,
            "StatementId": f"{rule_name}-invoke",
        }
        if qualifier:
            permission_args["Qualifier"] = qualifier
        self._remove_permission(permission_args)

    def _clear_async_invocation(self, function_name: str, qualifier: str | None) -> None:
        args: dict[str, Any] = {"FunctionName": function_name}
        if qualifier:
            args["Qualifier"] = qualifier
        try:
            self.lambda_client.delete_function_event_invoke_config(**args)
        except ClientError as error:
            if _error_code(error) != "ResourceNotFoundException":
                raise

    def _configure_async_invocation(
        self,
        config: CloudFunctionConfig,
        *,
        qualifier: str | None,
        previous_qualifier: str | None,
    ) -> None:
        if previous_qualifier and previous_qualifier != qualifier:
            self._clear_async_invocation(config.function_name, previous_qualifier)
        if not config.retry_config:
            self._clear_async_invocation(config.function_name, qualifier)
            return
        args: dict[str, Any] = {
            "FunctionName": config.function_name,
            "MaximumRetryAttempts": config.retry_config.max_retry_attempts,
            "MaximumEventAgeInSeconds": config.retry_config.max_event_age_seconds,
        }
        if qualifier:
            args["Qualifier"] = qualifier
        self.lambda_client.put_function_event_invoke_config(**args)

    def _clear_provisioned_concurrency(self, function_name: str, qualifier: str) -> None:
        try:
            self.lambda_client.delete_provisioned_concurrency_config(
                FunctionName=function_name,
                Qualifier=qualifier,
            )
        except ClientError as error:
            if _error_code(error) != "ResourceNotFoundException":
                raise

    def _configure_concurrency(
        self,
        config: CloudFunctionConfig,
        *,
        qualifier: str,
        previous_qualifier: str | None,
    ) -> None:
        if config.reserved_concurrent_executions is None:
            try:
                self.lambda_client.delete_function_concurrency(FunctionName=config.function_name)
            except ClientError as error:
                if _error_code(error) != "ResourceNotFoundException":
                    raise
        else:
            self.lambda_client.put_function_concurrency(
                FunctionName=config.function_name,
                ReservedConcurrentExecutions=config.reserved_concurrent_executions,
            )
        if previous_qualifier and previous_qualifier != qualifier:
            self._clear_provisioned_concurrency(config.function_name, previous_qualifier)
        if config.provisioned_concurrency is not None:
            self.lambda_client.put_provisioned_concurrency_config(
                FunctionName=config.function_name,
                Qualifier=qualifier,
                ProvisionedConcurrentExecutions=config.provisioned_concurrency,
            )
        elif not previous_qualifier or previous_qualifier == qualifier:
            self._clear_provisioned_concurrency(config.function_name, qualifier)

    def _reconcile_tags(
        self,
        function_arn: str,
        desired_tags: dict[str, str],
        *,
        managed_alias: str | None,
    ) -> None:
        current: dict[str, str] = {}
        try:
            response = self.lambda_client.list_tags(Resource=function_arn)
            if isinstance(response, dict) and isinstance(response.get("Tags"), dict):
                current = {str(key): str(value) for key, value in response["Tags"].items()}
        except ClientError:
            # Tag reconciliation must not turn a successful deployment into a
            # failure when the caller lacks the optional tagging permission.
            logger.warning("Could not read Lambda tags for %s", function_arn)

        managed_keys: set[str] = set()
        try:
            decoded = json.loads(current.get(_MANAGED_TAG_KEYS_TAG, "[]"))
            if isinstance(decoded, list):
                managed_keys = {str(key) for key in decoded}
        except json.JSONDecodeError:
            pass
        stale = managed_keys - set(desired_tags)
        if stale:
            self.lambda_client.untag_resource(Resource=function_arn, TagKeys=sorted(stale))
        tags = dict(desired_tags)
        tags[_MANAGED_ALIAS_TAG] = managed_alias or ""
        tags[_MANAGED_TAG_KEYS_TAG] = json.dumps(sorted(desired_tags), separators=(",", ":"))
        self.lambda_client.tag_resource(Resource=function_arn, Tags=tags)

    def _configure_log_retention(self, config: CloudFunctionConfig) -> None:
        group = f"/aws/lambda/{config.function_name}"
        try:
            self.logs_client.create_log_group(logGroupName=group, tags=config.tags or {})
        except ClientError as error:
            if _error_code(error) != "ResourceAlreadyExistsException":
                raise
        if config.log_retention_days:
            self.logs_client.put_retention_policy(
                logGroupName=group,
                retentionInDays=config.log_retention_days,
            )
        else:
            self.logs_client.delete_retention_policy(logGroupName=group)

    def _configure_alarms(self, config: CloudFunctionConfig) -> None:
        monitoring = config.monitoring
        # ``None`` means the caller did not manage monitoring in this
        # deployment. Do not create a CloudWatch client (and do not touch
        # existing alarms) in that case; this keeps partial configuration
        # updates non-destructive.
        if monitoring is None:
            return
        cloudwatch = self._client("cloudwatch")
        alarm_names = {
            f"{config.function_name}-error-rate",
            f"{config.function_name}-duration",
        }
        desired_names: set[str] = set()
        if monitoring and monitoring.enable_cloudwatch_alarms:
            if monitoring.error_rate_threshold is not None:
                desired_names.add(f"{config.function_name}-error-rate")
            if monitoring.duration_threshold_ms is not None:
                desired_names.add(f"{config.function_name}-duration")
        stale_names = alarm_names - desired_names
        if stale_names:
            cloudwatch.delete_alarms(AlarmNames=sorted(stale_names))
        if not monitoring or not monitoring.enable_cloudwatch_alarms:
            return
        actions = [monitoring.alarm_sns_topic_arn] if monitoring.alarm_sns_topic_arn else []
        if monitoring.error_rate_threshold is not None:
            cloudwatch.put_metric_alarm(
                AlarmName=f"{config.function_name}-error-rate",
                ComparisonOperator="GreaterThanThreshold",
                EvaluationPeriods=2,
                Threshold=monitoring.error_rate_threshold,
                TreatMissingData="notBreaching",
                AlarmActions=actions,
                Metrics=[
                    {
                        "Id": "errors",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": "AWS/Lambda",
                                "MetricName": "Errors",
                                "Dimensions": [
                                    {"Name": "FunctionName", "Value": config.function_name}
                                ],
                            },
                            "Period": 300,
                            "Stat": "Sum",
                        },
                        "ReturnData": False,
                    },
                    {
                        "Id": "invocations",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": "AWS/Lambda",
                                "MetricName": "Invocations",
                                "Dimensions": [
                                    {"Name": "FunctionName", "Value": config.function_name}
                                ],
                            },
                            "Period": 300,
                            "Stat": "Sum",
                        },
                        "ReturnData": False,
                    },
                    {
                        "Id": "rate",
                        "Expression": "IF(invocations>0,errors/invocations,0)",
                        "Label": "Error rate",
                        "ReturnData": True,
                    },
                ],
            )
        if monitoring.duration_threshold_ms is not None:
            cloudwatch.put_metric_alarm(
                AlarmName=f"{config.function_name}-duration",
                ComparisonOperator="GreaterThanThreshold",
                EvaluationPeriods=2,
                MetricName="Duration",
                Namespace="AWS/Lambda",
                Period=300,
                Statistic="Average",
                Threshold=monitoring.duration_threshold_ms,
                Dimensions=[{"Name": "FunctionName", "Value": config.function_name}],
                TreatMissingData="notBreaching",
                AlarmActions=actions,
            )

    def invoke_function(
        self,
        function_name: str,
        payload: dict[str, Any] | None = None,
        invocation_type: str = "RequestResponse",
    ) -> dict[str, Any]:
        if invocation_type not in {"RequestResponse", "Event", "DryRun"}:
            raise ValueError("invocation_type must be RequestResponse, Event, or DryRun")
        args: dict[str, Any] = {
            "FunctionName": function_name,
            "InvocationType": invocation_type,
        }
        if payload is not None:
            args["Payload"] = json.dumps(payload).encode()
        try:
            response = self.lambda_client.invoke(**args)
            result: dict[str, Any] = {
                "StatusCode": response["StatusCode"],
                "ExecutedVersion": response.get("ExecutedVersion"),
            }
            stream = response.get("Payload")
            if stream is not None:
                raw = stream.read()
                if raw:
                    try:
                        result["Payload"] = json.loads(raw)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        result["Payload"] = raw.decode(errors="replace")
            if response.get("FunctionError"):
                result["Error"] = response["FunctionError"]
            return result
        except Exception as error:
            logger.error(f"Failed to invoke function {function_name}: {error}")
            return {"Error": str(error)}

    def delete_function(self, function_name: str) -> bool:
        try:
            for rule_name in self._list_rule_names(self._schedule_prefix(function_name)):
                self._delete_rule(function_name, rule_name)
            self.lambda_client.delete_function(FunctionName=function_name)
            return True
        except ClientError as error:
            if _error_code(error) == "ResourceNotFoundException":
                return True
            logger.error(f"Failed to delete function {function_name}: {error}")
            return False

    def get_function_logs(
        self,
        function_name: str,
        limit: int = 100,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[str]:
        if limit < 1:
            raise ValueError("limit must be positive")
        args: dict[str, Any] = {
            "logGroupName": f"/aws/lambda/{function_name}",
            "limit": min(limit, 10_000),
            "interleaved": True,
        }
        if start_time is not None:
            args["startTime"] = start_time
        if end_time is not None:
            args["endTime"] = end_time
        try:
            events = self.logs_client.filter_log_events(**args).get("events", [])
            return [
                f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(event['timestamp'] / 1000))} UTC] "
                f"{event['message']}"
                for event in events[:limit]
            ]
        except ClientError as error:
            if _error_code(error) == "ResourceNotFoundException":
                return []
            logger.error(f"Failed to get logs for {function_name}: {error}")
            return [f"Error retrieving logs: {error}"]

    def list_functions(self) -> list[dict[str, Any]]:
        functions: list[dict[str, Any]] = []
        marker = None
        try:
            while True:
                args: dict[str, Any] = {"Marker": marker} if marker else {}
                response = self.lambda_client.list_functions(**args)
                functions.extend(
                    {
                        "name": item["FunctionName"],
                        "arn": item["FunctionArn"],
                        "runtime": item.get("Runtime"),
                        "memory": item.get("MemorySize"),
                        "timeout": item.get("Timeout"),
                        "last_modified": item.get("LastModified"),
                        "version": item.get("Version"),
                    }
                    for item in response.get("Functions", [])
                )
                marker = response.get("NextMarker")
                if not marker:
                    return functions
        except ClientError as error:
            logger.error(f"Failed to list functions: {error}")
            return []

    def update_function_code(
        self,
        function_name: str,
        function: Callable[[], None],
        dependencies: list[str] | None = None,
    ) -> CloudDeploymentResult:
        try:
            current = self.lambda_client.get_function_configuration(FunctionName=function_name)
            runtime = current.get("Runtime", "python3.11")
            architectures = current.get("Architectures") or ["x86_64"]
            package = create_lambda_deployment_package(
                function,
                dependencies,
                runtime=runtime,
                architecture=architectures[0],
                use_docker=True,
            )
            validate_lambda_package(package)
            package_config = CloudFunctionConfig(
                function_name=function_name,
                runtime=runtime,
                architecture=architectures[0],
                use_s3_for_large_packages=True,
            )
            code, package_location = self._prepare_code(package_config, package)
            response = self.lambda_client.update_function_code(
                FunctionName=function_name,
                Publish=True,
                **code,
            )
            self._wait_for_update(function_name)
            function_arn = response.get("FunctionArn", function_name)
            managed_alias = self._managed_alias(function_arn)
            alias_arn = None
            if managed_alias:
                alias_arn = self._set_alias(function_name, managed_alias, response["Version"])
            return CloudDeploymentResult(
                True,
                function_arn,
                endpoint=alias_arn,
                version=response.get("Version"),
                rollback_id=managed_alias,
                metadata={"updated": "code", "package_location": package_location},
            )
        except Exception as error:
            return CloudDeploymentResult(False, function_name, error=str(error))

    def update_function_configuration(
        self,
        function_name: str,
        config: CloudFunctionConfig,
    ) -> CloudDeploymentResult:
        if function_name != config.function_name:
            return CloudDeploymentResult(
                False, function_name, error="function_name must match config.function_name"
            )
        try:
            self._validate_config(config)
            dlq_arn = self._resolve_dlq(config)
            role_arn = self._get_execution_role_arn(config, dlq_arn)
            response = self.lambda_client.update_function_configuration(
                **self._function_configuration(config, role_arn, dlq_arn, for_update=True)
            )
            self._wait_for_update(function_name)
            function_arn = response.get("FunctionArn", function_name)
            version = "$LATEST"
            if config.enable_versioning:
                version = self.lambda_client.publish_version(FunctionName=function_name)["Version"]
            previous_alias = self._managed_alias(function_arn)
            alias_arn = self._reconcile_alias(
                function_name,
                function_arn,
                config.create_alias,
                version,
                previous_alias,
            )
            rule_arns = self._reconcile_eventbridge_schedules(
                function_name,
                alias_arn or function_arn,
                config.schedules or [],
                qualifier=config.create_alias,
                previous_qualifier=previous_alias,
            )
            self._configure_async_invocation(
                config,
                qualifier=config.create_alias,
                previous_qualifier=previous_alias,
            )
            self._configure_concurrency(
                config,
                qualifier=config.create_alias or version,
                previous_qualifier=previous_alias,
            )
            self._configure_log_retention(config)
            self._configure_alarms(config)
            self._reconcile_tags(function_arn, config.tags or {}, managed_alias=config.create_alias)
            return CloudDeploymentResult(
                True,
                function_arn,
                endpoint=alias_arn,
                version=version,
                rollback_id=config.create_alias,
                metadata={"updated": "configuration", "schedule_rules": rule_arns},
            )
        except Exception as error:
            return CloudDeploymentResult(False, function_name, error=str(error))

    def create_layer(self, layer_config: LayerConfig, requirements_file: Path | None = None) -> str:
        from .dependencies import DependencyManager

        dependencies = list(layer_config.dependencies or [])
        if requirements_file:
            dependencies.extend(DependencyManager().parse_requirements_file(requirements_file))
        package = DependencyManager(
            python_version=layer_config.compatible_runtimes[0].removeprefix("python"),
            architecture=layer_config.compatible_architectures[0],
        ).create_layer_package(
            dependencies,
            runtime=layer_config.compatible_runtimes[0],
            use_docker=layer_config.build_in_docker,
        )
        validate_lambda_package(package)
        if len(package) > DIRECT_UPLOAD_LIMIT:
            raise ValueError("Lambda layer exceeds the 50 MB direct-upload limit")
        response = self.lambda_client.publish_layer_version(
            LayerName=layer_config.layer_name,
            Content={"ZipFile": package},
            CompatibleRuntimes=layer_config.compatible_runtimes,
            CompatibleArchitectures=layer_config.compatible_architectures,
        )
        return str(response["LayerVersionArn"])

    def list_versions(self, function_name: str) -> list[dict[str, Any]]:
        versions = []
        marker = None
        while True:
            args = {"FunctionName": function_name}
            if marker:
                args["Marker"] = marker
            response = self.lambda_client.list_versions_by_function(**args)
            versions.extend(response.get("Versions", []))
            marker = response.get("NextMarker")
            if not marker:
                return versions

    def set_function_alias(self, function_name: str, alias_name: str, version: str) -> bool:
        try:
            self._set_alias(function_name, alias_name, version)
            return True
        except ClientError:
            return False

    def rollback_function(
        self,
        function_name: str,
        version: str | None = None,
        rollback_id: str | None = None,
    ) -> CloudDeploymentResult:
        try:
            alias = rollback_id
            if alias is None:
                aliases = self.lambda_client.list_aliases(FunctionName=function_name).get(
                    "Aliases", []
                )
                if len(aliases) != 1:
                    raise ValueError("rollback_id must name the alias to move")
                alias = aliases[0]["Name"]
            if version is None:
                published = [
                    item["Version"]
                    for item in self.list_versions(function_name)
                    if item["Version"] != "$LATEST"
                ]
                published.sort(key=int)
                if len(published) < 2:
                    raise ValueError("no previous published version is available")
                current = self.lambda_client.get_alias(FunctionName=function_name, Name=alias)[
                    "FunctionVersion"
                ]
                candidates = [item for item in published if int(item) < int(current)]
                if not candidates:
                    raise ValueError("alias already points to the oldest published version")
                version = candidates[-1]
            alias_arn = self._set_alias(function_name, alias, version)
            return CloudDeploymentResult(
                True,
                alias_arn,
                version=version,
                rollback_id=alias,
                metadata={"alias": alias},
            )
        except Exception as error:
            return CloudDeploymentResult(False, function_name, error=str(error))

    def get_function_metrics(
        self,
        function_name: str,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> dict[str, Any]:
        end = datetime.fromtimestamp(end_time / 1000, UTC) if end_time else datetime.now(UTC)
        start = (
            datetime.fromtimestamp(start_time / 1000, UTC)
            if start_time
            else end - timedelta(hours=1)
        )
        if start >= end:
            raise ValueError("start_time must be before end_time")
        cloudwatch = self._client("cloudwatch")

        def metric(name: str, statistic: str) -> list[dict[str, Any]]:
            result = cloudwatch.get_metric_statistics(
                Namespace="AWS/Lambda",
                MetricName=name,
                Dimensions=[{"Name": "FunctionName", "Value": function_name}],
                StartTime=start,
                EndTime=end,
                Period=max(60, min(3600, int((end - start).total_seconds() / 60) or 60)),
                Statistics=[statistic],
            ).get("Datapoints", [])
            return list(result)

        invocations = metric("Invocations", "Sum")
        errors = metric("Errors", "Sum")
        duration = metric("Duration", "Average")
        invocation_count = sum(item["Sum"] for item in invocations)
        error_count = sum(item["Sum"] for item in errors)
        duration_values = [item["Average"] for item in duration]
        return {
            "start_time": start,
            "end_time": end,
            "invocations": invocation_count,
            "errors": error_count,
            "error_rate": error_count / invocation_count if invocation_count else 0.0,
            "average_duration_ms": (
                sum(duration_values) / len(duration_values) if duration_values else None
            ),
        }
