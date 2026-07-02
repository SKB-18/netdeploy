"""Authentication endpoints — login and token management."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm, HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from pydantic import BaseModel

from api.dependencies import create_access_token, decode_access_token, ACCESS_TOKEN_EXPIRE_MINUTES

router = APIRouter(prefix="/api/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

_bearer = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# In-memory dev users — passwords hashed lazily on first request
# ---------------------------------------------------------------------------

_RAW_USERS = {
    "admin":    {"user_id": "admin",    "email": "admin@netdeploy.local",    "role": "admin",  "password": "admin"},
    "readonly": {"user_id": "readonly", "email": "readonly@netdeploy.local", "role": "viewer", "password": "readonly"},
}
_DEV_USERS: dict = {}   # populated on first login attempt


def _get_user(username: str):
    """Return user dict with hashed_password, hashing lazily on first access."""
    if username not in _DEV_USERS and username in _RAW_USERS:
        raw = _RAW_USERS[username]
        _DEV_USERS[username] = {
            "user_id": raw["user_id"],
            "email": raw["email"],
            "role": raw["role"],
            "hashed_password": pwd_context.hash(raw["password"]),
        }
    return _DEV_USERS.get(username)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_EXPIRE_MINUTES * 60


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/token", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Issue a JWT access token.

    Send as form body: ``username=admin&password=admin``
    (OAuth2 password flow — used by Swagger UI's Authorize button).
    """
    user = _get_user(form_data.username)
    if not user or not pwd_context.verify(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        data={
            "sub": user["user_id"],
            "email": user["email"],
            "role": user["role"],
        },
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return TokenResponse(access_token=token)


@router.get("/me")
async def get_me(credentials: HTTPAuthorizationCredentials = Depends(_bearer)):
    """Return current user info decoded from the Bearer JWT."""
    from api.dependencies import get_current_user
    user = get_current_user(credentials)
    return {k: v for k, v in user.items() if k != "token"}
