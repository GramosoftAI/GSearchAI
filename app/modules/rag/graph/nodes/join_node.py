from app.modules.rag.graph.state import GraphState

def join_node(state: GraphState) -> dict:
    """
    A no-op node that allows parallel branches (memory and retrieval/tabular) to fan-in.
    LangGraph natively waits for all incoming edges to this node to complete their superstep.
    """
    return {}

