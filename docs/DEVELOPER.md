# Developer Guide

How to develop, test, and iterate on Falcon-Eye without pushing to GitHub.

## Prerequisites

- Docker Desktop (macOS) or Docker Engine (Linux)
- Node.js 18+ and npm (for frontend hot-reload)
- Python 3.11+ (for backend development outside containers)
- A running Falcon-Eye cluster (via `bash install.sh`)

## Local Test Mode

The fastest way to test changes end-to-end in a real cluster:

```bash
LOCAL_TEST=true bash install.sh
```

This:

1. Builds all 7 Docker images from your local source
2. Tags them as both `:local` and `:latest`
3. Imports them into the k3d (macOS) or k3s (Linux) cluster
4. Sets `imagePullPolicy: IfNotPresent` so the cluster uses your local builds
5. Deploys/upgrades all components

Run it again after making changes. The full cycle (build + deploy) typically takes 1–2 minutes.

### What Gets Built

| Image | Source Directory | Used By |
|-------|-----------------|---------|
| `falcon-eye-api` | `scripts/cam-manager-py/` | API deployment, cleanup CronJob |
| `falcon-eye-dashboard` | `frontend/` | Dashboard deployment |
| `falcon-eye-recorder` | `scripts/recorder/` | Recorder pods (created per-camera) |
| `falcon-eye-camera-usb` | `scripts/camera-usb/` | USB camera pods |
| `falcon-eye-camera-rtsp` | `scripts/camera-rtsp/` | RTSP/ONVIF/HTTP camera pods |
| `falcon-eye-agent` | `scripts/agent/` | AI agent pods |
| `falcon-eye-cron-runner` | `scripts/cron-runner/` | Cron runner pods |

Dynamic pods (cameras, recorders, agents) use `imagePullPolicy: IfNotPresent` by default in the API's Python code, so they also pick up the locally imported images.

### Switching Back to GitHub Images

Run the installer without `LOCAL_TEST`:

```bash
bash install.sh
```

This pulls the latest images from `ghcr.io` and sets `imagePullPolicy: Always`.

## Frontend Development

For rapid UI iteration with hot-reload (no Docker rebuild needed):

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

The dev server starts at `http://localhost:3001`.

### Connecting to the Backend

The frontend resolves the API URL in this order:

```javascript
const API_URL = import.meta.env.VITE_API_URL || window.API_URL || '/api'
```

**Option A: Vite Proxy (recommended)**

Leave `VITE_API_URL` unset in `.env`. The Vite proxy in `vite.config.js` forwards `/api` to the backend:

```javascript
proxy: {
  '/api': {
    target: 'http://localhost:30800',
    changeOrigin: true,
  }
}
```

Edit the `target` to point to your API. This avoids CORS issues since all requests go through `localhost:3001`.

**Option B: Direct URL**

Set `VITE_API_URL` in `.env`:

```
VITE_API_URL=http://localhost:30800
```

This makes the browser call the API directly. May require CORS configuration.

### Reaching the In-Cluster API

On macOS with k3d, if port 30800 was mapped when the cluster was created (the installer does this automatically for new clusters), the API is directly available at `http://localhost:30800`.

If port 30800 is not mapped (older clusters), use port-forward:

```bash
kubectl port-forward svc/falcon-eye-api 30800:8000 -n falcon-eye
```

### Frontend File Structure

```
frontend/
├── .env.example            # Sample environment config
├── .env                    # Local config (git-ignored)
├── .env.production         # Production build config
├── vite.config.js          # Dev server + proxy config
├── nginx.conf.template     # Production nginx proxy config
├── Dockerfile              # Multi-stage: node build → nginx
└── src/
    ├── main.jsx            # React root
    ├── index.css           # Tailwind + custom styles
    ├── App.jsx             # Main app (cameras, recordings, settings, chat)
    └── components/
        ├── AgentsPage.jsx  # AI agents management
        ├── AgentChat.jsx   # Agent chat interface
        └── CronJobsPage.jsx # Cron job management
```

## Backend Development

### Running Locally (Outside Cluster)

