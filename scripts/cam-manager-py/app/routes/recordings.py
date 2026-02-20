"""Recordings API routes"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID
import os
import httpx

from app.database import get_db
from app.config import get_settings
from app.models.recording import Recording, RecordingStatus

router = APIRouter(prefix="/api/recordings", tags=["recordings"])


class RecordingCreate(BaseModel):
    """Create recording request (from recorder service)"""
    id: str
    camera_id: str
    camera_name: Optional[str] = None  # Preserved for when camera is deleted
    file_path: str
    file_name: str
    start_time: str
    status: str = "recording"


class RecordingUpdate(BaseModel):
    """Update recording request"""
    end_time: Optional[str] = None
    status: Optional[str] = None
    file_size_bytes: Optional[int] = None
    error_message: Optional[str] = None


class RecordingResponse(BaseModel):
    """Recording response"""
    id: str
    camera_id: Optional[str] = None  # Null if camera was deleted
    camera_name: Optional[str] = None  # Preserved camera name
    file_path: str
    file_name: str
    start_time: str
    end_time: Optional[str] = None
    duration_seconds: Optional[int] = None
    file_size_bytes: Optional[int] = None
    status: str
    error_message: Optional[str] = None
    camera_deleted: bool = False  # True if associated camera was deleted
    
    class Config:
        from_attributes = True


@router.get("/")
async def list_recordings(
    camera_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List recordings with optional filters"""
    query = select(Recording).order_by(Recording.start_time.desc())
    
    if camera_id:
        try:
            camera_uuid = UUID(camera_id)
            query = query.where(Recording.camera_id == camera_uuid)
        except ValueError:
            pass  # Invalid UUID, skip filter
    if status:
        query = query.where(Recording.status == status)
    
    query = query.limit(limit).offset(offset)
    
    result = await db.execute(query)
    recordings = result.scalars().all()
    
    return {
        "recordings": [r.to_dict() for r in recordings],
        "count": len(recordings),
    }


@router.get("/{recording_id}")
async def get_recording(
    recording_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific recording"""
    result = await db.execute(
        select(Recording).where(Recording.id == recording_id)
    )
    recording = result.scalar_one_or_none()
    
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    
    return recording.to_dict()


@router.post("/")
async def create_recording(
    data: RecordingCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new recording (called by recorder service)"""
    try:
        camera_uuid = UUID(data.camera_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid camera_id format")
    
    recording = Recording(
        id=data.id,
        camera_id=camera_uuid,
        camera_name=data.camera_name,  # Preserve camera name for when camera is deleted
        file_path=data.file_path,
        file_name=data.file_name,
        start_time=datetime.fromisoformat(data.start_time),
        status=RecordingStatus(data.status),
    )
    
    db.add(recording)
    await db.commit()
    await db.refresh(recording)
    
    return recording.to_dict()


@router.patch("/{recording_id}")
async def update_recording(
    recording_id: str,
    data: RecordingUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a recording (called by recorder service)"""
    result = await db.execute(
        select(Recording).where(Recording.id == recording_id)
    )
    recording = result.scalar_one_or_none()
    
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    
    update_data = {}
    
    if data.end_time:
        end_time = datetime.fromisoformat(data.end_time)
        update_data["end_time"] = end_time
        # Calculate duration
        if recording.start_time:
            update_data["duration_seconds"] = int((end_time - recording.start_time).total_seconds())
    
    if data.status:
        update_data["status"] = RecordingStatus(data.status)
    
    if data.file_size_bytes is not None:
        update_data["file_size_bytes"] = data.file_size_bytes
    
    if data.error_message:
        update_data["error_message"] = data.error_message
    
    if update_data:
        await db.execute(
            update(Recording)
            .where(Recording.id == recording_id)
            .values(**update_data)
        )
        await db.commit()
    
    # Refresh and return
    result = await db.execute(
        select(Recording).where(Recording.id == recording_id)
    )
    recording = result.scalar_one()
    
    return recording.to_dict()


@router.delete("/{recording_id}")
async def delete_recording(
    recording_id: str,
    delete_file: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Delete a recording"""
    result = await db.execute(
        select(Recording).where(Recording.id == recording_id)
    )
    recording = result.scalar_one_or_none()
    
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    
    # Delete the file if requested
    if delete_file and recording.file_path and os.path.exists(recording.file_path):
        try:
            os.remove(recording.file_path)
        except Exception as e:
            print(f"Failed to delete recording file: {e}")
    
    await db.execute(
        delete(Recording).where(Recording.id == recording_id)
    )
    await db.commit()
    
    return {"message": "Recording deleted", "id": recording_id}


async def _find_file_via_recorders(camera_id: str, file_name: str) -> Optional[str]:
    """Search all recorder pods for a recording file. Returns the URL if found."""
    settings = get_settings()
    try:
        from app.services.k8s import core_api
        services = core_api.list_namespaced_service(
            namespace=settings.k8s_namespace,
            label_selector="component=recorder",
        )
        for svc in services.items:
            svc_url = f"http://{svc.metadata.name}.{settings.k8s_namespace}.svc.cluster.local:8080"
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    res = await client.head(f"{svc_url}/files/{camera_id}/{file_name}")
                    if res.status_code == 200:
                        return f"{svc_url}/files/{camera_id}/{file_name}"
            except Exception:
                continue
    except Exception as e:
        print(f"Error searching recorder pods: {e}")
    return None


@router.get("/{recording_id}/download")
async def download_recording(
    recording_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Download a recording file.
    
    Strategy:
    1. Try serving from local volume (works when API and recorder share a node)
    2. Proxy through the recorder pod that has the file (multi-node)
    """
    result = await db.execute(
        select(Recording).where(Recording.id == recording_id)
    )
    recording = result.scalar_one_or_none()
    
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    
    if not recording.file_path:
        raise HTTPException(status_code=404, detail="No file path for this recording")
    
    # 1. Try local file first (same node or shared storage)
    if os.path.exists(recording.file_path):
        return FileResponse(
            recording.file_path,
            media_type="video/mp4",
            filename=recording.file_name,
        )
    
    # 2. File not on this node — proxy through a recorder pod that has it
    camera_id = str(recording.camera_id) if recording.camera_id else None
    if not camera_id or not recording.file_name:
        raise HTTPException(
            status_code=404,
            detail="Recording file not found on this node and cannot locate it remotely"
        )
    
    remote_url = await _find_file_via_recorders(camera_id, recording.file_name)
    if not remote_url:
        raise HTTPException(
            status_code=404,
            detail="Recording file not found on any node. The recorder pod may have been restarted."
        )
    
    # Stream the file from the recorder pod back to the client
    async def stream_from_recorder():
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream("GET", remote_url) as response:
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    yield chunk

    return StreamingResponse(
        stream_from_recorder(),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'attachment; filename="{recording.file_name}"',
        },
    )
