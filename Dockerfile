FROM python:3.11-slim@sha256:543d6cace00ffc96bc95d332493bb28a4332c6dd614aab5fcbd649ae8a7953d9

# Set working directory
WORKDIR /app

# Install system dependencies:
#   fonts-dejavu-core  - DejaVu fonts for PDF Polish character support
#   gcc, libcairo2-dev, pkg-config - build deps for xhtml2pdf (pycairo)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    gcc \
    libcairo2-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Remove build-only dependencies to keep image smaller
RUN apt-get purge -y --auto-remove gcc pkg-config libcairo2-dev

# Copy application structure
COPY main.py .
COPY app/ ./app/

# Create non-root user for security
RUN useradd -r -u 1000 -m ksef

# Create data directories for persistent storage
RUN mkdir -p /data/pdf && chown -R ksef:ksef /data

# Copy and set up entrypoint (runs as root, then drops to ksef)
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Make main script executable
RUN chmod +x main.py

# Set ownership of app directory
RUN chown -R ksef:ksef /app

# Expose Prometheus metrics port
EXPOSE 8000

# Health check via Prometheus metrics endpoint
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/metrics', timeout=5)" || exit 1

# Entrypoint fixes /data ownership on bind mount, then drops to ksef user
ENTRYPOINT ["/entrypoint.sh"]
