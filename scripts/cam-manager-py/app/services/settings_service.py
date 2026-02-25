"""Settings service — cached reads from postgres, no restarts needed.

Usage:
    from app.services.settings_service import settings_service

    val = await settings_service.get("RECORDING_CHUNK_MINUTES")
    await settings_service.set("RECORDING_CHUNK_MINUTES", "10")
    bulk = await settings_service.get_many(["CLOUD_STORAGE_ENABLED", "CLOUD_STORAGE_BUCKET"])
    await settings_service.set_many({"CLOUD_STORAGE_ENABLED": "true", ...})
"""
import asyncio
import logging
import time
from typing import Optional

from sqlalchemy import select, text
from app.database import AsyncSessionLocal
from app.models.settings import Setting, DEFAULTS

logger = logging.getLogger(__name__)

CACHE_TTL = 30  # seconds


class SettingsService:
    """In-memory cached settings backed by postgres."""

    def __init__(self, ttl: float = CACHE_TTL):
        self._cache: dict[str, str] = {}
        self._cache_time: float = 0
        self._ttl = ttl
        self._lock = asyncio.Lock()
        self._initialized = False

    async def _ensure_table(self):
        """Create settings table and seed defaults if needed."""
        if self._initialized:
            return
        async with AsyncSessionLocal() as session:
            # Table is created by Base.metadata.create_all in init_db,
            # but seed defaults for any missing keys
            for key, default in DEFAULTS.items():
                existing = await session.execute(
                    select(Setting).where(Setting.key == key)
                )
                if not existing.scalar_one_or_none():
                    session.add(Setting(key=key, value=default))
            await session.commit()
        self._initialized = True

    async def _refresh_cache(self, force: bool = False):
        """Reload all settings from DB if cache is stale."""
        now = time.time()
        if not force and self._cache and (now - self._cache_time) < self._ttl:
            return
        async with self._lock:
            # Double-check after acquiring lock
            if not force and self._cache and (time.time() - self._cache_time) < self._ttl:
                return
            await self._ensure_table()
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(Setting))
                rows = result.scalars().all()
                self._cache = {r.key: r.value for r in rows}
                self._cache_time = time.time()

    async def get(self, key: str, default: Optional[str] = None) -> str:
        """Get a single setting value."""
        await self._refresh_cache()
        return self._cache.get(key, DEFAULTS.get(key, default or ""))

    async def get_many(self, keys: list[str]) -> dict[str, str]:
        """Get multiple settings at once."""
        await self._refresh_cache()
        return {k: self._cache.get(k, DEFAULTS.get(k, "")) for k in keys}

    async def get_all(self) -> dict[str, str]:
        """Get all settings."""
        await self._refresh_cache()
        # Merge defaults with stored values (stored wins)
        merged = dict(DEFAULTS)
        merged.update(self._cache)
        return merged

    async def set(self, key: str, value: str):
        """Set a single setting (upsert)."""
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    "INSERT INTO settings (key, value, updated_at) "
                    "VALUES (:key, :value, NOW()) "
                    "ON CONFLICT (key) DO UPDATE SET value = :value, updated_at = NOW()"
                ),
                {"key": key, "value": value},
            )
            await session.commit()
        # Invalidate cache
        self._cache[key] = value

    async def set_many(self, updates: dict[str, str]):
        """Set multiple settings at once."""
        async with AsyncSessionLocal() as session:
            for key, value in updates.items():
                await session.execute(
                    text(
                        "INSERT INTO settings (key, value, updated_at) "
                        "VALUES (:key, :value, NOW()) "
                        "ON CONFLICT (key) DO UPDATE SET value = :value, updated_at = NOW()"
                    ),
                    {"key": key, "value": value},
                )
            await session.commit()
        # Update cache immediately
        self._cache.update(updates)

    async def get_recording_config(self) -> dict:
        """Return config blob needed by recorder pods."""
        keys = [
            "RECORDING_CHUNK_MINUTES",
            "CLOUD_STORAGE_ENABLED",
            "CLOUD_STORAGE_PROVIDER",
            "CLOUD_STORAGE_ACCESS_KEY",
            "CLOUD_STORAGE_SECRET_KEY",
            "CLOUD_STORAGE_BUCKET",
            "CLOUD_STORAGE_REGION",
            "CLOUD_STORAGE_ENDPOINT",
            "CLOUD_DELETE_LOCAL",
        ]
        return await self.get_many(keys)

    async def migrate_from_configmap(self, cm_data: dict[str, str]):
        """One-time migration: import existing ConfigMap values into DB.
        Only writes keys that don't already have a non-default value in DB."""
        await self._refresh_cache(force=True)
        updates = {}
        for key, value in cm_data.items():
            if key in DEFAULTS:
                current = self._cache.get(key, "")
                default = DEFAULTS.get(key, "")
                if current == default and value != default:
                    updates[key] = value
        if updates:
            await self.set_many(updates)
            logger.info(f"Migrated {len(updates)} settings from ConfigMap to DB: {list(updates.keys())}")


# Singleton
settings_service = SettingsService()
