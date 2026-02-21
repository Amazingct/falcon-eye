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
│   │       │   ├── recording.py        # Recording ORM model (incl. node_name)
│   │       │   ├── chat.py             # ChatSession + ChatMessage models
│   │       │   └── schemas.py          # Pydantic request/response schemas
│   │       ├── routes/
│   │       │   ├── cameras.py          # Camera CRUD + start/stop/restart + recording control + stream proxy
│   │       │   ├── recordings.py       # Recordings CRUD + download (via file-server DaemonSet)
│   │       │   ├── nodes.py            # Node listing + USB/network camera scanning
│   │       │   ├── settings.py         # Settings CRUD + restart-all + clear-all
│   │       │   ├── agents.py           # Agent CRUD + start/stop/restart
│   │       │   ├── agent_chat.py       # Chat send/history/sessions (proxies to agent pods)
│   │       │   ├── tools.py            # Tool listing + execution + agent tool management
│   │       │   ├── files.py            # Shared filesystem API (read/write/upload/delete)
│   │       │   └── cron_routes.py      # Cron job management
│   │       ├── tools/
│   │       │   ├── registry.py         # Tool definitions (name, schema, category, handler)
│   │       │   └── handlers.py         # Tool implementations (camera ops, agents, filesystem, web search)
│   │       ├── models/
│   │       │   ├── camera.py           # Camera ORM model + enums
│   │       │   ├── recording.py        # Recording ORM model (incl. node_name)
│   │       │   ├── agent.py            # Agent + AgentChatMessage ORM models
│   │       │   └── schemas.py          # Pydantic request/response schemas
│   │       ├── services/
│   │       │   ├── k8s.py              # K8s deployment/service generation + CRUD
│   │       │   └── converters.py       # Protocol-specific container spec generators
│   │       └── tasks/
│   │           └── cleanup.py          # CronJob: orphan cleanup + recording fix
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
│   ├── agent/                          # LangGraph Agent Pod
│   │   ├── Dockerfile
│   │   ├── main.py                     # FastAPI entry: /chat/send, /process, Telegram bot
│   │   └── tool_executor.py            # Builds LangChain StructuredTools from API schemas
│   │
│   └── recorder/                       # Recorder image
│       ├── Dockerfile
│       ├── requirements.txt
│       └── main.py                     # FastAPI app: FFmpeg recording control
│
└── frontend/                           # Dashboard (React SPA)
    ├── Dockerfile                      # Multi-stage: node build → nginx
    ├── nginx.conf.template             # nginx config with API + stream proxy
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
- **HTTP client**: `httpx` (async, for communicating with recorder pods and proxying streams)
- **Server**: Uvicorn

### Entry Point (`main.py`)

- Creates FastAPI app with lifespan handler
- On startup: calls `init_db()` which runs `Base.metadata.create_all` (auto-creates tables) plus lightweight migrations (e.g., `ALTER TABLE recordings ADD COLUMN IF NOT EXISTS node_name`)
- CORS middleware allows all origins
- Registers routers: cameras, nodes, recordings, settings, chatbot
- Global exception handler returns JSON errors

### Configuration (`config.py`)

Uses `pydantic-settings` to load from environment variables:

- `DATABASE_URL` → converted to `postgresql+asyncpg://` for async and plain `postgresql://` for sync
- K8s config: tries in-cluster config first, then kubeconfig file, then `~/.kube/config`
- Node IPs are **auto-discovered** by querying the K8s API for each node's `InternalIP` address, cached with a 5-minute TTL
- Defaults: 640×480 resolution, 15 fps, stream quality 70
- `DEFAULT_CAMERA_NODE` and `DEFAULT_RECORDER_NODE`: empty strings mean "let K8s scheduler decide"

### Database (`database.py`)

