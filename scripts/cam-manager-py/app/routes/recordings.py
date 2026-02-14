"""Recordings API routes"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID
import os

from app.database import get_db
from app.models.recording import Recording, RecordingStatus

router = APIRouter(prefix="/api/recordings", tags=["recordings"])


class RecordingCreate(BaseModel):
    """Create recording request (from recorder service)"""
    id: str
    camera_id: str
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
    camera_id: str
    file_path: str
    file_name: str
    start_time: str
    end_time: Optional[str] = None
    duration_seconds: Optional[int] = None
    file_size_bytes: Optional[int] = None
    status: str
    error_message: Optional[str] = None
    
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


@router.get("/{recording_id}/download")
async def download_recording(
    recording_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Download a recording file"""
    result = await db.execute(
        select(Recording).where(Recording.id == recording_id)
    )
    recording = result.scalar_one_or_none()
    
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    
    if not recording.file_path or not os.path.exists(recording.file_path):
        raise HTTPException(status_code=404, detail="Recording file not found")
    
    return FileResponse(
        recording.file_path,
        media_type="video/mp4",
        filename=recording.file_name,
    )
