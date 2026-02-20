# Code Reference

## Project Structure

```
falcon-eye/
├── install.sh                          # One-command installer/updater
├── .github/workflows/
│   └── build-push.yml                  # CI: build + push multi-arch images
│
├── scripts/
│   ├── cam-manager-py/                 # API Server (FastAPI)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── main.py                 # FastAPI app entry point
│   │       ├── config.py               # Pydantic settings from env vars
│   │       ├── database.py             # SQLAlchemy async engine + sessions
│   │       ├── models/
│   │       │   ├── camera.py           # Camera ORM model + enums
│   │       │   ├── recording.py        # Recording ORM model
│   │       │   ├── chat.py             # ChatSession + ChatMessage models
│   │       │   └── schemas.py          # Pydantic request/response schemas
│   │       ├── routes/
│   │       │   ├── cameras.py          # Camera CRUD + start/stop/restart + recording control
│   │       │   ├── recordings.py       # Recordings CRUD + download
│   │       │   ├── nodes.py            # Node listing + USB/network camera scanning
│   │       │   └── settings.py         # Settings CRUD + restart-all + clear-all
│   │       ├── services/
│   │       │   ├── k8s.py              # K8s deployment/service generation + CRUD
│   │       │   └── converters.py       # Protocol-specific container spec generators
│   │       ├── tasks/
│   │       │   └── cleanup.py          # CronJob: orphan cleanup + recording fix
│   │       └── chatbot/                # AI chatbot (Anthropic Claude)
│   │           ├── __init__.py
│   │           ├── router.py
│   │           └── tools.py
│   │
│   ├── camera-rtsp/                    # RTSP/ONVIF/HTTP relay image
│   │   ├── Dockerfile
│   │   ├── app.py                      # Flask app: FFmpeg → MJPEG conversion
│   │   └── entrypoint.sh
│   │
│   ├── camera-usb/                     # USB camera image
│   │   ├── Dockerfile
│   │   └── motion.conf                 # Default Motion config (overwritten at runtime)
│   │
│   └── recorder/                       # Recorder image
│       ├── Dockerfile
│       ├── requirements.txt
│       └── main.py                     # FastAPI app: FFmpeg recording control
│
└── frontend/                           # Dashboard (React SPA)
    ├── Dockerfile                      # Multi-stage: node build → nginx
    ├── nginx.conf.template             # nginx config with API proxy
    ├── package.json
    ├── vite.config.js
    ├── tailwind.config.js
    └── src/
        ├── main.jsx                    # React root
        ├── index.css                   # Tailwind imports + custom scrollbar
        └── App.jsx                     # Entire app (single-file SPA)
```

## Backend: API Server (`cam-manager-py`)

### Technology Stack

- **Framework**: FastAPI (async)
- **ORM**: SQLAlchemy 2.0 with asyncpg driver
- **Database**: PostgreSQL 15
- **K8s client**: official `kubernetes` Python client
- **Validation**: Pydantic v2 with `pydantic-settings`
- **HTTP client**: `httpx` (async, for communicating with recorder pods)
- **Server**: Uvicorn

### Entry Point (`main.py`)

- Creates FastAPI app with lifespan handler
- On startup: calls `init_db()` which runs `Base.metadata.create_all` (auto-creates tables)
- CORS middleware allows all origins
- Registers routers: cameras, nodes, recordings, settings, chatbot
- Global exception handler returns JSON errors

### Configuration (`config.py`)

Uses `pydantic-settings` to load from environment variables:

- `DATABASE_URL` → converted to `postgresql+asyncpg://` for async and plain `postgresql://` for sync
- K8s config: tries in-cluster config first, then kubeconfig file, then `~/.kube/config`
- Node IPs are **auto-discovered** by querying the K8s API for each node's `InternalIP` address, cached with a 5-minute TTL
- Defaults: 640×480 resolution, 15 fps, stream quality 70

### Database (`database.py`)

- **Async engine**: `create_async_engine` with `asyncpg`, pool size 10, overflow 20
- **Session factory**: `async_sessionmaker` with `expire_on_commit=False`
- **Dependency**: `get_db()` yields an `AsyncSession`, commits on success, rolls back on error
- **Context managers**: `get_db_context()` and `get_db_session()` for use in background tasks
- Tables are created automatically on startup (no migration tool needed)

### Models

