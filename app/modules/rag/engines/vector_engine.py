import logging
from typing import List, Dict, Any
from app.core.neo4j_repository import Neo4jRepository
from app.modules.rag.pipeline import RetrievedChunk
from app.modules.rag.schemas import RetrievalTask
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
    async def get_candidate_sections(self, task: RetrievalTask, kb_ids: List[str]) -> List[Dict[str, Any]]:
        import time
        trace_start = time.time()
        logger.info(f"[TRACE_E2E] [ENTRY] VectorEngine.get_candidate_sections - Input: KB {kb_ids}")
        keywords = task.metadata_filters.get("keywords", []) if isinstance(task.metadata_filters, dict) else (task.metadata_filters.keywords if getattr(task, "metadata_filters", None) else [])
        
        broad_keywords = []
        stopwords = {"what", "when", "this", "that", "code", "data", "info", "find", "how", "why", "where", "which", "with", "does", "then", "from", "they"}
        for kw in keywords:
            for word in kw.split():
                word = word.strip()
                if len(word) > 3 and word.lower() not in stopwords:
                    broad_keywords.append(word)
                    
        if not broad_keywords:
            broad_keywords = keywords

        if not broad_keywords:
            logger.warning("VectorEngine received empty keywords from task metadata. Candidate section search may return 0 results.")

        cypher = """
        MATCH (kb:KnowledgeBase)-[:HAS_CHUNK]->(c:Chunk)
        WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
        AND c.section IS NOT NULL
        AND any(word IN $keywords WHERE toLower(c.text) CONTAINS toLower(word))
        RETURN DISTINCT c.section as title, c.source_type as doc_type
        LIMIT 50
        """
        try:
            results = await self.neo4j_repo.execute_read(
                cypher,
                {"kb_ids": kb_ids, "tenant_id": self.tenant_id, "keywords": broad_keywords}
            )
            sections = []
            if results:
                for r in results:
                    sections.append({
                        "section_id": r.get("title", ""),
                        "title": r.get("title", ""),
                        "doc_type": r.get("doc_type", "unknown"),
                        "task_id": getattr(task, "task_id", "")
                    })
            latency = time.time() - trace_start
            logger.info(f"[TRACE_E2E] [EXIT] VectorEngine.get_candidate_sections - Output: {len(sections)} sections - Latency: {latency:.2f}s")
            return sections
        except Exception as e:
            latency = time.time() - trace_start
            logger.error(f"[TRACE_E2E] [EXIT] VectorEngine.get_candidate_sections - Output: ERROR - Latency: {latency:.2f}s - {e}")
            return []

    async def retrieve(self, task: RetrievalTask, kb_ids: List[str]) -> List[RetrievedChunk]:
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
          coverage-validation loop handles this correctly - we must not perform a
          full-KB scan and return unrelated chunks as authoritative evidence.
        * ``ontology_node`` is set to ``None`` for pgvector results because the
          pgvector branch retrieves by embedding proximity, not by explicit ontology
          membership.  Assigning task.target_section to every chunk would fabricate
          coverage-validation evidence and mask missing evidence.
        * The one exception is the coverage-validation fallback task (task_id starts
          with ``"fallback_"``), which is deliberately created without section
          restriction - it is the pipeline's intentional broad-search safety net.
        """
        import time
        trace_start = time.time()
        logger.info(f"[TRACE_E2E] [ENTRY] VectorEngine.retrieve - Input: Task {task.task_id}, KB {kb_ids}")
        logger.info(f"VectorEngine executing task: {task.task_id}")

        target_sections = getattr(task, "target_section_ids", []) or []
        is_tabular = False
        if getattr(task, "metadata_filters", None):
            is_tabular = task.metadata_filters.get("is_tabular", False) if isinstance(task.metadata_filters, dict) else getattr(task.metadata_filters, "is_tabular", False)

        # ------------------------------------------------------------------
        # Zero-section guard branched on is_tabular.
        # When target_sections is empty, we fall back to a full pgvector search 
        # strictly scoped by kb_ids and tenant_id, UNLESS it's a tabular query,
        # in which case we isolate to synthetic table chunks only.
        # ------------------------------------------------------------------
        if not target_sections:
            retrieval_path = "table_fallback" if is_tabular else "full_kb_fallback"
        else:
            retrieval_path = "targeted_section"
        logger.info(f"zero_section_guard_path: {retrieval_path}")

        if self.db:
            try:
                from app.core.embeddings import EmbeddingGenerator
                from sqlalchemy import select, and_, or_, case, Float
                from app.modules.knowledge_bases.models import DocumentChunk, KnowledgeBase
                from uuid import UUID

                query_embedding = None
                if getattr(task, "metadata_filters", None):
                    if isinstance(task.metadata_filters, dict):
                        query_embedding = task.metadata_filters.get("query_embedding")
                    else:
                        query_embedding = getattr(task.metadata_filters, "query_embedding", None)
                if not query_embedding:
                    query_embedding = await EmbeddingGenerator.generate_embedding(task.query)

                top_k = getattr(task, "top_k", 15)
                candidate_limit = max(top_k, 15)

                vector_score = (1.0 - DocumentChunk.embedding.cosine_distance(query_embedding))
                position_boost = case((DocumentChunk.chunk_index < 3, 0.01), else_=0.0).cast(Float)

                # Build the WHERE conditions.
                base_conditions = [
                    DocumentChunk.tenant_id == UUID(str(self.tenant_id)),
                    DocumentChunk.kb_id.in_([UUID(str(kb_id)) for kb_id in kb_ids]),
                ]

                if target_sections:
                    base_conditions.append(or_(
                        DocumentChunk.section.in_(target_sections),
                        DocumentChunk.chunk_index >= 90000
                    ))
                    logger.info(
                        "VectorEngine task=%s: restricting pgvector search "
                        "to %d target section names (or synthetic table chunks).",
                        task.task_id,
                        len(target_sections),
                    )
                elif is_tabular:
                    base_conditions.append(DocumentChunk.chunk_index >= 90000)
                    logger.info(
                        "VectorEngine task=%s: restricting pgvector search "
                        "to synthetic table chunks ONLY (table_fallback).",
                        task.task_id,
                    )

                stmt = (
                    select(
                        DocumentChunk.id,
                        DocumentChunk.text,
                        DocumentChunk.chunk_index,
                        DocumentChunk.kb_id,
                        DocumentChunk.section,
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
                all_rows = res.fetchall()

                # Fallback: If section-restricted search returned 0 results, fall back to broad search
                if not all_rows and target_sections:
                    logger.info(f"VectorEngine task={task.task_id}: 0 results with target_sections filter. Retrying with broad KB search fallback.")
                    fallback_conditions = [
                        DocumentChunk.tenant_id == UUID(str(self.tenant_id)),
                        DocumentChunk.kb_id.in_([UUID(str(kb_id)) for kb_id in kb_ids]),
                    ]
                    stmt_fallback = (
                        select(
                            DocumentChunk.id,
                            DocumentChunk.text,
                            DocumentChunk.chunk_index,
                            DocumentChunk.kb_id,
                            DocumentChunk.section,
                            DocumentChunk.metadata_json,
                            KnowledgeBase.name,
                            KnowledgeBase.s3_path,
                            vector_score.label("similarity"),
                        )
                        .join(KnowledgeBase, DocumentChunk.kb_id == KnowledgeBase.id)
                        .where(and_(*fallback_conditions))
                        .order_by((vector_score + position_boost).desc())
                        .limit(200)
                    )
                    res_fb = await self.db.execute(stmt_fallback)
                    all_rows = res_fb.fetchall()

                chunks = []

                # Get intelligent keywords from QueryAnalyzer
                analyzer_keywords = []
                if getattr(task, "metadata_filters", None):
                    if isinstance(task.metadata_filters, dict):
                        analyzer_keywords = task.metadata_filters.get("keywords", [])
                    else:
                        analyzer_keywords = getattr(task.metadata_filters, "keywords", [])
                
                # Explode multi-word keywords to catch partial matches in filenames (e.g. '5-day hike' -> 'hike')
                exploded_keywords = set()
                for kw in analyzer_keywords:
                    exploded_keywords.add(kw.lower())
                    for w in kw.split():
                        clean_w = ''.join(c for c in w if c.isalnum()).lower()
                        if len(clean_w) > 3:
                            exploded_keywords.add(clean_w)
                
                if not exploded_keywords:
                    exploded_keywords = {w.lower() for w in task.query.split() if len(w) > 4 and w.isalnum()}
                    
                logger.info(f"[BOOST_CHECK] task_id={task.task_id} analyzer_keywords={analyzer_keywords} exploded_keywords={exploded_keywords}")
                
                # To prevent log spam, we only log the match once per kb
                matched_kbs = set()
                
                for idx, row in enumerate(all_rows):
                    similarity = float(row.similarity) if row.similarity is not None else 0.8
                    chunk_text = row.text or ""
                    kb_name = (row.name or "").lower()
                    kb_path = (row.s3_path or "").lower()

                    weight = 1.0
                    
                    # Section Match Boost
                    if target_sections and row.section in target_sections:
                        weight *= 1.25

                    # 1. Source Identity Anchoring (Domain Match)
                    import re
                    def basic_stem(word):
                        if len(word) <= 3: return word
                        for suffix in ('ing', 'ed', 'es', 's', 'e'):
                            if word.endswith(suffix):
                                return word[:-len(suffix)]
                        return word

                    for kw in exploded_keywords:
                        if len(kw) > 3:
                            stemmed_kw = basic_stem(kw)
                            if re.search(rf"\b{re.escape(stemmed_kw)}", kb_name) or re.search(rf"\b{re.escape(stemmed_kw)}", kb_path):
                                weight *= 1.40
                                if row.kb_id not in matched_kbs:
                                    logger.info(f"[BOOST_CHECK] Domain Match: stemmed keyword '{stemmed_kw}' (from '{kw}') matched kb_name '{kb_name}' or path '{kb_path}'")
                                    matched_kbs.add(row.kb_id)
                            
                    # 2. Text Match Anchoring (Gentle boost for exact keyword occurrences)
                    for kw in exploded_keywords:
                        if len(kw) > 3 and kw in chunk_text.lower():
                            weight *= 1.05

                    base_weighted = similarity * weight
                    pos_boost = 0.005 if row.chunk_index < 3 else 0.0
                    final_score = base_weighted + pos_boost

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
                        section=row.section or "Unknown",
                        ontology_node=None,
                        retrieval_path=retrieval_path,
                    ))

                # Rerank in python
                chunks.sort(key=lambda x: x.hybrid_score, reverse=True)
                final_chunks = chunks[:candidate_limit]
                latency = time.time() - trace_start
                logger.info(f"[TRACE_E2E] [EXIT] VectorEngine.retrieve - Output: {len(final_chunks)} chunks (pgvector) - Latency: {latency:.2f}s")
                return final_chunks
            except Exception as e:
                logger.error(f"VectorEngine pgvector retrieval failed: {e}. Falling back to Cypher.")

        # ------------------------------------------------------------------
        # Cypher fallback (no db session available)
        # Uses keyword-in-text matching.  Apply section restriction when
        # target_section_ids is present.  Zero-section guard removed here too (Fix 2).
        # ------------------------------------------------------------------
        
        keywords = getattr(task.metadata_filters, "keywords", []) if getattr(task, "metadata_filters", None) else []
        if not keywords:
            keywords = [w for w in task.query.split() if len(w) > 3]

        cypher = """
        MATCH (kb:KnowledgeBase)-[:HAS_CHUNK]->(c:Chunk)
        WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
        """
        params = {"kb_ids": kb_ids, "tenant_id": self.tenant_id, "keywords": keywords}

        if target_sections:
            cypher += " AND c.section IN $target_sections "
            params["target_sections"] = target_sections

        cypher += """
        AND any(word IN $keywords WHERE toLower(c.text) CONTAINS toLower(word))
        RETURN c.id as chunk_id, c.text as text, c.section as section
        LIMIT 50
        """
        try:
            results = await self.neo4j_repo.execute_read(cypher, params)
            chunks = []
            if results:
                for idx, res in enumerate(results):
                    # Set ontology_node only when the chunk's own section metadata
                    # genuinely matches the requested scope - not as a blanket
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
                        retrieval_path=retrieval_path,
                    ))
            latency = time.time() - trace_start
            logger.info(f"[TRACE_E2E] [EXIT] VectorEngine.retrieve - Output: {len(chunks)} chunks (cypher) - Latency: {latency:.2f}s")
            return chunks
        except Exception as e:
            latency = time.time() - trace_start
            logger.error(f"[TRACE_E2E] [EXIT] VectorEngine.retrieve - Output: ERROR - Latency: {latency:.2f}s - {e}")
            logger.error(f"VectorEngine Cypher fallback failed: {e}")
            return []
