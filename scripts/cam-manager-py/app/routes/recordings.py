"""Recordings API routes"""
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID
import os
import logging
import subprocess
import tempfile
import hashlib
import httpx

from app.database import get_db
from app.config import get_settings
from app.models.recording import Recording, RecordingStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/recordings", tags=["recordings"])
settings = get_settings()

# Transcoding cache directory
TRANSCODE_CACHE_DIR = "/tmp/falcon-eye-transcode-cache"
os.makedirs(TRANSCODE_CACHE_DIR, exist_ok=True)


def _probe_codec(file_path: str) -> str:
    """Probe video codec using ffprobe. Returns codec name (e.g. 'hevc', 'h264')."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name", "-of", "csv=p=0", file_path],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip().lower()
    except Exception as e:
        logger.warning(f"ffprobe failed for {file_path}: {e}")
        return ""


def _needs_transcode(codec: str) -> bool:
    """Check if codec needs transcoding for web playback."""
    # HEVC/H.265 and VP9 don't play in all browsers
    return codec in ("hevc", "h265", "av1")


def _get_cache_path(recording_id: str) -> str:
    """Get the cache path for a transcoded recording."""
    safe_id = hashlib.md5(recording_id.encode()).hexdigest()
    return os.path.join(TRANSCODE_CACHE_DIR, f"{safe_id}.mp4")


def _transcode_to_h264(input_path: str, output_path: str) -> bool:
    """Transcode a video to H.264/AAC MP4 for web playback."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", input_path,
             "-c:v", "libx264", "-preset", "fast", "-crf", "23",
             "-c:a", "aac", "-b:a", "128k",
             "-movflags", "+faststart",
             output_path],
            capture_output=True, text=True, timeout=600,  # 10 min max
        )
        if result.returncode != 0:
            logger.error(f"ffmpeg transcode failed: {result.stderr[-500:]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg transcode timed out (10 min)")
        return False
    except Exception as e:
        logger.error(f"Transcode error: {e}")
        return False


