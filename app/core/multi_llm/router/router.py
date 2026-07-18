import logging
import uuid
from typing import AsyncIterator, List, Callable

from ..config.schema import LLMConfigModel, RouteStep
from ..factory import LLMProviderFactory
from ..types import LLMRequest, LLMResponse, StreamChunk
from ..exceptions import ProviderTimeoutError, ProviderUnavailableError, AllProvidersFailedError, ProviderError
from ..middlewares import run_pipeline, MIDDLEWARE_REGISTRY
from ..context import LLMExecutionContext

# Ensure all middlewares are registered
from ..middlewares import constraint, resilience

log = logging.getLogger(__name__)

class LLMRouter:
    def __init__(self, config: LLMConfigModel, factory: LLMProviderFactory):
        self.routes = config.routes
        self.factory = factory
        
        self.request_mw = []
        self.response_mw = []
        
        # Keep track of priorities to catch collisions
        priorities = set()
        
        # Build middlewares from config
        for mw_name in config.pipeline:
            if mw_name not in MIDDLEWARE_REGISTRY:
                raise ValueError(f"Middleware '{mw_name}' not found in registry")
            descriptor = MIDDLEWARE_REGISTRY[mw_name]
            
            if descriptor.priority in priorities:
                log.warning(f"Priority collision detected for priority {descriptor.priority} in middleware {mw_name}")
            priorities.add(descriptor.priority)
            
            mw_instance = descriptor.middleware_class(factory=self.factory)
            
            if "request" in descriptor.mw_types:
                self.request_mw.append((descriptor.priority, mw_instance))
            if "response" in descriptor.mw_types:
                self.response_mw.append((descriptor.priority, mw_instance))
                
        # Sort by priority
        self.request_mw = [mw for _, mw in sorted(self.request_mw, key=lambda x: x[0])]
        self.response_mw = [mw for _, mw in sorted(self.response_mw, key=lambda x: x[0])]
        
        # Startup validation: route constraints vs provider capabilities
        self._validate_routes()

    def _validate_routes(self):
        for route_name, route in self.routes.items():
            for step in [route.primary] + route.fallback:
                if step.provider not in self.factory._config.providers:
                    raise ValueError(f"Provider {step.provider} in route {route_name} not configured")
                    
                # We can validate constraint vs capability here if needed
                provider = self.factory.get_provider(step.provider)
                caps = provider.capabilities
                if step.constraints:
                    if step.constraints.require_json_mode and not caps.json_mode:
                        raise ValueError(f"Route {route_name} requires json_mode but {step.provider} lacks it")
                    if step.constraints.require_streaming and not caps.streaming:
                        raise ValueError(f"Route {route_name} requires streaming but {step.provider} lacks it")

    async def _call_provider(self, request: LLMRequest, context: LLMExecutionContext) -> LLMResponse:
        """The final step in the middleware chain: actually calling the provider."""
        async with self.factory.provider(context.route.provider) as provider:
            request.model = context.route.model
            return await provider.chat(request)

    async def chat(self, task_type: str, request: LLMRequest) -> LLMResponse:
        route = self.routes.get(task_type, self.routes.get("default"))
        if not route:
            raise ValueError(f"No routing configured for task '{task_type}' and no default provided.")
            
        steps = [route.primary] + route.fallback
        last_err = None
        
        req_id = uuid.uuid4()
        
        for idx, step in enumerate(steps):
            context = LLMExecutionContext(
                request_id=req_id,
                tenant_id="default",
                session_id="default",
                task_type=task_type,
                route=step,
                route_attempt=idx + 1,
                fallback_depth=idx
            )
            
            try:
                request.task_type = task_type
                response = await run_pipeline(
                    request, context, 
                    self.request_mw, self.response_mw, 
                    self._call_provider
                )
                return response
            except ProviderError as e:
                last_err = e
                log.debug(f"Step {step.provider}/{step.model} failed/skipped for {task_type}: {e}")
                continue
                
        raise AllProvidersFailedError(task_type, steps, last_err)
