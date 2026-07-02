"""Authentication endpoints — login and token management."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm, HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from pydantic import BaseModel

from api.dependencies import create_access_token, decode_access_token, ACCESS_TOKEN_EXPIRE_MINUTES

router = APIRouter(prefix="/api/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_bearer = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# In-memory dev users (replace with DB-backed users in production)
# ---------------------------------------------------------------------------

_DEV_USERS = {
    "admin": {
        "user_id": "admin",
        "email": "admin@netdeploy.local",
        "role": "admin",
        # password: "admin"
        "hashed_password": pwd_context.hash("admin"),
    },
    "readonly": {
        "user_id": "readonly",
        "email": "readonly@netdeploy.local",
        "role": "viewer",
        "hashed_password": pwd_context.hash("readonly"),
    },
}


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
    user = _DEV_USERS.get(form_data.username)
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
