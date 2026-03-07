FROM python:3.11-slim

LABEL org.opencontainers.image.title="KSeF Invoice Monitor" \
      org.opencontainers.image.description="Monitor faktur w Krajowym Systemie e-Faktur" \
      org.opencontainers.image.source="https://github.com/mlotocki2k/KSeF_Monitor" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="mlotocki2k"

# Set working directory
WORKDIR /app

# Install system dependencies (DejaVu fonts for PDF Polish character support)
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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
