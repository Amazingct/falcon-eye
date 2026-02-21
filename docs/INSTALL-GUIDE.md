# Installation Guide

## Philosophy

Falcon-Eye is designed for **one-command installation**. Run the installer, open the dashboard, and manage everything from the web UI. No YAML editing, no manual K8s configuration.

## Prerequisites

- Linux (amd64 or arm64 — including NVIDIA Jetson) or macOS (via k3d)
- Internet access (to pull container images from `ghcr.io`)
- **One of**:
  - An existing Kubernetes cluster with `kubectl` configured
  - A Linux machine where you can install k3s (the installer can do this for you)
  - macOS with Docker Desktop (the installer creates a k3d cluster automatically)
- For USB cameras: the cameras must be physically connected to a cluster node

## One-Line Install

```bash
curl -sSL https://raw.githubusercontent.com/Amazingct/falcon-eye/main/install.sh | bash
```

All images are built for both `linux/amd64` and `linux/arm64`. The container runtime automatically selects the correct architecture — no user action needed.

## What the Installer Does

The installer runs 9 steps, with an optional step 3.5 for configuration:

### Step 1/9: Check Prerequisites

- Checks if `kubectl` is installed; if not, auto-installs it for the detected OS/architecture
- Tests cluster connectivity via `kubectl cluster-info`
- If no cluster is reachable, offers three options:

| Option | Description |
|--------|-------------|
| **1) Create a new cluster** | On Linux: installs k3s. On macOS: installs k3d (k3s-in-Docker) with ports 30800 and 30900 mapped |
| **2) Connect to existing** | Choose from detected kubectl contexts or paste a kubeconfig manually |

### Step 2/9: Check Existing Installation

- Checks if the `falcon-eye` namespace exists
- If `falcon-eye-api` deployment exists → marks as **upgrade** (will pull latest images)
- Otherwise → **fresh install**

### Step 3/9: Detect Cluster Nodes

- Lists all cluster nodes with name, status, and IP
- Shows node count

### Step 3.5/9: Optional Configuration (Interactive Only)

Only runs in interactive mode and on fresh installs. Skipped during upgrades or piped installs.

**Node Selection** (multi-node clusters only):

For each component, you can choose which node to deploy to:
- PostgreSQL (needs stable storage)
- API Server
- Dashboard
- Camera Streams (default node for new cameras)
- Recordings (default node for recorder pods — useful for centralizing storage)

Option `0` = let Kubernetes auto-assign (recommended for most setups).

**AI Chatbot**:

Prompts for an Anthropic API key. If provided, enables the AI chatbot in the dashboard. Can be configured later via the Settings page.

### Step 4/9: Create Namespace

Creates the `falcon-eye` namespace (or confirms it exists).

### Step 5/9: Deploy PostgreSQL

Creates:

| Resource | Name | Details |
|----------|------|---------|
| PVC | `postgres-pvc` | 1Gi ReadWriteOnce |
| Secret | `postgres-secret` | User: `falcon`, Password: `falcon-eye-2026`, DB: `falconeye` |
| Deployment | `postgres` | postgres:15-alpine, 1 replica |
| Service | `postgres` | ClusterIP on port 5432 |

On fresh install, waits for PostgreSQL to be ready (up to 120s).

### Step 6/9: Deploy API Server

Creates:

| Resource | Name | Details |
|----------|------|---------|
| ConfigMap | `falcon-eye-config` | All application configuration |
| Deployment | `falcon-eye-api` | API image, port 8000, recordings hostPath mount |
| Service | `falcon-eye-api` | **ClusterIP** (internal only — accessed via Dashboard proxy) |
| ServiceAccount | `falcon-eye-sa` | For K8s API access |
| ClusterRole | `falcon-eye-role` | CRUD on pods, deployments, services, configmaps, secrets, nodes, cronjobs, jobs |
| ClusterRoleBinding | `falcon-eye-binding` | Binds SA to ClusterRole |

On upgrade, triggers `kubectl rollout restart` to pull the latest image.

### Step 7/9: Deploy Dashboard

Creates:

| Resource | Name | Details |
|----------|------|---------|
| Deployment | `falcon-eye-dashboard` | Dashboard image, port 80, `API_URL` env var |
| Service | `falcon-eye-dashboard` | **NodePort 30900** — the only externally accessible service |

