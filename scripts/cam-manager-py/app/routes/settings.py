"""Settings API routes"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from kubernetes import client
from kubernetes.client.rest import ApiException
import logging
import time
import httpx

from app.config import get_settings


async def validate_anthropic_api_key(api_key: str) -> bool:
    """Validate Anthropic API key by making a test request"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "Hi"}]
                },
                timeout=10.0
            )
            # 200 = valid, 401 = invalid key, other errors might be rate limits etc
            if response.status_code == 200:
                return True
            elif response.status_code == 401:
                return False
            else:
                # Other errors (rate limit, etc) - key might still be valid
                logger.warning(f"API key validation got status {response.status_code}")
                return True  # Assume valid if not explicitly 401
    except Exception as e:
        logger.error(f"API key validation error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to validate API key: {str(e)}")

router = APIRouter(prefix="/api/settings", tags=["settings"])
logger = logging.getLogger(__name__)
settings = get_settings()


class ChatbotSettings(BaseModel):
    """Chatbot configuration"""
    api_key_configured: bool
    enabled_tools: list[str]
    available_tools: list[str]


class SettingsResponse(BaseModel):
    """Current settings"""
    default_resolution: str
    default_framerate: int
    k8s_namespace: str
    cleanup_interval: str
    creating_timeout_minutes: int
    node_ips: dict[str, str]
    chatbot: ChatbotSettings


class SettingsUpdate(BaseModel):
    """Settings update request"""
    default_resolution: Optional[str] = None
    default_framerate: Optional[int] = None
    cleanup_interval: Optional[str] = None
    creating_timeout_minutes: Optional[int] = None
    anthropic_api_key: Optional[str] = None
    chatbot_tools: Optional[list[str]] = None


class RestartResponse(BaseModel):
    """Restart response"""
    message: str
    restarted: list[str]


def get_apps_api():
    """Get K8s AppsV1 API"""
    from app.services.k8s import apps_api
    return apps_api


def get_core_api():
    """Get K8s CoreV1 API"""
    from app.services.k8s import core_api
    return core_api


async def _update_api_key_secret(core_api, api_key: str):
    """Store Anthropic API key in Kubernetes Secret"""
    import base64
    
    secret_name = "falcon-eye-secrets"
    namespace = settings.k8s_namespace
    
    # Encode the key
    encoded_key = base64.b64encode(api_key.encode()).decode()
    
    secret = client.V1Secret(
        metadata=client.V1ObjectMeta(
            name=secret_name,
            namespace=namespace,
        ),
        type="Opaque",
        data={"ANTHROPIC_API_KEY": encoded_key},
    )
    
    try:
        # Try to replace existing secret
        core_api.replace_namespaced_secret(
            name=secret_name,
            namespace=namespace,
            body=secret,
        )
    except ApiException as e:
        if e.status == 404:
            # Create if doesn't exist
            core_api.create_namespaced_secret(
                namespace=namespace,
                body=secret,
            )
        else:
            raise
    
    # Update API deployment to use the secret
    apps_api = get_apps_api()
    
    # Patch deployment to add secret env var
    patch = {
        "spec": {
            "template": {
                "spec": {
                    "containers": [{
                        "name": "api",
                        "envFrom": [
                            {"configMapRef": {"name": "falcon-eye-config"}},
                            {"secretRef": {"name": secret_name, "optional": True}},
                        ]
                    }]
                }
            }
        }
    }
    
    try:
        apps_api.patch_namespaced_deployment(
            name="falcon-eye-api",
            namespace=namespace,
            body=patch,
        )
    except ApiException:
        pass  # Deployment might not exist yet


