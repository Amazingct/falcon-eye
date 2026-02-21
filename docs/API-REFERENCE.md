# API Reference

## Base URL

The API is **internal to the cluster** (ClusterIP) and is accessed through the Dashboard's nginx proxy:

```
http://<node-ip>:30900/api/
```

For local development, use `kubectl port-forward`:

```bash
kubectl port-forward svc/falcon-eye-api 8000:8000 -n falcon-eye
# Then access at http://localhost:8000
```

All endpoints return JSON. Request bodies should be `Content-Type: application/json`.

---

## Health

### `GET /health`

Health check endpoint.

**Response:**
```json
{
  "status": "ok",
  "timestamp": "2026-02-20T10:30:00.000000"
}
```

### `GET /`

API information and endpoint listing.

---

## Cameras

### `GET /api/cameras/`

List all cameras with optional filters. Syncs K8s pod status with the database.

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `protocol` | string | Filter by protocol: `usb`, `rtsp`, `onvif`, `http` |
| `status` | string | Filter by status: `running`, `stopped`, `error`, `creating`, `deleting` |
| `node` | string | Filter by node name |

**Response:**
```json
{
  "cameras": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "Office Camera",
      "protocol": "usb",
      "location": "Office",
      "source_url": null,
      "device_path": "/dev/video0",
      "node_name": "k3s-1",
      "deployment_name": "cam-office-camera",
      "service_name": "svc-office-camera",
      "stream_port": 8081,
      "control_port": 8080,
      "status": "running",
      "resolution": "640x480",
      "framerate": 15,
      "metadata": {},
      "created_at": "2026-02-20T10:00:00",
      "updated_at": "2026-02-20T10:00:30",
      "stream_url": "/api/cameras/550e8400-e29b-41d4-a716-446655440000/stream",
      "control_url": null,
      "k8s_status": {
        "ready": true,
        "replicas": 1,
        "ready_replicas": 1,
        "available_replicas": 1
      }
    }
  ],
  "total": 1
}
```

> **Note**: `stream_url` is a relative path. The browser loads it through the Dashboard, which proxies to the API, which proxies to the internal camera service.

**Example:**
```bash
curl http://localhost:8000/api/cameras/
curl http://localhost:8000/api/cameras/?protocol=usb&status=running
```

---

### `GET /api/cameras/{camera_id}`

Get a specific camera by UUID.

**Response:** Single camera object (same shape as list items).

**Status Codes:** `200` OK, `404` Camera not found.

```bash
curl http://localhost:8000/api/cameras/550e8400-e29b-41d4-a716-446655440000
```

---

### `GET /api/cameras/{camera_id}/stream`

Proxy the camera's MJPEG stream from its internal ClusterIP service. This endpoint relays the continuous `multipart/x-mixed-replace` stream from the camera pod to the browser.

**Response:** `multipart/x-mixed-replace` MJPEG stream (continuous).

**Status Codes:** `200` Streaming, `404` Camera not found, `502` Camera stream unavailable, `503` Camera has no service.

> This endpoint is designed to be used as an `<img>` source in the browser. The Dashboard's nginx has a dedicated location block for this path with 24-hour timeouts to support long-lived streams.

---

### `POST /api/cameras/`

Create a new camera. USB cameras deploy immediately; network cameras are created in `stopped` state.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Camera name (1–255 chars) |
| `protocol` | string | yes | `usb`, `rtsp`, `onvif`, or `http` |
| `location` | string | | Physical location description |
| `source_url` | string | yes for network | Stream URL (RTSP/ONVIF/HTTP cameras) |
| `device_path` | string | | Device path for USB (default: `/dev/video0`) |
| `node_name` | string | yes for USB | K8s node name (required for USB) |
| `resolution` | string | | Resolution (default: `640x480`) |
| `framerate` | int | | FPS, 1–60 (default: `15`) |
| `metadata` | object | | Custom key-value metadata |

**Example — USB camera:**
```bash
curl -X POST http://localhost:8000/api/cameras/ \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Office Camera",
    "protocol": "usb",
    "device_path": "/dev/video0",
    "node_name": "k3s-1"
  }'
```

**Example — RTSP camera:**
```bash
curl -X POST http://localhost:8000/api/cameras/ \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Front Door",
    "protocol": "rtsp",
    "source_url": "rtsp://admin:pass@192.168.1.100:554/stream1"
  }'
```

**Status Codes:** `201` Created, `400` Validation error, `409` Duplicate camera (same device path or IP).

---