#### `Camera` (`models/camera.py`)
- UUID primary key
- Fields: name, protocol, location, source_url, device_path, node_name, deployment_name, service_name, stream_port, control_port, status, resolution, framerate, extra_data (JSON), timestamps
- Statuses: `pending`, `creating`, `running`, `error`, `stopped`, `deleting`
- Protocols: `usb`, `rtsp`, `onvif`, `http`
- Relationship: `recordings` (one-to-many, cascade delete-orphan)

#### `Recording` (`models/recording.py`)
- String primary key (format: `{camera_id}_{timestamp}`)
- Foreign key to Camera with `SET NULL` on delete (recordings survive camera deletion)
- Fields: camera_id, camera_name (preserved), file_path, file_name, start_time, end_time, duration_seconds, file_size_bytes, status, error_message, camera_deleted flag
- Statuses: `recording`, `stopped`, `completed`, `failed`, `error`

#### `ChatSession` / `ChatMessage` (`models/chat.py`)
- Session: UUID PK, name, timestamps
- Message: UUID PK, session FK (cascade delete), role (user/assistant), content text, timestamp

### Routes

#### Cameras (`routes/cameras.py`)

The main CRUD router. Key behaviors:

- **List**: Syncs K8s pod status with DB on every list call. Detects stuck "creating" cameras (>3 min timeout) and auto-stops them.
- **Create**: USB cameras deploy immediately (Deployment + Service + Recorder). Network cameras are created in `stopped` state.
- **Update**: If `source_url` changes, auto-redeploys the camera pod. Updates `device_path` to extracted IP for network cameras.
- **Delete**: Background task — marks as `deleting`, deletes K8s resources, waits for pod termination (extra 15s grace for USB), marks recordings as orphaned, then deletes DB record.
- **Start/Stop/Restart**: Creates or deletes K8s resources accordingly.
- **Recording control**: Proxies to the recorder pod's API via internal ClusterIP service. Auto-deploys recorder if not present. Fixes orphaned recordings when recorder pod is gone.

Duplicate prevention: checks for existing cameras with same device_path (USB) or IP address (network).

#### Recordings (`routes/recordings.py`)

Standard CRUD. The `POST` and `PATCH` endpoints are called by the recorder service (not by users). `download` endpoint serves the MP4 file via `FileResponse`.

#### Nodes (`routes/nodes.py`)

- **List/Get**: Wraps K8s node API. Returns name, IP, ready status, taints, labels, architecture.
- **Scan**: SSH into each node using `paramiko` to enumerate `/dev/video*` devices. Network scan probes common camera ports (554, 8554, 80, 8080, 8899) across the subnet with socket connection tests.

#### Settings (`routes/settings.py`)

- **Get**: Reads from ConfigMap + environment. Includes chatbot configuration.
- **Update**: Writes to ConfigMap. API key stored in separate K8s Secret (`falcon-eye-secrets`). API key is validated against Anthropic's API before saving.
- **Restart All**: Patches all deployments with `restartedAt` annotation. Updates CronJob schedule.
- **Clear All**: Deletes all cameras and their K8s resources.

### Services

#### K8s Service (`services/k8s.py`)

Core orchestration layer. Handles all Kubernetes API interactions:

- **`generate_deployment()`**: Creates Deployment manifest with labels, nodeSelector, Jetson tolerations, container spec from converters
- **`generate_service()`**: Creates NodePort Service with `stream` (8081) and `control` (8080) ports
- **`generate_recorder_deployment()`**: Creates Recorder Deployment with stream URL, API URL, recordings hostPath
- **`generate_recorder_service()`**: Creates ClusterIP Service for recorder
- **`create_camera_deployment()`**: Creates Deployment + Service, handles 409 conflicts by replacing. Returns deployment name, service name, allocated NodePorts
- **`create_recorder_deployment()`**: Builds stream URL based on protocol (MJPEG ClusterIP for USB, direct RTSP for network cameras), creates Deployment + Service
- **`delete_*`**: Deletes resources by name or label selector, ignores 404
- **`get_camera_pod_status()`**: Checks actual container state (running/waiting/terminated) and maps to app status
- **`cleanup_stale_recorder_resources()`**: Finds recorder resources for cameras not in the valid ID list
- **`K8sService`** class: Wraps node listing, pod listing by label

#### Converters (`services/converters.py`)

Generates container specs per protocol:

