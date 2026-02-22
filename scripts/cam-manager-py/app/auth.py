"""Authentication utilities - JWT tokens and K8s secret management"""
import os
import base64
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from kubernetes import client
from kubernetes.client.rest import ApiException

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT settings
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
SECRET_NAME = "falcon-eye-auth"

# Generate a JWT signing key on first import, or read from env
_jwt_secret = os.environ.get("JWT_SECRET_KEY", "")
if not _jwt_secret:
    _jwt_secret = secrets.token_hex(32)

security = HTTPBearer(auto_error=False)


def _get_core_api():
    from app.services.k8s import core_api
    return core_api


def get_auth_secret() -> Optional[dict]:
    """Read falcon-eye-auth secret from K8s. Returns dict with 'username' and 'password_hash' or None."""
    try:
        secret = _get_core_api().read_namespaced_secret(
            name=SECRET_NAME,
            namespace=settings.k8s_namespace,
        )
        data = secret.data or {}
        if "username" not in data or "password_hash" not in data:
            return None
        return {
            "username": base64.b64decode(data["username"]).decode(),
            "password_hash": base64.b64decode(data["password_hash"]).decode(),
        }
    except ApiException as e:
        if e.status == 404:
            return None
        logger.error(f"Error reading auth secret: {e.reason}")
        return None


def create_auth_secret(username: str, password: str) -> bool:
    """Create the falcon-eye-auth K8s secret with hashed password."""
    password_hash = pwd_context.hash(password)
    body = client.V1Secret(
        metadata=client.V1ObjectMeta(name=SECRET_NAME, namespace=settings.k8s_namespace),
        data={
            "username": base64.b64encode(username.encode()).decode(),
            "password_hash": base64.b64encode(password_hash.encode()).decode(),
        },
    )
    try:
        _get_core_api().create_namespaced_secret(
            namespace=settings.k8s_namespace,
            body=body,
        )
        return True
    except ApiException as e:
        if e.status == 409:
            logger.error("Auth secret already exists")
            return False
        logger.error(f"Error creating auth secret: {e.reason}")
        raise


def update_auth_secret(username: str, password: str) -> bool:
    """Update credentials in the falcon-eye-auth K8s secret."""
    password_hash = pwd_context.hash(password)
    body = client.V1Secret(
        metadata=client.V1ObjectMeta(name=SECRET_NAME, namespace=settings.k8s_namespace),
        data={
            "username": base64.b64encode(username.encode()).decode(),
            "password_hash": base64.b64encode(password_hash.encode()).decode(),
        },
    )
    try:
        _get_core_api().replace_namespaced_secret(
            name=SECRET_NAME,
            namespace=settings.k8s_namespace,
            body=body,
        )
        return True
    except ApiException as e:
        logger.error(f"Error updating auth secret: {e.reason}")
        raise


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(username: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": username, "exp": expire}
    return jwt.encode(to_encode, _jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[str]:
    """Decode JWT token, return username or None."""
    try:
        payload = jwt.decode(token, _jwt_secret, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """FastAPI dependency that requires a valid JWT token.
    Checks Authorization header first, then ?token= query param (for img/stream URLs)."""
    token = None
    if credentials:
        token = credentials.credentials
    else:
        # Fallback: query parameter (for <img src=...> tags)
        token = request.query_params.get("token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username = decode_token(token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username
