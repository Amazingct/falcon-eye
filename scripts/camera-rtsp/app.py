"""
Falcon-Eye RTSP/ONVIF Camera Relay
Converts RTSP streams to MJPEG for web viewing
"""
import os
import re
import subprocess
from flask import Flask, Response

app = Flask(__name__)

# Configuration from environment
RTSP_URL = os.getenv("RTSP_URL", "")
WIDTH = os.getenv("WIDTH", "640")
HEIGHT = os.getenv("HEIGHT", "480")
FPS = os.getenv("FPS", "15")
CAMERA_LABEL = os.getenv("CAMERA_LABEL", "CAMERA")


def get_rtsp_from_onvif(onvif_url: str) -> str:
    """Extract RTSP URL from ONVIF camera"""
    try:
        from onvif import ONVIFCamera
        
        match = re.match(r'onvif://(?:([^:]+):([^@]+)@)?([^:/]+)(?::(\d+))?', onvif_url)
        if not match:
            return None
        
        user, passwd, host, port = match.groups()
        port = int(port) if port else 80
        
        cam = ONVIFCamera(host, port, user or 'admin', passwd or 'admin')
        media = cam.create_media_service()
        profiles = media.GetProfiles()
        stream_uri = media.GetStreamUri({
            'StreamSetup': {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}},
            'ProfileToken': profiles[0].token
        })
        return stream_uri.Uri
    except Exception as e:
        print(f'ONVIF error: {e}')
        return None


def get_stream_url() -> str:
    """Get the actual stream URL (resolve ONVIF if needed)"""
    url = RTSP_URL
    if url.startswith('onvif://'):
        url = get_rtsp_from_onvif(url)
    return url


def gen_frames():
    """Generate MJPEG frames from RTSP stream with proper multipart boundaries"""
    url = get_stream_url()
    if not url:
        print("No stream URL available")
        return
    
    cmd = [
        'ffmpeg',
        '-rtsp_transport', 'tcp',
        '-i', url,
        '-f', 'image2pipe',
        '-vcodec', 'mjpeg',
        '-q:v', '5',
        '-r', FPS,
        '-s', f'{WIDTH}x{HEIGHT}',
        'pipe:1'
    ]
    
    print(f"Starting FFmpeg: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    
    buf = b''
    JPEG_START = b'\xff\xd8'
    JPEG_END = b'\xff\xd9'
    
    try:
        while True:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            
            while True:
                start = buf.find(JPEG_START)
                if start == -1:
                    buf = b''
                    break
                end = buf.find(JPEG_END, start)
                if end == -1:
                    buf = buf[start:]
                    break
                
                frame = buf[start:end + 2]
                buf = buf[end + 2:]
                
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
    except GeneratorExit:
        pass
    finally:
        proc.kill()
        proc.wait()


@app.route('/')
@app.route('/stream')
def stream():
    """MJPEG stream endpoint (served at both / and /stream)"""
    return Response(
        gen_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@app.route('/health')
def health():
    """Health check"""
    return {'status': 'ok', 'camera': CAMERA_LABEL}


if __name__ == '__main__':
    print(f"Starting Falcon-Eye RTSP Relay for {CAMERA_LABEL}")
    print(f"Stream URL: {RTSP_URL}")
    print(f"Resolution: {WIDTH}x{HEIGHT} @ {FPS}fps")
    app.run(host='0.0.0.0', port=8081, threaded=True)