| Protocol | Image | Container Name | Ports | Special |
|----------|-------|---------------|-------|---------|
| `usb` | `falcon-eye-camera-usb` | `motion` | 8081 (stream), 8080 (control) | Privileged, hostPath volume for device, runtime-generated motion.conf |
| `rtsp` | `falcon-eye-camera-rtsp` | `rtsp-relay` | 8081 (stream) | Env vars: RTSP_URL, WIDTH, HEIGHT, FPS, CAMERA_LABEL |
| `onvif` | `falcon-eye-camera-rtsp` | `onvif-relay` | 8081 (stream) | Same image as RTSP, resolves ONVIF URL internally |
| `http` | `falcon-eye-camera-rtsp` | `http-relay` | 8081 (stream) | Same image, works with HTTP/MJPEG URLs too |

All containers have resource requests (128Mi/100m) and limits (512Mi/500m), except HTTP which uses smaller limits (256Mi/250m).

### Tasks

#### Cleanup CronJob (`tasks/cleanup.py`)

Standalone script run as `python -m app.tasks.cleanup`. Performs three operations:

1. **Fix orphaned recordings**: Finds recordings with status `RECORDING` whose recorder pod is no longer running. Marks them as `STOPPED` with error message.
2. **Get DB camera IDs**: Queries all camera UUIDs from the database.
3. **Clean up stale K8s resources**: Finds camera/recorder Deployments and Services with `camera-id` or `recorder-for` labels that don't match any DB camera ID. Deletes them.

---

## Frontend: Dashboard

### Technology Stack

- **Framework**: React 18 (Vite build)
- **Styling**: Tailwind CSS
- **Icons**: Lucide React
- **Server**: nginx (Alpine)

### Architecture

The entire app is a **single-file SPA** (`App.jsx`). Components are defined as functions within the same file:

| Component | Purpose |
|-----------|---------|
| `App` | Root: routing, state, header, stats bar |
| `CameraGrid` | Grid view of camera cards with live preview |
| `CameraList` | Table view of cameras |
| `AddCameraModal` | Form to create a new camera |
| `EditCameraModal` | Form to edit camera settings |
| `CameraPreviewModal` | Full-size camera stream view |
| `ScanCamerasModal` | USB + network camera discovery |
| `SettingsModal` | System settings management |
| `ChatWidget` | AI chatbot with session management, docking, resizing |
| `RecordingsPage` | Recordings grouped by camera with playback |

### API Communication

- Base URL: `window.API_URL || '/api'` — in production, nginx proxies `/api/*` to the API server
- All API calls use `fetch()` directly (no API client library)
- Camera list auto-refreshes every 5 seconds
- Recording status checks every 10 seconds
- Chat uses Server-Sent Events (SSE) for streaming responses

### nginx Proxy (`nginx.conf.template`)

The nginx config uses `envsubst` (built into `nginx:alpine`) to inject `$API_URL`:

- `/api/*` → proxied to API server with WebSocket upgrade support
- `/api/chat/*` → separate location with SSE-specific settings (no buffering, 1-hour timeouts)
- `/` → serves SPA with `try_files` fallback to `index.html`
- Static assets: 1-year cache with immutable header

---

## Camera Relay Images

### USB Camera (`camera-usb`)

- **Base**: Ubuntu 22.04 with `motion` package
- **How it works**: At deployment time, the API generates a `motion.conf` via a bash script injected as the container command. This configures the video device, resolution, framerate, stream port, and overlay text.
- **Ports**: 8081 (MJPEG stream), 8080 (Motion web control interface)
- **Security**: Requires `privileged: true` for USB device access
- **Volume**: hostPath mount of the specific `/dev/videoX` device

### RTSP Relay (`camera-rtsp`)

- **Base**: Python 3.11-slim with FFmpeg + Flask + onvif-zeep
- **How it works**: Flask app runs FFmpeg as a subprocess that reads the RTSP stream and outputs JPEG frames to stdout (`-f image2pipe -vcodec mjpeg`). The Python code parses JPEG start/end markers (`\xff\xd8` / `\xff\xd9`) and serves them as `multipart/x-mixed-replace` MJPEG stream.
- **ONVIF support**: If URL starts with `onvif://`, uses `onvif-zeep` to discover the RTSP URL from the camera's media service.
- **Endpoints**: Both `/` and `/stream` serve the MJPEG stream. `/health` returns status.
- **Boundary framing**: Each frame is properly delimited with `--frame\r\nContent-Type: image/jpeg\r\n\r\n{data}\r\n`

