from enum import Enum
from pydantic import BaseModel
from typing import Any, Optional, Dict

class ChunkType(str, Enum):
    START = "start"
    CONTENT = "content"
    METADATA = "metadata"
    STATUS = "status"
    ERROR = "error"
    DONE = "done"

class ResponseChunk(BaseModel):
    """
    Neutral event model yielded by the ChatPipeline to represent a segment
    of a streaming chat response.
    """
    type: ChunkType
    text: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
