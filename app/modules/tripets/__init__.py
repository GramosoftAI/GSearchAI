from .models import (
    ExtractedFact, 
    ExtractedTriplet, 
    ExtractedEvent, 
    ExtractedParticipant, 
    ExtractedAttribute, 
    TripletExtractionResult,
    ExtractedParticipantShape,
    ExtractedAttributeShape,
    ExtractedFactShape,
    CANONICAL_RELATIONS,
    create_uri
)
from .prompt import TRIPLET_EXTRACTION_PROMPT
from .extractor import TripletExtractor
from .retriever import TripletRetriever
from .writer import TripletGraphWriter

# Re-exports from the new RDF stack (app.rdf)
from app.rdf import (
    RDFPipeline,
    PipelineResult,
    RDFTriple,
    RDFLayer,
    Namespace,
    RDFSLayer,
    OWLLayer,
    SHACLLayer,
    RDFNeo4jWriter,
)
# Backward-compatible alias for condition_checker.needs_event_hub
from app.rdf.owl_layer import OWLLayer as _OWLLayer
def needs_event_hub(fact):
    """Backward-compatible wrapper around OWLLayer.needs_event_hub."""
    from app.rdf.namespace import RDFLayer as _RDFLayer
    _rdf = _RDFLayer("_compat")
    triples = _rdf.to_triples([fact], "")
    if triples:
        return _OWLLayer.needs_event_hub(triples[0])
    return False

__all__ = [
    # Original tripets exports
    "ExtractedFact",
    "ExtractedTriplet",
    "ExtractedEvent",
    "ExtractedParticipant",
    "ExtractedAttribute",
    "TripletExtractionResult",
    "ExtractedParticipantShape",
    "ExtractedAttributeShape",
    "ExtractedFactShape",
    "CANONICAL_RELATIONS",
    "create_uri",
    "needs_event_hub",
    "TRIPLET_EXTRACTION_PROMPT",
    "TripletExtractor",
    "TripletRetriever",
    "TripletGraphWriter",
    # RDF stack re-exports
    "RDFPipeline",
    "PipelineResult",
    "RDFTriple",
    "RDFLayer",
    "Namespace",
    "RDFSLayer",
    "OWLLayer",
    "SHACLLayer",
    "RDFNeo4jWriter",
]

