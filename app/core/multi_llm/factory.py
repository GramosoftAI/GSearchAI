import logging
from typing import Dict, Type
from pydantic import BaseModel

from .base import LLMProvider
from .config.schema import LLMConfigModel
from .providers.deepinfra_provider import DeepInfraProvider

log = logging.getLogger(__name__)

class ProviderDescriptor(BaseModel):
    name: str
    provider_class: Type[LLMProvider]
    supports_stream: bool
    supports_embeddings: bool

PROVIDER_REGISTRY: Dict[str, ProviderDescriptor] = {
    "deepinfra": ProviderDescriptor(
        name="deepinfra", 
        provider_class=DeepInfraProvider,
        supports_stream=True, 
        supports_embeddings=True
    ),
    # Ollama providers: REMOVED — do not re-add
}

class LLMProviderFactory:
    def __init__(self, config: LLMConfigModel):
        self._config = config
        self._instances: Dict[str, LLMProvider] = {}

    def get_provider(self, name: str) -> LLMProvider:
        """Retrieves or creates a singleton instance of the requested provider."""
        if name not in self._instances:
            self._instances[name] = self._build(name)
        return self._instances[name]

    def _build(self, name: str) -> LLMProvider:
        if name not in PROVIDER_REGISTRY:
            raise ValueError(f"Provider '{name}' not found in PROVIDER_REGISTRY")
            
        if name not in self._config.providers:
            raise ValueError(f"Provider '{name}' configuration not found in config")

        descriptor = PROVIDER_REGISTRY[name]
        provider_config = self._config.providers[name]
        
        log.info(f"Instantiating provider '{name}' via {descriptor.provider_class.__name__}")
        return descriptor.provider_class(provider_config)

    def provider(self, name: str) -> LLMProvider:
        """Helper to get a provider for use in an async context manager."""
        return self.get_provider(name)