- **Async engine**: `create_async_engine` with `asyncpg`, pool size 10, overflow 20
- **Session factory**: `async_sessionmaker` with `expire_on_commit=False`
- **Dependency**: `get_db()` yields an `AsyncSession`, commits on success, rolls back on error
- **Context managers**: `get_db_context()` and `get_db_session()` for use in background tasks
- **Migrations**: `init_db()` runs `create_all` plus manual `ALTER TABLE` statements for columns added after initial release (e.g., `node_name` on `recordings`)
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
- Fields: camera_id, camera_name (preserved), file_path, file_name, start_time, end_time, duration_seconds, file_size_bytes, status, error_message, camera_deleted flag, **node_name** (tracks which node holds the recording file)
- Statuses: `recording`, `stopped`, `completed`, `failed`, `error`

#### `Agent` / `AgentChatMessage` (`models/agent.py`)
- Agent: UUID PK, name, slug (unique), type, provider, model, api_key_ref, system_prompt, temperature, max_tokens, channel_type, channel_config (JSON), tools (JSON array of tool IDs), status, deployment_name, service_name, node_name, cpu_limit, memory_limit, timestamps
- AgentChatMessage: UUID PK, agent_id FK, session_id, role (user/assistant/system), content, source, source_user, prompt_tokens, completion_tokens, timestamps

### Routes

#### Cameras (`routes/cameras.py`)

The main CRUD router. Key behaviors:

- **List**: Syncs K8s pod status with DB on every list call. Detects stuck "creating" cameras (>3 min timeout) and auto-stops them.
- **Create**: USB cameras deploy immediately (Deployment + Service + Recorder). Network cameras are created in `stopped` state.
- **Update**: If `source_url` changes, auto-redeploys the camera pod. Updates `device_path` to extracted IP for network cameras.
- **Delete**: Background task — marks as `deleting`, deletes K8s resources, waits for pod termination (extra 15s grace for USB), marks recordings as orphaned, then deletes DB record.
- **Start/Stop/Restart**: Creates or deletes K8s resources accordingly.
- **Recording control**: Proxies to the recorder pod's API via internal ClusterIP service. Auto-deploys recorder if not present. Fixes orphaned recordings when recorder pod is gone.
- **Stream proxy** (`GET /{camera_id}/stream`): Proxies the camera's internal MJPEG stream to the browser. Uses `httpx.AsyncClient` with streaming to relay `multipart/x-mixed-replace` content from the camera pod's ClusterIP service. Handles connection errors with a 502 response.

Duplicate prevention: checks for existing cameras with same device_path (USB) or IP address (network).

Stream URL enrichment: `stream_url` is set to the relative path `/api/cameras/{id}/stream` (not a direct NodePort URL), and `control_url` is `null` since camera services are internal.

#### Recordings (`routes/recordings.py`)

Standard CRUD. The `POST` and `PATCH` endpoints are called by the recorder service (not by users). The `POST` endpoint accepts an optional `node_name` field.

The `download` endpoint locates recording files across the cluster by querying file-server DaemonSet pods. It uses the recording's `node_name` as a hint for optimized lookup, falling back to scanning all file-server pods if the file isn't found on the hinted node.

#### Nodes (`routes/nodes.py`)

- **List/Get**: Wraps K8s node API. Returns name, IP, ready status, taints, labels, architecture.
- **Scan**: SSH into each node using `paramiko` to enumerate `/dev/video*` devices. Network scan probes common camera ports (554, 8554, 80, 8080, 8899) across the subnet with socket connection tests.

#### Agents (`routes/agents.py`)

Full CRUD for agent configuration plus lifecycle management:

- **List/Get/Create/Update/Delete**: Standard CRUD with slug uniqueness check
- **Start**: Creates K8s Deployment + ClusterIP Service using the agent image. Mounts the shared filesystem PVC. Injects agent config (ID, provider, channel config) as environment variables.
- **Stop**: Deletes K8s Deployment and Service, updates status to `stopped`
- **Restart**: Stop + Start sequence
- **Delete protection**: The main agent cannot be deleted

#### Agent Chat (`routes/agent_chat.py`)

Proxies chat messages to agent pods and manages chat history:

- **Send** (`POST /{agent_id}/send`): Saves user message, builds LLM context (system prompt + tool schemas + chat history), proxies to agent pod's `/chat/send`, saves assistant response, returns result with optional media
- **History** (`GET /{agent_id}/history`): Paginated chat history with session filter
- **Save** (`POST /{agent_id}/messages/save`): Direct message save (used by agent pods for Telegram messages and inter-agent callbacks)
- **Sessions** (`GET /{agent_id}/sessions`): List sessions with message counts
- **Session locking**: Uses per-session `asyncio.Lock` to prevent concurrent writes to the same session

#### Tools (`routes/tools.py`)

- **List tools** (`GET /api/tools/`): All tools grouped by category
- **Execute** (`POST /api/tools/execute`): Runs a tool handler and returns result + media. Used by agent pods to execute tools via the API.
- **Agent tools** (`GET/PUT /api/agents/{id}/tools`): Get/set which tools an agent has access to
- **Chat config** (`GET /api/agents/{id}/chat-config`): Returns everything an agent pod needs for autonomous operation (tool schemas, system prompt, LLM credentials)

#### Files (`routes/files.py`)

Shared filesystem API for inter-agent file exchange:

- **List/Read/Write/Upload/Delete/Info/Mkdir**: Full filesystem operations
- **Path safety**: All paths are resolved relative to `AGENT_FILES_ROOT` with traversal prevention
- **Append mode**: `POST /write` supports `append: true` for log-style files
- **Binary upload**: `POST /upload/{path}` for images, media, etc.

#### Settings (`routes/settings.py`)

- **Get**: Reads from ConfigMap + environment. Includes chatbot configuration, `default_camera_node`, and `default_recorder_node`.
- **Update**: Writes to ConfigMap. API key stored in separate K8s Secret (`falcon-eye-secrets`). API key is validated against Anthropic's API before saving.
- **Restart All**: Patches all deployments with `restartedAt` annotation. Updates CronJob schedule.
- **Clear All**: Deletes all cameras and their K8s resources.

### Services

#### K8s Service (`services/k8s.py`)

Core orchestration layer. Handles all Kubernetes API interactions:

- **`generate_deployment()`**: Creates Deployment manifest with labels, nodeSelector, Jetson tolerations, container spec from converters
- **`generate_service()`**: Creates **ClusterIP** Service with `stream` (8081) and `control` (8080) ports
- **`generate_recorder_deployment()`**: Creates Recorder Deployment with stream URL, API URL, recordings hostPath, and `NODE_NAME` env var (injected via Kubernetes Downward API using `fieldRef: {fieldPath: spec.nodeName}`)
- **`generate_recorder_service()`**: Creates ClusterIP Service for recorder
- **`create_camera_deployment()`**: Creates Deployment + Service, handles 409 conflicts by replacing. Returns deployment name, service name, and internal container ports (8081 for stream, 8080 for control)
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
| `SettingsModal` | System settings management (incl. default camera/recorder node) |
| `ChatWidget` | AI chatbot with session management, docking, resizing |
| `RecordingsPage` | Recordings grouped by camera with playback |

### API Communication

- Base URL: `window.API_URL || '/api'` — in production, nginx proxies `/api/*` to the API server
- All API calls use `fetch()` directly (no API client library)
- Camera list auto-refreshes every 5 seconds
- Recording status checks every 10 seconds
- Chat uses Server-Sent Events (SSE) for streaming responses
- Camera streams use the relative URL `/api/cameras/{id}/stream` as `<img>` source — the browser loads streams through the Dashboard → API → Camera proxy chain

### nginx Proxy (`nginx.conf.template`)

The nginx config uses `envsubst` (built into `nginx:alpine`) to inject `$API_URL`:

| Location | Pattern | Target | Special Settings |
|----------|---------|--------|-----------------|
| Stream proxy | `~ ^/api/cameras/[^/]+/stream$` | API Server | No buffering, no cache, 24-hour read/send timeouts |
| Chat SSE | `/api/chat/` | API Server | No buffering, 1-hour timeouts |
| General API | `/api/` | API Server | Standard proxy with WebSocket upgrade |
| Static files | `/` | SPA files | `try_files` fallback to `index.html`, 1-year cache for assets |

The stream proxy location uses a regex to match camera stream URLs and applies very long timeouts (86400s) to keep the continuous MJPEG stream alive without nginx closing the connection.

