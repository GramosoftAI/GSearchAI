"""
Triplet-Based Knowledge Graph Construction Engine

PHASE 4A FEATURE: Extracts (Subject, Predicate, Object) triplets from text chunks
using LLM, then creates typed relationship edges in Neo4j graph.

INTEGRATION STRATEGY (ZERO BREAKING CHANGES):
    - Runs as a POST-INGESTION hook AFTER existing pipeline succeeds
    - Feature-flagged via settings.use_triplet_extraction (OFF by default)
    - Creates NEW node/edge types (Triplet, RELATES_TO)  never modifies existing
    - Existing MENTIONS, SIMILAR, NEXT edges remain untouched
    - If triplet extraction fails, ingestion still succeeds (graceful degradation)

ARCHITECTURE:
    Chunk Text  LLM Extract Triplets  (Subject, Predicate, Object)
                                        MERGE Entity nodes (deduplicated)
                                        CREATE typed RELATES_TO edges
                                        CREATE Triplet nodes with embedded text
                                        Embed triplet strings for semantic search

GRAPH SCHEMA (additive):
    (:Entity {text, type, tenant_id})
    (:Triplet {text, subject, predicate, object, chunk_id, tenant_id, embedding})
    (Entity)-[:RELATES_TO {predicate, chunk_id, confidence}]->(Entity)
    (Chunk)-[:HAS_TRIPLET]->(Triplet)
"""

import logging
import json
import re
import uuid
from typing import List, Dict, Optional
from dataclasses import dataclass, field

from .config import get_settings
from .embeddings import EmbeddingGenerator
import urllib.parse

# ============================================================================
# RDF SEMANTIC ONTOLOGY MAPPER
# ============================================================================
CANONICAL_RELATIONS = {
    "issued": "ISSUED_BY",
    "created_bill": "ISSUED_BY",
    "generated_invoice": "ISSUED_BY",
    "purchased": "PURCHASED",
    "bought": "PURCHASED",
    "ordered": "PURCHASED",
    "supplied_by": "SUPPLIED_BY",
    "provided_by": "SUPPLIED_BY",
    "contains": "CONTAINS_PRODUCT",
    "includes": "CONTAINS_PRODUCT",
    "belongs_to": "BELONGS_TO",
    "located_in": "LOCATED_IN",
    "has_amount": "HAS_AMOUNT",
    "has_date": "HAS_DATE",
    "references": "REFERENCES",
    "derived_from": "DERIVED_FROM"
}

def create_uri(entity_type: str, text: str) -> str:
    """Generate globally unique RDF-compliant URI for an entity."""
    clean_type = urllib.parse.quote(entity_type.lower().strip())
    clean_text = urllib.parse.quote(text.lower().strip().replace(' ', '_'))
    return f"https://grag.ai/kg/{clean_type}/{clean_text}"

logger = logging.getLogger(__name__)
settings = get_settings()


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class ExtractedTriplet:
    """Single (Subject, Predicate, Object) triplet extracted from text."""
    subject: str
    predicate: str
    object: str
    subject_type: str = "CONCEPT"
    object_type: str = "CONCEPT"
    confidence: float = 1.0
    evidence: str = None

    @property
    def text(self) -> str:
        """Triplet as searchable string: 'Einstein  born_in  Ulm'"""
        return f"{self.subject}  {self.predicate}  {self.object}"

    def normalize(self) -> "ExtractedTriplet":
        """Normalize triplet fields for consistency and apply RDF Ontology Mapping."""
        raw_pred = self.predicate.strip().lower().replace(" ", "_")
        canonical_pred = CANONICAL_RELATIONS.get(raw_pred, raw_pred.upper())
        return ExtractedTriplet(
            subject=self.subject.strip().lower(),
            predicate=canonical_pred,
            object=self.object.strip().lower(),
            subject_type=self.subject_type.upper().strip(),
            object_type=self.object_type.upper().strip(),
            confidence=self.confidence,
        )


@dataclass
class TripletExtractionResult:
    """Result of triplet extraction for a single chunk."""
    chunk_id: str
    triplets: List[ExtractedTriplet] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None


# ============================================================================
# TRIPLET EXTRACTOR (LLM-BASED)
# ============================================================================

