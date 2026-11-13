import asyncio
import json

from app.core.triplet_extractor import TripletExtractor, needs_event_hub

async def main():
    extractor = TripletExtractor()
    
    text = "Google purchased DeepMind in 2014 for 500 million dollars. Demis Hassabis is the CEO of DeepMind."
    print(f"Testing text:\n{text}\n")
    print("-" * 50)
    
    # We use extract_from_chunk directly to hit the LLM
    result = await extractor.extract_from_chunk("test_chunk_001", text)
    
    if not result.success:
        print(f"Extraction failed: {result.error}")
        return
        
    if not result.facts:
        print("No facts extracted.")
        return
        
    print(f"Extracted {len(result.facts)} facts:\n")
    
    for i, fact in enumerate(result.facts):
        print(f"Fact {i+1}:")
        print(f"  Name: {fact.name}")
        print(f"  Mode Hint: {fact.mode_hint}")
        if fact.subject and fact.object:
            print(f"  Subject: {fact.subject} ({fact.subject_type})")
            print(f"  Object: {fact.object} ({fact.object_type})")
            
        if fact.participants:
            print("  Participants:")
            for p in fact.participants:
                print(f"    - {p.entity} ({p.role}, {p.entity_type})")
                
        if fact.attributes:
            print("  Attributes:")
            for a in fact.attributes:
                print(f"    - {a.attribute}: {a.value} ({a.entity_type})")
                
        # The routing decision
        routing = "EVENT HUB" if needs_event_hub(fact) else "SIMPLE RELATIONSHIP"
        print(f"  --> Routing Decision: {routing}")
        print("-" * 50)

if __name__ == "__main__":
    asyncio.run(main())
