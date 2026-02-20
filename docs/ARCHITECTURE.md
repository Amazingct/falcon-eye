# Architecture

## High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Kubernetes Cluster                           │
│  Namespace: falcon-eye                                              │
│                                                                     │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐  │
│  │  Dashboard    │    │   API Server     │    │   PostgreSQL     │  │
│  │  (React SPA)  │───▶│   (FastAPI)      │───▶│   (postgres:15)  │  │
│  │  nginx:80     │    │   :8000          │    │   :5432          │  │
│  │  NodePort     │    │   NodePort       │    │   ClusterIP      │  │
│  │  30900        │    │   30901          │    │                  │  │
│  └──────────────┘    └────────┬─────────┘    └──────────────────┘  │
│                               │                                     │
│              ┌────────────────┼────────────────┐                   │
│              │                │                 │                   │
│              ▼                ▼                  ▼                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐     │
│  │ Camera Pod   │  │ Camera Pod   │  │ Cleanup CronJob      │     │
│  │ (USB/Motion) │  │ (RTSP/FFmpeg)│  │ (every 2 min)        │     │
│  │ :8081 stream │  │ :8081 stream │  │ Removes orphan pods  │     │
│  │ :8080 ctrl   │  │              │  │ Fixes stale recordings│     │
│  │ NodePort     │  │ NodePort     │  └──────────────────────┘     │
│  │ (30902-30999)│  │ (30902-30999)│                                │
│  └──────┬───────┘  └──────┬───────┘                                │
│         │                  │                                        │
│         ▼                  ▼                                        │
│  ┌──────────────┐  ┌──────────────┐                                │
│  │ Recorder Pod │  │ Recorder Pod │                                │
│  │ (FFmpeg)     │  │ (FFmpeg)     │                                │
│  │ :8080 API    │  │ :8080 API    │                                │
│  │ ClusterIP    │  │ ClusterIP    │                                │
│  │ hostPath:    │  │ hostPath:    │                                │
│  │ /data/falcon │  │ /data/falcon │                                │
│  │ -eye/record  │  │ -eye/record  │                                │
│  └──────────────┘  └──────────────┘                                │
└─────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Dashboard (falcon-eye-dashboard)

- **Image**: `ghcr.io/amazingct/falcon-eye-dashboard:latest`
- **Technology**: React SPA built with Vite, styled with Tailwind CSS
- **Served by**: nginx (Alpine) on port 80
- **NodePort**: 30900
- **Function**: Web UI for managing cameras, viewing live streams, managing recordings, AI chat
- **API proxy**: nginx proxies `/api/*` requests to the API server (ClusterIP), so the browser never contacts the API directly

### 2. API Server (falcon-eye-api)

- **Image**: `ghcr.io/amazingct/falcon-eye-api:latest`
- **Technology**: Python FastAPI with async SQLAlchemy
- **Port**: 8000, NodePort 30901
- **Function**: REST API for camera CRUD, K8s deployment orchestration, recording management, node scanning, settings, AI chatbot
- **RBAC**: Uses `falcon-eye-sa` ServiceAccount with cluster-wide permissions on pods, deployments, services, configmaps, secrets, nodes, cronjobs, and jobs
- **Recordings volume**: hostPath mount at `/data/falcon-eye/recordings`

### 3. PostgreSQL

- **Image**: `postgres:15-alpine`
- **Port**: 5432 (ClusterIP only — internal)
- **Storage**: 1Gi PVC
- **Credentials**: `falcon` / `falcon-eye-2026` / database `falconeye`
- **Tables**: `cameras`, `recordings`, `chat_sessions`, `chat_messages`

### 4. Camera Relay Pods

Each camera gets its own Deployment + NodePort Service. Two types:

#### USB Camera (Motion-based)
- **Image**: `ghcr.io/amazingct/falcon-eye-camera-usb:latest`
- **Base**: Ubuntu 22.04 with Motion
- **Ports**: 8081 (MJPEG stream), 8080 (Motion web control)
- **Requires**: `privileged: true` security context, hostPath volume for `/dev/videoX`
- **Must** run on the specific node where the USB device is attached (nodeSelector)

#### RTSP/ONVIF/HTTP Camera (FFmpeg-based)
- **Image**: `ghcr.io/amazingct/falcon-eye-camera-rtsp:latest`
- **Base**: Python 3.11-slim with FFmpeg + Flask
- **Port**: 8081 (MJPEG stream converted from RTSP via FFmpeg)
- **Stream endpoints**: Serves MJPEG at both `/` and `/stream` with proper multipart boundary framing (`--frame\r\n`)
- **ONVIF**: Resolves ONVIF URLs to RTSP using `onvif-zeep` library
- **Can** run on any node (uses default camera node if configured)

### 5. Recorder Pods

Each camera gets a paired recorder Deployment + ClusterIP Service:

