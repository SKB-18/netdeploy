"""Full system integration tests — [CURSOR IMPLEMENTS]."""

import pytest


def test_health_check(client):
    """API health endpoint should return 200."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data


def test_create_device(client):
    """POST /api/devices/ creates a device record."""
    response = client.post("/api/devices/", json={
        "hostname": "test-router-99",
        "device_type": "cisco_xr",
        "management_ip": "10.0.0.99",
        "ssh_port": 22,
        "bgp_asn": 65099,
    })
    assert response.status_code == 201
    data = response.json()
    assert data["hostname"] == "test-router-99"


def test_list_devices(client):
    """GET /api/devices/ returns a list."""
    response = client.get("/api/devices/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_list_deployments(client):
    """GET /api/deployments/ returns a list."""
    response = client.get("/api/deployments/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_audit_log_endpoint(client):
    """GET /api/audit-log/ returns a list."""
    response = client.get("/api/audit-log/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
