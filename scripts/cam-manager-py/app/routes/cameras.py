"""Camera API routes"""
import asyncio
from datetime import datetime, timedelta, timezone
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

# Timeout for stuck "creating" cameras (3 minutes)
CREATING_TIMEOUT_MINUTES = 3


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
    now = datetime.now(timezone.utc)
    
    for cam in cameras:
        k8s_status = None
        
        # Skip status check for cameras being deleted
        if cam.status == CameraStatus.DELETING.value:
            enriched.append(enrich_camera_response(cam, k8s_status))
            continue
        
        # Check for stuck "creating" cameras (timeout after 3 minutes)
        if cam.status == CameraStatus.CREATING.value:
            created_at = cam.updated_at or cam.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if now - created_at > timedelta(minutes=CREATING_TIMEOUT_MINUTES):
                # Auto-stop stuck camera
                try:
                    if cam.deployment_name or cam.service_name:
                        await k8s.delete_camera_deployment(
                            cam.deployment_name or "",
                            cam.service_name or "",
                        )
                    cam.status = CameraStatus.ERROR.value
                    cam.metadata = {**cam.metadata, "error": "Timed out while creating (3 min)"}
                    cam.deployment_name = None
                    cam.service_name = None
                    await db.commit()
                except Exception:
                    pass
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


def _extract_ip_from_url(url: str) -> str:
    """Extract IP address from a URL (rtsp://user:pass@192.168.1.1:554/...)"""
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if hostname:
            return hostname
    except:
        pass
    # Fallback: try to find IP pattern in URL
    import re
    match = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', url)
    if match:
        return match.group(1)
    return url


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
    
    # For network cameras, extract IP early for duplicate check
    check_device_path = camera_data.device_path
    if camera_data.protocol.value in ["rtsp", "onvif", "http"] and camera_data.source_url:
        check_device_path = _extract_ip_from_url(camera_data.source_url)
    
    # Check for duplicate IP/device_path (prevent adding same camera twice)
    if check_device_path:
        existing_camera = await db.execute(
            select(Camera).where(
                Camera.device_path == check_device_path,
                Camera.status != CameraStatus.DELETING.value
            )
        )
        if existing_camera.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"A camera with this {'IP address' if camera_data.protocol.value != 'usb' else 'device path'} already exists"
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
    
    # Network cameras (rtsp, onvif, http) start in stopped state
    # User must edit with credentials then start manually
    is_network_camera = camera_data.protocol.value in ["rtsp", "onvif", "http"]
    
    # For network cameras, set device_path to IP address extracted from source_url
    device_path = camera_data.device_path
    if is_network_camera and camera_data.source_url:
        device_path = _extract_ip_from_url(camera_data.source_url)
    
    # Create camera record
    camera = Camera(
        id=uuid4(),
        name=camera_data.name,
        protocol=camera_data.protocol.value,
        location=camera_data.location,
        source_url=camera_data.source_url,
        device_path=device_path,
        node_name=camera_data.node_name or ("LAN" if is_network_camera else None),
        resolution=camera_data.resolution or settings.default_resolution,
        framerate=camera_data.framerate or settings.default_framerate,
        metadata=camera_data.metadata or {},
        status=CameraStatus.STOPPED.value if is_network_camera else CameraStatus.CREATING.value,
    )
    
    db.add(camera)
    await db.flush()
    
    # Only create K8s deployment for USB cameras immediately
    # Network cameras wait for user to edit and start manually
    if not is_network_camera:
        try:
            k8s_result = await k8s.create_camera_deployment(camera)
            
            camera.deployment_name = k8s_result["deployment_name"]
            camera.service_name = k8s_result["service_name"]
            camera.stream_port = k8s_result["stream_port"]
            camera.control_port = k8s_result["control_port"]
            camera.status = CameraStatus.RUNNING.value
            
            # Also create recorder deployment
            if camera.stream_port:
                node_ip = settings.get_node_ip(camera.node_name)
                try:
                    await k8s.create_recorder_deployment(camera, camera.stream_port, node_ip)
                except Exception as e:
                    # Recorder failure is non-fatal, camera still works
                    print(f"Failed to create recorder: {e}")
            
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
    
    # If source_url changes for network camera, also update device_path with new IP
    if 'source_url' in update_data and camera.protocol in ["rtsp", "onvif", "http"]:
        update_data['device_path'] = _extract_ip_from_url(update_data['source_url'])
    
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
        
        # Delete recorder deployment
        try:
            await k8s.delete_recorder_deployment(str(camera_id))
        except Exception as e:
            print(f"Failed to delete recorder: {e}")
        
        # Wait for pod to fully terminate
        await asyncio.sleep(5)
        
        # Extra grace period for USB cameras to release device
        if is_usb:
            await asyncio.sleep(15)
        
        # Delete from database (cascades to recordings)
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
    
    # Delete existing recorder too
    try:
        await k8s.delete_recorder_deployment(str(camera_id))
    except Exception:
        pass
    
    # Recreate deployment
    try:
        k8s_result = await k8s.create_camera_deployment(camera)
        
        camera.deployment_name = k8s_result["deployment_name"]
        camera.service_name = k8s_result["service_name"]
        camera.stream_port = k8s_result["stream_port"]
        camera.control_port = k8s_result["control_port"]
        camera.status = CameraStatus.RUNNING.value
        
        await db.commit()
        
        # Also create recorder deployment
        if camera.stream_port:
            try:
                await k8s.create_recorder_deployment(camera, camera.stream_port)
            except Exception as e:
                print(f"Failed to create recorder: {e}")
        
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


