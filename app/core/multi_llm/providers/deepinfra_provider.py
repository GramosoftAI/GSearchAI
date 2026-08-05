import os
import time
from typing import AsyncIterator, List
import httpx

from ..base import LLMProvider
from ..types import LLMRequest, LLMResponse, HealthStatus, ProviderCapabilities, StreamChunk
from ..exceptions import ProviderTimeoutError, ProviderUnavailableError, ProviderAuthError
from ..config.schema import ProviderConfig

class DeepInfraProvider(LLMProvider):
    capabilities = ProviderCapabilities(
        chat=True, embeddings=True, streaming=True,
        json_mode=True, vision=False, tools=True,
    )

    def __init__(self, config: ProviderConfig):
        self.config = config
        self.base_url = config.base_url or "https://api.deepinfra.com/v1/openai"
        self.api_key = os.environ.get(config.api_key_env, "") if config.api_key_env else ""
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(config.timeout_s),
            headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        )

    def _handle_error(self, exc: Exception) -> None:
        if isinstance(exc, httpx.TimeoutException):
            raise ProviderTimeoutError(message=str(exc), provider="deepinfra") from exc
        if isinstance(exc, httpx.HTTPStatusError):
            if exc.response.status_code in (401, 403):
                raise ProviderAuthError(message=str(exc), provider="deepinfra") from exc
            if exc.response.status_code >= 500:
                raise ProviderUnavailableError(message=str(exc), provider="deepinfra") from exc
        raise ProviderUnavailableError(message=str(exc), provider="deepinfra") from exc

    async def chat(self, request: LLMRequest) -> LLMResponse:
        payload = {
            "model": request.model,
            "messages": [m.dict() for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
            "enable_thinking": False,
            "reasoning_effort": "none",
        }
        if request.json_schema:
            payload["response_format"] = {"type": "json_object"}
        if request.tools:
            payload["tools"] = [t.dict() for t in request.tools]
        
        start_time = time.time()
        try:
            response = await self.client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            latency = int((time.time() - start_time) * 1000)
            
            usage = data.get("usage", {})
            return LLMResponse(
                text=data["choices"][0]["message"]["content"],
                provider="deepinfra",
                model=request.model or "unknown",
                latency_ms=latency,
                tokens_prompt=usage.get("prompt_tokens", 0),
                tokens_completion=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                finish_reason=data["choices"][0].get("finish_reason", "unknown"),
                cached=False,
                raw=data
            )
        except Exception as e:
            self._handle_error(e)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        # Fallback to chat API for completion since OpenAI style doesn't strictly differ unless using /completions
        return await self.chat(request)

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        payload = {
            "model": request.model,
            "messages": [m.dict() for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True,
            "enable_thinking": False,
            "reasoning_effort": "none",
        }
        try:
            async with self.client.stream("POST", "/chat/completions", json=payload) as response:
                response.raise_for_status()
                async for chunk in response.aiter_lines():
                    if chunk.startswith("data: "):
                        chunk_data = chunk[6:]
                        if chunk_data == "[DONE]":
                            break
                        import json
                        try:
                            data = json.loads(chunk_data)
                            delta = data["choices"][0].get("delta", {})
                            yield StreamChunk(
                                text=delta.get("content", ""),
                                finish_reason=data["choices"][0].get("finish_reason")
                            )
                        except json.JSONDecodeError:
                            pass
        except Exception as e:
            self._handle_error(e)

    async def embed(self, texts: List[str]) -> List[List[float]]:
        # Need a default model for embeddings if not provided, assuming request.model would come here, 
        # but this takes only texts. In reality config or passed parameter should dictate.
        embed_model = os.environ.get("MODEL_EMBEDDING", "Qwen/Qwen3-Embedding-8B")
        payload = {
            "model": embed_model, 
            "input": texts
        }
        try:
            response = await self.client.post("/embeddings", json=payload)
            response.raise_for_status()
            data = response.json()
            return [item["embedding"] for item in data["data"]]
        except Exception as e:
            self._handle_error(e)

    async def health_check(self) -> HealthStatus:
        if not self.api_key:
            return HealthStatus(is_healthy=False, details="Missing API key")
        try:
            response = await self.client.get("/models")
            response.raise_for_status()
            return HealthStatus(is_healthy=True, details="DeepInfra is healthy")
        except Exception as e:
            return HealthStatus(is_healthy=False, details=str(e))

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # We could close the client here if we wanted a new one per request, 
        # but usually factory manages the singleton pool.
        pass
