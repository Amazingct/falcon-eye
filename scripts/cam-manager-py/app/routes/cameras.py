"""Camera API routes"""
from uuid import UUID, uuid4
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.config import get_settings
from app.models.camera import Camera, CameraStatus
from app.models.schemas import (
    CameraCreate, CameraUpdate, CameraResponse, CameraListResponse,
    StreamInfo, MessageResponse, ErrorResponse, K8sStatus
)
from app.services import k8s

router = APIRouter(prefix="/api/cameras", tags=["cameras"])
settings = get_settings()


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
    
    # Enrich with K8s status
    enriched = []
    for cam in cameras:
        k8s_status = None
        if cam.deployment_name:
            try:
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
    db: AsyncSession = Depends(get_db),
):
    """Update camera metadata"""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Update fields
    update_data = camera_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(camera, field, value)
    
    await db.commit()
    await db.refresh(camera)
    
    return enrich_camera_response(camera)


@router.delete("/{camera_id}", response_model=MessageResponse)
async def delete_camera(
    camera_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a camera and its Kubernetes resources"""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Delete K8s resources
    if camera.deployment_name or camera.service_name:
        await k8s.delete_camera_deployment(
            camera.deployment_name or "",
            camera.service_name or "",
        )
    
    # Delete from database
    await db.execute(delete(Camera).where(Camera.id == camera_id))
    await db.commit()
    
    return MessageResponse(message="Camera deleted", id=camera_id)


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
