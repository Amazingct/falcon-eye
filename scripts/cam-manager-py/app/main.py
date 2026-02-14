"""Falcon-Eye Camera Manager - FastAPI Application"""
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import init_db, close_db
from app.routes import cameras, nodes
from app.models.schemas import HealthResponse

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    print(f"Starting {settings.app_name}...")
    await init_db()
    yield
    # Shutdown
    await close_db()
    print("Shutdown complete")


app = FastAPI(
    title=settings.app_name,
    description="Camera management API for home lab K8s clusters",
    version="1.0.0",
    lifespan=lifespan,
    redirect_slashes=False,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["root"])
async def root():
    """API information and available endpoints"""
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "endpoints": {
            "GET /health": "Health check",
            "GET /api/cameras": "List all cameras",
            "GET /api/cameras/{id}": "Get camera details",
            "POST /api/cameras": "Add new camera",
            "PATCH /api/cameras/{id}": "Update camera",
            "DELETE /api/cameras/{id}": "Delete camera",
            "POST /api/cameras/{id}/restart": "Restart camera deployment",
            "GET /api/cameras/{id}/stream-info": "Get stream URLs",
        },
        "protocols": ["usb", "rtsp", "onvif", "http"],
    }


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="ok",
        timestamp=datetime.utcnow(),
    )


# Include routers
app.include_router(cameras.router)
app.include_router(nodes.router)


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler"""
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
