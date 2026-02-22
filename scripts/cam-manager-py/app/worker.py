"""Celery worker for async tasks (cloud upload, etc.)"""
import os
import logging
from celery import Celery

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery("falcon_eye", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_max_tasks_per_child=100,
)


def _get_sync_db_url():
    raw = os.getenv("DATABASE_URL", "postgresql://falcon:falcon-eye-2026@postgres:5432/falconeye")
    if "+asyncpg" in raw:
        raw = raw.replace("+asyncpg", "")
    if not raw.startswith("postgresql://"):
        raw = raw.replace("postgresql+asyncpg://", "postgresql://")
    return raw


def _get_cloud_settings():
    """Read cloud settings from environment (populated via ConfigMap)."""
    return {
        "enabled": os.getenv("CLOUD_STORAGE_ENABLED", "false").lower() == "true",
        "provider": os.getenv("CLOUD_STORAGE_PROVIDER", "spaces"),
        "access_key": os.getenv("CLOUD_STORAGE_ACCESS_KEY", ""),
        "secret_key": os.getenv("CLOUD_STORAGE_SECRET_KEY", ""),
        "bucket": os.getenv("CLOUD_STORAGE_BUCKET", ""),
        "region": os.getenv("CLOUD_STORAGE_REGION", ""),
        "endpoint": os.getenv("CLOUD_STORAGE_ENDPOINT", ""),
        "delete_local": os.getenv("CLOUD_DELETE_LOCAL", "true").lower() == "true",
    }


@celery_app.task(bind=True, name="upload_recording_to_cloud", max_retries=3, default_retry_delay=60)
def upload_recording_to_cloud(self, recording_id: str):
    """Upload a recording file to S3/Spaces and update DB."""
    import boto3
    from botocore.exceptions import ClientError
    from sqlalchemy import create_engine, text

    cloud = _get_cloud_settings()
    if not cloud["enabled"]:
        logger.info("Cloud storage disabled, skipping upload for %s", recording_id)
        return

    if not cloud["access_key"] or not cloud["bucket"]:
        logger.warning("Cloud storage not configured (missing key/bucket)")
        return

    db_url = _get_sync_db_url()
    engine = create_engine(db_url)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT file_path, file_name, camera_id FROM recordings WHERE id = :id"),
            {"id": recording_id},
        ).fetchone()

    if not row:
        logger.error("Recording %s not found in DB", recording_id)
        return

    file_path, file_name, camera_id = row[0], row[1], str(row[2]) if row[2] else "unknown"

    temp_file = None
    if not file_path or not os.path.exists(file_path):
        # File not on this node — fetch via internal API
        import requests
        import tempfile
        api_key = os.getenv("INTERNAL_API_KEY", "")
        api_url = f"http://falcon-eye-api:8000/api/recordings/{recording_id}/download"
        logger.info("File not local, fetching from API: %s", api_url)
        try:
            headers = {}
            if api_key:
                headers["X-Internal-Key"] = api_key
            resp = requests.get(api_url, headers=headers, stream=True, timeout=120)
            resp.raise_for_status()
            suffix = os.path.splitext(file_name)[1] if file_name else ".mp4"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            for chunk in resp.iter_content(chunk_size=8192):
                tmp.write(chunk)
            tmp.close()
            temp_file = tmp.name
            file_path = temp_file
            logger.info("Downloaded recording to temp file: %s", temp_file)
        except Exception as e:
            logger.error("Failed to fetch recording %s from API: %s", recording_id, e)
            return

    # Update status to uploading
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE recordings SET status = 'UPLOADING' WHERE id = :id"),
            {"id": recording_id},
        )
        conn.commit()

    # Build S3 client
    s3_kwargs = {
        "aws_access_key_id": cloud["access_key"],
        "aws_secret_access_key": cloud["secret_key"],
        "region_name": cloud["region"] or "us-east-1",
    }
    if cloud["endpoint"]:
        endpoint = cloud["endpoint"]
        if not endpoint.startswith("http"):
            endpoint = f"https://{endpoint}"
        s3_kwargs["endpoint_url"] = endpoint

    try:
        s3 = boto3.client("s3", **s3_kwargs)
        s3_key = f"falcon-eye/{camera_id}/{file_name}"

        logger.info("Uploading %s to %s/%s", file_path, cloud["bucket"], s3_key)
        s3.upload_file(file_path, cloud["bucket"], s3_key)

        # Build the cloud URL
        if cloud["endpoint"]:
            base = cloud["endpoint"].rstrip("/")
            if not base.startswith("http"):
                base = f"https://{base}"
            cloud_url = f"{base}/{cloud['bucket']}/{s3_key}"
        else:
            cloud_url = f"https://{cloud['bucket']}.s3.{cloud['region']}.amazonaws.com/{s3_key}"

        # Update DB
        with engine.connect() as conn:
            conn.execute(
                text("UPDATE recordings SET cloud_url = :url, status = 'UPLOADED' WHERE id = :id"),
                {"url": cloud_url, "id": recording_id},
            )
            conn.commit()

        logger.info("Upload complete: %s -> %s", recording_id, cloud_url)

        # Delete local file if configured (or always delete temp files)
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)
            logger.info("Deleted temp file: %s", temp_file)
        elif cloud["delete_local"] and os.path.exists(file_path):
            os.remove(file_path)
            logger.info("Deleted local file: %s", file_path)

    except ClientError as e:
        logger.error("S3 upload failed for %s: %s", recording_id, e)
        with engine.connect() as conn:
            conn.execute(
                text("UPDATE recordings SET status = 'COMPLETED', error_message = :err WHERE id = :id"),
                {"err": f"Cloud upload failed: {e}", "id": recording_id},
            )
            conn.commit()
        raise self.retry(exc=e)
    except Exception as e:
        logger.error("Upload error for %s: %s", recording_id, e)
        with engine.connect() as conn:
            conn.execute(
                text("UPDATE recordings SET status = 'COMPLETED', error_message = :err WHERE id = :id"),
                {"err": f"Cloud upload error: {e}", "id": recording_id},
            )
            conn.commit()
        raise

    engine.dispose()


@celery_app.task(name="delete_local_recording")
def delete_local_recording(recording_id: str):
    """Delete the local file for a recording after confirmed cloud upload."""
    from sqlalchemy import create_engine, text

    db_url = _get_sync_db_url()
    engine = create_engine(db_url)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT file_path, cloud_url FROM recordings WHERE id = :id"),
            {"id": recording_id},
        ).fetchone()

    if not row or not row[1]:
        logger.warning("Recording %s has no cloud_url, skipping local delete", recording_id)
        engine.dispose()
        return

    file_path = row[0]
    if file_path and os.path.exists(file_path):
        os.remove(file_path)
        logger.info("Deleted local file: %s", file_path)

    engine.dispose()
