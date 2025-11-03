"""Base abstractions for cloud deployment."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from ..schedule import Calendar, Periodic, Schedule


class DeploymentBackend(Enum):
    """Deployment backend type."""
    PULUMI = "pulumi"  # Infrastructure as Code via Pulumi
    BOTO3 = "boto3"    # Direct AWS SDK calls
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
    endpoint: Optional[str] = None  # URL or invocation endpoint if applicable
    metadata: Optional[Dict[str, Any]] = None  # Additional deployment metadata
    error: Optional[str] = None  # Error message if deployment failed
    warnings: List[str] = field(default_factory=list)  # Non-fatal warnings
    version: Optional[str] = None  # Deployed version/revision
    rollback_id: Optional[str] = None  # ID for rollback if needed


@dataclass
class LayerConfig:
    """Configuration for Lambda Layers or equivalent."""
    layer_arn: Optional[str] = None  # Existing layer ARN
    layer_name: Optional[str] = None  # Create new layer with this name
    dependencies: Optional[List[str]] = None  # pip packages for new layer
    compatible_runtimes: List[str] = field(default_factory=lambda: ["python3.11"])


@dataclass
class MonitoringConfig:
    """Monitoring and alerting configuration."""
    enable_cloudwatch_alarms: bool = False
    error_rate_threshold: float = 0.05  # 5% error rate triggers alarm
    duration_threshold_ms: Optional[int] = None  # Alert if function takes longer
    alarm_sns_topic_arn: Optional[str] = None  # SNS topic for alerts
    enable_detailed_metrics: bool = False
    metric_namespace: str = "TaskFlows"


@dataclass
class DeadLetterConfig:
    """Dead Letter Queue configuration for failed invocations."""
    target_arn: Optional[str] = None  # SQS or SNS ARN
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
    description: Optional[str] = None

    # Runtime configuration
    runtime: str = "python3.11"
    handler: str = "index.handler"
    timeout_seconds: int = 60
    memory_mb: int = 256
    ephemeral_storage_mb: int = 512  # /tmp storage (AWS: 512-10240)

    # Environment and variables
    environment_variables: Optional[Dict[str, str]] = None
    secrets: Optional[Dict[str, str]] = None  # Secret name -> env var name mapping

    # Scheduling
    schedules: Optional[List[Schedule]] = None

    # IAM and permissions
    execution_role_arn: Optional[str] = None
    role_name: Optional[str] = None
    auto_create_role: bool = True  # Auto-create execution role if not provided
    additional_iam_policies: Optional[List[str]] = None  # Policy ARNs to attach

    # Networking
    vpc_config: Optional[Dict[str, Any]] = None
    security_group_ids: Optional[List[str]] = None
    subnet_ids: Optional[List[str]] = None

    # Logging and monitoring
    log_retention_days: int = 7
    enable_xray_tracing: bool = False
    monitoring: Optional[MonitoringConfig] = None

    # Concurrency
    reserved_concurrent_executions: Optional[int] = None
    provisioned_concurrency: Optional[int] = None  # Keep N instances warm

    # Layers and dependencies
    layers: Optional[List[LayerConfig]] = None
    use_s3_for_large_packages: bool = True  # Auto-upload to S3 if >50MB

    # Error handling
    dead_letter_config: Optional[DeadLetterConfig] = None
    retry_config: Optional[RetryConfig] = None

    # Deployment configuration
    deployment_environment: str = "production"  # dev, staging, production
    enable_versioning: bool = True  # Create version on each deployment
    create_alias: Optional[str] = None  # Create alias (e.g., "live", "latest")

    # Tags
    tags: Optional[Dict[str, str]] = None

    # Advanced
    architecture: str = "x86_64"  # x86_64 or arm64
    code_signing_config_arn: Optional[str] = None
    file_system_configs: Optional[List[Dict[str, str]]] = None  # EFS mounts


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
        dependencies: Optional[List[str]] = None,
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
        payload: Optional[Dict[str, Any]] = None,
        invocation_type: str = "RequestResponse",
    ) -> Dict[str, Any]:
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
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[str]:
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
    def list_functions(self) -> List[Dict[str, Any]]:
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
        dependencies: Optional[List[str]] = None,
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
        version: Optional[str] = None,
        rollback_id: Optional[str] = None,
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
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> Dict[str, Any]:
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
        requirements_file: Optional[Path] = None,
    ) -> str:
        """Create a reusable layer with dependencies.

        Args:
            layer_config: Layer configuration
            requirements_file: Path to requirements.txt file

        Returns:
            Layer ARN or identifier
        """
        raise NotImplementedError("Layers not implemented for this provider")

    def list_versions(self, function_name: str) -> List[Dict[str, Any]]:
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
