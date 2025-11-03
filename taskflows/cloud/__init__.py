"""Cloud deployment support for taskflows.

This module provides production-ready implementations for deploying
taskflows services to cloud platforms like AWS Lambda, GCP Cloud Functions,
and Azure Functions.

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

# AWS imports - always available
from .aws_lambda import AWSLambdaEnvironment

# Try to import Pulumi-based deployer
try:
    from .pulumi_aws import PulumiAWSEnvironment

    PULUMI_AVAILABLE = True
except ImportError:
    PULUMI_AVAILABLE = False
    PulumiAWSEnvironment = None

# Try to import deployment manager
try:
    from .manager import DeploymentManager, deploy_service_to_cloud

    MANAGER_AVAILABLE = True
except ImportError:
    MANAGER_AVAILABLE = False
    DeploymentManager = None
    deploy_service_to_cloud = None

# Try to import dependency manager
try:
    from .dependencies import DependencyManager

    DEPENDENCY_MANAGER_AVAILABLE = True
except ImportError:
    DEPENDENCY_MANAGER_AVAILABLE = False
    DependencyManager = None

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
    "MANAGER_AVAILABLE",
    "DEPENDENCY_MANAGER_AVAILABLE",
]

__version__ = "1.0.0"