```bash
cd scripts/cam-manager-py
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Point to your cluster's PostgreSQL
export DATABASE_URL="postgresql://falcon:falcon-eye-2026@localhost:5432/falconeye"

# Port-forward PostgreSQL
kubectl port-forward svc/postgres 5432:5432 -n falcon-eye &

# Run the API
uvicorn app.main:app --reload --port 8000
```

The API auto-detects kubeconfig from `~/.kube/config` when not running in-cluster.

### Running in Docker Compose

```bash
cd scripts/cam-manager-py
docker compose up
```

This starts both the API and a local PostgreSQL. Note: K8s operations won't work unless you mount a kubeconfig.

### Key API Directories

| Path | Purpose |
|------|---------|
| `app/main.py` | FastAPI entry point, startup, routers |
| `app/config.py` | Pydantic settings (env vars) |
| `app/routes/cameras.py` | Camera CRUD, start/stop, stream proxy |
| `app/routes/agents.py` | Agent CRUD, start/stop/restart |
| `app/routes/agent_chat.py` | Chat send/history, proxies to agent pods |
| `app/routes/tools.py` | Tool listing, execution, agent tool management |
| `app/routes/files.py` | Shared filesystem API |
| `app/tools/registry.py` | Tool definitions (schemas, categories) |
| `app/tools/handlers.py` | Tool implementations (camera ops, agents, web search, filesystem) |
| `app/services/k8s.py` | K8s deployment/service CRUD |
| `app/services/converters.py` | Per-protocol container spec generators |
| `app/tasks/cleanup.py` | CronJob: orphan cleanup |

## Agent Development

### Agent Pod (`scripts/agent/`)

The agent pod runs LangGraph-powered AI agents. It has two key files:

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app: `/chat/send`, `/process`, `/health`, Telegram bot |
| `tool_executor.py` | Builds LangChain `StructuredTool` instances from OpenAI function schemas |

### Adding a New Tool

1. **Define the tool** in `scripts/cam-manager-py/app/tools/registry.py`:

```python
"my_tool": {
    "name": "my_tool",
    "description": "What this tool does (shown to the LLM)",
    "category": "my_category",
    "parameters": {
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "Parameter description"},
        },
        "required": ["param1"],
    },
    "handler": "app.tools.handlers.my_tool",
},
```

2. **Implement the handler** in `scripts/cam-manager-py/app/tools/handlers.py`:

```python
async def my_tool(param1: str, **kwargs) -> str:
    agent_ctx = kwargs.get("_agent_context", {})
    # Implementation...
    return "Result text"
```

3. **Enable on an agent**: Add the tool ID (`my_tool`) to the agent's tool list via the dashboard or API.

No changes needed on the agent pod side — tools are dynamically built from schemas at runtime.

### Testing Tools Locally

```bash
# Execute a tool directly via the API
curl -X POST http://localhost:8000/api/tools/execute \
  -H 'Content-Type: application/json' \
  -d '{"tool_name": "list_cameras", "arguments": {}}'
```

### Agent Pod Logs

```bash
# Main agent logs
kubectl logs -n falcon-eye -l component=agent -f

# Specific agent
kubectl logs -n falcon-eye deploy/agent-main-assistant -f
```

---

## Building Individual Images

To rebuild a single image and test it:

```bash
# Build
docker build -t ghcr.io/amazingct/falcon-eye-api:latest scripts/cam-manager-py/

# Import into k3d
k3d image import ghcr.io/amazingct/falcon-eye-api:latest -c falcon-eye

# Restart the deployment to pick up the new image
kubectl rollout restart deployment/falcon-eye-api -n falcon-eye
```

Make sure the deployment uses `imagePullPolicy: IfNotPresent`. If it was deployed with `LOCAL_TEST=true`, it already does. Otherwise, patch it:

```bash
kubectl patch deployment falcon-eye-api -n falcon-eye \
  --type='json' \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/imagePullPolicy","value":"IfNotPresent"}]'
```

## Useful Commands

### Logs