On upgrade, triggers rollout restart.

### Step 8/9: Deploy File-Server DaemonSet

Creates:

| Resource | Name | Details |
|----------|------|---------|
| ConfigMap | `file-server-nginx-config` | nginx config for static file serving |
| DaemonSet | `falcon-eye-file-server` | nginx:alpine, runs on **every** node, serves recordings read-only |
| Service | `falcon-eye-file-server` | Headless ClusterIP on port 8080 |

The file-server runs on every node (including master/control-plane) so the API can locate and stream recording files regardless of which node the recorder pod used.

### Step 9/9: Deploy Cleanup CronJob

Creates:

| Resource | Name | Details |
|----------|------|---------|
| CronJob | `falcon-eye-cleanup` | Runs every 2 minutes (configurable), uses API image with cleanup command |

## After Installation

The installer prints the access URL:

```
📊 Dashboard:  http://<node-ip>:30900
```

Open the dashboard in your browser. **All further configuration** — adding cameras, managing recordings, setting up the AI chatbot — happens through the dashboard UI.

> **Note**: The API and all other services are internal to the cluster. Only the Dashboard is accessible from your browser. The Dashboard proxies all API and stream requests securely.

## Upgrade vs Fresh Install

| Behavior | Fresh Install | Upgrade |
|----------|---------------|---------|
| Namespace | Created | Reused |
| PostgreSQL | Deployed + waited | Resources updated (data preserved via PVC) |
| API/Dashboard | Deployed | `kubectl apply` + `rollout restart` to pull latest |
| File-Server | Deployed | Updated (DaemonSet rolls out on all nodes) |
| Node selection | Prompted | Skipped (uses existing settings) |
| Configuration | Prompted | Skipped |

Upgrades are safe — all `kubectl apply` operations are idempotent. The PVC preserves database data.

## Local Test Mode

Build and deploy from local source without pushing to GitHub first:

```bash
LOCAL_TEST=true bash install.sh
```

When `LOCAL_TEST=true`:

1. All 7 Docker images are built from local source (API, dashboard, recorder, camera-usb, camera-rtsp, agent, cron-runner)
2. Images are tagged and imported into the k3d (macOS) or k3s (Linux) cluster
3. `imagePullPolicy` is set to `IfNotPresent` so Kubernetes uses the local images instead of pulling from ghcr.io
4. Dynamic pods (cameras, recorders, agents) also use the local images since they share the same tags

This is the recommended workflow for development: edit code, run `LOCAL_TEST=true bash install.sh`, and test in-cluster — no git push or CI pipeline needed.

When `LOCAL_TEST` is unset or `false`, the default behavior is unchanged — images are pulled from ghcr.io.

## Local Development Access

Since the API is not exposed externally, use `kubectl port-forward` for local development or debugging:

```bash
# Access the API locally
kubectl port-forward svc/falcon-eye-api 8000:8000 -n falcon-eye

# Access PostgreSQL locally
kubectl port-forward svc/postgres 5432:5432 -n falcon-eye
```

### Frontend Hot-Reload

Run the frontend locally with hot-reload against a live cluster:

```bash
cd frontend
cp .env.example .env     # Configure backend URL
npm install
npm run dev              # http://localhost:3001
```

The Vite proxy in `vite.config.js` forwards `/api` requests to the backend. Edit the proxy `target` to point to your API.

## Checking Status

```bash
curl -sSL https://raw.githubusercontent.com/Amazingct/falcon-eye/main/install.sh | bash -s -- --status
```

Shows: dashboard URL, pod status, image versions, and quick commands.

## Troubleshooting

### macOS: k3d cluster creation fails with `bufio.Scanner: token too long`

```
ERRO Failed Cluster Start: Failed to add one or more helper nodes:
  Node k3d-falcon-eye-serverlb failed to get ready:
  error waiting for log line `start worker processes` from node
  'k3d-falcon-eye-serverlb': stopped returning log lines:
  bufio.Scanner: token too long
ERRO Failed to create cluster >>> Rolling Back
```

This is a known k3d issue on macOS where the load balancer node produces log output that exceeds k3d's internal buffer. Common causes and fixes:

**1. Restart Docker Desktop** (fixes it most of the time)

