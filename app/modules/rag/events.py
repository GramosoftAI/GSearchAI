from typing import Literal, Optional, List, Dict, Any
from pydantic import BaseModel

class LoopEvent(BaseModel):
    type: Literal["token", "sources", "done", "error", "clarification_needed"]
    text: Optional[str] = None
    sources: Optional[List] = None
    triplets: Optional[List] = None
    error_detail: Optional[str] = None
    escalation_detected: Optional[bool] = None
    message_id: Optional[str] = None
    clarification: Optional[Dict[str, Any]] = None


