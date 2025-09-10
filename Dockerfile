# Use Python 3.11 as base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies required for audio processing
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    build-essential \
    ca-certificates \
    curl \
    openssl \
    libsndfile1 \
    libsox-fmt-all \
    sox \
    && rm -rf /var/lib/apt/lists/* \
    && update-ca-certificates \
    && c_rehash

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir "numpy<2.0.0" && \
    pip install --no-cache-dir -r requirements.txt

# Upgrade yt-dlp to the latest version to ensure SSL compatibility
RUN pip install --upgrade --no-cache-dir yt-dlp

# Pre-download the htdemucs model to avoid downloading during processing
# Create cache directory and download model directly
RUN mkdir -p /root/.cache/torch/hub/checkpoints && \
    cd /root/.cache/torch/hub/checkpoints && \
    curl -L -o 955717e8-8726e21a.th "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/955717e8-8726e21a.th" && \
    echo "Model downloaded successfully"

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/outputs /app/temp

# Set environment variables
ENV PYTHONPATH=/app
ENV OUTPUT_DIR=/app/outputs
ENV TEMP_DIR=/app/temp
ENV PYTHONHTTPSVERIFY=0
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV ENVIRONMENT=production
# Audio backend configuration
ENV TORCHAUDIO_BACKEND=soundfile
ENV OMP_NUM_THREADS=1

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Default command (will be overridden by docker-compose)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