Docker Desktop can get into a bad state where containers produce excessive logs. Restart it from the menu bar icon, then retry.

**2. Clean up stale state**

If a previous cluster left behind broken containers or volumes:

```bash
k3d cluster delete falcon-eye 2>/dev/null
docker volume prune -f
docker system prune -f
bash install.sh
```

**3. Port conflict**

Something else may be using the ports k3d needs. Check with:

```bash
lsof -i :30800 -i :30900 -i :6443
```

Kill anything occupying those ports before retrying.

**4. Increase Docker Desktop resources**

Open Docker Desktop > Settings > Resources and ensure at least **4 GB RAM** and **2 CPUs** are allocated. The default 2 GB is often not enough for k3d with Falcon-Eye.

**5. Nuclear option**

If the above don't work, reset Docker Desktop entirely: Docker Desktop > Troubleshoot > "Clean / Purge data", then retry `bash install.sh`.

### macOS: Cluster starts but pods are stuck in `Pending`

This usually means Docker Desktop doesn't have enough resources. Increase RAM to at least 4 GB in Docker Desktop > Settings > Resources.

### Linux: `install.sh` fails to install k3s

The installer needs `curl` and root access to install k3s. Run with:

```bash
curl -sSL https://raw.githubusercontent.com/Amazingct/falcon-eye/main/install.sh | sudo bash
```

### Upgrade: Pods not picking up new images

The installer restarts all deployments on upgrade, but if `imagePullPolicy` is set to `IfNotPresent` (from a previous `LOCAL_TEST` run), the cluster won't pull new images from ghcr.io. Fix by running a normal install (without `LOCAL_TEST`):

```bash
bash install.sh
```

This sets `imagePullPolicy: Always` and restarts all pods.

---

## Uninstall

```bash
kubectl delete namespace falcon-eye
```

This removes **all** Falcon-Eye resources including the database PVC. Recordings on the host filesystem (`/data/falcon-eye/recordings/`) are **not** deleted.

To also clean up cluster-wide RBAC resources:

```bash
kubectl delete clusterrole falcon-eye-role
kubectl delete clusterrolebinding falcon-eye-binding
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOCAL_TEST` | `false` | Set to `true` to build images from local source instead of pulling from ghcr.io |
| `FALCON_EYE_OWNER` | `amazingct` | GitHub owner for container images (allows forks to use their own images) |
| `ANTHROPIC_API_KEY` | *(empty)* | Anthropic API key for AI chatbot (can be set during install or via Settings page) |

## Complete K8s Resources Created

### Core Infrastructure
- Namespace: `falcon-eye`
- PVC: `postgres-pvc` (1Gi)
- Secret: `postgres-secret`
- ConfigMap: `falcon-eye-config`
- ConfigMap: `file-server-nginx-config`
- ServiceAccount: `falcon-eye-sa`
- ClusterRole: `falcon-eye-role`
- ClusterRoleBinding: `falcon-eye-binding`

### Deployments / DaemonSets
- `postgres` (PostgreSQL 15)
- `falcon-eye-api` (API server)
- `falcon-eye-dashboard` (Web UI)
- `falcon-eye-file-server` (DaemonSet — recordings file server on every node)

### Services
- `postgres` (ClusterIP:5432)
- `falcon-eye-api` (ClusterIP:8000)
- `falcon-eye-dashboard` (NodePort:30900)
- `falcon-eye-file-server` (Headless ClusterIP:8080)

### CronJobs
- `falcon-eye-cleanup` (orphan pod cleanup)

### Dynamic Resources (created per camera)
- Deployment: `cam-{name}` (camera relay)
- Service: `svc-{name}` (ClusterIP for camera stream)
- Deployment: `rec-{name}` (recorder)
- Service: `svc-rec-{name}` (ClusterIP for recorder)

### Dynamic Resources (created per agent)
- Deployment: `agent-{slug}` (LangGraph agent pod)
- Service: `svc-agent-{slug}` (ClusterIP for agent)
- PVC: `falcon-eye-agent-files` (shared filesystem, created once)

### Dynamic Resources (created per cron job)
- CronJob: `cron-{name}-{id}` (scheduled prompt execution)

### Optional (created via Settings / Agents page)
- Secret: `falcon-eye-secrets` (LLM API keys)
