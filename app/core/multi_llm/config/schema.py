from typing import Dict, List, Optional
from pydantic import BaseModel, Field, root_validator, model_validator
from pydantic_settings import BaseSettings

class ProviderConfig(BaseModel):
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    timeout_s: int = 60
    max_retries: int = 3
    keep_alive: Optional[str] = None
    num_ctx: Optional[int] = None
    
    @model_validator(mode='before')
    @classmethod
    def check_auth_or_url(cls, values):
        if not values.get('base_url') and not values.get('api_key_env'):
            pass
        return values

class RouteConstraints(BaseModel):
    max_latency_ms: Optional[int] = None
    max_cost_per_1k_tokens: Optional[float] = None
    require_json_mode: Optional[bool] = None
    require_streaming: Optional[bool] = None

class RouteStep(BaseModel):
    provider: str
    model: str
    constraints: Optional[RouteConstraints] = None

class RouteConfig(BaseModel):
    primary: RouteStep
    fallback: List[RouteStep] = Field(default_factory=list)

class ProviderPricing(BaseModel):
    prompt: float
    completion: float

from pydantic import RootModel

class PricingConfig(RootModel):
    root: Dict[str, Dict[str, ProviderPricing]]
    
class TaskConfig(BaseModel):
    provider: str
    model: str
    temperature: float = 0.0
    timeout: int = 60
    retries: int = 2
    json_mode: bool = False
    fallback_model: Optional[str] = None
    fallback_provider: Optional[str] = None

class LLMConfigModel(BaseModel):
    routes: Dict[str, RouteConfig] = Field(default_factory=dict)
    providers: Dict[str, ProviderConfig] = Field(default_factory=dict)
    pipeline: List[str] = Field(default_factory=list)
    tasks: Dict[str, TaskConfig] = Field(default_factory=dict)
    
    @model_validator(mode='after')
    def validate_routing_targets(self):
        routes = self.routes
        providers = self.providers
        tasks = self.tasks
        
        for route_name, route in routes.items():
            if providers and route.primary.provider not in providers:
                raise ValueError(f"Primary provider '{route.primary.provider}' for route '{route_name}' not found in providers")
            for fallback_step in route.fallback:
                if providers and fallback_step.provider not in providers:
                    raise ValueError(f"Fallback provider '{fallback_step.provider}' for route '{route_name}' not found in providers")
                    
        for task_name, task in tasks.items():
            if providers and task.provider not in providers:
                raise ValueError(f"Provider '{task.provider}' for task '{task_name}' not found in providers")
            if providers and task.fallback_provider and task.fallback_provider not in providers:
                raise ValueError(f"Fallback provider '{task.fallback_provider}' for task '{task_name}' not found in providers")
                    
        return self
        
class LLMConfig(BaseSettings):
    llm: LLMConfigModel
    class Config:
        env_nested_delimiter = '__'
