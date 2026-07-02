"""Pydantic schemas for NetDeploy API request/response models."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, validator


# ---------------------------------------------------------------------------
# Device Schemas
# ---------------------------------------------------------------------------

class DeviceRequest(BaseModel):
    hostname: str = Field(..., min_length=1, max_length=255)
    device_type: str = Field(..., description="cisco_xr | junos | arista_eos")
    management_ip: str = Field(..., description="IPv4 management address")
    ssh_port: int = Field(default=22, ge=1, le=65535)
    bgp_asn: Optional[int] = Field(None, ge=1, le=4294967295)
    ospf_area: Optional[str] = None
    os_version: Optional[str] = None

    @validator("device_type")
    def validate_device_type(cls, v):
        allowed = {"cisco_xr", "cisco_ios", "junos", "arista_eos", "nokia_sros"}
        if v not in allowed:
            raise ValueError(f"device_type must be one of {allowed}")
        return v

    @validator("management_ip")
    def validate_ip(cls, v):
        import ipaddress
        try:
            ipaddress.IPv4Address(v)
        except ValueError:
            raise ValueError(f"{v} is not a valid IPv4 address")
        return v


class DeviceResponse(BaseModel):
    id: UUID
    hostname: str
    device_type: str
    management_ip: str
    ssh_port: int
    bgp_asn: Optional[int]
    ospf_area: Optional[str]
    os_version: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class DeviceHealthResponse(BaseModel):
    device_id: UUID
    hostname: str
    reachable: bool
    bgp_neighbors_up: Optional[int] = None
    ospf_adjacencies_up: Optional[int] = None
    last_checked: datetime


# ---------------------------------------------------------------------------
# Configuration Schemas
# ---------------------------------------------------------------------------

class ConfigRequest(BaseModel):
    device_id: UUID
    desired_state: Dict[str, Any] = Field(..., description="BGP/OSPF config object")
    description: str = Field(default="Configuration update", max_length=500)
    created_by: str = Field(default="system")


class ConfigResponse(BaseModel):
    id: UUID
    device_id: UUID
    version: str
    desired_state: Dict[str, Any]
    running_state: Optional[Dict[str, Any]]
    status: str
    deployed_at: Optional[datetime]
    created_by: str
    created_at: datetime

    class Config:
        orm_mode = True


class ValidationResponse(BaseModel):
    valid: bool
    errors: List[str] = []
    warnings: List[str] = []


class ConfigDiffResponse(BaseModel):
    device_id: UUID
    desired: Optional[Dict[str, Any]]
    running: Optional[str]
    diff: Optional[str]


# ---------------------------------------------------------------------------
# Deployment Schemas
# ---------------------------------------------------------------------------

class DeploymentRequest(BaseModel):
    device_ids: List[UUID] = Field(..., min_items=1)
    config_version: str = Field(..., description="Git commit hash or 'latest'")
    strategy: str = Field(default="atomic")
    description: Optional[str] = None

    @validator("strategy")
    def validate_strategy(cls, v):
        allowed = {"canary", "rolling", "atomic"}
        if v not in allowed:
            raise ValueError(f"strategy must be one of {allowed}")
        return v


class DeploymentResponse(BaseModel):
    id: UUID
    batch_id: UUID
    device_id: UUID
    config_version: str
    status: str
    strategy: str
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    error_message: Optional[str]
    logs: Optional[str]
    created_at: datetime

    class Config:
        orm_mode = True


class DeploymentBatchResponse(BaseModel):
    batch_id: UUID
    status: str
    total_devices: int
    completed: int
    failed: int
    deployments: List[DeploymentResponse]


class RollbackRequest(BaseModel):
    deployment_id: UUID
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Audit Log Schemas
# ---------------------------------------------------------------------------

class AuditLogResponse(BaseModel):
    id: UUID
    user_id: str
    action: str
    resource_type: str
    resource_id: UUID
    details: Optional[Dict[str, Any]]
    timestamp: datetime
    ip_address: Optional[str]

    class Config:
        orm_mode = True


class AuditLogQuery(BaseModel):
    user_id: Optional[str] = None
    action: Optional[str] = None
    resource_type: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


# ---------------------------------------------------------------------------
# Health + Generic
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    version: str = "1.0.0"
    database: str
    redis: str
    timestamp: datetime
