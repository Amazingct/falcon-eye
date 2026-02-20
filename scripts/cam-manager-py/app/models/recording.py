"""Recording model for video recordings"""
from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, Enum as SQLEnum, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
import uuid

from app.models.camera import Base


class RecordingStatus(str, enum.Enum):
    """Recording status enum"""
    RECORDING = "recording"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"
    ERROR = "error"


class Recording(Base):
    """Recording model - tracks video recordings for cameras"""
    __tablename__ = "recordings"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    camera_id = Column(UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True)
    camera_name = Column(String, nullable=True)  # Preserved camera name (for when camera is deleted)
    file_path = Column(String, nullable=False)  # Path to video file
    file_name = Column(String, nullable=False)  # Just the filename
    start_time = Column(DateTime, nullable=False, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)  # Null while recording
    duration_seconds = Column(Integer, nullable=True)  # Calculated on completion
    file_size_bytes = Column(Integer, nullable=True)  # File size
    status = Column(SQLEnum(RecordingStatus), default=RecordingStatus.RECORDING)
    error_message = Column(String, nullable=True)
    node_name = Column(String, nullable=True)  # K8s node where the recording was stored
    camera_deleted = Column(Boolean, default=False, nullable=False)  # True if associated camera was deleted
    
    # Relationship to camera (nullable - camera may be deleted)
    camera = relationship("Camera", back_populates="recordings")

    def to_dict(self):
        return {
            "id": self.id,
            "camera_id": str(self.camera_id) if self.camera_id else None,
            "camera_name": self.camera_name,
            "file_path": self.file_path,
            "file_name": self.file_name,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "file_size_bytes": self.file_size_bytes,
            "status": self.status.value if self.status else None,
            "error_message": self.error_message,
            "node_name": self.node_name,
            "camera_deleted": self.camera_deleted,
        }