- **Image**: `ghcr.io/amazingct/falcon-eye-recorder:latest`
- **Technology**: Python FastAPI wrapping FFmpeg
- **Port**: 8080 (ClusterIP — only API server communicates with it)
- **Recording behavior**:
  - USB cameras (MJPEG source): re-encodes to H.264 MP4 with `libx264 ultrafast`
  - RTSP cameras: copies video stream as-is (`-c:v copy`) and transcodes audio to AAC (`-c:a aac -b:a 64k`). This handles cameras (e.g., Tuya devices) that output incompatible audio codecs like `pcm_mulaw` which MP4 containers don't support
- **Storage**: hostPath at `/data/falcon-eye/recordings/{camera_id}/`
- **Reports** to the API server when recordings start/stop/fail

### 6. Cleanup CronJob (falcon-eye-cleanup)

- **Image**: Same as API (`ghcr.io/amazingct/falcon-eye-api:latest`)
- **Command**: `python -m app.tasks.cleanup`
- **Schedule**: Every 2 minutes (configurable via `CLEANUP_INTERVAL`)
- **Actions**:
  1. Fixes orphaned recordings (status stuck at "recording" but recorder pod is gone)
  2. Deletes stale camera deployments/services not registered in the database
  3. Deletes stale recorder deployments/services for cameras no longer in the database

## Data Flow

### Live Streaming

```
Physical Camera
    │
    ▼
Camera Relay Pod (Motion or FFmpeg)
    │ Converts to MJPEG
    ▼
NodePort Service (30902-30999)
    │
    ▼
Browser <img src="http://<node-ip>:<nodeport>">
```

The dashboard displays camera streams by pointing `<img>` tags directly at the camera relay pod's NodePort. The MJPEG stream is `multipart/x-mixed-replace` — natively supported by browsers.

### Recording

```
Camera Source (MJPEG or RTSP)
    │
    ▼
Recorder Pod (FFmpeg)
    │ Records to MP4
    ▼
hostPath: /data/falcon-eye/recordings/{camera_id}/
    │
    ▼
API Server serves file via /api/recordings/{id}/download
```

- For **USB cameras**: recorder reads the MJPEG stream from the camera relay's ClusterIP service and re-encodes to H.264
- For **RTSP cameras**: recorder reads directly from the camera's source RTSP URL (better quality, no double-encoding) and copies the video stream

## Kubernetes Resource Model

### Labels

All resources use consistent labels:

| Label | Values | Purpose |
|-------|--------|---------|
| `app` | `falcon-eye` | Identifies all Falcon-Eye resources |
| `component` | `camera`, `recorder`, `cleanup` | Component type |
| `camera-id` | UUID | Links camera pods/services to DB record |
| `recorder-for` | UUID | Links recorder pods/services to camera |
| `protocol` | `usb`, `rtsp`, `onvif`, `http` | Camera protocol type |

### Naming Convention

| Resource | Pattern | Example |
|----------|---------|---------|
| Camera Deployment | `cam-{name-slug}` | `cam-office-cam` |
| Camera Service | `svc-{name-slug}` | `svc-office-cam` |
| Recorder Deployment | `rec-{name-slug}` | `rec-office-cam` |
| Recorder Service | `svc-rec-{name-slug}` | `svc-rec-office-cam` |

### Port Allocation

| Service | Port | Type |
|---------|------|------|
| Dashboard | 30900 | NodePort |
| API Server | 30901 | NodePort |
| Camera streams | 30902–30999 | NodePort (auto-assigned by K8s) |
| PostgreSQL | 5432 | ClusterIP |
| Recorder pods | 8080 | ClusterIP |

Camera services request NodePort without specifying a number — Kubernetes auto-assigns from the 30000–32767 range. The config defines `stream_port_start: 30900` and `stream_port_end: 30999` as a logical range tracked in the application.

### RBAC

| Resource | Name |
|----------|------|
| ServiceAccount | `falcon-eye-sa` |
| ClusterRole | `falcon-eye-role` |
| ClusterRoleBinding | `falcon-eye-binding` |

Permissions: full CRUD on pods, services, configmaps, secrets, deployments, cronjobs, jobs; read on nodes.

## Node IP Auto-Discovery

The API server **auto-discovers node IP addresses** by querying the Kubernetes API for each node's `InternalIP` address. Results are cached with a 5-minute TTL for performance. Stream URLs (e.g., `http://<node-ip>:<nodeport>`) are built dynamically — no hardcoded IP mappings are needed.

## Node Selection Logic

1. **USB cameras**: **Must** be pinned to the node where the USB device is physically connected (`nodeSelector: kubernetes.io/hostname`)
2. **Network cameras**: Use `DEFAULT_CAMERA_NODE` if configured, otherwise auto-assigned by the Kubernetes scheduler
3. **Recorders**: Follow the camera's node if set, otherwise use `DEFAULT_RECORDER_NODE`, otherwise auto-assigned

### Jetson Node Tolerations

Nodes listed in `JETSON_NODES` (configurable via environment variable, defaults to empty `[]`) are assumed to have a taint:

```yaml
tolerations:
  - key: dedicated
    operator: Equal
    value: jetson
    effect: NoSchedule
```

When a camera or recorder is scheduled to a Jetson node, this toleration is automatically added to the pod spec.
