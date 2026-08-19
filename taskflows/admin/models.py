"""Type definitions for admin module."""

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


class ServerInfo(TypedDict, total=False):
    """Server information from registry."""

    hostname: str
    public_ipv4: str
    address: str


class ResponseData(TypedDict, total=False):
    """Generic response data with hostname."""

    hostname: str


class ServiceStatusRow(TypedDict, total=False):
    """Service status row from systemd."""

    Service: str
    description: str
    load_state: str
    active_state: str
    sub_state: str


class OperationResult(BaseModel):
    """Result of a service operation."""

    hostname: str
    success: bool
    data: dict[str, Any]
    error: str | None = None


class BatchOperationRequest(BaseModel):
    """Batch operation request."""

    service_names: list[str]
    operation: Literal["start", "stop", "restart", "enable", "disable"]


class ServerTarget(BaseModel):
    """Server target specification."""

    address: str | None = None
    alias: str | None = None


class HealthCheckResponse(TypedDict):
    """Health check response."""

    status: str
    hostname: str


class ErrorResponse(TypedDict):
    """Error response."""

    error: str
    hostname: str


class PortableScheduleRequest(BaseModel):
    """Create or replace a portable short-lived scheduled command."""

    name: str
    command: list[str]
    run_at: str | None = None
    interval_seconds: float | None = None
    cron: str | None = None
    timezone: str = "UTC"
    enabled: bool = True
    timeout: float | None = None
    cwd: str | None = None
    environment: dict[str, str] = Field(default_factory=dict)
    misfire_grace_time: int | None = 3600
    coalesce: bool = True
    max_instances: int = 1
    replace_existing: bool = False
