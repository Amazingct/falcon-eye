"""Cron job API routes"""
from datetime import datetime
from uuid import UUID
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field

from app.database import get_db
from app.models.agent import Agent, CronJob
from app.services import k8s

router = APIRouter(prefix="/api/cron", tags=["cron"])


class CronJobCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    agent_id: str
    cron_expr: str = Field(..., min_length=1)
    timezone: str = Field(default="UTC")
    prompt: str = Field(..., min_length=1)
    timeout_seconds: int = Field(default=120, ge=10, le=3600)
    enabled: bool = True


class CronJobUpdate(BaseModel):
    name: Optional[str] = None
    cron_expr: Optional[str] = None
    timezone: Optional[str] = None
    prompt: Optional[str] = None
    timeout_seconds: Optional[int] = None
    enabled: Optional[bool] = None
    last_run: Optional[str] = None
    last_result: Optional[str] = None
    last_status: Optional[str] = None


@router.get("/")
async def list_cron_jobs(db: AsyncSession = Depends(get_db)):
    """List all cron jobs"""
    result = await db.execute(
        select(CronJob).order_by(CronJob.created_at.desc())
    )
    jobs = result.scalars().all()
    return {"cron_jobs": [j.to_dict() for j in jobs]}


@router.post("/", status_code=201)
async def create_cron_job(data: CronJobCreate, db: AsyncSession = Depends(get_db)):
    """Create a new cron job and K8s CronJob resource"""
    # Verify agent exists
    result = await db.execute(select(Agent).where(Agent.id == data.agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    cron_job = CronJob(
        name=data.name,
        agent_id=data.agent_id,
        cron_expr=data.cron_expr,
        timezone=data.timezone,
        prompt=data.prompt,
        timeout_seconds=data.timeout_seconds,
        enabled=data.enabled,
    )
    db.add(cron_job)
    await db.flush()
    await db.refresh(cron_job)

    # Create K8s CronJob
    try:
        cronjob_name = await k8s.create_k8s_cronjob(cron_job, agent)
        cron_job.cronjob_name = cronjob_name
        await db.commit()
        await db.refresh(cron_job)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create K8s CronJob: {e}")

    return cron_job.to_dict()


@router.get("/{cron_id}")
async def get_cron_job(cron_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get cron job details"""
    result = await db.execute(select(CronJob).where(CronJob.id == cron_id))
    cron_job = result.scalar_one_or_none()
    if not cron_job:
        raise HTTPException(status_code=404, detail="Cron job not found")
    return cron_job.to_dict()


@router.patch("/{cron_id}")
async def update_cron_job(cron_id: UUID, data: CronJobUpdate, db: AsyncSession = Depends(get_db)):
    """Update cron job configuration"""
    result = await db.execute(select(CronJob).where(CronJob.id == cron_id))
    cron_job = result.scalar_one_or_none()
    if not cron_job:
        raise HTTPException(status_code=404, detail="Cron job not found")

    update_data = data.model_dump(exclude_unset=True)

    # Handle last_run datetime conversion
    if "last_run" in update_data and update_data["last_run"]:
        try:
            update_data["last_run"] = datetime.fromisoformat(update_data["last_run"].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            update_data["last_run"] = datetime.utcnow()

    needs_k8s_update = any(k in update_data for k in ("cron_expr", "prompt", "timeout_seconds", "enabled"))

    for field, value in update_data.items():
        setattr(cron_job, field, value)

    # Update K8s CronJob if schedule/config changed
    if needs_k8s_update and cron_job.cronjob_name:
        try:
            agent_result = await db.execute(select(Agent).where(Agent.id == cron_job.agent_id))
            agent = agent_result.scalar_one_or_none()
            if agent:
                await k8s.update_k8s_cronjob(cron_job, agent)
        except Exception as e:
            # Log but don't fail the DB update
            import logging
            logging.getLogger(__name__).error(f"Failed to update K8s CronJob: {e}")

    await db.commit()
    await db.refresh(cron_job)
    return cron_job.to_dict()


@router.delete("/{cron_id}")
async def delete_cron_job(cron_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete cron job and K8s CronJob resource"""
    result = await db.execute(select(CronJob).where(CronJob.id == cron_id))
    cron_job = result.scalar_one_or_none()
    if not cron_job:
        raise HTTPException(status_code=404, detail="Cron job not found")

    # Delete K8s CronJob
    if cron_job.cronjob_name:
        try:
            await k8s.delete_k8s_cronjob(cron_job.cronjob_name)
        except Exception:
            pass

    await db.delete(cron_job)
    await db.commit()
    return {"message": "Cron job deleted", "id": str(cron_id)}


@router.post("/{cron_id}/run")
async def run_cron_job(cron_id: UUID, db: AsyncSession = Depends(get_db)):
    """Manually trigger a cron job (create one-off K8s Job)"""
    result = await db.execute(select(CronJob).where(CronJob.id == cron_id))
    cron_job = result.scalar_one_or_none()
    if not cron_job:
        raise HTTPException(status_code=404, detail="Cron job not found")

    agent_result = await db.execute(select(Agent).where(Agent.id == cron_job.agent_id))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        job_name = await k8s.trigger_k8s_cronjob(cron_job, agent)
        return {"message": "Cron job triggered", "job_name": job_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to trigger cron job: {e}")


@router.get("/{cron_id}/history")
async def get_cron_history(
    cron_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get execution history for a cron job (from K8s Jobs)"""
    result = await db.execute(select(CronJob).where(CronJob.id == cron_id))
    cron_job = result.scalar_one_or_none()
    if not cron_job:
        raise HTTPException(status_code=404, detail="Cron job not found")

    # Get job history from K8s
    history = []
    if cron_job.cronjob_name:
        try:
            from kubernetes import client as k8s_client
            batch_api = k8s_client.BatchV1Api()
            from app.config import get_settings
            settings = get_settings()
            jobs = batch_api.list_namespaced_job(
                namespace=settings.k8s_namespace,
                label_selector=f"cron-id={str(cron_job.id)}",
            )
            for job in sorted(jobs.items, key=lambda j: j.metadata.creation_timestamp or datetime.min, reverse=True)[:limit]:
                status = "running"
                if job.status.succeeded:
                    status = "success"
                elif job.status.failed:
                    status = "failed"
                history.append({
                    "job_name": job.metadata.name,
                    "status": status,
                    "started_at": job.metadata.creation_timestamp.isoformat() if job.metadata.creation_timestamp else None,
                    "completed_at": job.status.completion_time.isoformat() if job.status.completion_time else None,
                })
        except Exception:
            pass

    return {
        "cron_job_id": str(cron_id),
        "history": history,
        "last_run": cron_job.last_run.isoformat() if cron_job.last_run else None,
        "last_status": cron_job.last_status,
        "last_result": cron_job.last_result,
    }
