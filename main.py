"""
FastAPI Backend for Splitter Music Stems Separation App
"""
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
import os
from contextlib import asynccontextmanager

from routes.split import router as split_router
from config import settings

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Changed to DEBUG to see more details
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    logger.info("Starting Splitter API")
    
    # Ensure output directory exists
    os.makedirs(settings.OUTPUT_DIR, exist_ok=True)
    logger.info(f"Output directory: {settings.OUTPUT_DIR}")
    
    # Start the simple task processor in production
    if settings.is_production:
        import asyncio
        from simple_processor import simple_task_processor
        logger.info("Starting background task processor for production")
        # Start the task processor as a background task
        asyncio.create_task(simple_task_processor.start())
    
    yield
    
    # Shutdown
    logger.info("Shutting down Splitter API")
    
    # Stop the task processor in production
    if settings.is_production:
        from simple_processor import simple_task_processor
        simple_task_processor.stop()


# Create FastAPI app
app = FastAPI(
    title="Splitter API",
    description="Music stems separation API using Demucs",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_URL,
        "http://localhost:3000",  # Local development
        "https://localhost:3000",  # Local development with HTTPS
        "https://*.vercel.app",    # Vercel deployments
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(split_router, prefix="/api")


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "ok", "environment": settings.ENVIRONMENT}


@app.get("/health")
async def health_check():
    """Detailed health check endpoint"""
    try:
        # Test Redis connection
        redis_status = "ok"
        try:
            from services.redis_client import redis_client
            # Test Redis connection
            test_key = "health_check"
            redis_client.set(test_key, "test", ex=10)
            redis_client.get(test_key)
            redis_client.delete(test_key)
        except Exception as e:
            redis_status = f"error: {str(e)}"
        
        return {
            "status": "ok",
            "environment": settings.ENVIRONMENT,
            "redis": redis_status,
            "output_dir": settings.OUTPUT_DIR,
            "temp_dir": settings.TEMP_DIR
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "error", "message": str(e)}


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
