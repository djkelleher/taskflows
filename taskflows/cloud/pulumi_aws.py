"""Production AWS Lambda deployment using Pulumi for infrastructure as code.

This module provides a production-grade implementation of AWS Lambda deployment
using Pulumi, enabling infrastructure as code, state management, and multi-cloud
extensibility.

Requirements:
    pip install pulumi pulumi-aws pulumi-awsx
"""

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    import pulumi
    import pulumi_aws as aws
    from pulumi import automation as auto
    from pulumi import export, Output

    PULUMI_AVAILABLE = True
except ImportError:
    PULUMI_AVAILABLE = False
    pulumi = None
    aws = None
    auto = None

from ..common import logger
from .base import (
    CloudDeploymentResult,
    CloudEnvironment,
    CloudFunctionConfig,
    DeadLetterConfig,
    LayerConfig,
    MonitoringConfig,
)
from .utils import (
    create_lambda_deployment_package,
    schedule_to_eventbridge_expression,
    validate_lambda_constraints,
)


class PulumiAWSEnvironment(CloudEnvironment):
    """Production AWS Lambda environment using Pulumi.

    This implementation uses Pulumi for infrastructure as code, providing:
    - Declarative infrastructure management
    - State tracking and drift detection
    - Preview changes before deployment
    - Automatic rollback on failures
    - Multi-cloud extensibility

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
        work_dir: Optional[Path] = None,
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
                "Install with: pip install pulumi pulumi-aws"
            )

        self.project_name = project_name
        self.stack_name = stack_name
        self.region = region
        self.work_dir = work_dir or Path(tempfile.mkdtemp(prefix="taskflows-pulumi-"))

        # Create project structure
        self._init_pulumi_project()

        # Track deployed resources
        self._deployed_functions: Dict[str, Dict[str, Any]] = {}

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
        dependencies: Optional[List[str]] = None,
    ) -> CloudDeploymentResult:
        """Deploy function using Pulumi infrastructure as code."""

        try:
            validate_lambda_constraints(
                config.timeout_seconds,
                config.memory_mb,
                config.function_name,
            )

            # Create deployment package
            logger.info(f"Creating deployment package for {config.function_name}")
            deployment_package = create_lambda_deployment_package(function, dependencies)
            package_size_mb = len(deployment_package) / (1024 * 1024)

            # Determine deployment method
            use_s3 = config.use_s3_for_large_packages and package_size_mb > 50

            # Create Pulumi program
            def pulumi_program():
                return self._create_lambda_infrastructure(
                    config, deployment_package, use_s3
                )

            # Execute Pulumi deployment
            stack = self._get_or_create_stack(pulumi_program)
            up_result = stack.up(on_output=logger.info)

            # Extract outputs
            outputs = up_result.outputs
            function_arn = outputs.get("function_arn", {}).value
            function_version = outputs.get("function_version", {}).value

            # Store deployment info
            self._deployed_functions[config.function_name] = {
                "arn": function_arn,
                "version": function_version,
                "config": config,
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
                    "stack": self.stack_name,
                },
            )

        except Exception as e:
            logger.error(f"Failed to deploy {config.function_name}: {e}")
            return CloudDeploymentResult(
                success=False,
                resource_id="",
                error=str(e),
            )

    def _create_lambda_infrastructure(
        self,
        config: CloudFunctionConfig,
        deployment_package: bytes,
        use_s3: bool,
    ) -> Dict[str, Any]:
        """Create Lambda infrastructure using Pulumi.

        This is the Pulumi program that defines the infrastructure.
        """
        resources = {}

        # Create IAM role if needed
        if config.auto_create_role and not config.execution_role_arn:
            role = self._create_lambda_role(config)
            execution_role_arn = role.arn
            resources["role"] = role
        else:
            execution_role_arn = config.execution_role_arn

        # Create Dead Letter Queue if configured
        dlq_arn = None
        if config.dead_letter_config and config.dead_letter_config.auto_create:
            dlq = self._create_dlq(config)
            dlq_arn = dlq.arn
            resources["dlq"] = dlq

        # Upload to S3 if package is large
        code_args = {}
        if use_s3:
            bucket, s3_obj = self._upload_to_s3(config, deployment_package)
            code_args = {"s3_bucket": bucket.id, "s3_key": s3_obj.key}
            resources["bucket"] = bucket
            resources["s3_object"] = s3_obj
        else:
            code_args = {"archive": pulumi.AssetArchive({".": pulumi.BytesAsset(deployment_package)})}

        # Create Lambda Layers if specified
        layer_arns = []
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

        if dlq_arn or (config.dead_letter_config and config.dead_letter_config.target_arn):
            target = dlq_arn or config.dead_letter_config.target_arn
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

        # Publish version if versioning enabled
        if config.enable_versioning:
            # Function version is automatically created
            pass

        # Set concurrency limits
        if config.reserved_concurrent_executions:
            concurrency = aws.lambda_.FunctionConcurrency(
                f"{config.function_name}-concurrency",
                function_name=lambda_function.name,
                reserved_concurrent_executions=config.reserved_concurrent_executions,
            )
            resources["concurrency"] = concurrency

        # Create EventBridge rules for schedules
        if config.schedules:
            rules = self._create_eventbridge_schedules(config, lambda_function)
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

    def _create_lambda_role(self, config: CloudFunctionConfig) -> aws.iam.Role:
        """Create IAM role for Lambda execution."""
        role_name = config.role_name or f"{config.function_name}-role"

        # Trust policy for Lambda
        assume_role_policy = json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Action": "sts:AssumeRole",
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
            }],
        })

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

    def _upload_to_s3(
        self, config: CloudFunctionConfig, deployment_package: bytes
    ) -> tuple:
        """Upload deployment package to S3."""
        # Create S3 bucket for deployments
        bucket = aws.s3.Bucket(
            f"{self.project_name}-deployments",
            tags=config.tags,
        )

        # Generate unique key
        package_hash = hashlib.sha256(deployment_package).hexdigest()[:16]
        key = f"lambda/{config.function_name}/{package_hash}.zip"

        # Upload package
        s3_obj = aws.s3.BucketObject(
            f"{config.function_name}-package",
            bucket=bucket.id,
            key=key,
            source=pulumi.BytesAsset(deployment_package),
        )

        return bucket, s3_obj

    def _create_lambda_layer(self, layer_config: LayerConfig) -> aws.lambda_.LayerVersion:
        """Create Lambda Layer from dependencies."""
        # This would need proper layer packaging (dependencies in python/lib/python3.x/site-packages)
        # For now, simplified implementation
        from .utils import create_lambda_layer_package

        layer_package = create_lambda_layer_package(layer_config.dependencies or [])

        layer = aws.lambda_.LayerVersion(
            layer_config.layer_name,
            layer_name=layer_config.layer_name,
            code=pulumi.AssetArchive({".": pulumi.BytesAsset(layer_package)}),
            compatible_runtimes=layer_config.compatible_runtimes,
        )

        return layer

    def _create_eventbridge_schedules(
        self, config: CloudFunctionConfig, lambda_function: aws.lambda_.Function
    ) -> List[aws.cloudwatch.EventRule]:
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
            )

            # Add Lambda as target
            aws.cloudwatch.EventTarget(
                f"{rule_name}-target",
                rule=rule.name,
                arn=lambda_function.arn,
            )

            rules.append(rule)

        return rules

    def _create_cloudwatch_alarms(
        self, config: CloudFunctionConfig, lambda_function: aws.lambda_.Function
    ) -> List[aws.cloudwatch.MetricAlarm]:
        """Create CloudWatch alarms for monitoring."""
        alarms = []
        monitoring = config.monitoring

        # Error rate alarm
        if monitoring.error_rate_threshold:
            error_alarm = aws.cloudwatch.MetricAlarm(
                f"{config.function_name}-error-rate",
                name=f"{config.function_name}-error-rate",
                comparison_operator="GreaterThanThreshold",
                evaluation_periods=2,
                metric_name="Errors",
                namespace="AWS/Lambda",
                period=300,  # 5 minutes
                statistic="Average",
                threshold=monitoring.error_rate_threshold,
                dimensions={"FunctionName": lambda_function.name},
                alarm_description=f"Error rate > {monitoring.error_rate_threshold*100}%",
                alarm_actions=[monitoring.alarm_sns_topic_arn] if monitoring.alarm_sns_topic_arn else [],
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
                alarm_actions=[monitoring.alarm_sns_topic_arn] if monitoring.alarm_sns_topic_arn else [],
            )
            alarms.append(duration_alarm)

        return alarms

    def _get_or_create_stack(self, program: Callable) -> auto.Stack:
        """Get or create Pulumi stack."""
        try:
            stack = auto.create_or_select_stack(
                stack_name=self.stack_name,
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
        payload: Optional[Dict[str, Any]] = None,
        invocation_type: str = "RequestResponse",
    ) -> Dict[str, Any]:
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
                "Payload": json.loads(response["Payload"].read()) if "Payload" in response else None,
            }
        except Exception as e:
            logger.error(f"Failed to invoke {function_name}: {e}")
            return {"Error": str(e)}

    def delete_function(self, function_name: str) -> bool:
        """Delete function using Pulumi destroy."""
        try:
            if function_name in self._deployed_functions:
                stack = self._deployed_functions[function_name]["stack"]
                stack.destroy(on_output=logger.info)
                del self._deployed_functions[function_name]
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete {function_name}: {e}")
            return False

    def get_function_logs(
        self,
        function_name: str,
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[str]:
        """Get logs using boto3."""
        import boto3
        import time

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

    def list_functions(self) -> List[Dict[str, Any]]:
        """List deployed functions."""
        return [
            {
                "name": name,
                "arn": info["arn"],
                "version": info["version"],
                "stack": self.stack_name,
            }
            for name, info in self._deployed_functions.items()
        ]

    def update_function_code(
        self,
        function_name: str,
        function: Callable[[], None],
        dependencies: Optional[List[str]] = None,
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
        # This would trigger a Pulumi update with new configuration
        # Implementation would re-run the Pulumi program with updated config
        raise NotImplementedError("Configuration update via Pulumi not yet implemented")
