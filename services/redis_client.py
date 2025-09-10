"""
Redis client service that supports both standard Redis and Upstash Redis REST API
"""
import json
import logging
import base64
from typing import Optional, Any, Dict
import redis
import httpx
from config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """Redis client that works with both standard Redis and Upstash REST API"""
    
    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or settings.effective_redis_url
        self.use_upstash = self._should_use_upstash()
        
        if self.use_upstash:
            self.base_url = settings.UPSTASH_REDIS_REST_URL
            self.token = settings.UPSTASH_REDIS_REST_TOKEN
            self.headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
            logger.info("Using Upstash Redis REST API")
        else:
            self.redis_client = redis.from_url(self.redis_url)
            logger.info(f"Using standard Redis client: {self.redis_url}")
    
    def _should_use_upstash(self) -> bool:
        """Determine if we should use Upstash REST API"""
        return (
            settings.is_production and 
            settings.UPSTASH_REDIS_REST_URL and 
            settings.UPSTASH_REDIS_REST_TOKEN
        )
    
    async def _upstash_request(self, command: list) -> Any:
        """Make a request to Upstash REST API"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                headers=self.headers,
                json=command,
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            return data.get("result")
    
    def _sync_upstash_request(self, command: list) -> Any:
        """Make a synchronous request to Upstash REST API"""
        import requests
        response = requests.post(
            self.base_url,
            headers=self.headers,
            json=command,
            timeout=30.0
        )
        response.raise_for_status()
        data = response.json()
        return data.get("result")
    
    def get(self, key: str) -> Optional[bytes]:
        """Get a value from Redis"""
        if self.use_upstash:
            try:
                result = self._sync_upstash_request(["GET", key])
                if result is None:
                    return None
                return result.encode() if isinstance(result, str) else result
            except Exception as e:
                logger.error(f"Upstash GET error for key {key}: {e}")
                return None
        else:
            return self.redis_client.get(key)
    
    def set(self, key: str, value: Any, ex: Optional[int] = None, nx: bool = False) -> bool:
        """Set a value in Redis"""
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        elif not isinstance(value, (str, bytes)):
            value = str(value)
        
        if self.use_upstash:
            try:
                command = ["SET", key, value]
                if ex is not None:
                    command.extend(["EX", str(ex)])
                if nx:
                    command.append("NX")
                
                result = self._sync_upstash_request(command)
                return result == "OK" or result == 1
            except Exception as e:
                logger.error(f"Upstash SET error for key {key}: {e}")
                return False
        else:
            return self.redis_client.set(key, value, ex=ex, nx=nx)
    
    def setex(self, key: str, time: int, value: Any) -> bool:
        """Set a value with expiration"""
        return self.set(key, value, ex=time)
    
    def delete(self, key: str) -> int:
        """Delete a key from Redis"""
        if self.use_upstash:
            try:
                result = self._sync_upstash_request(["DEL", key])
                return result or 0
            except Exception as e:
                logger.error(f"Upstash DEL error for key {key}: {e}")
                return 0
        else:
            return self.redis_client.delete(key)
    
    def exists(self, key: str) -> bool:
        """Check if a key exists"""
        if self.use_upstash:
            try:
                result = self._sync_upstash_request(["EXISTS", key])
                return bool(result)
            except Exception as e:
                logger.error(f"Upstash EXISTS error for key {key}: {e}")
                return False
        else:
            return bool(self.redis_client.exists(key))
    
    def publish(self, channel: str, message: str) -> None:
        """Publish a message to a channel"""
        if self.use_upstash:
            try:
                self._sync_upstash_request(["PUBLISH", channel, message])
            except Exception as e:
                logger.error(f"Upstash PUBLISH error for channel {channel}: {e}")
        else:
            self.redis_client.publish(channel, message)
    
    def pubsub(self):
        """Get a pubsub object (only works with standard Redis)"""
        if self.use_upstash:
            # For Upstash, we'll need to implement polling-based updates
            # or use WebSocket connections instead of pub/sub
            logger.warning("Pub/sub not supported with Upstash REST API, falling back to polling")
            return None
        else:
            return self.redis_client.pubsub()


# Global Redis client instance
redis_client = RedisClient()
