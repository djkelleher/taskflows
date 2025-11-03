"""Deployment manager for coordinating cloud deployments.

This module provides a high-level interface for deploying taskflows services
to cloud platforms, with support for multiple backends (Pulumi, boto3, etc.).
"""

from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

from ..schedule import Schedule
from ..service import Service
from .base import (
    CloudDeploymentResult,
    CloudFunctionConfig,
    CloudProvider,
    DeploymentBackend,
    MonitoringConfig,
)
from ..common import logger


class DeploymentManager:
    """High-level deployment manager for cloud functions.

    This manager provides a unified interface for deploying taskflows services
    to various cloud platforms using different backends.

    Example:
        >>> manager = DeploymentManager(
        ...     provider=CloudProvider.AWS,
        ...     backend=DeploymentBackend.PULUMI,
        ...     region="us-east-1"
        ... )
        >>>
        >>> # Deploy a simple function
        >>> result = manager.deploy_function(
        ...     name="my-task",
        ...     function=lambda: print("Hello"),
        ...     schedule="Mon-Fri 09:00"
        ... )
        >>>
        >>> # Or deploy from existing Service
        >>> service = Service(name="processor", start_command=process_data, ...)
        >>> result = manager.deploy_service(service)
    """

    def __init__(
        self,
        provider: Union[CloudProvider, str] = CloudProvider.AWS,
        backend: Union[DeploymentBackend, str] = DeploymentBackend.PULUMI,
        region: str = "us-east-1",
        project_name: str = "taskflows",
        environment: str = "production",
        **backend_kwargs,
    ):
        """Initialize deployment manager.

        Args:
            provider: Cloud provider (AWS, GCP, Azure, etc.)
            backend: Deployment backend (Pulumi, boto3, Terraform)
            region: Cloud region
            project_name: Project name for resource grouping
            environment: Deployment environment (dev, staging, production)
            **backend_kwargs: Additional arguments for backend initialization
        """
        self.provider = CloudProvider(provider) if isinstance(provider, str) else provider
        self.backend = DeploymentBackend(backend) if isinstance(backend, str) else backend
        self.region = region
        self.project_name = project_name
        self.environment = environment

        # Initialize backend environment
        self._environment = self._create_environment(**backend_kwargs)

    def _create_environment(self, **kwargs):
        """Create cloud environment based on provider and backend."""
        if self.provider == CloudProvider.AWS:
            if self.backend == DeploymentBackend.PULUMI:
                from .pulumi_aws import PulumiAWSEnvironment

                return PulumiAWSEnvironment(
                    project_name=self.project_name,
                    stack_name=self.environment,
                    region=self.region,
                    **kwargs,
                )
            elif self.backend == DeploymentBackend.BOTO3:
                from .aws_lambda import AWSLambdaEnvironment

                return AWSLambdaEnvironment(
                    region=self.region,
                    **kwargs,
                )
            else:
                raise ValueError(f"Backend {self.backend} not supported for AWS")

        elif self.provider == CloudProvider.GCP:
            raise NotImplementedError("GCP support coming soon")

        elif self.provider == CloudProvider.AZURE:
            raise NotImplementedError("Azure support coming soon")

        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    def deploy_function(
        self,
        name: str,
        function: Callable[[], None],
        schedule: Optional[Union[str, Schedule, List[Schedule]]] = None,
        memory_mb: int = 256,
        timeout_seconds: int = 60,
        environment_variables: Optional[Dict[str, str]] = None,
        dependencies: Optional[List[str]] = None,
        enable_monitoring: bool = True,
        **config_kwargs,
    ) -> CloudDeploymentResult:
        """Deploy a function with simplified configuration.

        Args:
            name: Function name
            function: Python callable to deploy
            schedule: Schedule string (e.g., "Mon-Fri 09:00") or Schedule object(s)
            memory_mb: Memory allocation
            timeout_seconds: Execution timeout
            environment_variables: Environment variables
            dependencies: pip package dependencies
            enable_monitoring: Enable CloudWatch alarms and monitoring
            **config_kwargs: Additional CloudFunctionConfig arguments

        Returns:
            CloudDeploymentResult
        """
        # Parse schedule
        schedules = self._parse_schedule(schedule) if schedule else None

        # Build configuration
        config = CloudFunctionConfig(
            function_name=name,
            memory_mb=memory_mb,
            timeout_seconds=timeout_seconds,
            environment_variables=environment_variables,
            schedules=schedules,
            deployment_environment=self.environment,
            monitoring=MonitoringConfig(
                enable_cloudwatch_alarms=enable_monitoring
            ) if enable_monitoring else None,
            tags={
                "Project": self.project_name,
                "Environment": self.environment,
                "ManagedBy": "TaskFlows",
            },
            **config_kwargs,
        )

        return self._environment.deploy_function(function, config, dependencies)

    def deploy_service(
        self,
        service: Service,
        dependencies: Optional[List[str]] = None,
        **config_overrides,
    ) -> CloudDeploymentResult:
        """Deploy a taskflows Service to the cloud.

        Args:
            service: Existing taskflows Service object
            dependencies: pip package dependencies
            **config_overrides: Override CloudFunctionConfig settings

        Returns:
            CloudDeploymentResult
        """
        # Extract configuration from Service
        schedules = []
        if service.start_schedule:
            if isinstance(service.start_schedule, list):
                schedules.extend(service.start_schedule)
            else:
                schedules.append(service.start_schedule)

        # Build configuration from Service
        config = CloudFunctionConfig(
            function_name=service.name,
            schedules=schedules if schedules else None,
            environment_variables=service.env or {},
            timeout_seconds=service.timeout or 60,
            deployment_environment=self.environment,
            tags={
                "Project": self.project_name,
                "Environment": self.environment,
                "ManagedBy": "TaskFlows",
                "ServiceType": "Scheduled",
            },
            **config_overrides,
        )

        # Get the function to deploy
        if callable(service.start_command):
            function = service.start_command
        else:
            # If start_command is a string, wrap it
            def command_wrapper():
                import subprocess
                subprocess.run(service.start_command, shell=True, check=True)

            function = command_wrapper

        return self._environment.deploy_function(function, config, dependencies)

    def deploy_multiple(
        self,
        functions: List[Dict],
        parallel: bool = False,
    ) -> List[CloudDeploymentResult]:
        """Deploy multiple functions.

        Args:
            functions: List of function configurations (dict with keys: name, function, schedule, etc.)
            parallel: Deploy in parallel (if backend supports it)

        Returns:
            List of CloudDeploymentResults
        """
        results = []

        for func_config in functions:
            name = func_config.pop("name")
            function = func_config.pop("function")
            result = self.deploy_function(name=name, function=function, **func_config)
            results.append(result)

        return results

    def invoke(
        self,
        function_name: str,
        payload: Optional[Dict] = None,
        async_invoke: bool = False,
    ) -> Dict:
        """Invoke a deployed function.

        Args:
            function_name: Name of the function
            payload: Payload to send
            async_invoke: Asynchronous invocation (fire and forget)

        Returns:
            Invocation response
        """
        invocation_type = "Event" if async_invoke else "RequestResponse"
        return self._environment.invoke_function(function_name, payload, invocation_type)

    def get_logs(
        self,
        function_name: str,
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[str]:
        """Get function logs.

        Args:
            function_name: Name of the function
            limit: Number of log lines
            start_time: Start time (Unix timestamp in ms)
            end_time: End time (Unix timestamp in ms)

        Returns:
            List of log lines
        """
        return self._environment.get_function_logs(
            function_name, limit, start_time, end_time
        )

    def delete(self, function_name: str) -> bool:
        """Delete a deployed function.

        Args:
            function_name: Name of the function

        Returns:
            True if successful
        """
        return self._environment.delete_function(function_name)

    def list_functions(self) -> List[Dict]:
        """List all deployed functions.

        Returns:
            List of function metadata
        """
        return self._environment.list_functions()

    def rollback(
        self,
        function_name: str,
        version: Optional[str] = None,
    ) -> CloudDeploymentResult:
        """Rollback a function to a previous version.

        Args:
            function_name: Name of the function
            version: Specific version to rollback to (or latest if None)

        Returns:
            CloudDeploymentResult
        """
        return self._environment.rollback_function(function_name, version=version)

    def get_metrics(
        self,
        function_name: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> Dict:
        """Get function metrics.

        Args:
            function_name: Name of the function
            start_time: Start time (Unix timestamp in ms)
            end_time: End time (Unix timestamp in ms)

        Returns:
            Dictionary of metrics
        """
        return self._environment.get_function_metrics(function_name, start_time, end_time)

    def _parse_schedule(
        self, schedule: Union[str, Schedule, List[Schedule]]
    ) -> List[Schedule]:
        """Parse schedule from various formats.

        Args:
            schedule: Schedule string, object, or list

        Returns:
            List of Schedule objects
        """
        from ..schedule import Calendar

        if isinstance(schedule, list):
            return schedule
        elif isinstance(schedule, Schedule):
            return [schedule]
        elif isinstance(schedule, str):
            # Parse schedule string (e.g., "Mon-Fri 09:00")
            return [Calendar(schedule=schedule)]
        else:
            raise ValueError(f"Invalid schedule format: {type(schedule)}")


def deploy_service_to_cloud(
    service: Service,
    provider: Union[CloudProvider, str] = CloudProvider.AWS,
    backend: Union[DeploymentBackend, str] = DeploymentBackend.PULUMI,
    region: str = "us-east-1",
    environment: str = "production",
    **config_overrides,
) -> CloudDeploymentResult:
    """Convenience function to deploy a Service to the cloud.

    This is a helper function for quick deployments without creating a manager.

    Args:
        service: taskflows Service object
        provider: Cloud provider
        backend: Deployment backend
        region: Cloud region
        environment: Deployment environment
        **config_overrides: CloudFunctionConfig overrides

    Returns:
        CloudDeploymentResult

    Example:
        >>> service = Service(
        ...     name="processor",
        ...     start_command=process_data,
        ...     start_schedule=Calendar(schedule="Mon-Fri 09:00")
        ... )
        >>>
        >>> result = deploy_service_to_cloud(
        ...     service,
        ...     provider="aws",
        ...     backend="pulumi",
        ...     enable_monitoring=True
        ... )
    """
    manager = DeploymentManager(
        provider=provider,
        backend=backend,
        region=region,
        environment=environment,
    )

    return manager.deploy_service(service, **config_overrides)
