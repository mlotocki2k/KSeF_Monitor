FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application structure
COPY main.py .
COPY app/ ./app/

# Create data directory for persistent storage
RUN mkdir -p /data

# Make main script executable
RUN chmod +x main.py

# Expose Prometheus metrics port
EXPOSE 8000

# Run the application
CMD ["python", "-u", "main.py"]
