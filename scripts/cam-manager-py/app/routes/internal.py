"""Internal API routes — no auth required.

These endpoints are consumed by intra-cluster pods (recorders, agents)
that need runtime config without holding JWT credentials.
"""
from fastapi import APIRouter

from app.services.settings_service import settings_service

router = APIRouter(prefix="/api/internal", tags=["internal"])


@router.get("/settings/recording")
async def get_recording_settings():
    """Return recording + cloud storage config for recorder pods.
    No auth required — cluster-internal only."""
    return await settings_service.get_recording_config()


@router.get("/settings/{key}")
async def get_single_setting(key: str):
    """Return a single setting value. No auth required — cluster-internal."""
    value = await settings_service.get(key)
    return {"key": key, "value": value}
