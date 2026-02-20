# Installation Guide

## Philosophy

Falcon-Eye is designed for **one-command installation**. Run the installer, open the dashboard, and manage everything from the web UI. No YAML editing, no manual K8s configuration.

## Prerequisites

- A Linux machine (amd64 or arm64 — including NVIDIA Jetson)
- Internet access (to pull container images from `ghcr.io`)
- **One of**:
  - An existing Kubernetes cluster with `kubectl` configured
  - A machine where you can install k3s (the installer can do this for you)
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
| **1) Install k3s** | Installs k3s on the local machine (single-node setup). Sets up kubeconfig at `~/.kube/config` |
| **2) Paste kubeconfig** | Lets you paste an existing kubeconfig for a remote cluster |
| **3) Exit** | Exit and configure `kubectl` manually |

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

## Local Development Access

Since the API is not exposed externally, use `kubectl port-forward` for local development or debugging:

```bash
# Access the API locally
kubectl port-forward svc/falcon-eye-api 8000:8000 -n falcon-eye

# Access PostgreSQL locally
kubectl port-forward svc/postgres 5432:5432 -n falcon-eye
```

## Checking Status

```bash
curl -sSL https://raw.githubusercontent.com/Amazingct/falcon-eye/main/install.sh | bash -s -- --status
```

Shows: dashboard URL, pod status, image versions, and quick commands.

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

### Optional (created via Settings page)
- Secret: `falcon-eye-secrets` (Anthropic API key)
