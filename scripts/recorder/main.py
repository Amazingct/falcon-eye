"""
Falcon-Eye Recorder Service
Records video from camera streams using FFmpeg
"""
import os
import asyncio
import subprocess
import signal
from datetime import datetime
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx

app = FastAPI(title="Falcon-Eye Recorder")

# Configuration from environment
CAMERA_ID = os.getenv("CAMERA_ID", "unknown")
CAMERA_NAME = os.getenv("CAMERA_NAME", "camera")
STREAM_URL = os.getenv("STREAM_URL", "")  # HLS or RTSP URL to record from
RECORDINGS_PATH = os.getenv("RECORDINGS_PATH", "/recordings")
API_URL = os.getenv("API_URL", "http://falcon-eye-api:3000")  # Main API to report recordings
SEGMENT_DURATION = int(os.getenv("SEGMENT_DURATION", "3600"))  # Max segment duration in seconds (1 hour)

# Recording state
current_process: Optional[subprocess.Popen] = None
current_recording: Optional[dict] = None
recording_lock = asyncio.Lock()


class RecordingInfo(BaseModel):
    """Recording information"""
    recording_id: Optional[str] = None
    camera_id: str
    camera_name: str
    file_path: Optional[str] = None
    file_name: Optional[str] = None
    start_time: Optional[str] = None
    status: str  # recording, stopped, idle
    

class StartResponse(BaseModel):
    """Start recording response"""
    success: bool
    message: str
    recording: Optional[RecordingInfo] = None


class StopResponse(BaseModel):
    """Stop recording response"""
    success: bool
    message: str
    recording: Optional[RecordingInfo] = None


def generate_filename() -> tuple[str, str]:
    """Generate recording filename with timestamp"""
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_name = CAMERA_NAME.replace(" ", "_").replace("/", "-")[:30]
    filename = f"{safe_name}_{timestamp}.mp4"
    filepath = os.path.join(RECORDINGS_PATH, CAMERA_ID, filename)
    return filepath, filename


async def notify_api_start(recording_id: str, file_path: str, file_name: str, start_time: datetime):
    """Notify main API that recording started"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{API_URL}/api/recordings/", json={
                "id": recording_id,
                "camera_id": CAMERA_ID,
                "file_path": file_path,
                "file_name": file_name,
                "start_time": start_time.isoformat(),
                "status": "recording",
            })
    except Exception as e:
        print(f"Failed to notify API of recording start: {e}")


async def notify_api_stop(recording_id: str, end_time: datetime, file_size: int):
    """Notify main API that recording stopped"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.patch(f"{API_URL}/api/recordings/{recording_id}", json={
                "end_time": end_time.isoformat(),
                "status": "completed",
                "file_size_bytes": file_size,
            })
    except Exception as e:
        print(f"Failed to notify API of recording stop: {e}")


@app.get("/health")
async def health():
    """Health check"""
    return {"status": "ok", "camera_id": CAMERA_ID}


@app.get("/status")
async def get_status() -> RecordingInfo:
    """Get current recording status"""
    if current_recording:
        return RecordingInfo(
            recording_id=current_recording.get("id"),
            camera_id=CAMERA_ID,
            camera_name=CAMERA_NAME,
            file_path=current_recording.get("file_path"),
            file_name=current_recording.get("file_name"),
            start_time=current_recording.get("start_time"),
            status="recording" if current_process and current_process.poll() is None else "stopped",
        )
    return RecordingInfo(
        camera_id=CAMERA_ID,
        camera_name=CAMERA_NAME,
        status="idle",
    )


@app.post("/start")
async def start_recording() -> StartResponse:
    """Start recording"""
    global current_process, current_recording
    
    async with recording_lock:
        # Check if already recording
        if current_process and current_process.poll() is None:
            return StartResponse(
                success=False,
                message="Already recording",
                recording=await get_status(),
            )
        
        if not STREAM_URL:
            raise HTTPException(status_code=400, detail="No stream URL configured")
        
        # Create recordings directory
        recording_dir = os.path.join(RECORDINGS_PATH, CAMERA_ID)
        Path(recording_dir).mkdir(parents=True, exist_ok=True)
        
        # Generate filename
        file_path, file_name = generate_filename()
        start_time = datetime.utcnow()
        recording_id = f"{CAMERA_ID}_{start_time.strftime('%Y%m%d%H%M%S')}"
        
        # FFmpeg command to record from stream
        # -i: input stream
        # -c copy: copy codecs (no re-encoding, fast)
        # -t: max duration
        # -movflags +faststart: optimize for web playback
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-i", STREAM_URL,
            "-c", "copy",  # No re-encoding
            "-t", str(SEGMENT_DURATION),  # Max duration
            "-movflags", "+faststart",  # Web-optimized
            "-f", "mp4",
            file_path,
        ]
        
        try:
            # Start FFmpeg process
            current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            
            current_recording = {
                "id": recording_id,
                "file_path": file_path,
                "file_name": file_name,
                "start_time": start_time.isoformat(),
            }
            
            # Notify API (non-blocking)
            asyncio.create_task(notify_api_start(recording_id, file_path, file_name, start_time))
            
            return StartResponse(
                success=True,
                message="Recording started",
                recording=await get_status(),
            )
            
        except Exception as e:
            current_process = None
            current_recording = None
            raise HTTPException(status_code=500, detail=f"Failed to start recording: {e}")


@app.post("/stop")
async def stop_recording() -> StopResponse:
    """Stop recording"""
    global current_process, current_recording
    
    async with recording_lock:
        if not current_process:
            return StopResponse(
                success=False,
                message="Not recording",
            )
        
        recording_info = current_recording.copy() if current_recording else {}
        
        try:
            # Send SIGINT to FFmpeg for graceful shutdown
            current_process.send_signal(signal.SIGINT)
            
            # Wait for process to finish (max 10 seconds)
            try:
                current_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                current_process.kill()
                current_process.wait()
            
            end_time = datetime.utcnow()
            
            # Get file size
            file_size = 0
            if recording_info.get("file_path") and os.path.exists(recording_info["file_path"]):
                file_size = os.path.getsize(recording_info["file_path"])
            
            # Notify API
            if recording_info.get("id"):
                asyncio.create_task(notify_api_stop(recording_info["id"], end_time, file_size))
            
            current_process = None
            current_recording = None
            
            return StopResponse(
                success=True,
                message="Recording stopped",
                recording=RecordingInfo(
                    recording_id=recording_info.get("id"),
                    camera_id=CAMERA_ID,
                    camera_name=CAMERA_NAME,
                    file_path=recording_info.get("file_path"),
                    file_name=recording_info.get("file_name"),
                    start_time=recording_info.get("start_time"),
                    status="stopped",
                ),
            )
            
        except Exception as e:
            current_process = None
            current_recording = None
            raise HTTPException(status_code=500, detail=f"Failed to stop recording: {e}")


@app.on_event("shutdown")
async def shutdown():
    """Clean up on shutdown"""
    if current_process and current_process.poll() is None:
        await stop_recording()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
