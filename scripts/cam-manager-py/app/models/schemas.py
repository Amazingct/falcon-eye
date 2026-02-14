"""Pydantic schemas for API request/response validation"""
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field
from typing import Optional, Any
from enum import Enum


class CameraProtocol(str, Enum):
    USB = "usb"
    RTSP = "rtsp"
    ONVIF = "onvif"
    HTTP = "http"


class CameraStatus(str, Enum):
    PENDING = "pending"
    CREATING = "creating"
    RUNNING = "running"
    ERROR = "error"
    STOPPED = "stopped"


class CameraCreate(BaseModel):
    """Schema for creating a new camera"""
    name: str = Field(..., min_length=1, max_length=255, description="Camera name")
    protocol: CameraProtocol = Field(..., description="Camera protocol (usb, rtsp, onvif, http)")
    location: Optional[str] = Field(None, max_length=255, description="Physical location")
    source_url: Optional[str] = Field(None, description="URL for rtsp/onvif/http cameras")
    device_path: Optional[str] = Field("/dev/video0", description="Device path for USB cameras")
    node_name: Optional[str] = Field(None, description="K8s node for USB cameras")
    resolution: Optional[str] = Field("640x480", description="Video resolution")
    framerate: Optional[int] = Field(15, ge=1, le=60, description="Frames per second")
    metadata: Optional[dict[str, Any]] = Field(default_factory=dict, description="Custom metadata")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "office-cam",
                "protocol": "usb",
                "location": "Office",
                "device_path": "/dev/video0",
                "node_name": "ace",
                "resolution": "640x480",
                "framerate": 15,
                "metadata": {"model": "Logitech C920"}
            }
        }


class CameraUpdate(BaseModel):
    """Schema for updating a camera"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    location: Optional[str] = Field(None, max_length=255)
    source_url: Optional[str] = Field(None, description="Stream URL for network cameras")
    resolution: Optional[str] = None
    framerate: Optional[int] = Field(None, ge=1, le=60)
    metadata: Optional[dict[str, Any]] = None


class K8sStatus(BaseModel):
    """Kubernetes deployment status"""
    ready: bool
    replicas: int
    ready_replicas: int
    available_replicas: int


class CameraResponse(BaseModel):
    """Schema for camera response"""
    id: UUID
    name: str
    protocol: str
    location: Optional[str]
    source_url: Optional[str]
    device_path: Optional[str]
    node_name: Optional[str]
    deployment_name: Optional[str]
    service_name: Optional[str]
    stream_port: Optional[int]
    control_port: Optional[int]
    status: str
    resolution: str
    framerate: int
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    stream_url: Optional[str] = None
    control_url: Optional[str] = None
    k8s_status: Optional[K8sStatus] = None

    class Config:
        from_attributes = True


class CameraListResponse(BaseModel):
    """Schema for camera list response"""
    cameras: list[CameraResponse]
    total: int


class StreamInfo(BaseModel):
    """Stream info response"""
    id: UUID
    name: str
    stream_url: Optional[str]
    control_url: Optional[str]
    protocol: str
    status: str


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    timestamp: datetime


class MessageResponse(BaseModel):
    """Generic message response"""
    message: str
    id: Optional[UUID] = None
    deployment_name: Optional[str] = None
    service_name: Optional[str] = None
    stream_port: Optional[int] = None


class ErrorResponse(BaseModel):
    """Error response"""
    error: str
    detail: Optional[str] = None
