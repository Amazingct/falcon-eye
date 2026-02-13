"""Camera database models"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Integer, DateTime, JSON, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
import enum

Base = declarative_base()


class CameraProtocol(str, enum.Enum):
    USB = "usb"
    RTSP = "rtsp"
    ONVIF = "onvif"
    HTTP = "http"


class CameraStatus(str, enum.Enum):
    PENDING = "pending"
    CREATING = "creating"
    RUNNING = "running"
    ERROR = "error"
    STOPPED = "stopped"


class Camera(Base):
    """Camera model"""
    __tablename__ = "cameras"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False, index=True)
    protocol = Column(String(50), nullable=False, index=True)
    location = Column(String(255), nullable=True)
    source_url = Column(String, nullable=True)
    device_path = Column(String(255), nullable=True)
    node_name = Column(String(255), nullable=True, index=True)
    deployment_name = Column(String(255), nullable=True)
    service_name = Column(String(255), nullable=True)
    stream_port = Column(Integer, nullable=True)
    control_port = Column(Integer, nullable=True)
    status = Column(String(50), default=CameraStatus.PENDING.value, index=True)
    resolution = Column(String(20), default="640x480")
    framerate = Column(Integer, default=15)
    metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "id": str(self.id),
            "name": self.name,
            "protocol": self.protocol,
            "location": self.location,
            "source_url": self.source_url,
            "device_path": self.device_path,
            "node_name": self.node_name,
            "deployment_name": self.deployment_name,
            "service_name": self.service_name,
            "stream_port": self.stream_port,
            "control_port": self.control_port,
            "status": self.status,
            "resolution": self.resolution,
            "framerate": self.framerate,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
