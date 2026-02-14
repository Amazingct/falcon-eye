"""Camera API routes"""
import asyncio
from uuid import UUID, uuid4
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.exc import IntegrityError

from app.database import get_db, get_db_session
from app.config import get_settings
from app.models.camera import Camera, CameraStatus
from app.models.schemas import (
    CameraCreate, CameraUpdate, CameraResponse, CameraListResponse,
    StreamInfo, MessageResponse, ErrorResponse, K8sStatus
)
from app.services import k8s

router = APIRouter(prefix="/api/cameras", tags=["cameras"])
settings = get_settings()

# Track cameras being deleted (device_path -> delete_time)
_deleting_cameras: dict[str, float] = {}


def enrich_camera_response(camera: Camera, k8s_status: Optional[dict] = None) -> dict:
    """Add computed fields to camera response"""
    data = camera.to_dict()
    
    # Build stream URLs
    if camera.stream_port and camera.node_name:
        node_ip = settings.get_node_ip(camera.node_name)
        data["stream_url"] = f"http://{node_ip}:{camera.stream_port}"
        if camera.control_port:
            data["control_url"] = f"http://{node_ip}:{camera.control_port}"
    
    # Add K8s status
    if k8s_status:
        data["k8s_status"] = K8sStatus(**k8s_status)
    
    return data


@router.get("/", response_model=CameraListResponse)
async def list_cameras(
    protocol: Optional[str] = Query(None, description="Filter by protocol"),
    status: Optional[str] = Query(None, description="Filter by status"),
    node: Optional[str] = Query(None, description="Filter by node"),
    db: AsyncSession = Depends(get_db),
):
    """List all cameras with optional filters"""
    query = select(Camera)
    
    if protocol:
        query = query.where(Camera.protocol == protocol)
    if status:
        query = query.where(Camera.status == status)
    if node:
        query = query.where(Camera.node_name == node)
    
    query = query.order_by(Camera.created_at.desc())
    
    result = await db.execute(query)
    cameras = result.scalars().all()
    
    # Enrich with K8s status and sync DB status
    enriched = []
    for cam in cameras:
        k8s_status = None
        
        # Skip status check for cameras being deleted
        if cam.status == CameraStatus.DELETING.value:
            enriched.append(enrich_camera_response(cam, k8s_status))
            continue
            
        if cam.deployment_name:
            try:
                # Get actual pod status from K8s
                actual_status = await k8s.get_camera_pod_status(str(cam.id))
                
                # Update DB if status changed
                if actual_status != cam.status:
                    cam.status = actual_status
                    await db.commit()
                
                k8s_status = await k8s.get_deployment_status(cam.deployment_name)
            except Exception:
                pass
        enriched.append(enrich_camera_response(cam, k8s_status))
    
    return CameraListResponse(cameras=enriched, total=len(enriched))


