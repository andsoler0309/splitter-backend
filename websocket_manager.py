"""
WebSocket endpoint for real-time job updates
"""
import json
import logging
from typing import Dict
from fastapi import WebSocket, WebSocketDisconnect
import asyncio
from config import settings
from services.redis_client import redis_client

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections for job updates"""
    
    def __init__(self):
        # job_id -> list of websockets
        self.active_connections: Dict[str, list] = {}
        self.redis_client = redis_client
        
    async def connect(self, websocket: WebSocket, job_id: str):
        """Accept WebSocket connection and subscribe to job updates"""
        await websocket.accept()
        
        if job_id not in self.active_connections:
            self.active_connections[job_id] = []
        
        self.active_connections[job_id].append(websocket)
        logger.info(f"WebSocket connected for job {job_id}")
        
        # Start polling for job updates since Upstash doesn't support pub/sub via REST
        if settings.is_production:
            asyncio.create_task(self._poll_job_status(job_id))
        else:
            # Use pub/sub for local development
            asyncio.create_task(self._listen_for_updates(job_id))
    
    def disconnect(self, websocket: WebSocket, job_id: str):
        """Remove WebSocket connection"""
        if job_id in self.active_connections:
            if websocket in self.active_connections[job_id]:
                self.active_connections[job_id].remove(websocket)
            
            # Remove job entry if no more connections
            if not self.active_connections[job_id]:
                del self.active_connections[job_id]
        
        logger.info(f"WebSocket disconnected for job {job_id}")
    
    async def send_message_to_job(self, job_id: str, message: dict):
        """Send message to all WebSockets connected to a job"""
        if job_id in self.active_connections:
            disconnected = []
            
            for websocket in self.active_connections[job_id]:
                try:
                    await websocket.send_json(message)
                except:
                    disconnected.append(websocket)
            
            # Remove disconnected websockets
            for ws in disconnected:
                self.disconnect(ws, job_id)
    
    async def _poll_job_status(self, job_id: str):
        """Poll job status and send updates via WebSocket"""
        from services.job_manager import job_manager
        
        last_status = None
        try:
            while job_id in self.active_connections and self.active_connections[job_id]:
                try:
                    # Get current job status
                    job = job_manager.get_job(job_id)
                    if job and job.status != last_status:
                        # Status changed, send update
                        update_data = {
                            "job_id": job.job_id,
                            "status": job.status.value if hasattr(job.status, 'value') else str(job.status),
                            "message": self._get_status_message(job.status),
                            "song_title": job.song_title,
                            "song_duration": job.song_duration,
                            "download_urls": job.download_urls or {},
                            "preview_urls": job.preview_urls or {},
                            "error_message": job.error_message
                        }
                        await self.send_message_to_job(job_id, update_data)
                        last_status = job.status
                        
                        # If job is completed or failed, we can stop polling
                        if job.status in ['completed', 'failed']:
                            break
                    
                    await asyncio.sleep(2)  # Poll every 2 seconds
                except Exception as e:
                    logger.error(f"Error polling job status for {job_id}: {e}")
                    await asyncio.sleep(5)  # Wait longer on error
                    
        except Exception as e:
            logger.error(f"Fatal error in _poll_job_status for job {job_id}: {e}")
    
    def _get_status_message(self, status):
        """Get user-friendly status message"""
        messages = {
            'pending': "Job queued for processing",
            'downloading': "Downloading audio from YouTube",
            'processing': "Separating audio stems with AI",
            'completed': "Processing completed successfully",
            'failed': "Processing failed"
        }
        status_str = status.value if hasattr(status, 'value') else str(status)
        return messages.get(status_str, f"Status: {status_str}")

    async def _listen_for_updates(self, job_id: str):
        """Listen for Redis pub/sub updates for a specific job (local development only)"""
        if settings.is_production:
            # Use polling instead for production
            return await self._poll_job_status(job_id)
        
        # Only use pub/sub for local development with standard Redis
        pubsub = self.redis_client.pubsub()
        if not pubsub:
            # Fall back to polling if pub/sub not available
            return await self._poll_job_status(job_id)
        
        pubsub.subscribe(f"job_updates:{job_id}")
        
        try:
            while job_id in self.active_connections and self.active_connections[job_id]:
                # Use get_message with timeout to avoid blocking
                message = pubsub.get_message(timeout=0.1)
                if message and message['type'] == 'message':
                    try:
                        data = json.loads(message['data'])
                        await self.send_message_to_job(job_id, data)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to decode Redis message: {message['data']}")
                
                # Short sleep to prevent busy waiting
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Error in _listen_for_updates for job {job_id}: {e}")
        finally:
            try:
                pubsub.unsubscribe(f"job_updates:{job_id}")
                pubsub.close()
            except Exception as e:
                logger.error(f"Error closing pubsub for job {job_id}: {e}")


# Global WebSocket manager
websocket_manager = WebSocketManager()
