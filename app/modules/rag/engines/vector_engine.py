import logging
import re
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

    def __init__(self, tenant_id: str, neo4j_repo: Neo4jRepository, session_factory: Any = None):
        self.tenant_id = tenant_id
        self.neo4j_repo = neo4j_repo
        self.session_factory = session_factory

    async def get_candidate_sections(self, task: Any, kb_ids: List[str]) -> List[Dict[str, Any]]:
        keywords = getattr(task.metadata_filters, "keywords", []) if getattr(task, "metadata_filters", None) else []
        if not keywords and getattr(task, "query", None):
            import re
            words = re.findall(r'\w+', task.query)
            stopwords = {"what", "is", "are", "the", "a", "an", "in", "on", "of", "for", "to", "know", "does", "do", "did", "tell", "me", "about", "who", "where", "when", "why", "how"}
            keywords = [w for w in words if w.lower() not in stopwords and len(w) > 1]

        if self.session_factory:
            try:
                async with self.session_factory() as db:
                    from sqlalchemy import text
                    from uuid import UUID
                    parsed_tenant_id = UUID(str(self.tenant_id))
                    parsed_kb_ids = [UUID(str(kid)) for kid in kb_ids]
                    
                    or_fts_query = " OR ".join(f'"{k}"' if ' ' in k else k for k in keywords) if keywords else ""
                    query_text = task.query or ""
                    
                    # If there are no keywords and no query, just get 50 recent chunks
                    where_clause = ""
                    order_clause = "ORDER BY created_at DESC"
                    if keywords or query_text:
                        where_clause = """
                          AND (
                            search_vector @@ websearch_to_tsquery('simple', :query_text)
                            OR (:or_fts_query != '' AND search_vector @@ websearch_to_tsquery('simple', :or_fts_query))
                          )
                        """
                        order_clause = """
                        ORDER BY ts_rank_cd(
                            search_vector, 
                            CASE 
                                WHEN :or_fts_query != '' THEN websearch_to_tsquery('simple', :or_fts_query)
                                ELSE websearch_to_tsquery('simple', :query_text)
                            END
                        ) DESC
                        """

                    sql = f"""
                    SELECT 
                        id AS section_id,
                        metadata_json->>'section' AS title,
                        'document' AS doc_type
                    FROM document_chunks
                    WHERE tenant_id = :tenant_id 
                      AND kb_id = ANY(:kb_ids)
                      {where_clause}
                    {order_clause}
                    LIMIT 50
                    """
                    res = await db.execute(text(sql), {
                        "tenant_id": parsed_tenant_id,
                        "kb_ids": parsed_kb_ids,
                        "query_text": query_text,
                        "or_fts_query": or_fts_query
                    })
                    rows = res.fetchall()
                    if rows:
                        sections = []
                        for r in rows:
                            sections.append({
                                "title": r.title or "Unknown",
                                "doc_type": r.doc_type,
                                "section_id": r.section_id
                            })
                        return sections
            except Exception as e:
                logging.getLogger(__name__).error(f"VectorEngine Postgres candidate gathering failed: {e}. Falling back to Cypher.")

        if keywords:
            cypher = """
            MATCH (kb:KnowledgeBase)-[:HAS_CHUNK]->(c:Chunk)
            WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
            AND any(word IN $keywords WHERE toLower(c.text) CONTAINS toLower(word))
            RETURN DISTINCT c.section as title, c.source_type as doc_type, c.id as section_id
            LIMIT 50
            """
        else:
            cypher = """
            MATCH (kb:KnowledgeBase)-[:HAS_CHUNK]->(c:Chunk)
            WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
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
        """
        logger.info(f"VectorEngine executing task: {task.task_id}")

        target_section_ids = getattr(task, "target_section_ids", []) or []
        
        keywords = getattr(task.metadata_filters, "keywords", []) if getattr(task, "metadata_filters", None) else []
        if not keywords and getattr(task, "query", None):
            words = re.findall(r'\w+', task.query)
            stopwords = {"what", "is", "are", "the", "a", "an", "in", "on", "of", "for", "to", "know", "does", "do", "did", "tell", "me", "about", "who", "where", "when", "why", "how"}
            keywords = [w for w in words if w.lower() not in stopwords and len(w) > 1]

        is_coverage_fallback = getattr(task, "task_id", "").startswith("fallback_")

        if not target_section_ids and not is_coverage_fallback:
            logger.info(
                "VectorEngine task=%s: target_section_ids is empty. "
                "Falling back to full-KB vector search instead of aborting.",
                task.task_id,
            )

        if self.session_factory:
            try:
                async with self.session_factory() as db:
                    from sqlalchemy import text
                    from uuid import UUID
                    parsed_tenant_id = UUID(str(self.tenant_id))
                    parsed_kb_ids = [UUID(str(kid)) for kid in kb_ids]

                    effective_query = ""
                    if getattr(task, "query", None):
                        effective_query = task.query
                    elif keywords:
                        effective_query = " ".join(keywords)

                    if not effective_query:
                        logger.info(f"VectorEngine task={task.task_id}: Empty effective query. Returning [].")
                        return []

                    from app.core.embeddings import EmbeddingGenerator
                    query_embedding = await EmbeddingGenerator.generate_embedding(effective_query)
                    
                    if not query_embedding:
                        logger.error(f"VectorEngine task={task.task_id}: Failed to generate query embedding.")
                        return []

                    # RRF Parameters
                    rrf_k = 60
                    
                    from app.core.language import detect_document_language
                    query_lang = detect_document_language(effective_query)

                    section_filter_sql = ""
                    if target_section_ids:
                        section_uuids = [UUID(str(sid)) for sid in target_section_ids]
                        section_filter_sql = " AND c.id = ANY(:target_section_ids) "
                        
                    or_fts_query = " OR ".join(f'"{k}"' if ' ' in k else k for k in keywords) if keywords else ""
                    
                    top_k_limit = getattr(task, "top_k", 15)

                    hybrid_sql = f"""
                    WITH vector_candidates AS (
                        SELECT 
                            c.id, c.text, c.s3_path, c.metadata_json, 
                            c.chunk_index, c.kb_name,
                            (1.0 - (c.embedding <=> CAST(:query_embedding AS vector))) AS vec_score,
                            c.metadata_json->>'section' AS section
                        FROM document_chunks c
                        WHERE c.tenant_id = :tenant_id 
                          AND c.kb_id = ANY(:kb_ids)
                          AND c.embedding IS NOT NULL
                          {section_filter_sql}
                        ORDER BY c.embedding <=> CAST(:query_embedding AS vector)
                        LIMIT 50
                    ),
                    fts_candidates AS (
                        SELECT 
                            c.id, c.text, c.s3_path, c.metadata_json, 
                            c.chunk_index, c.kb_name,
                            ts_rank_cd(
                                c.search_vector, 
                                CASE 
                                    WHEN :or_fts_query != '' THEN websearch_to_tsquery(CAST(:query_lang AS regconfig), :or_fts_query)
                                    ELSE websearch_to_tsquery(CAST(:query_lang AS regconfig), :query_text)
                                END
                            ) AS fts_score,
                            c.metadata_json->>'section' AS section
                        FROM document_chunks c
                        WHERE c.tenant_id = :tenant_id 
                          AND c.kb_id = ANY(:kb_ids)
                          AND (
                            c.search_vector @@ websearch_to_tsquery(CAST(:query_lang AS regconfig), :query_text)
                            OR (:or_fts_query != '' AND c.search_vector @@ websearch_to_tsquery(CAST(:query_lang AS regconfig), :or_fts_query))
                          )
                          {section_filter_sql}
                        ORDER BY fts_score DESC
                        LIMIT 50
                    )
                    SELECT 
                        COALESCE(vc.id, fc.id) AS id,
                        COALESCE(vc.text, fc.text) AS text,
                        COALESCE(vc.s3_path, fc.s3_path) AS s3_path,
                        COALESCE(vc.metadata_json, fc.metadata_json) AS metadata_json,
                        COALESCE(vc.chunk_index, fc.chunk_index) AS chunk_index,
                        COALESCE(vc.kb_name, fc.kb_name) AS kb_name,
                        COALESCE(vc.vec_score, 0.0) AS vec_score,
                        COALESCE(fc.fts_score, 0.0) AS fts_score,
                        COALESCE(vc.section, fc.section) AS section,
                        (
                            COALESCE(1.0 / (:rrf_k + ROW_NUMBER() OVER (ORDER BY vc.vec_score DESC)), 0.0) +
                            COALESCE(1.0 / (:rrf_k + ROW_NUMBER() OVER (ORDER BY fc.fts_score DESC)), 0.0)
                        ) AS rrf_score
                    FROM vector_candidates vc
                    FULL OUTER JOIN fts_candidates fc ON vc.id = fc.id
                    ORDER BY rrf_score DESC
                    LIMIT {int(top_k_limit)};
                    """

                    sql_params = {
                        "tenant_id": parsed_tenant_id,
                        "kb_ids": parsed_kb_ids,
                        "query_text": effective_query,
                        "query_lang": query_lang,
                        "or_fts_query": or_fts_query,
                        "query_embedding": str(query_embedding),
                        "rrf_k": rrf_k
                    }
                    if target_section_ids:
                        sql_params["target_section_ids"] = [UUID(str(sid)) for sid in target_section_ids]

                    res = await db.execute(text(hybrid_sql), sql_params)
                    all_rows = res.fetchall()

                    # Fallback: if section-restricted search returned 0 candidates, retry without section restriction
                    if not all_rows and target_section_ids and not is_coverage_fallback:
                        logger.info(
                            "VectorEngine task=%s: section-restricted search returned 0 rows. Retrying broad hybrid search without section filter...",
                            task.task_id,
                        )
                        broad_sql = hybrid_sql.replace(" AND c.id = ANY(:target_section_ids) ", "")
                        broad_params = {k: v for k, v in sql_params.items() if k != "target_section_ids"}
                        res = await db.execute(text(broad_sql), broad_params)
                        all_rows = res.fetchall()

                    chunks = []
                    for row in all_rows:
                        vec_sim = float(row.vec_score) if row.vec_score is not None else 0.0
                        fts_score = float(row.fts_score) if row.fts_score is not None else 0.0
                        rrf = float(row.rrf_score) if row.rrf_score is not None else 0.0
                        
                        chunk_section = row.section
                        target_sec = getattr(task, "target_section", None)
                        
                        # Only tag the node if it was a strict section-targeted query and matches
                        node_value = (
                            chunk_section
                            if chunk_section and target_sec
                            and chunk_section.lower() == target_sec.lower()
                            else None
                        )

                        chunks.append(RetrievedChunk(
                            chunk_id=str(row.id),
                            text=row.text,
                            score=rrf,
                            # Use vec_sim if it's strong, otherwise if FTS found it, give it a baseline.
                            hybrid_score=vec_sim if vec_sim > 0.6 else (0.75 if fts_score else vec_sim),
                            reason="HYBRID_SEARCH_RRF",
                            source=row.s3_path or getattr(row, "kb_name", None) or f"DocumentChunk {row.chunk_index}",
                            s3_path=row.s3_path,
                            engine_name="vector",
                            section=chunk_section or "Unknown",
                            ontology_node=chunk_section
                        ))

                    return chunks
            except Exception as e:
                logger.error(f"VectorEngine pgvector hybrid retrieval failed: {e}. Falling back to Cypher.")

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
        else:
            logger.info(
                "VectorEngine Cypher task=%s: target_section_ids empty. "
                "Falling back to full-graph scan instead of aborting.",
                task.task_id,
            )

        if keywords:
            cypher += """
            AND any(word IN $keywords WHERE toLower(c.text) CONTAINS toLower(word))
            """
        
        cypher += """
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