---

## Recorder Service

- **Base**: Python 3.11-slim with FFmpeg
- **Framework**: FastAPI on Uvicorn, port 8080
- **Endpoints**: `/health`, `/status`, `/start`, `/stop`
- **State**: Single recording at a time, managed via global variables with an async lock

### Recording Logic

Two FFmpeg strategies based on stream type:

**MJPEG sources (USB cameras via Motion):**
```
ffmpeg -f mjpeg -i <stream_url> -c:v libx264 -preset ultrafast -crf 23 -t <max_duration> -movflags +faststart -f mp4 <output>
```
Must re-encode since MJPEG is not suitable for MP4 containers.

**RTSP sources (network cameras):**
```
ffmpeg -rtsp_transport tcp -i <stream_url> -c:v copy -c:a aac -b:a 64k -t <max_duration> -movflags +faststart -f mp4 <output>
```
Video is copied without re-encoding (preserving original quality, including HEVC/H.265). Audio is transcoded to AAC because some cameras (e.g., Tuya/Smart Life) output `pcm_mulaw` which is not compatible with the MP4 container format. If the source has no audio stream, FFmpeg silently ignores the audio flags.

### Lifecycle

1. **Start**: Creates output directory, generates filename with timestamp, spawns FFmpeg subprocess
2. **Monitor**: Background task checks if FFmpeg exited prematurely and reports failure to the API
3. **Stop**: Sends `SIGINT` for graceful FFmpeg shutdown (finalizes MP4 headers), waits up to 10s, then `SIGKILL` if needed
4. **Report**: Notifies the main API of recording start/stop/failure via HTTP POST/PATCH to `/api/recordings/`

Files are stored at: `/data/falcon-eye/recordings/{camera_id}/{camera_name}_{timestamp}.mp4`

---

## Docker Images

| Image | Dockerfile | Base | Key Packages |
|-------|-----------|------|-------------|
| `falcon-eye-api` | `scripts/cam-manager-py/Dockerfile` | Python 3.11-slim | FastAPI, SQLAlchemy, kubernetes, httpx |
| `falcon-eye-dashboard` | `frontend/Dockerfile` | Multi-stage: node:20 → nginx:alpine | React, Vite, Tailwind |
| `falcon-eye-camera-usb` | `scripts/camera-usb/Dockerfile` | Ubuntu 22.04 | motion |
| `falcon-eye-camera-rtsp` | `scripts/camera-rtsp/Dockerfile` | Python 3.11-slim | FFmpeg, Flask, onvif-zeep |
| `falcon-eye-recorder` | `scripts/recorder/Dockerfile` | Python 3.11-slim | FFmpeg, FastAPI, httpx |

All images are built for **linux/amd64** and **linux/arm64** via Docker Buildx with QEMU emulation. The container runtime automatically selects the correct platform — no user configuration required.

---

## CI/CD: GitHub Actions

### Workflow: `build-push.yml`

**Trigger**: Push to `main` branch (filtered by path), pull requests, or manual dispatch.

**Jobs** (run in parallel):

| Job | Builds | Context Path |
|-----|--------|-------------|
| `build-api` | `falcon-eye-api` | `./scripts/cam-manager-py` |
| `build-dashboard` | `falcon-eye-dashboard` | `./frontend` |
| `build-recorder` | `falcon-eye-recorder` | `./scripts/recorder` |
| `build-camera-usb` | `falcon-eye-camera-usb` | `./scripts/camera-usb` |
| `build-camera-rtsp` | `falcon-eye-camera-rtsp` | `./scripts/camera-rtsp` |

Each job:
1. Sets up QEMU + Docker Buildx
2. Logs into `ghcr.io` using `GITHUB_TOKEN`
3. Builds for `linux/amd64,linux/arm64`
4. Tags: `latest` (on main), git SHA, PR number
5. Pushes to GitHub Container Registry (skipped for PRs)
6. Uses GitHub Actions cache (`type=gha`)

A final `update-install-script` job runs after all builds succeed and generates a summary.

### Image Registry

All images are published to: `ghcr.io/amazingct/falcon-eye-*:latest`

The `FALCON_EYE_OWNER` environment variable in the install script allows forks to use their own registry prefix.