# Extraction prompt  deterministic, structured output
# NOTE: All literal {{ }} are escaped for Python .format()  only {text} is a placeholder
TRIPLET_EXTRACTION_PROMPT = """Extract knowledge triplets from the following text.
Each triplet must be a factual relationship in the form (Subject, Predicate, Object).

RULES:
1. Extract only FACTUAL relationships explicitly stated in the text
2. Subject and Object must be specific named entities or concepts
3. Predicate must be a clear relationship verb/phrase
4. Do NOT infer or assume relationships not stated
5. Normalize entity names (use full proper names)
6. Maximum 10 triplets per text chunk

Return ONLY valid JSON in this exact format:
{{
    "triplets": [
        {{
            "subject": "Albert Einstein",
            "predicate": "born_in",
            "object": "Ulm",
            "subject_type": "PERSON",
            "object_type": "LOCATION"
        }}
    ]
}}

Valid entity types: PERSON, ORGANIZATION, LOCATION, CONCEPT, EVENT, PRODUCT, TECHNOLOGY, NUMERIC
7. Always extract numeric values (years, scores, prices, percentages) as the 'object' if they define a key relationship (e.g., 'completed_in', 'has_gpa').

TEXT:
{text}

JSON:"""


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
        from .llm.deepinfra_llm import DeepInfraLLMClient
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
            valid_types_str = "PERSON, ORGANIZATION, LOCATION, CONCEPT, EVENT, PRODUCT, TECHNOLOGY, NUMERIC"
            valid_relations_str = ""
            rules_text = ""
            if self.tenant_id:
                from ..modules.ontology.service import OntologyService
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
                "Valid entity types: PERSON, ORGANIZATION, LOCATION, CONCEPT, EVENT, PRODUCT, TECHNOLOGY, NUMERIC",
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

            triplets = self._parse_triplets(response_text, max_triplets)

            logger.info(
                f"Extracted {len(triplets)} triplets from chunk {chunk_id[:8]}"
            )
            return TripletExtractionResult(chunk_id=chunk_id, triplets=triplets)

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
        
        # Create tasks for all chunks
        
        # --- DYNAMIC SCHEMA DISCOVERY (Ontology-Aware Ingestion) ---
        if self.tenant_id and chunks:
            try:
                from .schema_detector import SchemaDetector
                from ..modules.ontology.service import OntologyService
                
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
        
        total_triplets = sum(len(r.triplets) for r in results)
        failed = sum(1 for r in results if not r.success)
        logger.info(
            f" Batch extraction complete: {total_triplets} triplets "
            f"from {len(chunks)} chunks ({failed} failures)"
        )
        return results

    def _parse_triplets(
        self,
        response_text: str,
        max_triplets: int,
    ) -> List[ExtractedTriplet]:
        """Parse LLM response into validated ExtractedTriplet objects."""
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

        raw_triplets = data.get("triplets", [])
        if not isinstance(raw_triplets, list):
            return []

        triplets = []
        for raw in raw_triplets[:max_triplets]:
            if not isinstance(raw, dict):
                continue

            subject = raw.get("subject", "").strip()
            predicate = raw.get("predicate", "").strip()
            obj = raw.get("object", "").strip()

            # Validate: all three fields must be non-empty
            if not subject or not predicate or not obj:
                continue

            # Validate: minimum length (filter noise)
            if len(subject) < 2 or len(obj) < 2:
                continue

            triplet = ExtractedTriplet(
                subject=subject,
                predicate=predicate,
                object=obj,
                subject_type=raw.get("subject_type", "CONCEPT"),
                object_type=raw.get("object_type", "CONCEPT"),
                confidence=1.0,
            ).normalize()

            triplets.append(triplet)

        return triplets


# ============================================================================
# GRAPH PERSISTENCE (Neo4j)
# ============================================================================

