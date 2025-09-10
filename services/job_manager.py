"""
Job management service
"""
import json
import uuid
import hashlib
import logging
from datetime import datetime
from typing import Dict, List, Optional
from models.job import Job, JobStatus, JobUpdate, StemType
from config import settings
from services.redis_client import redis_client

logger = logging.getLogger(__name__)


class JobManager:
    """Manages job state and notifications"""
    
    def __init__(self, redis_client_instance=None):
        self.redis_client = redis_client_instance or redis_client
        
    def create_job(self, youtube_url: str, stems: List[str]) -> Job:
        """Create a new job, checking for duplicates first"""
        # Check for existing job with same URL and stems
        existing_job = self.find_existing_job(youtube_url, stems)
        if existing_job:
            # If job is stuck in processing/downloading for too long, reset it
            if existing_job.status in [JobStatus.PROCESSING, JobStatus.DOWNLOADING]:
                import time
                current_time = time.time()
                job_time = existing_job.updated_at.timestamp() if existing_job.updated_at else current_time
                
                # If job has been stuck for more than 20 minutes, reset it
                if current_time - job_time > 1200:  # 20 minutes
                    logger.warning(f"Job {existing_job.job_id} stuck in {existing_job.status} for too long, resetting")
                    existing_job = self.reset_job_status(existing_job.job_id)
                elif existing_job.status in [JobStatus.PENDING]:
                    # For pending jobs, return existing
                    return existing_job
                else:
                    # Job is actively processing, return it
                    return existing_job
            elif existing_job.status == JobStatus.COMPLETED:
                # Return completed job
                return existing_job
            elif existing_job.status == JobStatus.FAILED:
                # Reset failed jobs to allow retry
                logger.info(f"Resetting failed job {existing_job.job_id} for retry")
                existing_job = self.reset_job_status(existing_job.job_id)
        
        # If we reset an existing job, return it
        if existing_job and existing_job.status == JobStatus.PENDING:
            return existing_job
        
        # Create new job
        job_id = str(uuid.uuid4())
        now = datetime.utcnow()
        
        job = Job(
            job_id=job_id,
            youtube_url=youtube_url,
            stems=[StemType(stem) for stem in stems],
            status=JobStatus.PENDING,
            created_at=now,
            updated_at=now
        )
        
        # Store job in Redis
        self.redis_client.setex(
            f"job:{job_id}",
            3600 * 24,  # 24 hours TTL
            job.model_dump_json()
        )
        
        # Store job hash for duplicate detection
        job_hash = self._create_job_hash(youtube_url, stems)
        self.redis_client.setex(
            f"job_hash:{job_hash}",
            3600 * 2,  # 2 hours TTL for hash
            job_id
        )
        
        return job
    
    def find_existing_job(self, youtube_url: str, stems: List[str]) -> Optional[Job]:
        """Find existing job with same URL and stems"""
        job_hash = self._create_job_hash(youtube_url, stems)
        existing_job_id = self.redis_client.get(f"job_hash:{job_hash}")
        
        if existing_job_id:
            return self.get_job(existing_job_id.decode())
        
        return None
    
    def _create_job_hash(self, youtube_url: str, stems: List[str]) -> str:
        """Create hash for job deduplication"""
        # Normalize the data for consistent hashing
        normalized_stems = sorted(stems)
        hash_data = f"{youtube_url}:{':'.join(normalized_stems)}"
        return hashlib.md5(hash_data.encode()).hexdigest()
    
    def clear_processing_lock(self, job_id: str) -> bool:
        """Clear processing lock for a job"""
        processing_key = f"processing:{job_id}"
        result = self.redis_client.delete(processing_key)
        return result > 0
    
    def is_job_being_processed(self, job_id: str) -> bool:
        """Check if job is currently being processed"""
        processing_key = f"processing:{job_id}"
        return self.redis_client.exists(processing_key)
    
    def reset_job_status(self, job_id: str) -> Optional[Job]:
        """Reset a job to pending status and clear all locks"""
        job = self.get_job(job_id)
        if not job:
            return None
        
        # Clear processing lock
        self.clear_processing_lock(job_id)
        
        # Reset job status to pending
        job = self.update_job(
            job_id,
            status=JobStatus.PENDING,
            error_message="",
            download_urls={},
            preview_urls={}
        )
        
        return job
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID"""
        job_data = self.redis_client.get(f"job:{job_id}")
        if not job_data:
            return None
        
        return Job.model_validate_json(job_data)
    
    def update_job(self, job_id: str, **updates) -> Optional[Job]:
        """Update job and send notification"""
        job = self.get_job(job_id)
        if not job:
            return None
        
        # Update fields
        for key, value in updates.items():
            if hasattr(job, key):
                setattr(job, key, value)
        
        job.updated_at = datetime.utcnow()
        
        # Store updated job
        self.redis_client.setex(
            f"job:{job_id}",
            3600 * 24,
            job.model_dump_json()
        )
        
        # Send notification via Redis pub/sub
        self._send_notification(job)
        
        return job
    
    def _send_notification(self, job: Job):
        """Send job update notification"""
        update = JobUpdate(
            job_id=job.job_id,
            status=job.status,
            message=self._get_status_message(job.status),
            download_urls=job.download_urls,
            preview_urls=job.preview_urls,
            error_message=job.error_message,
            song_title=job.song_title,
            song_duration=job.song_duration
        )
        
        self.redis_client.publish(
            f"job_updates:{job.job_id}",
            update.model_dump_json()
        )
    
    def _get_status_message(self, status: JobStatus) -> str:
        """Get user-friendly status message"""
        messages = {
            JobStatus.PENDING: "Job queued for processing",
            JobStatus.DOWNLOADING: "Downloading audio from YouTube",
            JobStatus.PROCESSING: "Separating audio stems with AI",
            JobStatus.COMPLETED: "Processing completed successfully",
            JobStatus.FAILED: "Processing failed"
        }
        return messages.get(status, "Unknown status")
    
    def mark_payment_completed(self, job_id: str) -> Optional[Job]:
        """Mark payment as completed for a job"""
        return self.update_job(job_id, payment_completed=True)


# Global job manager instance
job_manager = JobManager()
