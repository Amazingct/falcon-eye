"""Authentication routes"""
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional

from app.auth import (
    get_auth_secret,
    create_auth_secret,
    update_auth_secret,
    verify_password,
    create_access_token,
    decode_token,
    require_auth,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
_optional_bearer = HTTPBearer(auto_error=False)


class SetupRequest(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)


class LoginRequest(BaseModel):
    username: str
    password: str


class CredentialsUpdate(BaseModel):
    current_password: str
    new_username: str | None = None
    new_password: str | None = None


@router.get("/status")
async def auth_status(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
):
    """Check if setup is complete and if current session is valid."""
    creds = get_auth_secret()
    setup_complete = creds is not None

    authenticated = False
    username = None
    token = None
    if credentials:
        token = credentials.credentials
    else:
        token = request.query_params.get("token")

    if token:
        username = decode_token(token)
        if username:
            authenticated = True

    return {
        "setup_complete": setup_complete,
        "authenticated": authenticated,
        "username": username,
    }


@router.post("/setup")
async def setup_credentials(req: SetupRequest):
    """Initial setup - create credentials. Only works if no credentials exist."""
    existing = get_auth_secret()
    if existing:
        raise HTTPException(status_code=400, detail="Credentials already configured")

    create_auth_secret(req.username, req.password)
    token = create_access_token(req.username)
    return {"message": "Setup complete", "token": token, "username": req.username}


@router.post("/login")
async def login(req: LoginRequest):
    """Login with username and password, returns JWT token."""
    creds = get_auth_secret()
    if not creds:
        raise HTTPException(status_code=400, detail="Setup not complete")

    if req.username != creds["username"] or not verify_password(req.password, creds["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(req.username)
    return {"token": token, "username": req.username}


@router.post("/logout")
async def logout(user: str = Depends(require_auth)):
    """Logout (client-side token removal). Server-side is stateless."""
    return {"message": "Logged out"}


@router.patch("/credentials")
async def change_credentials(req: CredentialsUpdate, user: str = Depends(require_auth)):
    """Change username and/or password. Requires current password."""
    creds = get_auth_secret()
    if not creds:
        raise HTTPException(status_code=400, detail="No credentials configured")

    if not verify_password(req.current_password, creds["password_hash"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    new_username = req.new_username or creds["username"]
    new_password = req.new_password or req.current_password

    update_auth_secret(new_username, new_password)
    token = create_access_token(new_username)
    return {"message": "Credentials updated", "token": token, "username": new_username}
