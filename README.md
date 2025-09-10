# Splitter Music Stems Separation API

A FastAPI backend for separating music stems (bass, drums, vocals) from YouTube videos using Demucs.

## Features

- 🎵 Download audio from YouTube videos using yt-dlp
- 🔧 Separate audio stems using Facebook's Demucs
- 🚀 Fast and async REST API built with FastAPI
- 🐳 Docker support for easy deployment
- 📁 Clean file management with temporary directories
- 🛡️ Comprehensive error handling and logging
- ⚙️ Environment-based configuration

## API Endpoints

### POST /api/split

Split audio stems from a YouTube video.

**Request Body:**
```json
{
  "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "stems": ["bass", "drums", "vocals"]
}
```

**Response:**
```json
{
  "job_id": "uuid-string",
  "status": "completed",
  "download_urls": {
    "bass": "/api/download/uuid-string/uuid-string_bass.wav",
    "drums": "/api/download/uuid-string/uuid-string_drums.wav",
    "vocals": "/api/download/uuid-string/uuid-string_vocals.wav"
  },
  "message": "Successfully separated 3 stems"
}
```

### GET /api/download/{job_id}/{filename}

Download a separated stem file.

### GET /

Health check endpoint that returns `{"status": "ok"}`.

## Installation

### Local Development

1. **Clone the repository and navigate to the backend directory:**
```bash
cd backend
```

2. **Create a virtual environment:**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
```

4. **Set up environment variables:**
```bash
cp .env.example .env
# Edit .env file with your configuration
```

5. **Create necessary directories:**
```bash
mkdir -p outputs temp
```

6. **Run the application:**
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Docker Deployment

1. **Build and run with Docker Compose:**
```bash
docker-compose up --build
```

2. **Or build and run manually:**
```bash
docker build -t splitter-api .
docker run -p 8000:8000 -v $(pwd)/outputs:/outputs splitter-api
```

## Configuration

Configure the application using environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `OUTPUT_DIR` | Directory for output files | `/outputs` |
| `TEMP_DIR` | Directory for temporary files | `/tmp/splitter` |
| `DEMUCS_MODEL` | Demucs model to use | `htdemucs` |
| `MAX_DURATION` | Maximum video duration (seconds) | `600` |

## Project Structure

```
backend/
├── main.py                 # FastAPI application entry point
├── config.py              # Configuration settings
├── requirements.txt       # Python dependencies
├── Dockerfile            # Docker configuration
├── docker-compose.yml    # Docker Compose configuration
├── .env.example          # Environment variables template
├── routes/
│   ├── __init__.py
│   └── split.py          # Split endpoint implementation
└── services/
    ├── __init__.py
    ├── youtube_service.py # YouTube download service
    └── demucs_service.py  # Demucs separation service
```

## Dependencies

- **FastAPI**: Modern web framework for building APIs
- **yt-dlp**: YouTube video/audio downloader
- **Demucs**: Facebook's music source separation toolkit
- **PyTorch**: Required for Demucs
- **Uvicorn**: ASGI server for running FastAPI

## Usage Examples

### Using curl

```bash
# Split stems from a YouTube video
curl -X POST "http://localhost:8000/api/split" \
     -H "Content-Type: application/json" \
     -d '{
       "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
       "stems": ["bass", "drums", "vocals"]
     }'

# Download a separated stem
curl -O "http://localhost:8000/api/download/uuid-string/uuid-string_bass.wav"
```

### Using Python requests

```python
import requests

# Split audio
response = requests.post(
    "http://localhost:8000/api/split",
    json={
        "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "stems": ["bass", "drums", "vocals"]
    }
)

result = response.json()
print(f"Job ID: {result['job_id']}")

# Download stems
for stem, url in result['download_urls'].items():
    file_response = requests.get(f"http://localhost:8000{url}")
    with open(f"{stem}.wav", "wb") as f:
        f.write(file_response.content)
```

## Error Handling

The API provides comprehensive error handling for common scenarios:

- **Invalid YouTube URL**: Returns 422 with validation error
- **Video too long**: Returns 422 if video exceeds `MAX_DURATION`
- **Download failure**: Returns 500 with error details
- **Demucs separation failure**: Returns 500 with error details
- **File not found**: Returns 404 for download requests

## Logging

The application uses Python's built-in logging module with INFO level by default. Logs include:

- Request processing steps
- Download and separation progress
- Error details with stack traces
- File cleanup operations

## Performance Considerations

- **Memory**: Demucs requires significant RAM for processing
- **CPU**: Separation is CPU-intensive; consider GPU support for production
- **Storage**: Temporary files are cleaned up automatically
- **Timeout**: 10-minute timeout for Demucs processing

## Security Notes

- Input validation for YouTube URLs
- File path sanitization
- Temporary file cleanup
- Resource limits (video duration)
- No file execution permissions

## License

This project is for educational purposes. Please respect YouTube's Terms of Service and copyright laws when using this application.

## Troubleshooting

### Common Issues

1. **Demucs not found**: Ensure PyTorch and Demucs are properly installed
2. **FFmpeg missing**: Install FFmpeg for audio processing
3. **Permission errors**: Check directory permissions for output/temp folders
4. **Memory errors**: Reduce video length or increase available RAM
5. **SSL Certificate errors**: See SSL troubleshooting section below

### SSL Certificate Issues

If you encounter SSL certificate verification errors when downloading from YouTube:

**Quick Fix (Development only):**
```bash
# Run the SSL debug script
./debug_ssl.sh
```

**Manual troubleshooting:**
```bash
# Test SSL connectivity
python test_ssl.py

# Check container logs
docker-compose logs splitter-api

# Enter container for debugging
docker-compose exec splitter-api bash
```

**Common SSL Error Solutions:**

1. **Certificate verify failed**: The app includes fallback SSL options that should handle most cases automatically.

2. **Corporate firewall/proxy**: If you're behind a corporate firewall, you may need to configure proxy settings:
   ```bash
   export HTTP_PROXY=http://your-proxy:port
   export HTTPS_PROXY=http://your-proxy:port
   ```

3. **Outdated certificates**: Rebuild the Docker container to get latest certificates:
   ```bash
   docker-compose build --no-cache
   ```

4. **Network restrictions**: Some networks block YouTube access. Test with:
   ```bash
   curl -I https://www.youtube.com
   ```

### Debug Mode

Run with debug logging:
```bash
export PYTHONPATH=/app
python -m uvicorn main:app --log-level debug
```
