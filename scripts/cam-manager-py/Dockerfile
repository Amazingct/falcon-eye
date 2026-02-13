# Falcon-Eye Camera Manager - Python FastAPI
# Multi-arch build for home lab K8s clusters

FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# Production image
FROM python:3.11-slim

LABEL maintainer="Falcon <falconeye338@gmail.com>"
LABEL description="Camera management API for Falcon-Eye system (FastAPI)"
LABEL version="1.0.0"

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application
COPY app/ ./app/

# Create non-root user
RUN useradd -m -u 1001 falcon && \
    chown -R falcon:falcon /app

USER falcon

# Environment defaults
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=3000 \
    DB_HOST=postgres \
    DB_PORT=5432 \
    DB_USER=admin \
    DB_PASSWORD=changeme \
    DB_NAME=falconeye \
    K8S_NAMESPACE=falcon-eye

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:3000/health || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]