### `PATCH /api/cameras/{camera_id}`

Update camera fields. If `source_url` changes on a running camera, the deployment is automatically recreated.

**Request Body:** (all fields optional)

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Camera name |
| `location` | string | Location description |
| `source_url` | string | Stream URL (network cameras) |
| `resolution` | string | Resolution |
| `framerate` | int | FPS |
| `metadata` | object | Custom metadata |

```bash
curl -X PATCH http://localhost:8000/api/cameras/550e8400-... \
  -H 'Content-Type: application/json' \
  -d '{"name": "New Name", "source_url": "rtsp://admin:newpass@192.168.1.100:554/stream1"}'
```

**Status Codes:** `200` Updated, `404` Not found.

---

### `DELETE /api/cameras/{camera_id}`

Delete a camera. Runs in the background: deletes K8s resources, marks recordings as orphaned, then removes the DB record.

```bash
curl -X DELETE http://localhost:8000/api/cameras/550e8400-...
```

**Response:**
```json
{
  "message": "Camera deletion started",
  "id": "550e8400-..."
}
```

**Status Codes:** `200` Deletion started, `400` Already deleting, `404` Not found.

---

### `POST /api/cameras/{camera_id}/start`

Start a stopped camera. Creates K8s deployment and recorder.

```bash
curl -X POST http://localhost:8000/api/cameras/550e8400-.../start
```

**Status Codes:** `200` Starting/already running, `404` Not found, `500` K8s error.

---

### `POST /api/cameras/{camera_id}/stop`

Stop a running camera. Deletes K8s deployment and recorder.

```bash
curl -X POST http://localhost:8000/api/cameras/550e8400-.../stop
```

**Status Codes:** `200` Stopped/already stopped, `404` Not found.

---

### `POST /api/cameras/{camera_id}/restart`

Restart a camera by deleting and recreating its K8s resources.

```bash
curl -X POST http://localhost:8000/api/cameras/550e8400-.../restart
```

**Status Codes:** `200` Restarted, `404` Not found, `500` K8s error.

---

### `GET /api/cameras/{camera_id}/stream-info`

Get stream URLs for a camera.

**Response:**
```json
{
  "id": "550e8400-...",
  "name": "Office Camera",
  "stream_url": "/api/cameras/550e8400-.../stream",
  "control_url": null,
  "protocol": "usb",
  "status": "running"
}
```

> **Note**: `stream_url` is a relative path proxied through the Dashboard and API. `control_url` is `null` since camera services are internal.

---

## Recording Control

### `GET /api/cameras/{camera_id}/recording/status`

Get recording status for a camera. Auto-fixes orphaned recordings if the recorder pod is gone.

**Response (recording):**
```json
{
  "recording_id": "550e8400-..._20260220103000",
  "camera_id": "550e8400-...",
  "camera_name": "Office Camera",
  "file_path": "/recordings/550e8400-.../Office_Camera_20260220_103000.mp4",
  "file_name": "Office_Camera_20260220_103000.mp4",
  "start_time": "2026-02-20T10:30:00",
  "status": "recording"
}
```

**Response (idle):**
```json
{
  "camera_id": "550e8400-...",
  "camera_name": "Office Camera",
  "status": "idle"
}
```

**Response (no recorder):**
```json
{
  "recording": false,
  "status": "no_recorder",
  "message": "Recorder not deployed"
}
```

---

### `POST /api/cameras/{camera_id}/recording/start`

Start recording. Auto-deploys the recorder pod if not already present. Only one active recording per camera is allowed.

```bash
curl -X POST http://localhost:8000/api/cameras/550e8400-.../recording/start
```

**Status Codes:** `200` Started, `400` Camera not running / no stream port, `409` Already recording, `503` Recorder still deploying.

---

### `POST /api/cameras/{camera_id}/recording/stop`

Stop the active recording.

```bash
curl -X POST http://localhost:8000/api/cameras/550e8400-.../recording/stop
```

**Status Codes:** `200` Stopped, `400` No recorder deployed, `503` Recorder still deploying.

---

## Recordings

### `GET /api/recordings/`

List all recordings.

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `camera_id` | string (UUID) | Filter by camera |
| `status` | string | Filter: `recording`, `stopped`, `completed`, `failed` |
| `limit` | int | Max results (default: 100) |
| `offset` | int | Pagination offset |