async def _download_to_temp(recording) -> str | None:
    """Download a recording to a temp file for probing/transcoding."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp_path = tmp.name
    tmp.close()
    try:
        if recording.file_path and os.path.exists(recording.file_path):
            import shutil
            shutil.copy2(recording.file_path, tmp_path)
            return tmp_path

        if recording.cloud_url:
            import boto3
            provider = os.environ.get("CLOUD_STORAGE_PROVIDER", "spaces")
            access_key = os.environ.get("CLOUD_STORAGE_ACCESS_KEY", "")
            secret_key = os.environ.get("CLOUD_STORAGE_SECRET_KEY", "")
            bucket = os.environ.get("CLOUD_STORAGE_BUCKET", "")
            region = os.environ.get("CLOUD_STORAGE_REGION", "us-east-1")
            endpoint = os.environ.get("CLOUD_STORAGE_ENDPOINT", "")

            if not access_key or not secret_key or not bucket:
                return None

            s3_kwargs = {
                "service_name": "s3",
                "aws_access_key_id": access_key,
                "aws_secret_access_key": secret_key,
                "region_name": region,
            }
            if endpoint:
                s3_kwargs["endpoint_url"] = f"https://{endpoint}"

            s3 = boto3.client(**s3_kwargs)
            from urllib.parse import urlparse
            parsed = urlparse(recording.cloud_url)
            s3_key = parsed.path.lstrip("/")
            if s3_key.startswith(f"{bucket}/"):
                s3_key = s3_key[len(f"{bucket}/"):]

            s3.download_file(bucket, s3_key, tmp_path)
            return tmp_path
    except Exception as e:
        logger.error(f"Failed to download recording for transcoding: {e}")
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return None


async def _stream_from_cloud(recording: Recording):
    """Stream a recording file from S3/Spaces through the API (for private buckets)."""
    import boto3
    from botocore.exceptions import ClientError

    provider = os.environ.get("CLOUD_STORAGE_PROVIDER", "spaces")
    access_key = os.environ.get("CLOUD_STORAGE_ACCESS_KEY", "")
    secret_key = os.environ.get("CLOUD_STORAGE_SECRET_KEY", "")
    bucket = os.environ.get("CLOUD_STORAGE_BUCKET", "")
    region = os.environ.get("CLOUD_STORAGE_REGION", "us-east-1")
    endpoint = os.environ.get("CLOUD_STORAGE_ENDPOINT", "")

    if not access_key or not secret_key or not bucket:
        raise HTTPException(status_code=500, detail="Cloud storage not configured")

    # Build S3 client
    s3_kwargs = {
        "service_name": "s3",
        "aws_access_key_id": access_key,
        "aws_secret_access_key": secret_key,
        "region_name": region,
    }
    if endpoint:
        s3_kwargs["endpoint_url"] = f"https://{endpoint}"

    s3 = boto3.client(**s3_kwargs)

    # Extract the S3 key from the cloud URL
    cloud_url = recording.cloud_url
    # URL format: https://bucket.endpoint/key or https://endpoint/bucket/key
    try:
        from urllib.parse import urlparse
        parsed = urlparse(cloud_url)
        # For DO Spaces: https://bucket.sfo3.digitaloceanspaces.com/path/to/file
        # The key is the path without leading slash
        s3_key = parsed.path.lstrip("/")
        # If bucket name is in the hostname, key is just the path
        # If bucket is in the path, strip it
        if s3_key.startswith(f"{bucket}/"):
            s3_key = s3_key[len(f"{bucket}/"):]
    except Exception:
        raise HTTPException(status_code=500, detail="Cannot parse cloud URL")

    try:
        s3_response = s3.get_object(Bucket=bucket, Key=s3_key)
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            raise HTTPException(status_code=404, detail="Recording not found in cloud storage")
        raise HTTPException(status_code=500, detail=f"Cloud storage error: {e}")

    content_type = s3_response.get("ContentType", "video/mp4")
    content_length = s3_response.get("ContentLength")

    def _iter_body():
        body = s3_response["Body"]
        try:
            while True:
                chunk = body.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    headers = {"Content-Disposition": f'attachment; filename="{recording.file_name}"'}
    if content_length:
        headers["Content-Length"] = str(content_length)

    return StreamingResponse(_iter_body(), media_type=content_type, headers=headers)


class RecordingCreate(BaseModel):
    """Create recording request (from recorder service)"""
    id: str
    camera_id: str
    camera_name: Optional[str] = None
    file_path: str
    file_name: str
    start_time: str
    status: str = "recording"
    node_name: Optional[str] = None  # K8s node where file is stored


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
    node_name: Optional[str] = None
    camera_deleted: bool = False
    cloud_url: Optional[str] = None
    camera_info: Optional[dict] = None
    
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
        camera_name=data.camera_name,
        file_path=data.file_path,
        file_name=data.file_name,
        start_time=datetime.fromisoformat(data.start_time),
        status=RecordingStatus(data.status),
        node_name=data.node_name,
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
    
    # Trigger cloud upload if recording completed/stopped and cloud storage enabled
    if data.status in ("completed", "stopped"):
        try:
            cloud_enabled = os.getenv("CLOUD_STORAGE_ENABLED", "false").lower() == "true"
            redis_url = os.getenv("REDIS_URL", "")
            if cloud_enabled and redis_url:
                from app.worker import upload_recording_to_cloud
                upload_recording_to_cloud.delay(recording_id)
        except Exception as e:
            print(f"Failed to queue cloud upload for {recording_id}: {e}")
    
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


async def _find_file_on_cluster(
    camera_id: str,
    file_name: str,
    hint_node: Optional[str] = None,
) -> Optional[str]:
    """Locate a recording file across the cluster via the file-server DaemonSet.
    
    The file-server DaemonSet runs on every node, mounting the local hostPath.
    If hint_node is provided, we try that node's pod first (O(1) best case).
    Otherwise we check all file-server pods.
    """
    settings = get_settings()
    file_path = f"/{camera_id}/{file_name}"

    try:
        from app.services.k8s import core_api
        pods = core_api.list_namespaced_pod(
            namespace=settings.k8s_namespace,
            label_selector="app=falcon-eye,component=file-server",
        )
        if not pods.items:
            return None

        # Sort so the hint node's pod is checked first
        pod_list = list(pods.items)
        if hint_node:
            pod_list.sort(key=lambda p: 0 if p.spec.node_name == hint_node else 1)

        async with httpx.AsyncClient(timeout=5) as client:
            for pod in pod_list:
                pod_ip = pod.status.pod_ip
                if not pod_ip:
                    continue
                try:
                    url = f"http://{pod_ip}:8080{file_path}"
                    res = await client.head(url)
                    if res.status_code == 200:
                        return url
                except Exception:
                    continue
    except Exception as e:
        print(f"Error searching file-server pods: {e}")
    return None


@router.get("/{recording_id}/download")
async def download_recording(
    recording_id: str,
    format: Optional[str] = Query(None, description="'web' to auto-transcode HEVC to H.264 for browser playback"),
    db: AsyncSession = Depends(get_db),
):
    """Download a recording file.
    
    Strategy:
    1. Try serving from local volume (works when API shares a node with the file)
    2. Locate the file via the file-server DaemonSet and stream it back
    
    If format=web, automatically detects HEVC and transcodes to H.264 for
    browser compatibility. H.264 recordings are served as-is (no transcoding).
    Transcoded files are cached to avoid re-transcoding.
    """
    result = await db.execute(
        select(Recording).where(Recording.id == recording_id)
    )
    recording = result.scalar_one_or_none()
    
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    
    if not recording.file_path and not recording.cloud_url:
        raise HTTPException(status_code=404, detail="No file path for this recording")
    
    # If format=web, check for HEVC and transcode if needed
    if format == "web":
        return await _serve_web_format(recording)
    
    # 0. Cloud URL is priority — stream from S3/Spaces via API
    if recording.cloud_url:
        return await _stream_from_cloud(recording)
    
    # 1. Fallback: local file (same node or shared storage)
    if recording.file_path and os.path.exists(recording.file_path):
        return FileResponse(
            recording.file_path,
            media_type="video/mp4",
            filename=recording.file_name,
        )
    
    # 2. File not on this node — locate it via the file-server DaemonSet
    camera_id = str(recording.camera_id) if recording.camera_id else None
    if not camera_id or not recording.file_name:
        raise HTTPException(
            status_code=404,
            detail="Recording file not found on this node and cannot locate it remotely",
        )
    
    remote_url = await _find_file_on_cluster(
        camera_id,
        recording.file_name,
        hint_node=getattr(recording, "node_name", None),
    )
    if not remote_url:
        raise HTTPException(
            status_code=404,
            detail="Recording file not found on any node",
        )
    
    async def _stream():
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream("GET", remote_url) as resp:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    yield chunk

    return StreamingResponse(
        _stream(),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'attachment; filename="{recording.file_name}"',
        },
    )


async def _serve_web_format(recording):
    """Serve a web-compatible version of a recording.
    
    - If codec is already H.264: serve original (no transcoding)
    - If codec is HEVC: transcode to H.264 with caching
    """
    cache_path = _get_cache_path(recording.id)
    
    # Check cache first
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        logger.info(f"Serving transcoded recording from cache: {recording.id}")
        return FileResponse(
            cache_path,
            media_type="video/mp4",
            filename=recording.file_name,
        )
    
    # Download to temp for probing
    tmp_path = await _download_to_temp(recording)
    if not tmp_path:
        # Fall back to regular download
        if recording.cloud_url:
            return await _stream_from_cloud(recording)
        raise HTTPException(status_code=500, detail="Could not download recording for transcoding")
    
    try:
        codec = _probe_codec(tmp_path)
        logger.info(f"Recording {recording.id} codec: {codec}")
        
        if not _needs_transcode(codec):
            # Already H.264 or compatible — serve as-is
            logger.info(f"Recording {recording.id} is {codec}, no transcoding needed")
            return FileResponse(
                tmp_path,
                media_type="video/mp4",
                filename=recording.file_name,
            )
        
        # Transcode HEVC → H.264
        logger.info(f"Transcoding recording {recording.id} from {codec} to H.264...")
        success = _transcode_to_h264(tmp_path, cache_path)
        
        if success and os.path.exists(cache_path):
            logger.info(f"Transcoding complete: {recording.id}")
            # Clean up temp file now
            os.unlink(tmp_path)
            return FileResponse(
                cache_path,
                media_type="video/mp4",
                filename=recording.file_name,
            )
        else:
            # Transcode failed — serve original
            logger.warning(f"Transcoding failed for {recording.id}, serving original")
            return FileResponse(
                tmp_path,
                media_type="video/mp4",
                filename=recording.file_name,
            )
    except Exception as e:
        logger.error(f"Web format error for {recording.id}: {e}")
        # Clean up and fall back
        if os.path.exists(tmp_path):
            return FileResponse(tmp_path, media_type="video/mp4", filename=recording.file_name)
        if recording.cloud_url:
            return await _stream_from_cloud(recording)
        raise HTTPException(status_code=500, detail=f"Transcoding error: {e}")
