# 🦅 Falcon-Eye

**Distributed Camera Streaming System for Home Lab Kubernetes Clusters**

Stream USB, RTSP, ONVIF, and HTTP cameras through a unified web interface. Deploy to any K8s cluster with a single command.

![Dashboard Preview](docs/dashboard-preview.png)

## ✨ Features

- **Multi-Protocol Support**: USB cameras, RTSP streams, ONVIF, HTTP/MJPEG
- **One-Line Install**: Deploy to any K8s cluster in under 5 minutes
- **Web Dashboard**: Modern UI for managing cameras and viewing streams
- **Auto-Discovery**: Detects cluster nodes and available cameras
- **Node Selection**: Pin cameras to specific nodes (USB cameras need physical connection)
- **Live Gallery**: View all streams in a responsive grid layout
- **ARM64 Support**: Works on Jetson, Raspberry Pi, and x86 clusters

## 🚀 Quick Install

```bash
curl -sSL https://raw.githubusercontent.com/curatelearn-dev/falcon-eye/main/install.sh | bash
```

### Prerequisites

- Kubernetes cluster (K3s, K8s, MicroK8s, etc.)
- `kubectl` configured with cluster access
- At least one camera (USB, IP, or network stream)

### What Gets Installed

- **PostgreSQL**: Database for camera configurations
- **Falcon-Eye API**: Backend service for camera management
- **Falcon-Eye Dashboard**: Web UI on port 30800
- **RBAC**: Service accounts and permissions for K8s integration

## 📋 Manual Installation

If you prefer manual installation:

```bash
# Clone the repository
git clone https://github.com/curatelearn-dev/falcon-eye.git
cd falcon-eye

# Create namespace
kubectl create namespace falcon-eye

# Apply manifests
kubectl apply -f manifests/

# Check status
kubectl get pods -n falcon-eye
```

## 🎯 Usage

### Access the Dashboard

After installation, open the dashboard:

```
http://<node-ip>:30800
```

### Add a Camera

1. Click "Add Camera"
2. Select camera type (USB, RTSP, HTTP, ONVIF)
3. Choose target node
4. Enter source (device path, URL, or IP)
5. Click "Add"

### Camera Types

| Type | Source Format | Example |
|------|--------------|---------|
| USB | Device path | `/dev/video0` |
| RTSP | Stream URL | `rtsp://user:pass@192.168.1.100:554/stream` |
| HTTP | MJPEG URL | `http://192.168.1.100/mjpg/video.mjpg` |
| ONVIF | Camera IP | `192.168.1.100` |

## 🔧 API Reference

Base URL: `http://<node-ip>:30850`

### Endpoints

```
GET  /health              # Health check
GET  /cameras             # List all cameras
POST /cameras             # Add camera
GET  /cameras/:id         # Get camera details
DELETE /cameras/:id       # Delete camera
POST /cameras/:id/start   # Start camera stream
POST /cameras/:id/stop    # Stop camera stream
GET  /nodes               # List cluster nodes
```

### Add Camera Example

```bash
curl -X POST http://<node-ip>:30850/cameras \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Living Room",
    "type": "usb",
    "node": "jetson-1",
    "source": "/dev/video0"
  }'
```

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Dashboard (Port 30800)             │
│                  React + Tailwind CSS               │
└─────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────┐
│                  Falcon-Eye API                      │
│               Python FastAPI (Port 30850)            │
│    • Camera CRUD    • K8s Deployment Management     │
└─────────────────────────────────────────────────────┘
        │                   │                   │
        ▼                   ▼                   ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│  USB Camera   │   │  RTSP Camera  │   │  HTTP Camera  │
│  (Node: ace)  │   │  (Node: k3s-1)│   │  (Node: k3s-2)│
│  Motion/FFmpeg│   │  FFmpeg/GStr  │   │  Passthrough  │
└───────────────┘   └───────────────┘   └───────────────┘
```

## 🛠️ Development

### Local Development

```bash
# Backend
cd scripts/cam-manager-py
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

### Building Docker Images

```bash
# Backend
cd scripts/cam-manager-py
docker build -t falcon-eye-api .

# Frontend
cd frontend
docker build -t falcon-eye-dashboard .
```

## 📂 Project Structure

```
falcon-eye/
├── install.sh              # One-line installer
├── manifests/              # K8s manifests
├── frontend/               # React dashboard
│   ├── src/
│   ├── Dockerfile
│   └── nginx.conf
└── scripts/
    └── cam-manager-py/     # FastAPI backend
        ├── app/
        ├── Dockerfile
        └── requirements.txt
```

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

MIT License - see [LICENSE](LICENSE) for details.

## 🙏 Acknowledgments

- Built for home lab enthusiasts
- Inspired by the need for unified camera management
- Powered by Kubernetes, Python, and React

---

Made with ❤️ by [CurateLearn](https://github.com/curatelearn-dev)
