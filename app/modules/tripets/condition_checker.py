from .models import ExtractedFact

def needs_event_hub(fact: ExtractedFact) -> bool:
    """
    Returns True if this fact should be modeled as an event-hub node
    rather than a single Neo4j relationship.
    """
    if len(set([p.entity for p in fact.participants])) >= 3:
        return True
    if len(fact.attributes) >= 1:
        return True
    if fact.mode_hint == "event":
        return True
    return False
