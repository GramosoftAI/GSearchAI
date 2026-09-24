import httpx
from app.modules.rag.graph.state import GraphState
from app.core.config import get_settings
import logging

logger = logging.getLogger(__name__)

_memory_client = None

async def memory_node(state: GraphState) -> GraphState:
    """
    Executes memory triage API call concurrently.
    """
    enable_memory = str(getattr(get_settings(), "memory_enabled", "True")).strip().lower() == "true"
    memory_api_url = getattr(get_settings(), "memory_api_url", "http://localhost:4917")
    global _memory_client
    if _memory_client is None or _memory_client.is_closed:
        _memory_client = httpx.AsyncClient(timeout=1.0)
        
    guidance = None
    if enable_memory and state.get("user_id"):
        try:
            import asyncio
            resp = await asyncio.wait_for(
                _memory_client.post(
                    f"{memory_api_url.rstrip('/')}/api/v1/memory/process-turn",
                    json={
                        "query": state["original_query"],
                        "session_id": state.get("session_id"),
                        "agent_id": state["agent_id"],
                        "user_id": state.get("user_id"),
                        "tenant_id": state["tenant_id"],
                    }
                ),
                timeout=1.0
            )
            if resp.status_code == 200:
                data = resp.json()
                guidance = data.get("guidance")
        except asyncio.TimeoutError:
            logger.warning("memory-api process-turn timed out (>=1.0s), continuing without memory")
        except Exception as e:
            logger.warning(f"memory-api process-turn unreachable/slow: {e}")
                
    # Return only owned state delta
    return {
        "memory_guidance": guidance
    }

