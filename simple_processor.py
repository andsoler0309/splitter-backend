"""
Simple task processor for production deployment without Celery
"""
import asyncio
import logging
import os
from typing import Optional
from services.job_manager import job_manager
from services.youtube_service import YouTubeService
from services.demucs_service import DemucsService
from services.redis_client import redis_client
from models.job import JobStatus
from config import settings

logger = logging.getLogger(__name__)


class SimpleTaskProcessor:
    """Simple background task processor for production environments"""
    
    def __init__(self):
        self.running = False
        self.task_queue_key = "task_queue"
    
    async def start(self):
        """Start the task processor"""
        self.running = True
        logger.info("Starting simple task processor")
        
        while self.running:
            try:
                await self._process_pending_jobs()
                await asyncio.sleep(5)  # Check every 5 seconds
            except Exception as e:
                logger.error(f"Error in task processor: {e}")
                await asyncio.sleep(10)  # Wait longer on error
    
    def stop(self):
        """Stop the task processor"""
        self.running = False
        logger.info("Stopping task processor")
    
    async def enqueue_job(self, job_id: str):
        """Add a job to the processing queue"""
        try:
            # For production with Upstash, we'll use a simple approach
            # Store the job ID in a way that the processor can find it
            queue_key = f"queued_job_scan_{hash(job_id) % 10}"  # Distribute across 10 slots
            redis_client.set(queue_key, job_id, ex=3600)  # 1 hour expiry
            logger.info(f"Enqueued job {job_id} for processing in slot {queue_key}")
        except Exception as e:
            logger.error(f"Failed to enqueue job {job_id}: {e}")
    
    async def _process_pending_jobs(self):
        """Process any pending jobs"""
        try:
            # Look for jobs that need processing by scanning Redis keys
            # This is a simple approach - in production you might want a proper queue
            
            # Get all pending job keys from Redis
            pending_jobs = []
            
            # For Upstash, we'll need to track queued jobs differently
            # Check for jobs marked as queued
            try:
                # Scan for queued job keys (this is a simplified approach)
                # In a real implementation, you'd use a proper job queue
                for i in range(10):  # Check up to 10 potential jobs
                    job_key = f"queued_job_scan_{i}"
                    queued_job_id = redis_client.get(job_key)
                    if queued_job_id:
                        job_id = queued_job_id.decode() if isinstance(queued_job_id, bytes) else queued_job_id
                        pending_jobs.append(job_id)
                        # Remove from queue after picking up
                        redis_client.delete(job_key)
            except Exception as e:
                logger.error(f"Error scanning for pending jobs: {e}")
            
            # Process each pending job
            for job_id in pending_jobs:
                try:
                    await self._process_job(job_id)
                except Exception as e:
                    logger.error(f"Error processing job {job_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Error processing pending jobs: {e}")
    
    async def _process_job(self, job_id: str):
        """Process a single job"""
        processing_key = f"processing:{job_id}"
        
        # Try to acquire a lock for this job
        lock_acquired = redis_client.set(
            processing_key, 
            "simple_processor", 
            ex=900,  # 15 minutes
            nx=True
        )
        
        if not lock_acquired:
            logger.info(f"Job {job_id} is already being processed")
            return
        
        try:
            logger.info(f"Processing job {job_id}")
            await self._process_audio_internal(job_id)
        except Exception as e:
            logger.error(f"Error processing job {job_id}: {e}")
        finally:
            # Release the lock
            redis_client.delete(processing_key)
    
    async def _process_audio_internal(self, job_id: str):
        """Process audio separation for a job"""
        logger.info(f"Starting audio processing for job {job_id}")
        
        try:
            # Check if job exists
            job = job_manager.get_job(job_id)
            if not job:
                logger.error(f"Job {job_id} not found")
                return
            
            if job.status in [JobStatus.COMPLETED, JobStatus.FAILED]:
                logger.info(f"Job {job_id} already completed with status {job.status}")
                return
            
            # Update job status to downloading
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
                        preview_filename = f"{job_id}_{stem_name}_preview.mp3"
                        preview_path = os.path.join(job_output_dir, preview_filename)
                        
                        # Use ffmpeg to create preview
                        import subprocess
                        try:
                            subprocess.run([
                                'ffmpeg', '-i', final_path, '-t', '30', 
                                '-c:a', 'libmp3lame', '-b:a', '128k', 
                                preview_path
                            ], check=True, capture_output=True)
                            
                            preview_urls[stem_name] = f"/api/preview/{job_id}/{preview_filename}"
                        except subprocess.CalledProcessError as e:
                            logger.warning(f"Failed to create preview for {stem_name}: {e}")
            
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
            await self._cleanup_temp_files(job_temp_dir)
            
            logger.info(f"Job {job_id}: Completed successfully")
            
        except Exception as e:
            logger.error(f"Job {job_id}: Error during processing: {e}", exc_info=True)
            
            # Mark job as failed
            job_manager.update_job(
                job_id,
                status=JobStatus.FAILED,
                error_message=str(e)
            )
            
            # Cleanup on error
            try:
                await self._cleanup_temp_files(job_temp_dir)
            except:
                pass
            
            raise
    
    async def _cleanup_temp_files(self, temp_dir: str):
        """Clean up temporary files"""
        try:
            if os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir)
                logger.info(f"Cleaned up temporary directory: {temp_dir}")
        except Exception as e:
            logger.warning(f"Failed to cleanup temp directory {temp_dir}: {e}")


# Global simple task processor
simple_task_processor = SimpleTaskProcessor()


async def process_job_simple(job_id: str):
    """Simple function to process a job in production"""
    if settings.is_production:
        await simple_task_processor.enqueue_job(job_id)
    else:
        # Use Celery for local development
        from worker import process_audio_async
        process_audio_async.delay(job_id)