```bash
# API logs (follow)
kubectl logs -n falcon-eye -l app=falcon-eye-api -f

# Dashboard nginx logs
kubectl logs -n falcon-eye -l app=falcon-eye-dashboard -f

# Camera pod logs
kubectl logs -n falcon-eye -l component=camera -f

# Recorder pod logs
kubectl logs -n falcon-eye -l component=recorder -f

# Agent pod logs (all agents)
kubectl logs -n falcon-eye -l component=agent -f

# Specific agent logs
kubectl logs -n falcon-eye deploy/agent-main-assistant -f
```

### Debugging

```bash
# Shell into the API pod
kubectl exec -it -n falcon-eye deploy/falcon-eye-api -- bash

# Shell into the dashboard pod
kubectl exec -it -n falcon-eye deploy/falcon-eye-dashboard -- sh

# Check what nginx config is active
kubectl exec -n falcon-eye deploy/falcon-eye-dashboard -- cat /etc/nginx/conf.d/default.conf

# Port-forward PostgreSQL for direct DB access
kubectl port-forward svc/postgres 5432:5432 -n falcon-eye
psql postgresql://falcon:falcon-eye-2026@localhost:5432/falconeye
```

### Cluster Management

```bash
# Check all pods
kubectl get pods -n falcon-eye

# Check services and ports
kubectl get svc -n falcon-eye

# Check what images are running
kubectl get pods -n falcon-eye -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[*].image}{"\n"}{end}'

# Delete cluster and start fresh (macOS k3d)
k3d cluster delete falcon-eye
bash install.sh          # or: LOCAL_TEST=true bash install.sh

# Show installer status
bash install.sh --status
```

## Typical Development Workflows

### "I changed the API code"

```bash
LOCAL_TEST=true bash install.sh
```

Or for faster iteration on just the API:

```bash
docker build -t ghcr.io/amazingct/falcon-eye-api:latest scripts/cam-manager-py/
k3d image import ghcr.io/amazingct/falcon-eye-api:latest -c falcon-eye
kubectl rollout restart deployment/falcon-eye-api -n falcon-eye
```

### "I changed the frontend"

For quick UI tweaks, use the Vite dev server:

```bash
cd frontend && npm run dev
```

To test the production nginx build in-cluster:

```bash
docker build -t ghcr.io/amazingct/falcon-eye-dashboard:latest frontend/
k3d image import ghcr.io/amazingct/falcon-eye-dashboard:latest -c falcon-eye
kubectl rollout restart deployment/falcon-eye-dashboard -n falcon-eye
```

### "I changed the agent code"

```bash
docker build -t ghcr.io/amazingct/falcon-eye-agent:latest scripts/agent/
k3d image import ghcr.io/amazingct/falcon-eye-agent:latest -c falcon-eye
# Restart all agent pods to pick up the new image
kubectl rollout restart deployment -l component=agent -n falcon-eye
```

### "I changed a tool handler or registry"

Tool handlers run on the API pod, not the agent pod. Rebuild and restart the API:

```bash
docker build -t ghcr.io/amazingct/falcon-eye-api:latest scripts/cam-manager-py/
k3d image import ghcr.io/amazingct/falcon-eye-api:latest -c falcon-eye
kubectl rollout restart deployment/falcon-eye-api -n falcon-eye
```

### "I changed the camera relay or recorder"

These images are used by dynamically created pods. Build, import, then restart the camera:

```bash
docker build -t ghcr.io/amazingct/falcon-eye-camera-rtsp:latest scripts/camera-rtsp/
k3d image import ghcr.io/amazingct/falcon-eye-camera-rtsp:latest -c falcon-eye
# Stop and start the camera from the dashboard to pick up the new image
```

### "I want a completely fresh cluster"

```bash
k3d cluster delete falcon-eye
LOCAL_TEST=true bash install.sh
```

Choose option 1 ("Create a new cluster") when prompted.

## CI/CD Pipeline

Pushing to `main` triggers GitHub Actions (`.github/workflows/build-push.yml`) which builds all images for `linux/amd64` and `linux/arm64` and pushes to `ghcr.io`. Users running `bash install.sh` (without `LOCAL_TEST`) pull these images.

The pipeline is not required for local development — `LOCAL_TEST=true` bypasses it entirely.
