"""Protocol converters - generate container specs for different camera protocols"""
from app.models.camera import Camera


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
    """Generate container spec for USB camera using Motion"""
    width, height = (camera.resolution or "640x480").split("x")
    fps = camera.framerate or 15
    label = camera.name.upper().replace(" ", "-")
    device_path = camera.device_path or "/dev/video0"
    
    script = f'''
apt-get update && apt-get install -y motion && \\
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
motion -c /etc/motion/motion.conf
'''
    
    return {
        "name": "motion",
        "image": "ubuntu:22.04",
        "command": ["/bin/bash", "-c"],
        "args": [script],
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
    """Generate container spec for RTSP camera"""
    width, height = (camera.resolution or "640x480").split("x")
    fps = camera.framerate or 15
    label = camera.name.upper().replace(" ", "-")
    rtsp_url = camera.source_url
    
    script = f'''
apt-get update && apt-get install -y ffmpeg python3 python3-pip && \\
pip3 install flask && \\
cat > /app.py << 'PYEOF'
from flask import Flask, Response
import subprocess

app = Flask(__name__)

def gen_frames():
    cmd = [
        'ffmpeg', '-rtsp_transport', 'tcp',
        '-i', '{rtsp_url}',
        '-f', 'mjpeg', '-q:v', '5',
        '-r', '{fps}', '-s', '{width}x{height}',
        'pipe:1'
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        while True:
            data = proc.stdout.read(4096)
            if not data:
                break
            yield (b'--frame\\r\\nContent-Type: image/jpeg\\r\\n\\r\\n' + data + b'\\r\\n')
    finally:
        proc.kill()

@app.route('/')
def index():
    return '<html><body><h1>FALCON-EYE-{label}</h1><img src="/stream"></body></html>'

@app.route('/stream')
def stream():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081, threaded=True)
PYEOF
python3 /app.py
'''
    
    return {
        "name": "rtsp-relay",
        "image": "ubuntu:22.04",
        "command": ["/bin/bash", "-c"],
        "args": [script],
        "ports": [{"containerPort": 8081, "name": "stream"}],
        "resources": {
            "requests": {"memory": "128Mi", "cpu": "100m"},
            "limits": {"memory": "512Mi", "cpu": "500m"},
        },
    }


def get_onvif_container(camera: Camera) -> dict:
    """Generate container spec for ONVIF camera"""
    width, height = (camera.resolution or "640x480").split("x")
    fps = camera.framerate or 15
    label = camera.name.upper().replace(" ", "-")
    onvif_url = camera.source_url
    
    script = f'''
apt-get update && apt-get install -y ffmpeg python3 python3-pip && \\
pip3 install flask onvif-zeep && \\
cat > /app.py << 'PYEOF'
from flask import Flask, Response
from onvif import ONVIFCamera
import subprocess
import re

app = Flask(__name__)

def get_rtsp_url():
    match = re.match(r'onvif://(?:([^:]+):([^@]+)@)?([^:/]+)(?::(\\d+))?', '{onvif_url}')
    if not match:
        return None
    user, passwd, host, port = match.groups()
    port = int(port) if port else 80
    try:
        cam = ONVIFCamera(host, port, user or 'admin', passwd or 'admin')
        media = cam.create_media_service()
        profiles = media.GetProfiles()
        stream_uri = media.GetStreamUri({{
            'StreamSetup': {{'Stream': 'RTP-Unicast', 'Transport': {{'Protocol': 'RTSP'}}}},
            'ProfileToken': profiles[0].token
        }})
        return stream_uri.Uri
    except Exception as e:
        print(f'ONVIF error: {{e}}')
        return None

rtsp_url = get_rtsp_url()

def gen_frames():
    if not rtsp_url:
        return
    cmd = [
        'ffmpeg', '-rtsp_transport', 'tcp',
        '-i', rtsp_url,
        '-f', 'mjpeg', '-q:v', '5',
        '-r', '{fps}', '-s', '{width}x{height}',
        'pipe:1'
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        while True:
            data = proc.stdout.read(4096)
            if not data:
                break
            yield (b'--frame\\r\\nContent-Type: image/jpeg\\r\\n\\r\\n' + data + b'\\r\\n')
    finally:
        proc.kill()

@app.route('/')
def index():
    return '<html><body><h1>FALCON-EYE-{label}</h1><img src="/stream"></body></html>'

@app.route('/stream')
def stream():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081, threaded=True)
PYEOF
python3 /app.py
'''
    
    return {
        "name": "onvif-relay",
        "image": "ubuntu:22.04",
        "command": ["/bin/bash", "-c"],
        "args": [script],
        "ports": [{"containerPort": 8081, "name": "stream"}],
        "resources": {
            "requests": {"memory": "128Mi", "cpu": "100m"},
            "limits": {"memory": "512Mi", "cpu": "500m"},
        },
    }


def get_http_container(camera: Camera) -> dict:
    """Generate container spec for HTTP/MJPEG camera"""
    label = camera.name.upper().replace(" ", "-")
    http_url = camera.source_url
    
    script = f'''
apt-get update && apt-get install -y python3 python3-pip && \\
pip3 install flask requests && \\
cat > /app.py << 'PYEOF'
from flask import Flask, Response
import requests

app = Flask(__name__)

def gen_frames():
    try:
        r = requests.get('{http_url}', stream=True, timeout=30)
        for chunk in r.iter_content(chunk_size=4096):
            yield chunk
    except Exception as e:
        print(f'Stream error: {{e}}')

@app.route('/')
def index():
    return '<html><body><h1>FALCON-EYE-{label}</h1><img src="/stream"></body></html>'

@app.route('/stream')
def stream():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081, threaded=True)
PYEOF
python3 /app.py
'''
    
    return {
        "name": "http-relay",
        "image": "ubuntu:22.04",
        "command": ["/bin/bash", "-c"],
        "args": [script],
        "ports": [{"containerPort": 8081, "name": "stream"}],
        "resources": {
            "requests": {"memory": "64Mi", "cpu": "50m"},
            "limits": {"memory": "256Mi", "cpu": "250m"},
        },
    }
