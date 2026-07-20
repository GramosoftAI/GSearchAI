from typing import Optional
from ..types import LLMRequest, LLMResponse
from ..context import LLMExecutionContext
from ..exceptions import CapabilityNotSupportedError
from ..factory import LLMProviderFactory
from .registry import register_middleware

class CapabilityMiddleware:
    def __init__(self, factory: LLMProviderFactory, **kwargs):
        self.factory = factory
        
    async def before_request(self, request: LLMRequest, context: LLMExecutionContext) -> Optional[LLMResponse]:
        provider_name = context.route.provider
        provider = self.factory.get_provider(provider_name)
        caps = provider.capabilities
        
        if not caps.chat:
            raise CapabilityNotSupportedError("Provider does not support chat", provider=provider_name)
        if request.stream and not caps.streaming:
            raise CapabilityNotSupportedError("Provider does not support streaming", provider=provider_name)
        if request.json_schema and not caps.json_mode:
            raise CapabilityNotSupportedError("Provider does not support json_mode", provider=provider_name)
        if request.tools and not caps.tools:
            raise CapabilityNotSupportedError("Provider does not support tools", provider=provider_name)
            
        return None

class ConstraintMiddleware:
    def __init__(self, **kwargs):
        pass

    async def before_request(self, request: LLMRequest, context: LLMExecutionContext) -> Optional[LLMResponse]:
        step = context.route
        if step.constraints:
            if step.constraints.require_streaming is not None:
                if step.constraints.require_streaming and not request.stream:
                    raise CapabilityNotSupportedError(
                        "Route requires streaming, but request does not request it", 
                        provider=step.provider
                    )
            if step.constraints.require_json_mode is not None:
                if step.constraints.require_json_mode and not request.json_schema:
                    raise CapabilityNotSupportedError(
                        "Route requires json_mode, but request does not request it", 
                        provider=step.provider
                    )
        return None

register_middleware("capability", CapabilityMiddleware, 100, mw_types=["request"])
register_middleware("constraint", ConstraintMiddleware, 200, mw_types=["request"])
