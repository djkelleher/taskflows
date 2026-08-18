"""Cloud deployment support for taskflows.

This beta module deploys taskflows services to AWS Lambda. GCP, Azure, and
Kubernetes provider values are reserved for future implementations.

Features:
    - Multiple backends (Pulumi for IaC, boto3 for direct deployment)
    - Production features (monitoring, DLQ, layers, versioning)
    - Service integration (deploy existing Service objects)
    - Multi-environment support (dev, staging, production)
    - Docker-based dependency builds

Quick Start:
    >>> from taskflows.cloud.manager import DeploymentManager
    >>>
    >>> manager = DeploymentManager(provider="aws", backend="pulumi")
    >>> result = manager.deploy_function(
    ...     name="my-task",
    ...     function=lambda: print("Hello"),
    ...     schedule="Mon-Fri 09:00"
    ... )
"""

# AWS imports - always available
from .aws_lambda import AWSLambdaEnvironment
from .base import (
    CloudDeploymentResult,
    CloudEnvironment,
    CloudFunctionConfig,
    CloudProvider,
    DeadLetterConfig,
    DeploymentBackend,
    LayerConfig,
    MonitoringConfig,
    RetryConfig,
)
from .dependencies import DependencyManager
from .manager import DeploymentManager, deploy_service_to_cloud
from .pulumi_aws import PULUMI_AVAILABLE, PulumiAWSEnvironment

__all__ = [
    # Base classes
    "CloudEnvironment",
    "CloudDeploymentResult",
    "CloudFunctionConfig",
    "CloudProvider",
    "DeploymentBackend",
    # Configuration classes
    "LayerConfig",
    "MonitoringConfig",
    "DeadLetterConfig",
    "RetryConfig",
    # AWS implementations
    "AWSLambdaEnvironment",
    "PulumiAWSEnvironment",
    # High-level APIs
    "DeploymentManager",
    "deploy_service_to_cloud",
    # Utilities
    "DependencyManager",
    # Feature flags
    "PULUMI_AVAILABLE",
]
