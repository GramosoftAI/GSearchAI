import httpx
from app.modules.rag.graph.state import GraphState
from app.core.config import get_settings
import logging

logger = logging.getLogger(__name__)

async def memory_node(state: GraphState) -> GraphState:
    """
    Executes memory triage API call concurrently.
    """
    enable_memory = str(getattr(get_settings(), "memory_enabled", "True")).strip().lower() == "true"
    memory_api_url = getattr(get_settings(), "memory_api_url", "http://localhost:4917")
    
    guidance = None
    if enable_memory and state.get("user_id"):
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{memory_api_url}/process-turn",
                    json={
                        "query": state["original_query"],
                        "session_id": state.get("session_id"),
                        "agent_id": state["agent_id"],
                        "user_id": state.get("user_id"),
                        "tenant_id": state["tenant_id"],
                    },
                    timeout=2.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    guidance = data.get("guidance")
            except Exception as e:
                logger.warning(f"memory-api process-turn unreachable/slow: {e}")
                
    # Return only owned state delta
    return {
        "memory_guidance": guidance
    }

