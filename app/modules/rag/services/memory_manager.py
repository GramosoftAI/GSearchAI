import os
import httpx
import logging
from typing import Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)

class MemoryManager:
    """
    Service wrapper for the external Memory API.
    Handles triage (process-turn) and persistence (save-turn).
    """
    
    def __init__(self):
        self.memory_api_url = f"{self._resolve_memory_api_base_url()}/api/v1/memory"
        
    def _resolve_memory_api_base_url(self) -> str:
        """Resolve the memory API base URL for local dev, containers, and tests."""
        configured = os.getenv("MEMORY_API_BASE_URL", "").strip()
        if configured:
            return configured.rstrip("/")

        env_host = os.getenv("MEMORY_API_HOST", "").strip()
        if env_host:
            return env_host.rstrip("/")

        return "http://127.0.0.1:8001"

    async def process_turn(self, query: str, session_id: str, agent_id: str, user_id: str, tenant_id: str) -> Dict[str, Any]:
        """
        Calls /process-turn to analyze the query against memory preferences.
        Returns a dict containing:
        - episodic_guidance (str)
        - is_feedback_only (bool)
        - is_history_query (bool)
        - router_category (str)
        """
        result = {
            "episodic_guidance": "",
            "is_feedback_only": False,
            "is_history_query": False,
            "router_category": None
        }
        
        async with httpx.AsyncClient() as client:
            try:
                mem_resp = await client.post(
                    f"{self.memory_api_url}/process-turn",
                    json={
                        "query": query,
                        "session_id": session_id,
                        "agent_id": agent_id,
                        "user_id": user_id,
                        "tenant_id": tenant_id,
                    },
                    timeout=8.0,
                )
                if mem_resp.status_code == 200:
                    mem_data = mem_resp.json()
                    result["episodic_guidance"] = mem_data.get("guidance_context") or ""
                    result["is_feedback_only"] = mem_data.get("is_feedback_only", False)
                    result["is_history_query"] = mem_data.get("is_history_query", False)
                    result["router_category"] = mem_data.get("category")
                else:
                    logger.warning(
                        f"memory-api process-turn status={mem_resp.status_code}: {mem_resp.text}"
                    )
            except Exception as e:
                logger.warning(
                    f"memory-api process-turn unreachable, continuing without memory: {e}"
                )
        return result

    async def save_turn(self, query: str, ai_response: str, session_id: str, agent_id: str, user_id: str, tenant_id: str, is_feedback_only: bool = False, metadata: Optional[Dict[str, Any]] = None):
        """
        Calls /save-turn to store the conversation turn and update episodic graph memory.
        """
        payload = {
            "query": query,
            "ai_response": ai_response,
            "session_id": session_id,
            "agent_id": agent_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
        }
        if is_feedback_only:
            payload["is_feedback_only"] = True
        if metadata:
            payload["metadata"] = metadata
            
        async with httpx.AsyncClient() as client:
            try:
                await client.post(
                    f"{self.memory_api_url}/save-turn",
                    json=payload,
                    timeout=3.0,
                )
            except Exception as e:
                logger.warning(f"memory-api save-turn failed: {e}")
