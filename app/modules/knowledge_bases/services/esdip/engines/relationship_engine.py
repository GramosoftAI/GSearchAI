from typing import Protocol, List
from ..domain.pipeline_context import PipelineContext
from ..domain.business_object import BusinessObject

class RelationshipDetector(Protocol):
    def detect(self, obj: BusinessObject, context: PipelineContext):
        ...

class PrimaryKeyDetector(RelationshipDetector):
    def detect(self, obj: BusinessObject, context: PipelineContext):
        pass

class ForeignKeyDetector(RelationshipDetector):
    def detect(self, obj: BusinessObject, context: PipelineContext):
        from ..domain.relationship import Relationship, Evidence
        from ..domain.confidence import ConfidenceResult
        
        for key, val in obj.attributes.items():
            if key.endswith("_id") and val is not None:
                target_type = key[:-3].upper()
                
                evidence = Evidence(
                    source_column=key,
                    target_column="id",
                    match_type="foreign_key_heuristic",
                    description=f"Column '{key}' suggests a link to {target_type}"
                )
                
                rel = Relationship(
                    source_id=obj.id,
                    source_type=obj.entity_type,
                    target_id=f"{target_type}_{val}",
                    target_type=target_type,
                    predicate=f"HAS_{target_type}",
                    evidence=[evidence],
                    confidence=ConfidenceResult(score=0.8, reason="Standard naming convention match")
                )
                obj.relationships.append(rel)

class RelationshipEngine:
    """A plugin executor that delegates to registered RelationshipDetectors."""
    def __init__(self):
        self.detectors: List[RelationshipDetector] = [
            PrimaryKeyDetector(),
            ForeignKeyDetector()
        ]
        
    def run(self, context: PipelineContext) -> PipelineContext:
        for obj in context.business_object_store.get_all():
            for detector in self.detectors:
                detector.detect(obj, context)
        return context