@router.get("/{camera_id}", response_model=CameraResponse)
async def get_camera(
    camera_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific camera by ID"""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    k8s_status = None
    if camera.deployment_name:
        try:
            k8s_status = await k8s.get_deployment_status(camera.deployment_name)
        except Exception:
            pass
    
    return enrich_camera_response(camera, k8s_status)


@router.post("/", response_model=CameraResponse, status_code=201)
async def create_camera(
    camera_data: CameraCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new camera and deploy to Kubernetes"""
    # Validate protocol-specific requirements
    if camera_data.protocol == "usb" and not camera_data.node_name:
        raise HTTPException(
            status_code=400,
            detail="node_name is required for USB cameras"
        )
    
    if camera_data.protocol in ["rtsp", "onvif", "http"] and not camera_data.source_url:
        raise HTTPException(
            status_code=400,
            detail="source_url is required for this protocol"
        )
    
    # Check if USB camera is being deleted
    if camera_data.protocol == "usb" and camera_data.device_path:
        device_key = f"{camera_data.node_name}:{camera_data.device_path}"
        if device_key in _deleting_cameras:
            raise HTTPException(
                status_code=409,
                detail="This camera is still being deleted. Please wait."
            )
        
        # Also check database for any camera with same device on same node with deleting status
        existing = await db.execute(
            select(Camera).where(
                Camera.node_name == camera_data.node_name,
                Camera.device_path == camera_data.device_path,
                Camera.status == CameraStatus.DELETING.value
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail="This camera is still being deleted. Please wait."
            )
    
    # Create camera record
    camera = Camera(
        id=uuid4(),
        name=camera_data.name,
        protocol=camera_data.protocol.value,
        location=camera_data.location,
        source_url=camera_data.source_url,
        device_path=camera_data.device_path,
        node_name=camera_data.node_name,
        resolution=camera_data.resolution or settings.default_resolution,
        framerate=camera_data.framerate or settings.default_framerate,
        metadata=camera_data.metadata or {},
        status=CameraStatus.CREATING.value,
    )
    
    db.add(camera)
    await db.flush()
    
    # Create K8s deployment
    try:
        k8s_result = await k8s.create_camera_deployment(camera)
        
        camera.deployment_name = k8s_result["deployment_name"]
        camera.service_name = k8s_result["service_name"]
        camera.stream_port = k8s_result["stream_port"]
        camera.control_port = k8s_result["control_port"]
        camera.status = CameraStatus.RUNNING.value
        
    except Exception as e:
        camera.status = CameraStatus.ERROR.value
        camera.metadata = {**camera.metadata, "error": str(e)}
    
    await db.commit()
    await db.refresh(camera)
    
    return enrich_camera_response(camera)


@router.patch("/{camera_id}", response_model=CameraResponse)
async def update_camera(
    camera_id: UUID,
    camera_data: CameraUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Update camera metadata. Redeploys if source_url changes."""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Check if source_url is changing (requires redeploy)
    update_data = camera_data.model_dump(exclude_unset=True)
    needs_redeploy = 'source_url' in update_data and update_data['source_url'] != camera.source_url
    
    # Update fields
    for field, value in update_data.items():
        setattr(camera, field, value)
    
    # If source_url changed, redeploy the camera
    if needs_redeploy and camera.deployment_name:
        camera.status = CameraStatus.CREATING.value
        await db.commit()
        
        # Delete old deployment and create new one
        try:
            await k8s.delete_camera_deployment(
                camera.deployment_name or "",
                camera.service_name or "",
            )
            await asyncio.sleep(2)  # Brief wait for cleanup
            
            k8s_result = await k8s.create_camera_deployment(camera)
            camera.deployment_name = k8s_result["deployment_name"]
            camera.service_name = k8s_result["service_name"]
            camera.stream_port = k8s_result["stream_port"]
            camera.control_port = k8s_result["control_port"]
            camera.status = CameraStatus.RUNNING.value
        except Exception as e:
            camera.status = CameraStatus.ERROR.value
            camera.metadata = {**camera.metadata, "error": str(e)}
    
    await db.commit()
    await db.refresh(camera)
    
    return enrich_camera_response(camera)


async def _background_delete_camera(
    camera_id: UUID,
    deployment_name: str,
    service_name: str,
    device_key: str,
    is_usb: bool,
):
    """Background task to delete camera with grace period"""
    import time
    
    try:
        # Delete K8s resources
        if deployment_name or service_name:
            await k8s.delete_camera_deployment(deployment_name, service_name)
        
        # Wait for pod to fully terminate
        await asyncio.sleep(5)
        
        # Extra grace period for USB cameras to release device
        if is_usb:
            await asyncio.sleep(15)
        
        # Delete from database
        async with get_db_session() as db:
            await db.execute(delete(Camera).where(Camera.id == camera_id))
            await db.commit()
        
    finally:
        # Remove from deleting tracker
        if device_key and device_key in _deleting_cameras:
            del _deleting_cameras[device_key]


@router.delete("/{camera_id}", response_model=MessageResponse)
async def delete_camera(
    camera_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Delete a camera and its Kubernetes resources"""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    if camera.status == CameraStatus.DELETING.value:
        raise HTTPException(status_code=400, detail="Camera is already being deleted")
    
    # Mark as deleting
    camera.status = CameraStatus.DELETING.value
    await db.commit()
    
    # Track USB device deletion
    device_key = ""
    is_usb = camera.protocol == "usb"
    if is_usb and camera.device_path and camera.node_name:
        device_key = f"{camera.node_name}:{camera.device_path}"
        _deleting_cameras[device_key] = asyncio.get_event_loop().time()
    
    # Start background deletion
    background_tasks.add_task(
        _background_delete_camera,
        camera_id,
        camera.deployment_name or "",
        camera.service_name or "",
        device_key,
        is_usb,
    )
    
    return MessageResponse(message="Camera deletion started", id=camera_id)


@router.post("/{camera_id}/restart", response_model=MessageResponse)
async def restart_camera(
    camera_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Restart a camera by recreating its Kubernetes deployment"""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Delete existing deployment
    if camera.deployment_name or camera.service_name:
        await k8s.delete_camera_deployment(
            camera.deployment_name or "",
            camera.service_name or "",
        )
    
    # Recreate deployment
    try:
        k8s_result = await k8s.create_camera_deployment(camera)
        
        camera.deployment_name = k8s_result["deployment_name"]
        camera.service_name = k8s_result["service_name"]
        camera.stream_port = k8s_result["stream_port"]
        camera.control_port = k8s_result["control_port"]
        camera.status = CameraStatus.RUNNING.value
        
        await db.commit()
        
        return MessageResponse(
            message="Camera restarted",
            deployment_name=k8s_result["deployment_name"],
            service_name=k8s_result["service_name"],
            stream_port=k8s_result["stream_port"],
        )
        
    except Exception as e:
        camera.status = CameraStatus.ERROR.value
        await db.commit()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{camera_id}/stream-info", response_model=StreamInfo)
async def get_stream_info(
    camera_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get stream URLs for a camera"""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    stream_url = None
    control_url = None
    
    if camera.stream_port and camera.node_name:
        node_ip = settings.get_node_ip(camera.node_name)
        stream_url = f"http://{node_ip}:{camera.stream_port}"
        if camera.control_port:
            control_url = f"http://{node_ip}:{camera.control_port}"
    
    return StreamInfo(
        id=camera.id,
        name=camera.name,
        stream_url=stream_url,
        control_url=control_url,
        protocol=camera.protocol,
        status=camera.status,
    )