@router.get("/", response_model=SettingsResponse)
async def get_current_settings():
    """Get current settings"""
    # Defaults from env/pydantic settings
    default_resolution = settings.default_resolution
    default_framerate = settings.default_framerate
    cleanup_interval = "*/10 * * * *"
    creating_timeout = 3
    
    # Chatbot settings
    from app.chatbot.tools import AVAILABLE_TOOLS, DEFAULT_TOOLS
    import os
    
    api_key_configured = bool(os.getenv("ANTHROPIC_API_KEY"))
    enabled_tools = DEFAULT_TOOLS.copy()
    
    # Try to read overrides from ConfigMap
    try:
        core_api = get_core_api()
        cm = core_api.read_namespaced_config_map(
            name="falcon-eye-config",
            namespace=settings.k8s_namespace
        )
        if cm.data:
            default_resolution = cm.data.get("DEFAULT_RESOLUTION", default_resolution)
            default_framerate = int(cm.data.get("DEFAULT_FRAMERATE", default_framerate))
            cleanup_interval = cm.data.get("CLEANUP_INTERVAL", cleanup_interval)
            creating_timeout = int(cm.data.get("CREATING_TIMEOUT_MINUTES", creating_timeout))
            # Chatbot tools from config
            if cm.data.get("CHATBOT_TOOLS"):
                enabled_tools = [t.strip() for t in cm.data.get("CHATBOT_TOOLS", "").split(",") if t.strip()]
            # Check if API key is in config
            if cm.data.get("ANTHROPIC_API_KEY"):
                api_key_configured = True
    except ApiException:
        pass  # ConfigMap doesn't exist, use defaults
    except ValueError:
        pass  # Invalid int conversion, use defaults
    
    # Build node_ips dict from individual settings
    node_ips = {
        "ace": settings.node_ip_ace,
        "falcon": settings.node_ip_falcon,
        "k3s-1": settings.node_ip_k3s1,
        "k3s-2": settings.node_ip_k3s2,
    }
    
    return SettingsResponse(
        default_resolution=default_resolution,
        default_framerate=default_framerate,
        k8s_namespace=settings.k8s_namespace,
        cleanup_interval=cleanup_interval,
        creating_timeout_minutes=creating_timeout,
        node_ips=node_ips,
        chatbot=ChatbotSettings(
            api_key_configured=api_key_configured,
            enabled_tools=enabled_tools,
            available_tools=list(AVAILABLE_TOOLS.keys()),
        ),
    )


@router.patch("/", response_model=SettingsResponse)
async def update_settings(update: SettingsUpdate):
    """Update settings via ConfigMap"""
    core_api = get_core_api()
    
    # Read or create ConfigMap
    config_data = {
        "DEFAULT_RESOLUTION": settings.default_resolution,
        "DEFAULT_FRAMERATE": str(settings.default_framerate),
        "CLEANUP_INTERVAL": "*/10 * * * *",
        "CREATING_TIMEOUT_MINUTES": "3",
    }
    
    try:
        cm = core_api.read_namespaced_config_map(
            name="falcon-eye-config",
            namespace=settings.k8s_namespace
        )
        if cm.data:
            config_data.update(cm.data)
    except ApiException as e:
        if e.status != 404:
            raise HTTPException(status_code=500, detail=f"K8s error: {e.reason}")
    
    # Apply updates
    if update.default_resolution:
        config_data["DEFAULT_RESOLUTION"] = update.default_resolution
    if update.default_framerate:
        config_data["DEFAULT_FRAMERATE"] = str(update.default_framerate)
    if update.cleanup_interval:
        config_data["CLEANUP_INTERVAL"] = update.cleanup_interval
    if update.creating_timeout_minutes:
        config_data["CREATING_TIMEOUT_MINUTES"] = str(update.creating_timeout_minutes)
    if update.chatbot_tools is not None:
        config_data["CHATBOT_TOOLS"] = ",".join(update.chatbot_tools)
    
    # Handle API key separately (store in Secret for security)
    api_key_updated = False
    if update.anthropic_api_key:
        # Validate API key before saving
        is_valid = await validate_anthropic_api_key(update.anthropic_api_key)
        if not is_valid:
            raise HTTPException(status_code=400, detail="Invalid Anthropic API key")
        await _update_api_key_secret(core_api, update.anthropic_api_key)
        api_key_updated = True
    
    # Create or update ConfigMap
    configmap = client.V1ConfigMap(
        metadata=client.V1ObjectMeta(
            name="falcon-eye-config",
            namespace=settings.k8s_namespace,
        ),
        data=config_data,
    )
    
    try:
        core_api.replace_namespaced_config_map(
            name="falcon-eye-config",
            namespace=settings.k8s_namespace,
            body=configmap,
        )
    except ApiException as e:
        if e.status == 404:
            core_api.create_namespaced_config_map(
                namespace=settings.k8s_namespace,
                body=configmap,
            )
        else:
            raise HTTPException(status_code=500, detail=f"K8s error: {e.reason}")
    
    logger.info(f"Settings updated: {config_data}")
    
    # Auto-restart API pod if API key was updated (to pick up new secret)
    if api_key_updated:
        try:
            import time as time_module
            apps_api = get_apps_api()
            patch = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "kubectl.kubernetes.io/restartedAt": time_module.strftime("%Y-%m-%dT%H:%M:%SZ")
                            }
                        }
                    }
                }
            }
            apps_api.patch_namespaced_deployment(
                name="falcon-eye-api",
                namespace=settings.k8s_namespace,
                body=patch,
            )
            logger.info("Restarted falcon-eye-api to pick up new API key")
        except Exception as e:
            logger.error(f"Failed to restart API pod: {e}")
            # Don't fail the request - settings were saved successfully
    
    return await get_current_settings()


