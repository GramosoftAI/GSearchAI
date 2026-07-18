import time
import asyncio
from .types import HealthStatus
from .base import LLMProvider

class HealthCache:
    """A TTL-based cache for provider health checks to avoid inline blocking."""
    def __init__(self, ttl_seconds: int = 60):
        self.ttl = ttl_seconds
        self._cache = {}  # dict of provider_name -> {"status": HealthStatus, "expires_at": float}
        self._lock = asyncio.Lock()

    async def get_health(self, provider_name: str, provider: LLMProvider) -> HealthStatus:
        now = time.time()
        
        async with self._lock:
            cached = self._cache.get(provider_name)
            if cached and cached["expires_at"] > now:
                return cached["status"]
                
        # If not cached or expired, we check inline (could also be done via a background task)
        # For simplicity without stray tasks, we do it inline here and cache it for the TTL.
        status = await provider.health_check()
        
        async with self._lock:
            self._cache[provider_name] = {
                "status": status,
                "expires_at": time.time() + self.ttl
            }
        
        return status
