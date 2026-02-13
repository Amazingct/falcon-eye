# Falcon-Eye Camera Manager
# Multi-arch build for home lab K8s clusters

FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm ci --only=production && npm cache clean --force

# Production image
FROM node:20-alpine

LABEL maintainer="Falcon <falconeye338@gmail.com>"
LABEL description="Camera management API for Falcon-Eye system"
LABEL version="1.0.0"

WORKDIR /app

# Install curl for healthchecks
RUN apk add --no-cache curl tini

# Copy dependencies from builder
COPY --from=builder /app/node_modules ./node_modules

# Copy application
COPY src/ ./src/
COPY package.json ./

# Create non-root user
RUN addgroup -g 1001 -S falcon && \
    adduser -u 1001 -S falcon -G falcon && \
    chown -R falcon:falcon /app

USER falcon

# Environment defaults
ENV NODE_ENV=production \
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

# Use tini as init system
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "src/index.js"]
