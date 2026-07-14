from abc import ABC, abstractmethod
from typing import AsyncIterator, List
from .types import LLMRequest, LLMResponse, StreamChunk, HealthStatus, ProviderCapabilities

class LLMProvider(ABC):
    """Abstract base class for all LLM providers."""
    
    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Returns the capabilities of this provider."""
        pass

    @abstractmethod
    async def chat(self, request: LLMRequest) -> LLMResponse:
        """Process a chat request."""
        pass

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Process a raw completion request (legacy)."""
        pass

    @abstractmethod
    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        """Stream a chat request chunk by chunk."""
        pass

    @abstractmethod
    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        pass

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Check if the provider is healthy and ready to serve requests."""
        pass

    async def __aenter__(self):
        # Allow implementations to return an active connection context if needed.
        # Can be overridden by subclasses.
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
