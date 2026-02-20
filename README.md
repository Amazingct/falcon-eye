# Falcon-Eye

**Distributed Camera Streaming & Recording System for Kubernetes**

Stream USB, RTSP, ONVIF, and HTTP cameras through a unified web interface. Deploy to any K8s cluster with a single command.

![Dashboard Preview](docs/dashboard-preview.png)

## Features

- **Multi-Protocol Support**: USB cameras, RTSP streams, ONVIF, HTTP/MJPEG
- **One-Line Install**: Deploy to any K8s cluster in under 5 minutes
- **Web Dashboard**: Modern UI for managing cameras, viewing streams, and recording
- **Secure by Default**: Only the Dashboard is exposed externally — all other services are internal
- **Recording**: Start/stop recording per camera, download MP4 files from any node
- **Auto-Discovery**: Detects cluster nodes and available cameras (USB + network scan)
- **Node Selection**: Pin cameras to specific nodes (required for USB, optional for network)
- **AI Chatbot**: Claude-powered assistant for camera management (optional)
- **Self-Healing**: Automatic cleanup of orphaned pods and stale resources
- **ARM64 Support**: Works on Jetson, Raspberry Pi, and x86 clusters
- **Generic Design**: Works across any Kubernetes distribution (k3s, k8s, MicroK8s, etc.)

## Quick Install

```bash
curl -sSL https://raw.githubusercontent.com/Amazingct/falcon-eye/main/install.sh | bash
```

### Prerequisites

- Kubernetes cluster (K3s, K8s, MicroK8s, etc.)
- `kubectl` configured with cluster access
- At least one camera (USB, IP, or network stream)

### What Gets Installed

- **PostgreSQL**: Database for camera configurations and recordings
- **Falcon-Eye API**: Backend service (ClusterIP — internal only)
- **Falcon-Eye Dashboard**: Web UI on port 30900 (the only external service)
- **File-Server DaemonSet**: Serves recordings from every node
- **Cleanup CronJob**: Removes orphaned resources
- **RBAC**: Service accounts and permissions for K8s integration

## Usage

### Access the Dashboard

After installation, open the dashboard:

```
http://<node-ip>:30900
```

All camera management, recording, and configuration happens through the web UI.

### Add a Camera

1. Click "Add Camera" (or "Scan" to auto-discover)
2. Select camera type (USB, RTSP, HTTP, ONVIF)
3. Choose target node (required for USB, optional for network)
4. Enter source (device path, URL, or IP)
5. Click "Add"

### Camera Types

