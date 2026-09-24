import asyncio
import time
from app.modules.rag.graph.state import GraphState
from app.modules.rag.orchestrator.query_analyzer import QueryAnalyzer
from app.core.embeddings import EmbeddingGenerator

async def init_node(state: GraphState) -> GraphState:
    """
    Initializes the RAG pipeline state.
    - Generates query embedding to prime the cache
    - Awaits memory triage (spawned via parallel memory_node)
    - Detects intent
    """
    query = state["query"]
    
    # 2. Query Analysis
    # In full implementation, kb_context will be injected from state after KBs are loaded.
    analyzer = QueryAnalyzer()
    analysis = await analyzer.analyze_query(
        query=query, 
        kb_context="", # Will map from state["doc_kbs"] + state["excel_kbs"] in full implementation
        chat_history=state.get("chat_history"), 
        tenant_id=state["tenant_id"], 
        user_id=state.get("user_id"), 
        session_id=state.get("session_id")
    )
    
    # Extract intent safely
    intent_name = getattr(analysis, "intent", "UNKNOWN") if analysis and getattr(analysis, "intent", None) else "UNKNOWN"
    if intent_name == "UNKNOWN":
        intent_name = getattr(getattr(analysis, "intent", object()), "name", "UNKNOWN")
    
    # Return only owned state delta
    return {
        "intent": intent_name,
        "analysis_object": analysis,
        # query_embedding_tuple is removed from here; retrieval_node will generate it
    }

