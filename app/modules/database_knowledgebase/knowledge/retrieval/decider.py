"""Phase 3 Step 3.9 Decider Interface

Protocol and backends for arbitrating close retrieval candidates:
- Protocol: decide(frame, candidates) -> choices with probability
- Backends configurable via settings.phase3_decider_backend:
  - "none" (default): passes candidates through as-is with rank-based probability
  - "llm": DeepInfra structured JSON, invoked ONLY when top-2 retrieval scores are close (configurable margin). Output must pick only from the shortlist; anything else is rejected. Falls back to retrieval order.
  - "jev": stub raising NotImplementedError
"""

import os
import json
import logging
from typing import Protocol, List, Dict, Any, Optional
from pydantic import BaseModel, Field

from .analyzer import QuestionFrame

logger = logging.getLogger(__name__)


class DecisionChoice(BaseModel):
    item_key: str
    probability: float
    reason: str = ""


class DecisionResult(BaseModel):
    backend: str
    choices: List[DecisionChoice] = Field(default_factory=list)
    tokens_used: int = 0
    invoked: bool = False
    fallback_used: bool = False


class Decider(Protocol):
    """Protocol for candidate decision arbiters."""
    async def decide(
        self,
        frame: QuestionFrame,
        candidates: List[Dict[str, Any]],
        margin_threshold: float = 0.05,
    ) -> DecisionResult:
        ...


class NoneDecider:
    """Default no-op decider. Passes candidates in their retrieval order."""

    async def decide(
        self,
        frame: QuestionFrame,
        candidates: List[Dict[str, Any]],
        margin_threshold: float = 0.05,
    ) -> DecisionResult:
        choices = []
        n = len(candidates)
        for i, c in enumerate(candidates):
            key = c.get("item_key") or c.get("table_name") or c.get("column_name") or str(c)
            # Rank based probability decay
            prob = 1.0 / (1.0 + i) if n > 0 else 1.0
            choices.append(DecisionChoice(item_key=key, probability=round(prob, 3), reason="retrieval_order"))

        return DecisionResult(
            backend="none",
            choices=choices,
            tokens_used=0,
            invoked=False,
            fallback_used=False,
        )


class JevDecider:
    """JEV Decider stub."""

    async def decide(
        self,
        frame: QuestionFrame,
        candidates: List[Dict[str, Any]],
        margin_threshold: float = 0.05,
    ) -> DecisionResult:
        raise NotImplementedError("JEV decider backend is not yet implemented.")


class LLMDecider:
    """DeepInfra structured JSON decider for disambiguating close candidate scores."""

    def __init__(self, api_key: Optional[str] = None, model: str = "meta-llama/Meta-Llama-3-8B-Instruct"):
        self.api_key = api_key or os.getenv("DEEPINFRA_API_KEY", "")
        self.model = model

    async def decide(
        self,
        frame: QuestionFrame,
        candidates: List[Dict[str, Any]],
        margin_threshold: float = 0.05,
    ) -> DecisionResult:
        if len(candidates) < 2:
            return await NoneDecider().decide(frame, candidates, margin_threshold)

        # Check margin between top 1 and top 2
        score1 = float(candidates[0].get("score", 0.0))
        score2 = float(candidates[1].get("score", 0.0))
        if abs(score1 - score2) > margin_threshold or not self.api_key:
            # Margin is clear or no API key, no need to invoke LLM
            return await NoneDecider().decide(frame, candidates, margin_threshold)

        # Candidates shortlist
        shortlist = [
            c.get("item_key") or c.get("table_name") or c.get("column_name") or str(c)
            for c in candidates[:5]
        ]

        # Call DeepInfra if configured, otherwise fallback gracefully
        try:
            import httpx
            prompt = (
                f"Question: \"{frame.original_question}\"\n"
                f"Candidate items: {json.dumps(shortlist)}\n"
                f"Select the most relevant items from the candidates list only. Return JSON with 'selected': list of items in order."
            )
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.post(
                    "https://api.deepinfra.com/v1/openai/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "response_format": {"type": "json_object"},
                    },
                )
                if res.status_code == 200:
                    data = res.json()
                    usage = data.get("usage", {})
                    tokens = usage.get("total_tokens", 0)
                    content = json.loads(data["choices"][0]["message"]["content"])
                    selected = content.get("selected", [])
                    valid_selected = [s for s in selected if s in shortlist]
                    if valid_selected:
                        choices = [
                            DecisionChoice(item_key=s, probability=0.9 - i * 0.1, reason="llm_disambiguation")
                            for i, s in enumerate(valid_selected)
                        ]
                        return DecisionResult(
                            backend="llm",
                            choices=choices,
                            tokens_used=tokens,
                            invoked=True,
                            fallback_used=False,
                        )
        except Exception as e:
            logger.warning(f"LLM Decider invocation failed, falling back: {e}")

        # Fallback to retrieval order
        fallback = await NoneDecider().decide(frame, candidates, margin_threshold)
        fallback.fallback_used = True
        return fallback


def get_decider(backend: Optional[str] = None) -> Decider:
    """Factory to get configured decider backend."""
    b = (backend or os.getenv("PHASE3_DECIDER_BACKEND", "none")).lower()
    if b == "none":
        return NoneDecider()
    elif b == "jev":
        return JevDecider()
    elif b == "llm":
        return LLMDecider()
    else:
        return NoneDecider()
