"""Custom exception hierarchy for taskflows."""


class TaskflowsError(Exception):
    """Base exception for all taskflows errors."""

    pass


class SecurityError(TaskflowsError):
    """Base exception for security/auth operations."""

    pass


class ValidationError(TaskflowsError):
    """Input validation error."""

    pass
