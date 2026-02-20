# Falcon-Eye Commands

Reusable commands for development, deployment, and operations.

## Cluster Management

```bash
# Create a new k3d cluster
k3d cluster create falcon-eye --api-port 6550 -p "30800-30900:30800-30900@server:0"

# Delete the cluster
k3d cluster delete falcon-eye

# Get kubeconfig
k3d kubeconfig get falcon-eye > kubeconfig.yaml

# Check cluster status
kubectl cluster-info
kubectl get nodes -o wide
```

## Install / Update

```bash
# Fresh install (pulls images from ghcr.io)
bash install.sh

# Fresh install with local image builds (dev)
LOCAL_TEST=true bash install.sh

# Remote install (no clone needed)
curl -sSL https://raw.githubusercontent.com/Amazingct/falcon-eye/main/install.sh | bash

# Check install status
curl -sSL https://raw.githubusercontent.com/Amazingct/falcon-eye/main/install.sh | bash -s -- --status
```

## Pull Latest Images

```bash
# Pull all 7 custom images
docker pull ghcr.io/amazingct/falcon-eye-api:latest
docker pull ghcr.io/amazingct/falcon-eye-dashboard:latest
docker pull ghcr.io/amazingct/falcon-eye-recorder:latest
docker pull ghcr.io/amazingct/falcon-eye-camera-usb:latest
docker pull ghcr.io/amazingct/falcon-eye-camera-rtsp:latest
docker pull ghcr.io/amazingct/falcon-eye-agent:latest
docker pull ghcr.io/amazingct/falcon-eye-cron-runner:latest

# One-liner
for img in api dashboard recorder camera-usb camera-rtsp agent cron-runner; do docker pull ghcr.io/amazingct/falcon-eye-$img:latest; done

# Import into k3d cluster after pulling
for img in api dashboard recorder camera-usb camera-rtsp agent cron-runner; do k3d image import ghcr.io/amazingct/falcon-eye-$img:latest -c falcon-eye; done
```

## Build Images Locally

```bash
# Build all images
docker build -t ghcr.io/amazingct/falcon-eye-api:latest scripts/cam-manager-py/
docker build -t ghcr.io/amazingct/falcon-eye-dashboard:latest frontend/
docker build -t ghcr.io/amazingct/falcon-eye-recorder:latest scripts/recorder/
docker build -t ghcr.io/amazingct/falcon-eye-camera-usb:latest scripts/camera-usb/
docker build -t ghcr.io/amazingct/falcon-eye-camera-rtsp:latest scripts/camera-rtsp/
docker build -t ghcr.io/amazingct/falcon-eye-agent:latest scripts/agent/
docker build -t ghcr.io/amazingct/falcon-eye-cron-runner:latest scripts/cron-runner/

# Build + import into k3d (dev cycle)
docker build -t ghcr.io/amazingct/falcon-eye-api:latest scripts/cam-manager-py/ && \
  k3d image import ghcr.io/amazingct/falcon-eye-api:latest -c falcon-eye && \
  kubectl rollout restart deployment/falcon-eye-api -n falcon-eye
```

## Restart / Redeploy

```bash
# Restart a single deployment (pulls latest if imagePullPolicy=Always)
kubectl rollout restart deployment/falcon-eye-api -n falcon-eye
kubectl rollout restart deployment/falcon-eye-dashboard -n falcon-eye

# Restart all deployments
kubectl rollout restart deployment -n falcon-eye

# Watch rollout status
kubectl rollout status deployment/falcon-eye-api -n falcon-eye
kubectl rollout status deployment/falcon-eye-dashboard -n falcon-eye
```

## Logs

```bash
# API logs (live)
kubectl logs -f deployment/falcon-eye-api -n falcon-eye

# Dashboard logs
kubectl logs -f deployment/falcon-eye-dashboard -n falcon-eye

# Specific pod logs
kubectl logs -f <pod-name> -n falcon-eye

# All pods in namespace
kubectl logs -f -l app --all-containers -n falcon-eye

# Previous crashed container
kubectl logs <pod-name> -n falcon-eye --previous
```

## Debugging

```bash
# List all pods
kubectl get pods -n falcon-eye -o wide

# Describe a failing pod
kubectl describe pod <pod-name> -n falcon-eye

# Exec into a pod
kubectl exec -it deployment/falcon-eye-api -n falcon-eye -- bash

# Check events (useful for crash loops / scheduling issues)
kubectl get events -n falcon-eye --sort-by=.lastTimestamp

# Check resource usage
kubectl top pods -n falcon-eye
kubectl top nodes
```

## Access Services

```bash
# Dashboard:  http://localhost:30900
# API:        http://localhost:30800

# Port-forward (alternative to NodePort)
kubectl port-forward svc/falcon-eye-dashboard 8080:80 -n falcon-eye
kubectl port-forward svc/falcon-eye-api 8000:8000 -n falcon-eye

# Check service endpoints
kubectl get svc -n falcon-eye
```

## Database

```bash
# Connect to Postgres
kubectl exec -it deployment/postgres -n falcon-eye -- psql -U falcon falcon_eye

# Common queries
# \dt                          -- list tables
# SELECT * FROM agents;        -- list agents
# SELECT * FROM cameras;       -- list cameras
# SELECT count(*) FROM agent_chat_messages;  -- message count
```

## Namespace Cleanup

```bash
# Delete everything in namespace (full reset)
kubectl delete namespace falcon-eye

# Delete specific resources
kubectl delete deployment falcon-eye-api -n falcon-eye
kubectl delete pods --all -n falcon-eye

# Remove DaemonSet
kubectl delete daemonset falcon-eye-file-server -n falcon-eye
```

## Git / CI

```bash
# Push to trigger CI build
git add . && git commit -m "message" && git push

# Check image digests after CI
docker manifest inspect ghcr.io/amazingct/falcon-eye-api:latest | grep digest
```

## Frontend Dev

```bash
# Run frontend locally (hot-reload)
cd frontend && npm run dev

# Build frontend
cd frontend && npm run build

# Preview production build
cd frontend && npm run preview
```
