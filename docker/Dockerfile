FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for rawpy (libraw) and Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libraw-dev \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY server/ .

# Expose the server port
EXPOSE 8600

# Bind to 0.0.0.0 so the container is reachable from the host/network
CMD ["python", "server.py", "--host", "0.0.0.0"]
