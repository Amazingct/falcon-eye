"""Chat session and message models"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, DateTime, Text, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.models.camera import Base

MEDIA_ROLES = {"assistant_media", "user_media"}


class ChatSession(Base):
    """Chat session model - groups messages into conversations"""
    __tablename__ = "chat_sessions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=True)  # Auto-generated or user-set
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to messages
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at")
    
    def to_dict(self, include_messages: bool = False, message_count: int = None) -> dict:
        """Convert to dict. Pass message_count separately to avoid lazy loading issues in async."""
        result = {
            "id": str(self.id),
            "name": self.name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        # Only include message_count if explicitly provided (avoids lazy load in async)
        if message_count is not None:
            result["message_count"] = message_count
        if include_messages:
            result["messages"] = [m.to_dict() for m in self.messages]
            result["message_count"] = len(self.messages)
        return result


class ChatMessage(Base):
    """Chat message model"""
    __tablename__ = "chat_messages"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user | assistant | assistant_media | user_media
    # Legacy text payload (kept for backwards compatibility; always non-null)
    content = Column(Text, nullable=False, default="")

    # New typed content (preferred)
    content_type = Column(String(20), nullable=True, default="text")  # text | media
    content_text = Column(Text, nullable=True)
    content_media = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship to session
    session = relationship("ChatSession", back_populates="messages")
    
    def content_for_api(self):
        if self.content_type == "media" or self.role in MEDIA_ROLES:
            return self.content_media or {}
        return self.content_text if self.content_text is not None else (self.content or "")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id),
            "role": self.role,
            "content": self.content_for_api(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
