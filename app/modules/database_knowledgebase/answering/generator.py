"""LLM Answer Generator for Phase 2D Grounded Synthesis

Interfaces with DeepInfraLLMClient with temperature=0.0 to synthesize natural-language
answers while stripping chain-of-thought tags and bounding output tokens.
"""

import logging
import time
from typing import Any, Dict, Optional, Tuple

from app.core.llm.deepinfra_llm import DeepInfraLLMClient, strip_think_tags
from .errors import AnswerSynthesisError
from .models import EvidenceModel
from .prompt import GroundedAnswerPromptBuilder

logger = logging.getLogger(__name__)


class AnswerGenerator:
    """Invokes enterprise LLM to generate candidate natural language answers."""

    def __init__(self, llm_client: Optional[DeepInfraLLMClient] = None):
        self.llm_client = llm_client or DeepInfraLLMClient()

    async def generate_answer(
        self,
        user_query: str,
        evidence: EvidenceModel,
        repair_feedback: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate grounded answer text via LLM with telemetry metrics.
        Returns (answer_text, telemetry_dict).
        """
        prompt = GroundedAnswerPromptBuilder.build_prompt(
            user_query=user_query,
            evidence=evidence,
            repair_feedback=repair_feedback,
        )

        t0 = time.perf_counter()
        try:
            raw_response = await self.llm_client.generate_cloud(
                prompt=prompt,
                system_prompt="You are a factual database reporting assistant for GSearchAI.",
                temperature=0.0,
                max_tokens=1024,
                enable_thinking=False,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            clean_text = strip_think_tags(raw_response).strip()
            telemetry = {
                "generator_latency_ms": round(elapsed_ms, 2),
                "model": self.llm_client.model_answer,
                "repaired": repair_feedback is not None,
            }
            return clean_text, telemetry

        except Exception as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            logger.error(f"AnswerGenerator LLM call failed after {elapsed_ms:.2f}ms: {e}")
            raise AnswerSynthesisError(
                detail=f"LLM answer generation failed: {str(e)}",
                details={"latency_ms": round(elapsed_ms, 2)},
            ) from e
