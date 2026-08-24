"""
RAG API schemas - Pydantic models for request/response validation
"""

from uuid import UUID
from typing import List, Optional, Dict
from pydantic import BaseModel, Field


class RAGQueryRequest(BaseModel):
    """User RAG query request (Hiding IDs in path)"""

    query: str = Field(..., min_length=5, max_length=2000, description="User query")
    Reasoning: Optional[str] = Field("True", description="Whether to return detailed graph reasoning path")
    Memory: Optional[str] = Field("True", description="Whether to use conversational memory context")
    top_k: Optional[int] = Field(15, ge=5, le=50, description="Initial seed chunks")
    max_depth: Optional[int] = Field(2, ge=1, le=3, description="Graph expansion depth")

    class Config:
        example = {
            "query": "What are the main concepts in this knowledge base?",
            "Reasoning": "True",
            "Memory": "True",
        }


class SourceChunk(BaseModel):
    """Source chunk with relevance score and attribution"""

    chunk_id: str = Field(..., description="Chunk UUID")
    score: float = Field(..., ge=0.0, le=1.0, description="Hybrid relevance score")
    position: int = Field(..., ge=0, description="Position in document")
    reason: str = Field(
        default="", description="Why retrieved (SIMILAR, ENTITY, NEXT, Seed)"
    )
    source: Optional[str] = Field(None, description="Source URL or filename")
    s3_path: Optional[str] = Field(None, description="Direct S3 URL if available")
    kb_id: Optional[str] = Field(None, description="Knowledge base ID / file ID")
    content_type: Optional[str] = Field(None, description="Type of content: text/html, text/plain, or original")




class RAGContextInfo(BaseModel):
    """Context metadata"""

    kb_id: str
    kb_name: str
    chunks_used: int
    entities_mentioned: List[str]
    reasoning_path: str = Field(default="", description="Detailed path used to find context")


class RAGStats(BaseModel):
    """Pipeline statistics"""

    total_chunks: int
    total_tokens: int
    entity_count: int


class RAGQueryResponse(BaseModel):
    """RAG query response"""

    answer: str = Field(..., description="Generated answer")
    sources: List[SourceChunk] = Field(
        default_factory=list, description="Source chunks with scores"
    )
    context: RAGContextInfo = Field(..., description="Context metadata")
    stats: RAGStats = Field(..., description="Pipeline statistics")
    
    # PRODUCT DASHBOARD FIELDS
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Overall answer confidence")
    nodes_used: int = Field(default=0, description="Total nodes (chunks+entities) used")
    reasoning_path: str = Field(default="", description="Human-readable summary of retrieval logic")

    class Config:
        example = {
            "answer": "Based on the knowledge base, the main concepts are...",
            "sources": [
                {
                    "chunk_id": "550e8400-e29b-41d4-a716-446655440002",
                    "score": 0.95,
                    "position": 0,
                }
            ],
            "context": {
                "kb_id": "550e8400-e29b-41d4-a716-446655440001",
                "kb_name": "Python Documentation",
                "chunks_used": 5,
                "entities_mentioned": ["Python", "Function", "Variable"],
            },
            "stats": {"total_chunks": 5, "total_tokens": 450, "entity_count": 3},
        }


class RAGErrorResponse(BaseModel):
    """Error response"""

    error: str = Field(..., description="Error message")
    answer: Optional[str] = Field(None, description="Fallback answer if available")
    sources: List[SourceChunk] = Field(default_factory=list)


class RAGFeedbackRequest(BaseModel):
    """User feedback for RAG generation to update node weights"""

    chunk_ids: List[str] = Field(..., description="IDs of chunks used for this answer")
    rating: int = Field(..., ge=-1, le=1, description="1 for thumbs up, -1 for thumbs down")


class UnifiedChatRequest(BaseModel):
    query: str
    top_k: int = 10
    max_depth: int = 2
    session_id: Optional[str] = None

    @classmethod
    def from_raw(cls, payload: dict) -> "UnifiedChatRequest":
        query = payload.get("query") or payload.get("message")
        if not query:
            raise ValueError("Missing 'query' or 'message' field")
        return cls(
            query=query,
            top_k=payload.get("top_k", 10),
            max_depth=payload.get("max_depth", 2),
            session_id=payload.get("session_id"),
        )

class RetrievalTask(BaseModel):
    """Shared task contract for vector engines and other retrieval modules"""
    task_id: str
    query: str
    metadata_filters: Optional[Dict] = None
    top_k: int = 15
    target_section_ids: Optional[List[str]] = None
