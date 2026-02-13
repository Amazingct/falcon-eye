# Falcon-Eye Camera Manager 🎥

REST API for managing cameras in the Falcon-Eye system.

## Features

- **Multi-protocol support**: USB, RTSP, ONVIF, HTTP cameras
- **Unified output**: All cameras output HTTP(S) MJPEG streams
- **Kubernetes native**: Each camera runs as a separate deployment
- **PostgreSQL storage**: Camera configs, metadata, and status

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | API info and available endpoints |
| GET | `/health` | Health check |
| GET | `/api/cameras` | List all cameras |
| GET | `/api/cameras/:id` | Get camera details |
| POST | `/api/cameras` | Add new camera |
| PATCH | `/api/cameras/:id` | Update camera metadata |
| DELETE | `/api/cameras/:id` | Delete camera and its deployment |
| POST | `/api/cameras/:id/restart` | Restart camera deployment |
| GET | `/api/cameras/:id/stream-info` | Get stream URLs |

## Adding Cameras

### USB Camera
```bash
curl -X POST http://192.168.1.207:30800/api/cameras \
  -H "Content-Type: application/json" \
  -d '{
    "name": "office-cam",
    "protocol": "usb",
    "location": "Office",
    "device_path": "/dev/video0",
    "node_name": "ace",
    "resolution": "640x480",
    "framerate": 15,
    "metadata": {"model": "Logitech C920"}
  }'
```

### RTSP Camera
```bash
curl -X POST http://192.168.1.207:30800/api/cameras \
  -H "Content-Type: application/json" \
  -d '{
    "name": "parking-cam",
    "protocol": "rtsp",
    "location": "Parking Lot",
    "source_url": "rtsp://admin:password@192.168.1.100:554/stream1",
    "resolution": "1280x720",
    "framerate": 10
  }'
```

### ONVIF Camera
```bash
curl -X POST http://192.168.1.207:30800/api/cameras \
  -H "Content-Type: application/json" \
  -d '{
    "name": "entrance-cam",
    "protocol": "onvif",
    "location": "Main Entrance",
    "source_url": "onvif://admin:password@192.168.1.101:80",
    "resolution": "1920x1080",
    "framerate": 15
  }'
```

### HTTP/MJPEG Camera
```bash
curl -X POST http://192.168.1.207:30800/api/cameras \
  -H "Content-Type: application/json" \
  -d '{
    "name": "esp32-cam",
    "protocol": "http",
    "location": "Garden",
    "source_url": "http://192.168.1.150:81/stream"
  }'
```

## Query Filters

```bash
# Filter by protocol
GET /api/cameras?protocol=usb

# Filter by status
GET /api/cameras?status=running

# Filter by node
GET /api/cameras?node=ace
```

## Camera Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| name | string | Yes | Camera name (used in deployment name) |
| protocol | string | Yes | usb, rtsp, onvif, or http |
| location | string | No | Physical location description |
| source_url | string | Conditional | URL for rtsp/onvif/http cameras |
| device_path | string | No | Device path for USB cameras (default: /dev/video0) |
| node_name | string | Conditional | K8s node for USB cameras (ace, falcon) |
| resolution | string | No | Video resolution (default: 640x480) |
| framerate | integer | No | FPS (default: 15) |
| metadata | object | No | Custom metadata (JSON) |

## Response Fields

After creation, cameras include:

| Field | Description |
|-------|-------------|
| id | UUID |
| deployment_name | K8s deployment name |
| service_name | K8s service name |
| stream_port | NodePort for MJPEG stream |
| control_port | NodePort for control (USB only) |
| stream_url | Full URL to access stream |
| status | pending, creating, running, error |

## Deployment

```bash
# Deploy cam-manager to cluster
kubectl apply -f k8s/cam-manager.yaml

# Check status
kubectl get pods -n falcon-eye -l component=manager

# View logs
kubectl logs -n falcon-eye -l component=manager -f
```

## Local Development

```bash
cd /media/falcon/external/falcon-eye/scripts/cam-manager

# Install dependencies
npm install

# Set environment variables
export DB_HOST=192.168.1.207
export DB_PORT=30432
export DB_USER=admin
export DB_PASSWORD=amazingct
export DB_NAME=homedb

# Run
npm start
# or with auto-reload
npm run dev
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    falcon-eye namespace                      │
│                                                              │
│  ┌──────────────────┐      ┌──────────────────┐            │
│  │   cam-manager    │─────▶│    PostgreSQL    │            │
│  │   (API Server)   │      │    (ace-db ns)   │            │
│  └────────┬─────────┘      └──────────────────┘            │
│           │                                                  │
│           │ creates/deletes                                  │
│           ▼                                                  │
│  ┌──────────────────┐  ┌──────────────────┐                │
│  │   cam-office     │  │   cam-parking    │  ...           │
│  │   (USB/Motion)   │  │   (RTSP/FFmpeg)  │                │
│  └──────────────────┘  └──────────────────┘                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Protocol Support

| Protocol | Input | Output | Container |
|----------|-------|--------|-----------|
| USB | /dev/videoX | MJPEG HTTP | Motion |
| RTSP | rtsp://... | MJPEG HTTP | FFmpeg+Flask |
| ONVIF | onvif://... | MJPEG HTTP | onvif-zeep+FFmpeg |
| HTTP | http://... | MJPEG HTTP | Flask proxy |

## Created

February 13, 2026 by Falcon 🦅
