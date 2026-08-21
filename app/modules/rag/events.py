from typing import Literal, Optional, List
from pydantic import BaseModel

class LoopEvent(BaseModel):
    type: Literal["token", "sources", "done", "error"]
    text: Optional[str] = None
    sources: Optional[List] = None
    triplets: Optional[List] = None
    error_detail: Optional[str] = None
