"""
Split endpoint for music stems separation
"""
import asyncio
import logging
from typing import List
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl, field_validator
import os

from services.job_manager import job_manager
from models.job import JobStatus
from websocket_manager import websocket_manager
from config import settings

# Import the appropriate worker based on environment
if settings.is_production:
    from simple_processor import process_job_simple
else:
    from worker import process_audio_async

logger = logging.getLogger(__name__)

router = APIRouter()


class SplitRequest(BaseModel):
    """Request model for split endpoint"""
    youtube_url: HttpUrl
    stems: List[str]
    
    @field_validator('stems')
    @classmethod
    def validate_stems(cls, v):
        """Validate stem names"""
        valid_stems = {"bass", "drums", "vocals", "other"}
        invalid_stems = set(v) - valid_stems
        if invalid_stems:
            raise ValueError(f"Invalid stems: {invalid_stems}. Valid stems are: {valid_stems}")
        if not v:
            raise ValueError("At least one stem must be specified")
        return v


class SplitResponse(BaseModel):
    """Response model for split endpoint"""
    job_id: str
    status: str
    message: str = ""


class JobStatusResponse(BaseModel):
    """Response model for job status"""
    job_id: str
    status: str
    download_urls: dict = {}
    preview_urls: dict = {}
    error_message: str = ""
    song_title: str = ""
    song_duration: int = 0
    payment_required: bool = True
    payment_completed: bool = False


@router.post("/split", response_model=SplitResponse)
async def split_audio(request: SplitRequest):
    """
    Start async audio stem separation
    
    Args:
        request: Split request containing YouTube URL and desired stems
    
    Returns:
        SplitResponse with job ID for tracking
    """
    logger.info(f"Starting split request for URL: {request.youtube_url}")
    
    try:
        # Create job (this will return existing job if already exists and active)
        job = job_manager.create_job(
            youtube_url=str(request.youtube_url),
            stems=request.stems
        )
        
        logger.info(f"Job {job.job_id} status: {job.status}")
        
        # Always try to process if job is PENDING
        if job.status == JobStatus.PENDING:
            # Clear any existing lock and start fresh
            job_manager.clear_processing_lock(job.job_id)
            
            # Start async processing
            if settings.is_production:
                await process_job_simple(job.job_id)
            else:
                process_audio_async.delay(job.job_id)
            logger.info(f"Job {job.job_id}: Started async processing")
            
        elif job.status in [JobStatus.DOWNLOADING, JobStatus.PROCESSING]:
            # Check if actually being processed
            if not job_manager.is_job_being_processed(job.job_id):
                logger.warning(f"Job {job.job_id} shows status {job.status} but no processing lock found. Restarting...")
                job = job_manager.reset_job_status(job.job_id)
                if settings.is_production:
                    await process_job_simple(job.job_id)
                else:
                    process_audio_async.delay(job.job_id)
                logger.info(f"Job {job.job_id}: Restarted processing")
            else:
                logger.info(f"Job {job.job_id}: Already being processed")
        else:
            logger.info(f"Job {job.job_id}: Returning existing job with status {job.status}")
        
        return SplitResponse(
            job_id=job.job_id,
            status=job.status.value,
            message="Job started. Connect to WebSocket for real-time updates."
        )
        
    except Exception as e:
        logger.error(f"Error starting job: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start processing: {str(e)}"
        )


