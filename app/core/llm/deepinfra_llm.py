"""

DeepInfra LLM Client - Production-grade answer generation



Provides async HTTP client for generating structured answers via DeepInfra chat API.

Used in Phase 3 RAG pipeline to transform context into natural language answers.



MODEL: qwen-2.5-72b-instruct (fast, accurate, production-ready)

TEMPERATURE: 0.7 (balanced creativity + consistency)

MAX_TOKENS: 1024 (prevents runaway output)

COST: Minimal per request via DeepInfra



SAFETY:

- Automatic retries (3 attempts)

- Timeout protection (15 seconds)

- Graceful fallback to template

- Token limits (prevents overload)

- Structured prompting

"""



import httpx

import logging

import asyncio

import base64

import json
import time
from typing import Optional, List, Dict, Any, Callable

from dataclasses import dataclass

from ..config import get_settings

import re
from ..billing.utils import is_billing_enabled

logger = logging.getLogger(__name__)

settings = get_settings()


def strip_think_tags(text: str) -> str:
    """
    Remove <think>...</think> reasoning blocks from model output.
    Must be applied to ALL model responses before any downstream use.
    """
    if not text:
        return ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()

# Prompt versioning (for A/B testing and rollout tracking)
PROMPT_VERSION = "v1"

# Unified LiteLLM pricing defaults
from app.core.llm.pricing import get_model_pricing
_default_inp_p, _default_out_p = get_model_pricing(None)
PRICE_PER_1M_INPUT_TOKENS = _default_inp_p
PRICE_PER_1M_OUTPUT_TOKENS = _default_out_p



# Global rate limiter (controlled by .env INGESTION_LLM_CONCURRENCY)

_llm_semaphore = asyncio.Semaphore(settings.ingestion_llm_concurrency)



# LLM call metrics

_llm_calls = 0

_llm_errors = 0

_llm_fallbacks = 0

_total_prompt_tokens = 0

_total_completion_tokens = 0

_total_cost_estimate = 0.0



# Per-tenant & per-agent cost tracking (for multi-tenant billing)

# Format: {tenant_id: {agent_id: {"calls": int, "cost": float, "tokens": int}}}

_tenant_costs = {}  # Track costs per tenant for accurate billing

_agent_costs = {}  # Track costs per agent for usage analytics





@dataclass

class LLMResponse:

    """

    Structured response from LLM with metrics for billing + optimization.



    Attributes:

        answer: Generated answer text

        prompt_tokens: Tokens in prompt (input)

        completion_tokens: Tokens in answer (output)

        total_tokens: Sum of prompt + completion tokens

        cost_estimate: Estimated cost in USD (for billing)

        prompt_version: Version of prompt used (for A/B testing)

        source: "DeepInfra" (API) or "Template" (fallback)

        tenant_id: Tenant UUID (for multi-tenant cost tracking)

        agent_id: Agent UUID (for usage analytics)

    """



    answer: str

    prompt_tokens: int = 0

    completion_tokens: int = 0

    total_tokens: int = 0

    cost_estimate: float = 0.0

    prompt_version: str = PROMPT_VERSION

    source: str = "DeepInfra"

    tenant_id: Optional[str] = None

    agent_id: Optional[str] = None

    model_name: Optional[str] = None

    request_id: Optional[str] = None