class TripletGraphWriter:
    """
    Persist extracted triplets to Neo4j graph.

    CREATES (additive only  never modifies existing graph):
        1. MERGE Entity nodes (deduplicated by text+type+tenant)
        2. CREATE typed RELATES_TO edges between entities
        3. CREATE Triplet nodes with embedded text for semantic search
        4. CREATE Chunk-[:HAS_TRIPLET]->Triplet relationships

    MULTI-TENANCY:
        - All nodes/edges tagged with tenant_id
        - Uses same Neo4jRepository pattern as existing codebase
    """

    def __init__(self, tenant_id: str):
        from .neo4j_repository import Neo4jRepository
        from .neo4j_retry import retry_neo4j_operation

        self.tenant_id = tenant_id
        self.neo4j_repo = Neo4jRepository(tenant_id)
        self._retry = retry_neo4j_operation

    async def persist_triplets(
        self,
        extraction_results: List[TripletExtractionResult],
    ) -> Dict:
        """
        Persist all extracted triplets to Neo4j.

        FLOW:
        1. Collect all unique entities across all chunks
        2. Batch MERGE entity nodes
        3. Batch CREATE relationship edges
        4. Batch CREATE triplet nodes with embeddings
        5. Link triplets to source chunks

        Returns:
            Dict with counts: entities_created, relationships_created, triplets_created
        """
        # Collect all triplets from successful extractions
        all_triplets = []
        for result in extraction_results:
            if result.success:
                for triplet in result.triplets:
                    all_triplets.append({
                        "chunk_id": result.chunk_id,
                        "triplet": triplet,
                    })

        if not all_triplets:
            logger.info(" No triplets to persist")
            return {"entities_created": 0, "relationships_created": 0, "triplets_created": 0}

        logger.info(f" Persisting {len(all_triplets)} triplets to Neo4j...")

        # Step 1: ONTOLOGY GROUNDING (Coreference Resolution)
        from .ontology_resolver import OntologyResolver
        resolver = OntologyResolver(self.tenant_id)
        
        unique_entities_list = []
        seen = set()
        for item in all_triplets:
            t = item["triplet"]
            for text, type_ in [(t.subject, t.subject_type), (t.object, t.object_type)]:
                k = f"{text}|{type_}"
                if k not in seen:
                    seen.add(k)
                    unique_entities_list.append({"text": text, "type": type_})
                    
        canonical_map = await resolver.resolve_entities(unique_entities_list)
        
        canonical_entities_to_merge = {}
        for item in all_triplets:
            t = item["triplet"]
            
            subj_mapped = canonical_map.get(t.subject)
            if subj_mapped:
                t.subject = subj_mapped["text"]
                canonical_entities_to_merge[f"{t.subject}|{t.subject_type}"] = {
                    "text": t.subject,
                    "type": t.subject_type,
                    "embedding": subj_mapped["embedding"],
                    "uri": create_uri(t.subject_type, t.subject)
                }
            else:
                canonical_entities_to_merge[f"{t.subject}|{t.subject_type}"] = {
                    "text": t.subject,
                    "type": t.subject_type,
                    "embedding": [],
                    "uri": create_uri(t.subject_type, t.subject)
                }
                
            obj_mapped = canonical_map.get(t.object)
            if obj_mapped:
                t.object = obj_mapped["text"]
                canonical_entities_to_merge[f"{t.object}|{t.object_type}"] = {
                    "text": t.object,
                    "type": t.object_type,
                    "embedding": obj_mapped["embedding"],
                    "uri": create_uri(t.object_type, t.object)
                }
            else:
                canonical_entities_to_merge[f"{t.object}|{t.object_type}"] = {
                    "text": t.object,
                    "type": t.object_type,
                    "embedding": [],
                    "uri": create_uri(t.object_type, t.object)
                }

        # Step 1: MERGE Entity nodes (deduplicated + embeddings)
        entities_created = await self._merge_entities(list(canonical_entities_to_merge.values()))

        # Step 2: CREATE relationship edges
        relationships_created = await self._create_relationships(all_triplets)

        # Step 3: CREATE Triplet nodes with embeddings + link to chunks
        triplets_created = await self._create_triplet_nodes(all_triplets)

        result = {
            "entities_created": entities_created,
            "relationships_created": relationships_created,
            "triplets_created": triplets_created,
        }

        logger.info(
            f" Triplet persistence complete: "
            f"{entities_created} entities, "
            f"{relationships_created} relationships, "
            f"{triplets_created} triplet nodes"
        )
        return result

    async def _merge_entities(self, entity_list: List[Dict]) -> int:
        """MERGE unique entity nodes (prevents duplicates)."""
        if not entity_list:
            return 0

        query = """
        WITH $entities AS entity_list
        UNWIND entity_list AS e
        MERGE (ent:TripletEntity {
            tenant_id: $tenant_id,
            text: e.text,
            type: e.type
        })
        ON CREATE SET 
            ent.id = randomUUID(), 
            ent.created_at = timestamp(),
            ent.uri = e.uri
        SET ent.embedding = CASE WHEN e.embedding IS NOT NULL AND size(e.embedding) > 0 THEN e.embedding ELSE ent.embedding END,
            ent.uri = CASE WHEN ent.uri IS NULL THEN e.uri ELSE ent.uri END
        RETURN count(ent) as count
        """

        try:
            await self._retry(
                lambda: self.neo4j_repo.execute_write(
                    query,
                    {"entities": entity_list, "tenant_id": self.tenant_id},
                )
            )
            return len(entity_list)
        except Exception as e:
            logger.warning(f" Entity MERGE failed: {e}")
            return 0

    async def _create_relationships(self, all_triplets: List[Dict]) -> int:
        """CREATE typed relationship edges between entities."""
        rel_data = []
        for item in all_triplets:
            t = item["triplet"]
            rel_data.append({
                "subject_text": t.subject,
                "subject_type": t.subject_type,
                "predicate": t.predicate,
                "object_text": t.object,
                "object_type": t.object_type,
                "chunk_id": item["chunk_id"],
                "confidence": t.confidence,
            })

        if not rel_data:
            return 0

        query = """
        WITH $relationships AS rel_list
        UNWIND rel_list AS r
        MATCH (s:TripletEntity {tenant_id: $tenant_id, text: r.subject_text, type: r.subject_type})
        MATCH (o:TripletEntity {tenant_id: $tenant_id, text: r.object_text, type: r.object_type})
        MATCH (c:Chunk {id: r.chunk_id, tenant_id: $tenant_id})
        CREATE (s)-[:RELATES_TO {
            predicate: r.predicate,
            chunk_id: r.chunk_id,
            confidence: r.confidence,
            tenant_id: $tenant_id,
            source_document: CASE WHEN c.source IS NOT NULL THEN c.source ELSE 'unknown' END,
            extraction_model: 'deepinfra-llm',
            created_at: timestamp()
        }]->(o)
        RETURN count(*) as count
        """

        try:
            await self._retry(
                lambda: self.neo4j_repo.execute_write(
                    query,
                    {"relationships": rel_data, "tenant_id": self.tenant_id},
                )
            )
            return len(rel_data)
        except Exception as e:
            logger.warning(f" Relationship creation failed: {e}")
            return 0

    async def _create_triplet_nodes(self, all_triplets: List[Dict]) -> int:
        """CREATE Triplet nodes with embeddings and link to source chunks."""
        # Generate embeddings for triplet text strings
        triplet_texts = [item["triplet"].text for item in all_triplets]

        try:
            embeddings = await EmbeddingGenerator.generate_embeddings_batch(
                triplet_texts
            )
        except Exception as e:
            logger.warning(f" Triplet embedding generation failed: {e}")
            embeddings = [None] * len(triplet_texts)

        node_data = []
        for i, item in enumerate(all_triplets):
            t = item["triplet"]
            node_data.append({
                "triplet_id": str(uuid.uuid4()),
                "text": t.text,
                "subject": t.subject,
                "predicate": t.predicate,
                "object": t.object,
                "chunk_id": item["chunk_id"],
                "embedding": embeddings[i] if embeddings[i] else [],
            })

        if not node_data:
            return 0

        query = """
        WITH $triplets AS triplet_list
        UNWIND triplet_list AS td
        CREATE (t:Triplet {
            id: td.triplet_id,
            tenant_id: $tenant_id,
            text: td.text,
            subject: td.subject,
            predicate: td.predicate,
            object: td.object,
            chunk_id: td.chunk_id,
            embedding: td.embedding,
            created_at: timestamp()
        })
        WITH t, td
        MATCH (c:Chunk {id: td.chunk_id, tenant_id: $tenant_id})
        CREATE (c)-[:HAS_TRIPLET]->(t)
        RETURN count(t) as count
        """

        try:
            await self._retry(
                lambda: self.neo4j_repo.execute_write(
                    query,
                    {"triplets": node_data, "tenant_id": self.tenant_id},
                )
            )
            return len(node_data)
        except Exception as e:
            logger.warning(f" Triplet node creation failed: {e}")
            return 0


