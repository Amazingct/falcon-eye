# Configuration

All configuration happens through **environment variables** and the **dashboard Settings page**. After the one-command install, you can manage settings entirely from the web UI.

---

## API Server Environment Variables

These are set via the `falcon-eye-config` ConfigMap and can be changed from the Settings page or by editing the ConfigMap directly.

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://falcon:falcon-eye-2026@postgres:5432/falconeye` | PostgreSQL connection string. Auto-converted to async (`+asyncpg`) driver internally. |
| `DB_HOST` | `postgres` | Database host (used if `DATABASE_URL` is not set) |
| `DB_PORT` | `5432` | Database port |
| `DB_USER` | `falcon` | Database user |
| `DB_PASSWORD` | `falcon-eye-2026` | Database password |
| `DB_NAME` | `falconeye` | Database name |

### Server

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | `Falcon-Eye Camera Manager` | Application name |
| `DEBUG` | `false` | Enable debug mode (verbose SQL logging) |
| `HOST` | `0.0.0.0` | API bind address |
| `PORT` | `8000` | API bind port |

### Kubernetes

| Variable | Default | Description |
|----------|---------|-------------|
| `K8S_NAMESPACE` | `falcon-eye` | Kubernetes namespace for all resources |
| `K8S_CONFIG_PATH` | *(empty)* | Path to kubeconfig file (if not using in-cluster config) |
| `K8S_API_SERVER` | *(empty)* | K8s API server URL (for token-based auth) |
| `K8S_TOKEN` | *(empty)* | K8s bearer token (for token-based auth) |

K8s config resolution order:
1. `K8S_CONFIG_PATH` (explicit kubeconfig file)
2. `K8S_API_SERVER` + `K8S_TOKEN` (token-based auth)
3. In-cluster config (when running as a pod with ServiceAccount)
4. Default `~/.kube/config`

### Camera Defaults

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_RESOLUTION` | `640x480` | Default resolution for new cameras |
| `DEFAULT_FRAMERATE` | `15` | Default FPS for new cameras |
| `DEFAULT_STREAM_QUALITY` | `70` | MJPEG stream quality (1–100) |
| `DEFAULT_CAMERA_NODE` | *(empty)* | Default node for camera pods (empty = K8s auto-assigns) |
| `DEFAULT_RECORDER_NODE` | *(empty)* | Default node for recorder pods (empty = K8s auto-assigns) |

### Node Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `JETSON_NODES` | `[]` | JSON list of node names that are NVIDIA Jetson devices. Pods scheduled to these nodes get a `dedicated=jetson:NoSchedule` toleration. Example: `["ace", "falcon"]` |

---

## ConfigMap: `falcon-eye-config`

The Settings page reads and writes to this ConfigMap. It stores:

| Key | Example Value | Description |
|-----|--------------|-------------|
| `DEFAULT_RESOLUTION` | `640x480` | Default camera resolution |
| `DEFAULT_FRAMERATE` | `15` | Default camera FPS |
| `DEFAULT_CAMERA_NODE` | *(empty)* | Default node for cameras (empty = auto-assign) |
| `DEFAULT_RECORDER_NODE` | *(empty)* | Default node for recorders (empty = auto-assign) |
| `CLEANUP_INTERVAL` | `*/2 * * * *` | Cron schedule for cleanup job |
| `CREATING_TIMEOUT_MINUTES` | `3` | Auto-stop cameras stuck in "creating" |
| `CHATBOT_TOOLS` | `list_cameras,get_camera,list_nodes` | Comma-separated list of enabled chatbot tools |

---

## Secret: `falcon-eye-secrets`

Created via the Settings page or installer when you configure API keys:

| Key | Description |
|-----|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key for AI agents |
| `OPENAI_API_KEY` | OpenAI API key for AI agents |

The API deployment is automatically patched to mount this secret and restarted to pick it up. Agent pods also receive the relevant key when the API proxies chat requests.

---

## Camera Relay Pod Environment Variables

These are set automatically by the API server when creating camera deployments.

### USB Camera (Motion)

Configuration is injected as a runtime-generated `motion.conf`. The relevant parameters:

| Parameter | Source | Description |
|-----------|--------|-------------|
| `videodevice` | Camera's `device_path` | e.g., `/dev/video0` |
| `width` / `height` | Camera's `resolution` | e.g., `640` / `480` |
| `framerate` | Camera's `framerate` | e.g., `15` |
| `stream_port` | Always `8081` | MJPEG stream port |
| `stream_quality` | Always `70` | JPEG quality |
| `webcontrol_port` | Always `8080` | Motion control API port |
| `text_left` | `FALCON-EYE-{CAMERA_LABEL}` | Overlay text (camera name) |

### RTSP/ONVIF/HTTP Camera

| Variable | Description |
|----------|-------------|
| `RTSP_URL` | Source URL (RTSP, ONVIF, or HTTP). For ONVIF, the relay resolves it to RTSP internally. |
| `WIDTH` | Target width (from camera resolution) |
| `HEIGHT` | Target height (from camera resolution) |
| `FPS` | Target framerate |
| `CAMERA_LABEL` | Camera name (uppercase, hyphens instead of spaces) |

---

## Recorder Pod Environment Variables

Set automatically when creating recorder deployments:

| Variable | Default | Description |
|----------|---------|-------------|
| `CAMERA_ID` | *(from camera)* | Camera UUID |
| `CAMERA_NAME` | *(from camera)* | Camera display name |
| `STREAM_URL` | *(varies)* | URL to record from (see below) |
| `API_URL` | `http://falcon-eye-api:8000` | Main API URL for reporting recordings |
| `RECORDINGS_PATH` | `/recordings` | Base path for recording files (mapped to hostPath) |
| `SEGMENT_DURATION` | `3600` | Maximum recording duration in seconds (1 hour) |
| `NODE_NAME` | *(auto-injected)* | Kubernetes node where the pod is running. Injected via the Downward API (`spec.nodeName`). Sent to the API when creating recording records so files can be located later. |

