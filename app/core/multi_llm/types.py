from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class TaskType(str, Enum):
    INTENT = "intent_detection"
    ENTITY = "entity_extraction"
    RELATION = "relationship_extraction"
    PLANNER = "planner"
    METADATA = "metadata_extraction"
    JSON_REPAIR = "json_repair"
    HALLUCINATION = "hallucination_validation"
    INGESTION = "ingestion_pipeline"
    EMBEDDINGS = "embeddings"
    FINAL_ANSWER = "final_answer_generation"
    DEFAULT = "default"
    USER_QUERY = "user_query_response"
    QUERY_REWRITE = "query_rewrite"

class Message(BaseModel):
    role: str
    content: str

class ToolSpec(BaseModel):
    type: str = "function"
    function: Dict[str, Any]

class LLMRequest(BaseModel):
    messages: List[Message]
    temperature: float = 0.2
    max_tokens: int = 4096
    json_schema: Optional[Dict[str, Any]] = None
    stream: bool = False
    tools: Optional[List[ToolSpec]] = None
    task_type: TaskType
    # model can be populated by the router before sending to the provider
    model: Optional[str] = None

class LLMResponse(BaseModel):
    text: str
    provider: str
    model: str
    latency_ms: int
    tokens_prompt: int
    tokens_completion: int
    total_tokens: int
    finish_reason: str
    cached: bool = False
    raw: Optional[Dict[str, Any]] = None

class ProviderCapabilities(BaseModel):
    chat: bool
    embeddings: bool
    streaming: bool
    json_mode: bool
    vision: bool
    tools: bool

class StreamChunk(BaseModel):
    text: str
    finish_reason: Optional[str] = None

class HealthStatus(BaseModel):
    is_healthy: bool
    details: str = ""
