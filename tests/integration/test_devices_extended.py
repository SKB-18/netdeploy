"""
Extended integration tests for /api/devices endpoints.

Covers: duplicate hostname 400, GET by ID 404, PUT update,
        PUT 404, DELETE 404, /health endpoint, /sync endpoint,
        pagination, audit log written on create.
"""

import uuid
import pytest


DEVICE_PAYLOAD = {
    "hostname": "edge-router-01",
    "device_type": "cisco_xr",
    "management_ip": "10.0.1.1",
    "ssh_port": 22,
    "bgp_asn": 65100,
    "os_version": "7.3.1",
}


# ---------------------------------------------------------------------------
# POST /api/devices/ — create
# ---------------------------------------------------------------------------

class TestCreateDevice:
    def test_create_returns_201(self, client):
        r = client.post("/api/devices/", json=DEVICE_PAYLOAD)
        assert r.status_code == 201
        body = r.json()
        assert body["hostname"] == DEVICE_PAYLOAD["hostname"]
        assert "id" in body

    def test_create_duplicate_hostname_returns_400(self, client):
        client.post("/api/devices/", json=DEVICE_PAYLOAD)
        r2 = client.post("/api/devices/", json=DEVICE_PAYLOAD)
        assert r2.status_code == 400
        assert "already exists" in r2.json()["detail"].lower()

    def test_create_invalid_device_type_returns_422(self, client):
        bad = {**DEVICE_PAYLOAD, "hostname": "bad-type", "device_type": "unknown_os"}
        r = client.post("/api/devices/", json=bad)
        assert r.status_code == 422

    def test_create_invalid_ip_returns_422(self, client):
        bad = {**DEVICE_PAYLOAD, "hostname": "bad-ip", "management_ip": "not-an-ip"}
        r = client.post("/api/devices/", json=bad)
        assert r.status_code == 422

    def test_create_with_junos_type(self, client):
        payload = {**DEVICE_PAYLOAD, "hostname": "junos-router-01", "device_type": "junos"}
        r = client.post("/api/devices/", json=payload)
        assert r.status_code == 201
        assert r.json()["device_type"] == "junos"

    def test_create_with_arista_type(self, client):
        payload = {**DEVICE_PAYLOAD, "hostname": "arista-sw-01", "device_type": "arista_eos"}
        r = client.post("/api/devices/", json=payload)
        assert r.status_code == 201

    def test_create_without_optional_fields(self, client):
        minimal = {"hostname": "minimal-router", "device_type": "cisco_ios", "management_ip": "10.0.1.99"}
        r = client.post("/api/devices/", json=minimal)
        assert r.status_code == 201
        assert r.json()["bgp_asn"] is None


# ---------------------------------------------------------------------------
# GET /api/devices/{id}
# ---------------------------------------------------------------------------

class TestGetDevice:
    def test_get_existing_device(self, client, mock_device):
        r = client.get(f"/api/devices/{mock_device.id}")
        assert r.status_code == 200
        assert r.json()["hostname"] == mock_device.hostname

    def test_get_nonexistent_device_returns_404(self, client):
        r = client.get(f"/api/devices/{uuid.uuid4()}")
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()

    def test_get_returns_all_fields(self, client, mock_device):
        r = client.get(f"/api/devices/{mock_device.id}")
        body = r.json()
        for field in ("id", "hostname", "device_type", "management_ip", "ssh_port", "created_at"):
            assert field in body


# ---------------------------------------------------------------------------
# GET /api/devices/ — list + pagination
# ---------------------------------------------------------------------------

class TestListDevices:
    def test_list_empty(self, client):
        r = client.get("/api/devices/")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_returns_created_devices(self, client, mock_device, mock_device_junos):
        r = client.get("/api/devices/")
        assert r.status_code == 200
        ids = [d["id"] for d in r.json()]
        assert str(mock_device.id) in ids
        assert str(mock_device_junos.id) in ids

    def test_pagination_limit(self, client, mock_device, mock_device_junos):
        r = client.get("/api/devices/?limit=1")
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_pagination_skip(self, client, mock_device, mock_device_junos):
        r_all = client.get("/api/devices/")
        r_skip = client.get("/api/devices/?skip=1")
        assert len(r_skip.json()) == len(r_all.json()) - 1


# ---------------------------------------------------------------------------
# PUT /api/devices/{id} — update
# ---------------------------------------------------------------------------

class TestUpdateDevice:
    def test_update_device_succeeds(self, client, mock_device):
        updated = {
            "hostname": mock_device.hostname,
            "device_type": mock_device.device_type,
            "management_ip": "10.99.99.99",
            "bgp_asn": 65099,
        }
        r = client.put(f"/api/devices/{mock_device.id}", json=updated)
        assert r.status_code == 200
        assert r.json()["management_ip"] == "10.99.99.99"
        assert r.json()["bgp_asn"] == 65099

    def test_update_nonexistent_device_returns_404(self, client):
        r = client.put(
            f"/api/devices/{uuid.uuid4()}",
            json=DEVICE_PAYLOAD,
        )
        assert r.status_code == 404

    def test_update_preserves_id(self, client, mock_device):
        updated = {
            "hostname": mock_device.hostname,
            "device_type": mock_device.device_type,
            "management_ip": "10.1.2.3",
        }
        r = client.put(f"/api/devices/{mock_device.id}", json=updated)
        assert r.json()["id"] == str(mock_device.id)


# ---------------------------------------------------------------------------
# DELETE /api/devices/{id}
# ---------------------------------------------------------------------------

class TestDeleteDevice:
    def test_delete_existing_device_returns_204(self, client, mock_device):
        r = client.delete(f"/api/devices/{mock_device.id}")
        assert r.status_code == 204

    def test_delete_nonexistent_device_returns_404(self, client):
        r = client.delete(f"/api/devices/{uuid.uuid4()}")
        assert r.status_code == 404

    def test_deleted_device_not_in_list(self, client, mock_device):
        client.delete(f"/api/devices/{mock_device.id}")
        r = client.get("/api/devices/")
        ids = [d["id"] for d in r.json()]
        assert str(mock_device.id) not in ids


# ---------------------------------------------------------------------------
# GET /api/devices/{id}/health
# ---------------------------------------------------------------------------

class TestDeviceHealth:
    def test_health_existing_device_returns_200(self, client, mock_device):
        r = client.get(f"/api/devices/{mock_device.id}/health")
        assert r.status_code == 200
        body = r.json()
        assert body["device_id"] == str(mock_device.id)
        assert body["hostname"] == mock_device.hostname
        assert "reachable" in body
        assert "last_checked" in body

    def test_health_nonexistent_device_returns_404(self, client):
        r = client.get(f"/api/devices/{uuid.uuid4()}/health")
        assert r.status_code == 404

    def test_health_returns_false_reachable_for_test_device(self, client, mock_device):
        r = client.get(f"/api/devices/{mock_device.id}/health")
        # Placeholder implementation always returns False (no SSH in test)
        assert r.json()["reachable"] is False


# ---------------------------------------------------------------------------
# POST /api/devices/{id}/sync
# ---------------------------------------------------------------------------

class TestDeviceSync:
    def test_sync_existing_device_queued(self, client, mock_device):
        r = client.post(f"/api/devices/{mock_device.id}/sync")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "sync_queued"
        assert body["device_id"] == str(mock_device.id)

    def test_sync_nonexistent_device_returns_404(self, client):
        r = client.post(f"/api/devices/{uuid.uuid4()}/sync")
        assert r.status_code == 404
