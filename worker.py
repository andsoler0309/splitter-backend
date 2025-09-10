"""
Celery worker for async audio processing
"""
import os
import logging
from celery import Celery
from services.job_manager import job_manager
from services.youtube_service import YouTubeService
from services.demucs_service import DemucsService
from services.redis_client import redis_client
from models.job import JobStatus
from config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create Celery app with conditional broker URL
broker_url = settings.CELERY_BROKER_URL
result_backend = settings.CELERY_RESULT_BACKEND

# For production with Upstash, we might need to adjust Celery config
if settings.is_production and settings.UPSTASH_REDIS_REST_URL:
    # Upstash doesn't support Celery directly via REST API
    # We'll need to implement a simpler task queue or use polling
    logger.warning("Production environment detected with Upstash - using simplified task processing")

celery_app = Celery(
    'splitter_worker',
    broker=broker_url,
    backend=result_backend
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_acks_late=True,  # Acknowledge tasks only after completion
    worker_prefetch_multiplier=1,  # Process one task at a time per worker
    task_routes={
        'worker.process_audio_async': {'queue': 'audio_processing'}
    },
    task_default_queue='audio_processing',
    task_default_exchange='audio_processing',
    task_default_exchange_type='direct',
    task_default_routing_key='audio_processing'
)


@celery_app.task(bind=True)
def process_audio_async(self, job_id: str):
    """
    Async task to process audio separation
    """
    import asyncio
    
    # Check if job is already being processed
    processing_key = f"processing:{job_id}"
    
    # Try to acquire a lock for this job with a shorter expiration
    lock_acquired = redis_client.set(
        processing_key, 
        f"worker-{self.request.id}", 
        ex=900,  # Expire after 15 minutes (reduced from 30)
        nx=True  # Only set if key doesn't exist
    )
    
    if not lock_acquired:
        # Check if the existing lock is from a dead worker
        existing_lock = redis_client.get(processing_key)
        if existing_lock:
            logger.warning(f"Job {job_id} is already being processed by {existing_lock.decode()}")
        else:
            logger.info(f"Lock for job {job_id} expired, attempting to acquire")
            # Try once more
            lock_acquired = redis_client.set(processing_key, f"worker-{self.request.id}", ex=900, nx=True)
    
    if not lock_acquired:
        logger.warning(f"Job {job_id} is already being processed by another worker")
        return {"error": "Job already being processed"}
    
    logger.info(f"Worker {self.request.id} acquired lock for job {job_id}")
    
    try:
        return asyncio.run(_process_audio_internal(job_id))
    except Exception as e:
        logger.error(f"Error processing job {job_id}: {e}")
        raise
    finally:
        # Release the lock when done
        current_lock = redis_client.get(processing_key)
        if current_lock and current_lock.decode() == f"worker-{self.request.id}":
            redis_client.delete(processing_key)
            logger.info(f"Worker {self.request.id} released lock for job {job_id}")
        else:
            logger.warning(f"Lock for job {job_id} was already released or taken by another worker")


async def _process_audio_internal(job_id: str):
    """
    Async task to process audio separation
    """
    logger.info(f"Starting async processing for job {job_id}")
    
    try:
        # Check if job exists and is not already completed
        job = job_manager.get_job(job_id)
        if not job:
            logger.error(f"Job {job_id} not found in Redis")
            raise Exception(f"Job {job_id} not found")
        
        logger.info(f"Job {job_id} current status: {job.status}")
        
        if job.status in [JobStatus.COMPLETED, JobStatus.FAILED]:
            logger.info(f"Job {job_id} already completed with status {job.status}")
            return {
                "job_id": job_id,
                "status": job.status.value,
                "message": "Job already completed"
            }
        
        # Update job status to downloading
        logger.info(f"Job {job_id}: Updating status to DOWNLOADING")
        job = job_manager.update_job(job_id, status=JobStatus.DOWNLOADING)
        
        # Create services
        youtube_service = YouTubeService()
        demucs_service = DemucsService()
        
        # Create job-specific directories
        job_temp_dir = os.path.join(settings.TEMP_DIR, job_id)
        job_output_dir = os.path.join(settings.OUTPUT_DIR, job_id)
        os.makedirs(job_temp_dir, exist_ok=True)
        os.makedirs(job_output_dir, exist_ok=True)
        
        # Step 1: Download audio from YouTube
        logger.info(f"Job {job_id}: Downloading audio from YouTube: {job.youtube_url}")
        audio_file = await youtube_service.download_audio(
            url=job.youtube_url,
            output_dir=job_temp_dir
        )
        
        # Get song metadata
        metadata = await youtube_service.get_video_info(job.youtube_url)
        job_manager.update_job(
            job_id,
            song_title=metadata.get('title', 'Unknown'),
            song_duration=metadata.get('duration', 0)
        )
        
        # Step 2: Update status to processing
        job_manager.update_job(job_id, status=JobStatus.PROCESSING)
        
        # Step 3: Run Demucs separation
        logger.info(f"Job {job_id}: Running Demucs separation for stems: {[stem.value for stem in job.stems]}")
        separated_files = await demucs_service.separate_audio(
            audio_file=audio_file,
            output_dir=job_output_dir,
            requested_stems=[stem.value for stem in job.stems]
        )
        
        # Step 4: Create download and preview URLs
        download_urls = {}
        preview_urls = {}
        
        for stem in job.stems:
            stem_name = stem.value
            if stem_name in separated_files:
                # Create full download file
                stem_filename = f"{job_id}_{stem_name}.wav"
                final_path = os.path.join(job_output_dir, stem_filename)
                
                if os.path.exists(separated_files[stem_name]):
                    os.rename(separated_files[stem_name], final_path)
                    download_urls[stem_name] = f"/api/download/{job_id}/{stem_filename}"
                    
                    # Create preview (first 30 seconds)
                    preview_filename = f"{job_id}_{stem_name}_preview.wav"
                    preview_path = os.path.join(job_output_dir, preview_filename)
                    
                    # Use ffmpeg to create preview
                    import subprocess
                    subprocess.run([
                        'ffmpeg', '-i', final_path, '-t', '30', 
                        '-c:a', 'libmp3lame', '-b:a', '128k', 
                        preview_path.replace('.wav', '.mp3')
                    ], check=True)
                    
                    preview_urls[stem_name] = f"/api/preview/{job_id}/{preview_filename.replace('.wav', '.mp3')}"
        
        if not download_urls:
            raise Exception("No requested stems were successfully separated")
        
        # Step 5: Mark job as completed
        job_manager.update_job(
            job_id,
            status=JobStatus.COMPLETED,
            download_urls=download_urls,
            preview_urls=preview_urls
        )
        
        # Cleanup temporary files
        await _cleanup_temp_files(job_temp_dir)
        
        logger.info(f"Job {job_id}: Completed successfully")
        return {
            "job_id": job_id,
            "status": "completed",
            "download_urls": download_urls,
            "preview_urls": preview_urls
        }
        
    except Exception as e:
        logger.error(f"Job {job_id}: Error during processing: {e}", exc_info=True)
        
        # Mark job as failed
        job_manager.update_job(
            job_id,
            status=JobStatus.FAILED,
            error_message=str(e)
        )
        
        # Cleanup on error
        await _cleanup_temp_files(job_temp_dir)
        
        raise


async def _cleanup_temp_files(temp_dir: str):
    """Clean up temporary files"""
    try:
        if os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir)
            logger.info(f"Cleaned up temporary directory: {temp_dir}")
    except Exception as e:
        logger.warning(f"Failed to cleanup temp directory {temp_dir}: {e}")


if __name__ == '__main__':
    celery_app.start()
