"""
Typed Pydantic schemas for the BGP/OSPF desired_state payload.

These are the strongly-typed equivalents of the free-form `desired_state: dict`
field in ConfigRequest. Cursor uses these for:
  - Input validation at the route level (before hitting ConfigValidator)
  - Auto-generated Swagger docs with example payloads
  - Type-safe access inside ConfigValidator

Usage in routes:
    from api.config_schemas import DeviceDesiredState
    state = DeviceDesiredState(**request_body.desired_state)
"""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field, validator
import ipaddress


# ---------------------------------------------------------------------------
# BGP schemas
# ---------------------------------------------------------------------------

class BGPRoutePolicy(BaseModel):
    """A single route policy (prefix-list entry)."""
    prefix: str = Field(..., description="CIDR prefix e.g. 10.0.0.0/8")
    action: Literal["permit", "deny"]
    sequence: Optional[int] = Field(None, ge=1, le=65535, description="Policy sequence number")
    description: Optional[str] = None

    @validator("prefix")
    def validate_cidr(cls, v):
        """
        Rule: prefix must be valid CIDR notation.
        Rejects host routes (/32) used as aggregate prefixes.
        [CURSOR CAN EXTEND with more specific checks]
        """
        try:
            network = ipaddress.IPv4Network(v, strict=False)
            return str(network)  # normalise e.g. 10.0.0.1/8 → 10.0.0.0/8
        except ValueError:
            raise ValueError(f"{v!r} is not valid CIDR notation")


class BGPNeighbor(BaseModel):
    """A single BGP peer configuration."""
    neighbor_ip: str = Field(..., description="Peer IPv4 address")
    remote_asn: int = Field(..., ge=1, le=4294967295)
    description: Optional[str] = Field(None, max_length=255)
    # Timers
    keepalive: Optional[int] = Field(None, ge=1, le=65535, description="Keepalive seconds (default 60)")
    hold_time: Optional[int] = Field(None, ge=3, le=65535, description="Hold-time seconds (default 180)")
    # Optional knobs
    next_hop_self: bool = False
    soft_reconfiguration: bool = False
    route_map_in: Optional[str] = None
    route_map_out: Optional[str] = None
    password: Optional[str] = Field(None, description="MD5 session password (stored hashed)")
    shutdown: bool = False

    @validator("neighbor_ip")
    def validate_ip(cls, v):
        try:
            ipaddress.IPv4Address(v)
        except ValueError:
            raise ValueError(f"{v!r} is not a valid IPv4 address")
        return v

    @validator("hold_time")
    def hold_time_gt_keepalive(cls, v, values):
        """
        Rule: hold_time must be at least 3× keepalive.
        [CURSOR IMPLEMENTS full timer relationship check]
        """
        keepalive = values.get("keepalive")
        if keepalive and v and v < keepalive * 3:
            raise ValueError(
                f"hold_time ({v}) must be >= 3 × keepalive ({keepalive})"
            )
        return v


class BGPAddressFamily(BaseModel):
    """Address-family activation for a neighbor."""
    afi: Literal["ipv4", "ipv6", "vpnv4", "vpnv6"] = "ipv4"
    safi: Literal["unicast", "multicast", "labeled-unicast"] = "unicast"
    activate: bool = True
    send_community: bool = False
    maximum_prefix: Optional[int] = Field(None, ge=1)


class BGPConfig(BaseModel):
    """Full BGP protocol configuration for one device."""
    local_asn: int = Field(..., ge=1, le=4294967295, description="Local AS number")
    router_id: Optional[str] = Field(None, description="BGP router-id (IPv4 address)")
    neighbors: List[BGPNeighbor] = Field(default_factory=list)
    route_policies: List[BGPRoutePolicy] = Field(default_factory=list)
    networks: List[str] = Field(
        default_factory=list,
        description="Networks to advertise (CIDR list)",
    )
    # Optional global knobs
    graceful_restart: bool = False
    log_neighbor_changes: bool = True
    bestpath_as_path_multipath_relax: bool = False

    @validator("router_id")
    def validate_router_id(cls, v):
        """
        Rule: router_id must be a valid IPv4 address (typically a loopback).
        [CURSOR CAN EXTEND: warn if router_id not in loopback range]
        """
        if v is not None:
            try:
                ipaddress.IPv4Address(v)
            except ValueError:
                raise ValueError(f"router_id {v!r} is not a valid IPv4 address")
        return v

    @validator("networks", each_item=True)
    def validate_networks(cls, v):
        try:
            ipaddress.IPv4Network(v, strict=False)
        except ValueError:
            raise ValueError(f"network {v!r} is not valid CIDR")
        return v


