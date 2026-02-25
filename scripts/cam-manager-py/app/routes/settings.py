"""Settings API routes — Postgres is the single source of truth.

Settings are stored in the ``settings`` table and cached in memory with
a short TTL.  Pods fetch their config from the API at runtime — no
restarts needed when settings change.

The ``/api/internal/settings/recording`` endpoint is public (no auth)
so recorder pods can fetch their config without credentials.
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from kubernetes import client
from kubernetes.client.rest import ApiException
import logging
import httpx
import time as time_module

from app.config import get_settings
from app.services.settings_service import settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])
logger = logging.getLogger(__name__)
app_settings = get_settings()


# ── Pydantic models ──────────────────────────────────────────

class ChatbotSettings(BaseModel):
    api_key_configured: bool
    openai_key_configured: bool
    enabled_tools: list[str]
    available_tools: list[str]


class CloudStorageSettings(BaseModel):
    enabled: bool = False
    provider: str = "spaces"
    access_key: str = ""
    secret_key: str = ""
    bucket: str = ""
    region: str = ""
    endpoint: str = ""
    delete_local: bool = True


class SettingsResponse(BaseModel):
    default_resolution: str
    default_framerate: int
    default_camera_node: str
    default_recorder_node: str
    k8s_namespace: str
    cleanup_interval: str
    creating_timeout_minutes: int
    recording_chunk_minutes: int
    node_ips: dict[str, str]
    chatbot: ChatbotSettings
    cloud_storage: CloudStorageSettings


class SettingsUpdate(BaseModel):
    default_resolution: Optional[str] = None
    default_framerate: Optional[int] = None
    default_camera_node: Optional[str] = None
    default_recorder_node: Optional[str] = None
    cleanup_interval: Optional[str] = None
    creating_timeout_minutes: Optional[int] = None
    recording_chunk_minutes: Optional[int] = None
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    chatbot_tools: Optional[list[str]] = None
    cloud_storage: Optional[CloudStorageSettings] = None


class RestartResponse(BaseModel):
    message: str
    restarted: list[str]


# ── K8s helpers ──────────────────────────────────────────────

def get_apps_api():
    from app.services.k8s import apps_api
    return apps_api


def get_core_api():
    from app.services.k8s import core_api
    return core_api


def _restart_deployments(prefixes: tuple[str, ...] = ("falcon-eye-", "agent-")) -> list[str]:
    """Restart deployments matching given prefixes."""
    apps = get_apps_api()
    ns = app_settings.k8s_namespace
    restarted: list[str] = []

    restart_patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "falcon-eye/settings-updated": time_module.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                }
            }
        }
    }

    try:
        deployments = apps.list_namespaced_deployment(namespace=ns)
        for dep in deployments.items:
            name = dep.metadata.name
            if name.startswith(prefixes):
                try:
                    apps.patch_namespaced_deployment(name=name, namespace=ns, body=restart_patch)
                    restarted.append(name)
                    logger.info(f"Restarted deployment: {name}")
                except ApiException as e:
                    logger.error(f"Failed to restart {name}: {e}")
    except ApiException as e:
        logger.error(f"Failed to list deployments: {e}")

    return restarted


def _update_cronjob_schedule(schedule: str):
    """Update the cleanup CronJob schedule."""
    try:
        batch_api = client.BatchV1Api()
        batch_api.patch_namespaced_cron_job(
            name="falcon-eye-cleanup",
            namespace=app_settings.k8s_namespace,
            body={"spec": {"schedule": schedule}},
        )
    except ApiException:
        pass


# ── API key validation ───────────────────────────────────────

async def _validate_anthropic_key(api_key: str) -> bool:
    try:
        async with httpx.AsyncClient() as c:
            res = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={"model": "claude-3-haiku-20240307", "max_tokens": 1, "messages": [{"role": "user", "content": "Hi"}]},
                timeout=10.0,
            )
            return res.status_code != 401
    except Exception as e:
        logger.error(f"Anthropic key validation error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to validate API key: {e}")


async def _validate_openai_key(api_key: str) -> bool:
    try:
        async with httpx.AsyncClient() as c:
            res = await c.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0,
            )
            return res.status_code != 401
    except Exception as e:
        logger.error(f"OpenAI key validation error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to validate API key: {e}")


# ── Routes ───────────────────────────────────────────────────

@router.get("/", response_model=SettingsResponse)
async def get_current_settings():
    """Read current settings from postgres."""
    s = await settings_service.get_all()

    from app.chatbot.tools import AVAILABLE_TOOLS, DEFAULT_TOOLS

    enabled_tools = DEFAULT_TOOLS.copy()
    if s.get("CHATBOT_TOOLS"):
        enabled_tools = [t.strip() for t in s["CHATBOT_TOOLS"].split(",") if t.strip()]

    return SettingsResponse(
        default_resolution=s.get("DEFAULT_RESOLUTION", "640x480"),
        default_framerate=int(s.get("DEFAULT_FRAMERATE", "15")),
        default_camera_node=s.get("DEFAULT_CAMERA_NODE", ""),
        default_recorder_node=s.get("DEFAULT_RECORDER_NODE", ""),
        k8s_namespace=app_settings.k8s_namespace,
        cleanup_interval=s.get("CLEANUP_INTERVAL", "*/2 * * * *"),
        creating_timeout_minutes=int(s.get("CREATING_TIMEOUT_MINUTES", "15")),
        recording_chunk_minutes=int(s.get("RECORDING_CHUNK_MINUTES", "15")),
        node_ips=app_settings.node_ips,
        chatbot=ChatbotSettings(
            api_key_configured=bool(s.get("ANTHROPIC_API_KEY")),
            openai_key_configured=bool(s.get("OPENAI_API_KEY")),
            enabled_tools=enabled_tools,
            available_tools=list(AVAILABLE_TOOLS.keys()),
        ),
        cloud_storage=CloudStorageSettings(
            enabled=s.get("CLOUD_STORAGE_ENABLED", "false").lower() == "true",
            provider=s.get("CLOUD_STORAGE_PROVIDER", "spaces"),
            access_key=s.get("CLOUD_STORAGE_ACCESS_KEY", ""),
            secret_key=s.get("CLOUD_STORAGE_SECRET_KEY", ""),
            bucket=s.get("CLOUD_STORAGE_BUCKET", ""),
            region=s.get("CLOUD_STORAGE_REGION", ""),
            endpoint=s.get("CLOUD_STORAGE_ENDPOINT", ""),
            delete_local=s.get("CLOUD_DELETE_LOCAL", "true").lower() == "true",
        ),
    )


@router.patch("/", response_model=SettingsResponse)
async def update_settings(update: SettingsUpdate, background_tasks: BackgroundTasks):
    """Update settings in postgres. Changes take effect immediately for pods
    that fetch config from the API. Also triggers restart for pods that read
    settings from env (until they are migrated)."""
    updates: dict[str, str] = {}
    need_cleanup_update = False

    if update.default_resolution:
        updates["DEFAULT_RESOLUTION"] = update.default_resolution
    if update.default_framerate:
        updates["DEFAULT_FRAMERATE"] = str(update.default_framerate)
    if update.default_camera_node is not None:
        updates["DEFAULT_CAMERA_NODE"] = update.default_camera_node
    if update.default_recorder_node is not None:
        updates["DEFAULT_RECORDER_NODE"] = update.default_recorder_node
    if update.cleanup_interval:
        updates["CLEANUP_INTERVAL"] = update.cleanup_interval
        need_cleanup_update = True
    if update.creating_timeout_minutes:
        updates["CREATING_TIMEOUT_MINUTES"] = str(update.creating_timeout_minutes)
    if update.recording_chunk_minutes is not None:
        val = max(5, min(60, update.recording_chunk_minutes))
        updates["RECORDING_CHUNK_MINUTES"] = str(val)
    if update.chatbot_tools is not None:
        updates["CHATBOT_TOOLS"] = ",".join(update.chatbot_tools)
    if update.cloud_storage is not None:
        cs = update.cloud_storage
        updates["CLOUD_STORAGE_ENABLED"] = str(cs.enabled).lower()
        updates["CLOUD_STORAGE_PROVIDER"] = cs.provider
        updates["CLOUD_STORAGE_ACCESS_KEY"] = cs.access_key
        updates["CLOUD_STORAGE_SECRET_KEY"] = cs.secret_key
        updates["CLOUD_STORAGE_BUCKET"] = cs.bucket
        updates["CLOUD_STORAGE_REGION"] = cs.region
        updates["CLOUD_STORAGE_ENDPOINT"] = cs.endpoint
        updates["CLOUD_DELETE_LOCAL"] = str(cs.delete_local).lower()

    # API keys — validate then store
    if update.anthropic_api_key:
        if not await _validate_anthropic_key(update.anthropic_api_key):
            raise HTTPException(status_code=400, detail="Invalid Anthropic API key")
        updates["ANTHROPIC_API_KEY"] = update.anthropic_api_key

    if update.openai_api_key:
        if not await _validate_openai_key(update.openai_api_key):
            raise HTTPException(status_code=400, detail="Invalid OpenAI API key")
        updates["OPENAI_API_KEY"] = update.openai_api_key

    if updates:
        await settings_service.set_many(updates)
        logger.info(f"Settings updated: {list(updates.keys())}")

    # Update cleanup CronJob schedule if changed
    if need_cleanup_update:
        background_tasks.add_task(_update_cronjob_schedule, updates["CLEANUP_INTERVAL"])

    return await get_current_settings()


@router.post("/restart-all", response_model=RestartResponse)
async def restart_all_deployments(background_tasks: BackgroundTasks):
    """Manually restart all pods."""
    prefixes = ("falcon-eye-", "agent-", "rec-", "cam-")
    background_tasks.add_task(_restart_deployments, prefixes)

    apps_api = get_apps_api()
    names: list[str] = []
    try:
        deps = apps_api.list_namespaced_deployment(namespace=app_settings.k8s_namespace)
        for dep in deps.items:
            n = dep.metadata.name
            if n.startswith(prefixes):
                names.append(n)
    except ApiException:
        pass

    return RestartResponse(
        message=f"Scheduled restart for {len(names)} deployment(s)",
        restarted=names,
    )


@router.delete("/cameras/all")
async def clear_all_cameras():
    """Delete all cameras from database and K8s."""
    from sqlalchemy import delete, select
    from app.database import get_db_session
    from app.models.camera import Camera
    from app.services import k8s as k8s_service

    deleted_count = 0
    try:
        async with get_db_session() as db:
            result = await db.execute(select(Camera))
            cameras = result.scalars().all()
            for cam in cameras:
                if cam.deployment_name or cam.service_name:
                    try:
                        await k8s_service.delete_camera_deployment(
                            cam.deployment_name or "",
                            cam.service_name or "",
                        )
                    except Exception:
                        pass
                deleted_count += 1
            await db.execute(delete(Camera))
            await db.commit()
        return {"message": f"Deleted {deleted_count} camera(s)", "count": deleted_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
