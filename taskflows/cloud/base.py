"""Base abstractions for cloud deployment."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..schedule import Schedule


class DeploymentBackend(Enum):
    """Deployment backend type."""

    PULUMI = "pulumi"  # Infrastructure as Code via Pulumi
    BOTO3 = "boto3"  # Direct AWS SDK calls
    TERRAFORM = "terraform"  # Future support


class CloudProvider(Enum):
    """Supported cloud providers."""

    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    KUBERNETES = "kubernetes"


@dataclass
class CloudDeploymentResult:
    """Result of a cloud deployment operation."""

    success: bool
    resource_id: str  # ARN, function name, or other cloud resource identifier
    endpoint: str | None = None  # URL or invocation endpoint if applicable
    metadata: dict[str, Any] | None = None  # Additional deployment metadata
    error: str | None = None  # Error message if deployment failed
    warnings: list[str] = field(default_factory=list)  # Non-fatal warnings
    version: str | None = None  # Deployed version/revision
    rollback_id: str | None = None  # ID for rollback if needed


@dataclass
class LayerConfig:
    """Configuration for Lambda Layers or equivalent."""

    layer_arn: str | None = None  # Existing layer ARN
    layer_name: str | None = None  # Create new layer with this name
    dependencies: list[str] | None = None  # pip packages for new layer
    compatible_runtimes: list[str] = field(default_factory=lambda: ["python3.11"])
    compatible_architectures: list[str] = field(default_factory=lambda: ["x86_64"])
    build_in_docker: bool = True


@dataclass
class MonitoringConfig:
    """Monitoring and alerting configuration."""

    enable_cloudwatch_alarms: bool = False
    error_rate_threshold: float = 0.05  # 5% error rate triggers alarm
    duration_threshold_ms: int | None = None  # Alert if function takes longer
    alarm_sns_topic_arn: str | None = None  # SNS topic for alerts
    enable_detailed_metrics: bool = False
    metric_namespace: str = "TaskFlows"


@dataclass
class DeadLetterConfig:
    """Dead Letter Queue configuration for failed invocations."""

    target_arn: str | None = None  # SQS or SNS ARN
    auto_create: bool = False  # Auto-create DLQ if not provided


@dataclass
class RetryConfig:
    """Retry configuration for async invocations."""

    max_retry_attempts: int = 2  # 0-2 for Lambda
    max_event_age_seconds: int = 3600  # 60-21600 seconds


@dataclass
class CloudFunctionConfig:
    """Common configuration for cloud function deployments.

    This configuration works across multiple cloud providers with
    provider-specific fields being ignored if not applicable.
    """

    # Function identification
    function_name: str
    description: str | None = None

    # Runtime configuration
    runtime: str = "python3.11"
    handler: str = "index.handler"
    timeout_seconds: int = 60
    memory_mb: int = 256
    ephemeral_storage_mb: int = 512  # /tmp storage (AWS: 512-10240)

    # Environment and variables
    environment_variables: dict[str, str] | None = None
    secrets: dict[str, str] | None = None  # Secret name -> env var name mapping

    # Scheduling
    schedules: list[Schedule] | None = None

    # IAM and permissions
    execution_role_arn: str | None = None
    role_name: str | None = None
    auto_create_role: bool = True  # Auto-create execution role if not provided
    additional_iam_policies: list[str] | None = None  # Policy ARNs to attach

    # Networking
    vpc_config: dict[str, Any] | None = None
    security_group_ids: list[str] | None = None
    subnet_ids: list[str] | None = None

    # Logging and monitoring
    log_retention_days: int = 7
    enable_xray_tracing: bool = False
    monitoring: MonitoringConfig | None = None

    # Concurrency
    reserved_concurrent_executions: int | None = None
    provisioned_concurrency: int | None = None  # Keep N instances warm

    # Layers and dependencies
    layers: list[LayerConfig] | None = None
    use_s3_for_large_packages: bool = True  # Auto-upload to S3 if >50MB
    build_dependencies_in_docker: bool = True  # Match Lambda Linux/runtime wheels

    # Error handling
    dead_letter_config: DeadLetterConfig | None = None
    retry_config: RetryConfig | None = None

    # Deployment configuration
    deployment_environment: str = "production"  # dev, staging, production
    enable_versioning: bool = True  # Create version on each deployment
    create_alias: str | None = None  # Create alias (e.g., "live", "latest")

    # Tags
    tags: dict[str, str] | None = None

    # Advanced
    architecture: str = "x86_64"  # x86_64 or arm64
    code_signing_config_arn: str | None = None
    file_system_configs: list[dict[str, str]] | None = None  # EFS mounts

    def __post_init__(self) -> None:
        """Reject invalid settings before a deployment reaches a provider API."""
        if not self.function_name:
            raise ValueError("function_name cannot be empty")
        if self.timeout_seconds < 1 or self.timeout_seconds > 900:
            raise ValueError("timeout_seconds must be between 1 and 900")
        if self.memory_mb < 128 or self.memory_mb > 10240:
            raise ValueError("memory_mb must be between 128 and 10240")
        if self.ephemeral_storage_mb < 512 or self.ephemeral_storage_mb > 10240:
            raise ValueError("ephemeral_storage_mb must be between 512 and 10240")
        if self.architecture not in {"x86_64", "arm64"}:
            raise ValueError("architecture must be 'x86_64' or 'arm64'")
        if (
            self.reserved_concurrent_executions is not None
            and self.reserved_concurrent_executions < 0
        ):
            raise ValueError("reserved_concurrent_executions cannot be negative")
        if self.provisioned_concurrency is not None:
            if self.provisioned_concurrency < 1:
                raise ValueError("provisioned_concurrency must be at least 1")
            if not self.enable_versioning:
                raise ValueError("provisioned_concurrency requires enable_versioning=True")
        if self.retry_config:
            if not 0 <= self.retry_config.max_retry_attempts <= 2:
                raise ValueError("max_retry_attempts must be between 0 and 2")
            if not 60 <= self.retry_config.max_event_age_seconds <= 21600:
                raise ValueError("max_event_age_seconds must be between 60 and 21600")
        if self.layers:
            for layer in self.layers:
                choices = (layer.layer_arn is not None, layer.layer_name is not None)
                if sum(choices) != 1:
                    raise ValueError("each layer must set exactly one of layer_arn or layer_name")
                if not layer.compatible_runtimes:
                    raise ValueError("layer compatible_runtimes cannot be empty")
                if not layer.compatible_architectures or not set(
                    layer.compatible_architectures
                ) <= {"x86_64", "arm64"}:
                    raise ValueError("layer compatible_architectures must contain x86_64 or arm64")


class CloudEnvironment(ABC):
    """Abstract base class for cloud execution environments.

    This class defines the interface for deploying and managing
    taskflows services on cloud platforms.
    """

    @abstractmethod
    def deploy_function(
        self,
        function: Callable[[], None],
        config: CloudFunctionConfig,
        dependencies: list[str] | None = None,
    ) -> CloudDeploymentResult:
        """Deploy a Python function to the cloud platform.

        Args:
            function: The Python function to deploy (must take no arguments)
            config: Cloud function configuration
            dependencies: List of pip package names to include in deployment

        Returns:
            CloudDeploymentResult with deployment status and resource information
        """
        pass

    @abstractmethod
    def invoke_function(
        self,
        function_name: str,
        payload: dict[str, Any] | None = None,
        invocation_type: str = "RequestResponse",
    ) -> dict[str, Any]:
        """Invoke a deployed cloud function.

        Args:
            function_name: Name of the function to invoke
            payload: Optional JSON-serializable payload to send to function
            invocation_type: Type of invocation (sync/async)

        Returns:
            Response from the function invocation
        """
        pass

    @abstractmethod
    def delete_function(self, function_name: str) -> bool:
        """Delete a deployed cloud function.

        Args:
            function_name: Name of the function to delete

        Returns:
            True if deletion was successful, False otherwise
        """
        pass

    @abstractmethod
    def get_function_logs(
        self,
        function_name: str,
        limit: int = 100,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[str]:
        """Retrieve logs for a deployed function.

        Args:
            function_name: Name of the function
            limit: Maximum number of log lines to retrieve
            start_time: Start time (Unix timestamp in milliseconds)
            end_time: End time (Unix timestamp in milliseconds)

        Returns:
            List of log lines
        """
        pass

    @abstractmethod
    def list_functions(self) -> list[dict[str, Any]]:
        """List all deployed functions.

        Returns:
            List of function metadata dictionaries
        """
        pass

    @abstractmethod
    def update_function_code(
        self,
        function_name: str,
        function: Callable[[], None],
        dependencies: list[str] | None = None,
    ) -> CloudDeploymentResult:
        """Update the code of an existing function.

        Args:
            function_name: Name of the function to update
            function: New function code
            dependencies: Updated list of dependencies

        Returns:
            CloudDeploymentResult with update status
        """
        pass

    @abstractmethod
    def update_function_configuration(
        self,
        function_name: str,
        config: CloudFunctionConfig,
    ) -> CloudDeploymentResult:
        """Update the configuration of an existing function.

        Args:
            function_name: Name of the function to update
            config: New configuration

        Returns:
            CloudDeploymentResult with update status
        """
        pass

    def rollback_function(
        self,
        function_name: str,
        version: str | None = None,
        rollback_id: str | None = None,
    ) -> CloudDeploymentResult:
        """Rollback function to a previous version.

        Args:
            function_name: Name of the function
            version: Specific version to rollback to
            rollback_id: Rollback ID from previous deployment

        Returns:
            CloudDeploymentResult with rollback status
        """
        raise NotImplementedError("Rollback not implemented for this provider")

    def get_function_metrics(
        self,
        function_name: str,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> dict[str, Any]:
        """Get metrics for a deployed function.

        Args:
            function_name: Name of the function
            start_time: Start time (Unix timestamp in milliseconds)
            end_time: End time (Unix timestamp in milliseconds)

        Returns:
            Dictionary of metrics (invocations, errors, duration, etc.)
        """
        raise NotImplementedError("Metrics not implemented for this provider")

    def create_layer(
        self,
        layer_config: LayerConfig,
        requirements_file: Path | None = None,
    ) -> str:
        """Create a reusable layer with dependencies.

        Args:
            layer_config: Layer configuration
            requirements_file: Path to requirements.txt file

        Returns:
            Layer ARN or identifier
        """
        raise NotImplementedError("Layers not implemented for this provider")

    def list_versions(self, function_name: str) -> list[dict[str, Any]]:
        """List all versions of a function.

        Args:
            function_name: Name of the function

        Returns:
            List of version metadata
        """
        raise NotImplementedError("Versioning not implemented for this provider")

    def set_function_alias(
        self,
        function_name: str,
        alias_name: str,
        version: str,
    ) -> bool:
        """Set or update a function alias to point to a specific version.

        Args:
            function_name: Name of the function
            alias_name: Alias name (e.g., "live", "staging")
            version: Version number to point to

        Returns:
            True if successful
        """
        raise NotImplementedError("Aliases not implemented for this provider")