**Response:**
```json
{
  "recordings": [
    {
      "id": "550e8400-..._20260220103000",
      "camera_id": "550e8400-...",
      "camera_name": "Office Camera",
      "file_path": "/recordings/.../Office_Camera_20260220_103000.mp4",
      "file_name": "Office_Camera_20260220_103000.mp4",
      "start_time": "2026-02-20T10:30:00",
      "end_time": "2026-02-20T10:45:00",
      "duration_seconds": 900,
      "file_size_bytes": 52428800,
      "status": "completed",
      "node_name": "k3s-1",
      "error_message": null,
      "camera_deleted": false
    }
  ],
  "count": 1
}
```

> **Note**: `node_name` indicates which cluster node holds the recording file. This is used internally by the file-server DaemonSet for optimized file lookup.

```bash
curl http://localhost:8000/api/recordings/
curl http://localhost:8000/api/recordings/?camera_id=550e8400-...&status=completed
```

---

### `GET /api/recordings/{recording_id}`

Get a specific recording.

**Status Codes:** `200` OK, `404` Not found.

---

### `POST /api/recordings/`

Create a recording record (called internally by the recorder service).

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Recording ID |
| `camera_id` | string | yes | Camera UUID |
| `camera_name` | string | | Camera name (preserved for orphaned recordings) |
| `file_path` | string | yes | Full path to recording file |
| `file_name` | string | yes | Filename only |
| `start_time` | string | yes | ISO 8601 timestamp |
| `status` | string | | Default: `recording` |
| `node_name` | string | | Name of the node where the file is stored |

---

### `PATCH /api/recordings/{recording_id}`

Update a recording (called internally by the recorder service on stop/completion).

**Request Body:**

| Field | Type | Description |
|-------|------|-------------|
| `end_time` | string | ISO 8601 end timestamp |
| `status` | string | `completed`, `stopped`, `failed` |
| `file_size_bytes` | int | File size in bytes |
| `error_message` | string | Error description |

---

### `DELETE /api/recordings/{recording_id}`

Delete a recording and optionally its file.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `delete_file` | bool | `true` | Also delete the video file from disk |

```bash
curl -X DELETE http://localhost:8000/api/recordings/rec-id-here
```

---

### `GET /api/recordings/{recording_id}/download`

Download the recording MP4 file. The API locates the file across the cluster by querying file-server DaemonSet pods.

**Response:** `video/mp4` file download (streamed from the file-server pod that has the file).

**Status Codes:** `200` File served, `404` Recording or file not found.

```bash
curl -O http://localhost:8000/api/recordings/rec-id-here/download
```

---

## Nodes

### `GET /api/nodes/`

List all cluster nodes with status, IP, taints, labels, and architecture.

**Response:**
```json
[
  {
    "name": "k3s-1",
    "ip": "192.168.1.207",
    "ready": true,
    "taints": [],
    "labels": {"kubernetes.io/hostname": "k3s-1"},
    "architecture": "arm64",
    "os": "linux"
  }
]
```

```bash
curl http://localhost:8000/api/nodes/
```

---

### `GET /api/nodes/{name}`

Get a specific node by name.

---

### `GET /api/nodes/scan/cameras`

Scan cluster nodes for available cameras (USB and optionally network).

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `node` | string | *(all)* | Scan a specific node only |
| `network` | bool | `false` | Also scan network for RTSP/ONVIF cameras |

**Response:**
```json
{
  "cameras": [
    {
      "device_path": "/dev/video0",
      "device_name": "HD Pro Webcam C920",
      "node_name": "k3s-1",
      "node_ip": "192.168.1.207",
      "protocol": "usb"
    }
  ],
  "network_cameras": [
    {
      "ip": "192.168.1.100",
      "port": 554,
      "protocol": "rtsp",
      "name": "Camera 192.168.1.100",
      "url": "rtsp://192.168.1.100:554/stream1",
      "node_name": "LAN"
    }
  ],
  "total": 2,
  "scanned_nodes": ["k3s-1", "k3s-2"],
  "errors": []
}
```

The USB scan connects via SSH to each node and enumerates `/dev/video*` devices. The network scan probes common camera ports (554, 8554, 80, 8080, 8899) across the subnet.

```bash
curl http://localhost:8000/api/nodes/scan/cameras
curl http://localhost:8000/api/nodes/scan/cameras?network=true
curl http://localhost:8000/api/nodes/scan/cameras?node=k3s-1
```

---

## Settings

### `GET /api/settings/`

Get current system settings.

