"""Settings API routes — ConfigMap is the single source of truth.

Every setting (including API keys) lives in the ``falcon-eye-config``
ConfigMap.  When settings are saved the ConfigMap is updated and **all**
pods that consume it are automatically restarted so they pick up the
latest values.
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

router = APIRouter(prefix="/api/settings", tags=["settings"])
logger = logging.getLogger(__name__)
settings = get_settings()


# ── Pydantic models ──────────────────────────────────────────

class ChatbotSettings(BaseModel):
    api_key_configured: bool
    openai_key_configured: bool
    enabled_tools: list[str]
    available_tools: list[str]


class CloudStorageSettings(BaseModel):
    enabled: bool = False
    provider: str = "spaces"  # "s3" | "spaces"
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


def _read_configmap() -> dict:
    """Read falcon-eye-config ConfigMap data, returning empty dict on 404."""
    try:
        cm = get_core_api().read_namespaced_config_map(
            name="falcon-eye-config",
            namespace=settings.k8s_namespace,
        )
        return dict(cm.data) if cm.data else {}
    except ApiException as e:
        if e.status == 404:
            return {}
        raise


def _write_configmap(data: dict):
    """Create-or-replace the falcon-eye-config ConfigMap."""
    core_api = get_core_api()
    body = client.V1ConfigMap(
        metadata=client.V1ObjectMeta(
            name="falcon-eye-config",
            namespace=settings.k8s_namespace,
        ),
        data=data,
    )
    try:
        core_api.replace_namespaced_config_map(
            name="falcon-eye-config",
            namespace=settings.k8s_namespace,
            body=body,
        )
    except ApiException as e:
        if e.status == 404:
            core_api.create_namespaced_config_map(
                namespace=settings.k8s_namespace,
                body=body,
            )
        else:
            raise HTTPException(status_code=500, detail=f"K8s error: {e.reason}")


def _restart_all_pods():
    """Restart every Deployment and CronJob that reads from the ConfigMap."""
    apps_api = get_apps_api()
    ns = settings.k8s_namespace
    restarted: list[str] = []

    restart_patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "falcon-eye/configmap-updated": time_module.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                }
            }
        }
    }

    try:
        deployments = apps_api.list_namespaced_deployment(namespace=ns)
        for dep in deployments.items:
            name = dep.metadata.name
            if name.startswith(("falcon-eye-", "agent-", "rec-", "cam-")):
                try:
                    apps_api.patch_namespaced_deployment(name=name, namespace=ns, body=restart_patch)
                    restarted.append(name)
                    logger.info(f"Restarted deployment: {name}")
                except ApiException as e:
                    logger.error(f"Failed to restart {name}: {e}")
    except ApiException as e:
        logger.error(f"Failed to list deployments: {e}")

    # Update CronJob schedule if it changed
    try:
        cm_data = _read_configmap()
        if "CLEANUP_INTERVAL" in cm_data:
            batch_api = client.BatchV1Api()
            batch_api.patch_namespaced_cron_job(
                name="falcon-eye-cleanup",
                namespace=ns,
                body={"spec": {"schedule": cm_data["CLEANUP_INTERVAL"]}},
            )
            restarted.append("falcon-eye-cleanup (cronjob)")
    except ApiException:
        pass

    return restarted


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
            if res.status_code == 401:
                return False
            return True
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
            if res.status_code == 401:
                return False
            return True
    except Exception as e:
        logger.error(f"OpenAI key validation error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to validate API key: {e}")


# ── Routes ───────────────────────────────────────────────────

@router.get("/", response_model=SettingsResponse)
async def get_current_settings():
    """Read current settings from the ConfigMap (single source of truth)."""
    cm = _read_configmap()

    from app.chatbot.tools import AVAILABLE_TOOLS, DEFAULT_TOOLS

    enabled_tools = DEFAULT_TOOLS.copy()
    if cm.get("CHATBOT_TOOLS"):
        enabled_tools = [t.strip() for t in cm["CHATBOT_TOOLS"].split(",") if t.strip()]

    return SettingsResponse(
        default_resolution=cm.get("DEFAULT_RESOLUTION", settings.default_resolution),
        default_framerate=int(cm.get("DEFAULT_FRAMERATE", settings.default_framerate)),
        default_camera_node=cm.get("DEFAULT_CAMERA_NODE", settings.default_camera_node),
        default_recorder_node=cm.get("DEFAULT_RECORDER_NODE", settings.default_recorder_node),
        k8s_namespace=settings.k8s_namespace,
        cleanup_interval=cm.get("CLEANUP_INTERVAL", "*/2 * * * *"),
        creating_timeout_minutes=int(cm.get("CREATING_TIMEOUT_MINUTES", "15")),
        recording_chunk_minutes=int(cm.get("RECORDING_CHUNK_MINUTES", "15")),
        node_ips=settings.node_ips,
        chatbot=ChatbotSettings(
            api_key_configured=bool(cm.get("ANTHROPIC_API_KEY")),
            openai_key_configured=bool(cm.get("OPENAI_API_KEY")),
            enabled_tools=enabled_tools,
            available_tools=list(AVAILABLE_TOOLS.keys()),
        ),
        cloud_storage=CloudStorageSettings(
            enabled=cm.get("CLOUD_STORAGE_ENABLED", "false").lower() == "true",
            provider=cm.get("CLOUD_STORAGE_PROVIDER", "spaces"),
            access_key=cm.get("CLOUD_STORAGE_ACCESS_KEY", ""),
            secret_key=cm.get("CLOUD_STORAGE_SECRET_KEY", ""),
            bucket=cm.get("CLOUD_STORAGE_BUCKET", ""),
            region=cm.get("CLOUD_STORAGE_REGION", ""),
            endpoint=cm.get("CLOUD_STORAGE_ENDPOINT", ""),
            delete_local=cm.get("CLOUD_DELETE_LOCAL", "true").lower() == "true",
        ),
    )


@router.patch("/", response_model=SettingsResponse)
async def update_settings(update: SettingsUpdate, background_tasks: BackgroundTasks):
    """Update settings in ConfigMap, then restart all pods that consume it."""
    cm = _read_configmap()

    # Apply non-key fields
    if update.default_resolution:
        cm["DEFAULT_RESOLUTION"] = update.default_resolution
    if update.default_framerate:
        cm["DEFAULT_FRAMERATE"] = str(update.default_framerate)
    if update.default_camera_node is not None:
        cm["DEFAULT_CAMERA_NODE"] = update.default_camera_node
    if update.default_recorder_node is not None:
        cm["DEFAULT_RECORDER_NODE"] = update.default_recorder_node
    if update.cleanup_interval:
        cm["CLEANUP_INTERVAL"] = update.cleanup_interval
    if update.creating_timeout_minutes:
        cm["CREATING_TIMEOUT_MINUTES"] = str(update.creating_timeout_minutes)
    if update.recording_chunk_minutes is not None:
        val = max(5, min(60, update.recording_chunk_minutes))
        cm["RECORDING_CHUNK_MINUTES"] = str(val)
    if update.chatbot_tools is not None:
        cm["CHATBOT_TOOLS"] = ",".join(update.chatbot_tools)
    if update.cloud_storage is not None:
        cs = update.cloud_storage
        cm["CLOUD_STORAGE_ENABLED"] = str(cs.enabled).lower()
        cm["CLOUD_STORAGE_PROVIDER"] = cs.provider
        cm["CLOUD_STORAGE_ACCESS_KEY"] = cs.access_key
        cm["CLOUD_STORAGE_SECRET_KEY"] = cs.secret_key
        cm["CLOUD_STORAGE_BUCKET"] = cs.bucket
        cm["CLOUD_STORAGE_REGION"] = cs.region
        cm["CLOUD_STORAGE_ENDPOINT"] = cs.endpoint
        cm["CLOUD_DELETE_LOCAL"] = str(cs.delete_local).lower()

    # API keys — validate then write directly into the ConfigMap
    if update.anthropic_api_key:
        if not await _validate_anthropic_key(update.anthropic_api_key):
            raise HTTPException(status_code=400, detail="Invalid Anthropic API key")
        cm["ANTHROPIC_API_KEY"] = update.anthropic_api_key

    if update.openai_api_key:
        if not await _validate_openai_key(update.openai_api_key):
            raise HTTPException(status_code=400, detail="Invalid OpenAI API key")
        cm["OPENAI_API_KEY"] = update.openai_api_key

    _write_configmap(cm)
    logger.info("ConfigMap updated — scheduling pod restarts")

    background_tasks.add_task(_restart_all_pods)

    return await get_current_settings()


@router.post("/restart-all", response_model=RestartResponse)
async def restart_all_deployments(background_tasks: BackgroundTasks):
    """Manually restart all pods (applies latest ConfigMap)."""
    background_tasks.add_task(_restart_all_pods)

    apps_api = get_apps_api()
    names: list[str] = []
    try:
        deps = apps_api.list_namespaced_deployment(namespace=settings.k8s_namespace)
        for dep in deps.items:
            n = dep.metadata.name
            if n.startswith(("falcon-eye-", "agent-", "rec-", "cam-")):
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