### Tool System

#### Registry (`tools/registry.py`)

Defines all available tools as a flat dictionary (`TOOLS_REGISTRY`). Each tool has:
- `name`: Function name used in LLM tool calls
- `description`: Shown to the LLM to decide when to use the tool
- `category`: Grouping (cameras, recording, system, agents, filesystem, alerts, external, messaging)
- `parameters`: OpenAI function calling schema (JSON Schema)
- `handler`: Dotted path to the async handler function

Helper functions:
- `get_openai_function_schema(tool_id)`: Converts a registry entry to OpenAI function calling format
- `get_tools_for_agent(tool_ids)`: Returns schemas for a list of tool IDs
- `get_tools_grouped()`: Groups all tools by category for the UI

#### Handlers (`tools/handlers.py`)

Async handler implementations for every tool. Key patterns:

- All handlers accept `**kwargs` and extract `_agent_context` for caller identity
- `execute_tool(tool_name, arguments, agent_context)` is the central dispatcher — resolves the handler by name, injects context, runs it, and returns `(result_text, media_list)`
- Internal API calls use `_api_get()` / `_api_post()` helpers that talk to `localhost:{port}`

**Camera tools**: `list_cameras`, `camera_status`, `control_camera`, `camera_snapshot` (captures MJPEG frame and uploads to shared filesystem), `analyze_camera` (sends frame to vision LLM)

**Agent tools**: `spawn_agent`, `delegate_task`, `clone_agent`
- `spawn_agent` with a task is **non-blocking**: creates the agent, starts the pod, fires off `_background_spawn_task` via `asyncio.create_task`, and returns immediately
- The background task waits for the pod, executes the task, posts the result as a system message to the caller's session, re-triggers the caller agent, then cleans up the ephemeral pod
- `delegate_task` follows the same async pattern via `_background_delegate_task`

**Background helpers**:
- `_background_spawn_task()`: Full lifecycle — execute → callback → retrigger caller → cleanup pod
- `_background_delegate_task()`: Execute → callback → retrigger caller (no cleanup)
- `_wait_and_send_task()`: Polls agent until reachable, then sends task via chat API
- `_post_callback()`: Injects a system message into the caller's session
- `_retrigger_caller()`: Sends a follow-up message to re-invoke the caller agent's LLM
- `_try_push_telegram()`: If the caller has Telegram configured, pushes the response to the chat
- `_cleanup_agent()`: Stops pod and deletes DB record

