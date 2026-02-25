"""Database connection and session management"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from app.config import get_settings
from app.models.camera import Base
from app.models.recording import Recording  # Import to register model
from app.models.chat import ChatSession, ChatMessage  # Import to register models
from app.models.agent import Agent, AgentChatMessage, CronJob  # Import to register models
from app.models.settings import Setting  # Import to register model

settings = get_settings()

# Async engine for FastAPI
async_engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=10,
    max_overflow=20,
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Sync engine for migrations
sync_engine = create_engine(settings.sync_database_url, echo=settings.debug)
SyncSessionLocal = sessionmaker(bind=sync_engine)


async def init_db():
    """Initialize database tables and run lightweight migrations"""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Add columns that may not exist in older databases
    async with async_engine.begin() as conn:
        from sqlalchemy import text
        migrations = [
            "ALTER TABLE recordings ADD COLUMN IF NOT EXISTS node_name VARCHAR",
            "ALTER TABLE cron_jobs ADD COLUMN IF NOT EXISTS session_id VARCHAR(100)",

            # Typed chat content (agent chat)
            "ALTER TABLE agent_chat_messages ADD COLUMN IF NOT EXISTS content_type VARCHAR(20)",
            "ALTER TABLE agent_chat_messages ADD COLUMN IF NOT EXISTS content_text TEXT",
            "ALTER TABLE agent_chat_messages ADD COLUMN IF NOT EXISTS content_media JSONB",

            # Typed chat content (chatbot sessions)
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS content_type VARCHAR(20)",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS content_text TEXT",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS content_media JSONB",

            # Recording cloud upload fields
            "ALTER TABLE recordings ADD COLUMN IF NOT EXISTS cloud_url VARCHAR",
            "ALTER TABLE recordings ADD COLUMN IF NOT EXISTS camera_info JSONB",
        ]
        for sql in migrations:
            try:
                await conn.execute(text(sql))
            except Exception:
                pass

        # Backfill defaults for older rows (best-effort)
        try:
            await conn.execute(text(
                "UPDATE agent_chat_messages "
                "SET content_type = COALESCE(content_type, 'text'), "
                "    content_text = COALESCE(content_text, content) "
                "WHERE content_type IS NULL OR content_text IS NULL"
            ))
        except Exception:
            pass

        try:
            await conn.execute(text(
                "UPDATE chat_messages "
                "SET content_type = COALESCE(content_type, 'text'), "
                "    content_text = COALESCE(content_text, content) "
                "WHERE content_type IS NULL OR content_text IS NULL"
            ))
        except Exception:
            pass
    
    print("Database initialized")


async def close_db():
    """Close database connections"""
    await async_engine.dispose()
    print("Database connections closed")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context():
    """Context manager for database sessions"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_db_session():
    """Async context manager for background tasks"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