# ---------------------------------------------------------------------------
# OSPF schemas
# ---------------------------------------------------------------------------

class OSPFInterface(BaseModel):
    """OSPF interface configuration within an area."""
    name: str = Field(..., description="Interface name e.g. GigabitEthernet0/0/0")
    cost: Optional[int] = Field(None, ge=1, le=65535)
    priority: int = Field(default=1, ge=0, le=255)
    hello_interval: int = Field(default=10, ge=1, le=65535)
    dead_interval: int = Field(default=40, ge=1, le=65535)
    passive: bool = False
    network_type: Optional[Literal["point-to-point", "broadcast", "non-broadcast", "point-to-multipoint"]] = None
    authentication: Optional[Literal["simple", "md5", "none"]] = None
    authentication_key: Optional[str] = None


class OSPFArea(BaseModel):
    """OSPF area configuration."""
    area_id: str = Field(..., description="Area ID: 0 / 0.0.0.0 / 1 / etc.")
    area_type: Literal["normal", "stub", "nssa"] = "normal"
    networks: List[str] = Field(
        default_factory=list,
        description="Networks in this area (CIDR list)",
    )
    interfaces: List[OSPFInterface] = Field(default_factory=list)
    authentication: Optional[Literal["simple", "md5", "none"]] = None
    # Stub/NSSA options
    no_summary: bool = False
    default_cost: Optional[int] = Field(None, ge=0, le=16777215)

    @validator("networks", each_item=True)
    def validate_networks(cls, v):
        try:
            ipaddress.IPv4Network(v, strict=False)
        except ValueError:
            raise ValueError(f"network {v!r} is not valid CIDR")
        return v


class OSPFConfig(BaseModel):
    """Full OSPF protocol configuration for one device."""
    process_id: int = Field(..., ge=1, le=65535)
    router_id: Optional[str] = None
    areas: List[OSPFArea] = Field(default_factory=list)
    # Optional global knobs
    log_adjacency_changes: bool = True
    auto_cost_reference_bandwidth: Optional[int] = Field(
        None, ge=1, description="Reference bandwidth in Mbps for auto-cost"
    )
    redistribute: List[str] = Field(
        default_factory=list,
        description="Protocols to redistribute into OSPF e.g. ['bgp 65001', 'static']",
    )

    @validator("router_id")
    def validate_router_id(cls, v):
        if v is not None:
            try:
                ipaddress.IPv4Address(v)
            except ValueError:
                raise ValueError(f"router_id {v!r} is not a valid IPv4 address")
        return v


# ---------------------------------------------------------------------------
# Top-level desired state
# ---------------------------------------------------------------------------

class DeviceDesiredState(BaseModel):
    """
    The complete desired configuration for a single network device.

    Maps 1:1 to Configuration.desired_state in the DB.
    All sections are optional — a device may run only BGP, only OSPF, or both.

    Example:
    {
        "bgp": {
            "local_asn": 65001,
            "router_id": "10.0.0.1",
            "neighbors": [
                {"neighbor_ip": "10.0.0.2", "remote_asn": 65002, "description": "peer-r2"}
            ]
        },
        "ospf": {
            "process_id": 1,
            "areas": [{"area_id": "0.0.0.0", "networks": ["192.168.1.0/24"]}]
        }
    }
    """
    bgp: Optional[BGPConfig] = None
    ospf: Optional[OSPFConfig] = None
    # Future: isis, eigrp, static_routes, acls, etc.

    class Config:
        extra = "allow"  # Allow vendor-specific keys without breaking validation
