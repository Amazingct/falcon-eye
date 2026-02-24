# Falcon-Eye Camera Manager - Python FastAPI
# Multi-arch build for home lab K8s clusters

FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies using pip (more reliable for multi-arch)
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# Production image
FROM python:3.11-slim

LABEL maintainer="Falcon <falconeye338@gmail.com>"
LABEL description="Camera management API for Falcon-Eye system (FastAPI)"
LABEL version="1.0.0"

WORKDIR /app

# Install runtime dependencies (ffmpeg for video transcoding)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user first
RUN useradd -m -u 1001 falcon

# Copy Python packages from builder to falcon user's local
COPY --from=builder /root/.local /home/falcon/.local
RUN chown -R falcon:falcon /home/falcon/.local

# Copy application
COPY app/ ./app/
RUN chown -R falcon:falcon /app

USER falcon

# Set PATH for falcon user
ENV PATH=/home/falcon/.local/bin:$PATH

# Environment defaults
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    DB_HOST=postgres \
    DB_PORT=5432 \
    DB_USER=falcon \
    DB_PASSWORD=falcon-eye-2026 \
    DB_NAME=falconeye \
    K8S_NAMESPACE=falcon-eye

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
