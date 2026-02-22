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

# Lazy-loaded JWT secret (loaded from K8s secret on first use)
_jwt_secret: Optional[str] = None

# Internal API key for intra-cluster traffic
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "")

security = HTTPBearer(auto_error=False)


def _get_core_api():
    from app.services.k8s import core_api
    return core_api


def _get_jwt_secret() -> str:
    """Get JWT secret: K8s auth secret > env var > random fallback."""
    global _jwt_secret
    if _jwt_secret:
        return _jwt_secret

    # Try K8s secret
    try:
        secret = _get_core_api().read_namespaced_secret(
            name=SECRET_NAME,
            namespace=settings.k8s_namespace,
        )
        data = secret.data or {}
        if "jwt_secret" in data:
            _jwt_secret = base64.b64decode(data["jwt_secret"]).decode()
            return _jwt_secret
    except Exception:
        pass

    # Try env var
    env_secret = os.environ.get("JWT_SECRET_KEY", "")
    if env_secret:
        _jwt_secret = env_secret
        return _jwt_secret

    # Random fallback (tokens won't survive restart)
    logger.warning("No persistent JWT secret found — generating ephemeral key")
    _jwt_secret = secrets.token_hex(32)
    return _jwt_secret


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


def is_default_credentials() -> bool:
    """Check if credentials are still the defaults (admin/falconeye)."""
    creds = get_auth_secret()
    if not creds:
        return False
    return creds["username"] == "admin" and verify_password("falconeye", creds["password_hash"])


def create_auth_secret(username: str, password: str) -> bool:
    """Create the falcon-eye-auth K8s secret with hashed password."""
    password_hash = pwd_context.hash(password)
    jwt_key = secrets.token_hex(32)
    internal_key = secrets.token_hex(32)

    body = client.V1Secret(
        metadata=client.V1ObjectMeta(name=SECRET_NAME, namespace=settings.k8s_namespace),
        data={
            "username": base64.b64encode(username.encode()).decode(),
            "password_hash": base64.b64encode(password_hash.encode()).decode(),
            "jwt_secret": base64.b64encode(jwt_key.encode()).decode(),
            "internal_api_key": base64.b64encode(internal_key.encode()).decode(),
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
    """Update credentials in the falcon-eye-auth K8s secret, preserving jwt_secret and internal_api_key."""
    password_hash = pwd_context.hash(password)

    # Read existing secret to preserve jwt_secret and internal_api_key
    try:
        existing = _get_core_api().read_namespaced_secret(
            name=SECRET_NAME, namespace=settings.k8s_namespace
        )
        existing_data = existing.data or {}
    except Exception:
        existing_data = {}

    new_data = {
        "username": base64.b64encode(username.encode()).decode(),
        "password_hash": base64.b64encode(password_hash.encode()).decode(),
    }
    # Preserve existing keys
    for key in ("jwt_secret", "internal_api_key"):
        if key in existing_data:
            new_data[key] = existing_data[key]

    body = client.V1Secret(
        metadata=client.V1ObjectMeta(name=SECRET_NAME, namespace=settings.k8s_namespace),
        data=new_data,
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
    return jwt.encode(to_encode, _get_jwt_secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[str]:
    """Decode JWT token, return username or None."""
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """FastAPI dependency that requires a valid JWT token or internal API key.
    Checks: 1) X-Internal-Key header  2) Authorization Bearer  3) ?token= query param."""

    # 1. Internal API key bypass (intra-cluster traffic)
    internal_key = request.headers.get("X-Internal-Key")
    if internal_key and INTERNAL_API_KEY and internal_key == INTERNAL_API_KEY:
        return "__internal__"

    # 2. JWT from Authorization header or query param
    token = None
    if credentials:
        token = credentials.credentials
    else:
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