**Response:**
```json
{
  "default_resolution": "640x480",
  "default_framerate": 15,
  "default_camera_node": "",
  "default_recorder_node": "",
  "k8s_namespace": "falcon-eye",
  "cleanup_interval": "*/2 * * * *",
  "creating_timeout_minutes": 3,
  "node_ips": {"k3s-1": "192.168.1.207", "k3s-2": "192.168.1.138"},
  "chatbot": {
    "api_key_configured": true,
    "enabled_tools": ["list_cameras", "get_camera", "list_nodes"],
    "available_tools": ["list_cameras", "get_camera", "list_nodes", "list_recordings"]
  }
}
```

---

### `PATCH /api/settings/`

Update settings. Writes to the `falcon-eye-config` ConfigMap. API key is stored in a separate Secret.

**Request Body:** (all fields optional)

| Field | Type | Description |
|-------|------|-------------|
| `default_resolution` | string | Default camera resolution |
| `default_framerate` | int | Default FPS |
| `default_camera_node` | string | Default node for camera pods (empty = auto-assign) |
| `default_recorder_node` | string | Default node for recorder pods (empty = auto-assign) |
| `cleanup_interval` | string | Cron expression for cleanup job |
| `creating_timeout_minutes` | int | Timeout for stuck cameras |
| `anthropic_api_key` | string | Anthropic API key (validated before saving) |
| `chatbot_tools` | string[] | List of enabled chatbot tools |

```bash
curl -X PATCH http://localhost:8000/api/settings/ \
  -H 'Content-Type: application/json' \
  -d '{"default_resolution": "1280x720", "default_framerate": 30}'
```

**Status Codes:** `200` Updated, `400` Invalid API key.

---

### `POST /api/settings/restart-all`

Restart all Falcon-Eye deployments (API, dashboard, camera pods) and update CronJob schedule.

```bash
curl -X POST http://localhost:8000/api/settings/restart-all
```

**Response:**
```json
{
  "message": "Scheduled restart for 5 deployment(s)",
  "restarted": ["falcon-eye-api", "falcon-eye-dashboard", "cam-office", "cam-front-door", "falcon-eye-cleanup (cronjob)"]
}
```

---

### `DELETE /api/settings/cameras/all`

Delete ALL cameras from database and K8s. **Destructive — cannot be undone.**

```bash
curl -X DELETE http://localhost:8000/api/settings/cameras/all
```

**Response:**
```json
{
  "message": "Deleted 5 camera(s)",
  "count": 5
}
```

---

## Agents

### `GET /api/agents/`

List all agents.

**Response:**
```json
{
  "agents": [
    {
      "id": "550e8400-...",
      "name": "Main Assistant",
      "slug": "main-assistant",
      "type": "pod",
      "provider": "anthropic",
      "model": "claude-sonnet-4-20250514",
      "status": "running",
      "channel_type": "telegram",
      "tools": ["camera_list", "camera_snapshot", "agent_spawn"],
      "deployment_name": "agent-main-assistant",
      "service_name": "svc-agent-main-assistant",
      "created_at": "2026-02-20T10:00:00"
    }
  ]
}
```

---

### `POST /api/agents/`

Create a new agent.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Display name (1–100 chars) |
| `slug` | string | yes | URL-safe identifier (1–50 chars, must be unique) |
| `type` | string | | `pod` (default) |
| `provider` | string | | `openai` (default), `anthropic` |
| `model` | string | | LLM model name (default: `gpt-4o`) |
| `api_key_ref` | string | | API key (or empty to use env var) |
| `system_prompt` | string | | System prompt for the agent |
| `temperature` | float | | 0–2 (default: 0.7) |
| `max_tokens` | int | | Max response tokens (default: 4096) |
| `channel_type` | string | | `telegram`, `webhook`, or null |
| `channel_config` | object | | Channel-specific config (e.g. `{"bot_token": "...", "chat_id": "..."}`) |
| `tools` | string[] | | Tool IDs from the registry |
| `cpu_limit` | string | | K8s CPU limit (default: `500m`) |
| `memory_limit` | string | | K8s memory limit (default: `512Mi`) |

**Status Codes:** `201` Created, `409` Duplicate slug.

---

### `GET /api/agents/{agent_id}`

Get agent details by UUID.

---

### `PATCH /api/agents/{agent_id}`

Update agent configuration. All fields optional.

---

### `DELETE /api/agents/{agent_id}`

Delete an agent and its K8s resources. The main agent cannot be deleted.

---

### `POST /api/agents/{agent_id}/start`

Deploy the agent's K8s pod. Creates a Deployment and ClusterIP Service.

---

### `POST /api/agents/{agent_id}/stop`

