import sys
import os
import json
import asyncio
from typing import List

# Add the root project directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pydantic import ValidationError
from app.core.triplet_extractor import (
    ExtractedFact, 
    ExtractedParticipant, 
    ExtractedAttribute, 
    needs_event_hub,
    ExtractedFactShape
)

def test_needs_event_hub():
    # 2-party fact with no attributes -> False
    simple_fact = ExtractedFact(
        name="CEO_OF",
        subject="Demis Hassabis",
        object="DeepMind",
        participants=[
            ExtractedParticipant(entity="Demis Hassabis", role="subject"),
            ExtractedParticipant(entity="DeepMind", role="object")
        ]
    )
    assert not needs_event_hub(simple_fact), "Simple fact should not need event hub"
    
    # 2-party fact with an attribute -> True
    fact_with_attr = ExtractedFact(
        name="CEO_OF",
        subject="Demis Hassabis",
        object="DeepMind",
        participants=[
            ExtractedParticipant(entity="Demis Hassabis", role="subject"),
            ExtractedParticipant(entity="DeepMind", role="object")
        ],
        attributes=[ExtractedAttribute(attribute="since", value="2010")]
    )
    assert needs_event_hub(fact_with_attr), "Fact with attribute should trigger event hub"
    
    # 3+ party fact -> True
    complex_fact = ExtractedFact(
        name="Meeting",
        participants=[
            ExtractedParticipant(entity="Alice", role="participant"),
            ExtractedParticipant(entity="Bob", role="participant"),
            ExtractedParticipant(entity="Charlie", role="participant")
        ]
    )
    assert needs_event_hub(complex_fact), "3+ participants should trigger event hub"
    
    print("test_needs_event_hub passed!")

def test_shape_validation():
    # Valid fact
    valid_fact_dict = {
        "name": "ACQUIRED",
        "mode_hint": "event",
        "subject": "Google",
        "object": "DeepMind"
    }
    try:
        ExtractedFactShape(**valid_fact_dict)
        print("Valid shape passed validation")
    except ValidationError:
        assert False, "Valid shape failed validation"
        
    # Invalid fact (missing mode_hint, or wrong literal)
    invalid_fact_dict = {
        "name": "ACQUIRED",
        "mode_hint": "invalid_mode",
        "subject": "Google"
    }
    try:
        ExtractedFactShape(**invalid_fact_dict)
        assert False, "Invalid shape should have failed validation"
    except ValidationError as e:
        print("Invalid shape correctly rejected!")
        
    print("test_shape_validation passed!")

if __name__ == "__main__":
    test_needs_event_hub()
    test_shape_validation()
    print("All tests passed!")
