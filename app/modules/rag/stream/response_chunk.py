from enum import Enum
from pydantic import BaseModel, Field
from typing import Any, Optional, Dict, List, Union

class ChunkType(str, Enum):
    START = "start"
    CONTENT = "content"
    METADATA = "metadata"
    STATUS = "status"
    ERROR = "error"
    DONE = "done"

class SourceChunk(BaseModel):
    chunk_id: str
    source: str
    score: float
    position: int
    reason: Optional[str] = None
    kb_id: str
    content_type: str = "original"
    s3_path: Optional[str] = None

class MetadataPayload(BaseModel):
    sources: List[SourceChunk] = Field(default_factory=list)
    triplets: Optional[List[Dict[str, str]]] = None
    kb_name: str
    augmented_query: Optional[str] = None
    authoritative_entities: Optional[List[Dict[str, Any]]] = None
    session_id: Optional[str] = None
    is_enhanced: Optional[bool] = False
    enhanced_query: Optional[str] = None

class BaseResponseChunk(BaseModel):
    type: ChunkType
    
class StartChunk(BaseResponseChunk):
    type: ChunkType = ChunkType.START

class ContentChunk(BaseResponseChunk):
    type: ChunkType = ChunkType.CONTENT
    text: str

class MetadataChunk(BaseResponseChunk):
    type: ChunkType = ChunkType.METADATA
    data: MetadataPayload

class StatusChunk(BaseResponseChunk):
    type: ChunkType = ChunkType.STATUS
    text: str

class ErrorChunk(BaseResponseChunk):
    type: ChunkType = ChunkType.ERROR
    text: str
    code: Optional[int] = 500

class DoneChunk(BaseResponseChunk):
    type: ChunkType = ChunkType.DONE

ResponseChunk = Union[StartChunk, ContentChunk, MetadataChunk, StatusChunk, ErrorChunk, DoneChunk]
