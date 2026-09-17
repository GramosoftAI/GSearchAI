import asyncio
from typing import TypedDict, List, Dict, Any, Optional

class GraphState(TypedDict):
    # ==========================================
    # 1. CORE REQUEST (Immutable Input)
    # ==========================================
    query: str
    original_query: str
    tenant_id: str
    agent_id: str
    session_id: Optional[str]
    user_id: Optional[str]
    kb_ids: List[str]
    chat_history: Optional[str]
    skip_search: bool
    top_k: int
    max_depth: int
    stream_queue: Optional[Any]

    # ==========================================
    # 2. INITIALIZATION STATE
    # ==========================================
    intent: Optional[str]
    memory_guidance: Optional[str]
    analysis_object: Optional[Any]
    query_embedding_tuple: Optional[tuple]

    # ==========================================
    # 3. KB RESOLUTION STATE
    # ==========================================
    doc_kbs: List[Any]
    excel_kbs: List[Any]
    csv_kbs: List[Any]
    target_kb_id: Optional[str]
    
    # Phase 7 Disambiguation Interruption State
    clarification_payload: Optional[Dict[str, Any]]
    requires_clarification: bool

    # ==========================================
    # 4. RETRIEVAL STATE
    # ==========================================
    # Unstructured
    retrieved_chunks: List[Any]
    graph_triplets: List[Any]
    
    # Tabular
    tabular_results: Optional[str]
    used_sql_fallback: bool

    # ==========================================
    # 5. RERANKING STATE
    # ==========================================
    reranked_chunks: List[Any]

    # ==========================================
    # 6. GENERATION & OUTPUT STATE
    # ==========================================
    system_prompt: Optional[str]
    final_answer: Optional[str]
    sources: List[str]
    error: Optional[str]
