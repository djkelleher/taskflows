"""Type definitions for admin module."""

from typing import Any, Dict, List, Literal, Optional, TypedDict

from pydantic import BaseModel


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
    data: Dict[str, Any]
    error: Optional[str] = None


class BatchOperationRequest(BaseModel):
    """Batch operation request."""

    service_names: List[str]
    operation: Literal["start", "stop", "restart", "enable", "disable"]


class ServerTarget(BaseModel):
    """Server target specification."""

    address: Optional[str] = None
    alias: Optional[str] = None


class HealthCheckResponse(TypedDict):
    """Health check response."""

    status: str
    hostname: str


class ErrorResponse(TypedDict):
    """Error response."""

    error: str
    hostname: str
