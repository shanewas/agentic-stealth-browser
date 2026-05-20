# Production Docker image for Agentic Stealth Browser
FROM python:3.12-slim

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

# Default command
CMD ["python", "-c", "print('Agentic Stealth Browser ready')"]
