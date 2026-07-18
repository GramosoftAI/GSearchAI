import logging
from typing import List, Protocol
from ..domain.pipeline_context import PipelineContext

logger = logging.getLogger(__name__)

class PipelineEngine(Protocol):
    """Protocol that every Engine must implement."""
    def run(self, context: PipelineContext) -> PipelineContext:
        ...

class EngineRegistry:
    """Registry of sequentially executed engines."""
    def __init__(self):
        self._engines: List[PipelineEngine] = []
        
    def register(self, engine: PipelineEngine):
        self._engines.append(engine)
        
    def get_engines(self) -> List[PipelineEngine]:
        return self._engines

class PipelineManager:
    """Orchestrates the sequential execution of registered engines."""
    def __init__(self, registry: EngineRegistry):
        self.registry = registry
        
    def execute(self, context: PipelineContext) -> PipelineContext:
        engines = self.registry.get_engines()
        logger.info(f"Starting ESDIP Pipeline with {len(engines)} registered engines.")
        
        for engine in engines:
            engine_name = engine.__class__.__name__
            context.log(f"Executing {engine_name}...")
            try:
                context = engine.run(context)
            except Exception as e:
                context.add_error(f"{engine_name} failed: {e}")
                logger.exception(f"{engine_name} failed.")
                break  # Halt pipeline on engine failure
                
        context.log("Pipeline execution finished.")
        return context