| Type | Source Format | Example |
|------|--------------|---------|
| USB | Device path | `/dev/video0` |
| RTSP | Stream URL | `rtsp://user:pass@192.168.1.100:554/stream` |
| HTTP | MJPEG URL | `http://192.168.1.100/mjpg/video.mjpg` |
| ONVIF | Camera IP | `192.168.1.100` |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  Kubernetes Cluster                          │
│                                                              │
│  ┌──────────────────────────────────────────┐               │
│  │  Dashboard (NodePort 30900)               │               │
│  │  React + Tailwind CSS + nginx             │               │
│  │  Only externally accessible service       │               │
│  └──────────────────┬───────────────────────┘               │
│                     │ /api/* proxy                           │
│                     ▼                                        │
│  ┌──────────────────────────────────────────┐               │
│  │  Falcon-Eye API (ClusterIP)               │               │
│  │  Python FastAPI — camera CRUD, K8s mgmt,  │               │
│  │  stream proxy, recording management       │               │
│  └─────┬─────────────┬──────────────┬───────┘               │
│        │             │              │                        │
│        ▼             ▼              ▼                        │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐                 │
│  │ Camera    │ │ Camera    │ │ Recorder  │                  │
│  │ Pod (USB) │ │ Pod (RTSP)│ │ Pod       │                  │
│  │ ClusterIP │ │ ClusterIP │ │ ClusterIP │                  │
│  └───────────┘ └───────────┘ └─────┬─────┘                 │
│                                     │                        │
│                                     ▼                        │
│  ┌──────────────────────────────────────────┐               │
│  │  File-Server DaemonSet (every node)       │               │
│  │  nginx:alpine — serves recordings         │               │
│  └──────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────┘
```

## API Reference

The API is internal (ClusterIP) and accessed through the Dashboard proxy at `/api/`. For local development:

```bash
kubectl port-forward svc/falcon-eye-api 8000:8000 -n falcon-eye
```

### Key Endpoints

```
GET  /api/cameras/                  # List all cameras
POST /api/cameras/                  # Add camera
GET  /api/cameras/:id               # Get camera details
GET  /api/cameras/:id/stream        # Proxy camera MJPEG stream
DELETE /api/cameras/:id             # Delete camera
POST /api/cameras/:id/start         # Start camera stream
POST /api/cameras/:id/stop          # Stop camera stream
POST /api/cameras/:id/recording/start  # Start recording
POST /api/cameras/:id/recording/stop   # Stop recording
GET  /api/recordings/               # List recordings
GET  /api/recordings/:id/download   # Download recording
GET  /api/nodes/                    # List cluster nodes
GET  /api/nodes/scan/cameras        # Scan for cameras
GET  /api/settings/                 # Get settings
PATCH /api/settings/                # Update settings
```

See [docs/API-REFERENCE.md](docs/API-REFERENCE.md) for full documentation.

## Development

### Local Test Mode

Build and deploy from local source without pushing to GitHub:

```bash
LOCAL_TEST=true bash install.sh
```

This builds all 7 Docker images from local source, imports them into k3d/k3s, and sets `imagePullPolicy: IfNotPresent` so the cluster uses your local code. Run it again after making changes to rebuild and redeploy.

### Frontend Development

Run the frontend against a live cluster for hot-reload development:

```bash
cd frontend
cp .env.example .env     # Edit VITE_API_URL or use the Vite proxy
npm install
npm run dev              # http://localhost:3001
```

The Vite proxy in `vite.config.js` forwards `/api` requests to the backend. Edit the proxy `target` to point to your API (default: `http://localhost:30800`).

### Backend Development

```bash
cd scripts/cam-manager-py
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Port-Forward (for local access to in-cluster services)

```bash
kubectl port-forward svc/falcon-eye-api 8000:8000 -n falcon-eye
```

## Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture, components, data flow |
| [INSTALL-GUIDE.md](docs/INSTALL-GUIDE.md) | Installation walkthrough, upgrade, uninstall |
| [DEVELOPER.md](docs/DEVELOPER.md) | Local development setup, LOCAL_TEST mode, building and testing |
| [USER-MANUAL.md](docs/USER-MANUAL.md) | Dashboard usage guide for end users |
| [API-REFERENCE.md](docs/API-REFERENCE.md) | Complete REST API documentation |
| [CODE-REFERENCE.md](docs/CODE-REFERENCE.md) | Source code structure and internals |
| [CONFIGURATION.md](docs/CONFIGURATION.md) | Environment variables and configuration |

## Project Structure

```
falcon-eye/
├── install.sh              # One-line installer
├── frontend/               # React dashboard
│   ├── src/
│   ├── Dockerfile
│   └── nginx.conf.template
└── scripts/
    ├── cam-manager-py/     # FastAPI backend
    │   ├── app/
    │   ├── Dockerfile
    │   └── requirements.txt
    ├── camera-usb/         # USB camera relay image
    ├── camera-rtsp/        # RTSP/ONVIF/HTTP relay image
    └── recorder/           # FFmpeg recorder image
```

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

- Built for home lab enthusiasts
- Inspired by the need for unified camera management
- Powered by Kubernetes, Python, and React

---

Made with care by [CurateLearn](https://github.com/Amazingct)