@router.get("/job/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """
    Get job status and download URLs
    
    Args:
        job_id: Job identifier
    
    Returns:
        JobStatusResponse with current status and URLs
    """
    job = job_manager.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status.value,
        download_urls=job.download_urls,
        preview_urls=job.preview_urls,
        error_message=job.error_message or "",
        song_title=job.song_title or "",
        song_duration=job.song_duration or 0,
        payment_required=job.payment_required,
        payment_completed=job.payment_completed
    )


@router.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """
    WebSocket endpoint for real-time job updates
    
    Args:
        websocket: WebSocket connection
        job_id: Job identifier to listen for updates
    """
    try:
        await websocket_manager.connect(websocket, job_id)
        logger.info(f"WebSocket connected successfully for job {job_id}")
        
        # Send initial connection confirmation
        await websocket.send_json({
            "type": "connected",
            "job_id": job_id,
            "message": "WebSocket connected successfully"
        })
        
        # Keep connection alive and handle disconnections
        while True:
            try:
                # Wait for any message with a timeout to avoid hanging
                message = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                logger.info(f"Received WebSocket message for job {job_id}: {message}")
                
                # Echo back any message received (for debugging)
                await websocket.send_json({
                    "type": "echo",
                    "job_id": job_id,
                    "received": message
                })
                
            except asyncio.TimeoutError:
                # Send a ping to keep connection alive
                await websocket.send_json({
                    "type": "ping",
                    "job_id": job_id,
                    "timestamp": asyncio.get_event_loop().time()
                })
                logger.debug(f"Sent ping to WebSocket for job {job_id}")
                
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected for job {job_id}")
                break
                
    except Exception as e:
        logger.error(f"WebSocket error for job {job_id}: {e}", exc_info=True)
    finally:
        websocket_manager.disconnect(websocket, job_id)
        logger.info(f"WebSocket cleanup completed for job {job_id}")


@router.get("/preview/{job_id}/{filename}")
async def preview_file(job_id: str, filename: str):
    """
    Download preview file (30-second sample)
    
    Args:
        job_id: Job identifier
        filename: Name of the preview file to download
    
    Returns:
        File response for preview
    """
    file_path = os.path.join(settings.OUTPUT_DIR, job_id, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Preview file not found")
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="audio/mpeg"
    )


@router.get("/download/{job_id}/{filename}")
async def download_file(job_id: str, filename: str):
    """
    Download separated stem file (requires payment)
    
    Args:
        job_id: Job identifier
        filename: Name of the file to download
    
    Returns:
        File response for downloading or payment redirect
    """
    # Check if payment is completed
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.payment_required and not job.payment_completed:
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Payment required",
                "payment_url": f"/api/payment/{job_id}",
                "amount": 3.00,
                "currency": "USD"
            }
        )
    
    file_path = os.path.join(settings.OUTPUT_DIR, job_id, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="audio/wav"
    )


@router.post("/payment/{job_id}/complete")
async def complete_payment(job_id: str):
    """
    Mark payment as completed for a job
    
    Args:
        job_id: Job identifier
    
    Returns:
        Success message
    """
    # In a real implementation, you would verify the payment with Stripe/PayPal
    # For now, we'll just mark it as completed
    
    job = job_manager.mark_payment_completed(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return {"message": "Payment completed successfully", "job_id": job_id}


@router.get("/payment/{job_id}")
async def get_payment_info(job_id: str):
    """
    Get payment information for a job
    
    Args:
        job_id: Job identifier
    
    Returns:
        Payment information
    """
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return {
        "job_id": job_id,
        "amount": 3.00,
        "currency": "USD",
        "song_title": job.song_title or "Unknown Song",
        "stems": [stem.value for stem in job.stems],
        "payment_completed": job.payment_completed
    }


@router.post("/debug/clear-lock/{job_id}")
async def clear_job_lock(job_id: str):
    """
    Debug endpoint to clear processing lock for a stuck job
    
    Args:
        job_id: Job identifier
    
    Returns:
        Success message
    """
    cleared = job_manager.clear_processing_lock(job_id)
    if cleared:
        logger.info(f"Cleared processing lock for job {job_id}")
        return {"message": f"Processing lock cleared for job {job_id}"}
    else:
        return {"message": f"No processing lock found for job {job_id}"}


@router.post("/debug/reset-job/{job_id}")
async def reset_job(job_id: str):
    """
    Debug endpoint to completely reset a stuck job
    
    Args:
        job_id: Job identifier
    
    Returns:
        Success message
    """
    job = job_manager.reset_job_status(job_id)
    if job:
        logger.info(f"Reset job {job_id} to pending status")
        return {"message": f"Job {job_id} reset to pending status", "status": job.status.value}
    else:
        raise HTTPException(status_code=404, detail="Job not found")
