import json
import time
from typing import AsyncIterator, List
import httpx

from ..base import LLMProvider
from ..types import LLMRequest, LLMResponse, HealthStatus, ProviderCapabilities, StreamChunk
from ..exceptions import ProviderTimeoutError, ProviderUnavailableError
from ..config.schema import ProviderConfig

class OllamaProvider(LLMProvider):
    capabilities = ProviderCapabilities(
        chat=True, embeddings=True, streaming=True,
        json_mode=True, vision=False, tools=False,
    )

    def __init__(self, config: ProviderConfig):
        self.config = config
        self.base_url = config.base_url or "http://localhost:11434"
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(config.timeout_s)
        )

    def _handle_error(self, exc: Exception) -> None:
        if isinstance(exc, httpx.TimeoutException):
            raise ProviderTimeoutError(message=str(exc), provider="ollama") from exc
        if isinstance(exc, httpx.HTTPStatusError):
            if exc.response.status_code >= 500:
                raise ProviderUnavailableError(message=str(exc), provider="ollama") from exc
        raise ProviderUnavailableError(message=str(exc), provider="ollama") from exc

    def _build_options(self, request: LLMRequest) -> dict:
        options = {
            "temperature": request.temperature,
            "num_predict": request.max_tokens,
        }
        if self.config.num_ctx:
            options["num_ctx"] = self.config.num_ctx
        return options

    async def chat(self, request: LLMRequest) -> LLMResponse:
        payload = {
            "model": request.model,
            "messages": [m.dict() for m in request.messages],
            "stream": False,
            "options": self._build_options(request)
        }
        if request.json_schema:
            payload["format"] = "json"
        if self.config.keep_alive:
            payload["keep_alive"] = self.config.keep_alive

        start_time = time.time()
        try:
            response = await self.client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
            latency = int((time.time() - start_time) * 1000)
            
            return LLMResponse(
                text=data.get("message", {}).get("content", ""),
                provider="ollama",
                model=request.model or "unknown",
                latency_ms=latency,
                tokens_prompt=data.get("prompt_eval_count", 0),
                tokens_completion=data.get("eval_count", 0),
                total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                finish_reason="stop" if data.get("done") else "unknown",
                cached=False,
                raw=data
            )
        except Exception as e:
            self._handle_error(e)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        payload = {
            "model": request.model,
            "prompt": "\n".join([m.content for m in request.messages]),
            "stream": False,
            "options": self._build_options(request)
        }
        if request.json_schema:
            payload["format"] = "json"
        if self.config.keep_alive:
            payload["keep_alive"] = self.config.keep_alive

        start_time = time.time()
        try:
            response = await self.client.post("/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
            latency = int((time.time() - start_time) * 1000)
            
            return LLMResponse(
                text=data.get("response", ""),
                provider="ollama",
                model=request.model or "unknown",
                latency_ms=latency,
                tokens_prompt=data.get("prompt_eval_count", 0),
                tokens_completion=data.get("eval_count", 0),
                total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                finish_reason="stop" if data.get("done") else "unknown",
                cached=False,
                raw=data
            )
        except Exception as e:
            self._handle_error(e)

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        payload = {
            "model": request.model,
            "messages": [m.dict() for m in request.messages],
            "stream": True,
            "options": self._build_options(request)
        }
        if self.config.keep_alive:
            payload["keep_alive"] = self.config.keep_alive

        try:
            async with self.client.stream("POST", "/api/chat", json=payload) as response:
                response.raise_for_status()
                async for chunk in response.aiter_lines():
                    if chunk:
                        try:
                            data = json.loads(chunk)
                            yield StreamChunk(
                                text=data.get("message", {}).get("content", ""),
                                finish_reason="stop" if data.get("done") else None
                            )
                        except json.JSONDecodeError:
                            pass
        except Exception as e:
            self._handle_error(e)

    async def embed(self, texts: List[str]) -> List[List[float]]:
        embeddings = []
        try:
            for text in texts:
                payload = {
                    "model": "nomic-embed-text",
                    "prompt": text
                }
                if self.config.keep_alive:
                    payload["keep_alive"] = self.config.keep_alive
                response = await self.client.post("/api/embeddings", json=payload)
                response.raise_for_status()
                data = response.json()
                embeddings.append(data.get("embedding", []))
            return embeddings
        except Exception as e:
            self._handle_error(e)

    async def health_check(self) -> HealthStatus:
        try:
            response = await self.client.get("/api/tags")
            response.raise_for_status()
            return HealthStatus(is_healthy=True, details="Ollama is healthy")
        except Exception as e:
            return HealthStatus(is_healthy=False, details=str(e))
