from abc import ABC, abstractmethod
from typing import List, Dict, Any, Type
import logging
from app.modules.rag.pipeline import RetrievedChunk
from app.modules.rag.orchestrator.query_analyzer import QueryIntent

logger = logging.getLogger(__name__)

class BaseEngine(ABC):
    """Base class for all retrieval engines."""
    
    @classmethod
    @abstractmethod
    def supports(cls, intent: QueryIntent) -> bool:
        pass
        
    @classmethod
    @abstractmethod
    def priority(cls) -> float:
        pass
        
    @classmethod
    @abstractmethod
    def cost(cls) -> float:
        pass
        
    @classmethod
    @abstractmethod
    def domain(cls) -> List[str]:
        pass
        
    @abstractmethod
    async def get_candidate_sections(self, task: Any, kb_ids: List[str]) -> List[Dict[str, Any]]:
        """Returns candidate sections matching the task."""
        pass
        
    @abstractmethod
    async def retrieve(self, task: Any, kb_ids: List[str]) -> List[RetrievedChunk]:
        pass

class CapabilityRegistry:
    """Registry to dynamically route tasks to capable engines."""
    
    _engines: Dict[str, Type[BaseEngine]] = {}
    
    @classmethod
    def register(cls, name: str):
        def decorator(engine_cls: Type[BaseEngine]):
            cls._engines[name] = engine_cls
            return engine_cls
        return decorator
        
    @classmethod
    def get_best_engine(cls, intent: QueryIntent, target_domain: str = None) -> str:
        """Finds the most cost-effective engine that supports the intent."""
        from app.modules.rag.engines.telemetry_optimizer import TelemetryOptimizer
        TelemetryOptimizer.load_stats()
        penalty = TelemetryOptimizer.get_penalty_multiplier(intent.name)
        
        capable_engines = []
        for name, engine_cls in cls._engines.items():
            if engine_cls.supports(intent):
                if target_domain and target_domain not in engine_cls.domain() and "*" not in engine_cls.domain():
                    continue
                capable_engines.append((name, engine_cls))
                
        if not capable_engines:
            return "vector" # fallback
            
        # Sort by (cost * penalty) ascending, then priority descending
        capable_engines.sort(key=lambda x: (x[1].cost() * penalty, -x[1].priority()))
        best_engine = capable_engines[0][0]
        logger.info(f"Registry selected {best_engine} for intent {intent.name} (Penalty: {penalty:.2f})")
        return best_engine
        
    @classmethod
    def get_engine_class(cls, name: str) -> Type[BaseEngine]:
        return cls._engines.get(name)
