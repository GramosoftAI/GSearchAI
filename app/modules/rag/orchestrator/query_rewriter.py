import re
import json
import logging
import asyncio
from typing import Optional, Dict

from app.core.llm.deepinfra_llm import DeepInfraLLMClient
from app.core.llm.routing import LLMTask

logger = logging.getLogger(__name__)

class QueryRewriter:
    """
    Contextualizes follow-up queries by resolving pronouns and carrying over 
    implicit intent (like target columns) from the conversation history and previous intent.
    """
    def __init__(self):
        self.llm_client = DeepInfraLLMClient.get_instance()

    async def rewrite(
        self, 
        current_query: str, 
        chat_history: Optional[str] = None, 
        last_intent_context: Optional[dict] = None,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> str:
        # If no history or context, don't waste an LLM call
        if not chat_history and not last_intent_context:
            return current_query.strip()
            
        intent_str = json.dumps(last_intent_context) if last_intent_context else "None"
            
        prompt = f"""
You are a Query Contextualization Expert. 
Your job is to rewrite the user's current query so that it is self-contained. It must explicitly mention any missing context (like specific columns, metrics, or intent) from the recent conversation history.

[CONVERSATION HISTORY]
{chat_history or "None"}

[LAST KNOWN STRUCTURED INTENT]
{intent_str}

[CURRENT QUERY]
{current_query}

RULES:
1. If the current query is a follow-up (e.g., "what about X", "and for Y?"), carry over the intent (like "salary" or "address") from history/intent context.
2. PRESERVE ALL QUESTION REQUIREMENTS: When the query asks for definitions, categories, counts, benefits, limitations, or comparisons, PRESERVE ALL OF THEM COMPLETELY. NEVER drop subquestions, constraints, or document references (e.g. "According to NIST IR 8397, what is fuzzing, what are the two main categories...").
3. For short follow-up lookups, PREFER TERSE, KEYWORD-STYLE QUERIES (e.g., "EMP1003 salary").
4. PRESERVE EXACT ENTITY IDs (like "EMP1003" or "USR_445") completely intact. Do not paraphrase them.
5. If the current query introduces a NEW topic or NEW column (e.g., "what is the address for X"), DO NOT carry over the old intent. Switch to the new topic.
6. If the current query is already fully specified or complex, return it unchanged.
7. Output ONLY the rewritten query text. No preamble, no quotes, no explanations.
"""
        try:
            # We use the fast intent model for cheap/fast rewrites
            response = await asyncio.wait_for(
                self.llm_client.generate_cloud(
                    prompt=prompt,
                    system_prompt="You are a strict query rewriter. Return only the rewritten text.",
                    temperature=0.0,
                    max_tokens=50,
                    model=self.llm_client.model_intent,
                    timeout=3.0,
                    task=LLMTask.INTENT_DETECTION, # Reusing this for fast routing
                    tenant_id=tenant_id,
                    user_id=user_id
                ),
                timeout=4.0
            )
            rewritten = response.strip().strip('"\'')
            if rewritten and rewritten.lower() != current_query.lower():
                logger.info(f"[QueryRewriter] Contextualized '{current_query}' -> '{rewritten}'")
                return rewritten
        except asyncio.TimeoutError:
            logger.warning("[QueryRewriter] Timeout occurred. Falling back to raw query. [REASON: rewrite_timeout]")
        except Exception as e:
            logger.warning(f"[QueryRewriter] Failed to rewrite query, falling back to original: {e}")
            
        return current_query.strip()
