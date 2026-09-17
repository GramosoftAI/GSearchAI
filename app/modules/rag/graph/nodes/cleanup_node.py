from app.modules.rag.graph.state import GraphState

def cleanup_node(state: GraphState) -> dict:
    """
    Clears heavy state fields before checkpointing to save SQLite/Postgres DB space across turns.
    """
    return {
        "retrieved_chunks": [],
        "tabular_results": None,
        "graph_triplets": [],
        "reranked_chunks": []
    }

