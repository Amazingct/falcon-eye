"""Recording model for video recordings"""
from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, Enum as SQLEnum
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
    camera_id = Column(UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path = Column(String, nullable=False)  # Path to video file
    file_name = Column(String, nullable=False)  # Just the filename
    start_time = Column(DateTime, nullable=False, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)  # Null while recording
    duration_seconds = Column(Integer, nullable=True)  # Calculated on completion
    file_size_bytes = Column(Integer, nullable=True)  # File size
    status = Column(SQLEnum(RecordingStatus), default=RecordingStatus.RECORDING)
    error_message = Column(String, nullable=True)
    
    # Relationship to camera
    camera = relationship("Camera", back_populates="recordings")

    def to_dict(self):
        return {
            "id": self.id,
            "camera_id": str(self.camera_id) if self.camera_id else None,
            "file_path": self.file_path,
            "file_name": self.file_name,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "file_size_bytes": self.file_size_bytes,
            "status": self.status.value if self.status else None,
            "error_message": self.error_message,
        }
