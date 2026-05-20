# Production Docker image for Agentic Stealth Browser
FROM python:3.12-slim

# Create non-root user (security)
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright dependencies
RUN pip install playwright aiohttp httpx
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy project
COPY . /app

# Set environment
ENV PYTHONPATH=/app
ENV STEALTH_HEADLESS=true
ENV STEALTH_REGION=japan

# Healthcheck (production requirement)
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import asyncio; from core.agent_browser import AgentBrowser; print('ok')" || exit 1

# Run as non-root
USER appuser

# Default command
CMD ["python", "-c", "print('Agentic Stealth Browser ready')"]