@router.post("/{camera_id}/start", response_model=MessageResponse)
async def start_camera(
    camera_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Start a stopped camera"""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    if camera.status == CameraStatus.RUNNING.value:
        return MessageResponse(message="Camera already running", id=camera_id)
    
    # Create deployment if it doesn't exist
    try:
        camera.status = CameraStatus.CREATING.value
        await db.commit()
        
        k8s_result = await k8s.create_camera_deployment(camera)
        
        camera.deployment_name = k8s_result["deployment_name"]
        camera.service_name = k8s_result["service_name"]
        camera.stream_port = k8s_result["stream_port"]
        camera.control_port = k8s_result["control_port"]
        camera.status = CameraStatus.RUNNING.value
        
        await db.commit()
        
        # Also create recorder deployment
        if camera.stream_port:
            node_ip = settings.get_node_ip(camera.node_name)
            try:
                await k8s.create_recorder_deployment(camera, camera.stream_port, node_ip)
            except Exception as e:
                print(f"Failed to create recorder: {e}")
        
        return MessageResponse(message="Camera started", id=camera_id)
        
    except Exception as e:
        camera.status = CameraStatus.ERROR.value
        await db.commit()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{camera_id}/stop", response_model=MessageResponse)
async def stop_camera(
    camera_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Stop a running camera"""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    if camera.status == CameraStatus.STOPPED.value:
        return MessageResponse(message="Camera already stopped", id=camera_id)
    
    # Delete K8s resources
    if camera.deployment_name or camera.service_name:
        await k8s.delete_camera_deployment(
            camera.deployment_name or "",
            camera.service_name or "",
        )
    
    # Also delete recorder
    try:
        await k8s.delete_recorder_deployment(str(camera.id))
    except Exception as e:
        print(f"Failed to delete recorder: {e}")
    
    camera.status = CameraStatus.STOPPED.value
    camera.deployment_name = None
    camera.service_name = None
    await db.commit()
    
    return MessageResponse(message="Camera stopped", id=camera_id)


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


# Recording control endpoints
import httpx


async def _get_recorder_url(camera_id: str) -> str:
    """Get the recorder service URL for a camera"""
    # Recorder service is internal ClusterIP
    # Service name pattern: svc-rec-{name_slug}
    # But we can use label selector to find it
    try:
        services = k8s.core_api.list_namespaced_service(
            namespace=settings.k8s_namespace,
            label_selector=f"component=recorder,recorder-for={camera_id}",
        )
        if services.items:
            svc = services.items[0]
            return f"http://{svc.metadata.name}.{settings.k8s_namespace}.svc.cluster.local:8080"
    except Exception as e:
        print(f"Failed to find recorder service: {e}")
    return None


@router.get("/{camera_id}/recording/status")
async def get_recording_status(
    camera_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get recording status for a camera"""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    recorder_url = await _get_recorder_url(str(camera_id))
    if not recorder_url:
        return {"recording": False, "status": "no_recorder", "message": "Recorder not deployed"}
    
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            res = await client.get(f"{recorder_url}/status")
            if res.status_code == 200:
                return res.json()
            return {"recording": False, "status": "error", "message": f"Recorder returned {res.status_code}"}
    except Exception as e:
        return {"recording": False, "status": "error", "message": str(e)}


@router.post("/{camera_id}/recording/start")
async def start_recording(
    camera_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Start recording for a camera. Auto-deploys recorder if not present."""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    if camera.status != CameraStatus.RUNNING.value:
        raise HTTPException(status_code=400, detail="Camera is not running")
    
    recorder_url = await _get_recorder_url(str(camera_id))
    
    # Auto-deploy recorder if not present
    if not recorder_url:
        if not camera.stream_port:
            raise HTTPException(status_code=400, detail="Camera has no stream port")
        
        try:
            await k8s.create_recorder_deployment(camera, camera.stream_port)
            # Wait for recorder to be ready
            import asyncio
            for _ in range(30):  # Wait up to 30 seconds
                await asyncio.sleep(1)
                recorder_url = await _get_recorder_url(str(camera_id))
                if recorder_url:
                    break
            
            if not recorder_url:
                raise HTTPException(status_code=500, detail="Recorder deployed but not ready yet, try again")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to deploy recorder: {e}")
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(f"{recorder_url}/start")
            if res.status_code == 200:
                return res.json()
            raise HTTPException(status_code=res.status_code, detail=res.text)
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Failed to contact recorder: {e}")


@router.post("/{camera_id}/recording/stop")
async def stop_recording(
    camera_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Stop recording for a camera"""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    recorder_url = await _get_recorder_url(str(camera_id))
    if not recorder_url:
        raise HTTPException(status_code=400, detail="Recorder not deployed")
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(f"{recorder_url}/stop")
            if res.status_code == 200:
                return res.json()
            raise HTTPException(status_code=res.status_code, detail=res.text)
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Failed to contact recorder: {e}")
