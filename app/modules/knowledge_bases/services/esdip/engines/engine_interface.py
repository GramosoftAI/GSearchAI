from typing import Protocol
from ..domain.pipeline_context import PipelineContext

class Engine(Protocol):
    """Core extension point for the ESDIP framework."""
    def run(self, context: PipelineContext) -> PipelineContext:
        ...
