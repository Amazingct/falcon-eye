"""
Falcon-Eye Recorder Service
Records video from camera streams using FFmpeg
"""
import os
import asyncio
import subprocess
import signal
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("falcon-eye-recorder")

app = FastAPI(title="Falcon-Eye Recorder")

# Configuration from environment
CAMERA_ID = os.getenv("CAMERA_ID", "unknown")
CAMERA_NAME = os.getenv("CAMERA_NAME", "camera")
STREAM_URL = os.getenv("STREAM_URL", "")
RECORDINGS_PATH = os.getenv("RECORDINGS_PATH", "/recordings")
API_URL = os.getenv("API_URL", "http://falcon-eye-api:8000")
SEGMENT_DURATION = int(os.getenv("SEGMENT_DURATION", "3600"))
NODE_NAME = os.getenv("NODE_NAME", "")

# Recording state
current_process: Optional[subprocess.Popen] = None
current_recording: Optional[dict] = None
_monitor_task: Optional[asyncio.Task] = None
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
            payload = {
                "id": recording_id,
                "camera_id": CAMERA_ID,
                "camera_name": CAMERA_NAME,
                "file_path": file_path,
                "file_name": file_name,
                "start_time": start_time.isoformat(),
                "status": "recording",
            }
            if NODE_NAME:
                payload["node_name"] = NODE_NAME
            await client.post(f"{API_URL}/api/recordings/", json=payload)
    except Exception as e:
        logger.warning("Failed to notify API of recording start: %s", e)


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
        logger.warning("Failed to notify API of recording stop: %s", e)


