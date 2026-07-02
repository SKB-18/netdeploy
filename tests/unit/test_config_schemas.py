"""
Unit tests for api/config_schemas.py typed Pydantic models.

These verify that the typed schemas correctly accept/reject inputs
before they even reach ConfigValidator.
"""

import pytest
from pydantic import ValidationError

from api.config_schemas import (
    BGPConfig,
    BGPNeighbor,
    BGPRoutePolicy,
    OSPFConfig,
    OSPFArea,
    DeviceDesiredState,
)


# ---------------------------------------------------------------------------
# BGPRoutePolicy
# ---------------------------------------------------------------------------

def test_route_policy_valid():
    p = BGPRoutePolicy(prefix="10.0.0.0/8", action="permit")
    assert str(p.prefix) == "10.0.0.0/8"


def test_route_policy_normalises_host_bits():
    p = BGPRoutePolicy(prefix="10.0.0.1/8", action="permit")
    assert p.prefix == "10.0.0.0/8"  # normalised


def test_route_policy_invalid_prefix():
    with pytest.raises(ValidationError) as exc_info:
        BGPRoutePolicy(prefix="not-cidr", action="permit")
    assert "cidr" in str(exc_info.value).lower() or "not valid" in str(exc_info.value).lower()


def test_route_policy_invalid_action():
    with pytest.raises(ValidationError):
        BGPRoutePolicy(prefix="10.0.0.0/8", action="allow")  # must be permit|deny


# ---------------------------------------------------------------------------
# BGPNeighbor
# ---------------------------------------------------------------------------

def test_bgp_neighbor_valid():
    n = BGPNeighbor(neighbor_ip="192.168.1.2", remote_asn=65002)
    assert n.remote_asn == 65002


def test_bgp_neighbor_invalid_ip():
    with pytest.raises(ValidationError):
        BGPNeighbor(neighbor_ip="not-an-ip", remote_asn=65002)


def test_bgp_neighbor_asn_zero():
    with pytest.raises(ValidationError):
        BGPNeighbor(neighbor_ip="192.168.1.2", remote_asn=0)


def test_bgp_neighbor_timers_valid():
    n = BGPNeighbor(neighbor_ip="192.168.1.2", remote_asn=65002, keepalive=60, hold_time=180)
    assert n.hold_time == 180


def test_bgp_neighbor_timers_invalid():
    with pytest.raises(ValidationError):
        BGPNeighbor(neighbor_ip="192.168.1.2", remote_asn=65002, keepalive=60, hold_time=100)


# ---------------------------------------------------------------------------
# BGPConfig
# ---------------------------------------------------------------------------

def test_bgp_config_valid():
    c = BGPConfig(
        local_asn=65001,
        router_id="10.0.0.1",
        neighbors=[BGPNeighbor(neighbor_ip="10.0.0.2", remote_asn=65002)],
    )
    assert c.local_asn == 65001


def test_bgp_config_invalid_router_id():
    with pytest.raises(ValidationError):
        BGPConfig(local_asn=65001, router_id="not-an-ip")


def test_bgp_config_invalid_network_cidr():
    with pytest.raises(ValidationError):
        BGPConfig(local_asn=65001, networks=["bad-cidr"])


# ---------------------------------------------------------------------------
# OSPFArea
# ---------------------------------------------------------------------------

def test_ospf_area_valid():
    a = OSPFArea(area_id="0.0.0.0", networks=["192.168.1.0/24"])
    assert a.area_type == "normal"


def test_ospf_area_invalid_network():
    with pytest.raises(ValidationError):
        OSPFArea(area_id="0", networks=["not-cidr"])


def test_ospf_area_invalid_type():
    with pytest.raises(ValidationError):
        OSPFArea(area_id="0", area_type="totally-stub")  # not in literal


# ---------------------------------------------------------------------------
# DeviceDesiredState (top-level)
# ---------------------------------------------------------------------------

def test_desired_state_bgp_only():
    d = DeviceDesiredState(bgp={"local_asn": 65001, "neighbors": []})
    assert d.bgp is not None
    assert d.ospf is None


def test_desired_state_ospf_only():
    d = DeviceDesiredState(ospf={"process_id": 1, "areas": []})
    assert d.ospf is not None


def test_desired_state_empty():
    d = DeviceDesiredState()
    assert d.bgp is None
    assert d.ospf is None


def test_desired_state_both_protocols():
    d = DeviceDesiredState(
        bgp={"local_asn": 65001, "neighbors": []},
        ospf={"process_id": 1, "areas": []},
    )
    assert d.bgp is not None
    assert d.ospf is not None


def test_desired_state_allows_extra_keys():
    """Extra keys (vendor-specific) should not raise ValidationError."""
    d = DeviceDesiredState(bgp={"local_asn": 65001, "neighbors": []}, custom_vendor_key="value")
    assert d is not None
