# Architecture

## High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Kubernetes Cluster                              │
│  Namespace: falcon-eye                                                   │
│                                                                          │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐       │
│  │  Dashboard    │    │   API Server     │    │   PostgreSQL     │       │
│  │  (React SPA)  │───▶│   (FastAPI)      │───▶│   (postgres:15)  │       │
│  │  nginx:80     │    │   :8000          │    │   :5432          │       │
│  │  NodePort     │    │   ClusterIP      │    │   ClusterIP      │       │
│  │  30900        │    │   (internal)     │    │                  │       │
│  └──────────────┘    └────────┬─────────┘    └──────────────────┘       │
│         │                     │                                          │
│  streams proxied         ┌────┼────────────────┐                        │
│  via API                 │    │                 │                        │
│         │                ▼    ▼                 ▼                        │
│         │    ┌──────────────┐  ┌──────────────┐  ┌────────────────┐     │
│         └───▶│ Camera Pod   │  │ Camera Pod   │  │ Cleanup CronJob│     │
│              │ (USB/Motion) │  │ (RTSP/FFmpeg)│  │ (every 2 min)  │     │
│              │ :8081 stream │  │ :8081 stream │  │ Removes orphans│     │
│              │ :8080 ctrl   │  │              │  │ Fixes stale rec│     │
│              │ ClusterIP    │  │ ClusterIP    │  └────────────────┘     │
│              └──────┬───────┘  └──────┬───────┘                         │
│                     │                  │                                  │
│                     ▼                  ▼                                  │
│              ┌──────────────┐  ┌──────────────┐                         │
│              │ Recorder Pod │  │ Recorder Pod │                         │
│              │ (FFmpeg)     │  │ (FFmpeg)     │                         │
│              │ :8080 API    │  │ :8080 API    │                         │
│              │ ClusterIP    │  │ ClusterIP    │                         │
│              │ hostPath:    │  │ hostPath:    │                         │
│              │ /data/falcon │  │ /data/falcon │                         │
│              │ -eye/record  │  │ -eye/record  │                         │
│              └──────────────┘  └──────────────┘                         │
│                                                                          │
│  ┌───────────────────────────────────────────────────────────────┐      │
│  │  File-Server DaemonSet (runs on EVERY node)                    │      │
│  │  nginx:alpine — serves /data/falcon-eye/recordings (read-only) │      │
│  │  :8080  |  Headless ClusterIP service                          │      │
│  └───────────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────────┘
```

## Network Security Model

Only the **Dashboard** is exposed outside the cluster (NodePort 30900). All other services use ClusterIP and are only reachable within the cluster network:

```
Browser ──▶ Dashboard (NodePort 30900)
               │
               ├── /api/* ──▶ API Server (ClusterIP)
               │
               └── /api/cameras/{id}/stream ──▶ API Server ──▶ Camera Pod (ClusterIP)
```

The API proxies camera streams internally, so camera pods never need direct external access.

## High-Level Overview (with Agent System)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          Kubernetes Cluster                                │
│  Namespace: falcon-eye                                                    │
│                                                                           │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐        │
│  │  Dashboard    │    │   API Server     │    │   PostgreSQL     │        │
│  │  (React SPA)  │───▶│   (FastAPI)      │───▶│   (postgres:15)  │        │
│  │  nginx:80     │    │   :8000          │    │   :5432          │        │
│  │  NodePort     │    │   ClusterIP      │    │                  │        │
│  │  30900        │    │   (internal)     │    │                  │        │
│  └──────────────┘    └───────┬──────────┘    └──────────────────┘        │
│         │                    │                                             │
│  streams proxied        ┌────┼────────────┬──────────────┐               │
│  via API                │    │            │              │               │
│         │               ▼    ▼            ▼              ▼               │
│         │   ┌──────────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐ │
│         └──▶│ Camera Pods  │ │ Recorder │ │ Cleanup  │ │ Agent Pods  │ │
│             │ (USB/RTSP)   │ │ Pods     │ │ CronJob  │ │ (LangGraph) │ │
│             │ ClusterIP    │ │ ClusterIP│ │          │ │ ClusterIP   │ │
│             └──────┬───────┘ └────┬─────┘ └──────────┘ └──────┬──────┘ │
│                    │              │                             │         │
│                    │              │    ┌────────────────────────┘         │
│                    │              │    │  tools executed via API           │
│                    ▼              ▼    ▼                                   │
│  ┌───────────────────────────────────────────────────────────┐           │
│  │  Shared Filesystem (PVC: falcon-eye-agent-files)           │           │
│  │  /agent-files — snapshots, reports, media, alerts          │           │
│  ├───────────────────────────────────────────────────────────┤           │
│  │  File-Server DaemonSet (every node)                        │           │
│  │  nginx:alpine — serves /data/falcon-eye/recordings         │           │
│  └───────────────────────────────────────────────────────────┘           │
└──────────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Dashboard (falcon-eye-dashboard)

- **Image**: `ghcr.io/amazingct/falcon-eye-dashboard:latest`
- **Technology**: React SPA built with Vite, styled with Tailwind CSS
- **Served by**: nginx (Alpine) on port 80
- **NodePort**: 30900 — the **only** externally accessible service
- **Function**: Web UI for managing cameras, viewing live streams, managing recordings, AI chat
- **API proxy**: nginx proxies `/api/*` requests to the API server (ClusterIP), so the browser never contacts the API directly
- **Stream proxy**: nginx has a dedicated location for `/api/cameras/{id}/stream` with long timeouts (24h) to support continuous MJPEG streams

### 2. API Server (falcon-eye-api)

- **Image**: `ghcr.io/amazingct/falcon-eye-api:latest`
- **Technology**: Python FastAPI with async SQLAlchemy
- **Port**: 8000, **ClusterIP** (internal only)
- **Function**: REST API for camera CRUD, K8s deployment orchestration, recording management, node scanning, settings, AI chatbot, stream proxying
- **Stream proxy**: `GET /api/cameras/{id}/stream` proxies the camera's internal MJPEG stream to the browser via the dashboard
- **Recording downloads**: Locates recording files across all cluster nodes via the file-server DaemonSet
- **RBAC**: Uses `falcon-eye-sa` ServiceAccount with cluster-wide permissions on pods, deployments, services, configmaps, secrets, nodes, cronjobs, and jobs
- **Recordings volume**: hostPath mount at `/data/falcon-eye/recordings`

### 3. PostgreSQL

- **Image**: `postgres:15-alpine`
- **Port**: 5432 (ClusterIP only — internal)
- **Storage**: 1Gi PVC
- **Credentials**: `falcon` / `falcon-eye-2026` / database `falconeye`
- **Tables**: `cameras`, `recordings`, `chat_sessions`, `chat_messages`

### 4. Camera Relay Pods

Each camera gets its own Deployment + ClusterIP Service. Two types:

#### USB Camera (Motion-based)
- **Image**: `ghcr.io/amazingct/falcon-eye-camera-usb:latest`
- **Base**: Ubuntu 22.04 with Motion
- **Ports**: 8081 (MJPEG stream), 8080 (Motion web control) — ClusterIP only
- **Requires**: `privileged: true` security context, hostPath volume for `/dev/videoX`
- **Must** run on the specific node where the USB device is attached (nodeSelector)

#### RTSP/ONVIF/HTTP Camera (FFmpeg-based)
- **Image**: `ghcr.io/amazingct/falcon-eye-camera-rtsp:latest`
- **Base**: Python 3.11-slim with FFmpeg + Flask
- **Port**: 8081 (MJPEG stream converted from RTSP via FFmpeg) — ClusterIP only
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
- **Reports** to the API server when recordings start/stop/fail, including the `node_name` where the recording is stored
- **Node tracking**: Injects `NODE_NAME` via the Kubernetes Downward API (`spec.nodeName`) so the API knows which node holds each recording file

### 6. File-Server DaemonSet (falcon-eye-file-server)

- **Image**: `nginx:alpine`
- **Type**: DaemonSet — runs on **every** node in the cluster
- **Port**: 8080 (Headless ClusterIP service)
- **Tolerations**: `operator: Exists` — tolerates all taints, ensuring it runs on master/control-plane nodes too
- **Function**: Serves `/data/falcon-eye/recordings` as static files (read-only mount)
- **Purpose**: Allows the API server to locate and download recording files from any node, regardless of where the recorder pod ran. The API queries file-server pods to find recordings, using the `node_name` hint for optimized lookup.

### 7. Cleanup CronJob (falcon-eye-cleanup)

- **Image**: Same as API (`ghcr.io/amazingct/falcon-eye-api:latest`)
- **Command**: `python -m app.tasks.cleanup`
- **Schedule**: Every 2 minutes (configurable via `CLEANUP_INTERVAL`)
- **Actions**:
  1. Fixes orphaned recordings (status stuck at "recording" but recorder pod is gone)
  2. Deletes stale camera deployments/services not registered in the database
  3. Deletes stale recorder deployments/services for cameras no longer in the database

### 8. Agent Pods (LangGraph)

Each AI agent runs as its own Kubernetes Deployment + ClusterIP Service:

- **Image**: `ghcr.io/amazingct/falcon-eye-agent:latest`
- **Technology**: Python with LangGraph `create_react_agent`, supporting Anthropic and OpenAI providers
- **Port**: 8080 (ClusterIP only — API server proxies all communication)
- **Endpoints**: `/chat/send` (API-proxied chat), `/process` (direct Telegram/webhook messages), `/health`
- **Tool execution**: Agent pods do **not** execute tools directly. They call back to the API's `/api/tools/execute` endpoint, which runs the handler on the API pod. This keeps all Kubernetes and database access centralized.
- **Shared filesystem**: Mounted at `/agent-files` via PVC (`falcon-eye-agent-files`) for inter-agent file exchange
- **Channels**: Dashboard (via API proxy), Telegram (bot running on the agent pod), Webhooks

#### Agent Types

| Type | Lifecycle | Description |
|------|-----------|-------------|
| Persistent | Long-running | Created via dashboard or API, runs until stopped |
| Ephemeral | Task-scoped | Spawned by another agent via `spawn_agent` tool, auto-deleted after task completion |

#### Multi-Agent Communication

Agents can collaborate asynchronously:

- **`spawn_agent` (with task)**: Creates an ephemeral agent pod, returns immediately. The spawned agent executes in the background. When done, the result is injected as a system message into the caller's session, the caller is re-triggered to process it, and the ephemeral pod is cleaned up.
- **`delegate_task`**: Sends a task to an already-running agent asynchronously. Returns immediately. The result is delivered the same way — as a system message to the caller's session.

```
Caller Agent                    Spawned Agent
    │                               │
    │── spawn_agent(task) ──────▶   │ (pod created)
    │   returns immediately         │
    │   continues working...        │
    │                               │── executes task
    │                               │── calls tools via API
    │                               │── returns result
    │                               │
    │◀── system message injected ───│
    │◀── caller re-triggered        │
    │   processes result             │ (pod deleted)
    ▼                               ▼
```

### 9. Tool System

Tools are registered in `app/tools/registry.py` and executed by handlers in `app/tools/handlers.py`. The API serves as the central tool execution hub:

| Category | Tools | Description |
|----------|-------|-------------|
| cameras | `list_cameras`, `camera_status`, `control_camera`, `camera_snapshot`, `analyze_camera` | Camera management and vision AI |
| recording | `start_recording`, `stop_recording`, `list_recordings` | Recording control |
| system | `list_nodes`, `scan_cameras`, `system_info` | Cluster operations |
| agents | `spawn_agent`, `delegate_task`, `clone_agent` | Multi-agent orchestration |
| filesystem | `read_file`, `write_file`, `list_files`, `delete_file`, `send_media` | Shared filesystem operations |
| alerts | `send_alert` | Alert logging + Telegram push |
| external | `web_search`, `custom_api_call` | External integrations |

### 10. Shared Filesystem

- **PVC**: `falcon-eye-agent-files` (1Gi)
- **Mount path**: `/agent-files` on API and all agent pods
- **Purpose**: Camera snapshots, reports, alert logs, and inter-agent file exchange
- **API**: `/api/files/*` endpoints for read/write/upload/delete/list

## Data Flow

### Live Streaming

```
Physical Camera
    │
    ▼
Camera Relay Pod (Motion or FFmpeg)
    │ Converts to MJPEG
    ▼
ClusterIP Service (internal)
    │
    ▼
API Server (proxies stream via /api/cameras/{id}/stream)
    │
    ▼
Dashboard nginx (proxies to API with long timeouts)
    │
    ▼
Browser <img src="/api/cameras/{id}/stream">
```

The dashboard displays camera streams by pointing `<img>` tags at the API's stream proxy endpoint. The API fetches the MJPEG stream from the camera's internal ClusterIP service and relays it to the browser. This keeps camera services off the public network — the browser only talks to the Dashboard.

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
File-Server DaemonSet (nginx on every node)
    │ Serves files on request
    ▼
API Server finds file via file-server pods → streams via /api/recordings/{id}/download
    │
    ▼
Dashboard proxies to API → Browser downloads file
```

- For **USB cameras**: recorder reads the MJPEG stream from the camera relay's ClusterIP service and re-encodes to H.264
- For **RTSP cameras**: recorder reads directly from the camera's source RTSP URL (better quality, no double-encoding) and copies the video stream
- **File discovery**: When downloading, the API queries file-server DaemonSet pods to locate the file. It uses the `node_name` stored on the recording as a hint, falling back to scanning all nodes.

### Agent Chat (Dashboard)

```
Browser (Dashboard)
    │
    ├── POST /api/chat/{agent_id}/send
    │
    ▼
API Server
    │ 1. Save user message to DB
    │ 2. Build LLM context (system prompt + history + tool schemas)
    │ 3. Proxy to agent pod
    │
    ▼
Agent Pod (LangGraph ReAct agent)
    │ 4. LLM decides: respond or call tools
    │ 5. If tool needed → POST /api/tools/execute → API handler → result
    │ 6. LLM loop continues until final response
    │
    ▼
API Server
    │ 7. Save assistant message to DB
    │ 8. Return response + media (if any)
    │
    ▼
Browser (renders markdown response)
```

### Agent Chat (Telegram)

```
Telegram Cloud
    │ Webhook or polling
    ▼
Agent Pod (Telegram bot)
    │ 1. Receive message
    │ 2. Fetch chat-config from API (tools, system prompt, credentials)
    │ 3. Run LangGraph agent (tools call back to API)
    │ 4. Save messages to DB via API
    │ 5. Send response + media to Telegram
    ▼
Telegram Cloud → User's phone/desktop
```

### Async Multi-Agent Task

```
User → Caller Agent
    │
    ├── spawn_agent("researcher", task="...")
    │   Returns: "Agent spawned, running in background"
    │
    ├── Caller responds to user immediately
    │
    │   [Background]
    │   ├── Spawned agent pod starts
    │   ├── Task sent via /api/chat/{id}/send
    │   ├── Spawned agent executes (may call tools)
    │   ├── Result saved as system message in caller's session
    │   ├── Caller re-triggered via /api/chat/{caller}/send
    │   ├── Caller processes result, generates follow-up
    │   ├── If Telegram: pushed to chat
    │   └── Spawned agent pod deleted
```

## Kubernetes Resource Model

### Labels

All resources use consistent labels:

| Label | Values | Purpose |
|-------|--------|---------|
| `app` | `falcon-eye` | Identifies all Falcon-Eye resources |
| `component` | `camera`, `recorder`, `cleanup`, `file-server`, `agent` | Component type |
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
| File-Server DaemonSet | `falcon-eye-file-server` | (one per cluster) |
| Agent Deployment | `agent-{slug}` | `agent-main-assistant` |
| Agent Service | `svc-agent-{slug}` | `svc-agent-main-assistant` |

### Service Types

| Service | Port | Type | Accessible From |
|---------|------|------|-----------------|
| Dashboard | 30900 | NodePort | External (browser) |
| API Server | 8000 | ClusterIP | Internal only |
| Camera streams | 8081 | ClusterIP | Internal only |
| PostgreSQL | 5432 | ClusterIP | Internal only |
| Recorder pods | 8080 | ClusterIP | Internal only |
| Agent pods | 8080 | ClusterIP | Internal only |
| File-Server | 8080 | Headless ClusterIP | Internal only |

### RBAC

| Resource | Name |
|----------|------|
| ServiceAccount | `falcon-eye-sa` |
| ClusterRole | `falcon-eye-role` |
| ClusterRoleBinding | `falcon-eye-binding` |

Permissions: full CRUD on pods, services, configmaps, secrets, deployments, cronjobs, jobs; read on nodes.

## Node Selection Logic

1. **USB cameras**: **Must** be pinned to the node where the USB device is physically connected (`nodeSelector: kubernetes.io/hostname`)
2. **Network cameras**: Use `DEFAULT_CAMERA_NODE` if configured, otherwise auto-assigned by the Kubernetes scheduler
3. **Recorders**: Follow the camera's node if set, otherwise use `DEFAULT_RECORDER_NODE`, otherwise auto-assigned
4. **File-server**: Runs on **every** node (DaemonSet with `tolerations: [{operator: Exists}]`)

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
