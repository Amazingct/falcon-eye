# Falcon-Eye Camera Manager - Python FastAPI
# Multi-arch build for home lab K8s clusters

FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
ENV POETRY_HOME=/opt/poetry \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1
RUN curl -sSL https://install.python-poetry.org | python3 - && \
    ln -s /opt/poetry/bin/poetry /usr/local/bin/poetry

# Copy Poetry files
COPY pyproject.toml poetry.lock* ./

# Generate lock file if not present, then install dependencies
RUN poetry lock --no-update 2>/dev/null || true && \
    poetry install --no-root --only main

# Copy application
COPY app/ ./app/

# Install the project itself
RUN poetry install --only main


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

# Create non-root user
RUN useradd -m -u 1001 falcon

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application
COPY --from=builder /app/app ./app/

RUN chown -R falcon:falcon /app

USER falcon

# Set PATH to use virtualenv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
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
