"""
Integration tests for /api/auth endpoints.

Covers: login success/failure, /me with valid/invalid/missing token,
        token content verification.
"""

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# POST /api/auth/token
# ---------------------------------------------------------------------------

class TestLogin:
    def test_admin_login_success(self, client):
        r = client.post(
            "/api/auth/token",
            data={"username": "admin", "password": "admin"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["expires_in"] > 0
        assert len(body["access_token"]) > 20

    def test_readonly_login_success(self, client):
        r = client.post(
            "/api/auth/token",
            data={"username": "readonly", "password": "readonly"},
        )
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_wrong_password_returns_401(self, client):
        r = client.post(
            "/api/auth/token",
            data={"username": "admin", "password": "wrongpassword"},
        )
        assert r.status_code == 401
        assert "incorrect" in r.json()["detail"].lower()

    def test_unknown_user_returns_401(self, client):
        r = client.post(
            "/api/auth/token",
            data={"username": "nobody", "password": "whatever"},
        )
        assert r.status_code == 401

    def test_empty_password_rejected(self, client):
        """FastAPI OAuth2 form validation rejects empty password (422 or 401)."""
        r = client.post(
            "/api/auth/token",
            data={"username": "admin", "password": ""},
        )
        assert r.status_code in (401, 422)

    def test_login_twice_both_succeed(self, client):
        """Lazy hashing works correctly on second call."""
        r1 = client.post("/api/auth/token", data={"username": "admin", "password": "admin"})
        r2 = client.post("/api/auth/token", data={"username": "admin", "password": "admin"})
        assert r1.status_code == 200
        assert r2.status_code == 200

    def test_token_payload_contains_role(self, client):
        r = client.post("/api/auth/token", data={"username": "admin", "password": "admin"})
        token = r.json()["access_token"]
        # Verify via /me endpoint (no need to decode directly)
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.json()["user_id"] == "admin"
        assert me.json()["role"] == "admin"

    def test_readonly_token_has_viewer_role(self, client):
        r = client.post("/api/auth/token", data={"username": "readonly", "password": "readonly"})
        token = r.json()["access_token"]
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.json()["role"] == "viewer"


# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------

class TestGetMe:
    def _get_token(self, client, username="admin", password="admin") -> str:
        r = client.post("/api/auth/token", data={"username": username, "password": password})
        return r.json()["access_token"]

    def test_me_with_valid_token(self, client):
        token = self._get_token(client)
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        body = r.json()
        assert body["user_id"] == "admin"
        assert body["role"] == "admin"

    def test_me_readonly_user(self, client):
        token = self._get_token(client, "readonly", "readonly")
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["role"] == "viewer"

    def test_me_without_token_returns_anonymous(self, client):
        r = client.get("/api/auth/me")
        assert r.status_code == 200
        body = r.json()
        assert body["user_id"] == "anonymous"

    def test_me_with_invalid_token_returns_401(self, client):
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.real.token"})
        assert r.status_code == 401

    def test_me_token_field_not_exposed(self, client):
        """The raw token should not be returned in /me response."""
        token = self._get_token(client)
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert "token" not in r.json()

    def test_me_email_present(self, client):
        token = self._get_token(client)
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert "email" in r.json()
        assert "@" in r.json()["email"]
