"""Settings database model — single source of truth for runtime config."""
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime

from app.models.camera import Base


class Setting(Base):
    """Key-value settings stored in postgres."""
    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Setting {self.key}={self.value!r}>"


# Default settings — used to seed the table on first boot
DEFAULTS = {
    # General
    "DEFAULT_RESOLUTION": "640x480",
    "DEFAULT_FRAMERATE": "15",
    "DEFAULT_CAMERA_NODE": "",
    "DEFAULT_RECORDER_NODE": "",
    "CLEANUP_INTERVAL": "*/2 * * * *",
    "CREATING_TIMEOUT_MINUTES": "15",
    "RECORDING_CHUNK_MINUTES": "15",

    # Cloud storage
    "CLOUD_STORAGE_ENABLED": "false",
    "CLOUD_STORAGE_PROVIDER": "spaces",
    "CLOUD_STORAGE_ACCESS_KEY": "",
    "CLOUD_STORAGE_SECRET_KEY": "",
    "CLOUD_STORAGE_BUCKET": "",
    "CLOUD_STORAGE_REGION": "",
    "CLOUD_STORAGE_ENDPOINT": "",
    "CLOUD_DELETE_LOCAL": "true",

    # API keys
    "ANTHROPIC_API_KEY": "",
    "OPENAI_API_KEY": "",

    # Chatbot
    "CHATBOT_TOOLS": "",
}
