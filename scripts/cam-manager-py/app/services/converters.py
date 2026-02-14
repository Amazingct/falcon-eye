"""Protocol converters - generate container specs for different camera protocols"""
import os
from app.models.camera import Camera

# Pre-built images (set via env or use defaults)
CAMERA_USB_IMAGE = os.getenv("CAMERA_USB_IMAGE", "ghcr.io/amazingct/falcon-eye-camera-usb:latest")
CAMERA_RTSP_IMAGE = os.getenv("CAMERA_RTSP_IMAGE", "ghcr.io/amazingct/falcon-eye-camera-rtsp:latest")


def get_container_spec(camera: Camera) -> dict:
    """Get container specification based on camera protocol"""
    protocol = camera.protocol.lower()
    
    if protocol == "usb":
        return get_usb_container(camera)
    elif protocol == "rtsp":
        return get_rtsp_container(camera)
    elif protocol == "onvif":
        return get_onvif_container(camera)
    elif protocol == "http":
        return get_http_container(camera)
    else:
        raise ValueError(f"Unsupported protocol: {protocol}")


def get_usb_container(camera: Camera) -> dict:
    """Generate container spec for USB camera using pre-built Motion image"""
    width, height = (camera.resolution or "640x480").split("x")
    fps = camera.framerate or 15
    label = camera.name.upper().replace(" ", "-")
    device_path = camera.device_path or "/dev/video0"
    
    # Generate motion.conf at runtime via command
    config_script = f'''
cat > /etc/motion/motion.conf << 'CONF'
daemon off
videodevice {device_path}
width {width}
height {height}
framerate {fps}
stream_port 8081
stream_localhost off
stream_maxrate {fps}
stream_quality 70
webcontrol_port 8080
webcontrol_localhost off
picture_output off
movie_output off
text_left FALCON-EYE-{label}
text_right %Y-%m-%d\\n%T
CONF
exec motion -c /etc/motion/motion.conf
'''
    
    return {
        "name": "motion",
        "image": CAMERA_USB_IMAGE,
        "imagePullPolicy": "Always",
        "command": ["/bin/bash", "-c"],
        "args": [config_script],
        "securityContext": {"privileged": True},
        "ports": [
            {"containerPort": 8081, "name": "stream"},
            {"containerPort": 8080, "name": "control"},
        ],
        "volumeMounts": [{
            "name": "dev-video",
            "mountPath": device_path,
        }],
        "resources": {
            "requests": {"memory": "128Mi", "cpu": "100m"},
            "limits": {"memory": "512Mi", "cpu": "500m"},
        },
    }


def get_rtsp_container(camera: Camera) -> dict:
    """Generate container spec for RTSP camera using pre-built image"""
    width, height = (camera.resolution or "640x480").split("x")
    fps = camera.framerate or 15
    label = camera.name.upper().replace(" ", "-")
    rtsp_url = camera.source_url
    
    return {
        "name": "rtsp-relay",
        "image": CAMERA_RTSP_IMAGE,
        "imagePullPolicy": "Always",
        "env": [
            {"name": "RTSP_URL", "value": rtsp_url},
            {"name": "WIDTH", "value": str(width)},
            {"name": "HEIGHT", "value": str(height)},
            {"name": "FPS", "value": str(fps)},
            {"name": "CAMERA_LABEL", "value": label},
        ],
        "ports": [{"containerPort": 8081, "name": "stream"}],
        "resources": {
            "requests": {"memory": "128Mi", "cpu": "100m"},
            "limits": {"memory": "512Mi", "cpu": "500m"},
        },
    }


def get_onvif_container(camera: Camera) -> dict:
    """Generate container spec for ONVIF camera using pre-built image (same as RTSP with ONVIF support)"""
    width, height = (camera.resolution or "640x480").split("x")
    fps = camera.framerate or 15
    label = camera.name.upper().replace(" ", "-")
    onvif_url = camera.source_url  # Format: onvif://user:pass@host:port
    
    return {
        "name": "onvif-relay",
        "image": CAMERA_RTSP_IMAGE,  # Same image, supports ONVIF URLs
        "imagePullPolicy": "Always",
        "env": [
            {"name": "RTSP_URL", "value": onvif_url},  # Will be converted to RTSP by app.py
            {"name": "WIDTH", "value": str(width)},
            {"name": "HEIGHT", "value": str(height)},
            {"name": "FPS", "value": str(fps)},
            {"name": "CAMERA_LABEL", "value": label},
        ],
        "ports": [{"containerPort": 8081, "name": "stream"}],
        "resources": {
            "requests": {"memory": "128Mi", "cpu": "100m"},
            "limits": {"memory": "512Mi", "cpu": "500m"},
        },
    }


def get_http_container(camera: Camera) -> dict:
    """Generate container spec for HTTP/MJPEG camera using pre-built image"""
    label = camera.name.upper().replace(" ", "-")
    http_url = camera.source_url
    
    return {
        "name": "http-relay",
        "image": CAMERA_RTSP_IMAGE,  # Same image, works for HTTP streams too
        "imagePullPolicy": "Always",
        "env": [
            {"name": "RTSP_URL", "value": http_url},  # HTTP URLs work too
            {"name": "WIDTH", "value": "640"},
            {"name": "HEIGHT", "value": "480"},
            {"name": "FPS", "value": "15"},
            {"name": "CAMERA_LABEL", "value": label},
        ],
        "ports": [{"containerPort": 8081, "name": "stream"}],
        "resources": {
            "requests": {"memory": "64Mi", "cpu": "50m"},
            "limits": {"memory": "256Mi", "cpu": "250m"},
        },
    }
