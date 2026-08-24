# ============================================================================
# REFACTORED: All logic has been moved to app/modules/tripets/
# We keep this file to redirect imports and maintain backward compatibility.
# ============================================================================

from app.modules.tripets import (
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
    create_uri,
    needs_event_hub,
    TRIPLET_EXTRACTION_PROMPT,
    TripletExtractor,
    TripletRetriever,
    TripletGraphWriter
)

# ============================================================================
# ORIGINAL CODE (COMMENTED OUT)
# ============================================================================
# """
# Triplet-Based Knowledge Graph Construction Engine
#
# PHASE 4A FEATURE: Extracts (Subject, Predicate, Object) triplets from text chunks
# using LLM, then creates typed relationship edges in Neo4j graph.
#
# INTEGRATION STRATEGY (ZERO BREAKING CHANGES):
#     - Runs as a POST-INGESTION hook AFTER existing pipeline succeeds
#     - Feature-flagged via settings.use_triplet_extraction (OFF by default)
#     - Creates NEW node/edge types (Triplet, RELATES_TO)  never modifies existing
#     - Existing MENTIONS, SIMILAR, NEXT edges remain untouched
#     - If triplet extraction fails, ingestion still succeeds (graceful degradation)
#
# ARCHITECTURE:
#     Chunk Text  LLM Extract Triplets  (Subject, Predicate, Object)
#                                         MERGE Entity nodes (deduplicated)
#                                         CREATE typed RELATES_TO edges
#                                         CREATE Triplet nodes with embedded text
#                                         Embed triplet strings for semantic search
#
# GRAPH SCHEMA (additive):
#     (:Entity {text, type, tenant_id})
#     (:Triplet {text, subject, predicate, object, chunk_id, tenant_id, embedding})
#     (Entity)-[:RELATES_TO {predicate, chunk_id, confidence}]->(Entity)
#     (Chunk)-[:HAS_TRIPLET]->(Triplet)
# """
#
# import logging
# import json
# import re
# import uuid
# from typing import List, Dict, Optional, Literal
# from dataclasses import dataclass, field
# import time
# import json
# from pydantic import BaseModel, ValidationError
#
# from .config import get_settings
# from .embeddings import EmbeddingGenerator
# import urllib.parse
#
# # ============================================================================
# # --- REFACTORED: IMPORT MODULES ---
# from app.modules.tripets import (
#     ExtractedFact, ExtractedTriplet, ExtractedEvent,
#     ExtractedParticipant, ExtractedAttribute, TripletExtractionResult,
#     ExtractedParticipantShape, ExtractedAttributeShape, ExtractedFactShape,
#     CANONICAL_RELATIONS, create_uri, needs_event_hub,
#     StandardTripletWriter, EventHubWriter, TRIPLET_EXTRACTION_PROMPT
# )
# # RDF SEMANTIC ONTOLOGY MAPPER
# # ============================================================================
# # CANONICAL_RELATIONS = {
# #     "issued": "ISSUED_BY",
# #     "created_bill": "ISSUED_BY",
# #     "generated_invoice": "ISSUED_BY",
# #     "purchased": "PURCHASED",
# #     "bought": "PURCHASED",
# #     "ordered": "PURCHASED",
# #     "supplied_by": "SUPPLIED_BY",
# #     "provided_by": "SUPPLIED_BY",
# #     "contains": "CONTAINS_PRODUCT",
# #     "includes": "CONTAINS_PRODUCT",
# #     "belongs_to": "BELONGS_TO",
# #     "located_in": "LOCATED_IN",
# #     "has_amount": "HAS_AMOUNT",
# #     "has_date": "HAS_DATE",
# #     "references": "REFERENCES",
# #     "derived_from": "DERIVED_FROM"
# # }
# # 
# # def create_uri(entity_type: str, text: str) -> str:
# #     """Generate globally unique RDF-compliant URI for an entity."""
# #     clean_type = urllib.parse.quote(entity_type.lower().strip())
# #     clean_text = urllib.parse.quote(text.lower().strip().replace(' ', '_'))
# #     return f"https://grag.ai/kg/{clean_type}/{clean_text}"
# # 
# # logger = logging.getLogger(__name__)
# # settings = get_settings()
# # 
# # 
# # # ============================================================================
# # # DATA MODELS & SHACL-LITE VALIDATION
# # # ============================================================================
# # 
# # @dataclass
# # class ExtractedParticipant:
# #     entity: str
# #     role: str
# #     entity_type: str = "CONCEPT"
# # 
# # @dataclass
# # class ExtractedAttribute:
# #     attribute: str
# #     value: str
# #     entity_type: str = "CONCEPT"
# # 
# # @dataclass
# # class ExtractedFact:
# #     """Unified representation of a fact that can be a simple relation or an event hub."""
# #     name: str  # The event name or the predicate
# #     subject: Optional[str] = None
# #     object: Optional[str] = None
# #     subject_type: str = "CONCEPT"
# #     object_type: str = "CONCEPT"
# #     mode_hint: str = "relationship" # 'relationship' or 'event'
# #     event_type: str = "EVENT"
# #     participants: List[ExtractedParticipant] = field(default_factory=list)
# #     attributes: List[ExtractedAttribute] = field(default_factory=list)
# #     confidence: float = 1.0
# #     evidence: str = None
# #     
# #     @property
# #     def text(self) -> str:
# #         if self.mode_hint == "relationship" and self.subject and self.object:
# #             return f"{self.subject}  {self.name}  {self.object}"
# #         return f"{self.name} (Event)"
# # 
# #     def normalize(self) -> "ExtractedFact":
# #         """Normalize fields for consistency."""
# #         raw_name = self.name.strip().lower().replace(" ", "_")
# #         canonical_name = CANONICAL_RELATIONS.get(raw_name, raw_name.upper())
# #         self.name = canonical_name
# #         
# #         if self.subject:
# #             self.subject = self.subject.strip().lower()
# #             self.subject_type = self.subject_type.upper().strip()
# #         if self.object:
# #             self.object = self.object.strip().lower()
# #             self.object_type = self.object_type.upper().strip()
# #             
# #         return self
# # 
# # 
# # class TripletExtractionResult:
# #     """Result of triplet extraction for a single chunk."""
# #     def __init__(
# #         self,
# #         chunk_id: str,
# #         facts: List[ExtractedFact] = None,
# #         triplets: List[ExtractedFact] = None,
# #         events: List[ExtractedFact] = None,
# #         error: Optional[str] = None
# #     ):
# #         self.chunk_id = chunk_id
# #         self.error = error
# #         
# #         if facts is not None:
# #             self.facts = facts
# #         else:
# #             self.facts = []
# #             
# #         if triplets is not None:
# #             for t in triplets:
# #                 t.mode_hint = "relationship"
# #                 self.facts.append(t)
# #                 
# #         if events is not None:
# #             for ev in events:
# #                 ev.mode_hint = "event"
# #                 self.facts.append(ev)
# # 
# #     @property
# #     def success(self) -> bool:
# #         return self.error is None
# # 
# #     @property
# #     def triplets(self) -> List["ExtractedTriplet"]:
# #         return [
# #             ExtractedTriplet(
# #                 subject=f.subject,
# #                 predicate=f.name,
# #                 object=f.object,
# #                 subject_type=f.subject_type,
# #                 object_type=f.object_type,
# #                 confidence=f.confidence,
# #                 evidence=f.evidence
# #             )
# #             for f in self.facts if f.mode_hint == "relationship"
# #         ]
# # 
# #     @property
# #     def events(self) -> List["ExtractedEvent"]:
# #         return [
# #             ExtractedEvent(
# #                 name=f.name,
# #                 event_type=f.event_type,
# #                 participants=f.participants,
# #                 attributes=f.attributes
# #             )
# #             for f in self.facts if f.mode_hint == "event"
# #         ]
# # 
# # 
# # class ExtractedTriplet(ExtractedFact):
# #     def __init__(
# #         self,
# #         subject: str,
# #         predicate: str,
# #         object: str,
# #         subject_type: str = "CONCEPT",
# #         object_type: str = "CONCEPT",
# #         confidence: float = 1.0,
# #         evidence: str = None
# #     ):
# #         self.subject = subject
# #         self.name = predicate
# #         self.object = object
# #         self.subject_type = subject_type
# #         self.object_type = object_type
# #         self.mode_hint = "relationship"
# #         self.confidence = confidence
# #         self.evidence = evidence
# #         self.participants = []
# #         self.attributes = []
# # 
# #     @property
# #     def predicate(self) -> str:
# #         return self.name
# # 
# #     @predicate.setter
# #     def predicate(self, value: str):
# #         self.name = value
# # 
# # 
# # class ExtractedEvent(ExtractedFact):
# #     def __init__(
# #         self,
# #         name: str,
# #         event_type: str = "EVENT",
# #         participants: List[ExtractedParticipant] = None,
# #         attributes: List[ExtractedAttribute] = None
# #     ):
# #         self.name = name
# #         self.event_type = event_type
# #         self.participants = participants or []
# #         self.attributes = attributes or []
# #         self.mode_hint = "event"
# #         self.subject = None
# #         self.object = None
# #         self.subject_type = "CONCEPT"
# #         self.object_type = "CONCEPT"
# # 
# # # --- SHACL-LITE PYDANTIC SHAPES ---
# # class ExtractedParticipantShape(BaseModel):
# #     entity: str
# #     role: str
# #     entity_type: str
# # 
# # class ExtractedAttributeShape(BaseModel):
# #     attribute: str
# #     value: str
# #     entity_type: str
# # 
# # class ExtractedFactShape(BaseModel):
# #     name: str
# #     mode_hint: Literal["relationship", "event"]
# #     subject: Optional[str] = None
# #     object: Optional[str] = None
# #     participants: List[ExtractedParticipantShape] = []
# #     attributes: List[ExtractedAttributeShape] = []
# # 
# # def needs_event_hub(fact: ExtractedFact) -> bool:
# #     """
# #     Returns True if this fact should be modeled as an event-hub node
# #     rather than a single Neo4j relationship.
# #     """
# #     if len(set([p.entity for p in fact.participants])) >= 3:
# #         return True
# #     if len(fact.attributes) >= 1:
# #         return True
# #     if fact.mode_hint == "event":
# #         return True
# #     return False
# # 
#
#
# # ============================================================================
# # TRIPLET EXTRACTOR (LLM-BASED)
# # ============================================================================
#
# # # Extraction prompt  deterministic, structured output
# # # NOTE: All literal {{ }} are escaped for Python .format()  only {text} is a placeholder
# # TRIPLET_EXTRACTION_PROMPT = """Extract knowledge events and facts from the following text.
# # For each fact, output it in a structured format. 
# # If it is a simple relationship between two entities, provide the subject, predicate, and object.
# # If it is a complex fact or event (e.g., acquisitions, transactions, employment, launches, agreements), you can specify multiple participants and attributes.
# # Provide a `mode_hint` indicating if you believe it should be a "relationship" or an "event".
# # 
# # Return ONLY valid JSON in this exact format:
# # {{
# #     "facts": [
# #         {{
# #             "mode_hint": "event",
# #             "name": "Google acquisition of DeepMind",
# #             "event_type": "EVENT",
# #             "participants": [
# #                 {{
# #                     "entity": "Google",
# #                     "role": "buyer",
# #                     "entity_type": "ORGANIZATION"
# #                 }},
# #                 {{
# #                     "entity": "DeepMind",
# #                     "role": "acquired_company",
# #                     "entity_type": "ORGANIZATION"
# #                 }}
# #             ],
# #             "attributes": [
# #                 {{
# #                     "attribute": "date",
# #                     "value": "2014",
# #                     "entity_type": "NUMERIC"
# #                 }},
# #                 {{
# #                     "attribute": "amount",
# #                     "value": "500 million dollars",
# #                     "entity_type": "NUMERIC"
# #                 }}
# #             ]
# #         }},
# #         {{
# #             "mode_hint": "relationship",
# #             "name": "CEO_OF",
# #             "subject": "Demis Hassabis",
# #             "subject_type": "PERSON",
# #             "object": "DeepMind",
# #             "object_type": "ORGANIZATION"
# #         }}
# #     ]
# # }}
# # 
# # Valid entity types: PERSON, ORGANIZATION, LOCATION, CONCEPT, EVENT, PRODUCT, TECHNOLOGY, NUMERIC, STRUCTURED_IDENTIFIER
# # 
# # TEXT:
# # {text}
# # 
# # JSON:"""
#
#
# class TripletExtractor:
#     """
#     Extract structured knowledge triplets from text using LLM.
#
#     USAGE:
#         extractor = TripletExtractor()
#         result = await extractor.extract_from_chunk(chunk_id, chunk_text)
#         # result.triplets = [ExtractedTriplet(...), ...]
#
#     SAFETY:
#         - Temperature 0.0 for deterministic extraction
#         - Structured JSON output with validation
#         - Max 10 triplets per chunk (prevent runaway)
#         - Graceful fallback on LLM failure
#     """
#
#     # Track initialization logging
#     _init_logged = False
#
#     def __init__(self, tenant_id: Optional[str] = None):
#         """Initialize with LLM client (lazy import to avoid circular deps)."""
#         from .llm.deepinfra_llm import DeepInfraLLMClient
#         self.llm_client = DeepInfraLLMClient()
#         self.tenant_id = tenant_id
#
#     async def extract_from_chunk(
#         self,
#         chunk_id: str,
#         chunk_text: str,
#         max_triplets: int = 10,
#     ) -> TripletExtractionResult:
#         """
#         Extract triplets from a single chunk.
#
#         Args:
#             chunk_id: Chunk UUID
#             chunk_text: Raw text content
#             max_triplets: Maximum triplets to extract
#
#         Returns:
#             TripletExtractionResult with extracted triplets
#         """
#         if not chunk_text or len(chunk_text.strip()) < 20:
#             return TripletExtractionResult(chunk_id=chunk_id, triplets=[])
#
#         if not TripletExtractor._init_logged:
#             logger.info("Triplet Extraction Engine initialized (LLM-based)")
#             TripletExtractor._init_logged = True
#
#         try:
#             # --- ONTOLOGY GROUNDING INJECTION ---
#             valid_types_str = "PERSON, ORGANIZATION, LOCATION, CONCEPT, EVENT, PRODUCT, TECHNOLOGY, NUMERIC, STRUCTURED_IDENTIFIER"
#             valid_relations_str = ""
#             rules_text = ""
#             if self.tenant_id:
#                 from ..modules.ontology.service import OntologyService
#                 ont_svc = OntologyService(self.tenant_id)
#                 ont_data = await ont_svc.get_ontology()
#                 if ont_data.get("classes"):
#                     valid_types_str = ", ".join([c["name"] for c in ont_data["classes"]])
#                 if ont_data.get("relations"):
#                     # Avoid duplicate empty objects if no relations
#                     rels = [r["name"] for r in ont_data["relations"] if r.get("name")]
#                     if rels:
#                         valid_relations_str = "\nValid relationship predicates: " + ", ".join(rels)
#                 if ont_data.get("rules"):
#                     rules_list = [f"({r['source_class']} -> {r['relation']} -> {r['target_class']})" for r in ont_data["rules"] if r.get("source_class")]
#                     if rules_list:
#                         rules_text = "\nALLOWED RELATIONSHIP RULES (STRICT SCHEMA):\n" + "\n".join(rules_list) + "\nYou MUST ONLY use these exact relationships if they apply."
#
#             replacement = f"Valid entity types: {valid_types_str}{valid_relations_str}{rules_text}"
#
#             prompt = TRIPLET_EXTRACTION_PROMPT.replace(
#                 "Valid entity types: PERSON, ORGANIZATION, LOCATION, CONCEPT, EVENT, PRODUCT, TECHNOLOGY, NUMERIC, STRUCTURED_IDENTIFIER",
#                 replacement
#             ).format(text=chunk_text[:2000])
#
#             logger.info(f"Calling LLM for triplet extraction (chunk {chunk_id[:8]}, text length: {len(chunk_text)})")
#
#             response_text = await self.llm_client.generate(
#                 prompt=prompt,
#                 system_prompt="You are a strict extraction system. Return ONLY valid JSON. DO NOT use <think> tags or explanations.",
#                 temperature=0.1,
#                 max_tokens=1024,
#             )
#
#             logger.info(f"LLM response received ({len(response_text)} chars): {response_text[:300]}...")
#
#             facts = self._parse_triplets(response_text, max_triplets)
#
#             logger.info(
#                 f"Extracted {len(facts)} facts from chunk {chunk_id[:8]}"
#             )
#             return TripletExtractionResult(chunk_id=chunk_id, facts=facts)
#
#         except Exception as e:
#             logger.error(f"Triplet extraction failed for chunk {chunk_id[:8]}: {e}", exc_info=True)
#             return TripletExtractionResult(chunk_id=chunk_id, error=str(e))
#
#     async def extract_from_chunks_batch(
#         self,
#         chunks: List[Dict[str, str]],
#     ) -> List[TripletExtractionResult]:
#         """
#         Extract triplets from multiple chunks in parallel.
#
#         Args:
#             chunks: List of {"chunk_id": str, "text": str}
#
#         Returns:
#             List of TripletExtractionResult
#         """
#         import asyncio
#
#         logger.info(f" Batch extracting triplets from {len(chunks)} chunks in parallel...")
#
#         # Create tasks for all chunks
#
#         # --- DYNAMIC SCHEMA DISCOVERY (Ontology-Aware Ingestion) ---
#         if self.tenant_id and chunks:
#             try:
#                 from .schema_detector import SchemaDetector
#                 from ..modules.ontology.service import OntologyService
#
#                 sample_text = "\n".join([c.get("text", "") for c in chunks[:3]])
#                 if sample_text:
#                     detector = SchemaDetector()
#                     schema = await detector.discover_schema(sample_text)
#
#                     if schema.get("classes") or schema.get("relations"):
#                         ont_svc = OntologyService(self.tenant_id)
#                         await ont_svc.auto_register_schema(schema)
#             except Exception as e:
#                 logger.warning(f"Dynamic schema detection failed: {e}")
#
#         # --- TRIPLET EXTRACTION ---
#         tasks = [
#             self.extract_from_chunk(
#                 chunk_id=chunk["chunk_id"],
#                 chunk_text=chunk["text"],
#             )
#             for chunk in chunks
#         ]
#
#         # Execute all tasks in parallel
#         results = await asyncio.gather(*tasks)
#
#         total_facts = sum(len(r.facts) for r in results)
#         failed = sum(1 for r in results if not r.success)
#         logger.info(
#             f" Batch extraction complete: {total_facts} facts "
#             f"from {len(chunks)} chunks ({failed} failures)"
#         )
#         return results
#
#     def _parse_triplets(
#         self,
#         response_text: str,
#         max_triplets: int,
#     ) -> List[ExtractedFact]:
#         """Parse LLM response into validated ExtractedFact objects."""
#         # Extract JSON from response (handle markdown code blocks)
#         json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
#         if not json_match:
#             logger.warning("No JSON found in triplet extraction response")
#             return []
#
#         try:
#             data = json.loads(json_match.group(0))
#         except json.JSONDecodeError as e:
#             logger.warning(f"Invalid JSON in triplet response: {e}")
#             return []
#
#         facts = []
#
#         # Parse Facts
#         raw_facts = data.get("facts", [])
#         if isinstance(raw_facts, list) and raw_facts:
#             for raw_fact in raw_facts:
#                 if not isinstance(raw_fact, dict):
#                     continue
#
#                 name = raw_fact.get("name", "").strip()
#                 if not name:
#                     continue
#
#                 mode_hint = raw_fact.get("mode_hint", "relationship").strip().lower()
#                 event_type = raw_fact.get("event_type", "EVENT").strip().upper()
#                 subject = raw_fact.get("subject")
#                 if subject: subject = subject.strip()
#                 obj = raw_fact.get("object")
#                 if obj: obj = obj.strip()
#                 subject_type = raw_fact.get("subject_type", "CONCEPT").strip().upper()
#                 object_type = raw_fact.get("object_type", "CONCEPT").strip().upper()
#
#                 raw_participants = raw_fact.get("participants", [])
#                 raw_attributes = raw_fact.get("attributes", [])
#
#                 participants = []
#                 attributes = []
#
#                 for p in raw_participants:
#                     if not isinstance(p, dict): continue
#                     entity = p.get("entity", "").strip()
#                     role = p.get("role", "participant").strip().upper()
#                     ent_type = p.get("entity_type", "CONCEPT").strip().upper()
#                     if entity and len(entity) >= 2:
#                         participants.append(ExtractedParticipant(entity=entity.lower(), role=role, entity_type=ent_type))
#
#                 for a in raw_attributes:
#                     if not isinstance(a, dict): continue
#                     attr = a.get("attribute", "has_attribute").strip().upper().replace(" ", "_")
#                     val = a.get("value", "").strip()
#                     ent_type = a.get("entity_type", "CONCEPT").strip().upper()
#                     if val and len(val) >= 2:
#                         attributes.append(ExtractedAttribute(attribute=attr, value=val.lower(), entity_type=ent_type))
#
#                 fact = ExtractedFact(
#                     name=name,
#                     subject=subject,
#                     object=obj,
#                     subject_type=subject_type,
#                     object_type=object_type,
#                     mode_hint=mode_hint,
#                     event_type=event_type,
#                     participants=participants,
#                     attributes=attributes
#                 )
#                 facts.append(fact.normalize())
#
#         return facts[:max_triplets]
#
#
# # ============================================================================
# # GRAPH PERSISTENCE (Neo4j)
# # ============================================================================
#
# # class TripletGraphWriter:
# #     """
# #     Persist extracted triplets to Neo4j graph.
# # 
# #     CREATES (additive only  never modifies existing graph):
# #         1. MERGE Entity nodes (deduplicated by text+type+tenant)
# #         2. CREATE typed RELATES_TO edges between entities
# #         3. CREATE Triplet nodes with embedded text for semantic search
# #         4. CREATE Chunk-[:HAS_TRIPLET]->Triplet relationships
# # 
# #     MULTI-TENANCY:
# #         - All nodes/edges tagged with tenant_id
# #         - Uses same Neo4jRepository pattern as existing codebase
# #     """
# # 
# #     def __init__(self, tenant_id: str):
# #         from .neo4j_repository import Neo4jRepository
# #         from .neo4j_retry import retry_neo4j_operation
# # 
# #         self.tenant_id = tenant_id
# #         self.neo4j_repo = Neo4jRepository(tenant_id)
# #         self._retry = retry_neo4j_operation
# # 
# #     async def persist_triplets(
# #         self,
# #         extraction_results: List[TripletExtractionResult],
# #     ) -> Dict:
# #         """
# #         Persist all extracted triplets and events to Neo4j.
# # 
# #         FLOW:
# #         1. SHACL-lite Validation
# #         2. Routing based on `needs_event_hub`
# #         3. Collect all unique entities across all chunks/triplets/events
# #         4. Batch MERGE entity nodes as standard Entity nodes
# #         5. Batch CREATE relationship edges for triplets
# #         6. Batch CREATE triplet nodes with embeddings
# #         7. Batch CREATE EventHub nodes and their relations
# #         """
# #         all_triplets = []
# #         all_events = []
# #         
# #         start_time = time.perf_counter()
# # 
# #         # Validation & Routing
# #         for result in extraction_results:
# #             if not result.success: continue
# #             
# #             for fact in result.facts:
# #                 try:
# #                     ExtractedFactShape(**fact.__dict__)
# #                 except ValidationError as e:
# #                     logger.warning(f"Fact validation failed: {e}")
# #                     # Write to rejection sink
# #                     with open("logs/rejected_triplets.jsonl", "a", encoding="utf-8") as f:
# #                         f.write(json.dumps({"chunk_id": result.chunk_id, "tenant_id": self.tenant_id, "reason": str(e), "fact": fact.__dict__}) + "\n")
# #                     continue
# #                     
# #                 if needs_event_hub(fact):
# #                     all_events.append({
# #                         "chunk_id": result.chunk_id,
# #                         "event": fact,
# #                     })
# #                 else:
# #                     all_triplets.append({
# #                         "chunk_id": result.chunk_id,
# #                         "triplet": fact,
# #                     })
# # 
# #         if not all_triplets and not all_events:
# #             logger.info(" No facts to persist after validation")
# #             return {
# #                 "entities_created": 0,
# #                 "relationships_created": 0,
# #                 "triplets_created": 0,
# #                 "events_created": 0,
# #             }
# # 
# #         logger.info(f" Persisting {len(all_triplets)} relations and {len(all_events)} events to Neo4j...")
# # 
# #         # Step 1: ONTOLOGY GROUNDING (Coreference Resolution)
# #         from .ontology_resolver import OntologyResolver
# #         resolver = OntologyResolver(self.tenant_id)
# #         
# #         unique_entities_list = []
# #         seen = set()
# #         
# #         # Collect from triplets
# #         for item in all_triplets:
# #             t = item["triplet"]
# #             for text, type_ in [(t.subject, t.subject_type), (t.object, t.object_type)]:
# #                 k = f"{text}|{type_}"
# #                 if k not in seen and text:
# #                     seen.add(k)
# #                     unique_entities_list.append({"text": text, "type": type_})
# #                     
# #         # Collect from events
# #         for item in all_events:
# #             ev = item["event"]
# #             for p in ev.participants:
# #                 k = f"{p.entity}|{p.entity_type}"
# #                 if k not in seen:
# #                     seen.add(k)
# #                     unique_entities_list.append({"text": p.entity, "type": p.entity_type})
# #             for a in ev.attributes:
# #                 k = f"{a.value}|{a.entity_type}"
# #                 if k not in seen:
# #                     seen.add(k)
# #                     unique_entities_list.append({"text": a.value, "type": a.entity_type})
# #                     
# #         canonical_map = await resolver.resolve_entities(unique_entities_list)
# #         
# #         canonical_entities_to_merge = {}
# #         
# #         def add_entity_to_merge(text: str, type_: str):
# #             if not text: return text
# #             mapped = canonical_map.get(text)
# #             if mapped:
# #                 resolved_text = mapped["text"]
# #                 emb = mapped["embedding"]
# #             else:
# #                 resolved_text = text
# #                 emb = []
# #             
# #             key = f"{resolved_text}|{type_}"
# #             canonical_entities_to_merge[key] = {
# #                 "text": resolved_text,
# #                 "type": type_,
# #                 "embedding": emb,
# #                 "uri": create_uri(type_, resolved_text)
# #             }
# #             return resolved_text
# # 
# #         # Update triplets and collect entities
# #         for item in all_triplets:
# #             t = item["triplet"]
# #             t.subject = add_entity_to_merge(t.subject, t.subject_type)
# #             t.object = add_entity_to_merge(t.object, t.object_type)
# #             
# #         # Update events and collect entities
# #         for item in all_events:
# #             ev = item["event"]
# #             for p in ev.participants:
# #                 p.entity = add_entity_to_merge(p.entity, p.entity_type)
# #             for a in ev.attributes:
# #                 a.value = add_entity_to_merge(a.value, a.entity_type)
# # 
# #         # Step 1: MERGE Entity nodes (deduplicated + embeddings)
# #         entities_created = await self._merge_entities(list(canonical_entities_to_merge.values()))
# # 
# #         # Step 2: CREATE relationship edges
# #         relationships_created = await self._create_relationships(all_triplets)
# # 
# #         # Step 3: CREATE Triplet nodes with embeddings + link to chunks
# #         triplets_created = await self._create_triplet_nodes(all_triplets)
# # 
# #         # Step 4: CREATE EventHub nodes and relationships
# #         events_created = await self._create_events(all_events)
# # 
# #         elapsed = time.perf_counter() - start_time
# #         logger.info(
# #             f" Triplet & Event persistence complete in {elapsed:.2f}s: "
# #             f"{entities_created} entities, "
# #             f"{relationships_created} relationships, "
# #             f"{triplets_created} triplet nodes, "
# #             f"{events_created} event hubs"
# #         )
# #         return {
# #             "entities_created": entities_created,
# #             "relationships_created": relationships_created,
# #             "triplets_created": triplets_created,
# #             "events_created": events_created,
# #         }
# # 
# #     async def _merge_entities(self, entity_list: List[Dict]) -> int:
# #         """MERGE unique entity nodes (prevents duplicates)."""
# #         if not entity_list:
# #             return 0
# # 
# #         query = """
# #         WITH $entities AS entity_list
# #         UNWIND entity_list AS e
# #         MERGE (ent:Entity {
# #             tenant_id: $tenant_id,
# #             text: e.text,
# #             type: e.type
# #         })
# #         ON CREATE SET 
# #             ent.id = randomUUID(), 
# #             ent.created_at = timestamp(),
# #             ent.uri = e.uri
# #         SET ent.embedding = CASE WHEN e.embedding IS NOT NULL AND size(e.embedding) > 0 THEN e.embedding ELSE ent.embedding END,
# #             ent.uri = CASE WHEN ent.uri IS NULL THEN e.uri ELSE ent.uri END
# #         RETURN count(ent) as count
# #         """
# # 
# #         try:
# #             await self._retry(
# #                 lambda: self.neo4j_repo.execute_write(
# #                      query,
# #                      {"entities": entity_list, "tenant_id": self.tenant_id},
# #                 )
# #             )
# #             return len(entity_list)
# #         except Exception as e:
# #             logger.warning(f" Entity MERGE failed: {e}")
# #             return 0
# # 
# #     async def _create_relationships(self, all_triplets: List[Dict]) -> int:
# #         """CREATE typed relationship edges between entities."""
# #         rel_data = []
# #         for item in all_triplets:
# #             t = item["triplet"]
# #             rel_data.append({
# #                 "subject_text": t.subject,
# #                 "subject_type": t.subject_type,
# #                 "predicate": t.name,
# #                 "object_text": t.object,
# #                 "object_type": t.object_type,
# #                 "chunk_id": item["chunk_id"],
# #                 "confidence": t.confidence,
# #             })
# # 
# #         if not rel_data:
# #             return 0
# # 
# #         query = """
# #         WITH $relationships AS rel_list
# #         UNWIND rel_list AS r
# #         MATCH (s:Entity {tenant_id: $tenant_id, text: r.subject_text, type: r.subject_type})
# #         MATCH (o:Entity {tenant_id: $tenant_id, text: r.object_text, type: r.object_type})
# #         MATCH (c:Chunk {id: r.chunk_id, tenant_id: $tenant_id})
# #         CREATE (s)-[:RELATES_TO {
# #             predicate: r.predicate,
# #             chunk_id: r.chunk_id,
# #             confidence: r.confidence,
# #             tenant_id: $tenant_id,
# #             source_document: CASE WHEN c.source IS NOT NULL THEN c.source ELSE 'unknown' END,
# #             extraction_model: 'deepinfra-llm',
# #             created_at: timestamp()
# #         }]->(o)
# #         RETURN count(*) as count
# #         """
# # 
# #         try:
# #             await self._retry(
# #                 lambda: self.neo4j_repo.execute_write(
# #                     query,
# #                     {"relationships": rel_data, "tenant_id": self.tenant_id},
# #                 )
# #             )
# #             return len(rel_data)
# #         except Exception as e:
# #             logger.warning(f" Relationship creation failed: {e}")
# #             return 0
# # 
# #     async def _create_events(self, all_events: List[Dict]) -> int:
# #         """Create EventHub nodes and their relations to Entities and Chunks."""
# #         if not all_events:
# #             return 0
# # 
# #         hubs = {}
# #         chunk_links = []
# #         participant_links = []
# #         occurred_on_links = []
# #         attribute_of_links = []
# #         
# #         date_attributes = {'DATE', 'TIME', 'OCCURRED_ON', 'WHEN', 'YEAR'}
# # 
# #         for item in all_events:
# #             chunk_id = item["chunk_id"]
# #             ev = item["event"]
# #             
# #             # Deduplicate/collect hubs
# #             hub_key = ev.name
# #             hubs[hub_key] = {
# #                 "name": ev.name,
# #                 "event_type": ev.event_type,
# #             }
# #             
# #             chunk_links.append({
# #                 "chunk_id": chunk_id,
# #                 "event_name": ev.name,
# #             })
# #             
# #             for p in ev.participants:
# #                 participant_links.append({
# #                     "event_name": ev.name,
# #                     "entity_text": p.entity,
# #                     "entity_type": p.entity_type,
# #                     "role": p.role,
# #                 })
# #                 
# #             for a in ev.attributes:
# #                 link = {
# #                     "event_name": ev.name,
# #                     "entity_text": a.value,
# #                     "entity_type": a.entity_type,
# #                     "attribute": a.attribute,
# #                 }
# #                 if a.attribute.upper() in date_attributes:
# #                     occurred_on_links.append(link)
# #                 else:
# #                     attribute_of_links.append(link)
# # 
# #         # Batch MERGE EventHub nodes
# #         hub_query = """
# #         WITH $hubs AS hub_list
# #         UNWIND hub_list AS h
# #         MERGE (hub:EventHub {tenant_id: $tenant_id, name: h.name})
# #         ON CREATE SET 
# #             hub.id = randomUUID(),
# #             hub.type = h.event_type,
# #             hub.created_at = timestamp()
# #         RETURN count(hub) as count
# #         """
# #         
# #         # Batch MERGE Chunk connections
# #         chunk_query = """
# #         WITH $links AS link_list
# #         UNWIND link_list AS l
# #         MATCH (c:Chunk {id: l.chunk_id, tenant_id: $tenant_id})
# #         MATCH (hub:EventHub {tenant_id: $tenant_id, name: l.event_name})
# #         MERGE (c)-[:HAS_EVENT_HUB {tenant_id: $tenant_id}]->(hub)
# #         RETURN count(*) as count
# #         """
# #         
# #         # Batch MERGE Participant connections
# #         participant_query = """
# #         WITH $links AS link_list
# #         UNWIND link_list AS l
# #         MATCH (e:Entity {tenant_id: $tenant_id, text: l.entity_text, type: l.entity_type})
# #         MATCH (hub:EventHub {tenant_id: $tenant_id, name: l.event_name})
# #         MERGE (e)-[:PARTICIPANT_IN {role: l.role, tenant_id: $tenant_id}]->(hub)
# #         RETURN count(*) as count
# #         """
# # 
# #         # Batch MERGE Occurred On (Dates) connections
# #         occurred_on_query = """
# #         WITH $links AS link_list
# #         UNWIND link_list AS l
# #         MATCH (e:Entity {tenant_id: $tenant_id, text: l.entity_text, type: l.entity_type})
# #         MATCH (hub:EventHub {tenant_id: $tenant_id, name: l.event_name})
# #         MERGE (e)-[:OCCURRED_ON {tenant_id: $tenant_id}]->(hub)
# #         RETURN count(*) as count
# #         """
# # 
# #         # Batch MERGE Attribute Of connections
# #         attribute_of_query = """
# #         WITH $links AS link_list
# #         UNWIND link_list AS l
# #         MATCH (e:Entity {tenant_id: $tenant_id, text: l.entity_text, type: l.entity_type})
# #         MATCH (hub:EventHub {tenant_id: $tenant_id, name: l.event_name})
# #         MERGE (e)-[:ATTRIBUTE_OF {attribute: l.attribute, tenant_id: $tenant_id}]->(hub)
# #         RETURN count(*) as count
# #         """
# # 
# #         try:
# #             # 1. Merge Hubs
# #             await self._retry(lambda: self.neo4j_repo.execute_write(hub_query, {"hubs": list(hubs.values()), "tenant_id": self.tenant_id}))
# #             
# #             # 2. Chunk connections
# #             if chunk_links:
# #                 await self._retry(lambda: self.neo4j_repo.execute_write(chunk_query, {"links": chunk_links, "tenant_id": self.tenant_id}))
# #             
# #             # 3. Participant connections
# #             if participant_links:
# #                 await self._retry(lambda: self.neo4j_repo.execute_write(participant_query, {"links": participant_links, "tenant_id": self.tenant_id}))
# #                 
# #             # 4. Occurred On connections
# #             if occurred_on_links:
# #                 await self._retry(lambda: self.neo4j_repo.execute_write(occurred_on_query, {"links": occurred_on_links, "tenant_id": self.tenant_id}))
# #                 
# #             # 5. Attribute Of connections
# #             if attribute_of_links:
# #                 await self._retry(lambda: self.neo4j_repo.execute_write(attribute_of_query, {"links": attribute_of_links, "tenant_id": self.tenant_id}))
# #                 
# #             return len(hubs)
# #         except Exception as e:
# #             logger.warning(f" Event creation failed: {e}")
# #             return 0
# # 
# #     async def _create_triplet_nodes(self, all_triplets: List[Dict]) -> int:
# #         """CREATE Triplet nodes with embeddings and link to source chunks."""
# #         # Generate embeddings for triplet text strings
# #         triplet_texts = [item["triplet"].text for item in all_triplets]
# # 
# #         try:
# #             embeddings = await EmbeddingGenerator.generate_embeddings_batch(
# #                 triplet_texts
# #             )
# #         except Exception as e:
# #             logger.warning(f" Triplet embedding generation failed: {e}")
# #             embeddings = [None] * len(triplet_texts)
# # 
# #         node_data = []
# #         for i, item in enumerate(all_triplets):
# #             t = item["triplet"]
# #             node_data.append({
# #                 "triplet_id": str(uuid.uuid4()),
# #                 "text": t.text,
# #                 "subject": t.subject,
# #                 "predicate": t.name,
# #                 "object": t.object,
# #                 "chunk_id": item["chunk_id"],
# #                 "embedding": embeddings[i] if embeddings[i] else [],
# #             })
# # 
# #         if not node_data:
# #             return 0
# # 
# #         query = """
# #         WITH $triplets AS triplet_list
# #         UNWIND triplet_list AS td
# #         CREATE (t:Triplet {
# #             id: td.triplet_id,
# #             tenant_id: $tenant_id,
# #             text: td.text,
# #             subject: td.subject,
# #             predicate: td.predicate,
# #             object: td.object,
# #             chunk_id: td.chunk_id,
# #             embedding: td.embedding,
# #             created_at: timestamp()
# #         })
# #         WITH t, td
# #         MATCH (c:Chunk {id: td.chunk_id, tenant_id: $tenant_id})
# #         CREATE (c)-[:HAS_TRIPLET]->(t)
# #         RETURN count(t) as count
# #         """
# # 
# #         try:
# #             await self._retry(
# #                 lambda: self.neo4j_repo.execute_write(
# #                     query,
# #                     {"triplets": node_data, "tenant_id": self.tenant_id},
# #                 )
# #             )
# #             return len(node_data)
# #         except Exception as e:
# #             logger.warning(f" Triplet node creation failed: {e}")
# #             return 0
# # 
#
# class TripletGraphWriter:
#     """
#     Orchestrator for persisting extracted triplets to Neo4j graph.
#     Delegates to StandardTripletWriter and EventHubWriter.
#     """
#     def __init__(self, tenant_id: str):
#         from .neo4j_repository import Neo4jRepository
#         from .neo4j_retry import retry_neo4j_operation
#
#         self.tenant_id = tenant_id
#         self.neo4j_repo = Neo4jRepository(tenant_id)
#         self._retry = retry_neo4j_operation
#
#         self.standard_writer = StandardTripletWriter(tenant_id, self.neo4j_repo, self._retry)
#         self.event_hub_writer = EventHubWriter(tenant_id, self.neo4j_repo, self._retry)
#
#     async def persist_triplets(
#         self,
#         extraction_results: List[TripletExtractionResult],
#     ) -> Dict:
#         """
#         Persist all extracted triplets and events to Neo4j.
#         """
#         all_triplets = []
#         all_events = []
#
#         start_time = time.perf_counter()
#
#         # Validation & Routing
#         for result in extraction_results:
#             if not result.success: continue
#
#             for fact in result.facts:
#                 try:
#                     ExtractedFactShape(**fact.__dict__)
#                 except ValidationError as e:
#                     logger.warning(f"Fact validation failed: {e}")
#                     # Write to rejection sink
#                     with open("logs/rejected_triplets.jsonl", "a", encoding="utf-8") as f:
#                         f.write(json.dumps({"chunk_id": result.chunk_id, "tenant_id": self.tenant_id, "reason": str(e), "fact": fact.__dict__}) + "\n")
#                     continue
#
#                 if needs_event_hub(fact):
#                     all_events.append({
#                         "chunk_id": result.chunk_id,
#                         "event": fact,
#                     })
#                 else:
#                     all_triplets.append({
#                         "chunk_id": result.chunk_id,
#                         "triplet": fact,
#                     })
#
#         if not all_triplets and not all_events:
#             logger.info(" No facts to persist after validation")
#             return {
#                 "entities_created": 0,
#                 "relationships_created": 0,
#                 "triplets_created": 0,
#                 "events_created": 0,
#             }
#
#         logger.info(f" Persisting {len(all_triplets)} relations and {len(all_events)} events to Neo4j...")
#
#         # Step 1: ONTOLOGY GROUNDING (Coreference Resolution)
#         from .ontology_resolver import OntologyResolver
#         resolver = OntologyResolver(self.tenant_id)
#
#         unique_entities_list = []
#         seen = set()
#
#         # Collect from triplets
#         for item in all_triplets:
#             t = item["triplet"]
#             for text, type_ in [(t.subject, t.subject_type), (t.object, t.object_type)]:
#                 k = f"{text}|{type_}"
#                 if k not in seen and text:
#                     seen.add(k)
#                     unique_entities_list.append({"text": text, "type": type_})
#
#         # Collect from events
#         for item in all_events:
#             ev = item["event"]
#             for p in ev.participants:
#                 k = f"{p.entity}|{p.entity_type}"
#                 if k not in seen:
#                     seen.add(k)
#                     unique_entities_list.append({"text": p.entity, "type": p.entity_type})
#             for a in ev.attributes:
#                 k = f"{a.value}|{a.entity_type}"
#                 if k not in seen:
#                     seen.add(k)
#                     unique_entities_list.append({"text": a.value, "type": a.entity_type})
#
#         canonical_map = await resolver.resolve_entities(unique_entities_list)
#
#         canonical_entities_to_merge = {}
#
#         def add_entity_to_merge(text: str, type_: str):
#             if not text: return text
#             mapped = canonical_map.get(text)
#             if mapped:
#                 resolved_text = mapped["text"]
#                 emb = mapped["embedding"]
#             else:
#                 resolved_text = text
#                 emb = []
#
#             key = f"{resolved_text}|{type_}"
#             canonical_entities_to_merge[key] = {
#                 "text": resolved_text,
#                 "type": type_,
#                 "embedding": emb,
#                 "uri": create_uri(type_, resolved_text)
#             }
#             return resolved_text
#
#         # Update triplets and collect entities
#         for item in all_triplets:
#             t = item["triplet"]
#             t.subject = add_entity_to_merge(t.subject, t.subject_type)
#             t.object = add_entity_to_merge(t.object, t.object_type)
#
#         # Update events and collect entities
#         for item in all_events:
#             ev = item["event"]
#             for p in ev.participants:
#                 p.entity = add_entity_to_merge(p.entity, p.entity_type)
#             for a in ev.attributes:
#                 a.value = add_entity_to_merge(a.value, a.entity_type)
#
#         # Delegate writes
#         std_results = await self.standard_writer.write(all_triplets, canonical_entities_to_merge)
#         events_created = await self.event_hub_writer.write(all_events)
#
#         elapsed = time.perf_counter() - start_time
#         logger.info(
#             f" Triplet & Event persistence complete in {elapsed:.2f}s: "
#             f"{std_results['entities_created']} entities, "
#             f"{std_results['relationships_created']} relationships, "
#             f"{std_results['triplets_created']} triplet nodes, "
#             f"{events_created} event hubs"
#         )
#         return {
#             "entities_created": std_results["entities_created"],
#             "relationships_created": std_results["relationships_created"],
#             "triplets_created": std_results["triplets_created"],
#             "events_created": events_created,
#         }
#
# # ============================================================================
# # TRIPLET RETRIEVER (for RAG pipeline enhancement)
# # ============================================================================
#
# class TripletRetriever:
#     """
#     Retrieve relevant triplets for a query using semantic search.
#
#     INTEGRATION: Called as an optional enrichment step in RAG pipeline.
#     Does NOT replace existing retrieval  ADDS triplet context alongside chunks.
#
#     FLOW:
#         Query  Embed  Search Triplet embeddings  Get relevant (S,P,O)
#                Expand to neighboring entities  Format as context
#     """
#
#     def __init__(self, tenant_id: str):
#         from .neo4j_repository import Neo4jRepository
#         self.tenant_id = tenant_id
#         self.neo4j_repo = Neo4jRepository(tenant_id)
#
#     async def search_triplets(
#         self,
#         query_embedding: List[float],
#         kb_ids: List[str],
#         top_k: int = 20,
#     ) -> List[Dict]:
#         """
#         Search triplets by embedding similarity.
#
#         Args:
#             query_embedding: Query embedding vector
#             kb_id: Knowledge Base UUID (scope search)
#             top_k: Max triplets to return
#
#         Returns:
#             List of triplet dicts with text, subject, predicate, object, score
#         """
#         # Get triplets linked to chunks in this KB OR memory-based triplets (not linked to KB)
#         query = """
#         // Part 1: KB-linked triplets
#         MATCH (kb:KnowledgeBase)
#         WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
#         MATCH (kb)-[:HAS_CHUNK]->(c:Chunk)-[:HAS_TRIPLET]->(t:Triplet {tenant_id: $tenant_id})
#         WHERE t.embedding IS NOT NULL AND size(t.embedding) = $dimension
#         RETURN t.id as id, t.text as text, t.subject as subject,
#                t.predicate as predicate, t.object as object,
#                t.embedding as embedding, t.chunk_id as chunk_id
#
#         UNION
#
#         // Part 2: Floating memory-based triplets (e.g., from chat consolidation)
#         MATCH (t:Triplet {tenant_id: $tenant_id})
#         WHERE t.embedding IS NOT NULL AND size(t.embedding) = $dimension
#         AND NOT (t)<-[:HAS_TRIPLET]-(:Chunk)-[:HAS_CHUNK]-(:KnowledgeBase)
#         RETURN t.id as id, t.text as text, t.subject as subject,
#                t.predicate as predicate, t.object as object,
#                t.embedding as embedding, t.chunk_id as chunk_id
#
#         LIMIT 500
#         """
#
#         try:
#             results = await self.neo4j_repo.execute_read(
#                 query,
#                 {
#                     "kb_ids": kb_ids,
#                     "tenant_id": self.tenant_id,
#                     "dimension": EmbeddingGenerator.get_dimension(),
#                 },
#             )
#
#             if not results:
#                 return []
#
#             # Score by cosine similarity
#             scored_triplets = []
#             for r in results:
#                 similarity = EmbeddingGenerator.cosine_similarity(
#                     query_embedding, r["embedding"]
#                 )
#                 scored_triplets.append({
#                     "id": r["id"],
#                     "text": r["text"],
#                     "subject": r["subject"],
#                     "predicate": r["predicate"],
#                     "object": r["object"],
#                     "chunk_id": r["chunk_id"],
#                     "similarity": similarity,
#                 })
#
#             # Sort by similarity, return top-k
#             scored_triplets.sort(key=lambda x: x["similarity"], reverse=True)
#             return scored_triplets[:top_k]
#
#         except Exception as e:
#             logger.warning(f" Triplet search failed: {e}")
#             return []
#
#     async def get_entity_neighborhood(
#         self,
#         entity_texts: List[str],
#         max_hops: int = 1,
#     ) -> List[Dict]:
#         """
#         Get triplet relationships around specific entities.
#
#         Args:
#             entity_texts: Entity names to expand
#             max_hops: Relationship hops (1 = direct connections)
#
#         Returns:
#             List of relationship dicts
#         """
#         query = """
#         WITH $entities AS entity_list
#         UNWIND entity_list AS ent_text
#         MATCH (e:Entity {tenant_id: $tenant_id, text: ent_text})
#         MATCH (e)-[r:RELATES_TO]->(target:Entity {tenant_id: $tenant_id})
#         RETURN e.text as source, r.predicate as predicate,
#                target.text as target, r.confidence as confidence
#         UNION
#         MATCH (source:Entity {tenant_id: $tenant_id})-[r:RELATES_TO]->(e:Entity {tenant_id: $tenant_id})
#         WHERE e.text IN $entities
#         RETURN source.text as source, r.predicate as predicate,
#                e.text as target, r.confidence as confidence
#         """
#
#         try:
#             results = await self.neo4j_repo.execute_read(
#                 query,
#                 {"entities": entity_texts, "tenant_id": self.tenant_id},
#             )
#             return [dict(r) for r in results] if results else []
#         except Exception as e:
#             logger.warning(f" Entity neighborhood search failed: {e}")
#             return []
#
#     def format_triplets_as_context(self, triplets: List[Dict]) -> str:
#         """Format triplets as readable context for LLM injection, grouping by event hubs."""
#         if not triplets:
#             return ""
#
#         hubs = {}
#         simple_relations = []
#
#         for t in triplets:
#             pred = t["predicate"].upper()
#             subj = t["subject"]
#             obj = t["object"]
#             score = t.get("similarity", 0)
#
#             # Check if this is a participant link to a hub
#             if "PARTICIPATED_IN_ROLE_" in pred:
#                 role = pred.replace("PARTICIPATED_IN_ROLE_", "")
#                 hub_name = obj
#                 if hub_name not in hubs:
#                     hubs[hub_name] = {"participants": [], "attributes": [], "max_score": score}
#                 hubs[hub_name]["participants"].append((subj, role))
#                 hubs[hub_name]["max_score"] = max(hubs[hub_name]["max_score"], score)
#
#             # Check if this is an attribute link from a hub
#             elif any(indicator in pred for indicator in ["DATE", "AMOUNT", "HAS_DATE", "HAS_AMOUNT", "LOCATION", "STATUS", "VALUE"]):
#                 hub_name = subj
#                 if hub_name not in hubs:
#                     hubs[hub_name] = {"participants": [], "attributes": [], "max_score": score}
#                 hubs[hub_name]["attributes"].append((pred.lower(), obj))
#                 hubs[hub_name]["max_score"] = max(hubs[hub_name]["max_score"], score)
#
#             else:
#                 simple_relations.append(t)
#
#         lines = ["KNOWLEDGE GRAPH RELATIONSHIPS:"]
#
#         # 1. Output Grouped Event Hubs
#         if hubs:
#             lines.append("   Grouped Events:")
#             for hub_name, info in hubs.items():
#                 lines.append(f"     * Event: {hub_name} (relevance: {info['max_score']:.2f})")
#                 if info["participants"]:
#                     parts_str = ", ".join([f"{entity} ({role.lower()})" for entity, role in info["participants"]])
#                     lines.append(f"       - Participants: {parts_str}")
#                 if info["attributes"]:
#                     attrs_str = ", ".join([f"{attr}: {val}" for attr, val in info["attributes"]])
#                     lines.append(f"       - Details: {attrs_str}")
#
#         # 2. Output Simple Binary Relations
#         if simple_relations:
#             if hubs:
#                 lines.append("   Direct Relationships:")
#             for t in simple_relations:
#                 lines.append(
#                     f"     - {t['subject']} [{t['predicate']}] {t['object']} "
#                     f"(relevance: {t.get('similarity', 0):.2f})"
#                 )
#
#         return "\n".join(lines)