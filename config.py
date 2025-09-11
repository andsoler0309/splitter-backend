"""
Configuration settings for the Splitter API
"""
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings"""
    
    # API Configuration
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    
    # Environment
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    
    # Directories
    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "./outputs")
    TEMP_DIR: str = os.getenv("TEMP_DIR", "./temp")
    
    # Demucs Configuration
    DEMUCS_MODEL: str = os.getenv("DEMUCS_MODEL", "htdemucs")
    
    # Memory optimization settings
    CHUNK_DURATION: int = int(os.getenv("CHUNK_DURATION", "15"))  # seconds
    MEMORY_LIMIT_MB: int = int(os.getenv("MEMORY_LIMIT_MB", "450"))  # Leave 62MB buffer for 512MB limit
    CHUNK_TIMEOUT: int = int(os.getenv("CHUNK_TIMEOUT", "600"))  # 10 minutes for chunks
    FULL_TIMEOUT: int = int(os.getenv("FULL_TIMEOUT", "1800"))  # 30 minutes for full files

    # YouTube Download Configuration
    MAX_DURATION: int = int(os.getenv("MAX_DURATION", "600"))  # 10 minutes max
    
    # Redis Configuration (for local development)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # Upstash Redis Configuration (for production)
    UPSTASH_REDIS_REST_URL: str = os.getenv("UPSTASH_REDIS_REST_URL", "")
    UPSTASH_REDIS_REST_TOKEN: str = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
    
    # Celery Configuration
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")
    
    # CORS Configuration
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:3000")
    
    @property
    def is_production(self) -> bool:
        """Check if running in production environment"""
        return self.ENVIRONMENT.lower() == "production"
    
    @property
    def effective_redis_url(self) -> str:
        """Get the effective Redis URL based on environment"""
        if self.is_production and self.UPSTASH_REDIS_REST_URL:
            return self.UPSTASH_REDIS_REST_URL
        return self.REDIS_URL
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