def _do_restart_deployments(deployment_names: list[str], namespace: str):
    """Background task to restart deployments (runs after response is sent)"""
    import time as time_module
    apps_api = get_apps_api()
    
    patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/restartedAt": time_module.strftime("%Y-%m-%dT%H:%M:%SZ")
                    }
                }
            }
        }
    }
    
    for dep_name in deployment_names:
        try:
            apps_api.patch_namespaced_deployment(
                name=dep_name,
                namespace=namespace,
                body=patch,
            )
            logger.info(f"Restarted deployment: {dep_name}")
        except ApiException as e:
            logger.error(f"Failed to restart {dep_name}: {e}")


@router.post("/restart-all", response_model=RestartResponse)
async def restart_all_deployments(background_tasks: BackgroundTasks):
    """Restart all Falcon-Eye deployments to apply new settings"""
    apps_api = get_apps_api()
    
    to_restart = []
    
    try:
        # List all deployments in namespace and filter by name prefix
        deployments = apps_api.list_namespaced_deployment(
            namespace=settings.k8s_namespace
        )
        
        for dep in deployments.items:
            name = dep.metadata.name
            # Include falcon-eye-* deployments and camera deployments
            if name.startswith("falcon-eye") or name.startswith("cam-"):
                to_restart.append(name)
        
        # Also update CronJob if schedule changed
        cronjob_updated = False
        try:
            core_api = get_core_api()
            cm = core_api.read_namespaced_config_map(
                name="falcon-eye-config",
                namespace=settings.k8s_namespace
            )
            if cm.data and "CLEANUP_INTERVAL" in cm.data:
                batch_api = client.BatchV1Api()
                cron_patch = {
                    "spec": {
                        "schedule": cm.data["CLEANUP_INTERVAL"]
                    }
                }
                batch_api.patch_namespaced_cron_job(
                    name="falcon-eye-cleanup",
                    namespace=settings.k8s_namespace,
                    body=cron_patch,
                )
                cronjob_updated = True
                logger.info("Updated cleanup CronJob schedule")
        except ApiException:
            pass  # CronJob might not exist yet
        
        # Schedule restart in background (after response is sent)
        background_tasks.add_task(_do_restart_deployments, to_restart, settings.k8s_namespace)
        
        result = to_restart.copy()
        if cronjob_updated:
            result.append("falcon-eye-cleanup (cronjob)")
        
        return RestartResponse(
            message=f"Scheduled restart for {len(to_restart)} deployment(s)",
            restarted=result,
        )
        
    except ApiException as e:
        raise HTTPException(status_code=500, detail=f"K8s error: {e.reason}")


@router.delete("/cameras/all")
async def clear_all_cameras():
    """Delete all cameras from database and K8s"""
    from sqlalchemy import delete
    from app.database import get_db_session
    from app.models.camera import Camera
    from app.services import k8s as k8s_service
    
    deleted_count = 0
    
    try:
        # Get all cameras
        async with get_db_session() as db:
            from sqlalchemy import select
            result = await db.execute(select(Camera))
            cameras = result.scalars().all()
            
            # Delete K8s resources for each camera
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
            
            # Clear database
            await db.execute(delete(Camera))
            await db.commit()
        
        return {"message": f"Deleted {deleted_count} camera(s)", "count": deleted_count}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