async def notify_api_failed(recording_id: str, error_message: str):
    """Notify main API that recording failed"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.patch(f"{API_URL}/api/recordings/{recording_id}", json={
                "end_time": datetime.utcnow().isoformat(),
                "status": "failed",
                "error_message": error_message,
            })
    except Exception as e:
        logger.warning("Failed to notify API of recording failure: %s", e)


async def monitor_ffmpeg_process(recording_id: str, log_path: str):
    """Continuously monitor the FFmpeg process. Reports crashes to the API."""
    global current_process, current_recording

    await asyncio.sleep(3)

    try:
        while current_process is not None:
            exit_code = current_process.poll()
            if exit_code is not None:
                # Close log file handle if still open
                if current_recording:
                    log_fh = current_recording.get("log_fh")
                    if log_fh:
                        try:
                            log_fh.close()
                        except Exception:
                            pass

                stderr_tail = ""
                try:
                    with open(log_path, "r") as f:
                        stderr_tail = f.read()[-1000:]
                except Exception:
                    stderr_tail = "(could not read ffmpeg log)"

                if exit_code == 0:
                    logger.info("FFmpeg finished normally for recording %s", recording_id)
                else:
                    logger.error("FFmpeg crashed (code %d) for %s: %s", exit_code, recording_id, stderr_tail)
                    await notify_api_failed(recording_id, f"FFmpeg exited with code {exit_code}: {stderr_tail}")

                current_process = None
                current_recording = None
                return

            await asyncio.sleep(5)
    except asyncio.CancelledError:
        logger.info("Monitor cancelled for %s", recording_id)
        return

    logger.info("Monitor exiting — no active process for %s", recording_id)


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
    global current_process, current_recording, _monitor_task

    async with recording_lock:
        if current_process and current_process.poll() is None:
            return StartResponse(
                success=False,
                message="Already recording",
                recording=await get_status(),
            )

        if not STREAM_URL:
            raise HTTPException(status_code=400, detail="No stream URL configured")

        recording_dir = os.path.join(RECORDINGS_PATH, CAMERA_ID)
        Path(recording_dir).mkdir(parents=True, exist_ok=True)

        file_path, file_name = generate_filename()
        start_time = datetime.utcnow()
        recording_id = f"{CAMERA_ID}_{start_time.strftime('%Y%m%d%H%M%S')}"

        # FFmpeg stderr log — written to a file to avoid pipe buffer deadlock
        log_path = file_path + ".log"

        is_http = STREAM_URL.startswith("http://") or STREAM_URL.startswith("https://")
        is_mjpeg = STREAM_URL.endswith("/") or "mjpeg" in STREAM_URL.lower() or "mjpg" in STREAM_URL.lower()

        # Use frag_keyframe+empty_moov so the file is playable even if
        # ffmpeg is killed mid-recording (moov atom is at the start).
        frag_movflags = "frag_keyframe+empty_moov+default_base_moof"

        if is_mjpeg:
            cmd = [
                "ffmpeg", "-y",
                "-f", "mjpeg",
                "-i", STREAM_URL,
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "23",
                "-t", str(SEGMENT_DURATION),
                "-movflags", frag_movflags,
                "-f", "mp4",
                file_path,
            ]
        elif is_http:
            cmd = [
                "ffmpeg", "-y",
                "-i", STREAM_URL,
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "23",
                "-c:a", "aac", "-b:a", "64k",
                "-t", str(SEGMENT_DURATION),
                "-movflags", frag_movflags,
                "-f", "mp4",
                file_path,
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-rtsp_transport", "tcp",
                "-i", STREAM_URL,
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "64k",
                "-t", str(SEGMENT_DURATION),
                "-movflags", frag_movflags,
                "-f", "mp4",
                file_path,
            ]

        try:
            logger.info("Starting FFmpeg: %s", " ".join(cmd))

            # CRITICAL: redirect stderr to a log file instead of PIPE.
            # Piped stderr fills the OS buffer (~64KB), which blocks ffmpeg,
            # causing the recording to stall and the file to be corrupted.
            log_fh = open(log_path, "w")
            current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=log_fh,
            )

            current_recording = {
                "id": recording_id,
                "file_path": file_path,
                "file_name": file_name,
                "start_time": start_time.isoformat(),
                "log_path": log_path,
                "log_fh": log_fh,
            }

            asyncio.create_task(notify_api_start(recording_id, file_path, file_name, start_time))

            _monitor_task = asyncio.create_task(monitor_ffmpeg_process(recording_id, log_path))

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
    global current_process, current_recording, _monitor_task

    async with recording_lock:
        if not current_process:
            return StopResponse(success=False, message="Not recording")

        recording_info = dict(current_recording) if current_recording else {}

        try:
            # Cancel the background monitor so it doesn't race with us
            if _monitor_task and not _monitor_task.done():
                _monitor_task.cancel()
                _monitor_task = None

            if current_process.poll() is None:
                # Send 'q' to ffmpeg stdin for the cleanest shutdown.
                # Falls back to SIGINT → SIGKILL.
                try:
                    current_process.send_signal(signal.SIGINT)
                except OSError:
                    pass

                try:
                    current_process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    logger.warning("FFmpeg did not stop in 15s, sending SIGKILL")
                    current_process.kill()
                    current_process.wait(timeout=5)

            end_time = datetime.utcnow()

            # Close the stderr log file handle
            log_fh = recording_info.get("log_fh")
            if log_fh:
                try:
                    log_fh.close()
                except Exception:
                    pass

            file_size = 0
            fp = recording_info.get("file_path")
            if fp and os.path.exists(fp):
                file_size = os.path.getsize(fp)

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


@app.get("/files/{camera_id}/{filename}")
async def serve_recording_file(camera_id: str, filename: str):
    """Serve a recording file from this node's local storage.
    Used by the API to proxy downloads from whichever node holds the file."""
    file_path = os.path.join(RECORDINGS_PATH, camera_id, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on this node")
    return FileResponse(file_path, media_type="video/mp4", filename=filename)


@app.get("/files")
async def list_local_files():
    """List all recording files on this node (for debugging)"""
    files = []
    for cam_dir in Path(RECORDINGS_PATH).iterdir():
        if cam_dir.is_dir():
            for f in cam_dir.iterdir():
                if f.is_file():
                    files.append({
                        "camera_id": cam_dir.name,
                        "filename": f.name,
                        "size_bytes": f.stat().st_size,
                    })
    return {"node_camera_id": CAMERA_ID, "files": files}


@app.on_event("startup")
async def startup():
    logger.info("Recorder ready — camera=%s stream=%s", CAMERA_ID, STREAM_URL)


@app.on_event("shutdown")
async def shutdown():
    """Clean up on shutdown"""
    if current_process and current_process.poll() is None:
        logger.info("Shutting down — stopping active recording")
        await stop_recording()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
