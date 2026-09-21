import logging
import time
from app.modules.rag.graph.state import GraphState

logger = logging.getLogger(__name__)

def join_node(state: GraphState) -> dict:
    """
    A no-op node that allows parallel branches (memory and retrieval/tabular) to fan-in.
    LangGraph natively waits for all incoming edges to this node to complete their superstep.
    """
    logger.info(f"[TIMING] join_node executed at {time.perf_counter():.3f}")
    return {}

