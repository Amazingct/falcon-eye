# 🦅 Falcon-Eye Documentation

**Falcon-Eye** is a distributed camera streaming and recording system for Kubernetes. It manages USB and network (RTSP/ONVIF/HTTP) cameras across multiple nodes, providing live MJPEG streams via a web dashboard with recording capabilities and an AI chatbot assistant.

## Quick Start

One command. That's it.

```bash
curl -sSL https://raw.githubusercontent.com/Amazingct/falcon-eye/main/install.sh | bash
```

Open the dashboard URL printed at the end, and manage everything from the web UI.

## Documentation Index

| Document | Description | Audience |
|----------|-------------|----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture, components, data flow, K8s resource model | Developers, Architects |
| [INSTALL-GUIDE.md](INSTALL-GUIDE.md) | Step-by-step installation walkthrough, upgrade, uninstall | Operators, DevOps |
| [USER-MANUAL.md](USER-MANUAL.md) | How to use the dashboard, add cameras, record video | End Users |
| [API-REFERENCE.md](API-REFERENCE.md) | Complete REST API documentation with examples | Developers |
| [CODE-REFERENCE.md](CODE-REFERENCE.md) | Source code structure, component internals, CI/CD | Contributors |
| [CONFIGURATION.md](CONFIGURATION.md) | All environment variables and configuration options | Operators, Developers |

## Key Features

- **Multi-protocol support**: USB, RTSP, ONVIF, HTTP/MJPEG cameras
- **Multi-node**: Distribute cameras across Kubernetes cluster nodes
- **Live streaming**: MJPEG streams viewable directly in the browser
- **Recording**: Start/stop recording with FFmpeg, download MP4 files
- **Camera scanning**: Auto-discover USB devices and network cameras
- **AI Chatbot**: Claude-powered assistant for camera management (optional)
- **Self-healing**: Automatic cleanup of orphaned pods and stale resources
- **Multi-arch**: Runs on both amd64 and arm64 (including NVIDIA Jetson) — container runtime auto-selects the right image

## Repository

[https://github.com/Amazingct/falcon-eye](https://github.com/Amazingct/falcon-eye)
