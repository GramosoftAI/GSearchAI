from typing import Type, Dict, Union, List, Any
from pydantic import BaseModel, Field

from .base import RequestMiddleware, ResponseMiddleware

class MiddlewareDescriptor(BaseModel):
    name: str
    middleware_class: Any
    priority: int
    mw_types: List[str] = Field(description="List containing 'request' and/or 'response'")

MIDDLEWARE_REGISTRY: Dict[str, MiddlewareDescriptor] = {}

def register_middleware(name: str, middleware_class: Type[Union[RequestMiddleware, ResponseMiddleware]], priority: int, mw_types: List[str]):
    for t in mw_types:
        if t not in ("request", "response"):
            raise ValueError(f"mw_types must contain 'request' or 'response', got '{t}'")
    MIDDLEWARE_REGISTRY[name] = MiddlewareDescriptor(
        name=name,
        middleware_class=middleware_class,
        priority=priority,
        mw_types=mw_types
    )