# ============================================================================
# TRIPLET RETRIEVER (for RAG pipeline enhancement)
# ============================================================================

class TripletRetriever:
    """
    Retrieve relevant triplets for a query using semantic search.

    INTEGRATION: Called as an optional enrichment step in RAG pipeline.
    Does NOT replace existing retrieval  ADDS triplet context alongside chunks.

    FLOW:
        Query  Embed  Search Triplet embeddings  Get relevant (S,P,O)
               Expand to neighboring entities  Format as context
    """

    def __init__(self, tenant_id: str):
        from .neo4j_repository import Neo4jRepository
        self.tenant_id = tenant_id
        self.neo4j_repo = Neo4jRepository(tenant_id)

    async def search_triplets(
        self,
        query_embedding: List[float],
        kb_ids: List[str],
        top_k: int = 20,
    ) -> List[Dict]:
        """
        Search triplets by embedding similarity.

        Args:
            query_embedding: Query embedding vector
            kb_id: Knowledge Base UUID (scope search)
            top_k: Max triplets to return

        Returns:
            List of triplet dicts with text, subject, predicate, object, score
        """
        # Get triplets linked to chunks in this KB OR memory-based triplets (not linked to KB)
        query = """
        // Part 1: KB-linked triplets
        MATCH (kb:KnowledgeBase)
        WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
        MATCH (kb)-[:HAS_CHUNK]->(c:Chunk)-[:HAS_TRIPLET]->(t:Triplet {tenant_id: $tenant_id})
        WHERE t.embedding IS NOT NULL AND size(t.embedding) = $dimension
        RETURN t.id as id, t.text as text, t.subject as subject,
               t.predicate as predicate, t.object as object,
               t.embedding as embedding, t.chunk_id as chunk_id
        
        UNION
        
        // Part 2: Floating memory-based triplets (e.g., from chat consolidation)
        MATCH (t:Triplet {tenant_id: $tenant_id})
        WHERE t.embedding IS NOT NULL AND size(t.embedding) = $dimension
        AND NOT (t)<-[:HAS_TRIPLET]-(:Chunk)-[:HAS_CHUNK]-(:KnowledgeBase)
        RETURN t.id as id, t.text as text, t.subject as subject,
               t.predicate as predicate, t.object as object,
               t.embedding as embedding, t.chunk_id as chunk_id
        
        LIMIT 500
        """

        try:
            results = await self.neo4j_repo.execute_read(
                query,
                {
                    "kb_ids": kb_ids,
                    "tenant_id": self.tenant_id,
                    "dimension": EmbeddingGenerator.get_dimension(),
                },
            )

            if not results:
                return []

            # Score by cosine similarity
            scored_triplets = []
            for r in results:
                similarity = EmbeddingGenerator.cosine_similarity(
                    query_embedding, r["embedding"]
                )
                scored_triplets.append({
                    "id": r["id"],
                    "text": r["text"],
                    "subject": r["subject"],
                    "predicate": r["predicate"],
                    "object": r["object"],
                    "chunk_id": r["chunk_id"],
                    "similarity": similarity,
                })

            # Sort by similarity, return top-k
            scored_triplets.sort(key=lambda x: x["similarity"], reverse=True)
            return scored_triplets[:top_k]

        except Exception as e:
            logger.warning(f" Triplet search failed: {e}")
            return []

    async def get_entity_neighborhood(
        self,
        entity_texts: List[str],
        max_hops: int = 1,
    ) -> List[Dict]:
        """
        Get triplet relationships around specific entities.

        Args:
            entity_texts: Entity names to expand
            max_hops: Relationship hops (1 = direct connections)

        Returns:
            List of relationship dicts
        """
        query = """
        WITH $entities AS entity_list
        UNWIND entity_list AS ent_text
        MATCH (e:TripletEntity {tenant_id: $tenant_id, text: ent_text})
        MATCH (e)-[r:RELATES_TO]->(target:TripletEntity {tenant_id: $tenant_id})
        RETURN e.text as source, r.predicate as predicate,
               target.text as target, r.confidence as confidence
        UNION
        MATCH (source:TripletEntity {tenant_id: $tenant_id})-[r:RELATES_TO]->(e:TripletEntity {tenant_id: $tenant_id})
        WHERE e.text IN $entities
        RETURN source.text as source, r.predicate as predicate,
               e.text as target, r.confidence as confidence
        """

        try:
            results = await self.neo4j_repo.execute_read(
                query,
                {"entities": entity_texts, "tenant_id": self.tenant_id},
            )
            return [dict(r) for r in results] if results else []
        except Exception as e:
            logger.warning(f" Entity neighborhood search failed: {e}")
            return []

    def format_triplets_as_context(self, triplets: List[Dict]) -> str:
        """Format triplets as readable context for LLM injection."""
        if not triplets:
            return ""

        lines = ["KNOWLEDGE GRAPH RELATIONSHIPS:"]
        for t in triplets:
            score = t.get("similarity", 0)
            lines.append(
                f"   {t['subject']} [{t['predicate']}] {t['object']} "
                f"(relevance: {score:.2f})"
            )
        return "\n".join(lines)
