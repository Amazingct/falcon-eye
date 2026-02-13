# Falcon-Eye Camera Manager (Python FastAPI) 🎥🐍

REST API for managing cameras in the Falcon-Eye system, built with FastAPI.

## Features

- **FastAPI** with async support
- **SQLAlchemy 2.0** async ORM
- **Pydantic v2** validation
- **Multi-protocol**: USB, RTSP, ONVIF, HTTP cameras
- **Kubernetes native**: Each camera as a deployment
- **PostgreSQL**: Persistent storage

## Quick Start

### Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Set environment
cp .env.example .env
# Edit .env with your settings

# Run
uvicorn app.main:app --reload --port 3000
```

### Docker

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f cam-manager
```

### Kubernetes

```bash
# Deploy to cluster
kubectl apply -f k8s/cam-manager.yaml

# Check status
kubectl get pods -n falcon-eye -l component=manager
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | API info |
| GET | `/health` | Health check |
| GET | `/api/cameras` | List cameras |
| GET | `/api/cameras/{id}` | Get camera |
| POST | `/api/cameras` | Create camera |
| PATCH | `/api/cameras/{id}` | Update camera |
| DELETE | `/api/cameras/{id}` | Delete camera |
| POST | `/api/cameras/{id}/restart` | Restart deployment |
| GET | `/api/cameras/{id}/stream-info` | Get stream URLs |

## API Docs

FastAPI auto-generates interactive docs:

- **Swagger UI**: http://localhost:3000/docs
- **ReDoc**: http://localhost:3000/redoc

## Examples

### Add USB Camera

```bash
curl -X POST http://localhost:3000/api/cameras \
  -H "Content-Type: application/json" \
  -d '{
    "name": "office-cam",
    "protocol": "usb",
    "node_name": "ace",
    "device_path": "/dev/video0",
    "location": "Office"
  }'
```

### Add RTSP Camera

```bash
curl -X POST http://localhost:3000/api/cameras \
  -H "Content-Type: application/json" \
  -d '{
    "name": "parking",
    "protocol": "rtsp",
    "source_url": "rtsp://admin:pass@192.168.1.100:554/stream",
    "resolution": "1280x720"
  }'
```

### List Cameras

```bash
curl http://localhost:3000/api/cameras

# Filter by protocol
curl "http://localhost:3000/api/cameras?protocol=usb"

# Filter by status
curl "http://localhost:3000/api/cameras?status=running"
```

## Project Structure

```
cam-manager-py/
├── app/
│   ├── __init__.py
│   ├── main.py           # FastAPI app
│   ├── config.py         # Settings
│   ├── database.py       # DB connection
│   ├── models/
│   │   ├── camera.py     # SQLAlchemy models
│   │   └── schemas.py    # Pydantic schemas
│   ├── routes/
│   │   └── cameras.py    # API routes
│   └── services/
│       ├── k8s.py        # K8s deployment
│       └── converters.py # Protocol converters
├── k8s/
│   └── cam-manager.yaml  # K8s manifests
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| PORT | 3000 | Server port |
| DB_HOST | localhost | PostgreSQL host |
| DB_PORT | 5432 | PostgreSQL port |
| DB_USER | admin | Database user |
| DB_PASSWORD | - | Database password |
| DB_NAME | homedb | Database name |
| K8S_NAMESPACE | falcon-eye | K8s namespace |
| NODE_IP_ACE | 192.168.1.142 | Ace Jetson IP |
| NODE_IP_FALCON | 192.168.1.176 | Falcon Jetson IP |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    falcon-eye namespace                      │
│                                                              │
│  ┌──────────────────┐      ┌──────────────────┐            │
│  │   cam-manager    │─────▶│    PostgreSQL    │            │
│  │    (FastAPI)     │      │    (ace-db ns)   │            │
│  └────────┬─────────┘      └──────────────────┘            │
│           │                                                  │
│           │ K8s API                                         │
│           ▼                                                  │
│  ┌──────────────────┐  ┌──────────────────┐                │
│  │   cam-office     │  │   cam-parking    │  ...           │
│  │   (USB/Motion)   │  │   (RTSP/FFmpeg)  │                │
│  └──────────────────┘  └──────────────────┘                │
└─────────────────────────────────────────────────────────────┘
```

## Created

February 13, 2026 by Falcon 🦅
