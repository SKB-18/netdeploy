"""
Integration tests for the validation API endpoints.

Cowork provides: all test cases with clear assertions.
Cursor implements: any fixtures or helpers marked [CURSOR IMPLEMENTS],
                   and verifies tests pass after implementing the validator.
"""

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# POST /api/configs/validate — sync validation
# ---------------------------------------------------------------------------

def test_validate_valid_bgp_returns_200(client, mock_device, valid_bgp_config):
    response = client.post(
        "/api/configs/validate",
        json={
            "device_id": str(mock_device.id),
            "desired_state": valid_bgp_config,
            "description": "Test valid BGP",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["errors"] == []


def test_validate_invalid_bgp_returns_errors(client, mock_device, invalid_bgp_config):
    response = client.post(
        "/api/configs/validate",
        json={
            "device_id": str(mock_device.id),
            "desired_state": invalid_bgp_config,
            "description": "Test invalid ASN",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert len(body["errors"]) > 0


def test_validate_unknown_device_returns_404(client):
    import uuid
    response = client.post(
        "/api/configs/validate",
        json={
            "device_id": str(uuid.uuid4()),
            "desired_state": {"bgp": {"local_asn": 65001, "neighbors": []}},
            "description": "Unknown device",
        },
    )
    assert response.status_code == 404


def test_validate_policy_conflict_returns_errors(client, mock_device, conflicting_policy_config):
    response = client.post(
        "/api/configs/validate",
        json={
            "device_id": str(mock_device.id),
            "desired_state": conflicting_policy_config,
            "description": "Conflict test",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert any("conflict" in e.lower() for e in body["errors"])


def test_validate_ospf_valid(client, mock_device, valid_ospf_config):
    response = client.post(
        "/api/configs/validate",
        json={
            "device_id": str(mock_device.id),
            "desired_state": valid_ospf_config,
            "description": "Valid OSPF",
        },
    )
    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_validate_invalid_ospf_area(client, mock_device):
    response = client.post(
        "/api/configs/validate",
        json={
            "device_id": str(mock_device.id),
            "desired_state": {"ospf": {"process_id": 1, "areas": [{"area_id": "999.999.0.0"}]}},
            "description": "Bad OSPF area",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False


def test_validate_warns_on_ibgp(client, mock_device):
    """Same local and remote ASN should produce a warning, not an error."""
    config = {
        "bgp": {
            "local_asn": 65001,
            "neighbors": [{"neighbor_ip": "192.168.1.2", "remote_asn": 65001}],
        }
    }
    response = client.post(
        "/api/configs/validate",
        json={"device_id": str(mock_device.id), "desired_state": config, "description": "iBGP"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert len(body["warnings"]) > 0


def test_validate_duplicate_neighbor_is_error(client, mock_device):
    config = {
        "bgp": {
            "local_asn": 65001,
            "neighbors": [
                {"neighbor_ip": "192.168.1.2", "remote_asn": 65002},
                {"neighbor_ip": "192.168.1.2", "remote_asn": 65003},
            ],
        }
    }
    response = client.post(
        "/api/configs/validate",
        json={"device_id": str(mock_device.id), "desired_state": config, "description": "dup"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert any("duplicate" in e.lower() for e in body["errors"])


def test_validate_bgp_timer_violation(client, mock_device):
    """hold_time < 3 × keepalive violates RFC 4271."""
    config = {
        "bgp": {
            "local_asn": 65001,
            "neighbors": [
                {
                    "neighbor_ip": "192.168.1.2",
                    "remote_asn": 65002,
                    "keepalive": 30,
                    "hold_time": 60,  # must be >= 90
                }
            ],
        }
    }
    response = client.post(
        "/api/configs/validate",
        json={"device_id": str(mock_device.id), "desired_state": config, "description": "bad timers"},
    )
    assert response.status_code == 200
    assert response.json()["valid"] is False


def test_validate_invalid_cidr_in_networks(client, mock_device):
    config = {
        "bgp": {
            "local_asn": 65001,
            "neighbors": [],
            "networks": ["not-a-cidr", "10.0.0.0/8"],
        }
    }
    response = client.post(
        "/api/configs/validate",
        json={"device_id": str(mock_device.id), "desired_state": config, "description": "bad cidr"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert any("cidr" in e.lower() or "not valid" in e.lower() for e in body["errors"])


def test_validate_loopback_neighbor_ip(client, mock_device):
    config = {
        "bgp": {
            "local_asn": 65001,
            "neighbors": [{"neighbor_ip": "127.0.0.1", "remote_asn": 65002}],
        }
    }
    response = client.post(
        "/api/configs/validate",
        json={"device_id": str(mock_device.id), "desired_state": config, "description": "loopback neighbor"},
    )
    assert response.status_code == 200
    assert response.json()["valid"] is False


def test_validate_empty_config_is_valid(client, mock_device):
    """An empty config (no protocols) is technically valid."""
    response = client.post(
        "/api/configs/validate",
        json={"device_id": str(mock_device.id), "desired_state": {}, "description": "empty"},
    )
    assert response.status_code == 200
    assert response.json()["valid"] is True


# ---------------------------------------------------------------------------
# POST /api/configs/validate-batch
# ---------------------------------------------------------------------------

def test_validate_batch_mixed_results(client, mock_device, mock_device_junos, valid_bgp_config, invalid_bgp_config):
    """Batch endpoint returns one result per device."""
    response = client.post(
        "/api/configs/validate-batch",
        json=[
            {
                "device_id": str(mock_device.id),
                "desired_state": valid_bgp_config,
                "description": "valid",
            },
            {
                "device_id": str(mock_device_junos.id),
                "desired_state": invalid_bgp_config,
                "description": "invalid",
            },
        ],
    )
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 2

    valid_result = next(r for r in results if r["device_id"] == str(mock_device.id))
    invalid_result = next(r for r in results if r["device_id"] == str(mock_device_junos.id))

    assert valid_result["valid"] is True
    assert invalid_result["valid"] is False


def test_validate_batch_unknown_device_included(client, mock_device, valid_bgp_config):
    """Unknown device_id in batch returns an error entry, not a 404."""
    import uuid
    response = client.post(
        "/api/configs/validate-batch",
        json=[
            {
                "device_id": str(mock_device.id),
                "desired_state": valid_bgp_config,
                "description": "ok",
            },
            {
                "device_id": str(uuid.uuid4()),
                "desired_state": valid_bgp_config,
                "description": "unknown device",
            },
        ],
    )
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 2
    # The unknown device entry should have valid=False
    failed = [r for r in results if not r["valid"]]
    assert len(failed) == 1


# ---------------------------------------------------------------------------
# POST /api/configs/ — store desired state
# ---------------------------------------------------------------------------

def test_create_config_stores_record(client, mock_device, valid_bgp_config):
    response = client.post(
        "/api/configs/",
        json={
            "device_id": str(mock_device.id),
            "desired_state": valid_bgp_config,
            "description": "Phase 2 test config",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["device_id"] == str(mock_device.id)
    assert body["status"] == "PENDING"


def test_create_config_unknown_device_404(client, valid_bgp_config):
    import uuid
    response = client.post(
        "/api/configs/",
        json={
            "device_id": str(uuid.uuid4()),
            "desired_state": valid_bgp_config,
            "description": "missing device",
        },
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/configs/history
# ---------------------------------------------------------------------------

def test_config_history_returns_list(client, mock_device):
    response = client.get(f"/api/configs/history?device_id={mock_device.id}")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ---------------------------------------------------------------------------
# GET /api/configs/diff
# ---------------------------------------------------------------------------

def test_config_diff_no_config(client, mock_device):
    """Device with no stored config returns null desired/diff."""
    response = client.get(f"/api/configs/diff?device_id={mock_device.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["device_id"] == str(mock_device.id)
    assert body["desired"] is None
