from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

@dataclass
class PipelineContext:
    query: str
    session_id: str
    agent_id: str
    user_id: str
    tenant_id: str
    kb_ids: List[str]
    
    # State accumulated throughout the pipeline
    rewritten_query: Optional[str] = None
    memory_context: Optional[str] = None
    router_category: Optional[str] = None
    is_feedback_only: bool = False
    is_history_query: bool = False
    
    # Outputs
    retrieved_chunks: List[Any] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
