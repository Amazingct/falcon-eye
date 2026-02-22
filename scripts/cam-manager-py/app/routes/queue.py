"""Queue management API — Celery task inspection and control."""
import logging
from fastapi import APIRouter, HTTPException
from app.worker import celery_app

router = APIRouter(prefix="/api/queue", tags=["queue"])
logger = logging.getLogger(__name__)


def _redis_ok() -> bool:
    try:
        celery_app.connection().ensure_connection(max_retries=1, timeout=2)
        return True
    except Exception:
        return False


def _inspect():
    return celery_app.control.inspect(timeout=3)


@router.get("/status")
async def queue_status():
    redis_connected = _redis_ok()
    workers = []
    stats = {"completed": 0, "failed": 0}
    try:
        i = _inspect()
        active_workers = i.ping() or {}
        worker_stats = i.stats() or {}
        for name in active_workers:
            ws = worker_stats.get(name, {})
            total = ws.get("total", {})
            completed = sum(total.values()) if total else 0
            workers.append({"name": name})
            stats["completed"] += completed
    except Exception as e:
        logger.warning("Inspect failed: %s", e)
    return {
        "redis_connected": redis_connected,
        "workers": workers,
        "stats": stats,
    }


def _extract_task(t, status):
    args = t.get("args", [])
    recording_id = args[0] if args else t.get("kwargs", {}).get("recording_id")
    return {
        "task_id": t.get("id"),
        "task_name": t.get("name", ""),
        "status": status,
        "recording_id": recording_id,
        "started_at": t.get("time_start"),
        "error": None,
    }


@router.get("/tasks")
async def queue_tasks():
    active, reserved, completed, failed = [], [], [], []
    try:
        i = _inspect()
        for wname, tlist in (i.active() or {}).items():
            for t in tlist:
                active.append(_extract_task(t, "active"))
        for wname, tlist in (i.reserved() or {}).items():
            for t in tlist:
                reserved.append(_extract_task(t, "reserved"))
    except Exception as e:
        logger.warning("Task inspect failed: %s", e)

    # Check recent results from the result backend
    try:
        import redis as redis_lib
        import json
        r = redis_lib.Redis.from_url(celery_app.conf.result_backend, decode_responses=True)
        for key in r.scan_iter("celery-task-meta-*", count=200):
            try:
                raw = r.get(key)
                if not raw:
                    continue
                meta = json.loads(raw)
                task_id = meta.get("task_id") or key.replace("celery-task-meta-", "")
                status = (meta.get("status") or "").upper()
                task_info = {
                    "task_id": task_id,
                    "task_name": meta.get("name", ""),
                    "recording_id": None,
                    "started_at": meta.get("date_done"),
                    "completed_at": meta.get("date_done"),
                    "error": None,
                }
                # Try to get args from the meta
                args = meta.get("args")
                if args and isinstance(args, list) and args:
                    task_info["recording_id"] = args[0]
                if status == "SUCCESS":
                    task_info["status"] = "completed"
                    completed.append(task_info)
                elif status == "FAILURE":
                    task_info["status"] = "failed"
                    result = meta.get("result")
                    if result:
                        task_info["error"] = str(result)[:300]
                    traceback = meta.get("traceback")
                    if traceback and not task_info["error"]:
                        task_info["error"] = traceback.strip().split("\n")[-1][:300]
                    failed.append(task_info)
            except Exception:
                continue
    except Exception as e:
        logger.warning("Result backend scan failed: %s", e)

    return {
        "active": active,
        "reserved": reserved,
        "completed": completed[-50:],
        "failed": failed[-50:],
    }


@router.post("/retry/{task_id}")
async def retry_task(task_id: str):
    """Re-send a failed task. Looks up original task name/args from result backend."""
    try:
        import redis as redis_lib
        import json
        r = redis_lib.Redis.from_url(celery_app.conf.result_backend, decode_responses=True)
        raw = r.get(f"celery-task-meta-{task_id}")
        if not raw:
            raise HTTPException(404, "Task result not found")
        meta = json.loads(raw)
        task_name = meta.get("name")
        args = meta.get("args", [])
        kwargs = meta.get("kwargs", {})
        if not task_name:
            # Try to infer from children or just re-send upload
            raise HTTPException(400, "Cannot determine original task name")
        celery_app.send_task(task_name, args=args, kwargs=kwargs)
        return {"ok": True, "message": f"Retried {task_name}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/purge")
async def purge_queue():
    """Purge all pending (reserved) tasks."""
    try:
        purged = celery_app.control.purge()
        return {"ok": True, "purged": purged}
    except Exception as e:
        raise HTTPException(500, str(e))
