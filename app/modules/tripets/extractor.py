import logging
import json
import re
from typing import List, Dict, Optional

from app.core.config import get_settings
from app.modules.tripets.prompt import TRIPLET_EXTRACTION_PROMPT
from app.modules.tripets.models import (
    ExtractedFact,
    ExtractedParticipant,
    ExtractedAttribute,
    TripletExtractionResult
)

logger = logging.getLogger(__name__)
settings = get_settings()

class TripletExtractor:
    """
    Extract structured knowledge triplets from text using LLM.

    USAGE:
        extractor = TripletExtractor()
        result = await extractor.extract_from_chunk(chunk_id, chunk_text)
        # result.triplets = [ExtractedTriplet(...), ...]

    SAFETY:
        - Temperature 0.0 for deterministic extraction
        - Structured JSON output with validation
        - Max 10 triplets per chunk (prevent runaway)
        - Graceful fallback on LLM failure
    """

    # Track initialization logging
    _init_logged = False

    def __init__(self, tenant_id: Optional[str] = None):
        """Initialize with LLM client (lazy import to avoid circular deps)."""
        from app.core.llm.deepinfra_llm import DeepInfraLLMClient
        self.llm_client = DeepInfraLLMClient()
        self.tenant_id = tenant_id

    async def extract_from_chunk(
        self,
        chunk_id: str,
        chunk_text: str,
        max_triplets: int = 10,
    ) -> TripletExtractionResult:
        """
        Extract triplets from a single chunk.

        Args:
            chunk_id: Chunk UUID
            chunk_text: Raw text content
            max_triplets: Maximum triplets to extract

        Returns:
            TripletExtractionResult with extracted triplets
        """
        if not chunk_text or len(chunk_text.strip()) < 20:
            return TripletExtractionResult(chunk_id=chunk_id, triplets=[])

        if not TripletExtractor._init_logged:
            logger.info("Triplet Extraction Engine initialized (LLM-based)")
            TripletExtractor._init_logged = True

        try:
            # --- ONTOLOGY GROUNDING INJECTION ---
            valid_types_str = "PERSON, ORGANIZATION, LOCATION, CONCEPT, EVENT, PRODUCT, TECHNOLOGY, NUMERIC, STRUCTURED_IDENTIFIER"
            valid_relations_str = ""
            rules_text = ""
            if self.tenant_id:
                from app.modules.ontology.service import OntologyService
                ont_svc = OntologyService(self.tenant_id)
                ont_data = await ont_svc.get_ontology()
                if ont_data.get("classes"):
                    valid_types_str = ", ".join([c["name"] for c in ont_data["classes"]])
                if ont_data.get("relations"):
                    # Avoid duplicate empty objects if no relations
                    rels = [r["name"] for r in ont_data["relations"] if r.get("name")]
                    if rels:
                        valid_relations_str = "\nValid relationship predicates: " + ", ".join(rels)
                if ont_data.get("rules"):
                    rules_list = [f"({r['source_class']} -> {r['relation']} -> {r['target_class']})" for r in ont_data["rules"] if r.get("source_class")]
                    if rules_list:
                        rules_text = "\nALLOWED RELATIONSHIP RULES (STRICT SCHEMA):\n" + "\n".join(rules_list) + "\nYou MUST ONLY use these exact relationships if they apply."

            replacement = f"Valid entity types: {valid_types_str}{valid_relations_str}{rules_text}"
            
            prompt = TRIPLET_EXTRACTION_PROMPT.replace(
                "Valid entity types: PERSON, ORGANIZATION, LOCATION, CONCEPT, EVENT, PRODUCT, TECHNOLOGY, NUMERIC, STRUCTURED_IDENTIFIER",
                replacement
            ).format(text=chunk_text[:2000])

            logger.info(f"Calling LLM for triplet extraction (chunk {chunk_id[:8]}, text length: {len(chunk_text)})")

            response_text = await self.llm_client.generate(
                prompt=prompt,
                system_prompt="You are a strict extraction system. Return ONLY valid JSON. DO NOT use <think> tags or explanations.",
                temperature=0.1,
                max_tokens=1024,
            )

            logger.info(f"LLM response received ({len(response_text)} chars): {response_text[:300]}...")

            facts = self._parse_triplets(response_text, max_triplets)

            logger.info(
                f"Extracted {len(facts)} facts from chunk {chunk_id[:8]}"
            )
            return TripletExtractionResult(chunk_id=chunk_id, facts=facts)

        except Exception as e:
            logger.error(f"Triplet extraction failed for chunk {chunk_id[:8]}: {e}", exc_info=True)
            return TripletExtractionResult(chunk_id=chunk_id, error=str(e))

    async def extract_from_chunks_batch(
        self,
        chunks: List[Dict[str, str]],
    ) -> List[TripletExtractionResult]:
        """
        Extract triplets from multiple chunks in parallel.

        Args:
            chunks: List of {"chunk_id": str, "text": str}

        Returns:
            List of TripletExtractionResult
        """
        import asyncio
        
        logger.info(f" Batch extracting triplets from {len(chunks)} chunks in parallel...")
        
        # --- DYNAMIC SCHEMA DISCOVERY (Ontology-Aware Ingestion) ---
        if self.tenant_id and chunks:
            try:
                from app.core.schema_detector import SchemaDetector
                from app.modules.ontology.service import OntologyService
                
                sample_text = "\n".join([c.get("text", "") for c in chunks[:3]])
                if sample_text:
                    detector = SchemaDetector()
                    schema = await detector.discover_schema(sample_text)
                    
                    if schema.get("classes") or schema.get("relations"):
                        ont_svc = OntologyService(self.tenant_id)
                        await ont_svc.auto_register_schema(schema)
            except Exception as e:
                logger.warning(f"Dynamic schema detection failed: {e}")
                
        # --- TRIPLET EXTRACTION ---
        tasks = [
            self.extract_from_chunk(
                chunk_id=chunk["chunk_id"],
                chunk_text=chunk["text"],
            )
            for chunk in chunks
        ]
        
        # Execute all tasks in parallel
        results = await asyncio.gather(*tasks)
        
        total_facts = sum(len(r.facts) for r in results)
        failed = sum(1 for r in results if not r.success)
        logger.info(
            f" Batch extraction complete: {total_facts} facts "
            f"from {len(chunks)} chunks ({failed} failures)"
        )
        return results

    def _parse_triplets(
        self,
        response_text: str,
        max_triplets: int,
    ) -> List[ExtractedFact]:
        """Parse LLM response into validated ExtractedFact objects."""
        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if not json_match:
            logger.warning("No JSON found in triplet extraction response")
            return []

        try:
            data = json.loads(json_match.group(0))
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in triplet response: {e}")
            return []

        facts = []

        # Parse Facts
        raw_facts = data.get("facts", [])
        if isinstance(raw_facts, list) and raw_facts:
            for raw_fact in raw_facts:
                if not isinstance(raw_fact, dict):
                    continue
                
                name = raw_fact.get("name", "").strip()
                if not name:
                    continue
                
                mode_hint = str(raw_fact.get("mode_hint", "relationship")).strip().lower()
                event_type = str(raw_fact.get("event_type", "EVENT")).strip().upper()
                
                subject = raw_fact.get("subject")
                if isinstance(subject, list): subject = ", ".join(str(v) for v in subject)
                if subject: subject = str(subject).strip()
                
                obj = raw_fact.get("object")
                if isinstance(obj, list): obj = ", ".join(str(v) for v in obj)
                if obj: obj = str(obj).strip()
                
                subject_type = str(raw_fact.get("subject_type", "CONCEPT")).strip().upper()
                object_type = str(raw_fact.get("object_type", "CONCEPT")).strip().upper()
                
                raw_participants = raw_fact.get("participants", [])
                raw_attributes = raw_fact.get("attributes", [])
                
                participants = []
                attributes = []
                
                for p in raw_participants:
                    if not isinstance(p, dict): continue
                    
                    entity = p.get("entity", "")
                    if isinstance(entity, list): entity = ", ".join(str(v) for v in entity)
                    entity = str(entity).strip()
                    
                    role = p.get("role", "participant")
                    if isinstance(role, list): role = ", ".join(str(v) for v in role)
                    role = str(role).strip().upper()
                    
                    ent_type = str(p.get("entity_type", "CONCEPT")).strip().upper()
                    
                    if entity and len(entity) >= 2:
                        participants.append(ExtractedParticipant(entity=entity.lower(), role=role, entity_type=ent_type))

                for a in raw_attributes:
                    if not isinstance(a, dict): continue
                    
                    attr = a.get("attribute", "has_attribute")
                    if isinstance(attr, list): attr = ", ".join(str(v) for v in attr)
                    attr = str(attr).strip().upper().replace(" ", "_")
                    
                    val = a.get("value", "")
                    if isinstance(val, list): val = ", ".join(str(v) for v in val)
                    val = str(val).strip()
                    
                    ent_type = str(a.get("entity_type", "CONCEPT")).strip().upper()
                    
                    if val and len(val) >= 2:
                        attributes.append(ExtractedAttribute(attribute=attr, value=val.lower(), entity_type=ent_type))

                fact = ExtractedFact(
                    name=name,
                    subject=subject,
                    object=obj,
                    subject_type=subject_type,
                    object_type=object_type,
                    mode_hint=mode_hint,
                    event_type=event_type,
                    participants=participants,
                    attributes=attributes
                )
                facts.append(fact.normalize())

        return facts[:max_triplets]
