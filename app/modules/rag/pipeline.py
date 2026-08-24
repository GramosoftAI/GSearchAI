"""



RAG Pipeline - Graph-first retrieval and ranking system



Phase 2 Step 4: Transforms Graph Intelligence into Production RAG



"""







import json
import logging
import asyncio



from typing import List, Dict, Tuple, Set, Optional



from dataclasses import dataclass



from uuid import UUID







from sqlalchemy.ext.asyncio import AsyncSession



from app.core.neo4j_repository import Neo4jRepository



from app.core.embeddings import EmbeddingGenerator



from app.core.config import get_settings



from .query_router import QueryRouter, SearchType











logger = logging.getLogger(__name__)











@dataclass



class RetrievedChunk:



    """Chunk retrieved by RAG pipeline with scoring metadata and attribution"""







    chunk_id: str



    text: str



    kb_id: str



    position: int



    embedding_similarity: float



    graph_score: float



    hybrid_score: float



    reason: str = ""  # Why this chunk was retrieved (SIMILAR, ENTITY, NEXT, Seed)



    source: Optional[str] = None  # Source of the chunk (e.g., filename, URL, database table)
    s3_path: Optional[str] = None # S3 path to the original document
    content_type: str = "original"
    
    # Provenance fields for Enterprise Retrieval Orchestrator
    engine_name: Optional[str] = None
    document: Optional[str] = None
    page: Optional[int] = None
    section: Optional[str] = None
    ontology_node: Optional[str] = None
    retrieval_path: Optional[str] = None
    provenance_metadata: Optional[Dict] = None












@dataclass



class RAGContext:



    """Context retrieved for LLM generation"""







    query: str



    chunks: List[RetrievedChunk]



    entity_mentions: Dict[str, List[str]]  # entity_name -> [chunk_ids]



    total_tokens: int



    triplet_context: str = ""  # Phase 4A: Formatted triplet relationships (additive)



    triplets: List[Dict] = None  # Raw triplets for metadata



    search_type: str = "DEFAULT" # The strategy selected by the router

    personal_memories: List[str] = None # Phase 5: Personal user context (Mem0)
    
    authoritative_entities: List[Dict] = None # Phase 6: System-Level Value Injection (Highest Trust)
    
    query_embedding_tokens: int = 0











import time

# Module-level TTL cache for KB noisy words
_KB_NOISY_WORDS_CACHE = {}  # kb_id -> {"data": noisy_words_list, "expiry": timestamp}
KB_NOISY_WORDS_CACHE_TTL = 300  # 5 minutes

