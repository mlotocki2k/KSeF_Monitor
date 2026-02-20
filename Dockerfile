FROM python:3.11-slim

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

# Create data directories for persistent storage
RUN mkdir -p /data/pdf

# Make main script executable
RUN chmod +x main.py

# Expose Prometheus metrics port
EXPOSE 8000

# Run the application
CMD ["python", "-u", "main.py"]