### Stream URL Logic

The recorder's `STREAM_URL` is determined by protocol:

| Camera Protocol | Stream URL | Reason |
|----------------|-----------|--------|
| `usb` | `http://svc-{name}.falcon-eye.svc.cluster.local:8081/` | Records from Motion's MJPEG stream (ClusterIP) |
| `rtsp` / `onvif` | Camera's original `source_url` (e.g., `rtsp://...`) | Records directly from source for best quality (no double-encoding) |
| `http` (fallback) | Internal ClusterIP service URL | Fallback to relay service |

---

## Dashboard Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `API_URL` | `http://falcon-eye-api:8000` | Backend API URL (used by nginx proxy, not by browser) |

The nginx config template uses `envsubst` to inject this at container startup.

### nginx Proxy Locations

The Dashboard's nginx configuration proxies all API and stream requests:

| Location | Target | Special Settings |
|----------|--------|-----------------|
| `/api/*` | API Server | Standard proxy with WebSocket upgrade |
| `/api/chat/*` | API Server | SSE-specific: no buffering, 1-hour timeouts |
| `/api/cameras/{id}/stream` | API Server | No buffering, no cache, 24-hour timeouts for long-lived MJPEG streams |
| `/` | Static files | SPA with `try_files` fallback to `index.html` |

---

## Cleanup CronJob Environment Variables

The cleanup job inherits the same environment as the API server (via ConfigMap):

| Variable | Used For |
|----------|----------|
| `DATABASE_URL` | Connecting to PostgreSQL to query cameras and fix recordings |
| `K8S_NAMESPACE` | Namespace to scan for orphaned resources |

---

## File-Server DaemonSet

The file-server runs as a DaemonSet on every node with a dedicated nginx configuration:

| Setting | Value | Description |
|---------|-------|-------------|
| Image | `nginx:alpine` | Lightweight nginx |
| Port | `8080` | HTTP port for serving files |
| Volume | `/data/falcon-eye/recordings` | Mounted read-only as `/recordings` |
| Tolerations | `operator: Exists` | Runs on all nodes including control-plane |
| Service | Headless ClusterIP | Individual pods addressable by hostname |

The ConfigMap `file-server-nginx-config` provides the nginx configuration for serving static recording files with autoindex enabled.

---

## Agent Pod Environment Variables

Set automatically when creating agent deployments:

| Variable | Description |
|----------|-------------|
| `AGENT_ID` | Agent UUID (used to fetch config and save messages) |
| `API_URL` | API server URL (e.g., `http://falcon-eye-api:8000`) |
| `CHANNEL_TYPE` | `telegram`, `webhook`, or empty |
| `CHANNEL_CONFIG` | JSON string with channel-specific config (e.g., bot token, chat ID) |
| `AGENT_FILES_ROOT` | Shared filesystem mount path (default: `/agent-files`) |

### Agent LLM Configuration

LLM credentials are **not** stored as pod environment variables. Instead:
- For **dashboard chat**: The API resolves the key and passes it to the agent pod in the chat request payload
- For **Telegram/webhook**: The agent pod fetches its config from `GET /api/agents/{id}/chat-config`, which includes the resolved API key

This keeps secrets centralized in the API pod.

---

## Shared Filesystem (Agent Files)

| Setting | Value | Description |
|---------|-------|-------------|
| PVC Name | `falcon-eye-agent-files` | Persistent Volume Claim |
| Size | 1Gi | Default storage size |
| Mount Path | `/agent-files` | Mounted on API and all agent pods |
| API Prefix | `/api/files/` | REST API for file operations |
| Env Variable | `AGENT_FILES_ROOT` | Override mount path (default: `/agent-files`) |

---

## Container Images

Image names can be overridden via environment variables (useful for forks or private registries):

| Variable | Default |
|----------|---------|
| `CAMERA_USB_IMAGE` | `ghcr.io/amazingct/falcon-eye-camera-usb:latest` |
| `CAMERA_RTSP_IMAGE` | `ghcr.io/amazingct/falcon-eye-camera-rtsp:latest` |
| `AGENT_IMAGE` | `ghcr.io/amazingct/falcon-eye-agent:latest` |

The recorder image is hardcoded in `k8s.py` as `ghcr.io/amazingct/falcon-eye-recorder:latest`.

---

## Install Script Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOCAL_TEST` | `false` | Set to `true` to build all images from local source and use `imagePullPolicy: IfNotPresent`. See [DEVELOPER.md](DEVELOPER.md) for details. |
| `FALCON_EYE_OWNER` | `amazingct` | GitHub owner for container image references. Change this when using a fork. |
| `ANTHROPIC_API_KEY` | *(empty)* | Anthropic API key for AI agents. Can also be configured later via the Agents page. |
| `OPENAI_API_KEY` | *(empty)* | OpenAI API key for AI agents. Can also be configured later via the Agents page. |