class RAGPipeline:



    """



    Graph-first RAG pipeline: Query  Graph Retrieval  Expansion  Ranking  LLM.







    CRITICAL FLOW:



    1. Query embedding generation



    2. Semantic retrieval (TOP-K similar chunks)



    3. Graph expansion (SIMILAR, MENTIONS, NEXT edges)



    4. Hybrid scoring (embedding similarity + graph connectivity)



    5. Token-limited context selection



    6. Context formatting for LLM







    DESIGN PRINCIPLES:



    - Graph-first: Leverage semantic relationships for intelligent expansion



    - Deterministic: Same query always scores same



    - Efficient: Max depth 2, max 15 chunks, token budgeted



    - Safe: RLS enforced on every query, tenant_id validated everywhere



    """







    def __init__(self, tenant_id: str, db: Optional[AsyncSession] = None):



        """



        Initialize RAG pipeline for tenant.







        Args:



            tenant_id: Tenant UUID (for multi-tenancy enforcement)



            db: Optional PostgreSQL AsyncSession for pgvector search



        """



        self.tenant_id = tenant_id



        self.db = db
        self._kb_metadata = {}



        self.neo4j_repo = Neo4jRepository(tenant_id)



        self.settings = get_settings()



        self.router = QueryRouter()

        from app.core.llm.deepinfra_llm import DeepInfraLLMClient
        self.llm_client = DeepInfraLLMClient()







    async def query(



        self,



        query: str,



        agent_id: str,



        kb_id: str | list[str],



        user_id: Optional[str] = None,
        top_k: int = 3,
        max_depth: int = 2,
        max_tokens: int = 24000,
        kb_context: str = "",
        analysis = None
    ) -> RAGContext:



        """



        Execute RAG query on knowledge base.







        FLOW:



        1. Generate query embedding



        2. Retrieve seed chunks (top-k similarity)



        3. Expand via graph (multi-hop)



        4. Score and rank



        5. Select context within token budget







        Args:



            query: User query string



            agent_id: Agent UUID (ownership validation)



            kb_id: Knowledge Base UUID



            top_k: Initial seed chunks to retrieve



            max_depth: Max graph expansion depth (2 = 2-hop)



            max_tokens: Token budget for context







        Returns:



            RAGContext with ranked chunks and metadata



        """



        logger.info(



            f" RAG Query: agent={agent_id}, kb={kb_id}, query_len={len(query)}"



        )







        # Normalize kb_id to a list for uniform processing



        kb_ids = [kb_id] if isinstance(kb_id, str) else kb_id

        # --- SUPPLEMENTARY PANDAS CSV EXTRACTION ---
        # Removed redundant interception (now handled by service.py hybrid routing)
        supplementary_csv_context = ""
        # ---------------------------------------------

        # STAGE 0: EARLY PARALLEL PRE-REQUISITES
        import asyncio
        from app.modules.rag.orchestrator.query_analyzer import QueryAnalyzer, QueryIntent
        from app.core.embeddings import EmbeddingGenerator
        import time
        start_time = time.time()
        
        if analysis is None:
            analyzer_task = asyncio.create_task(QueryAnalyzer().analyze_query(query, kb_context=kb_context))
        else:
            async def _return_analysis(): return analysis
            analyzer_task = asyncio.create_task(_return_analysis())
        embedding_task = asyncio.create_task(EmbeddingGenerator.generate_embedding_with_usage(query))
        
        # We can also prefetch KB metadata here
        kb_metadata_task = None
        if self.db:
            async def _fetch_metadata():
                try:
                    from app.modules.knowledge_bases.models import KnowledgeBase
                    from sqlalchemy import select
                    from uuid import UUID
                    stmt = select(KnowledgeBase.id, KnowledgeBase.name, KnowledgeBase.total_chunks).where(
                        KnowledgeBase.id.in_([UUID(kbid) if isinstance(kbid, str) else kbid for kbid in kb_ids])
                    )
                    res = await self.db.execute(stmt)
                    for row in res.all():
                        self._kb_metadata[str(row.id)] = {
                            "name": row.name,
                            "total_chunks": row.total_chunks
                        }
                except Exception as e:
                    logger.error(f"Error prefetching KB metadata: {e}")
            kb_metadata_task = asyncio.create_task(_fetch_metadata())

        # Ensure engines are loaded to register them
        import app.modules.rag.engines.financial_engine
        import app.modules.rag.engines.table_engine
        import app.modules.rag.engines.vector_engine
        
        from app.modules.rag.orchestrator.section_ranker import SectionRanker

        total_pipeline_start = time.time()
        # Now wait for analysis to finish (needed for routing)
        analysis = await analyzer_task
        if kb_metadata_task:
            await kb_metadata_task

        # Preserve the original query as an immutable reference throughout this pipeline run
        original_query = query
        corrected = getattr(analysis.metadata, "corrected_query", None)
        logger.info(
            "QUERY_FIDELITY | original=%r | analyzer_corrected=%r",
            original_query,
            corrected,
        )

        if corrected and corrected.lower().strip() != original_query.lower().strip():
            logger.info(
                "Query spell checked: %r -> %r", original_query, corrected
            )
            query = corrected

        # STAGE 0.5: EARLY EXIT FOR TABLE ANALYTICS (Using new QueryAnalyzer)
        if analysis.is_tabular:
            logger.info("   -> Intercepting query for SQL Table Analytics engine!")
            try:
                table_results = await self._execute_table_analytics(query, kb_ids)
                if table_results and "validation error" not in table_results.lower():
                    return RAGContext(
                        query=query,
                        chunks=[],
                        entity_mentions={},
                        total_tokens=0,
                        triplet_context=f"### Table Analytics Results\n\n{table_results}",
                        search_type="TABLE_ANALYTICS"
                    )
                else:
                    logger.warning(f"   -> SQL Table Analytics returned validation error or no results: {table_results}. Falling back to RRF vector search.")
            except Exception as e:
                logger.error(f"   -> SQL Table Analytics failed: {e}. Falling back to RRF vector search.", exc_info=True)
                if self.db:
                    await self.db.rollback()

        # Gather structured queries. If none, default to corrected/original query.
        structured_queries = getattr(analysis.metadata, "structured_queries", [])
        if not structured_queries:
            structured_queries = [query]
            
        table_analytics_attempted = False

        for sq_idx, sq in enumerate(structured_queries):
            logger.info(
                "Running retrieval for structured query variation %d/%d: %r",
                sq_idx + 1,
                len(structured_queries),
                sq
            )
            variation_start_time = time.time()
            current_query = sq

            # Tabular analysis is now handled concurrently in service.py
            extractive_context_text = ""

            # Ensure embedding is generated ONCE for this structured query
            if current_query == original_query:
                query_embedding_val, emb_tokens = await embedding_task
            else:
                from app.core.embeddings import EmbeddingGenerator
                query_embedding_val, emb_tokens = await EmbeddingGenerator.generate_embedding_with_usage(current_query)
            
            analysis.metadata.query_embedding = query_embedding_val
            
            from app.modules.rag.orchestrator.conflict_detector import ConflictDetector
            from app.modules.rag.telemetry import TelemetryLogger

            # Define RRF parameters
            RRF_K = 60
            WEIGHT_GRAPH = 1.5
            WEIGHT_KEYWORD = 1.0
            WEIGHT_VECTOR = 1.0
            TOP_N = 15

            # Convert analysis metadata to dictionary for RetrievalTasks
            meta_dict = {}
            if analysis and hasattr(analysis, "metadata") and analysis.metadata:
                if hasattr(analysis.metadata, "model_dump"):
                    meta_dict = analysis.metadata.model_dump()
                elif hasattr(analysis.metadata, "dict"):
                    meta_dict = analysis.metadata.dict()
                elif isinstance(analysis.metadata, dict):
                    meta_dict = analysis.metadata
                else:
                    meta_dict = vars(analysis.metadata)
            
            # Fix 2: Explicitly inject top-level AnalysisResult fields that were dropped
            if analysis:
                meta_dict["is_tabular"] = getattr(analysis, "is_tabular", False)
                meta_dict["intent"] = getattr(analysis, "intent", None)
                meta_dict["confidence"] = getattr(analysis, "confidence", 0.0)
                meta_dict["reasoning"] = getattr(analysis, "reasoning", "")

            # 0. Section Ranking
            async def _run_section_ranking():
                try:
                    from app.modules.rag.engines.vector_engine import VectorEngine
                    from app.modules.rag.orchestrator.section_ranker import SectionRanker
                    from app.modules.rag.schemas import RetrievalTask
                    
                    v_engine = VectorEngine(self.tenant_id, self.neo4j_repo, getattr(self, "db", None))
                    dummy_task = RetrievalTask(
                        task_id="section_ranking",
                        query=current_query,
                        metadata_filters=meta_dict,
                        top_k=50,
                        target_section_ids=[]
                    )
                    candidate_sections = await v_engine.get_candidate_sections(dummy_task, kb_ids)
                    if not candidate_sections:
                        return []
                        
                    ranker = SectionRanker()
                    ranked_sections = ranker.rank_sections(current_query, candidate_sections, top_k=5)
                    logger.info(f"SectionRanker selected {len(ranked_sections)} candidate sections out of {len(candidate_sections)}")
                    
                    # Implement fallback logic:
                    if not ranked_sections:
                        return []
                        
                    top_score = ranked_sections[0].get("rank_score", 0.0)
                    if top_score < 2.0:
                        logger.info(f"[FALLBACK] SectionRanker top score ({top_score}) < 2.0. Falling back to full-KB search.")
                        return []
                        
                    if len(ranked_sections) > 1:
                        second_score = ranked_sections[1].get("rank_score", 0.0)
                        gap = top_score - second_score
                        if gap < (0.3 * top_score):
                            logger.info(f"[FALLBACK] SectionRanker score gap between {top_score} and {second_score} is < 30%. Falling back to full-KB search.")
                            return []

                    return [s.get("section_id") for s in ranked_sections if s.get("section_id")]
                except Exception as e:
                    logger.warning(f"Section ranking failed (non-blocking): {e}")
                    return []

            # 1. Graph Traversal
            async def _run_triplet_search(target_sections=None):
                if not self.settings.use_triplet_extraction:
                    return []
                try:
                    from app.core.triplet_extractor import TripletRetriever
                    retriever = TripletRetriever(self.tenant_id)
                    return await retriever.search_triplets(
                        query_embedding=query_embedding_val,
                        kb_ids=kb_ids,
                        top_k=20,
                        target_sections=target_sections,
                    )
                except Exception as e:
                    logger.warning(f"Triplet retrieval failed (non-blocking): {e}")
                    return []

            # 2. Neo4j Keyword Search
            async def _run_keyword_search(target_sections=None):
                try:
                    keywords = getattr(analysis.metadata, "keywords", [])
                    if not keywords:
                        # Extract simple words if no keywords provided
                        keywords = [w for w in current_query.split() if len(w) > 3]
                    if not keywords:
                        return []
                    
                    cypher = """
                    MATCH (kb:KnowledgeBase)-[:HAS_CHUNK]->(c:Chunk)
                    WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
                    """
                    if target_sections:
                        cypher += " AND c.section IN $target_sections "
                    
                    cypher += """
                    AND any(word IN $keywords WHERE toLower(c.text) CONTAINS toLower(word))
                    RETURN DISTINCT c.id as section_id
                    LIMIT 50
                    """
                    
                    params = {"kb_ids": kb_ids, "tenant_id": self.tenant_id, "keywords": keywords}
                    if target_sections:
                        params["target_sections"] = target_sections
                        
                    results = await self.neo4j_repo.execute_read(cypher, params)
                    return [r.get("section_id") for r in results] if results else []
                except Exception as e:
                    logger.warning(f"Keyword search failed (non-blocking): {e}")
                    return []

            # 3. pgvector Full-KB Semantic Search
            async def _run_vector_search(target_sections=None):
                try:
                    from app.modules.rag.engines.vector_engine import VectorEngine
                    from app.modules.rag.schemas import RetrievalTask
                    vector_engine = VectorEngine(self.tenant_id, self.neo4j_repo, getattr(self, "db", None))
                    
                    dummy_task = RetrievalTask(
                        task_id="full_kb_search",
                        query=current_query,
                        metadata_filters=meta_dict,
                        top_k=TOP_N,
                        target_section_ids=target_sections or []
                    )
                    return await vector_engine.retrieve(dummy_task, kb_ids)
                except Exception as e:
                    logger.warning(f"Vector search failed (non-blocking): {e}")
                    return []

            # Launch sequentially then concurrently (2-wave design)
            engine_start = time.time()
            
            # WAVE 1
            section_res = await _run_section_ranking()
            target_sections = section_res if isinstance(section_res, list) else []
            
            # WAVE 2
            triplet_res, keyword_res, vector_res = await asyncio.gather(
                _run_triplet_search(target_sections),
                _run_keyword_search(target_sections),
                _run_vector_search(target_sections),
                return_exceptions=True
            )
            engine_time = time.time() - engine_start

            # Handle exceptions cleanly
            if isinstance(triplet_res, Exception): triplet_res = []
            if isinstance(keyword_res, Exception): keyword_res = []
            if isinstance(vector_res, Exception): vector_res = []

            logger.info(f"[RRF_FLOW_MARKER] RRF Sources returned: Graph={len(triplet_res)}, Keyword={len(keyword_res)}, Vector={len(vector_res)}")

            # --- RECIPROCAL RANK FUSION ---
            logger.info("[RRF_FLOW_MARKER] Starting Reciprocal Rank Fusion...")
            fused_scores = {}
            
            # Graph scoring
            for rank, t in enumerate(triplet_res):
                cid = t.get("chunk_id")
                if not cid: continue
                score = WEIGHT_GRAPH / (RRF_K + rank + 1)
                fused_scores[cid] = fused_scores.get(cid, 0.0) + score

            # Keyword scoring
            for rank, cid in enumerate(keyword_res):
                if not cid: continue
                score = WEIGHT_KEYWORD / (RRF_K + rank + 1)
                fused_scores[cid] = fused_scores.get(cid, 0.0) + score

            # Vector scoring
            vector_chunk_map = {}
            for rank, chunk in enumerate(vector_res):
                cid = chunk.chunk_id
                vector_chunk_map[cid] = chunk
                score = WEIGHT_VECTOR / (RRF_K + rank + 1)
                fused_scores[cid] = fused_scores.get(cid, 0.0) + score

            # Apply SectionRanker boost post-hoc
            boosted_count = 0
            SECTION_BOOST_WEIGHT = 2.0  # Configurable RRF weight bonus
            if section_res:
                target_sections_set = set(section_res)
                for cid in fused_scores.keys():
                    chunk_obj = vector_chunk_map.get(cid)
                    c_section = None
                    if chunk_obj:
                        c_section = getattr(chunk_obj, "section_id", None) or getattr(chunk_obj, "section", None)
                    if cid in target_sections_set or c_section in target_sections_set:
                        fused_scores[cid] += SECTION_BOOST_WEIGHT
                        boosted_count += 1
            
            logger.info(f"[RRF_FLOW_MARKER] Target section IDs from SectionRanker: {section_res}. Boost applied to {boosted_count} chunks.")

            # Sort top N chunks
            sorted_fused = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)[:TOP_N]
            top_cids = [cid for cid, score in sorted_fused]
            logger.info(f"[RRF_FLOW_MARKER] Fusion complete. Top {len(top_cids)} chunk IDs selected.")
            
            # Fetch missing chunks from postgres
            final_chunks = []
            missing_cids = [cid for cid in top_cids if cid not in vector_chunk_map]
            
            if missing_cids and getattr(self, "db", None):
                from app.modules.knowledge_bases.models import DocumentChunk
                from sqlalchemy import select
                from uuid import UUID
                
                try:
                    uuid_list = []
                    for cid in missing_cids:
                        try:
                            uuid_list.append(UUID(str(cid)))
                        except:
                            pass
                    
                    if uuid_list:
                        stmt = select(DocumentChunk).where(DocumentChunk.id.in_(uuid_list))
                        result = await self.db.execute(stmt)
                        for row in result.scalars():
                            c_id = str(row.id)
                            # Create RetrievedChunk object
                            from app.modules.rag.pipeline import RetrievedChunk
                            s3_path = row.metadata_json.get("s3_path") if row.metadata_json else None
                            rc = RetrievedChunk(
                                chunk_id=c_id,
                                text=row.text,
                                kb_id=str(row.kb_id),
                                position=row.chunk_index,
                                embedding_similarity=0.0,
                                graph_score=0.0,
                                hybrid_score=0.0, # Will be set next
                                reason="RRF_MERGE",
                                source=s3_path or f"DocumentChunk {row.chunk_index}",
                                s3_path=s3_path,
                                engine_name="hybrid_rrf",
                                section="Unknown",
                                ontology_node=None
                            )
                            vector_chunk_map[c_id] = rc
                except Exception as e:
                    logger.error(f"Failed to fetch missing chunks: {e}")

            # Build final chunk list and assign hybrid_score
            for rank, (cid, score) in enumerate(sorted_fused):
                if cid in vector_chunk_map:
                    rc = vector_chunk_map[cid]
                    # Map RRF rank to a safe hybrid_score range [0.85, 0.99] so service.py doesn't drop them
                    rc.hybrid_score = 0.99 - (rank * 0.01)
                    final_chunks.append(rc)
                    
            if final_chunks:
                logger.info(f"RRF successfully aggregated {len(final_chunks)} chunks. Returning early.")
                
                triplet_context_str = ""
                if triplet_res:
                    from app.core.triplet_extractor import TripletRetriever
                    retriever = TripletRetriever(self.tenant_id)
                    triplet_context_str = retriever.format_triplets_as_context(triplet_res)

                rag_context = RAGContext(
                    query=original_query,
                    chunks=final_chunks,
                    entity_mentions={},
                    total_tokens=sum(len(c.text.split()) for c in final_chunks),
                    triplet_context=extractive_context_text + triplet_context_str,
                    triplets=triplet_res,
                    search_type=analysis.intent.name
                )
                
                # Pre-generation conflict detection
                detector = ConflictDetector()
                conflict_res = await detector.detect_conflicts(rag_context)
                if conflict_res.get("conflict_found"):
                    logger.warning(f"Conflict detected in evidence: {conflict_res.get('explanation')}")
                    rag_context.triplet_context += f"\n\n### SYSTEM WARNING: CONFLICTING EVIDENCE DETECTED\n{conflict_res.get('explanation')}\nExplicitly address and resolve this conflict in your response based on the provided snippets."
                    
                # Telemetry logging
                TelemetryLogger.log_query(
                    query=original_query,
                    intent=analysis.intent.name,
                    planner_latency=0.0,
                    engine_latency=engine_time,
                    coverage_score=1.0,
                    conflict_found=conflict_res.get("conflict_found", False),
                    token_usage=rag_context.total_tokens,
                    evidence_count=len(final_chunks)
                )
                    
                variation_elapsed = time.time() - variation_start_time
                pipeline_total_elapsed = time.time() - total_pipeline_start
                logger.info(f"TELEMETRY: Structured query variation {sq_idx + 1} completed in {variation_elapsed:.2f}s")
                logger.info(f"TELEMETRY: Pipeline total retrieval phase completed in {pipeline_total_elapsed:.2f}s")
                
                return rag_context
            
            variation_elapsed = time.time() - variation_start_time
            logger.warning(
                "TELEMETRY: Structured query %d yielded no final chunks after %s aggregation in %.2fs. "
                "Moving to next variation.",
                sq_idx + 1,
                "RRF",
                variation_elapsed
            )

        # Fallback to standard router using the first structured query or original query if all fail
        fallback_query = structured_queries[0] if structured_queries else original_query
        logger.warning("All structured queries failed. Falling back to standard router with query: %r", fallback_query)
        route_result = await self.router.route_query(fallback_query, tenant_id=str(self.tenant_id))
        search_type = route_result.intent
        
        rewritten_data = route_result.rewritten or {}
        extracted_keywords = rewritten_data.get("keywords", [])
        if extracted_keywords:
            split_keywords = []
            for kw in extracted_keywords:
                for word in kw.split():
                    cleaned = "".join(c for c in word if c.isalnum() or c in "-.")
                    if cleaned:
                        split_keywords.append(cleaned)
            # Fetch dynamic noisy words from database (with caching)
            noisy_words_scores = {}
            now_time = time.time()
            kbs_to_fetch = []
            
            for kbid in kb_ids:
                if kbid in _KB_NOISY_WORDS_CACHE:
                    cached = _KB_NOISY_WORDS_CACHE[kbid]
                    if now_time < cached["expiry"]:
                        for word_data in cached["data"]:
                            word = word_data["word"]
                            score = word_data["score"]
                            noisy_words_scores[word] = max(noisy_words_scores.get(word, 0.0), score)
                        continue
                kbs_to_fetch.append(kbid)
                
            if kbs_to_fetch and self.db:
                try:
                    from sqlalchemy import select
                    from app.modules.knowledge_bases.models import KnowledgeBase
                    
                    stmt = select(KnowledgeBase.id, KnowledgeBase.noisy_words).where(
                        KnowledgeBase.id.in_(kbs_to_fetch),
                        KnowledgeBase.tenant_id == self.tenant_id
                    )
                    res = await self.db.execute(stmt)
                    rows = res.fetchall()
                    
                    for kb_id_val, noisy_words_val in rows:
                        kb_id_str = str(kb_id_val)
                        words_list = noisy_words_val or []
                        _KB_NOISY_WORDS_CACHE[kb_id_str] = {
                            "data": words_list,
                            "expiry": now_time + KB_NOISY_WORDS_CACHE_TTL
                        }
                        for word_data in words_list:
                            word = word_data["word"]
                            score = word_data["score"]
                            noisy_words_scores[word] = max(noisy_words_scores.get(word, 0.0), score)
                except Exception as db_err:
                    logger.error(f"Error fetching noisy words for KBs {kbs_to_fetch}: {db_err}")
            
            # Fail-safe static fallback if no dynamic noisy words are computed/available yet
            if not noisy_words_scores:
                noisy_words_scores = {
                    "report": 0.99, "reports": 0.99,
                    "financial": 0.98,
                    "company": 0.97, "corporation": 0.97, "inc": 0.97,
                    "statement": 0.91, "statements": 0.91,
                    "sheet": 0.91, "sheets": 0.91,
                    "annual": 0.83,
                    "quarter": 0.80, "quarters": 0.80,
                    "period": 0.75, "periods": 0.75,
                    "months": 0.70,
                    "ended": 0.65,
                    "form": 0.60,
                    "10-q": 0.55, "10-k": 0.55,
                    "disclose": 0.50, "disclosed": 0.50, "disclosures": 0.50,
                    "performance": 0.45,
                    "item": 0.40, "items": 0.40,
                    "apple": 0.30, "aapl": 0.30
                }

            # 1. ENTITY PROTECTION: Extract all entities from the route result to protect them
            entities_to_protect = set()
            for entity in (rewritten_data.get("entities", []) + getattr(route_result, "requested_entities", [])):
                for part in str(entity).split():
                    cleaned_part = "".join(c for c in part if c.isalnum() or c in "-.").lower()
                    if cleaned_part:
                        entities_to_protect.add(cleaned_part)

            # 2. NOISY WORD CANDIDATE DETECTION & SCORES COLLECTION
            noisy_candidates = []
            for idx, k in enumerate(split_keywords):
                k_lower = k.lower()
                # Keyword is a noise candidate ONLY if it exists in score map and is NOT protected as an entity
                if k_lower in noisy_words_scores and k_lower not in entities_to_protect:
                    noisy_candidates.append((idx, k_lower, noisy_words_scores[k_lower]))

            # 3. TOP-3 NOISY-WORD REMOVAL: Rank candidates by noise score and remove top 3
            # Sort by score in descending order (highest noise first)
            noisy_candidates.sort(key=lambda x: x[2], reverse=True)
            to_remove_indices = {candidate[0] for candidate in noisy_candidates[:3]}

            filtered_keywords = [
                k for idx, k in enumerate(split_keywords)
                if idx not in to_remove_indices
            ]

            # 4. FAIL-SAFE FALLBACK: If the list is empty after filtering, restore original keywords
            if not filtered_keywords:
                filtered_keywords = split_keywords

            extracted_keywords = list(dict.fromkeys(filtered_keywords))
        
        logger.info(f" Query Router selected strategy: {search_type.name} (Confidence: {route_result.confidence})")
        if extracted_keywords:
            logger.info(f" Query Rewriter extracted keywords: {extracted_keywords}")





        # Old Table Analytics block removed since it is now executed before RRF

        # STAGE 0.6: HYBRID CONTEXT INJECTION (Extractive DB + Vector Search)
        extractive_context_text = ""
        if search_type in [SearchType.EXTRACTIVE, SearchType.CHUNK_SEARCH]:
            logger.info("   -> Checking Extractive DB for any structured identifiers matching the query.")
            try:
                # We do not use a hardcoded list of entities anymore.
                # Instead of string-matching valid_entities, we let the ExtractiveEngine do a dynamic lookup
                # across all available entity types in the DB that might match the query keywords!
                from .extractive_engine import ExtractiveEngine
                engine = ExtractiveEngine(self.db, str(self.tenant_id))
                
                from sqlalchemy import text
                kb_ids_formatted = "','".join(kb_ids)
                stmt = text(
                    f"SELECT DISTINCT de.entity_type, de.entity_value, de.page_number, de.entity_status, kb.name AS kb_name "
                    f"FROM document_entities de "
                    f"JOIN knowledge_bases kb ON de.document_id = kb.id "
                    f"WHERE de.document_id IN ('{kb_ids_formatted}')"
                )
                
                result = await self.db.execute(stmt)
                db_entities = result.fetchall()
                
                matched_types = set()
                
                authoritative_entities_list = []
                q_lower = query.lower()
                
                logger.info(f"   [DEBUG] q_lower: '{q_lower}'")
                logger.info(f"   [DEBUG] fetched {len(db_entities)} rows from DB")
                
                for row in db_entities:
                    e_type = row.entity_type.lower().replace('_', ' ')
                    e_type_normalized = row.entity_type.lower().replace(' ', '_')
                    logger.info(f"   [DEBUG] checking row: type='{e_type}', val='{row.entity_value}'")
                    
                    is_requested = False
                    if route_result and route_result.requested_entities:
                        is_requested = any(req.lower() == e_type_normalized for req in route_result.requested_entities)
                        
                    if is_requested or e_type in q_lower or str(row.entity_value).lower() in q_lower:
                        logger.info(f"   [DEBUG] MATCHED: {e_type}")
                        matched_types.add(e_type)
                        trust_score = 1.0 if row.entity_status == "VERIFIED" else 0.8
                        authoritative_entities_list.append({
                            "entity_type": row.entity_type,
                            "value": row.entity_value,
                            "source": row.kb_name,
                            "page": row.page_number,
                            "confidence": trust_score
                        })
                
                if authoritative_entities_list:
                    logger.info(f"   -> Found {len(authoritative_entities_list)} authoritative structured entities.")
                    
                    # Deterministic completeness check based on intent
                    requested_entities = route_result.requested_entities or []
                    req_set = {str(r).lower().replace(' ', '_') for r in requested_entities}
                    found_set = {str(mt).lower().replace(' ', '_') for mt in matched_types}
                    
                    if req_set:
                        missing_entities = req_set - found_set
                        if not missing_entities:
                            is_complete = True
                        else:
                            is_complete = False
                            logger.info(f"   -> Missing requested entities: {missing_entities}")
                    else:
                        # Fallback if LLM didn't specify requested_entities
                        is_complete = False
                        
                    is_group_match = route_result is not None and bool(route_result.requested_groups)
                    if is_complete or (is_group_match and len(authoritative_entities_list) > 0):
                        logger.info("   -> Structured DB satisfies intent (complete or group match). EARLY EXIT.")
                        return RAGContext(
                            query=query,
                            chunks=[],
                            entity_mentions={},
                            total_tokens=0,
                            triplet_context="",
                            search_type=search_type.name,
                            authoritative_entities=authoritative_entities_list
                        )
                    else:
                        logger.info("   -> Structured DB partially satisfies query. Proceeding to Hybrid Vector Search.")
                        # We do NOT inject this into the triplet context. It will be system-injected in service.py
                        search_type = SearchType.CHUNK_SEARCH
                        # We must attach it to the pipeline context state so it can be passed up
                        # We can store it in a local variable and pass it to RAGContext later
                else:
                    search_type = SearchType.CHUNK_SEARCH
                
            except Exception as e:
                logger.error(f"   -> Extractive Engine failed: {e}. Falling back to standard vector search.", exc_info=True)
                search_type = SearchType.CHUNK_SEARCH








        # STAGE 0.7: GRAPH EXACT MATCHING & HIERARCHY TRAVERSAL
        hierarchy_context = ""
        if search_type in [SearchType.EXTRACTIVE, SearchType.CHUNK_SEARCH] and route_result and route_result.requested_entities:
            logger.info("   -> Checking Neo4j Graph for Exact Matches and Hierarchy.")
            try:
                structured_ids = route_result.requested_entities
                
                for sid in structured_ids:
                    # Query Neo4j for node and its subgraph (HAS_SECTION, HAS_TEXT, HAS_TABLE)
                    cypher = """
                    MATCH (root {tenant_id: $tenant_id, id: $sid})
                    OPTIONAL MATCH path = (root)-[:HAS_SECTION|HAS_SUBSECTION|HAS_TEXT|HAS_TABLE|HAS_ROW|HAS_IDENTIFIER*0..3]->(leaf)
                    RETURN root, collect(nodes(path)) as descendants
                    """
                    results = await self.neo4j_repo.execute_read(cypher, {"sid": sid})
                    if results:
                        for res in results:
                            root_node = res.get("root", {})
                            if root_node:
                                hierarchy_context += f"\n--- Exact Match: {root_node.get('title', sid)} ---\n"
                                hierarchy_context += f"Type: {root_node.get('type')}\n"
                                if root_node.get('content'):
                                    hierarchy_context += f"{root_node.get('content')}\n"
                                    
                            descendants = res.get("descendants", [])
                            for path_nodes in descendants:
                                if path_nodes:
                                    for d in path_nodes:
                                        if d.get("id") != root_node.get("id"):
                                            d_type = d.get('type', '')
                                            d_title = d.get('title', '')
                                            d_content = d.get('content', '')
                                            if d_title or d_content:
                                                hierarchy_context += f"[{d_type}] {d_title}: {d_content}\n"
                
                if hierarchy_context:
                    logger.info("   -> Exact match found in graph. Returning Graph Context directly.")
                    return RAGContext(
                        query=query,
                        chunks=[],
                        entity_mentions={},
                        total_tokens=0,
                        triplet_context=f"### Structural Graph Hierarchy\n\n{hierarchy_context}",
                        search_type=search_type.name,
                        authoritative_entities=authoritative_entities_list if 'authoritative_entities_list' in locals() else []
                    )
            except Exception as e:
                logger.error(f"   -> Graph Exact Match failed: {e}")

        # Dynamically adjust retrieval parameters based on the chosen strategy



        if search_type == SearchType.RECENT_EMAILS:
            logger.info("   -> Optimizing for RECENT_EMAILS: Bypassing vector search, fetching latest directly from Neo4j.")
            neo_query = """
            MATCH (kb:KnowledgeBase)-[:HAS_CHUNK]->(c:Chunk)-[:EXTRACTED_FROM]->(e:Email)
            WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
            RETURN c.id as chunk_id, c.text as text, c.position as position, c.kb_id as kb_id, e.date as email_date, e.subject as source
            ORDER BY e.date DESC
            LIMIT 10
            """
            try:
                results = await self.neo4j_repo.execute_read(
                    neo_query,
                    {
                        "kb_ids": kb_ids, 
                        "tenant_id": self.tenant_id
                    },
                )
                if results:
                    chunks = []
                    for idx, res in enumerate(results):
                        chunks.append(RetrievedChunk(
                            chunk_id=res["chunk_id"],
                            text=f"Date: {res['email_date']}\nSubject: {res['source']}\nBody: {res['text']}",
                            kb_id=res["kb_id"],
                            position=res["position"],
                            embedding_similarity=1.0,
                            graph_score=1.0,
                            hybrid_score=1.0 - (idx * 0.01),
                            reason="RECENT_EMAIL",
                            source=res["source"]
                        ))
                    
                    return RAGContext(
                        query=query, 
                        chunks=chunks, 
                        entity_mentions={}, 
                        total_tokens=len(" ".join([c.text for c in chunks]).split()) * 1.5,
                        personal_memories=[],
                        search_type=search_type.name
                    )
            except Exception as e:
                logger.error(f" Failed to fetch recent emails: {e}")
                pass

        if search_type == SearchType.CHUNK_SEARCH:



            max_depth = 0  # No graph expansion needed for direct facts; pure vector



            logger.info("   -> Optimizing for CHUNK_SEARCH: Disabling graph expansion.")



        elif search_type == SearchType.GRAPH_SUMMARY:



            top_k = 20  # Broader initial sweep for summary



            max_tokens = max_tokens + 1000  # Expand token budget



            logger.info("   -> Optimizing for GRAPH_SUMMARY: Expanding top_k and token budget.")



        elif search_type == SearchType.CHAIN_OF_THOUGHT:



            max_depth = max(max_depth, 3)  # Deeper traversal for complex reasoning



            logger.info("   -> Optimizing for CHAIN_OF_THOUGHT: Increasing graph expansion depth.")



        elif search_type == SearchType.MEMORY_ONLY:



            # For memory-only queries, we prioritize consolidated triplets from chat



            top_k = 5



            max_depth = 1



            logger.info("   -> Optimizing for MEMORY_ONLY: Targeting consolidated chat facts.")



        elif search_type == SearchType.ENTITY_CONNECTION:



            max_depth = max(max_depth, 2)



            top_k = 20 # Broader search to find the bridge



            logger.info("   -> Optimizing for ENTITY_CONNECTION: Broadening search for relationship paths.")



        elif search_type == SearchType.SOCIAL:



            # For social interactions, we don't need many chunks, but we want to allow conversation



            top_k = 1



            max_depth = 0



            logger.info("   -> Optimizing for SOCIAL: Enabling conversational mode.")







        # STEP 1: GENERATE QUERY EMBEDDING



        logger.debug("Step 1: Generating query embedding...")



        if 'analysis' in locals() and analysis and analysis.metadata and analysis.metadata.query_embedding:
            query_embedding = analysis.metadata.query_embedding
            emb_tokens = getattr(locals().get('emb_tokens'), 'emb_tokens', 10)
        else:
            from app.core.embeddings import EmbeddingGenerator
            query_embedding, emb_tokens = await EmbeddingGenerator.generate_embedding_with_usage(query)



        logger.debug(f" Query embedding generated ({len(query_embedding)} dims)")







        # STEP 1.5: PERSONAL MEMORY RETRIEVAL (Phase 5  Feature-Flagged)



        personal_memories = []



        if self.settings.use_personal_memory and user_id:



            try:



                from app.core.memory.personalization import PersonalMemoryService



                pm_service = PersonalMemoryService(self.tenant_id)



                personal_memories = await pm_service.get_relevant_memories(



                    user_id=user_id,



                    query_embedding=query_embedding,



                    top_k=3



                )



                if personal_memories:



                    logger.info(f" Retrieved {len(personal_memories)} personal memories for user {user_id[:8]}")



            except Exception as e:



                logger.warning(f" Personal memory retrieval failed (non-blocking): {e}")







        # STEP 2: RETRIEVE SEED CHUNKS (SEMANTIC SIMILARITY)



        logger.info(f"Step 2: Retrieving top-{top_k} seed chunks for KBs {kb_ids}...")



        seed_chunks = await self._retrieve_seed_chunks(
            kb_ids=kb_ids,
            query_embedding=query_embedding,
            top_k=top_k,
            query=query,
            exact_terms=extracted_keywords,
        )



        



        if not seed_chunks:



            # DIAGNOSTIC: Check if any chunks exist at all



            all_chunks_query = "MATCH (kb:KnowledgeBase)-[:HAS_CHUNK]->(c) WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id RETURN count(c) as count"



            count_res = await self.neo4j_repo.execute_read(



                all_chunks_query, 



                {"kb_ids": kb_ids, "tenant_id": self.tenant_id}



            )



            chunk_count = count_res[0]["count"] if count_res else 0



            



            logger.warning(f" No seed chunks found! Total chunks in DB for this KB: {chunk_count}")



            



            # If it's a SOCIAL query, we don't fail, we just continue to allow conversational response



            if search_type == SearchType.SOCIAL:



                logger.info(" Continuing with empty context for SOCIAL query.")



                return RAGContext(



                    query=query, 



                    chunks=[], 



                    entity_mentions={}, 



                    total_tokens=0,



                    personal_memories=personal_memories,



                    search_type=search_type.name



                )







            return RAGContext(



                query=query, 



                chunks=[], 



                entity_mentions={}, 



                total_tokens=0,



                personal_memories=personal_memories,



                search_type=search_type.name



            )







        logger.info(f" Retrieved {len(seed_chunks)} seed chunks")







        # STEP 3: EXPAND VIA GRAPH (MULTI-HOP)



        logger.debug(f"Step 3: Expanding graph (max_depth={max_depth})...")



        seed_chunk_ids = {chunk["chunk_id"] for chunk in seed_chunks}



        expanded_chunks = await self._expand_via_graph(



            seed_chunk_ids=seed_chunk_ids,



            kb_ids=kb_ids,



            max_depth=max_depth,



        )



        logger.info(



            f" Graph expansion: {len(seed_chunk_ids)} seed  {len(expanded_chunks)} total chunks"



        )







        # STEP 4: SCORE AND RANK (HYBRID SCORING)



        logger.debug("Step 4: Scoring and ranking chunks...")



        scored_chunks = await self._score_chunks(



            seed_chunks=seed_chunks,



            expanded_chunks=expanded_chunks,



            query_embedding=query_embedding,

            search_type=search_type,



        )



        logger.info(f" Scored {len(scored_chunks)} chunks")

        # Retrieve and inject reconstructed tables matching query keywords
        try:
            table_chunks = await self._retrieve_reconstructed_tables(
                keywords=extracted_keywords,
                kb_ids=kb_ids
            )
            if table_chunks:
                logger.info(f"   -> Injecting {len(table_chunks)} reconstructed tables into context.")
                scored_chunks.extend(table_chunks)
                # Sort scored_chunks again by hybrid_score descending
                scored_chunks.sort(key=lambda x: x.hybrid_score, reverse=True)
        except Exception as e:
            logger.error(f"Failed to inject reconstructed tables: {e}", exc_info=True)







        # STEP 5: SELECT CONTEXT (TOKEN BUDGET)



        logger.debug(f"Step 5: Selecting context (token_budget={max_tokens})...")



        context_chunks = self._select_context(



            scored_chunks=scored_chunks,



            max_tokens=max_tokens,



        )



        logger.info(



            f" Selected {len(context_chunks)} chunks for context "



            f"({context_chunks[-1].hybrid_score:.3f} - {context_chunks[0].hybrid_score:.3f} score range)"



        )







        # STEP 6: EXTRACT ENTITY MENTIONS



        logger.debug("Step 6: Extracting entity mentions...")



        entity_mentions = await self._extract_entity_mentions(



            chunk_ids={chunk.chunk_id for chunk in context_chunks}



        )



        logger.info(f" Extracted {len(entity_mentions)} unique entities")







        # STEP 7: TRIPLET RETRIEVAL (Phase 4A  Feature-Flagged)



        # Enriches context with knowledge graph relationships



        # SAFETY: Independent step  if disabled or fails, pipeline continues



        triplet_context = ""



        if self.settings.use_triplet_extraction:



            try:



                from app.core.triplet_extractor import TripletRetriever



                retriever = TripletRetriever(self.tenant_id)



                relevant_triplets = await retriever.search_triplets(



                    query_embedding=query_embedding,



                    kb_ids=kb_ids,



                    top_k=self.settings.triplet_retrieval_top_k,



                )



                if relevant_triplets:



                    triplet_context = retriever.format_triplets_as_context(relevant_triplets)



                    logger.info(f" Retrieved {len(relevant_triplets)} relevant triplets")



            except Exception as e:



                logger.warning(f" Triplet retrieval failed (non-blocking): {e}")








        # STEP 5.5: BULK RESOLVE CHUNK DETAILS (text, kb_id, position, source)
        # Expanded chunks start with empty text; pgvector chunks lack source field in Postgres.
        needed_chunk_ids = [c.chunk_id for c in context_chunks]
        if needed_chunk_ids:
            # 1. Bulk query from PostgreSQL to fetch full chunk texts, kb_ids, and indices
            if self.db:
                try:
                    from sqlalchemy import select
                    from app.modules.knowledge_bases.models import DocumentChunk, KnowledgeBase
                    uuid_chunk_ids = []
                    for cid in needed_chunk_ids:
                        if not cid.startswith("table-"):
                            try:
                                uuid_chunk_ids.append(UUID(cid))
                            except ValueError:
                                pass
                                
                    stmt = select(DocumentChunk, KnowledgeBase.parsed_path, KnowledgeBase.name, KnowledgeBase.s3_path).outerjoin(
                        KnowledgeBase, DocumentChunk.kb_id == KnowledgeBase.id
                    ).where(DocumentChunk.id.in_(uuid_chunk_ids))
                    res = await self.db.execute(stmt)
                    
                    db_chunks = {}
                    for db_c, parsed_path, kb_name, s3_path in res.all():
                        db_chunks[str(db_c.id)] = (db_c, parsed_path, kb_name, s3_path)
                    
                    for chunk in context_chunks:
                        if chunk.chunk_id in db_chunks:
                            db_c, parsed_path, kb_name, s3_path = db_chunks[chunk.chunk_id]
                            if not chunk.text:
                                chunk.text = db_c.text or ""
                            if not chunk.kb_id:
                                chunk.kb_id = str(db_c.kb_id)
                            if chunk.position == 0:
                                chunk.position = db_c.chunk_index
                                
                            # Overwrite default "DocumentChunk X" source with actual filename
                            if not chunk.source or str(chunk.source).startswith("DocumentChunk"):
                                chunk.source = s3_path or kb_name or chunk.source
                                chunk.s3_path = s3_path
                                
                            if parsed_path:
                                if parsed_path.endswith(".html"):
                                    chunk.content_type = "text/html"
                                elif parsed_path.endswith(".md"):
                                    chunk.content_type = "text/markdown"
                                else:
                                    chunk.content_type = "text/plain"
                except Exception as db_err:
                    logger.error(f"Failed to bulk fetch chunk details from PostgreSQL: {db_err}")

            # 2. Bulk query from Neo4j to fetch source metadata and fallback values
            try:
                neo_query = """
                MATCH (c:Chunk {tenant_id: $tenant_id})
                WHERE c.id IN $chunk_ids
                OPTIONAL MATCH (kb:KnowledgeBase {tenant_id: $tenant_id})-[:HAS_CHUNK]->(c)
                RETURN c.id as chunk_id, c.text as text, c.kb_id as kb_id, c.position as position, COALESCE(kb.s3_path, c.source, kb.name) as source, kb.parsed_path as parsed_path, kb.s3_path as s3_path
                """
                neo_res = await self.neo4j_repo.execute_read(neo_query, {
                    "chunk_ids": needed_chunk_ids,
                    "tenant_id": self.tenant_id
                })
                neo_chunks = {r["chunk_id"]: r for r in neo_res}
                
                for chunk in context_chunks:
                    if chunk.chunk_id in neo_chunks:
                        n_c = neo_chunks[chunk.chunk_id]
                        if not chunk.text and n_c.get("text"):
                            chunk.text = n_c["text"]
                        if not chunk.kb_id and n_c.get("kb_id"):
                            chunk.kb_id = n_c["kb_id"]
                        if chunk.position == 0 and n_c.get("position") is not None:
                            chunk.position = n_c["position"]
                        neo_source = n_c.get("source")
                        kb_name = self._kb_metadata.get(chunk.kb_id, {}).get("name") if chunk.kb_id else None
                        s3_path = n_c.get("s3_path")
                        if not neo_source or str(neo_source).startswith("DocumentChunk"):
                            chunk.source = s3_path or kb_name or neo_source
                        else:
                            chunk.source = neo_source
                        chunk.s3_path = s3_path
                        parsed_path = n_c.get("parsed_path")
                        if parsed_path:
                            if parsed_path.endswith(".html"):
                                chunk.content_type = "text/html"
                            elif parsed_path.endswith(".md"):
                                chunk.content_type = "text/markdown"
                            else:
                                chunk.content_type = "text/plain"

            except Exception as neo_err:
                logger.error(f"Failed to bulk fetch chunk details from Neo4j: {neo_err}")


        # Calculate total tokens in context



        total_tokens = sum(



            len(chunk.text.split()) * 1.3 for chunk in context_chunks



        )  # Rough estimate



        if triplet_context:



            total_tokens += len(triplet_context.split()) * 1.3







        # Merge Hybrid Context
        final_triplet_context = triplet_context or ""
        if 'extractive_context_text' in locals() and extractive_context_text:
            final_triplet_context = extractive_context_text + final_triplet_context
            

            
        return RAGContext(

            query=query,



            chunks=context_chunks,



            entity_mentions=entity_mentions,



            total_tokens=int(total_tokens),



            triplet_context=final_triplet_context,



            triplets=relevant_triplets if 'relevant_triplets' in locals() else None,

            search_type=search_type.name,

            authoritative_entities=authoritative_entities_list if 'authoritative_entities_list' in locals() else None,

            personal_memories=personal_memories,

            query_embedding_tokens=emb_tokens

        )







    async def _retrieve_seed_chunks(
        self,
        kb_ids: List[str],
        query_embedding: List[float],
        top_k: int,
        query: Optional[str] = None,
        exact_terms: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        Retrieve top-k chunks by embedding similarity.
        Uses PostgreSQL pgvector if available, with a resilient fallback to Neo4j.
        """
        candidate_limit = max(top_k * 3, 45)
        # Extract exact terms (numbers >= 4 digits, alphanumeric >= 5 chars) from query for hybrid search/boosting
        if exact_terms is None:
            exact_terms = []
            if query:
                import re
                numbers = re.findall(r'\b\d{4,}\b', query)
                exact_terms.extend(numbers)
                alphanumeric = re.findall(r'\b[A-Za-z0-9\-\.]{5,}\b', query)
                for item in alphanumeric:
                    if item not in exact_terms:
                        exact_terms.append(item)

        # ============= STRATEGY 1: POSTGRESQL PGVECTOR =============
        if self.db:
            try:
                from sqlalchemy import select, and_, or_
                from app.modules.knowledge_bases.models import DocumentChunk

                # Query using pgvector cosine_distance operator
                stmt = (
                    select(
                        DocumentChunk.id,
                        DocumentChunk.text,
                        DocumentChunk.chunk_index,
                        DocumentChunk.kb_id,
                        DocumentChunk.metadata_json,
                        (1.0 - DocumentChunk.embedding.cosine_distance(query_embedding)).label("similarity")
                    )
                    .where(
                        and_(
                            DocumentChunk.tenant_id == UUID(self.tenant_id),
                            DocumentChunk.kb_id.in_([UUID(kb_id) for kb_id in kb_ids])
                        )
                    )
                    .order_by(DocumentChunk.embedding.cosine_distance(query_embedding).asc())
                    .limit(candidate_limit)
                )

                result = await self.db.execute(stmt)
                rows = result.fetchall()

                pg_chunks = []
                retrieved_ids = set()

                for row in rows:
                    similarity = float(row.similarity)
                    if similarity >= self.settings.similarity_min_threshold:
                        chunk_id = str(row.id)
                        retrieved_ids.add(chunk_id)
                        
                        chunk_text = row.text or ""
                        if row.metadata_json:
                            row_id_attr = f' row_id="{row.metadata_json.get("row_id")}"' if row.metadata_json.get("row_id") else ""
                            chunk_text += f"\n<ROW_DATA{row_id_attr}>\n{json.dumps(row.metadata_json, indent=2)}\n</ROW_DATA>"
                        
                        # Apply keyword boost if term matches
                        weight = 1.0
                        boosted_similarity = similarity
                        if exact_terms:
                            STOPWORDS = {"how", "has", "had", "have", "from", "across", "the", "and", "for", "with", "this", "that", "what", "who", "whom", "which", "where", "when", "why", "been", "were", "was", "are", "their", "them", "they", "than", "then", "into", "onto", "your", "mine", "some", "more", "most", "each", "both", "either", "neither", "about", "above", "after", "again", "against", "all", "any", "are", "arent", "because", "before", "being", "below", "between", "but", "down", "during", "each", "few", "further", "here", "just", "more", "once", "only", "other", "our", "out", "over", "same", "should", "some", "such", "than", "then", "there", "these", "this", "those", "through", "under", "until", "very", "were", "what", "when", "where", "which", "while", "with", "you", "your", "yours", "yourself"}
                            matching_terms = [t for t in exact_terms if t.lower() not in STOPWORDS]
                            if matching_terms and any(term.lower() in chunk_text.lower() for term in matching_terms):
                                boosted_similarity = similarity + 0.15
                                weight = 1.2

                        pg_chunks.append({
                            "chunk_id": chunk_id,
                            "text": chunk_text,
                            "position": row.chunk_index,
                            "kb_id": str(row.kb_id),
                            "embedding": None,
                            "similarity": boosted_similarity,
                            "weight": weight,
                            "source": None
                        })

                # --- KEYWORD EXACT MATCH SEARCH (HYBRID FALLBACK) ---
                if exact_terms:
                    conditions = []
                    for term in exact_terms:
                        conditions.append(DocumentChunk.text.ilike(f"%{term}%"))
                    
                    if conditions:
                        stmt_kw = (
                            select(
                                DocumentChunk.id,
                                DocumentChunk.text,
                                DocumentChunk.chunk_index,
                                DocumentChunk.kb_id,
                                DocumentChunk.metadata_json,
                                (1.0 - DocumentChunk.embedding.cosine_distance(query_embedding)).label("similarity")
                            )
                            .where(
                                and_(
                                    DocumentChunk.tenant_id == UUID(self.tenant_id),
                                    DocumentChunk.kb_id.in_([UUID(kb_id) for kb_id in kb_ids]),
                                    or_(*conditions)
                                )
                            )
                            .limit(candidate_limit)
                        )
                        
                        res_kw = await self.db.execute(stmt_kw)
                        rows_kw = res_kw.fetchall()
                        
                        added_count = 0
                        for row in rows_kw:
                            chunk_id = str(row.id)
                            if chunk_id not in retrieved_ids:
                                retrieved_ids.add(chunk_id)
                                chunk_text = row.text or ""
                                if row.metadata_json:
                                    row_id_attr = f' row_id="{row.metadata_json.get("row_id")}"' if row.metadata_json.get("row_id") else ""
                                    chunk_text += f"\n<ROW_DATA{row_id_attr}>\n{json.dumps(row.metadata_json, indent=2)}\n</ROW_DATA>"
                                raw_sim = float(row.similarity) if row.similarity else 0.4
                                pg_chunks.append({
                                    "chunk_id": chunk_id,
                                    "text": chunk_text,
                                    "position": row.chunk_index,
                                    "kb_id": str(row.kb_id),
                                    "embedding": None,
                                    "similarity": raw_sim + 0.05,
                                    "weight": 1.05,
                                    "source": None
                                })
                                retrieved_ids.add(chunk_id)
                                added_count += 1
                        if added_count > 0:
                            logger.info(f" Exact keyword search fetched {added_count} additional matching chunks")

                logger.info(f" PostgreSQL pgvector/keyword retrieved {len(pg_chunks)} seed chunks")
                if pg_chunks:
                    pg_chunks.sort(key=lambda x: x["similarity"], reverse=True)
                    return pg_chunks[:candidate_limit]

                logger.warning(" No chunks met similarity threshold in PostgreSQL. Falling back to Neo4j...")
            except Exception as pg_err:
                logger.error(f" PostgreSQL pgvector search failed: {pg_err}. Falling back to Neo4j...", exc_info=True)

        # ============= STRATEGY 2: NEO4J VECTOR FALLBACK =============
        query_neo = """
        MATCH (kb:KnowledgeBase)
        WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
        MATCH (kb)-[:HAS_CHUNK]->(c:Chunk)
        WHERE c.embedding IS NOT NULL AND size(c.embedding) = $dimension
        RETURN c.id as chunk_id, c.text as text, c.position as position, c.kb_id as kb_id, c.embedding as embedding, coalesce(c.weight, 1.0) as weight, COALESCE(kb.s3_path, c.source, kb.name) as source
        LIMIT 1000
        """

        try:
            results = await self.neo4j_repo.execute_read(
                query_neo,
                {
                    "kb_ids": kb_ids, 
                    "tenant_id": self.tenant_id,
                    "dimension": EmbeddingGenerator.get_dimension()
                },
            )

            if not results:
                logger.warning(f" No chunks found for KBs {kb_ids} in Neo4j.")
                return []

            for res in results[:3]:
                logger.info(f" Found chunk in Neo4j: {res['text'][:50]}... (Dim: {len(res['embedding'])})")

            # Compute similarities
            chunks_with_similarity = []
            for result in results:
                similarity = EmbeddingGenerator.cosine_similarity(
                    query_embedding, result["embedding"]
                )
                
                # Check for exact terms matching
                weight = result.get("weight", 1.0)
                if exact_terms:
                    chunk_text = result["text"] or ""
                    STOPWORDS = {"how", "has", "had", "have", "from", "across", "the", "and", "for", "with", "this", "that", "what", "who", "whom", "which", "where", "when", "why", "been", "were", "was", "are", "their", "them", "they", "than", "then", "into", "onto", "your", "mine", "some", "more", "most", "each", "both", "either", "neither", "about", "above", "after", "again", "against", "all", "any", "are", "arent", "because", "before", "being", "below", "between", "but", "down", "during", "each", "few", "further", "here", "just", "more", "once", "only", "other", "our", "out", "over", "same", "should", "some", "such", "than", "then", "there", "these", "this", "those", "through", "under", "until", "very", "were", "what", "when", "where", "which", "while", "with", "you", "your", "yours", "yourself"}
                    matching_terms = [t for t in exact_terms if t.lower() not in STOPWORDS]
                    if matching_terms and any(term.lower() in chunk_text.lower() for term in matching_terms):
                        similarity = similarity + 0.05
                        weight = 1.15

                chunks_with_similarity.append(
                    {
                        "chunk_id": result["chunk_id"],
                        "text": result["text"],
                        "position": result["position"],
                        "kb_id": result["kb_id"],
                        "embedding": result["embedding"],
                        "similarity": similarity,
                        "weight": weight,
                        "source": result.get("source"),
                    }
                )

            # Sort by similarity, return top-k
            sorted_chunks = sorted(
                [c for c in chunks_with_similarity if c["similarity"] >= self.settings.similarity_min_threshold],
                key=lambda x: x["similarity"],
                reverse=True
            )
            
            if chunks_with_similarity:
                max_score = max(c["similarity"] for c in chunks_with_similarity)
                logger.info(f" Max similarity score found in Neo4j: {max_score:.4f} (Threshold: {self.settings.similarity_min_threshold})")
            else:
                logger.warning(" No chunks found in Neo4j (with embeddings) for this Knowledge Base.")

            return sorted_chunks[:candidate_limit]

        except Exception as e:
            logger.error(f" Failed to retrieve seed chunks via Neo4j: {e}")
            return []

    async def _execute_table_analytics(self, query: str, kb_ids: list[str]) -> Optional[str]:
        """
        Text-to-JSON Structured Query Planner.
        Uses LLM to convert natural language query into a JSON AST, executes it securely, and returns results.
        """
        from sqlalchemy import text
        import json
        import time
        import os
        import uuid
        from app.modules.knowledge_bases.models import AnalyticsQueryLog as TableQueryLog
        
        debug_mode = os.environ.get("DEBUG_ANALYTICS", "False").lower() == "true"
        trace_log = []
        if debug_mode:
            trace_log.append(f"User Query:\n{query}\n\nIntent:\nTABLE_ANALYTICS\n")
            
        t_start = time.perf_counter()
        ast = {}
        query_str = "SQL Generation Failed"
        rows_count = 0

        async def log_attempt(status_rows: int = 0):
            try:
                log_record = TableQueryLog(
                    tenant_id=uuid.UUID(str(self.tenant_id)),
                    kb_id=uuid.UUID(str(kb_ids[0])) if kb_ids else None,
                    query_text=query,
                    intent_json=ast,
                    generated_sql=query_str,
                    rows_returned=status_rows,
                    execution_time_ms=int((time.perf_counter() - t_start) * 1000)
                )
                self.db.add(log_record)
                await self.db.commit()
            except Exception as db_err:
                logger.error(f"Failed to save AnalyticsQueryLog: {db_err}")
                if self.db:
                    await self.db.rollback()
        
        # 1. Fetch schema, name, parsed_path AND s3_path for target KBs
        import uuid
        kb_param_dict = {f"kb_{i}": uuid.UUID(str(k)) for i, k in enumerate(kb_ids)}
        kb_param_dict["tenant_id"] = uuid.UUID(str(self.tenant_id))
        kb_in_str = ", ".join([f":kb_{i}" for i in range(len(kb_ids))])
        kb_query = f"SELECT id, name, dataset_schema, parsed_path, s3_path, source, description FROM knowledge_bases WHERE id IN ({kb_in_str}) AND tenant_id = :tenant_id;"
        result = await self.db.execute(text(kb_query), kb_param_dict)
        kb_rows = result.all()
        
        if not kb_rows:
            await log_attempt(0)
            return None
            
        kb_names = {str(r.id): r.name for r in kb_rows}
        # --- DEFINITIVE FIX: Use ParquetIngester registry to resolve local parquet path ---
        # The CSV ingestion pipeline converts CSV->Parquet and registers the path in
        # data/parquet/active_datasets.json under the key kb.parsed_path (e.g. 'dummy_employees_details').
        # kb.description == 'excel_parquet' is the authoritative flag for spreadsheet KBs.
        # We must NOT check s3_path for .csv - the S3 bucket is private (403 Forbidden).
        # This is the same pattern used in service.py lines 130-145.
        from app.core.parquet_ingester import ParquetIngester

        excel_kb_rows = [r for r in kb_rows if getattr(r, 'description', '') == 'excel_parquet']
        non_excel_rows = [r for r in kb_rows if getattr(r, 'description', '') != 'excel_parquet']

        # 1.5. HYBRID PANDAS ENGINE ROUTING FOR SPREADSHEET (PARQUET) FILES
        if excel_kb_rows:
            logger.info(f" {len(excel_kb_rows)} excel_parquet KB(s) detected! Resolving local parquet via ParquetIngester.")
            from .pandas_engine import PandasQueryEngine
            active_paths = []
            for ekb in excel_kb_rows:
                dataset_name = getattr(ekb, 'parsed_path', None) or getattr(ekb, 'name', None)
                if dataset_name:
                    p = ParquetIngester.get_active_dataset(dataset_name)
                    if p:
                        logger.info(f" Resolved parquet: {p}")
                        active_paths.append(p)
                    else:
                        logger.warning(f" No active parquet found for dataset_name={dataset_name!r}")

            if active_paths:
                engine = PandasQueryEngine(active_paths[0], all_dataset_paths=active_paths)
                query_str = "PANDAS PandasQueryEngine.execute_query"
                all_csv_results = []
                for ekb, path in zip(excel_kb_rows, active_paths):
                    try:
                        res = await engine.execute_query(query, path)
                        if res and "No valid spreadsheet" not in res:
                            kb_label = ekb.name or path
                            all_csv_results.append(f"[Source: {kb_label}]\n{res}")
                        else:
                            logger.warning(f" PandasQueryEngine returned empty/error for {path}: {res}")
                    except Exception as csv_err:
                        logger.error(f"PandasQueryEngine failed for {path}: {csv_err}", exc_info=True)
                if all_csv_results:
                    await log_attempt(len(all_csv_results))
                    return "\n\n".join(all_csv_results)
            else:
                logger.warning(" No active parquet files resolved for excel_parquet KBs. Cannot answer tabular query.")
            await log_attempt(0)
            return None

        # Fall through to SQL path for non-spreadsheet knowledge bases
        dataset_schema = {}
        for r in non_excel_rows or kb_rows:
            if r.dataset_schema:
                dataset_schema.update(r.dataset_schema)
                
        parsed_path = non_excel_rows[0].parsed_path if non_excel_rows else kb_rows[0].parsed_path
        source = non_excel_rows[0].source if non_excel_rows else kb_rows[0].source
        # Fallback to standard SQL generation over document_table_rows
        if not dataset_schema:
            kb_param_dict = {f"kb_{i}": uuid.UUID(str(k)) for i, k in enumerate(kb_ids)}
            kb_param_dict["tenant_id"] = uuid.UUID(str(self.tenant_id))
            kb_in_str = ", ".join([f":kb_{i}" for i in range(len(kb_ids))])
            sample_query = f"SELECT row_data FROM document_table_rows WHERE kb_id IN ({kb_in_str}) AND tenant_id = :tenant_id LIMIT 300;"
            result = await self.db.execute(text(sample_query), kb_param_dict)
            rows = result.scalars().all()
            if rows:
                dataset_schema = {}
                all_keys = set()
                for row in rows:
                    all_keys.update(row.keys())
                
                import re
                for k in all_keys:
                    vals = [row[k] for row in rows if k in row and row[k] is not None and str(row[k]).strip() != ""]
                    if not vals:
                        dataset_schema[k] = "string"
                        continue
                        
                    # 0. Check identifier columns
                    if re.search(r'\b(id|code|sku|number|no|ref|key)\b', k, re.IGNORECASE):
                        dataset_schema[k] = "string"
                        continue

                    # 1. Check boolean
                    unique_vals = set(str(v).lower().strip() for v in vals)
                    if unique_vals.issubset({"true", "false", "yes", "no", "t", "f"}):
                        dataset_schema[k] = "boolean"
                        continue
                        
                    # 2. Check numeric, currency, and percentage
                    has_currency_symbols = False
                    has_percentage_symbols = False
                    is_integer_all = True
                    cleaned_values = []
                    non_empty_count = 0
                    numeric_count = 0
                    
                    for val in vals:
                        val_str = str(val).strip()
                        if not val_str or val_str.lower() in ["na", "n/a", "none", "null", "-", ""]:
                            continue
                            
                        non_empty_count += 1
                        is_neg = False
                        if val_str.startswith("(") and val_str.endswith(")"):
                            is_neg = True
                            val_str = val_str[1:-1].strip()
                            
                        if any(c in val_str for c in ["$", "\u20ac", "\u00a3", "\u20b9"]):
                            has_currency_symbols = True
                            val_str = re.sub(r'[\$\u20ac\u00a3\u20b9]', '', val_str).strip()
                            
                        if "%" in val_str:
                            has_percentage_symbols = True
                            val_str = val_str.replace("%", "").strip()

                        # Strip common ordinal suffixes like st, nd, rd, th from numbers
                        val_str = re.sub(r'(?<=\d)(st|nd|rd|th)\b', '', val_str, flags=re.IGNORECASE)
                            
                        if "," in val_str:
                            if "." in val_str:
                                val_str = val_str.replace(",", "")
                            else:
                                parts = val_str.split(",")
                                if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
                                    val_str = val_str.replace(",", "")
                                elif len(parts) == 2 and len(parts[1]) != 3:
                                    val_str = val_str.replace(",", ".")
                                else:
                                    val_str = val_str.replace(",", "")
                                    
                        if is_neg:
                            val_str = "-" + val_str
                            
                        try:
                            num_val = float(val_str)
                            cleaned_values.append(num_val)
                            numeric_count += 1
                            if not num_val.is_integer():
                                is_integer_all = False
                        except ValueError:
                            pass
                            
                    is_numeric_candidate = (non_empty_count > 0 and (numeric_count / non_empty_count) >= 0.9)
                    if is_numeric_candidate and cleaned_values:
                        if has_currency_symbols:
                            dataset_schema[k] = "currency"
                        elif has_percentage_symbols:
                            dataset_schema[k] = "percentage"
                        elif is_integer_all:
                            dataset_schema[k] = "integer"
                        else:
                            dataset_schema[k] = "float"
                        continue
                        
                    # 3. Check datetime
                    try:
                        if all(re.search(r'[-/:]', str(v)) for v in vals):
                            import pandas as pd
                            for v in vals:
                                pd.to_datetime(v)
                            dataset_schema[k] = "datetime"
                            continue
                    except Exception:
                        pass
                        
                    dataset_schema[k] = "string"
            else:
                return None
                
        # 2. Ask LLM to generate JSON AST
        t_ast_start = time.perf_counter()
        prompt = f"""You are a Structured Query Planner. Convert the user's natural language query into a JSON Abstract Syntax Tree (AST) for tabular analytics.

AVAILABLE COLUMNS & TYPES:
{json.dumps(dataset_schema, indent=2)}

USER QUERY: {query}

INSTRUCTIONS:
Return ONLY valid JSON matching this schema:
{{
  "operation": "string", // MUST be one of: "COUNT", "AVG", "MAX", "MIN", "SUM", "GROUP", "SORT", "FILTER", "ERROR"
  "target_field": "string | null", // The field to aggregate or target, or null
  "filters": [
    {{
      "field": "string", // The exact column name
      "operator": "string", // MUST be one of: "=", "!=", ">", "<", ">=", "<=", "ILIKE", "LIKE". Use ILIKE for case-insensitive substring/regex matches.
      "value": "string | number" // The value to compare.
    }}
  ],
  "group_by": "string | null", // Field to group by
  "sort_by": "string | null", // Field to sort by
  "sort_dir": "string", // "ASC" or "DESC"
  "difference_fields": ["string", "string"] | null, // Exactly two fields to compute difference/subtraction, or null
  "limit": 50 // Integer limit
}}

CRITICAL RULES:
1. If the query asks for "Which country has the highest/lowest X" or "Which country has the maximum/minimum X", do NOT use operations "MAX", "MIN" or "AVG". Instead, use operation "SORT" with target_field=null, sort_by="X", sort_dir="DESC" (for highest/max) or "ASC" (for lowest/min), and set limit=1. This ensures the engine returns the complete row including the country name, rather than just the number.
2. For rank queries, e.g., "Which country is ranked 5th?", use operation "FILTER" with a filter on "rank" equal to 5 (or "5th").
3. For comparisons, e.g., "Compare the Economy (E1) scores of Somalia and Yemen", use "FILTER" with a filter on "country" matching "Somalia" and "Yemen".
4. Always use exact column names matching the AVAILABLE COLUMNS list. Do not invent columns.
5. If the query asks for a difference/comparison between two columns (e.g., 'greatest difference between X and Y'), do NOT use sort_by. Instead, set 'difference_fields': ['X', 'Y'], 'sort_dir': 'DESC', 'operation': 'SORT', 'limit': 1.
6. For queries asking for the average, sum, minimum, or maximum of a subset of top/bottom ranked records (e.g., 'average of the top 5', 'sum of the bottom 10'), set 'operation' to the aggregate ("AVG", "SUM", etc.), 'target_field' to the field to aggregate, 'sort_by' to the rank or sort field (e.g. 'rank' or 'total'), 'sort_dir' to "DESC" (for top/highest) or "ASC" (for bottom/lowest), and 'limit' to the number of records (e.g., 5 or 10).
7. If the query requires a multi-stage or nested sort/filter (e.g., 'Among the top 10, which one has the lowest X'), do not generate a JSON AST. Instead, return a JSON with "operation": "ERROR" and "target_field": "Nested operations not supported".
"""

        generated_ast_str = await self.llm_client.generate_cloud(
            prompt=prompt,
            system_prompt="You are a Structured Query Planner. Return only JSON.",
            temperature=0.0,
            max_tokens=4000,
            enable_thinking=False
        )
        
        import re
        try:
            # Extract JSON block even if there is a <think> tag
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', generated_ast_str, re.DOTALL)
            if json_match:
                clean_json = json_match.group(1)
            else:
                # Fallback to finding the first { and last }
                start_idx = generated_ast_str.find('{')
                end_idx = generated_ast_str.rfind('}')
                if start_idx != -1 and end_idx != -1:
                    clean_json = generated_ast_str[start_idx:end_idx+1]
                else:
                    clean_json = generated_ast_str
            ast = json.loads(clean_json)
            
            # Reject relative queries and nested sorts
            relative_terms = ["immediately after", "ranked after", "immediately before", "ranked before", "ranked immediately", "next to"]
            if any(term in query.lower() for term in relative_terms):
                await log_attempt(0)
                return "Validation Error: Relative ranking queries cannot be resolved via static SQL filters."

            if ast.get("operation") == "ERROR":
                await log_attempt(0)
                return f"Validation Error: {ast.get('target_field', 'Unsupported query structure')}"
        except Exception as e:
            logger.error(f" Failed to parse JSON AST: {e} - String: {generated_ast_str}")
            return None
            
        t_ast_gen = time.perf_counter() - t_ast_start
        logger.info(f" Structured Query AST: {json.dumps(ast)}")
        if debug_mode:
            trace_log.append(f"Generated AST:\n{json.dumps(ast, indent=2)}\n")
        
        # 2.5 AST Validation Layer
        t_val_start = time.perf_counter()
        operation = str(ast.get("operation", "FILTER")).upper()
        target_field = ast.get("target_field")
        
        valid_operations = {"COUNT", "AVG", "MAX", "MIN", "SUM", "GROUP", "SORT", "FILTER"}
        if operation not in valid_operations:
            await log_attempt(0)
            return f"Validation Error: Unsupported operation '{operation}'."
            
        numeric_types = ["float", "integer", "currency", "percentage"]
        if operation in ["AVG", "MAX", "MIN", "SUM"]:
            if not target_field:
                await log_attempt(0)
                return f"Validation Error: Operation '{operation}' requires a target_field."
            if target_field not in dataset_schema:
                await log_attempt(0)
                return f"Validation Error: Field '{target_field}' does not exist in this dataset."
            if dataset_schema[target_field] not in numeric_types:
                # Dynamically check if the values in database are actually numeric
                try:
                    import re
                    kb_param_dict = {f"kb_{i}": uuid.UUID(str(k)) for i, k in enumerate(kb_ids)}
                    kb_param_dict["tenant_id"] = uuid.UUID(str(self.tenant_id))
                    kb_param_dict["field"] = target_field
                    kb_in_str = ", ".join([f":kb_{i}" for i in range(len(kb_ids))])
                    sample_query = f"SELECT row_data->>:field as val FROM document_table_rows WHERE kb_id IN ({kb_in_str}) AND tenant_id = :tenant_id LIMIT 20;"
                    sample_res = await self.db.execute(text(sample_query), kb_param_dict)
                    sample_vals = [r.val for r in sample_res.all() if r.val is not None and str(r.val).strip() != ""]
                    if sample_vals:
                        non_empty_count = 0
                        numeric_count = 0
                        for val in sample_vals:
                            val_str = str(val).strip()
                            if not val_str or val_str.lower() in ["na", "n/a", "none", "null", "-", ""]:
                                continue
                            non_empty_count += 1
                            if val_str.startswith("(") and val_str.endswith(")"):
                                val_str = "-" + val_str[1:-1].strip()
                            val_str = re.sub(r'[\$\u20ac\u00a3\u20b9]', '', val_str).strip()
                            val_str = val_str.replace("%", "").strip()
                            val_str = val_str.replace(",", "")
                            try:
                                float(val_str)
                                numeric_count += 1
                            except ValueError:
                                pass
                        if non_empty_count > 0 and (numeric_count / non_empty_count) >= 0.9:
                            dataset_schema[target_field] = "float"
                except Exception as e:
                    logger.error(f"Dynamic numeric validation check failed: {e}")

            if dataset_schema[target_field] not in numeric_types:
                await log_attempt(0)
                return f"Validation Error: {operation} cannot be applied to string field '{target_field}'"
                
        if operation == "GROUP":
            group_by = ast.get("group_by")
            if not group_by or group_by not in dataset_schema:
                await log_attempt(0)
                return f"Validation Error: Unknown or missing group_by field '{group_by}'."
                
        sort_by = ast.get("sort_by")
        if sort_by and sort_by not in dataset_schema:
            await log_attempt(0)
            return f"Validation Error: Unknown sort_by field '{sort_by}'."
            
        diff_fields = ast.get("difference_fields")
        if diff_fields:
            if not isinstance(diff_fields, list) or len(diff_fields) != 2:
                await log_attempt(0)
                return "Validation Error: 'difference_fields' must be an array of exactly 2 fields."
            for f in diff_fields:
                if f not in dataset_schema:
                    await log_attempt(0)
                    return f"Validation Error: Field '{f}' in 'difference_fields' does not exist in this dataset."
                if dataset_schema[f] not in numeric_types:
                    await log_attempt(0)
                    return f"Validation Error: Field '{f}' in 'difference_fields' is not numeric."

        for f in ast.get("filters", []):
            field = f.get("field")
            if not field or field not in dataset_schema:
                await log_attempt(0)
                return f"Validation Error: Unknown filter field '{field}'."
            op = str(f.get("operator", "=")).upper()
            if op not in ["=", "!=", ">", "<", ">=", "<=", "ILIKE", "LIKE", "CONTAINS"]:
                await log_attempt(0)
                return f"Validation Error: Unsupported filter operator '{op}' for field '{field}'."

        t_ast_val = time.perf_counter() - t_val_start
        if debug_mode:
            trace_log.append(f"Validated AST:\n{json.dumps(ast, indent=2)}\n")

        # 3. Secure Backend Query Builder
        def get_json_val(field_name):
            return f"(SELECT v FROM jsonb_each_text(row_data) AS kv(k,v) WHERE lower(k) = lower('{field_name}') LIMIT 1)"

        def safe_numeric_cast(field_name):
            val = get_json_val(field_name)
            clean = f"TRIM(REGEXP_REPLACE({val}, '[\\$\\u20ac\\u00a3\\u20b9,%]', '', 'g'))"
            return f"CASE WHEN {clean} ~ '^[-+]?[0-9]*\.?[0-9]+$' THEN {clean}::numeric ELSE NULL END"

        t_sql_start = time.perf_counter()
        
        # Determine if we need a subquery for aggregation over limited/sorted rows
        use_subquery = False
        if operation in ["AVG", "MAX", "MIN", "SUM"] and ast.get("limit") and (ast.get("sort_by") or ast.get("filters") or ast.get("difference_fields")):
            use_subquery = True

        kb_param_dict = {f"kb_{i}": uuid.UUID(str(k)) for i, k in enumerate(kb_ids)}
        kb_param_dict["tenant_id"] = uuid.UUID(str(self.tenant_id))
        kb_in_str = ", ".join([f":kb_{i}" for i in range(len(kb_ids))])
        where_clauses = [f"kb_id IN ({kb_in_str})", "tenant_id = :tenant_id"]
        params = kb_param_dict
        
        # Build explainability parts
        explain_filters = []
        
        # Group filters by field so multiple filters on the SAME field can be joined with OR.
        # Across fields, groups will still be joined with AND.
        # Note: If mixed AND/OR logic is needed in the future, a generalized 'logic'
        # node could be added to the AST.
        from collections import defaultdict
        field_groups = defaultdict(list)
        for i, f in enumerate(ast.get("filters", [])):
            field_groups[f.get("field")].append((i, f))
            
        for field, group_filters in field_groups.items():
            group_clauses = []
            for i, f in group_filters:
                op = str(f.get("operator", "=")).upper()
                val = f.get("value")
                
                # Translate contains to ILIKE
                if op == "CONTAINS":
                    op = "ILIKE"
                    if isinstance(val, str) and not val.startswith("%"):
                        val = f"%{val}%"
                        
                field_type = dataset_schema.get(field, "string")
                if field_type in numeric_types and op in [">", "<", ">=", "<=", "=", "!="]:
                    try:
                        val_str = re.sub(r'[^\d.-]', '', str(val))
                        val_cast = float(val_str)
                        if val_cast.is_integer():
                            val_cast = int(val_cast)
                    except ValueError:
                        val_cast = val
                    group_clauses.append(f"{safe_numeric_cast(field)} {op} :val_{i}")
                    params[f"val_{i}"] = val_cast
                elif field_type == "boolean":
                    safe_bool = f"CASE WHEN LOWER({get_json_val(field)}) IN ('true', 'yes', 't', '1') THEN TRUE WHEN LOWER({get_json_val(field)}) IN ('false', 'no', 'f', '0') THEN FALSE ELSE NULL END"
                    bool_val = str(val).lower().strip() in ["true", "yes", "t", "1"]
                    group_clauses.append(f"{safe_bool} = :val_{i}")
                    params[f"val_{i}"] = bool_val
                else:
                    if op == "ILIKE" and isinstance(val, str):
                        clean_val = val.strip('%')
                        words = [w.strip() for w in re.split(r'\s+', clean_val) if len(w.strip()) > 1]
                        if not words:
                            words = [clean_val]
                            
                        word_clauses = []
                        for w_idx, word in enumerate(words):
                            # Naive singularization for trailing 'es' and 's'
                            if word.lower().endswith('es') and len(word) > 4:
                                word = word[:-2]
                            elif word.lower().endswith('s') and len(word) > 3:
                                word = word[:-1]
                            
                            word_clauses.append(f"{get_json_val(field)} ILIKE :val_{i}_{w_idx}")
                            params[f"val_{i}_{w_idx}"] = f"%{word}%"
                            
                        if len(word_clauses) > 1:
                            group_clauses.append("(" + " AND ".join(word_clauses) + ")")
                        else:
                            group_clauses.append(word_clauses[0])
                    else:
                        group_clauses.append(f"{get_json_val(field)} {op} :val_{i}")
                        params[f"val_{i}"] = val
                    
                explain_filters.append(f"{field} {op} {val}")
                
            if len(group_clauses) > 1:
                where_clauses.append("(" + " OR ".join(group_clauses) + ")")
            elif len(group_clauses) == 1:
                where_clauses.append(group_clauses[0])
            
        where_str = " AND ".join(where_clauses)

        if use_subquery:
            inner_select = f"{safe_numeric_cast(target_field)} as sub_val"
            inner_query = f"SELECT {inner_select} FROM document_table_rows WHERE {where_str}"
            
            if ast.get("sort_by"):
                sort_dir = "ASC" if str(ast.get("sort_dir", "DESC")).upper() == "ASC" else "DESC"
                sort_field = ast["sort_by"]
                if sort_field == "rank":
                    inner_query += f" ORDER BY NULLIF(REGEXP_REPLACE({get_json_val('rank')}, '[^0-9]', '', 'g'), '')::numeric {sort_dir}"
                elif dataset_schema.get(sort_field) in numeric_types:
                    inner_query += f" ORDER BY {safe_numeric_cast(sort_field)} {sort_dir}"
                else:
                    inner_query += f" ORDER BY {get_json_val(sort_field)} {sort_dir}"
            elif ast.get("difference_fields"):
                sort_dir = "ASC" if str(ast.get("sort_dir", "DESC")).upper() == "ASC" else "DESC"
                diff_f = ast["difference_fields"]
                sort_expr = f"ABS({safe_numeric_cast(diff_f[0])} - {safe_numeric_cast(diff_f[1])})"
                inner_query += f" ORDER BY {sort_expr} {sort_dir}"
                
            limit = min(int(ast.get("limit", 50) or 50), 100)
            inner_query += f" LIMIT {limit}"
            
            query_str = f"SELECT {operation}(sub_val) as val FROM ({inner_query}) as sub"
        else:
            select_clause = "row_data, kb_id, page_number, table_index"
            if operation == "COUNT":
                select_clause = "COUNT(*)"
            elif operation in ["AVG", "MAX", "MIN", "SUM"] and target_field:
                select_clause = f"{operation}({safe_numeric_cast(target_field)}) as val"
            elif operation == "GROUP" and ast.get("group_by"):
                group_field = ast.get("group_by")
                select_clause = f"{get_json_val(group_field)} as group_key, COUNT(*) as count"
                
            query_str = f"SELECT {select_clause} FROM document_table_rows WHERE {where_str}"
            
            if operation == "GROUP" and ast.get("group_by"):
                query_str += f" GROUP BY {get_json_val(ast['group_by'])}"
                
            if ast.get("sort_by"):
                sort_dir = "ASC" if str(ast.get("sort_dir", "DESC")).upper() == "ASC" else "DESC"
                sort_field = ast["sort_by"]
                if sort_field == "rank":
                    query_str += f" ORDER BY NULLIF(REGEXP_REPLACE({get_json_val('rank')}, '[^0-9]', '', 'g'), '')::numeric {sort_dir}"
                elif dataset_schema.get(sort_field) in numeric_types:
                    query_str += f" ORDER BY {safe_numeric_cast(sort_field)} {sort_dir}"
                else:
                    query_str += f" ORDER BY {get_json_val(sort_field)} {sort_dir}"
            elif ast.get("difference_fields"):
                sort_dir = "ASC" if str(ast.get("sort_dir", "DESC")).upper() == "ASC" else "DESC"
                diff_f = ast["difference_fields"]
                sort_expr = f"ABS({safe_numeric_cast(diff_f[0])} - {safe_numeric_cast(diff_f[1])})"
                query_str += f" ORDER BY {sort_expr} {sort_dir}"
            elif operation == "GROUP":
                query_str += " ORDER BY count DESC"
                
            limit = min(int(ast.get("limit", 50) or 50), 100)
            if operation not in ["COUNT", "AVG", "MAX", "MIN", "SUM"]:
                query_str += f" LIMIT {limit}"
            
        logger.info(f" Executing Parameterized SQL: {query_str} with {params}")
        t_sql_gen = time.perf_counter() - t_sql_start
        
        if debug_mode:
            trace_log.append(f"Generated SQL:\n{query_str}\n\nParameters:\n{json.dumps(params, default=str)}\n")
            
        # 4. Execute the generated SQL
        t_exec_start = time.perf_counter()
        try:
            result = await self.db.execute(text(query_str), params)
            rows = result.all()
            t_exec = time.perf_counter() - t_exec_start
            t_total = time.perf_counter() - t_start
            
            if debug_mode:
                trace_log.append(f"Execution Time:\n{int(t_total*1000)} ms (AST: {int(t_ast_gen*1000)}ms, Val: {int(t_ast_val*1000)}ms, SQL Gen: {int(t_sql_gen*1000)}ms, DB Exec: {int(t_exec*1000)}ms)\n")
                trace_log.append(f"Rows Returned:\n{len(rows)}\n")
            
            logger.info(f"SQL Table Analytics execution returned {len(rows)} rows.")
            
            if not rows:
                logger.warning(f"SQL execution returned no records: {query_str}")
                await log_attempt(0)
                return None

            from decimal import Decimal
            formatted_rows = []
            for r in rows:
                if hasattr(r, '_mapping'):
                    row_dict = dict(r._mapping)
                elif hasattr(r, 'keys'):
                    row_dict = dict(r)
                else:
                    row_dict = {"value": r[0]}
                    
                # Convert Decimals to float
                for k, v in row_dict.items():
                    if isinstance(v, Decimal):
                        row_dict[k] = float(v)
                        
                formatted_rows.append(row_dict)
            
            # If all target/aggregation values are None, return None to trigger fallback
            all_none = True
            for r in formatted_rows:
                meta_keys = {"kb_id", "page_number", "table_index", "row_index", "id", "tenant_id", "created_at"}
                for k, v in r.items():
                    if k in meta_keys:
                        continue
                    if v is not None and str(v).strip().lower() not in ["", "none", "null"]:
                        all_none = False
                        break
                if not all_none:
                    break
            if all_none:
                logger.warning("SQL execution returned only None or empty values. Falling back to vector search.")
                await log_attempt(0)
                return None
                    
            # Group rows by (kb_id, page_number, table_index)
            tables_map = {}
            for r in formatted_rows:
                if "row_data" in r and isinstance(r["row_data"], dict):
                    kb_val = r.get("kb_id")
                    page_num = r.get("page_number", 1)
                    tbl_val = r.get("table_index", 0)
                    key = (str(kb_val) if kb_val else "unknown_kb", page_num, tbl_val)
                    if key not in tables_map:
                        tables_map[key] = []
                    tables_map[key].append(r["row_data"])
                else:
                    key = ("agg", 0, 0)
                    if key not in tables_map:
                        tables_map[key] = []
                    tables_map[key].append(r)
            
            # Sort keys to preserve natural document order (page_number first, then table_index)
            sorted_keys = sorted(tables_map.keys(), key=lambda x: (x[0], x[1], x[2]))
            
            # Format each group as a separate markdown table
            markdown_tables = []
            kb_table_counters = {}
            
            for key in sorted_keys:
                kb_id_str, page_num, tbl_index = key
                data_rows = tables_map[key]
                headers = []
                for r in data_rows:
                    for k in r.keys():
                        if k not in headers:
                            headers.append(k)
                
                if headers:
                    table_lines = []
                    # Add a title if it's not a simple aggregation
                    if kb_id_str != "agg":
                        kb_name = kb_names.get(kb_id_str, "Knowledge Base")
                        kb_display = kb_name.replace("PDF: ", "").replace("Spreadsheet: ", "")
                        
                        # Increment table count for this KB
                        kb_table_counters[kb_id_str] = kb_table_counters.get(kb_id_str, 0) + 1
                        display_idx = kb_table_counters[kb_id_str]
                        
                        table_lines.append(f"#### Table: {kb_display} (Table #{display_idx})")
                        table_lines.append("")
                        
                    table_lines.append("| " + " | ".join(headers) + " |")
                    table_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
                    for r in data_rows:
                        row_vals = []
                        for h in headers:
                            val = r.get(h, "")
                            val_str = str(val).replace("\n", " ").replace("|", "\\|")
                            row_vals.append(val_str)
                        table_lines.append("| " + " | ".join(row_vals) + " |")
                    
                    markdown_tables.append("\n".join(table_lines))
            
            if markdown_tables:
                formatted = "\n\n".join(markdown_tables)
            else:
                formatted = json.dumps(formatted_rows, indent=2)
            
            # 5. Explainability Layer
            explanation = "\n\n---\nComputed using:\n"
            if operation in ["AVG", "MAX", "MIN", "SUM"]:
                explanation += f"- Operation: {operation} on '{target_field}'\n"
            elif operation == "GROUP":
                explanation += f"- Operation: GROUP BY '{ast.get('group_by')}'\n"
            else:
                explanation += f"- Operation: {operation}\n"
                
            if explain_filters:
                explanation += f"- Filters: {', '.join(explain_filters)}\n"
            else:
                explanation += f"- Filters: None\n"
                
            explanation += f"- Records returned: {len(formatted_rows)}\n"
            
            if debug_mode:
                explanation += "\n\n---\n**Analytics Debug Trace:**\n```text\n" + "\n".join(trace_log) + "\n```"
            
            await log_attempt(len(formatted_rows))
            return formatted + explanation
            
        except Exception as e:
            logger.error(f" SQL Execution Failed: {e}")
            await log_attempt(0)
            if self.db:
                await self.db.rollback()
            return None

    async def _expand_via_graph(



        self,



        seed_chunk_ids: Set[str],



        kb_ids: List[str],



        max_depth: int = 2,



    ) -> Dict[str, Dict]:



        """



        Expand seed chunks via graph relationships.







        EXPANSION STRATEGY:



        - Depth 1: Via SIMILAR (semantic), MENTIONS (entity), NEXT (context)



        - Depth 2: One more hop from Depth 1 neighbors







        Args:



            seed_chunk_ids: Set of seed chunk IDs



            max_depth: Max expansion hops







        Returns:



            Dict mapping chunk_id -> chunk metadata



        """



        expanded = {cid: {"depth": 0, "connection": "seed"} for cid in seed_chunk_ids}







        for depth in range(1, max_depth + 1):



            # Get all IDs from current frontier



            frontier_ids = [



                cid for cid, meta in expanded.items() if meta.get("depth") == depth - 1



            ]







            if not frontier_ids:



                break







            # Expand via all relationship types



            query = """



            WITH $frontier_ids AS frontier



            MATCH (c:Chunk {tenant_id: $tenant_id})



            WHERE c.id IN frontier



            



            WITH c



            MATCH (c)-[r]-(neighbor:Chunk {tenant_id: $tenant_id})



            WHERE NOT (neighbor.id IN $existing_ids)



            AND neighbor.kb_id IN $kb_ids



            AND NOT (neighbor)-[:HAS_CHUNK]-(:KnowledgeBase)  // Not KB root



            



            RETURN DISTINCT



                neighbor.id as chunk_id,



                type(r) as relationship_type,



                coalesce(neighbor.weight, 1.0) as weight



            LIMIT 50



            """







            try:



                results = await self.neo4j_repo.execute_read(



                    query,



                    {



                        "frontier_ids": frontier_ids,



                        "existing_ids": list(expanded.keys()),



                        "kb_ids": kb_ids,



                        "tenant_id": self.tenant_id,



                    },



                )







                for result in results:



                    if result["chunk_id"] not in expanded:



                        expanded[result["chunk_id"]] = {



                            "depth": depth,



                            "connection": result["relationship_type"],



                            "weight": result.get("weight", 1.0),



                        }







            except Exception as e:



                logger.warning(



                    f" Graph expansion depth {depth} failed: {e}. Continuing..."



                )



                break







        logger.debug(



            f"Graph expansion: {len(expanded) - len(seed_chunk_ids)} new chunks discovered"



        )



        return expanded

    async def _retrieve_reconstructed_tables(
        self,
        keywords: List[str],
        kb_ids: List[str],
    ) -> List[RetrievedChunk]:
        """
        Searches document_table_rows for rows matching the keywords,
        groups them by (kb_id, page_number, table_index),
        reconstructs the tables in Markdown, and returns them as RetrievedChunks.
        """
        if not keywords or not kb_ids:
            return []
            
        import uuid
        from collections import defaultdict
        
        # We also want to include synonyms or sub-words if keywords are phrases
        search_keywords = []
        for kw in keywords:
            cleaned = kw.strip().lower()
            if cleaned and cleaned not in search_keywords:
                search_keywords.append(cleaned)
        
        if not search_keywords:
            return []
            
        # Build query to find matching tables
        like_clauses = " OR ".join([f"row_data::text ILIKE :kw_{i}" for i in range(len(search_keywords))])
        params = {f"kw_{i}": f"%{kw}%" for i, kw in enumerate(search_keywords)}
        
        # Convert kb_ids to UUID objects for safe SQL execution
        kb_uuids = []
        for k in kb_ids:
            try:
                kb_uuids.append(uuid.UUID(k))
            except:
                pass
        if not kb_uuids:
            return []
            
        params["kb_ids"] = kb_uuids
        
        # Pre-rank: count keyword hits per (kb_id, page_number, table_index) to prioritise most-relevant tables
        # Cap results at MAX_TABLES_PER_KB per source document and MAX_TOTAL_TABLES total
        MAX_TABLES_PER_KB = 5
        MAX_TOTAL_TABLES = 10
        
        # Count hits per table group for ranking (prioritizing unique keyword hits, then total keyword occurrences)
        max_clauses = " + ".join(
            [f"MAX(CASE WHEN row_data::text ILIKE :kw_{i} THEN 1 ELSE 0 END)" for i in range(len(search_keywords))]
        )
        sum_clauses = " + ".join(
            [f"SUM(CASE WHEN row_data::text ILIKE :kw_{i} THEN 1 ELSE 0 END)" for i in range(len(search_keywords))]
        )
        rank_query_str = f"""
            SELECT kb_id, page_number, table_index, 
                   ({max_clauses}) AS unique_hits,
                   ({sum_clauses}) AS total_hits
            FROM document_table_rows 
            WHERE kb_id IN ({kb_in_str}) AND ({like_clauses})
            GROUP BY kb_id, page_number, table_index
            ORDER BY unique_hits DESC, total_hits DESC
        """
        
        try:
            from sqlalchemy import text
            res = await self.db.execute(text(rank_query_str), params)
            all_ranked_tables = res.fetchall()
            if not all_ranked_tables:
                return []
            
            # Limit per KB, cap total
            tables_per_kb: dict = {}
            matched_tables = []
            min_hits_threshold = 1
            for row in all_ranked_tables:
                if row.unique_hits < min_hits_threshold:
                    continue
                kb_key = str(row.kb_id)
                if tables_per_kb.get(kb_key, 0) < MAX_TABLES_PER_KB:
                    matched_tables.append((row.kb_id, row.page_number, row.table_index, row.unique_hits))
                    tables_per_kb[kb_key] = tables_per_kb.get(kb_key, 0) + 1
                if len(matched_tables) >= MAX_TOTAL_TABLES:
                    break
                
            logger.info(f"   -> Table search found {len(all_ranked_tables)} tables; injecting top {len(matched_tables)}.")
            
            chunks = []
            for kb_id, page, table_idx, hit_count in matched_tables:
                # Fetch ALL rows for this specific table to reconstruct it completely
                stmt = text("""
                    SELECT row_index, row_data 
                    FROM document_table_rows 
                    WHERE kb_id = :kb_id AND page_number = :page AND table_index = :table_idx
                    ORDER BY row_index ASC
                """)
                table_res = await self.db.execute(stmt, {"kb_id": kb_id, "page": page, "table_idx": table_idx})
                row_list = table_res.fetchall()
                if not row_list:
                    continue
                    
                # Determine all keys in order of appearance
                all_keys = []
                seen_keys = set()
                for r_idx, r_data in row_list:
                    if not r_data:
                        continue
                    for k in r_data.keys():
                        if k not in seen_keys:
                            seen_keys.add(k)
                            all_keys.append(k)
                
                if not all_keys:
                    continue
                    
                # Build markdown table
                headers = [str(k) for k in all_keys]
                md_lines = []
                md_lines.append("| " + " | ".join(headers) + " |")
                md_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
                
                for r_idx, r_data in row_list:
                    row_vals = [str(r_data.get(k, "")).replace("|", "\\|") for k in all_keys]
                    md_lines.append("| " + " | ".join(row_vals) + " |")
                    
                table_md = "\n".join(md_lines)
                
                # Fetch knowledge base name for source attribution
                stmt_kb = text("SELECT name FROM knowledge_bases WHERE id = :kb_id")
                kb_res = await self.db.execute(stmt_kb, {"kb_id": kb_id})
                kb_name = kb_res.scalar() or str(kb_id)
                
                source_str = f"{kb_name} Page {page}"
                
                # Use pre-computed hit_count for similarity score
                sim_score = min(1.0, hit_count / max(len(search_keywords), 1))
                
                # Tiered scoring formula: High-match tables get a boost, low-match tables do not outrank semantic text chunks
                if sim_score >= 0.5:
                    tbl_hybrid_score = 1.2 + sim_score  # Prioritized table
                else:
                    tbl_hybrid_score = 0.4 + sim_score  # Low-match table, kept but not prioritized
                
                # Create a virtual RetrievedChunk with tiered hybrid score
                chunks.append(RetrievedChunk(
                    chunk_id=f"table-{kb_id}-{page}-{table_idx}",
                    text=f"### Table from {source_str} (Page {page}, Table {table_idx}):\n\n{table_md}",
                    kb_id=str(kb_id),
                    position=page * 100 + table_idx,
                    embedding_similarity=sim_score,
                    graph_score=1.0,
                    hybrid_score=tbl_hybrid_score,
                    reason="TABLE_RECONSTRUCTED",
                    source=kb_name,
                    page=page
                ))
                
            return chunks
        except Exception as e:
            logger.error(f"Error in _retrieve_reconstructed_tables: {e}", exc_info=True)
            return []

    async def _score_chunks(



        self,



        seed_chunks: List[Dict],



        expanded_chunks: Dict[str, Dict],



        query_embedding: List[float],

        search_type: SearchType = SearchType.CHUNK_SEARCH,



    ) -> List[RetrievedChunk]:



        """



        Score chunks using hybrid scoring: semantic + graph connectivity.







        SCORING FORMULA:



        hybrid_score = 0.6 * embedding_similarity + 0.4 * graph_score







        Where:



        - embedding_similarity: Cosine similarity to query (01)



        - graph_score: Inverse distance from seed (seed=1.0, depth 1=0.75, depth 2=0.5)







        Args:



            seed_chunks: Seed chunks with similarity scores



            expanded_chunks: All expanded chunks with depth/connection



            query_embedding: Query embedding for similarity







        Returns:



            Sorted list of RetrievedChunk (highest score first)



        """



        scored = []







        # Determine adaptive weights for hybrid search based on SearchType
        if search_type == SearchType.CHUNK_SEARCH:
            vector_weight = 1.0
            graph_weight = 0.0
        elif search_type in [SearchType.ENTITY_CONNECTION, SearchType.CHAIN_OF_THOUGHT]:
            vector_weight = 0.3
            graph_weight = 0.7
        elif search_type == SearchType.GRAPH_SUMMARY:
            vector_weight = 0.5
            graph_weight = 0.5
        else:
            # Default / FALLBACK weight
            vector_weight = 0.6
            graph_weight = 0.4







        # Score seed chunks (already have embedding similarity)



        for seed in seed_chunks:



            # Graph score for seed: 1.0 (closest)



            graph_score = 1.0







            base_hybrid = vector_weight * seed["similarity"] + graph_weight * graph_score



            hybrid_score = base_hybrid * seed["weight"]







            scored.append(



                RetrievedChunk(



                    chunk_id=seed["chunk_id"],



                    text=seed["text"],



                    kb_id=seed["kb_id"],



                    position=seed["position"],



                    embedding_similarity=seed["similarity"],



                    graph_score=graph_score,



                    hybrid_score=hybrid_score,



                    reason="Seed chunk (semantic similarity)",



                    source=seed.get("source"),



                )



            )







        # Score expanded chunks (approximate embedding similarity from neighbors)



        for chunk_id, meta in expanded_chunks.items():



            if meta.get("depth", 0) == 0:



                continue  # Skip seeds (already scored)







            # Graph score based on depth (inverse distance)



            depth = meta.get("depth", 2)



            graph_score = max(0.3, 1.0 - (depth * 0.25))







            # Embedding similarity: interpolate from neighbors (heuristic)



            # For phase 2: Use graph_score as proxy



            embedding_similarity = graph_score * 0.7







            base_hybrid = vector_weight * embedding_similarity + graph_weight * graph_score



            hybrid_score = base_hybrid * meta.get("weight", 1.0)







            # Build reason based on connection type



            connection_type = meta.get("connection", "UNKNOWN")



            reason = f"{connection_type} connection (depth {depth})"







            scored.append(



                RetrievedChunk(



                    chunk_id=chunk_id,



                    text="",  # Will be fetched if needed



                    kb_id="",



                    position=0,



                    embedding_similarity=embedding_similarity,



                    graph_score=graph_score,



                    hybrid_score=hybrid_score,



                    reason=reason,



                )



            )







        # Sort by hybrid score (highest first)



        scored.sort(key=lambda x: x.hybrid_score, reverse=True)



        return scored







    def _select_context(



        self,



        scored_chunks: List[RetrievedChunk],



        max_tokens: int,



    ) -> List[RetrievedChunk]:



        """



        Select top chunks within token budget.







        DIVERSITY IMPROVEMENT:



        - Avoid selecting too many similar chunks (redundancy penalty)



        - Prefer diverse chunks that cover different topics



        - Max Marginal Relevance (MMR) approach







        Args:



            scored_chunks: Ranked chunks



            max_tokens: Token budget







        Returns:



            Selected chunks (ordered by score, highest first)



        """



        # Step 1: Apply diversity penalty (re-score to reduce redundancy)



        selected_with_diversity = self._apply_diversity_penalty(scored_chunks)







        # Step 2: Select top chunks within token budget



        selected = []



        token_count = 0







        for chunk in selected_with_diversity:



            # Estimate tokens (rough: words * 1.3)



            chunk_tokens = int(len(chunk.text.split()) * 1.3) if chunk.text else 0







            if token_count + chunk_tokens <= max_tokens:



                selected.append(chunk)



                token_count += chunk_tokens



            else:
                # Over budget for this chunk, skip and try other ones
                continue







        return selected







    def _apply_diversity_penalty(



        self,



        scored_chunks: List[RetrievedChunk],



    ) -> List[RetrievedChunk]:



        """



        Apply diversity penalty to reduce redundant chunks.







        ALGORITHM (Max Marginal Relevance):



        1. Start with highest-scored chunk



        2. For each remaining chunk:



            If too similar to selected chunks: penalize score



            Otherwise: keep original score



        3. Select next highest-scored chunk (accounting for penalties)



        4. Repeat until all scored







        PENALTY FORMULA:



        diversity_adjusted_score = 0.8 * original_score - 0.2 * max_similarity_to_selected







        Intuition:



        - If new chunk is similar to already-selected chunk, reduce its score



        - Prefer chunks that are highly relevant AND different from others



        """



        if not scored_chunks or len(scored_chunks) < 2:



            return scored_chunks







        # Track which chunks we've selected



        selected_indices = []



        adjusted_scores = {



            i: chunk.hybrid_score for i, chunk in enumerate(scored_chunks)



        }







        # Step 1: Always select highest-scored chunk first



        selected_indices.append(0)







        # Step 2: Iteratively select next-best chunk with diversity bonus



        while len(selected_indices) < len(scored_chunks):



            best_idx = None



            best_adjusted_score = -1.0







            for i, chunk in enumerate(scored_chunks):



                if i in selected_indices:



                    continue  # Already selected







                # Compute similarity to selected chunks



                max_similarity_to_selected = 0.0



                for selected_idx in selected_indices:



                    selected_chunk = scored_chunks[selected_idx]







                    # Heuristic: chunks from the same knowledge base (source document) are only redundant if they are close in position
                    if chunk.kb_id and selected_chunk.kb_id and chunk.kb_id == selected_chunk.kb_id:
                        # Check if this KB has small total_chunks
                        kb_meta = getattr(self, "_kb_metadata", {}).get(str(chunk.kb_id), {})
                        total_chunks = kb_meta.get("total_chunks", 0)
                        
                        # Also check if it's a syllabus / curriculum / small document based on source filename
                        is_small_doc = False
                        if total_chunks > 0 and total_chunks <= 15:
                            is_small_doc = True
                        else:
                            src_name = (chunk.source or "").lower()
                            if "syllabus" in src_name or "curriculum" in src_name:
                                is_small_doc = True

                        if chunk.reason == "TABLE_RECONSTRUCTED" or selected_chunk.reason == "TABLE_RECONSTRUCTED":
                            max_similarity_to_selected = max(
                                max_similarity_to_selected, 0.3
                            )
                        elif is_small_doc:
                            # Lower the proximity penalty for small documents / syllabus
                            pos_diff = abs(chunk.position - selected_chunk.position)
                            if pos_diff < 3:
                                max_similarity_to_selected = max(
                                    max_similarity_to_selected, 0.3
                                )
                            else:
                                max_similarity_to_selected = max(
                                    max_similarity_to_selected, 0.15
                                )
                        else:
                            pos_diff = abs(chunk.position - selected_chunk.position)
                            if pos_diff < 3:
                                max_similarity_to_selected = max(
                                    max_similarity_to_selected, 0.85
                                )
                            else:
                                # Chunks from different parts of the same document are not redundant
                                max_similarity_to_selected = max(
                                    max_similarity_to_selected, 0.3
                                )
                        
                        # If they also have the same non-seed reason, add a bit more similarity
                        if chunk.reason == selected_chunk.reason and chunk.reason not in ["Seed chunk (semantic similarity)", "TABLE_RECONSTRUCTED"]:
                            max_similarity_to_selected = max(
                                max_similarity_to_selected, 0.5
                            )







                # Apply diversity penalty
                adjusted_score = (0.6 * adjusted_scores[i]) - (
                    0.4 * max_similarity_to_selected
                )







                if adjusted_score > best_adjusted_score:



                    best_adjusted_score = adjusted_score



                    best_idx = i







            if best_idx is not None:



                selected_indices.append(best_idx)



            else:



                break







        # Return chunks in original score order (highest first)



        result = [scored_chunks[i] for i in selected_indices]



        # Result is already in MMR selection order



        return result







    async def _extract_entity_mentions(



        self,



        chunk_ids: Set[str],



    ) -> Dict[str, List[str]]:



        """



        Extract entities mentioned by selected chunks.







        Args:



            chunk_ids: Set of selected chunk IDs







        Returns:



            Dict mapping entity_text -> [chunk_ids mentioning it]



        """



        query = """



        WITH $chunk_ids AS chunk_list



        MATCH (c:Chunk {tenant_id: $tenant_id})



        WHERE c.id IN chunk_list



        MATCH (c)-[:MENTIONS]->(e:Entity {tenant_id: $tenant_id})



        RETURN e.text as entity_text, collect(c.id) as chunk_ids



        """







        try:



            results = await self.neo4j_repo.execute_read(



                query,



                {"chunk_ids": list(chunk_ids), "tenant_id": self.tenant_id},



            )







            entity_mentions = {}



            for result in results:



                entity_mentions[result["entity_text"]] = result["chunk_ids"]







            return entity_mentions







        except Exception as e:



            logger.warning(f" Failed to extract entity mentions: {e}")



            return {}