**Filesystem tools**: `file_read`, `file_write`, `file_list`, `file_delete`, `send_media` (marks files for delivery to the user's chat channel)

**External tools**: `web_search` (DuckDuckGo HTML + instant answer fallback), `custom_api_call`, `send_alert` (log to file + push to Telegram agents)

---

## Agent Pod (`scripts/agent/`)

### Technology Stack

- **Framework**: FastAPI on Uvicorn, port 8080
- **LLM**: LangGraph `create_react_agent` (ReAct pattern)
- **Providers**: `langchain-anthropic` (ChatAnthropic) and `langchain-openai` (ChatOpenAI)
- **Tool execution**: Dynamic `StructuredTool` instances built from OpenAI function schemas at runtime

### Entry Point (`main.py`)

Two modes of operation:

1. **API-proxied chat** (`POST /chat/send`): Receives pre-built messages + tool schemas + agent config from the API server. Runs the LangGraph agent loop. Returns the final response text, token counts, and collected media.

2. **Channel adapters** (`POST /process`): For Telegram and webhooks. The agent pod autonomously fetches its chat config from the API (`GET /api/agents/{id}/chat-config`), builds messages from stored history, runs the LangGraph agent, saves messages back to the API, and delivers responses via the channel.

### Telegram Integration

If `CHANNEL_TYPE=telegram`, the agent pod starts a Telegram bot on startup using `python-telegram-bot`. The bot:
- Receives messages via long polling
- Fetches chat config and history from the API
- Runs the LangGraph agent
- Sends text responses and media (photos/videos/documents) to the Telegram chat
- Saves all messages to the API for session continuity

### Tool Executor (`tool_executor.py`)

`build_tools(tools_schema, media_collector, api_url, agent_context)` dynamically constructs `StructuredTool` instances from OpenAI function schemas:

1. For each tool in the schema, creates a Pydantic model from the `parameters` definition
2. Wraps execution in an async function that `POST`s to `/api/tools/execute` on the API server
3. Collects any `media` items from the API response into the shared `media_collector` list
4. Returns a list of LangChain-compatible tools for the LangGraph agent

### LangGraph Agent Loop

The ReAct agent loop:
1. LLM receives system prompt + conversation history + available tools
2. LLM decides: respond directly or call a tool
3. If tool call: `StructuredTool._execute()` → HTTP POST to API → handler runs → result returned
4. LLM processes tool result, decides next action
5. Loop continues until LLM produces a final text response
6. Token usage is tracked from `AIMessage.usage_metadata`

---

## Camera Relay Images

### USB Camera (`camera-usb`)

- **Base**: Ubuntu 22.04 with `motion` package
- **How it works**: At deployment time, the API generates a `motion.conf` via a bash script injected as the container command. This configures the video device, resolution, framerate, stream port, and overlay text.
- **Ports**: 8081 (MJPEG stream), 8080 (Motion web control interface) — both ClusterIP only
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
- **Node tracking**: Reads `NODE_NAME` from environment (injected via K8s Downward API) and reports it to the API when creating recording records

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
4. **Report**: Notifies the main API of recording start/stop/failure via HTTP POST/PATCH to `/api/recordings/`, including `node_name` on start

Files are stored at: `/data/falcon-eye/recordings/{camera_id}/{camera_name}_{timestamp}.mp4`

---

## File-Server DaemonSet

- **Image**: `nginx:alpine`
- **Type**: DaemonSet running on every node
- **Tolerations**: `operator: Exists` — runs on all nodes including control-plane/master
- **Volume**: `/data/falcon-eye/recordings` mounted read-only at `/recordings`
- **Port**: 8080 via headless ClusterIP service
- **Purpose**: The API queries file-server pods to locate and stream recording files for download. Uses the recording's `node_name` as a hint for optimized lookup.
- **Config**: Dedicated ConfigMap (`file-server-nginx-config`) with autoindex and static file serving

---

## Docker Images

| Image | Dockerfile | Base | Key Packages |
|-------|-----------|------|-------------|
| `falcon-eye-api` | `scripts/cam-manager-py/Dockerfile` | Python 3.11-slim | FastAPI, SQLAlchemy, kubernetes, httpx |
| `falcon-eye-dashboard` | `frontend/Dockerfile` | Multi-stage: node:20 → nginx:alpine | React, Vite, Tailwind, react-markdown |
| `falcon-eye-agent` | `scripts/agent/Dockerfile` | Python 3.11-slim | LangGraph, langchain-anthropic, langchain-openai, python-telegram-bot |
| `falcon-eye-camera-usb` | `scripts/camera-usb/Dockerfile` | Ubuntu 22.04 | motion |
| `falcon-eye-camera-rtsp` | `scripts/camera-rtsp/Dockerfile` | Python 3.11-slim | FFmpeg, Flask, onvif-zeep |
| `falcon-eye-recorder` | `scripts/recorder/Dockerfile` | Python 3.11-slim | FFmpeg, FastAPI, httpx |

The file-server DaemonSet uses the standard `nginx:alpine` image directly — no custom build required.

All custom images are built for **linux/amd64** and **linux/arm64** via Docker Buildx with QEMU emulation. The container runtime automatically selects the correct platform — no user configuration required.

---

## CI/CD: GitHub Actions

### Workflow: `build-push.yml`

**Trigger**: Push to `main` branch (filtered by path), pull requests, or manual dispatch.

**Jobs** (run in parallel):

| Job | Builds | Context Path |
|-----|--------|-------------|
| `build-api` | `falcon-eye-api` | `./scripts/cam-manager-py` |
| `build-dashboard` | `falcon-eye-dashboard` | `./frontend` |
| `build-agent` | `falcon-eye-agent` | `./scripts/agent` |
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
