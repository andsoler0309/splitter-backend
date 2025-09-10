"""
Job models for the Splitter API
"""
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel
from datetime import datetime


class JobStatus(str, Enum):
    """Job status enumeration"""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class StemType(str, Enum):
    """Available stem types"""
    BASS = "bass"
    DRUMS = "drums"
    VOCALS = "vocals"
    OTHER = "other"


class Job(BaseModel):
    """Job model"""
    job_id: str
    youtube_url: str
    stems: List[StemType]
    status: JobStatus = JobStatus.PENDING
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str] = None
    download_urls: Dict[str, str] = {}
    preview_urls: Dict[str, str] = {}
    payment_required: bool = True
    payment_completed: bool = False
    song_title: Optional[str] = None
    song_duration: Optional[int] = None  # in seconds


class JobUpdate(BaseModel):
    """Job update model for WebSocket notifications"""
    job_id: str
    status: JobStatus
    message: str
    progress: Optional[int] = None  # 0-100
    error_message: Optional[str] = None
    download_urls: Optional[Dict[str, str]] = None
    preview_urls: Optional[Dict[str, str]] = None
    song_title: Optional[str] = None
    song_duration: Optional[int] = None