Stop the agent pod. Deletes K8s Deployment and Service.

---

### `POST /api/agents/{agent_id}/restart`

Restart the agent pod (stop + start).

---

## Agent Chat

### `POST /api/chat/{agent_id}/send`

Send a message to an agent. Stores the user message, proxies to the agent pod for LLM processing, stores the response, and returns it.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | string | yes | User message |
| `session_id` | string | | Chat session ID (auto-generated if omitted) |
| `source` | string | | `dashboard` (default), `telegram`, `agent`, `system` |
| `source_user` | string | | Identifier of the message sender |

**Response:**
```json
{
  "response": "I found 3 cameras online...",
  "session_id": "550e8400-...",
  "timestamp": "2026-02-20T10:30:00",
  "prompt_tokens": 1500,
  "completion_tokens": 200,
  "media": [
    {"type": "photo", "path": "snapshots/cam-office.jpg", "caption": "Office camera snapshot"}
  ]
}
```

---

### `GET /api/chat/{agent_id}/history`

Get chat history for an agent.

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `session_id` | string | Filter by session |
| `limit` | int | Max messages (default: 50, max: 200) |
| `offset` | int | Pagination offset |

---

### `POST /api/chat/{agent_id}/messages/save`

Save a message directly to an agent's chat history. Used by agent pods for Telegram/webhook messages and by inter-agent callbacks.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | yes | Chat session ID |
| `role` | string | yes | `user`, `assistant`, or `system` |
| `content` | string | yes | Message content |
| `source` | string | | Message source |
| `source_user` | string | | Sender identifier |

---

### `GET /api/chat/{agent_id}/sessions`

List chat sessions for an agent with message counts and timestamps.

---

### `POST /api/chat/{agent_id}/sessions/new`

Create a new chat session and return its ID.

---

## Tools

### `GET /api/tools/`

List all available tools grouped by category.

**Response:**
```json
{
  "tools": {
    "cameras": [
      {
        "id": "camera_list",
        "name": "list_cameras",
        "description": "Get all cameras and their current status",
        "category": "cameras",
        "parameters": { "type": "object", "properties": {} }
      }
    ],
    "agents": [...],
    "filesystem": [...],
    ...
  }
}
```

---

### `POST /api/tools/execute`

Execute a tool by name. Used by agent pods to run tools via the API.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `tool_name` | string | yes | Tool function name (e.g. `list_cameras`) |
| `arguments` | object | | Tool arguments |
| `agent_context` | object | | Agent context (provider, model, agent_id, session_id) |

**Response:**
```json
{
  "result": "Found 3 cameras:\n- **Office** (id: `abc-123`) — running | usb",
  "media": [
    {"type": "photo", "path": "snapshots/office.jpg", "caption": "Office snapshot"}
  ]
}
```

---

### `GET /api/agents/{agent_id}/tools`

Get the tools assigned to a specific agent.

---

### `PUT /api/agents/{agent_id}/tools`

Set the tools for an agent.

**Request Body:**
```json
{
  "tools": ["camera_list", "camera_snapshot", "agent_spawn", "send_media"]
}
```

---

### `GET /api/agents/{agent_id}/chat-config`

Get everything an agent pod needs for autonomous chat: tool schemas, system prompt, and LLM config. Used by agent pods handling Telegram/webhook messages.

---

## Files (Shared Filesystem)

### `GET /api/files/`

List files and directories at a given prefix.

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `prefix` | string | Directory path (empty for root) |

**Response:**
```json
{
  "path": "snapshots",
  "files": [
    {
      "name": "office.jpg",
      "path": "snapshots/office.jpg",
      "is_dir": false,
      "size": 52428,
      "modified": "2026-02-20T10:30:00+00:00",
      "mime_type": "image/jpeg"
    }
  ]
}
```

---

### `GET /api/files/read/{file_path}`

Read a text file's content, or download a binary file.

---

### `POST /api/files/write`

Write text content to a file. Creates parent directories as needed.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | yes | File path relative to root |
| `content` | string | yes | Text content |
| `append` | bool | | Append instead of overwrite (default: false) |

---

### `POST /api/files/upload/{file_path}`

Upload a binary file (multipart form). Creates parent directories.

---

### `DELETE /api/files/{file_path}`

Delete a file or empty directory.

---

### `GET /api/files/info/{file_path}`

Get metadata about a file (size, mime type, modified date).

---

### `POST /api/files/mkdir/{dir_path}`

Create a directory (and parent directories).
