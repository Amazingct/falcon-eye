"""Settings API routes"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from kubernetes import client
from kubernetes.client.rest import ApiException
import logging

from app.config import get_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])
logger = logging.getLogger(__name__)
settings = get_settings()


class SettingsResponse(BaseModel):
    """Current settings"""
    default_resolution: str
    default_framerate: int
    k8s_namespace: str
    cleanup_interval: str
    creating_timeout_minutes: int
    node_ips: dict[str, str]


class SettingsUpdate(BaseModel):
    """Settings update request"""
    default_resolution: Optional[str] = None
    default_framerate: Optional[int] = None
    cleanup_interval: Optional[str] = None
    creating_timeout_minutes: Optional[int] = None


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


@router.get("/", response_model=SettingsResponse)
async def get_current_settings():
    """Get current settings"""
    # Try to read from ConfigMap
    cleanup_interval = "*/10 * * * *"
    creating_timeout = 3
    
    try:
        core_api = get_core_api()
        cm = core_api.read_namespaced_config_map(
            name="falcon-eye-config",
            namespace=settings.k8s_namespace
        )
        if cm.data:
            cleanup_interval = cm.data.get("CLEANUP_INTERVAL", cleanup_interval)
            creating_timeout = int(cm.data.get("CREATING_TIMEOUT_MINUTES", creating_timeout))
    except ApiException:
        pass  # ConfigMap doesn't exist, use defaults
    
    return SettingsResponse(
        default_resolution=settings.default_resolution,
        default_framerate=settings.default_framerate,
        k8s_namespace=settings.k8s_namespace,
        cleanup_interval=cleanup_interval,
        creating_timeout_minutes=creating_timeout,
        node_ips=settings.node_ips,
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
    
    return await get_current_settings()


@router.post("/restart-all", response_model=RestartResponse)
async def restart_all_deployments():
    """Restart all Falcon-Eye deployments to apply new settings"""
    import time
    apps_api = get_apps_api()
    
    restarted = []
    
    try:
        # List all Falcon-Eye deployments
        deployments = apps_api.list_namespaced_deployment(
            namespace=settings.k8s_namespace,
            label_selector="app=falcon-eye"
        )
        
        # Restart each deployment by patching restart annotation
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ")
                        }
                    }
                }
            }
        }
        
        for dep in deployments.items:
            try:
                apps_api.patch_namespaced_deployment(
                    name=dep.metadata.name,
                    namespace=settings.k8s_namespace,
                    body=patch,
                )
                restarted.append(dep.metadata.name)
                logger.info(f"Restarted deployment: {dep.metadata.name}")
            except ApiException as e:
                logger.error(f"Failed to restart {dep.metadata.name}: {e}")
        
        # Also update CronJob if schedule changed
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
                restarted.append("falcon-eye-cleanup (cronjob)")
                logger.info("Updated cleanup CronJob schedule")
        except ApiException:
            pass  # CronJob might not exist yet
        
        return RestartResponse(
            message=f"Restarted {len(restarted)} deployment(s)",
            restarted=restarted,
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
