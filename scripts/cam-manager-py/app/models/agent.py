"""Agent, AgentChatMessage, and CronJob database models"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Integer, DateTime, Text, Float, Boolean, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.models.camera import Base

MEDIA_ROLES = {"assistant_media", "user_media"}


class Agent(Base):
    """Agent model - represents an AI agent (built-in or pod)"""
    __tablename__ = "agents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(100), nullable=False)
    slug = Column(String(50), unique=True, nullable=False, index=True)
    type = Column(String(20), nullable=False)  # built-in | pod
    status = Column(String(20), default="stopped")  # running | stopped | error | creating

    # LLM Configuration
    provider = Column(String(50), nullable=False, default="openai")
    model = Column(String(100), nullable=False, default="gpt-4o")
    api_key_ref = Column(Text, nullable=True)
    system_prompt = Column(Text, nullable=True)
    temperature = Column(Float, default=0.7)
    max_tokens = Column(Integer, default=4096)

    # Channel Configuration
    channel_type = Column(String(20), nullable=True)  # null | telegram | webhook | discord
    channel_config = Column(JSONB, default=dict)

    # K8s Configuration
    deployment_name = Column(String(255), nullable=True)
    service_name = Column(String(255), nullable=True)
    node_name = Column(String(255), nullable=True)

    # Tools
    tools = Column(JSONB, default=list)

    # Resource limits
    cpu_limit = Column(String(20), default="500m")
    memory_limit = Column(String(20), default="512Mi")

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    chat_messages = relationship("AgentChatMessage", back_populates="agent", cascade="all, delete-orphan")
    cron_jobs = relationship("CronJob", back_populates="agent", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "slug": self.slug,
            "type": self.type,
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "api_key_ref": self.api_key_ref,
            "system_prompt": self.system_prompt,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "channel_type": self.channel_type,
            "channel_config": self.channel_config or {},
            "deployment_name": self.deployment_name,
            "service_name": self.service_name,
            "node_name": self.node_name,
            "tools": self.tools or [],
            "cpu_limit": self.cpu_limit,
            "memory_limit": self.memory_limit,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AgentChatMessage(Base):
    """Chat message model for agent conversations"""
    __tablename__ = "agent_chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String(100), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user | assistant | system | assistant_media | user_media
    # Legacy text payload (kept for backwards compatibility; always non-null)
    content = Column(Text, nullable=False, default="")

    # New typed content (preferred)
    content_type = Column(String(20), nullable=True, default="text")  # text | media
    content_text = Column(Text, nullable=True)
    content_media = Column(JSONB, nullable=True)

    # Source tracking
    source = Column(String(50), nullable=True)  # dashboard | telegram | cron | api
    source_user = Column(String(100), nullable=True)

    # Token usage
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship
    agent = relationship("Agent", back_populates="chat_messages")

    __table_args__ = (
        Index("idx_agent_session", "agent_id", "session_id", "created_at"),
    )

    def content_for_api(self):
        """Return content in API-friendly shape: str for text, dict for media."""
        if self.content_type == "media" or self.role in MEDIA_ROLES:
            return self.content_media or {}
        return self.content_text if self.content_text is not None else (self.content or "")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "agent_id": str(self.agent_id),
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content_for_api(),
            "source": self.source,
            "source_user": self.source_user,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class CronJob(Base):
    """Cron job model - scheduled prompts for agents"""
    __tablename__ = "cron_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(100), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)

    # Schedule
    cron_expr = Column(String(100), nullable=False)
    timezone = Column(String(50), default="UTC")

    # Session — when set, cron results are delivered to this session
    session_id = Column(String(100), nullable=True)

    # Prompt
    prompt = Column(Text, nullable=False)

    # K8s CronJob
    cronjob_name = Column(String(255), nullable=True)
    enabled = Column(Boolean, default=True)

    # Execution tracking
    last_run = Column(DateTime, nullable=True)
    last_result = Column(Text, nullable=True)
    last_status = Column(String(20), nullable=True)  # success | failed | timeout

    # Limits
    timeout_seconds = Column(Integer, default=120)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    agent = relationship("Agent", back_populates="cron_jobs")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "agent_id": str(self.agent_id),
            "cron_expr": self.cron_expr,
            "timezone": self.timezone,
            "session_id": self.session_id,
            "prompt": self.prompt,
            "cronjob_name": self.cronjob_name,
            "enabled": self.enabled,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_result": self.last_result,
            "last_status": self.last_status,
            "timeout_seconds": self.timeout_seconds,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
