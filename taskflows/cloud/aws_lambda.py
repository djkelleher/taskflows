"""AWS Lambda deployment environment for taskflows."""

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

try:
    import boto3
    from botocore.exceptions import ClientError

    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    boto3 = None
    ClientError = Exception

from ..common import logger
from .base import CloudDeploymentResult, CloudEnvironment, CloudFunctionConfig
from .utils import (
    create_lambda_deployment_package,
    schedule_to_eventbridge_expression,
    validate_lambda_constraints,
)


@dataclass
class AWSLambdaConfig:
    """AWS-specific configuration for Lambda deployment."""

    region: str = "us-east-1"
    # IAM role ARN for Lambda execution (required)
    execution_role_arn: Optional[str] = None
    # S3 bucket for storing deployment packages (optional, for large packages)
    deployment_bucket: Optional[str] = None
    # KMS key for encryption (optional)
    kms_key_arn: Optional[str] = None
    # VPC configuration
    vpc_config: Optional[Dict[str, List[str]]] = None  # {"SubnetIds": [...], "SecurityGroupIds": [...]}


class AWSLambdaEnvironment(CloudEnvironment):
    """AWS Lambda deployment environment.

    This class handles deployment of taskflows services to AWS Lambda,
    including function creation, EventBridge scheduling, and monitoring.

    Example:
        >>> from taskflows.cloud import AWSLambdaEnvironment, CloudFunctionConfig
        >>> from taskflows.schedule import Periodic
        >>>
        >>> def my_task():
        ...     print("Hello from Lambda!")
        >>>
        >>> lambda_env = AWSLambdaEnvironment(
        ...     region="us-east-1",
        ...     execution_role_arn="arn:aws:iam::123456789012:role/lambda-role"
        ... )
        >>>
        >>> config = CloudFunctionConfig(
        ...     function_name="my-scheduled-task",
        ...     runtime="python3.11",
        ...     memory_mb=256,
        ...     timeout_seconds=60,
        ...     schedules=[Periodic(start_on="boot", period=3600, relative_to="finish")]
        ... )
        >>>
        >>> result = lambda_env.deploy_function(my_task, config)
        >>> print(result.resource_id)  # Lambda function ARN
    """

    def __init__(self, aws_config: Optional[AWSLambdaConfig] = None, **kwargs):
        """Initialize AWS Lambda environment.

        Args:
            aws_config: AWS-specific configuration
            **kwargs: Additional arguments passed to AWSLambdaConfig if aws_config not provided
        """
        if not BOTO3_AVAILABLE:
            raise ImportError(
                "boto3 is required for AWS Lambda deployment. "
                "Install it with: pip install boto3"
            )

        if aws_config is None:
            aws_config = AWSLambdaConfig(**kwargs)

        self.config = aws_config
        self.lambda_client = boto3.client("lambda", region_name=self.config.region)
        self.events_client = boto3.client("events", region_name=self.config.region)
        self.logs_client = boto3.client("logs", region_name=self.config.region)
        self.iam_client = boto3.client("iam", region_name=self.config.region)

    def deploy_function(
        self,
        function: Callable[[], None],
        config: CloudFunctionConfig,
        dependencies: Optional[List[str]] = None,
    ) -> CloudDeploymentResult:
        """Deploy a function to AWS Lambda with optional EventBridge scheduling.

        Args:
            function: Python function to deploy (must take no arguments)
            config: Cloud function configuration
            dependencies: List of pip packages to include

        Returns:
            CloudDeploymentResult with deployment status
        """
        try:
            # Validate configuration
            validate_lambda_constraints(
                config.timeout_seconds,
                config.memory_mb,
                config.function_name,
            )

            # Get or validate execution role
            role_arn = self._get_execution_role_arn(config)

            # Create deployment package
            logger.info(f"Creating deployment package for {config.function_name}")
            deployment_package = create_lambda_deployment_package(function, dependencies)

            # Check if package is too large (Lambda limit: 50MB zipped, 250MB unzipped)
            package_size_mb = len(deployment_package) / (1024 * 1024)
            if package_size_mb > 50:
                raise ValueError(
                    f"Deployment package is {package_size_mb:.2f}MB, exceeds Lambda 50MB limit. "
                    f"Consider using S3 for deployment or reducing dependencies."
                )

            # Create or update Lambda function
            logger.info(f"Deploying function {config.function_name} to Lambda")
            function_arn = self._create_or_update_function(
                config, deployment_package, role_arn
            )

            # Set up EventBridge schedules if provided
            rule_arns = []
            if config.schedules:
                logger.info(f"Setting up {len(config.schedules)} schedule(s)")
                rule_arns = self._create_eventbridge_schedules(
                    config.function_name, function_arn, config.schedules
                )

            return CloudDeploymentResult(
                success=True,
                resource_id=function_arn,
                metadata={
                    "function_name": config.function_name,
                    "region": self.config.region,
                    "runtime": config.runtime,
                    "memory_mb": config.memory_mb,
                    "timeout": config.timeout_seconds,
                    "schedule_rules": rule_arns,
                    "package_size_mb": round(package_size_mb, 2),
                },
            )

        except Exception as e:
            logger.error(f"Failed to deploy function {config.function_name}: {e}")
            return CloudDeploymentResult(
                success=False,
                resource_id="",
                error=str(e),
            )

    def _get_execution_role_arn(self, config: CloudFunctionConfig) -> str:
        """Get or create IAM execution role for Lambda."""
        # Use provided role ARN
        if config.execution_role_arn:
            return config.execution_role_arn

        if self.config.execution_role_arn:
            return self.config.execution_role_arn

        # For POC: require explicit role ARN
        # In production, you could auto-create a role here
        raise ValueError(
            "execution_role_arn must be provided in CloudFunctionConfig or AWSLambdaConfig. "
            "Create a Lambda execution role with basic Lambda execution permissions."
        )

    def _create_or_update_function(
        self, config: CloudFunctionConfig, deployment_package: bytes, role_arn: str
    ) -> str:
        """Create new Lambda function or update existing one."""
        function_config = {
            "FunctionName": config.function_name,
            "Runtime": config.runtime,
            "Role": role_arn,
            "Handler": "index.handler",
            "Timeout": config.timeout_seconds,
            "MemorySize": config.memory_mb,
        }

        if config.description:
            function_config["Description"] = config.description

        if config.environment_variables:
            function_config["Environment"] = {"Variables": config.environment_variables}

        if config.vpc_config or self.config.vpc_config:
            vpc = config.vpc_config or self.config.vpc_config
            function_config["VpcConfig"] = vpc

        if config.tags:
            function_config["Tags"] = config.tags

        if config.enable_xray_tracing:
            function_config["TracingConfig"] = {"Mode": "Active"}

        if config.reserved_concurrent_executions:
            # Note: ReservedConcurrentExecutions is set separately via put_function_concurrency
            pass

        try:
            # Try to get existing function
            self.lambda_client.get_function(FunctionName=config.function_name)

            # Function exists, update it
            logger.info(f"Updating existing function {config.function_name}")

            # Update code
            self.lambda_client.update_function_code(
                FunctionName=config.function_name,
                ZipFile=deployment_package,
            )

            # Wait for update to complete
            waiter = self.lambda_client.get_waiter("function_updated")
            waiter.wait(FunctionName=config.function_name)

            # Update configuration
            response = self.lambda_client.update_function_configuration(**function_config)

        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                # Function doesn't exist, create it
                logger.info(f"Creating new function {config.function_name}")
                function_config["Code"] = {"ZipFile": deployment_package}
                response = self.lambda_client.create_function(**function_config)
            else:
                raise

        # Set concurrency if specified
        if config.reserved_concurrent_executions:
            self.lambda_client.put_function_concurrency(
                FunctionName=config.function_name,
                ReservedConcurrentExecutions=config.reserved_concurrent_executions,
            )

        return response["FunctionArn"]

    def _create_eventbridge_schedules(
        self, function_name: str, function_arn: str, schedules: List
    ) -> List[str]:
        """Create EventBridge rules for schedules."""
        rule_arns = []

        for i, schedule in enumerate(schedules):
            rule_name = f"{function_name}-schedule-{i}"

            # Convert schedule to EventBridge expression
            schedule_expression = schedule_to_eventbridge_expression(schedule)

            # Create EventBridge rule
            logger.info(f"Creating EventBridge rule: {rule_name} with {schedule_expression}")

            rule_response = self.events_client.put_rule(
                Name=rule_name,
                ScheduleExpression=schedule_expression,
                State="ENABLED",
                Description=f"Scheduled trigger for {function_name}",
            )

            rule_arn = rule_response["RuleArn"]
            rule_arns.append(rule_arn)

            # Add Lambda permission for EventBridge to invoke the function
            try:
                self.lambda_client.add_permission(
                    FunctionName=function_name,
                    StatementId=f"{rule_name}-invoke",
                    Action="lambda:InvokeFunction",
                    Principal="events.amazonaws.com",
                    SourceArn=rule_arn,
                )
            except ClientError as e:
                if e.response["Error"]["Code"] != "ResourceConflictException":
                    raise

            # Add Lambda as target for the rule
            self.events_client.put_targets(
                Rule=rule_name,
                Targets=[
                    {
                        "Id": "1",
                        "Arn": function_arn,
                    }
                ],
            )

        return rule_arns

    def invoke_function(
        self,
        function_name: str,
        payload: Optional[Dict[str, Any]] = None,
        invocation_type: str = "RequestResponse",
    ) -> Dict[str, Any]:
        """Invoke a Lambda function.

        Args:
            function_name: Name of the function
            payload: JSON-serializable payload
            invocation_type: "RequestResponse" (sync) or "Event" (async)

        Returns:
            Response from Lambda invocation
        """
        invoke_args = {
            "FunctionName": function_name,
            "InvocationType": invocation_type,
        }

        if payload:
            invoke_args["Payload"] = json.dumps(payload)

        try:
            response = self.lambda_client.invoke(**invoke_args)

            result = {
                "StatusCode": response["StatusCode"],
                "ExecutedVersion": response.get("ExecutedVersion"),
            }

            if "Payload" in response:
                result["Payload"] = json.loads(response["Payload"].read())

            if "FunctionError" in response:
                result["Error"] = response["FunctionError"]

            return result

        except Exception as e:
            logger.error(f"Failed to invoke function {function_name}: {e}")
            return {"Error": str(e)}

    def delete_function(self, function_name: str) -> bool:
        """Delete a Lambda function and associated EventBridge rules."""
        try:
            # Delete associated EventBridge rules
            self._delete_eventbridge_schedules(function_name)

            # Delete the function
            self.lambda_client.delete_function(FunctionName=function_name)
            logger.info(f"Deleted function {function_name}")
            return True

        except ClientError as e:
            logger.error(f"Failed to delete function {function_name}: {e}")
            return False

    def _delete_eventbridge_schedules(self, function_name: str):
        """Delete EventBridge rules associated with a function."""
        try:
            # List rules with function name prefix
            response = self.events_client.list_rules(NamePrefix=f"{function_name}-schedule-")

            for rule in response.get("Rules", []):
                rule_name = rule["Name"]

                # Remove targets
                targets_response = self.events_client.list_targets_by_rule(Rule=rule_name)
                target_ids = [t["Id"] for t in targets_response.get("Targets", [])]

                if target_ids:
                    self.events_client.remove_targets(Rule=rule_name, Ids=target_ids)

                # Delete rule
                self.events_client.delete_rule(Name=rule_name)
                logger.info(f"Deleted EventBridge rule {rule_name}")

        except ClientError as e:
            logger.warning(f"Error deleting EventBridge rules: {e}")

    def get_function_logs(
        self,
        function_name: str,
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[str]:
        """Retrieve CloudWatch logs for a Lambda function."""
        log_group_name = f"/aws/lambda/{function_name}"

        try:
            # Get log streams
            streams_response = self.logs_client.describe_log_streams(
                logGroupName=log_group_name,
                orderBy="LastEventTime",
                descending=True,
                limit=5,  # Get latest 5 streams
            )

            log_lines = []

            for stream in streams_response.get("logStreams", []):
                stream_name = stream["logStreamName"]

                # Get log events
                events_args = {
                    "logGroupName": log_group_name,
                    "logStreamName": stream_name,
                    "limit": limit,
                }

                if start_time:
                    events_args["startTime"] = start_time
                if end_time:
                    events_args["endTime"] = end_time

                events_response = self.logs_client.get_log_events(**events_args)

                for event in events_response.get("events", []):
                    timestamp = time.strftime(
                        "%Y-%m-%d %H:%M:%S",
                        time.localtime(event["timestamp"] / 1000),
                    )
                    log_lines.append(f"[{timestamp}] {event['message']}")

                if len(log_lines) >= limit:
                    break

            return log_lines[:limit]

        except ClientError as e:
            logger.error(f"Failed to get logs for {function_name}: {e}")
            return [f"Error retrieving logs: {e}"]

    def list_functions(self) -> List[Dict[str, Any]]:
        """List all Lambda functions in the region."""
        try:
            response = self.lambda_client.list_functions()

            functions = []
            for func in response.get("Functions", []):
                functions.append(
                    {
                        "name": func["FunctionName"],
                        "arn": func["FunctionArn"],
                        "runtime": func["Runtime"],
                        "memory": func["MemorySize"],
                        "timeout": func["Timeout"],
                        "last_modified": func["LastModified"],
                    }
                )

            return functions

        except ClientError as e:
            logger.error(f"Failed to list functions: {e}")
            return []

    def update_function_code(
        self,
        function_name: str,
        function: Callable[[], None],
        dependencies: Optional[List[str]] = None,
    ) -> CloudDeploymentResult:
        """Update Lambda function code."""
        try:
            deployment_package = create_lambda_deployment_package(function, dependencies)

            self.lambda_client.update_function_code(
                FunctionName=function_name,
                ZipFile=deployment_package,
            )

            # Wait for update
            waiter = self.lambda_client.get_waiter("function_updated")
            waiter.wait(FunctionName=function_name)

            return CloudDeploymentResult(
                success=True,
                resource_id=function_name,
                metadata={"updated": "code"},
            )

        except Exception as e:
            return CloudDeploymentResult(
                success=False,
                resource_id=function_name,
                error=str(e),
            )

    def update_function_configuration(
        self,
        function_name: str,
        config: CloudFunctionConfig,
    ) -> CloudDeploymentResult:
        """Update Lambda function configuration."""
        try:
            update_args = {
                "FunctionName": function_name,
                "Timeout": config.timeout_seconds,
                "MemorySize": config.memory_mb,
            }

            if config.environment_variables:
                update_args["Environment"] = {"Variables": config.environment_variables}

            self.lambda_client.update_function_configuration(**update_args)

            return CloudDeploymentResult(
                success=True,
                resource_id=function_name,
                metadata={"updated": "configuration"},
            )

        except Exception as e:
            return CloudDeploymentResult(
                success=False,
                resource_id=function_name,
                error=str(e),
            )
