"""Custom exception hierarchy for taskflows."""


class TaskflowsError(Exception):
    """Base exception for all taskflows errors."""

    pass


# Service-related exceptions
class ServiceError(TaskflowsError):
    """Base exception for service operations."""

    pass


class ServiceNotFoundError(ServiceError):
    """Service not found."""

    pass


class ServiceAlreadyExistsError(ServiceError):
    """Service already exists."""

    pass


class ServiceStateError(ServiceError):
    """Invalid service state for operation."""

    pass


class UnitFileError(ServiceError):
    """Error with systemd unit files."""

    pass


# Environment exceptions
class EnvironmentError(TaskflowsError):
    """Base exception for environment operations."""

    pass


class EnvironmentNotFoundError(EnvironmentError):
    """Named environment not found."""

    pass


class EnvironmentAlreadyExistsError(EnvironmentError):
    """Environment already exists."""

    pass


class EnvironmentInUseError(EnvironmentError):
    """Environment is in use by services."""

    pass


# Docker exceptions
class DockerError(TaskflowsError):
    """Base exception for Docker operations."""

    pass


class ContainerNotFoundError(DockerError):
    """Docker container not found."""

    pass


class ImageNotFoundError(DockerError):
    """Docker image not found."""

    pass


class ContainerStateError(DockerError):
    """Invalid container state for operation."""

    pass


# Task exceptions
class TaskError(TaskflowsError):
    """Base exception for task execution."""

    pass


class TaskTimeoutError(TaskError):
    """Task execution timed out."""

    pass


class TaskRetryExhaustedError(TaskError):
    """Task retries exhausted."""

    pass


class TaskRequiredError(TaskError):
    """Required task failed."""

    pass


# Security/Auth exceptions
class SecurityError(TaskflowsError):
    """Base exception for security/auth operations."""

    pass


# Configuration exceptions
class ConfigurationError(TaskflowsError):
    """Configuration error."""

    pass


class ValidationError(TaskflowsError):
    """Input validation error."""

    pass


# API/Server exceptions
class ServerError(TaskflowsError):
    """Server/API operation error."""

    pass


class ServerNotFoundError(ServerError):
    """Server not found in registry."""

    pass


class APIError(TaskflowsError):
    """API call failed."""

    pass
