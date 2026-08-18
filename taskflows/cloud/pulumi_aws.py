"""Experimental AWS Lambda deployment using Pulumi Automation API.

Each function is stored in a separate deterministic Pulumi stack. This backend
has not yet been certified by an end-to-end AWS deployment test.

Requirements:
    pip install "taskflows[pulumi]"
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    import pulumi
    import pulumi_aws as aws
    from pulumi import automation as auto
    from pulumi import export

    PULUMI_AVAILABLE = True
except ImportError:
    PULUMI_AVAILABLE = False
    pulumi = None  # type: ignore[assignment]
    aws = None  # type: ignore[assignment]
    auto = None  # type: ignore[assignment]

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


class PulumiAWSEnvironment(CloudEnvironment):
    """Experimental AWS Lambda environment using Pulumi.

    This implementation uses Pulumi for infrastructure as code, providing:
    - Declarative infrastructure management
    - State tracking and drift detection
    - Preview changes before deployment
    - Separate state and lifecycle per function

    Example:
        >>> env = PulumiAWSEnvironment(
        ...     project_name="taskflows-prod",
        ...     stack_name="production",
        ...     region="us-east-1"
        ... )
        >>>
        >>> config = CloudFunctionConfig(
        ...     function_name="my-task",
        ...     schedules=[Calendar(schedule="Mon-Fri 09:00")],
        ...     monitoring=MonitoringConfig(enable_cloudwatch_alarms=True),
        ...     auto_create_role=True
        ... )
        >>>
        >>> result = env.deploy_function(my_function, config)
    """

    def __init__(
        self,
        project_name: str = "taskflows",
        stack_name: str = "dev",
        region: str = "us-east-1",
        work_dir: Path | None = None,
        auto_create_stack: bool = True,
    ):
        """Initialize Pulumi AWS environment.

        Args:
            project_name: Pulumi project name
            stack_name: Pulumi stack name (dev, staging, production)
            region: AWS region
            work_dir: Working directory for Pulumi files (default: temp dir)
            auto_create_stack: Auto-create stack if it doesn't exist
        """
        if not PULUMI_AVAILABLE:
            raise ImportError(
                "Pulumi is required for this deployment backend. "
                "Install with: pip install 'taskflows[pulumi]'"
            )

        self.project_name = project_name
        self.stack_name = stack_name
        self.region = region
        self.work_dir = work_dir or Path.home() / ".taskflows" / "pulumi" / project_name
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.auto_create_stack = auto_create_stack

        # Create project structure
        self._init_pulumi_project()

        # Track deployed resources
        self._deployed_functions: dict[str, dict[str, Any]] = {}

    def _init_pulumi_project(self):
        """Initialize Pulumi project structure."""
        # Create Pulumi.yaml
        pulumi_yaml = self.work_dir / "Pulumi.yaml"
        if not pulumi_yaml.exists():
            pulumi_yaml.write_text(
                f"""name: {self.project_name}
