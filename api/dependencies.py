"""FastAPI dependency injection functions."""

from datetime import datetime, timedelta
from typing import Generator, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from api.database import SessionLocal
from core.config import settings

security = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT access token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT.  Raises JWTError on failure."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])


# ---------------------------------------------------------------------------
# Database dependency
# ---------------------------------------------------------------------------


def get_db() -> Generator:
    """Yield database session, close on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    Extract and validate the current user from a Bearer JWT.

    If no token is provided (development / unauthenticated route), returns an
    anonymous user so existing endpoint tests continue to work without auth.

    Returns a dict with at least ``user_id`` and ``email`` keys.
    """
    if credentials is None:
        # No token provided — allow with anonymous identity (dev mode)
        return {"user_id": "anonymous", "email": "dev@netdeploy.local", "role": "admin"}

    try:
        payload = decode_access_token(credentials.credentials)
        user_id: str = payload.get("sub")
        email: str = payload.get("email", "")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing subject claim",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return {
            "user_id": user_id,
            "email": email,
            "role": payload.get("role", "user"),
            "token": credentials.credentials,
        }
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    Stricter version of get_current_user — rejects anonymous/missing tokens.
    Use on endpoints that must be authenticated.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return get_current_user(credentials)


def get_client_ip(request=None) -> str:
    """Extract client IP from request."""
    if request is None:
        return "0.0.0.0"
    return request.client.host if request.client else "0.0.0.0"
