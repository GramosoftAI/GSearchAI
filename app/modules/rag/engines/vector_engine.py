import logging
from typing import List, Dict, Any
from app.core.neo4j_repository import Neo4jRepository
from app.modules.rag.pipeline import RetrievedChunk
from app.modules.rag.orchestrator.query_analyzer import QueryIntent
from app.modules.rag.engines.registry import BaseEngine, CapabilityRegistry

logger = logging.getLogger(__name__)

@CapabilityRegistry.register("vector")
class VectorEngine(BaseEngine):
    """
    Standard semantic vector retrieval engine.
    Used as a fallback for missing coverage goals or unknown domains.
    """

    @classmethod
    def supports(cls, intent: QueryIntent) -> bool:
        return True  # Supports all intents as fallback

    @classmethod
    def priority(cls) -> float:
        return 0.1  # Lowest priority

    @classmethod
    def cost(cls) -> float:
        return 50.0  # Vector similarity is more expensive than exact graph traversal

    @classmethod
    def domain(cls) -> List[str]:
        return ["*"]

    def __init__(self, tenant_id: str, neo4j_repo: Neo4jRepository, db: Any = None):
        self.tenant_id = tenant_id
        self.neo4j_repo = neo4j_repo
        self.db = db

    async def get_candidate_sections(self, task: Any, kb_ids: List[str]) -> List[Dict[str, Any]]:
        keywords = task.metadata_filters.keywords if task.metadata_filters else []
        if not keywords:
            keywords = [task.query.split()[0]] if task.query else []

        cypher = """
        MATCH (kb:KnowledgeBase)-[:HAS_CHUNK]->(c:Chunk)
        WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
        AND any(word IN $keywords WHERE toLower(c.text) CONTAINS toLower(word))
        RETURN DISTINCT c.section as title, c.source_type as doc_type, c.id as section_id
        LIMIT 50
        """
        try:
            results = await self.neo4j_repo.execute_read(
                cypher,
                {"kb_ids": kb_ids, "tenant_id": self.tenant_id, "keywords": keywords}
            )
            sections = []
            if results:
                for r in results:
                    sections.append({
                        "section_id": r.get("section_id"),
                        "title": r.get("title", ""),
                        "doc_type": r.get("doc_type", "unknown"),
                        "task_id": getattr(task, "task_id", "")
                    })
            return sections
        except Exception as e:
            logger.error(f"VectorEngine failed to get candidate sections: {e}")
            return []

    async def retrieve(self, task: Any, kb_ids: List[str]) -> List[RetrievedChunk]:
        """
        Retrieves chunks using PostgreSQL pgvector when db session is available.
        Otherwise, falls back to simulated vector retrieval using Cypher.

        Scoping contract
        ----------------
        * If ``task.target_section_ids`` is a **non-empty** list the pgvector query
          restricts candidates to those chunk UUIDs before applying vector ranking.
          This ensures SectionRanker's decision is always respected.
        * If ``task.target_section_ids`` is **empty** (SectionRanker found zero valid
          candidate sections) we return an empty list immediately.  The pipeline's
          coverage-validation loop handles this correctly — we must not perform a
          full-KB scan and return unrelated chunks as authoritative evidence.
        * ``ontology_node`` is set to ``None`` for pgvector results because the
          pgvector branch retrieves by embedding proximity, not by explicit ontology
          membership.  Assigning task.target_section to every chunk would fabricate
          coverage-validation evidence and mask missing evidence.
        * The one exception is the coverage-validation fallback task (task_id starts
          with ``"fallback_"``), which is deliberately created without section
          restriction — it is the pipeline's intentional broad-search safety net.
        """
        logger.info(f"VectorEngine executing task: {task.task_id}")

        target_section_ids = getattr(task, "target_section_ids", []) or []
        keywords = task.metadata_filters.keywords if task.metadata_filters else []
        if not keywords:
            keywords = [task.query.split()[0]] if task.query else []

        # ------------------------------------------------------------------
        # Zero-section guard
        # When SectionRanker produced no valid candidates, target_section_ids
        # will be an empty list on a normal retrieval task.  Returning []
        # here prevents a full-KB vector scan from fabricating coverage.
        # Coverage-validation fallback tasks (task_id prefix "fallback_") are
        # the pipeline's intentional broad-search safety net and are allowed
        # through without a section restriction.
        # ------------------------------------------------------------------
        is_coverage_fallback = getattr(task, "task_id", "").startswith("fallback_")

        if not target_section_ids and not is_coverage_fallback:
            logger.info(
                "VectorEngine task=%s: target_section_ids is empty "
                "(SectionRanker found 0 valid candidates). "
                "Returning [] to prevent full-KB scan.",
                task.task_id,
            )
            return []

        if self.db:
            try:
                from app.core.embeddings import EmbeddingGenerator
                from sqlalchemy import select, and_, case, Float
                from app.modules.knowledge_bases.models import DocumentChunk, KnowledgeBase
                from uuid import UUID

                query_embedding = (
                    getattr(task.metadata_filters, "query_embedding", None)
                    if getattr(task, "metadata_filters", None)
                    else None
                )
                if not query_embedding:
                    query_embedding = await EmbeddingGenerator.generate_embedding(task.query)

                top_k = getattr(task, "top_k", 15)
                candidate_limit = max(top_k, 15)

                vector_score = (1.0 - DocumentChunk.embedding.cosine_distance(query_embedding))
                position_boost = case((DocumentChunk.chunk_index < 3, 1.0), else_=0.0).cast(Float)

                # Build the WHERE conditions.
                # When target_section_ids is populated, restrict the candidate
                # set to those specific chunk UUIDs so vector ranking operates
                # within the permitted section scope, not across the entire KB.
                base_conditions = [
                    DocumentChunk.tenant_id == UUID(str(self.tenant_id)),
                    DocumentChunk.kb_id.in_([UUID(str(kb_id)) for kb_id in kb_ids]),
                ]

                if target_section_ids:
                    try:
                        section_uuids = [UUID(str(sid)) for sid in target_section_ids]
                        base_conditions.append(DocumentChunk.id.in_(section_uuids))
                        logger.info(
                            "VectorEngine task=%s: restricting pgvector search "
                            "to %d target section IDs.",
                            task.task_id,
                            len(section_uuids),
                        )
                    except (ValueError, AttributeError) as uuid_err:
                        # target_section_ids may contain non-UUID strings from
                        # Neo4j (e.g. element IDs).  Fail closed and return no evidence
                        # rather than broadening the search scope incorrectly.
                        logger.error(
                            "VectorEngine task=%s: invalid target_section_ids: %s",
                            task.task_id,
                            uuid_err,
                        )
                        return []

                stmt = (
                    select(
                        DocumentChunk.id,
                        DocumentChunk.text,
                        DocumentChunk.chunk_index,
                        DocumentChunk.kb_id,
                        DocumentChunk.metadata_json,
                        KnowledgeBase.name,
                        KnowledgeBase.s3_path,
                        vector_score.label("similarity"),
                    )
                    .join(KnowledgeBase, DocumentChunk.kb_id == KnowledgeBase.id)
                    .where(and_(*base_conditions))
                    .order_by((vector_score + position_boost).desc())
                    .limit(200)  # Fetch more for Python re-ranking
                )

                res = await self.db.execute(stmt)
                chunks = []

                # Simple keyword extraction (alphanumeric words > 4 chars)
                exact_terms = [w for w in task.query.split() if len(w) > 4 and w.isalnum()]

                all_rows = res.fetchall()
                for idx, row in enumerate(all_rows):
                    similarity = float(row.similarity) if row.similarity is not None else 0.8
                    chunk_text = row.text or ""

                    weight = 1.0
                    for term in exact_terms:
                        if term.lower() in chunk_text.lower():
                            weight *= 1.15

                    if row.chunk_index < 3:
                        final_score = similarity + 1.0
                    else:
                        final_score = min(similarity * weight, 1.0)

                    chunks.append(RetrievedChunk(
                        chunk_id=str(row.id),
                        text=chunk_text,
                        kb_id=str(row.kb_id),
                        position=idx,
                        embedding_similarity=similarity,
                        graph_score=0.0,
                        hybrid_score=final_score,
                        reason="VECTOR_SEARCH_HYBRID",
                        source=row.s3_path or row.name or f"DocumentChunk {row.chunk_index}",
                        s3_path=row.s3_path,
                        engine_name="vector",
                        section="Unknown",
                        # ontology_node is intentionally None: pgvector retrieves
                        # by embedding proximity, not by explicit ontology
                        # membership.  Assigning task.target_section here would
                        # fabricate coverage-validation evidence.
                        ontology_node=None,
                    ))

                # Rerank in python
                chunks.sort(key=lambda x: x.hybrid_score, reverse=True)
                return chunks[:candidate_limit]
            except Exception as e:
                logger.error(f"VectorEngine pgvector retrieval failed: {e}. Falling back to Cypher.")

        # ------------------------------------------------------------------
        # Cypher fallback (no db session available)
        # Uses keyword-in-text matching.  Apply section restriction when
        # target_section_ids is present.  Return [] on zero sections (unless
        # coverage-fallback) for the same reason as the pgvector branch.
        # ------------------------------------------------------------------
        cypher = """
        MATCH (kb:KnowledgeBase)-[:HAS_CHUNK]->(c:Chunk)
        WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
        """
        params = {"kb_ids": kb_ids, "tenant_id": self.tenant_id, "keywords": keywords}

        if target_section_ids:
            cypher += " AND c.id IN $target_section_ids "
            params["target_section_ids"] = target_section_ids
        elif not is_coverage_fallback:
            logger.info(
                "VectorEngine Cypher task=%s: target_section_ids empty, "
                "returning [] to prevent full-graph scan.",
                task.task_id,
            )
            return []

        cypher += """
        AND any(word IN $keywords WHERE toLower(c.text) CONTAINS toLower(word))
        RETURN c.id as chunk_id, c.text as text, c.section as section
        LIMIT 5
        """
        try:
            results = await self.neo4j_repo.execute_read(cypher, params)
            chunks = []
            if results:
                for idx, res in enumerate(results):
                    # Set ontology_node only when the chunk's own section metadata
                    # genuinely matches the requested scope — not as a blanket
                    # assignment of task.target_section.
                    chunk_section = res.get("section")
                    target_sec = getattr(task, "target_section", None)
                    node_value = (
                        chunk_section
                        if chunk_section and target_sec
                        and chunk_section.lower() == target_sec.lower()
                        else None
                    )
                    chunks.append(RetrievedChunk(
                        chunk_id=res.get("chunk_id", f"vec-chunk-{idx}"),
                        text=res.get("text"),
                        kb_id=kb_ids[0],
                        position=idx,
                        embedding_similarity=0.85,
                        graph_score=0.1,
                        hybrid_score=0.85,
                        reason="VECTOR_FALLBACK",
                        source=f"Section: {chunk_section}",
                        engine_name="vector",
                        section=chunk_section,
                        ontology_node=node_value,
                    ))
            return chunks
        except Exception as e:
            logger.error(f"VectorEngine Cypher fallback failed: {e}")
            return []