runtime: python
description: TaskFlows cloud deployment infrastructure
"""
            )

        # Create __main__.py (required by Pulumi)
        main_py = self.work_dir / "__main__.py"
        if not main_py.exists():
            main_py.write_text('"""Pulumi program managed by TaskFlows."""\n')

    def deploy_function(
        self,
        function: Callable[[], None],
        config: CloudFunctionConfig,
        dependencies: list[str] | None = None,
    ) -> CloudDeploymentResult:
        """Deploy function using Pulumi infrastructure as code."""

        try:
            validate_aws_lambda_config(config)
            if not config.auto_create_role and not config.execution_role_arn:
                raise ValueError("execution_role_arn is required when auto_create_role=False")
            if config.execution_role_arn and config.additional_iam_policies:
                raise ValueError(
                    "additional_iam_policies can only be attached to an auto-created role"
                )
            if (
                config.execution_role_arn
                and config.dead_letter_config
                and config.dead_letter_config.auto_create
            ):
                raise ValueError("auto_create DLQ requires an auto-created execution role")

            # Create deployment package
            logger.info(f"Creating deployment package for {config.function_name}")
            deployment_package = create_lambda_deployment_package(
                function,
                dependencies,
                runtime=config.runtime,
                architecture=config.architecture,
                use_docker=config.build_dependencies_in_docker,
            )
            validate_lambda_package(deployment_package)
            package_size_mb = len(deployment_package) / (1024 * 1024)

            # Determine deployment method
            use_s3 = config.use_s3_for_large_packages and package_size_mb > 50

            # Create Pulumi program
            def pulumi_program():
                return self._create_lambda_infrastructure(config, deployment_package, use_s3)

            # Execute Pulumi deployment
            stack = self._get_or_create_stack(pulumi_program, config.function_name)
            up_result = stack.up(on_output=logger.info)

            # Extract outputs
            outputs = up_result.outputs
            function_arn_output = outputs.get("function_arn")
            function_version_output = outputs.get("function_version")
            function_arn = function_arn_output.value if function_arn_output else ""
            function_version = function_version_output.value if function_version_output else None

            # Store deployment info
            self._deployed_functions[config.function_name] = {
                "arn": function_arn,
                "version": function_version,
                "config": config,
                "function": function,
                "dependencies": dependencies,
                "stack": stack,
            }

            return CloudDeploymentResult(
                success=True,
                resource_id=function_arn,
                version=function_version,
                metadata={
                    "function_name": config.function_name,
                    "region": self.region,
                    "package_size_mb": round(package_size_mb, 2),
                    "deployment_method": "s3" if use_s3 else "direct",
                    "stack": self._function_stack_name(config.function_name),
                },
            )

        except Exception as e:
            logger.error(f"Failed to deploy {config.function_name}: {e}")
            return CloudDeploymentResult(
                success=False,
                resource_id="",
                error=str(e),
            )

    def preview_function(
        self,
        function: Callable[[], None],
        config: CloudFunctionConfig,
        dependencies: list[str] | None = None,
    ) -> dict[str, int]:
        """Preview a deployment without applying it and return change counts."""
        validate_aws_lambda_config(config)
        package = create_lambda_deployment_package(
            function,
            dependencies,
            runtime=config.runtime,
            architecture=config.architecture,
            use_docker=config.build_dependencies_in_docker,
        )
        validate_lambda_package(package)

        def pulumi_program():
            return self._create_lambda_infrastructure(
                config,
                package,
                config.use_s3_for_large_packages and len(package) > 50 * 1024 * 1024,
            )

        stack = self._get_or_create_stack(pulumi_program, config.function_name)
        result = stack.preview(on_output=logger.info)
        return {str(key): value for key, value in result.change_summary.items()}

    def _create_lambda_infrastructure(
        self,
        config: CloudFunctionConfig,
        deployment_package: bytes,
        use_s3: bool,
    ) -> dict[str, Any]:
        """Create Lambda infrastructure using Pulumi.

        This is the Pulumi program that defines the infrastructure.
        """
        resources: dict[str, Any] = {}

        # Create Dead Letter Queue if configured
        dlq_arn: Any | None = None
        if config.dead_letter_config and config.dead_letter_config.auto_create:
            dlq = self._create_dlq(config)
            dlq_arn = dlq.arn
            resources["dlq"] = dlq
        elif config.dead_letter_config:
            dlq_arn = config.dead_letter_config.target_arn

        # Create IAM role after the DLQ so its send permission can be scoped.
        execution_role_arn: Any
        if config.auto_create_role and not config.execution_role_arn:
            role = self._create_lambda_role(config, dlq_arn)
            execution_role_arn = role.arn
            resources["role"] = role
        else:
            execution_role_arn = config.execution_role_arn

        # Persist the deployment archive for Pulumi's asset APIs.
        package_hash = hashlib.sha256(deployment_package).hexdigest()[:16]
        package_path = self.work_dir / f"{config.function_name}-{package_hash}.zip"
        package_path.write_bytes(deployment_package)

        # Upload to S3 if package is large
        code_args = {}
        if use_s3:
            bucket, s3_obj = self._upload_to_s3(config, package_path)
            code_args = {"s3_bucket": bucket.id, "s3_key": s3_obj.key}
            resources["bucket"] = bucket
            resources["s3_object"] = s3_obj
        else:
            code_args = {"code": pulumi.FileArchive(str(package_path))}

        # Create Lambda Layers if specified
        layer_arns: list[Any] = []
        if config.layers:
            for layer_config in config.layers:
                if layer_config.layer_arn:
                    layer_arns.append(layer_config.layer_arn)
                elif layer_config.layer_name:
                    layer = self._create_lambda_layer(layer_config)
                    layer_arns.append(layer.arn)
                    resources[f"layer_{layer_config.layer_name}"] = layer

        # Build Lambda function configuration
        lambda_args = {
            "name": config.function_name,
            "runtime": config.runtime,
            "handler": config.handler,
            "role": execution_role_arn,
            "timeout": config.timeout_seconds,
            "memory_size": config.memory_mb,
            "publish": config.enable_versioning,
            "reserved_concurrent_executions": config.reserved_concurrent_executions,
            **code_args,
        }

        # Add optional configurations
        if config.description:
            lambda_args["description"] = config.description

        if config.environment_variables:
            lambda_args["environment"] = {"variables": config.environment_variables}

        if layer_arns:
            lambda_args["layers"] = layer_arns

        if config.vpc_config:
            lambda_args["vpc_config"] = config.vpc_config

        if dlq_arn:
            target = dlq_arn
            lambda_args["dead_letter_config"] = {"target_arn": target}

        if config.enable_xray_tracing:
            lambda_args["tracing_config"] = {"mode": "Active"}

        if config.ephemeral_storage_mb != 512:
            lambda_args["ephemeral_storage"] = {"size": config.ephemeral_storage_mb}

        if config.architecture != "x86_64":
            lambda_args["architectures"] = [config.architecture]

        if config.tags:
            lambda_args["tags"] = config.tags

        # Create Lambda function
        lambda_function = aws.lambda_.Function(
            f"{config.function_name}-function",
            **lambda_args,
        )
        resources["function"] = lambda_function

        log_group = aws.cloudwatch.LogGroup(
            f"{config.function_name}-logs",
            name=pulumi.Output.concat("/aws/lambda/", lambda_function.name),
            retention_in_days=config.log_retention_days,
            tags=config.tags,
        )
        resources["log_group"] = log_group

        invoke_arn = lambda_function.arn
        invoke_qualifier = None
        if config.create_alias:
            alias = aws.lambda_.Alias(
                f"{config.function_name}-{config.create_alias}-alias",
                name=config.create_alias,
                function_name=lambda_function.name,
                function_version=lambda_function.version,
            )
            resources["alias"] = alias
            invoke_arn = alias.arn
            invoke_qualifier = alias.name

        if config.retry_config:
            event_invoke_config = aws.lambda_.FunctionEventInvokeConfig(
                f"{config.function_name}-async-invocation",
                function_name=lambda_function.name,
                qualifier=invoke_qualifier,
                maximum_retry_attempts=config.retry_config.max_retry_attempts,
                maximum_event_age_in_seconds=config.retry_config.max_event_age_seconds,
            )
            resources["event_invoke_config"] = event_invoke_config

        if config.provisioned_concurrency:
            provisioned = aws.lambda_.ProvisionedConcurrencyConfig(
                f"{config.function_name}-provisioned-concurrency",
                function_name=lambda_function.name,
                qualifier=invoke_qualifier or lambda_function.version,
                provisioned_concurrent_executions=config.provisioned_concurrency,
            )
            resources["provisioned_concurrency"] = provisioned

        # Create EventBridge rules for schedules
        if config.schedules:
            rules = self._create_eventbridge_schedules(
                config, lambda_function, invoke_arn, invoke_qualifier
            )
            resources["schedule_rules"] = rules

        # Create CloudWatch alarms if monitoring enabled
        if config.monitoring and config.monitoring.enable_cloudwatch_alarms:
            alarms = self._create_cloudwatch_alarms(config, lambda_function)
            resources["alarms"] = alarms

        # Export outputs
        export("function_arn", lambda_function.arn)
        export("function_name", lambda_function.name)
        if config.enable_versioning:
            export("function_version", lambda_function.version)

        return resources

    def _create_lambda_role(
        self, config: CloudFunctionConfig, dlq_arn: Any | None = None
    ) -> aws.iam.Role:
        """Create IAM role for Lambda execution."""
        role_name = config.role_name or f"{config.function_name}-role"

        # Trust policy for Lambda
        assume_role_policy = json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Action": "sts:AssumeRole",
                        "Effect": "Allow",
                        "Principal": {"Service": "lambda.amazonaws.com"},
                    }
                ],
            }
        )

        role = aws.iam.Role(
            f"{config.function_name}-role",
            name=role_name,
            assume_role_policy=assume_role_policy,
            tags=config.tags,
        )

        # Attach basic execution policy
        aws.iam.RolePolicyAttachment(
            f"{config.function_name}-basic-execution",
            role=role.name,
            policy_arn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        )

        # Attach VPC execution policy if in VPC
        if config.vpc_config:
            aws.iam.RolePolicyAttachment(
                f"{config.function_name}-vpc-execution",
                role=role.name,
                policy_arn="arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole",
            )

        # Attach additional policies
        if config.additional_iam_policies:
            for i, policy_arn in enumerate(config.additional_iam_policies):
                aws.iam.RolePolicyAttachment(
                    f"{config.function_name}-policy-{i}",
                    role=role.name,
                    policy_arn=policy_arn,
                )

        if dlq_arn:
            aws.iam.RolePolicy(
                f"{config.function_name}-dlq-policy",
                role=role.name,
                policy=pulumi.Output.json_dumps(
                    {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Action": (
                                    "sns:Publish"
                                    if isinstance(dlq_arn, str) and ":sns:" in dlq_arn
                                    else "sqs:SendMessage"
                                ),
                                "Resource": dlq_arn,
                            }
                        ],
                    }
                ),
            )

        return role

    def _create_dlq(self, config: CloudFunctionConfig) -> aws.sqs.Queue:
        """Create Dead Letter Queue for failed invocations."""
        dlq = aws.sqs.Queue(
            f"{config.function_name}-dlq",
            name=f"{config.function_name}-dlq",
            message_retention_seconds=1209600,  # 14 days
            tags=config.tags,
        )
        return dlq

    def _upload_to_s3(self, config: CloudFunctionConfig, package_path: Path) -> tuple:
        """Upload deployment package to S3."""
        # Create S3 bucket for deployments
        bucket = aws.s3.Bucket(
            f"{self.project_name}-deployments",
            tags=config.tags,
        )

        # Generate unique key
        package_hash = hashlib.sha256(package_path.read_bytes()).hexdigest()[:16]
        key = f"lambda/{config.function_name}/{package_hash}.zip"

        # Upload package
        s3_obj = aws.s3.BucketObject(
            f"{config.function_name}-package",
            bucket=bucket.id,
            key=key,
            source=pulumi.FileAsset(str(package_path)),
        )

        return bucket, s3_obj

    def _create_lambda_layer(self, layer_config: LayerConfig) -> aws.lambda_.LayerVersion:
        """Create Lambda Layer from dependencies."""
        from .dependencies import DependencyManager

        layer_package = DependencyManager(
            python_version=layer_config.compatible_runtimes[0].removeprefix("python"),
            architecture=layer_config.compatible_architectures[0],
        ).create_layer_package(
            layer_config.dependencies or [],
            runtime=layer_config.compatible_runtimes[0],
            use_docker=layer_config.build_in_docker,
        )
        layer_path = self.work_dir / f"{layer_config.layer_name}-layer.zip"
        layer_path.write_bytes(layer_package)
        if layer_config.layer_name is None:
            raise ValueError("layer_name is required when creating a layer")

        layer = aws.lambda_.LayerVersion(
            layer_config.layer_name,
            layer_name=layer_config.layer_name,
            code=pulumi.FileArchive(str(layer_path)),
            compatible_runtimes=layer_config.compatible_runtimes,
            compatible_architectures=layer_config.compatible_architectures,
        )

        return layer

    def _create_eventbridge_schedules(
        self,
        config: CloudFunctionConfig,
        lambda_function: aws.lambda_.Function,
        invoke_arn: Any,
        invoke_qualifier: Any | None,
    ) -> list[aws.cloudwatch.EventRule]:
        """Create EventBridge rules for schedules."""
        rules = []

        for i, schedule in enumerate(config.schedules or []):
            rule_name = f"{config.function_name}-schedule-{i}"
            schedule_expression = schedule_to_eventbridge_expression(schedule)

            # Create EventBridge rule
            rule = aws.cloudwatch.EventRule(
                rule_name,
                name=rule_name,
                schedule_expression=schedule_expression,
                description=f"Schedule for {config.function_name}",
            )

            # Grant permission for EventBridge to invoke Lambda
            aws.lambda_.Permission(
                f"{rule_name}-permission",
                action="lambda:InvokeFunction",
                function=lambda_function.name,
                principal="events.amazonaws.com",
                source_arn=rule.arn,
                qualifier=invoke_qualifier,
            )

            # Add Lambda as target
            aws.cloudwatch.EventTarget(
                f"{rule_name}-target",
                rule=rule.name,
                arn=invoke_arn,
            )

            rules.append(rule)

        return rules

    def _create_cloudwatch_alarms(
        self, config: CloudFunctionConfig, lambda_function: aws.lambda_.Function
    ) -> list[aws.cloudwatch.MetricAlarm]:
        """Create CloudWatch alarms for monitoring."""
        alarms: list[Any] = []
        monitoring = config.monitoring
        if monitoring is None:
            return alarms

        # Error rate alarm
        if monitoring.error_rate_threshold is not None:
            error_alarm = aws.cloudwatch.MetricAlarm(
                f"{config.function_name}-error-rate",
                name=f"{config.function_name}-error-rate",
                comparison_operator="GreaterThanThreshold",
                evaluation_periods=2,
                threshold=monitoring.error_rate_threshold,
                alarm_description=f"Error rate > {monitoring.error_rate_threshold * 100}%",
                alarm_actions=[monitoring.alarm_sns_topic_arn]
                if monitoring.alarm_sns_topic_arn
                else [],
                treat_missing_data="notBreaching",
                metric_queries=[
                    {
                        "id": "rate",
                        "expression": "IF(invocations>0,errors/invocations,0)",
                        "label": "Error rate",
                        "return_data": True,
                    },
                    {
                        "id": "invocations",
                        "metric": {
                            "metric_name": "Invocations",
                            "namespace": "AWS/Lambda",
                            "period": 300,
                            "stat": "Sum",
                            "dimensions": {"FunctionName": lambda_function.name},
                        },
                    },
                    {
                        "id": "errors",
                        "metric": {
                            "metric_name": "Errors",
                            "namespace": "AWS/Lambda",
                            "period": 300,
                            "stat": "Sum",
                            "dimensions": {"FunctionName": lambda_function.name},
                        },
                    },
                ],
            )
            alarms.append(error_alarm)

        # Duration alarm
        if monitoring.duration_threshold_ms:
            duration_alarm = aws.cloudwatch.MetricAlarm(
                f"{config.function_name}-duration",
                name=f"{config.function_name}-duration",
                comparison_operator="GreaterThanThreshold",
                evaluation_periods=2,
                metric_name="Duration",
                namespace="AWS/Lambda",
                period=300,
                statistic="Average",
                threshold=monitoring.duration_threshold_ms,
                dimensions={"FunctionName": lambda_function.name},
                alarm_description=f"Duration > {monitoring.duration_threshold_ms}ms",
                alarm_actions=[monitoring.alarm_sns_topic_arn]
                if monitoring.alarm_sns_topic_arn
                else [],
            )
            alarms.append(duration_alarm)

        return alarms

    def _function_stack_name(self, function_name: str) -> str:
        """Return a stable stack name so functions cannot replace one another."""
        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "-", function_name)
        digest = hashlib.sha256(function_name.encode()).hexdigest()[:8]
        return f"{self.stack_name}-{safe_name[:60]}-{digest}"

    def _get_or_create_stack(self, program: Callable, function_name: str) -> auto.Stack:
        """Get or create Pulumi stack."""
        try:
            operation = auto.create_or_select_stack if self.auto_create_stack else auto.select_stack
            stack = operation(
                stack_name=self._function_stack_name(function_name),
                project_name=self.project_name,
                program=program,
                opts=auto.LocalWorkspaceOptions(work_dir=str(self.work_dir)),
            )

            # Set AWS region
            stack.set_config("aws:region", auto.ConfigValue(value=self.region))

            return stack

        except Exception as e:
            logger.error(f"Failed to create Pulumi stack: {e}")
            raise

    # Implement abstract methods with Pulumi integration

    def invoke_function(
        self,
        function_name: str,
        payload: dict[str, Any] | None = None,
        invocation_type: str = "RequestResponse",
    ) -> dict[str, Any]:
        """Invoke function using AWS SDK (not Pulumi)."""
        # Use boto3 for runtime operations
        import boto3

        lambda_client = boto3.client("lambda", region_name=self.region)

        invoke_args = {
            "FunctionName": function_name,
            "InvocationType": invocation_type,
        }

        if payload:
            invoke_args["Payload"] = json.dumps(payload)

        try:
            response = lambda_client.invoke(**invoke_args)
            return {
                "StatusCode": response["StatusCode"],
                "Payload": json.loads(response["Payload"].read())
                if "Payload" in response
                else None,
            }
        except Exception as e:
            logger.error(f"Failed to invoke {function_name}: {e}")
            return {"Error": str(e)}

    def delete_function(self, function_name: str) -> bool:
        """Delete function using Pulumi destroy."""
        try:
            if function_name in self._deployed_functions:
                stack = self._deployed_functions[function_name]["stack"]
            else:
                stack = auto.select_stack(
                    stack_name=self._function_stack_name(function_name),
                    project_name=self.project_name,
                    program=lambda: None,
                    opts=auto.LocalWorkspaceOptions(work_dir=str(self.work_dir)),
                )
            stack.destroy(on_output=logger.info)
            try:
                stack.workspace.remove_stack(stack.name)
            except Exception as error:
                logger.warning(f"Destroyed stack but could not remove its state: {error}")
            self._deployed_functions.pop(function_name, None)
            return True
        except Exception as e:
            logger.error(f"Failed to delete {function_name}: {e}")
            return False

    def get_function_logs(
        self,
        function_name: str,
        limit: int = 100,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[str]:
        """Get logs using boto3."""
        import time

        import boto3

        logs_client = boto3.client("logs", region_name=self.region)
        log_group_name = f"/aws/lambda/{function_name}"

        try:
            # Get log streams
            streams_response = logs_client.describe_log_streams(
                logGroupName=log_group_name,
                orderBy="LastEventTime",
                descending=True,
                limit=5,
            )

            log_lines = []
            for stream in streams_response.get("logStreams", []):
                events_args = {
                    "logGroupName": log_group_name,
                    "logStreamName": stream["logStreamName"],
                    "limit": limit,
                }

                if start_time:
                    events_args["startTime"] = start_time
                if end_time:
                    events_args["endTime"] = end_time

                events_response = logs_client.get_log_events(**events_args)

                for event in events_response.get("events", []):
                    timestamp = time.strftime(
                        "%Y-%m-%d %H:%M:%S",
                        time.localtime(event["timestamp"] / 1000),
                    )
                    log_lines.append(f"[{timestamp}] {event['message']}")

                if len(log_lines) >= limit:
                    break

            return log_lines[:limit]

        except Exception as e:
            logger.error(f"Failed to get logs for {function_name}: {e}")
            return [f"Error retrieving logs: {e}"]

    def list_functions(self) -> list[dict[str, Any]]:
        """List deployed functions."""
        return [
            {
                "name": name,
                "arn": info["arn"],
                "version": info["version"],
                "stack": self._function_stack_name(name),
            }
            for name, info in self._deployed_functions.items()
        ]

    def update_function_code(
        self,
        function_name: str,
        function: Callable[[], None],
        dependencies: list[str] | None = None,
    ) -> CloudDeploymentResult:
        """Update function code using Pulumi update."""
        # Re-deploy with new code
        if function_name in self._deployed_functions:
            config = self._deployed_functions[function_name]["config"]
            return self.deploy_function(function, config, dependencies)
        else:
            return CloudDeploymentResult(
                success=False,
                resource_id=function_name,
                error="Function not found in deployed functions",
            )

    def update_function_configuration(
        self,
        function_name: str,
        config: CloudFunctionConfig,
    ) -> CloudDeploymentResult:
        """Update function configuration using Pulumi update."""
        deployed = self._deployed_functions.get(function_name)
        if not deployed:
            return CloudDeploymentResult(
                success=False,
                resource_id=function_name,
                error=(
                    "Function code is not available in this process; use deploy_function "
                    "to reconcile a persisted Pulumi stack"
                ),
            )
        return self.deploy_function(
            deployed["function"],
            config,
            deployed["dependencies"],
        )
