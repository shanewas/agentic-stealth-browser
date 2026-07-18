# Production Docker image for Agentic Stealth Browser
# Addresses #15/#13: non-root, volumes, healthcheck, entrypoint, proper install

# Stage 1: Install system dependencies
# ponytail: pin FROM by @sha256 digest at next release (docker inspect); deferred — no docker in authoring env
FROM python:3.12-slim AS base

# Create non-root user (security)
RUN groupadd -r appuser && useradd -r -g appuser -u 1000 appuser

# Install system dependencies for Playwright + production
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libatspi2.0-0 \
    libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright and browser
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
RUN playwright install chromium
RUN playwright install-deps chromium

# Stage 2: Application
FROM base AS app

WORKDIR /app

# Copy only necessary files (use .dockerignore for exclusions)
COPY pyproject.toml README.md ./
COPY core/ ./core/
COPY stealth/ ./stealth/
COPY behavior/ ./behavior/
COPY recovery/ ./recovery/
COPY proxy/ ./proxy/
COPY production/ ./production/
COPY sessions/ ./sessions/
COPY audit/ ./audit/
COPY linkedin/ ./linkedin/
COPY ai/ ./ai/
COPY scraping/ ./scraping/
COPY workflows/ ./workflows/
COPY plugins/ ./plugins/
COPY mcp_security.py ./

# App dir must be writable by non-root user (e.g. workflow_orchestrator checkpoints/)
RUN chown -R appuser:appuser /app

# Install the project
RUN pip install --no-cache-dir --no-deps -e .

COPY production/docker-healthcheck.py ./production/

# Create data directories for volumes
RUN mkdir -p /data/sessions /data/logs /data/screenshots /data/cookies /data/warming && \
    chown -R appuser:appuser /data

# Set environment
ENV PYTHONPATH=/app
ENV STEALTH_HEADLESS=true
ENV STEALTH_REGION=global
ENV DATA_DIR=/data

# Healthcheck (production requirement)
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD python /app/production/docker-healthcheck.py || exit 1

# Define volumes for persistent data
VOLUME ["/data/sessions", "/data/logs", "/data/screenshots", "/data/cookies", "/data/warming"]

# Run as non-root
USER appuser

# Flexible entrypoint — override with `docker run --entrypoint` for custom commands
ENTRYPOINT []

# Default: run MCP server
CMD ["python", "-m", "production.mcp_server"]
