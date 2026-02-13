# Falcon-Eye 🦅👁️

A distributed camera streaming system running on K3s cluster with Jetson nodes.

## Overview

Falcon-Eye deploys camera streams from USB webcams connected to Jetson Orin devices, making them accessible over the network via MJPEG streams.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     K3s Cluster                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │   k3s-1     │  │   k3s-2     │  │   ace       │◄─USB Cam │
│  │  (master)   │  │  (worker)   │  │  (Jetson)   │          │
│  └─────────────┘  └─────────────┘  └──────┬──────┘          │
│                                           │                  │
│                              ┌────────────┴────────────┐    │
│                              │  falcon-eye namespace   │    │
│                              │  ┌──────────────────┐   │    │
│                              │  │   ace-camera     │   │    │
│                              │  │   (motion pod)   │   │    │
│                              │  └────────┬─────────┘   │    │
│                              │           │             │    │
│                              │  NodePort: 30881       │    │
│                              └─────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## Components

### ace-camera
- **Node:** ace (192.168.1.142)
- **Camera:** Logitech UVC Camera (046d:0825)
- **Stream URL:** http://192.168.1.142:30881
- **Control URL:** http://192.168.1.142:30880
- **Resolution:** 640x480 @ 15fps
- **Format:** MJPEG

## Deployment

```bash
# Apply all manifests
kubectl apply -f manifests/

# Check status
kubectl get pods -n falcon-eye
kubectl get svc -n falcon-eye
```

## Access Streams

| Camera | Stream URL | Control URL |
|--------|-----------|-------------|
| ace-camera | http://192.168.1.142:30881 | http://192.168.1.142:30880 |

## Adding New Cameras

1. Connect USB camera to a Jetson node
2. Scan for video devices: `ls /dev/video*`
3. Copy and modify `manifests/camera-stream.yaml`
4. Update node selector and device path
5. Apply: `kubectl apply -f manifests/`

## Project Structure

```
falcon-eye/
├── README.md
├── manifests/          # Kubernetes manifests
│   └── camera-stream.yaml
├── docs/               # Documentation
└── scripts/            # Utility scripts
```

## Tech Stack

- **Container Runtime:** containerd
- **Orchestration:** K3s (Kubernetes)
- **Streaming:** Motion (MJPEG)
- **Hardware:** NVIDIA Jetson Orin Nano

## Created

February 13, 2026 by Falcon 🦅
