from pydantic import BaseModel
from typing import Literal, List

class FileMatch(BaseModel):
    kb_id: str
    name: str
    match_type: Literal["exact_identifier", "semantic"]
    score: float
    matched_on: str

class RoutingResult(BaseModel):
    is_confident_match: bool
    matched_kb_ids: List[str]
    candidates: List[FileMatch]
    reason: str
