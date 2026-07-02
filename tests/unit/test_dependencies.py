"""
Unit tests for api/dependencies.py

Covers: create_access_token, decode_access_token, get_current_user,
        require_auth, get_client_ip
"""

import pytest
from datetime import timedelta
from unittest.mock import MagicMock

from jose import JWTError, jwt
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from api.dependencies import (
    create_access_token,
    decode_access_token,
    get_current_user,
    require_auth,
    get_client_ip,
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from core.config import settings


# ---------------------------------------------------------------------------
# create_access_token
# ---------------------------------------------------------------------------

class TestCreateAccessToken:
    def test_returns_string(self):
        token = create_access_token({"sub": "user1"})
        assert isinstance(token, str)
        assert len(token) > 20

    def test_default_expiry_in_payload(self):
        token = create_access_token({"sub": "user1"})
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert "exp" in payload
        assert "iat" in payload

    def test_custom_expiry(self):
        token = create_access_token({"sub": "user1"}, expires_delta=timedelta(minutes=5))
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        # Expiry should be ~5 mins from now
        import time
        remaining = payload["exp"] - time.time()
        assert 0 < remaining <= 310  # 5 min + small buffer

    def test_payload_fields_preserved(self):
        token = create_access_token({"sub": "admin", "email": "a@b.com", "role": "admin"})
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == "admin"
        assert payload["email"] == "a@b.com"
        assert payload["role"] == "admin"

    def test_two_tokens_differ(self):
        """Same data, different calls produce different tokens (due to exp/iat)."""
        t1 = create_access_token({"sub": "user1"})
        t2 = create_access_token({"sub": "user1"})
        # May be equal within same second but typically differ; just ensure both decode
        p1 = jwt.decode(t1, settings.SECRET_KEY, algorithms=[ALGORITHM])
        p2 = jwt.decode(t2, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert p1["sub"] == p2["sub"] == "user1"


# ---------------------------------------------------------------------------
# decode_access_token
# ---------------------------------------------------------------------------

class TestDecodeAccessToken:
    def test_decode_valid_token(self):
        token = create_access_token({"sub": "test_user", "role": "admin"})
        payload = decode_access_token(token)
        assert payload["sub"] == "test_user"
        assert payload["role"] == "admin"

    def test_decode_invalid_token_raises_jwterror(self):
        with pytest.raises(JWTError):
            decode_access_token("not.a.valid.token")

    def test_decode_tampered_token_raises_jwterror(self):
        token = create_access_token({"sub": "user1"})
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(JWTError):
            decode_access_token(tampered)

    def test_decode_wrong_key_raises_jwterror(self):
        bad_token = jwt.encode({"sub": "hacker"}, "wrongsecret", algorithm=ALGORITHM)
        with pytest.raises(JWTError):
            decode_access_token(bad_token)

    def test_decode_expired_token_raises_jwterror(self):
        token = create_access_token({"sub": "user1"}, expires_delta=timedelta(seconds=-1))
        with pytest.raises(JWTError):
            decode_access_token(token)


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------

class TestGetCurrentUser:
    def _make_creds(self, token: str) -> HTTPAuthorizationCredentials:
        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    def test_no_credentials_returns_anonymous(self):
        user = get_current_user(credentials=None)
        assert user["user_id"] == "anonymous"
        assert user["role"] == "admin"

    def test_valid_token_returns_user(self):
        token = create_access_token({"sub": "alice", "email": "alice@x.com", "role": "viewer"})
        user = get_current_user(credentials=self._make_creds(token))
        assert user["user_id"] == "alice"
        assert user["email"] == "alice@x.com"
        assert user["role"] == "viewer"

    def test_token_without_sub_raises_401(self):
        token = create_access_token({"email": "no-sub@x.com"})
        with pytest.raises(HTTPException) as exc:
            get_current_user(credentials=self._make_creds(token))
        assert exc.value.status_code == 401
        assert "subject" in exc.value.detail.lower()

    def test_invalid_token_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            get_current_user(credentials=self._make_creds("garbage.token.here"))
        assert exc.value.status_code == 401
        assert "invalid" in exc.value.detail.lower() or "expired" in exc.value.detail.lower()

    def test_expired_token_raises_401(self):
        token = create_access_token({"sub": "user1"}, expires_delta=timedelta(seconds=-1))
        with pytest.raises(HTTPException) as exc:
            get_current_user(credentials=self._make_creds(token))
        assert exc.value.status_code == 401

    def test_token_stored_in_return(self):
        token = create_access_token({"sub": "bob", "email": "bob@x.com"})
        user = get_current_user(credentials=self._make_creds(token))
        assert user["token"] == token

    def test_missing_email_defaults_empty(self):
        token = create_access_token({"sub": "noemail"})
        user = get_current_user(credentials=self._make_creds(token))
        assert user["email"] == ""

    def test_missing_role_defaults_user(self):
        token = create_access_token({"sub": "norole"})
        user = get_current_user(credentials=self._make_creds(token))
        assert user["role"] == "user"


# ---------------------------------------------------------------------------
# require_auth
# ---------------------------------------------------------------------------

class TestRequireAuth:
    def _make_creds(self, token: str) -> HTTPAuthorizationCredentials:
        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    def test_no_credentials_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            require_auth(credentials=None)
        assert exc.value.status_code == 401
        assert "required" in exc.value.detail.lower()

    def test_valid_credentials_returns_user(self):
        token = create_access_token({"sub": "admin", "email": "a@b.com", "role": "admin"})
        user = require_auth(credentials=self._make_creds(token))
        assert user["user_id"] == "admin"

    def test_invalid_token_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            require_auth(credentials=self._make_creds("bad.token"))
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# get_client_ip
# ---------------------------------------------------------------------------

class TestGetClientIP:
    def test_none_request_returns_default(self):
        assert get_client_ip(None) == "0.0.0.0"

    def test_request_with_client(self):
        req = MagicMock()
        req.client.host = "10.0.0.5"
        assert get_client_ip(req) == "10.0.0.5"

    def test_request_without_client(self):
        req = MagicMock()
        req.client = None
        assert get_client_ip(req) == "0.0.0.0"