class DeepInfraLLMClient:

    """

    Async HTTP client for DeepInfra chat/completions API.

    """

    # Shared client to reuse connections (Persistent Pool)

    _shared_client: Optional[httpx.AsyncClient] = None



    @classmethod
    async def get_client(cls) -> httpx.AsyncClient:
        """Get or create the shared persistent HTTP client."""
        if cls._shared_client is None or cls._shared_client.is_closed:
            # PROD-GRADE TIMEOUTS: 
            # DeepSeek-R1 <think> tags can take up to 45-60 seconds before yielding.
            # 300s read timeout ensures the WebSocket doesn't abruptly interrupt.
            timeout_config = httpx.Timeout(
                connect=10.0,   # Fail fast on network drop
                read=300.0,     # Allow up to 5 mins for LLM streaming response
                write=30.0,     # Sending prompt should be fast
                pool=30.0       # Wait up to 30s for an available connection from pool
            )
            cls._shared_client = httpx.AsyncClient(
                timeout=timeout_config,
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                headers={"Authorization": f"Bearer {settings.deepinfra_api_key}"}
            )
        return cls._shared_client



    def __init__(self):
        """
        Initialize DeepInfra LLM client with API key and stage model config from Settings.
        """
        settings = get_settings()
        self.api_key = settings.deepinfra_api_key
        self.base_url = settings.deepinfra_api_url

        # Task-specific model assignments — all from settings, never hardcoded
        self.model_answer          = settings.model_answer
        self.model_answer_fallback = getattr(settings, "model_answer_fallback", "deepseek-ai/DeepSeek-V3")
        self.model_answer_try      = getattr(settings, "model_answer_try", 3)
        self.model_extraction      = settings.active_model("extraction")
        self.model_intent          = settings.model_intent
        self.model_nl_to_cypher    = settings.active_model("nl_to_cypher")
        self.model_reranker        = settings.active_model("reranker")
        self.model_memory          = settings.model_memory
        self.model_vision          = settings.model_vision

        # Token limits — all from settings
        self.max_tokens_answer       = settings.max_tokens_answer
        self.max_tokens_extraction   = settings.max_tokens_extraction
        self.max_tokens_intent       = settings.max_tokens_intent
        self.max_tokens_nl_to_cypher = settings.max_tokens_nl_to_cypher
        self.max_tokens_reranker     = settings.max_tokens_reranker
        self.max_tokens_memory       = settings.max_tokens_memory
        self.max_tokens_vision       = settings.max_tokens_vision

        # Backwards compatibility attributes
        self.deepinfra_model = self.model_answer
        self.gateway_model = self.model_extraction
        self.deepinfra_base_url = f"{self.base_url}/chat/completions"
        self.gateway_base_url = f"{self.base_url}/chat/completions"
        self.deepinfra_api_key = self.api_key
        self.gateway_api_key = self.api_key

        self.timeout = 60.0  # Enterprise timeout cap against stalled sockets (60s for high-concurrency extraction)
        self.max_retries = self.model_answer_try  # Configurable retry attempts from settings
        self.max_tokens = self.max_tokens_answer  # Max output tokens
        self.max_answer_length = 2000  # Max chars in answer
        self.temperature = 0.0

        logger.info(
            f"LLM Client init: Answer -> {self.model_answer} (Fallback: {self.model_answer_fallback}, Max Retries: {self.max_retries}), Extraction -> {self.model_extraction}"
        )



    async def vision_ocr(

        self,

        image_bytes: bytes,

        tenant_id: Optional[str] = None,

        agent_id: Optional[str] = None,

    ) -> str:

        """

        PERFORM AI-BASED OCR ON IMAGE DATA.



        Uses: llama-3.2-11b-vision-instruct (highly accurate for scanned docs)

        

        Args:

            image_bytes: Raw bytes of the image (PNG/JPEG)

            tenant_id: For billing

            agent_id: For usage tracking

            

        Returns:

            str: Extracted text from the image

        """

        model = self.model_vision

        base64_image = base64.b64encode(image_bytes).decode("utf-8")

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract all text from this image exactly as it appears. Maintains the layout if possible. Do not add any commentary."},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                        }
                    ]
                }
            ],
            "max_tokens": self.max_tokens_vision,
            "enable_thinking": False,
            "reasoning_effort": "none",
        }



        headers = {

            "Authorization": f"Bearer {self.api_key}",

            "Content-Type": "application/json",

        }



        async with _llm_semaphore:
            client = await self.get_client()
            response = await client.post(self.deepinfra_base_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

            

            text = data["choices"][0]["message"]["content"].strip()

            # Track usage (estimated)
            cost = (1000 / 1_000_000) * PRICE_PER_1M_INPUT_TOKENS # Rough estimation
            self._track_billing(tenant_id, agent_id, cost, 1000)

            return strip_think_tags(text)



    async def generate(

        self,

        prompt: str,

        system_prompt: str = "You are a helpful assistant.",

        max_tokens: Optional[int] = None,

        temperature: Optional[float] = None,

        enable_thinking: bool = False,

    ) -> str:

        """

        Generic prompt generation (for entity extraction, triplet extraction, etc.)

        Includes retry logic and extended timeout for extraction tasks.

        """

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model_extraction,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens or self.max_tokens_extraction,
            "enable_thinking": False,
            "reasoning_effort": "none",
        }
        
        # Retry logic (3 attempts with backoff)
        last_error = None
        for attempt in range(self.max_retries):
            try:
                client = await self.get_client()
                async with _llm_semaphore:
                    response = await client.post(self.deepinfra_base_url, headers=headers, json=payload, timeout=self.timeout)

                response.raise_for_status()

                data = response.json()

                content = data["choices"][0]["message"]["content"].strip()
                return strip_think_tags(content)

            except Exception as e:

                last_error = e

                logger.warning(f"generate() attempt {attempt+1}/{self.max_retries} failed: {e}")

                if attempt < self.max_retries - 1:

                    import asyncio

                    await asyncio.sleep(1.0)

        

        logger.error(f"generate() all {self.max_retries} attempts failed. Last error: {last_error}")
        raise last_error
    async def generate_cloud(
        self, 
        prompt: str, 
        system_prompt: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        enable_thinking: Optional[bool] = False,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        task: Optional[Any] = None,
    ) -> str:
        """
        Equivalent to generate() but explicitly routes to the cloud DeepInfra model 
        (qwen3.5-9B) for faster processing (e.g. query routing, planning, answer generation).
        Thinking is disabled by default to save tokens.
        """
        headers = {
            "Content-Type": "application/json",
        }
        if self.deepinfra_api_key:
            headers["Authorization"] = f"Bearer {self.deepinfra_api_key}"
        
        effective_model = model or self.model_answer
        payload = {
            "model": effective_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens or self.max_tokens_answer,
            "enable_thinking": False,
            "reasoning_effort": "none"
        }
        
        last_error = None
        for attempt in range(3):
            try:
                client = await self.get_client()
                async with _llm_semaphore:
                    response = await client.post(self.deepinfra_base_url, headers=headers, json=payload, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"].strip()
                return strip_think_tags(content)
            except Exception as e:
                last_error = e
                logger.warning(f"generate_cloud() attempt {attempt+1}/3 failed: {e}")
                if attempt < 2:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
        
        logger.error(f"generate_cloud() all 3 attempts failed. Last error: {last_error}")
        raise last_error

    async def generate_with_usage(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        enable_thinking: bool = False,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Similar to generate() but returns token usage alongside content.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        target_model = model or self.model_extraction
        payload = {
            "model": target_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens or self.max_tokens_extraction,
            "enable_thinking": False,
            "reasoning_effort": "none",
        }
        
        last_error = None
        for attempt in range(self.max_retries):
            try:
                client = await self.get_client()
                async with _llm_semaphore:
                    response = await client.post(self.deepinfra_base_url, headers=headers, json=payload, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"].strip()
                content = strip_think_tags(content)
                    
                usage = data.get("usage", {})
                return {
                    "content": content,
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "model_name": target_model,
                }
            except Exception as e:
                last_error = e
                logger.warning(f"generate_with_usage() attempt {attempt+1}/{self.max_retries} failed: {e}")
                if attempt < self.max_retries - 1:
                    import asyncio
                    await asyncio.sleep(1.0)
        
        logger.error(f"generate_with_usage() all {self.max_retries} attempts failed. Last error: {last_error}")
        raise last_error


    async def stream_answer(
        self,
        query: str,
        context: str,
        tenant_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        agent_persona: Optional[dict] = None,
        enable_thinking: Optional[bool] = None,
        on_usage_callback: Optional[Callable[[dict], None]] = None,
        model: Optional[str] = None,
    ):
        """
        Stream structured answer from query + context.
        Yields text chunks as they arrive from the API.
        """
        prompt = self._build_prompt(query, context)

        headers = {
            "Authorization": f"Bearer {self.deepinfra_api_key}",
            "Content-Type": "application/json",
        }
        
        # Build System Persona
        system_content = "You are a helpful knowledge base assistant."
        if agent_persona:
            name = agent_persona.get("name", "Assistant")
            personality = agent_persona.get("personality", "Friendly")
            prompt_custom = agent_persona.get("system_prompt", "")
            
            system_content = f"You are {name}. Your tone and personality is {personality}. "
            if prompt_custom:
                system_content += f"\n\nInstructions: {prompt_custom}"
            
            # STRICT GROUNDING + NUMERIC PRESERVATION
            system_content += (
                "\n\nCRITICAL INSTRUCTION: You must strictly respond ONLY using the provided knowledge base content, CONVERSATION HISTORY, AND the 'MANDATORY USER PREFERENCES & MEMORY DIRECTIVES'. "
                "Do not rely on your own pre-trained knowledge. Always include precise numeric values, years, percentages, "
                "and symbols (like GPA scores, dates, or currency) explicitly mentioned in the context. "
                "Within the 'MANDATORY USER PREFERENCES & MEMORY DIRECTIVES', the 'Stored User Profile & Preferences (Active Overrides)' is the ABSOLUTE SOURCE OF TRUTH. "
                "You MUST use ANY relevant facts from the 'Active Overrides' to answer the user's question, EVEN IF those facts are completely absent from the document context. "
                "If the user asks to filter or modify previous answers, prioritize the CONVERSATION HISTORY. "
                "If an 'Active Override' contradicts the document context or 'Graph Memory', the 'Active Override' always wins. "
                "If the answer is not contained within the provided context, conversation history, and no preference applies, you MUST respond exactly with: "
                "\"Im sorry, but the requested information is not available within my current knowledge base. "
                "Please try a related query or provide additional context.\""
            )
        else:
            system_content = (
                "You are a helpful knowledge base assistant. You must strictly respond ONLY using the provided context, CONVERSATION HISTORY, AND the 'MANDATORY USER PREFERENCES & MEMORY DIRECTIVES'. "
                "Preserve all numeric values, years, and specific details like GPA or percentages. "
                "Within the 'MANDATORY USER PREFERENCES & MEMORY DIRECTIVES', the 'Stored User Profile & Preferences (Active Overrides)' is the ABSOLUTE SOURCE OF TRUTH. "
                "You MUST use ANY relevant facts from the 'Active Overrides' to answer the user's question, EVEN IF those facts are completely absent from the document context. "
                "If the user asks to filter or modify previous answers, prioritize the CONVERSATION HISTORY. "
                "If an 'Active Override' contradicts the document context or 'Graph Memory', the 'Active Override' always wins. "
                "If the information is not available in the context, conversation history, and no preference applies, respond exactly with: "
                "\"Im sorry, but the requested information is not available within my current knowledge base. "
                "Please try a related query or provide additional context.\""
            )

        models_to_try = []
        if model and model.strip():
            models_to_try.append(model.strip())
        if self.model_answer not in models_to_try:
            models_to_try.append(self.model_answer)
        if self.model_answer_fallback and self.model_answer_fallback not in models_to_try:
            models_to_try.append(self.model_answer_fallback)

        client = await self.get_client()
        stream_timeout = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=30.0)

        for model_idx, target_model in enumerate(models_to_try):
            is_fallback_model = (model_idx > 0)
            max_attempts = self.model_answer_try if not is_fallback_model else 2

            for attempt in range(1, max_attempts + 1):
                logger.info(
                    f"LLM Stream Attempt {attempt}/{max_attempts} for model '{target_model}' "
                    f"({'FALLBACK' if is_fallback_model else 'PRIMARY'})"
                )

                payload = {
                    "model": target_model,
                    "messages": [
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens_answer,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                    "enable_thinking": False,
                    "reasoning_effort": "none",
                }

                think_state = 0
                think_buf = ""
                full_text = ""
                chunk_yielded = False
                start_time = time.time()

                try:
                    async with client.stream("POST", self.deepinfra_base_url, headers=headers, json=payload, timeout=stream_timeout) as response:
                        if response.status_code != 200:
                            logger.warning(
                                f"LLM API Error {response.status_code} for model '{target_model}' (Attempt {attempt}/{max_attempts})"
                            )
                            if attempt < max_attempts:
                                await asyncio.sleep(1.0 * attempt)
                                continue
                            else:
                                break  # Move to fallback model if available

                        async for line in response.aiter_lines():
                            if not line or line.strip() == "":
                                continue

                            if line.startswith("data: "):
                                data_str = line[6:].strip()
                                if data_str == "[DONE]":
                                    break

                                try:
                                    data = json.loads(data_str)

                                    if "usage" in data and data["usage"] is not None:
                                        usage_data = dict(data["usage"])
                                        usage_data["model_name"] = target_model
                                        if on_usage_callback:
                                            on_usage_callback(usage_data)
                                        continue

                                    if not data.get("choices"):
                                        continue

                                    chunk = data["choices"][0]["delta"].get("content", "")
                                    if not chunk:
                                        continue

                                    delta = chunk

                                    # Filter <think> tags
                                    clean_delta = ""
                                    if think_state == 0:
                                        think_buf += delta
                                        b = think_buf.lstrip()

                                        if b.startswith("<think>"):
                                            think_state = 1
                                            think_buf = b[7:]
                                            if "</think>" in think_buf:
                                                think_state = 2
                                                clean_delta = think_buf.split("</think>", 1)[1].lstrip("\n")
                                                think_buf = ""
                                        elif "<think>".startswith(b):
                                            clean_delta = ""
                                        else:
                                            think_state = 2
                                            clean_delta = think_buf
                                            think_buf = ""

                                    elif think_state == 1:
                                        think_buf += delta
                                        if "</think>" in think_buf:
                                            think_state = 2
                                            clean_delta = think_buf.split("</think>", 1)[1].lstrip("\n")
                                            think_buf = ""

                                    elif think_state == 2:
                                        clean_delta = delta

                                    if clean_delta:
                                        full_text += clean_delta
                                        chunk_yielded = True
                                        yield clean_delta
                                except json.JSONDecodeError as e:
                                    logger.warning(f"Response parsing error in stream: {e} for line {data_str}")
                                    continue

                    if think_state == 0 and think_buf and not "<think>".startswith(think_buf.lstrip()):
                        full_text += think_buf
                        chunk_yielded = True
                        yield think_buf

                    if "[Source:" in full_text:
                        last_source_idx = full_text.rfind("[Source:")
                        last_close_idx = full_text.rfind("]", last_source_idx)
                        if last_close_idx == -1:
                            yield "]"

                    logger.info(
                        f"LLM Stream Completed in {time.time() - start_time:.2f}s using model '{target_model}'"
                    )
                    return  # Success! Exit function.

                except httpx.ReadTimeout:
                    logger.error(
                        f"LLM Stream ReadTimeout after {time.time() - start_time:.2f}s for model '{target_model}' (Attempt {attempt}/{max_attempts})"
                    )
                    if chunk_yielded:
                        yield " [Error: Stream timed out]"
                        return
                    if attempt < max_attempts:
                        await asyncio.sleep(1.0 * attempt)
                except Exception as e:
                    logger.error(
                        f"LLM Stream Exception for model '{target_model}' (Attempt {attempt}/{max_attempts}): {e}"
                    )
                    if chunk_yielded:
                        yield f" [Error: Stream interrupted - {e}]"
                        return
                    if attempt < max_attempts:
                        await asyncio.sleep(1.0 * attempt)

            if is_fallback_model:
                logger.error(f"Fallback model '{target_model}' also failed.")
            else:
                logger.warning(
                    f"Primary model '{target_model}' failed after {max_attempts} attempts. "
                    f"Switching to fallback model '{models_to_try[1] if len(models_to_try) > 1 else 'None'}'..."
                )

        yield "Error: All answer generation models (primary & fallback) failed to respond."

    async def generate_answer(
        self,
        query: str,
        context: str,
        tenant_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        agent_persona: Optional[dict] = None,
        enable_thinking: Optional[bool] = None,
        model: Optional[str] = None,
    ) -> LLMResponse:
        """
        Generate structured answer from query + context.

        FLOW:
        1. Validate inputs (not empty)
        2. Build structured prompt
        3. Acquire rate limit semaphore (prevent throttling)
        4. Call API with retries
        5. Validate response & token usage
        6. Track cost per tenant/agent (for multi-tenant billing)
        7. Return LLMResponse with metrics (tokens, cost, version)
        """
        global _llm_calls, _total_prompt_tokens, _total_completion_tokens, _total_cost_estimate

        # Validate inputs
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")
        if not context or not context.strip():
            raise ValueError("Context cannot be empty")

        _llm_calls += 1
        target_model = model.strip() if (model and model.strip()) else self.model_answer
        logger.debug(
            f"Generating answer using '{target_model}' for query: {query[:60]}... (prompt_version={PROMPT_VERSION})"
        )

        # Build structured prompt (improves consistency + quality)
        prompt = self._build_prompt(query, context)
        logger.debug(f"Prompt built ({len(prompt)} chars)")

        # Estimate prompt tokens (rough: ~4 chars per token)
        estimated_prompt_tokens = max(len(prompt) // 4, 1)

        # Prepare headers
        headers = {
            "Authorization": f"Bearer {self.deepinfra_api_key}",
            "Content-Type": "application/json",
        }

        # Build System Persona
        system_content = "You are a helpful knowledge base assistant."
        if agent_persona:
            name = agent_persona.get("name", "Assistant")
            personality = agent_persona.get("personality", "Friendly")
            prompt_custom = agent_persona.get("system_prompt", "")
            
            system_content = f"You are {name}. Your tone and personality is {personality}. "
            if prompt_custom:
                system_content += f"\n\nInstructions: {prompt_custom}"
            
            system_content += (
                "\n\nCRITICAL INSTRUCTION: You must strictly respond ONLY using the provided knowledge base content. "
                "Do not rely on your own pre-trained knowledge. Always include precise numeric values, years, percentages, "
                "and symbols (like GPA scores, dates, or currency) explicitly mentioned in the context. "
                "If the answer is not contained within the provided context, you MUST respond exactly with: "
                "\"Im sorry, but the requested information is not available within my current knowledge base. "
                "Please try a related query or provide additional context.\""
            )
        else:
            system_content = (
                "You are a helpful knowledge base assistant. You must strictly respond ONLY using the provided context. "
                "Preserve all numeric values, years, and specific details like GPA or percentages. "
                "If the information is not available in the context, respond exactly with: "
                "\"Im sorry, but the requested information is not available within my current knowledge base. "
                "Please try a related query or provide additional context.\""
            )

        payload = {
            "model": target_model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens_answer,
            "enable_thinking": False,
            "reasoning_effort": "none",
        }

        # Rate limit guard (prevent API throttling)
        async with _llm_semaphore:
            last_error = None

            for attempt in range(self.max_retries):
                try:
                    logger.debug(
                        f"API request attempt {attempt + 1}/{self.max_retries} for model {target_model}"
                    )

                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        response = await client.post(
                            self.deepinfra_base_url, headers=headers, json=payload
                        )
                        response.raise_for_status()
                        data = response.json()

                        if "choices" not in data or len(data["choices"]) == 0:
                            raise ValueError("Invalid API response: missing choices")

                        answer = data["choices"][0].get("message", {}).get("content")
                        if not answer:
                            raise ValueError("Invalid API response: missing content")

                        if len(answer) > self.max_answer_length:
                            logger.warning(
                                f"  Answer truncated ({len(answer)} > {self.max_answer_length} chars)"
                            )
                            answer = answer[: self.max_answer_length] + "..."

                        answer = answer.strip()
                        import re as _re
                        answer = _re.sub(r'<think>.*?</think>', '', answer, flags=_re.DOTALL).strip()
                        if '<think>' in answer:
                            answer = answer[:answer.index('<think>')].strip()

                        # Extract token usage from response
                        usage = data.get("usage", {})
                        prompt_tokens = usage.get(
                            "prompt_tokens", estimated_prompt_tokens
                        )
                        completion_tokens = usage.get(
                            "completion_tokens", len(answer) // 4
                        )
                        total_tokens = prompt_tokens + completion_tokens

                        # Calculate cost estimate with model pricing
                        from app.core.llm.pricing import calculate_token_cost
                        cost_estimate = calculate_token_cost(
                            model_name=target_model,
                            input_tokens=prompt_tokens,
                            output_tokens=completion_tokens,
                        )

                        # Track global metrics
                        _total_prompt_tokens += prompt_tokens
                        _total_completion_tokens += completion_tokens
                        _total_cost_estimate += cost_estimate

                        # Track per-tenant costs and per-agent usage
                        self._track_billing(
                            tenant_id, agent_id, cost_estimate, total_tokens
                        )

                        logger.info(
                            f"Answer source: DeepInfra (model={target_model}, tokens={total_tokens}, cost=${cost_estimate:.6f})"
                        )

                        return LLMResponse(
                            answer=answer,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            total_tokens=total_tokens,
                            cost_estimate=cost_estimate,
                            prompt_version=PROMPT_VERSION,
                            source="DeepInfra",
                            tenant_id=tenant_id,
                            agent_id=agent_id,
                            model_name=target_model,
                        )



                except httpx.TimeoutException:

                    last_error = TimeoutError(

                        f"API timeout after {self.timeout}s (attempt {attempt + 1})"

                    )

                    logger.warning(

                        f"  API timeout on attempt {attempt + 1}/{self.max_retries}"

                    )



                except httpx.HTTPStatusError as e:

                    # HTTP error (4xx, 5xx)

                    last_error = e

                    logger.warning(

                        f"  HTTP {e.response.status_code} on attempt {attempt + 1}/{self.max_retries}: {e.response.text}"

                    )



                except (ValueError, KeyError) as e:

                    # Response parsing error

                    last_error = e

                    logger.warning(f"  Response parsing error: {e}")



                except Exception as e:

                    # Unexpected error

                    last_error = e

                    logger.warning(f"  Unexpected error on attempt {attempt + 1}: {e}")



                # Don't retry on last attempt

                if attempt < self.max_retries - 1:

                    # Exponential backoff: 1s, 2s, 4s, ...

                    wait_time = 2**attempt

                    logger.debug(f"Retrying in {wait_time}s...")

                    await asyncio.sleep(wait_time)



            # All retries exhausted

            global _llm_errors

            _llm_errors += 1

            logger.error(

                f" All LLM API attempts failed ({self.max_retries} retries). Last error: {last_error}"

            )

            raise last_error



    def _build_prompt(self, query: str, context: str) -> str:

        """

        Build structured prompt for LLM (improves consistency + quality).



        STRUCTURE:

        1. Context (retrieved relevant information)

        2. Query (user's question)

        3. Instructions (how to answer)



        Args:

            query: User query

            context: Retrieved context



        Returns:

            Formatted prompt string

        """

        prompt = f"""You are an elite, human-like RAG assistant. Your primary goal is to help the user by providing accurate answers based on the provided CONTEXT.



STRICT GROUNDING RULES:

1. If the QUESTION is a factual inquiry, use ONLY the provided CONTEXT to answer.

2. PRESERVE NUMERICS: Always include precise years, scores (GPA), and technical symbols.

3. If the answer to a factual question is NOT in the context, respond with: "Im sorry, but I don't have that specific information in my current knowledge base."



HUMAN-LIKE ASSISTANCE:

1. If the QUESTION is a greeting (e.g., Hi, Hello) or a social interaction, respond warmly and professionally as a helpful assistant.

2. Maintain a professional yet friendly "human-to-human" tone. Do not sound like a rigid bot.

3. If the context is empty but the user is just saying hello, do NOT give the "information not available" error. Instead, greet them and ask how you can help.



CONTEXT:

{context}



QUESTION:

{query}



ANSWER:

"""

        return prompt



    def _track_billing(

        self,

        tenant_id: Optional[str],

        agent_id: Optional[str],

        cost_estimate: float,

        total_tokens: int,

    ) -> None:

        """

        Track LLM usage for billing (only if billing enabled).



        Centralizes billing logic to keep code clean.

        When billing disabled, this is a no-op.



        Args:

            tenant_id: Tenant UUID (for per-tenant billing)

            agent_id: Agent UUID (for per-agent usage)

            cost_estimate: Cost in USD

            total_tokens: Total tokens used

        """

        # Feature flag: only track if billing enabled

        if not is_billing_enabled():

            return



        # Track per-tenant costs (for multi-tenant billing)

        if tenant_id:

            if tenant_id not in _tenant_costs:

                _tenant_costs[tenant_id] = {

                    "calls": 0,

                    "cost": 0.0,

                    "tokens": 0,

                }

            _tenant_costs[tenant_id]["calls"] += 1

            _tenant_costs[tenant_id]["cost"] += cost_estimate

            _tenant_costs[tenant_id]["tokens"] += total_tokens



        # Track per-agent usage (for analytics)

        if agent_id:

            if agent_id not in _agent_costs:

                _agent_costs[agent_id] = {

                    "calls": 0,

                    "cost": 0.0,

                    "tokens": 0,

                }

            _agent_costs[agent_id]["calls"] += 1

            _agent_costs[agent_id]["cost"] += cost_estimate

            _agent_costs[agent_id]["tokens"] += total_tokens





# Singleton instance (reuse across application)

_llm_client: Optional[DeepInfraLLMClient] = None





async def get_llm_client() -> DeepInfraLLMClient:

    """

    Get or create singleton LLM client instance.



    Lazy initialization on first use.



    Returns:

        DeepInfraLLMClient: Singleton instance

    """

    global _llm_client

    if _llm_client is None:

        _llm_client = DeepInfraLLMClient()

    return _llm_client





async def generate_answer(

    query: str,

    context: str,

    tenant_id: Optional[str] = None,

    agent_id: Optional[str] = None,

) -> LLMResponse:

    """

    Generate answer (convenience function).



    Wraps get_llm_client() + generate_answer() for simple usage.



    Args:

        query: User query

        context: Retrieved context

        tenant_id: Tenant UUID (optional, for cost tracking)

        agent_id: Agent UUID (optional, for usage analytics)



    Returns:

        LLMResponse: Response with answer + metrics (tokens, cost, version, tenant_id, agent_id)

    """

    client = await get_llm_client()

    return await client.generate_answer(

        query=query,

        context=context,

        tenant_id=tenant_id,

        agent_id=agent_id,

    )





def get_llm_metrics() -> dict:

    """

    Get global LLM metrics for monitoring.



    Returns:

        Dict with:

        - total_calls: Total API calls

        - total_errors: Failed API calls

        - total_fallbacks: Template fallbacks

        - total_prompt_tokens: Total input tokens

        - total_completion_tokens: Total output tokens

        - total_cost_estimate: Total cost (USD)

        - average_cost_per_call: Mean cost per successful call

        - error_rate: Percentage of failed calls

        - per_tenant: Dict of tenant_id  {calls, cost, tokens}

        - per_agent: Dict of agent_id  {calls, cost, tokens}

    """

    if _llm_calls == 0:

        return {"status": "no_calls_yet"}



    average_cost = _total_cost_estimate / max(_llm_calls - _llm_errors, 1)

    error_rate = (_llm_errors / _llm_calls) * 100 if _llm_calls > 0 else 0



    return {

        "total_calls": _llm_calls,

        "total_errors": _llm_errors,

        "total_fallbacks": _llm_fallbacks,

        "total_prompt_tokens": _total_prompt_tokens,

        "total_completion_tokens": _total_completion_tokens,

        "total_cost_estimate": round(_total_cost_estimate, 4),

        "average_cost_per_call": round(average_cost, 6),

        "error_rate_percent": round(error_rate, 2),

        "per_tenant": {

            tid: {

                "calls": metrics["calls"],

                "cost": round(metrics["cost"], 6),

                "tokens": metrics["tokens"],

            }

            for tid, metrics in _tenant_costs.items()

        },

        "per_agent": {

            aid: {

                "calls": metrics["calls"],

                "cost": round(metrics["cost"], 6),

                "tokens": metrics["tokens"],

            }

            for aid, metrics in _agent_costs.items()

        },

    }





def get_tenant_billing(tenant_id: str) -> dict:

    """

    Get billing metrics for a specific tenant.



    Used for per-tenant cost allocation and billing.



    Args:

        tenant_id: Tenant UUID



    Returns:

        Dict with tenant's cost metrics (calls, cost, tokens)

    """

    if tenant_id not in _tenant_costs:

        return {"status": "no_usage", "cost": 0.0}



    metrics = _tenant_costs[tenant_id]

    return {

        "tenant_id": tenant_id,

        "total_calls": metrics["calls"],

        "total_cost": round(metrics["cost"], 6),

        "total_tokens": metrics["tokens"],

        "average_cost_per_call": round(metrics["cost"] / max(metrics["calls"], 1), 6),

    }





def get_agent_usage(agent_id: str) -> dict:

    """

    Get usage metrics for a specific agent.



    Used for per-agent analytics and usage tracking.



    Args:

        agent_id: Agent UUID



    Returns:

        Dict with agent's usage metrics (calls, cost, tokens)

    """

    if agent_id not in _agent_costs:

        return {"status": "no_usage", "cost": 0.0}



    metrics = _agent_costs[agent_id]

    return {

        "agent_id": agent_id,

        "total_calls": metrics["calls"],

        "total_cost": round(metrics["cost"], 6),

        "total_tokens": metrics["tokens"],

        "average_cost_per_call": round(metrics["cost"] / max(metrics["calls"], 1), 6),

    }

