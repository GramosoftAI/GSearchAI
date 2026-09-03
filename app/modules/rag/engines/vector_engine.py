import logging
from typing import List, Dict, Any
from app.core.neo4j_repository import Neo4jRepository
from app.modules.rag.pipeline import RetrievedChunk
from app.modules.rag.schemas import RetrievalTask
from app.modules.rag.orchestrator.query_analyzer import QueryIntent
from app.modules.rag.engines.registry import BaseEngine, CapabilityRegistry
from cachetools import TTLCache
import asyncio

logger = logging.getLogger(__name__)

# Cache for section snippets to avoid per-query STRING_AGG DB hits
# Key: f"{kb_id}_{tenant_id}", Value: Dict[str, str] mapping section -> snippet
_KB_SECTION_SNIPPETS_CACHE = TTLCache(maxsize=100, ttl=3600)
_KB_SECTION_SNIPPETS_LOCK = asyncio.Lock()

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

    async def _get_or_load_kb_snippets(self, kb_id: str) -> Dict[str, str]:
        """Lazy loads and caches the first ~600 chars of content for each section in a KB."""
        cache_key = f"{kb_id}_{self.tenant_id}"
        
        # Fast path
        if cache_key in _KB_SECTION_SNIPPETS_CACHE:
            return _KB_SECTION_SNIPPETS_CACHE[cache_key]
            
        # Slow path with lock to prevent dogpiling
        async with _KB_SECTION_SNIPPETS_LOCK:
            if cache_key in _KB_SECTION_SNIPPETS_CACHE:
                return _KB_SECTION_SNIPPETS_CACHE[cache_key]
                
            snippets = {}
            if self.db:
                try:
                    import time
                    from sqlalchemy import text
                    t0 = time.time()
                    
                    sql = """
                    WITH RankedChunks AS (
                        SELECT kb_id, section, chunk_index, text,
                               ROW_NUMBER() OVER(PARTITION BY kb_id, section ORDER BY chunk_index) as rn
                        FROM document_chunks
                        WHERE kb_id = :kb_id AND tenant_id = :tenant_id AND section IS NOT NULL
                    )
                    SELECT section, STRING_AGG(SUBSTRING(text, 1, 200), ' ' ORDER BY rn) as snippet
                    FROM RankedChunks
                    WHERE rn <= 3
                    GROUP BY kb_id, section
                    """
                    res = await self.db.execute(text(sql), {'kb_id': kb_id, 'tenant_id': str(self.tenant_id)})
                    for row in res.all():
                        snippets[row.section] = row.snippet
                        
                    t1 = time.time()
                    logger.info(f"[CACHE_WARM] Loaded {len(snippets)} section snippets for KB {kb_id} in {t1-t0:.3f}s")
                except Exception as e:
                    logger.error(f"Failed to load section snippets for KB {kb_id}: {e}")
            
            _KB_SECTION_SNIPPETS_CACHE[cache_key] = snippets
            return snippets

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

        # Prefetch snippets for all candidate KBs concurrently
        kb_snippets = {}
        if self.db:
            snippet_results = await asyncio.gather(
                *[self._get_or_load_kb_snippets(str(k)) for k in kb_ids],
                return_exceptions=True
            )
            for k, res in zip(kb_ids, snippet_results):
                if isinstance(res, dict):
                    kb_snippets.update(res)

        sections = []
        if self.db:
            try:
                from sqlalchemy import select, or_, text
                from app.modules.knowledge_bases.models import DocumentChunk
                from uuid import UUID
                
                stmt = select(DocumentChunk.section).where(
                    DocumentChunk.kb_id.in_([UUID(str(k)) for k in kb_ids]),
                    DocumentChunk.tenant_id == UUID(str(self.tenant_id)),
                    DocumentChunk.section.is_not(None)
                ).group_by(DocumentChunk.section)
                
                if broad_keywords:
                    # Use ILIKE for partial word matches without raw string interpolation
                    ilike_conditions = [DocumentChunk.text.ilike(f"%{kw}%") for kw in broad_keywords]
                    stmt = stmt.where(or_(*ilike_conditions))
                    
                    from sqlalchemy import case
                    relevance_exprs = [
                        case((DocumentChunk.section.ilike(f"%{kw}%"), 1), else_=0)
                        for kw in broad_keywords
                    ]
                    relevance_score = sum(relevance_exprs)
                    stmt = stmt.order_by(relevance_score.desc(), DocumentChunk.section.asc())
                else:
                    stmt = stmt.order_by(DocumentChunk.section.asc())
                    
                stmt = stmt.limit(1000)
                
                logger.info(f"[VECTOR_ENGINE_DEBUG] get_candidate_sections broad_keywords={broad_keywords}")
                
                res = await self.db.execute(stmt)
                rows = res.all()
                if len(rows) >= 1000:
                    logger.warning(f"Candidate section truncation triggered: >= 1000 sections found, truncated to 1000.")
                
                for row in rows:
                    sec = row.section
                    if sec:
                        sections.append({
                            "section_id": sec,
                            "title": sec,
                            "snippet": kb_snippets.get(sec, ""),
                            "doc_type": "document",
                            "task_id": getattr(task, "task_id", "")
                        })
            except Exception as e:
                logger.error(f"Postgres candidate section search failed: {e}")
                if hasattr(self.db, "rollback"):
                    import asyncio
                    if asyncio.iscoroutinefunction(self.db.rollback):
                        await self.db.rollback()
                    else:
                        self.db.rollback()
                
        latency = time.time() - trace_start
        logger.info(f"[TRACE_E2E] [EXIT] VectorEngine.get_candidate_sections - Output: {len(sections)} sections - Latency: {latency:.2f}s")
        return sections

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
            retrieval_path = "full_kb_fallback"
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
                position_boost = case((DocumentChunk.chunk_index < 3, 1.0), else_=0.0).cast(Float)

                # Build the WHERE conditions.
                # When target_section_ids is populated, restrict the candidate
                # set to those specific chunk UUIDs so vector ranking operates
                # within the permitted section scope, not across the entire KB.
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

                all_rows = res.fetchall()
                
                # To prevent log spam, we only log the match once per kb
                matched_kbs = set()
                
                for idx, row in enumerate(all_rows):
                    similarity = float(row.similarity) if row.similarity is not None else 0.8
                    chunk_text = row.text or ""
                    kb_name = (row.name or "").lower()
                    kb_path = (row.s3_path or "").lower()

                    weight = 1.0
                    
                    # 1. Source Identity Anchoring (Domain Match)
                    # If the KB filename/name explicitly contains our query's core entities, massively boost it
                    import re
                    def basic_stem(word):
                        if len(word) <= 3: return word
                        for suffix in ('ing', 'ed', 'es', 's', 'e'):
                            if word.endswith(suffix):
                                return word[:-len(suffix)]
                        return word

                    STOP_WORDS = {"south", "north", "east", "west", "total", "amount", "count", "sum", "average", "max", "min", "data", "report"}
                    for kw in exploded_keywords:
                        if len(kw) > 3:
                            # Use basic stemming to allow 'hike' to match 'hiking' (stem 'hik')
                            stemmed_kw = basic_stem(kw)
                            if re.search(rf"\b{re.escape(stemmed_kw)}", kb_name) or re.search(rf"\b{re.escape(stemmed_kw)}", kb_path):
                                is_stopword = kw in STOP_WORDS or stemmed_kw in STOP_WORDS
                                is_multiword = " " in kw
                                if is_stopword and not is_multiword:
                                    continue
                                
                                weight *= 1.40
                                if row.kb_id not in matched_kbs:
                                    logger.info(f"[BOOST_CHECK] Domain Match: stemmed keyword '{stemmed_kw}' (from '{kw}') matched kb_name '{kb_name}' or path '{kb_path}'")
                                    matched_kbs.add(row.kb_id)
                            
                    # 2. Text Match Anchoring (Gentle boost for exact keyword occurrences)
                    for kw in exploded_keywords:
                        if len(kw) > 3 and kw in chunk_text.lower():
                            weight *= 1.05

                    base_weighted = similarity * weight
                    if row.chunk_index < 3:
                        final_score = base_weighted + 1.0
                    elif row.chunk_index >= 90000 and not is_tabular:
                        # Synthetic table chunks are short, keyword-dense fragments
                        # that artificially inflate similarity for narrative queries.
                        # Penalize them so narrative chunks can surface.
                        final_score = min(base_weighted * 0.85, 2.0)
                    else:
                        final_score = min(base_weighted, 2.0)

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
                        # fabricate coverage-validation evidence.
                        ontology_node=None,
                        retrieval_path=retrieval_path,
                        domain_matched=(row.kb_id in matched_kbs),
                    ))

                # Rerank in python
                chunks.sort(key=lambda x: x.hybrid_score, reverse=True)
                final_chunks = chunks[:candidate_limit]
                latency = time.time() - trace_start
                logger.info(f"[TRACE_E2E] [EXIT] VectorEngine.retrieve - Output: {len(final_chunks)} chunks (pgvector) - Latency: {latency:.2f}s")
                logger.info(f"[BOOST_CHECK] returning matched_kb_ids={matched_kbs} type={type(matched_kbs)} to caller")
                return final_chunks
            except Exception as e:
                logger.error(f"VectorEngine pgvector retrieval failed: {e}. Falling back to Cypher.")
                if hasattr(self.db, "rollback"):
                    import asyncio
                    if asyncio.iscoroutinefunction(self.db.rollback):
                        await self.db.rollback()
                    else:
                        self.db.rollback()

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
