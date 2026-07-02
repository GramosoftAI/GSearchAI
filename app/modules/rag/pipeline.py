"""



RAG Pipeline - Graph-first retrieval and ranking system



Phase 2 Step 4: Transforms Graph Intelligence into Production RAG



"""







import logging



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
    content_type: str = "original"












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



        top_k: int = 10,



        max_depth: int = 2,



        max_tokens: int = 3000,



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







        # STEP 0: ROUTE QUERY TO OPTIMAL SEARCH STRATEGY
        route_result = await self.router.route_query(query)
        search_type = route_result.intent
        rewritten_data = route_result.rewritten or {}
        extracted_keywords = rewritten_data.get("keywords", [])
        
        logger.info(f" Query Router selected strategy: {search_type.name} (Confidence: {route_result.confidence})")
        if extracted_keywords:
            logger.info(f" Query Rewriter extracted keywords: {extracted_keywords}")





        # STAGE 0.5: EARLY EXIT FOR TABLE ANALYTICS
        if search_type in [SearchType.TABLE_ANALYTICS, SearchType.DATA_ANALYSIS]:
            logger.info("   -> Intercepting query for SQL Table Analytics engine!")
            try:
                table_results = await self._execute_table_analytics(query, kb_ids)
                if table_results:
                    return RAGContext(
                        query=query,
                        chunks=[],
                        entity_mentions={},
                        total_tokens=0,
                        triplet_context=f"STRUCTURED TABLE ANALYTICS RESULTS:\n{table_results}",
                        search_type=search_type.name
                    )
                else:
                    logger.warning("   -> SQL Table Analytics returned no results. Falling back to vector search.")
                    search_type = SearchType.CHUNK_SEARCH
            except Exception as e:
                logger.error(f"   -> SQL Table Analytics failed: {e}. Falling back to vector search.", exc_info=True)
                search_type = SearchType.CHUNK_SEARCH

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
                stmt = text(f"SELECT DISTINCT entity_type, entity_value, page_number, entity_status FROM document_entities WHERE document_id IN ('{kb_ids_formatted}')")
                
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
                            "source": "document_entities",
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



            top_k = min(top_k * 2, 30)  # Broader initial sweep for summary



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



        query_embedding = await EmbeddingGenerator.generate_embedding(query)



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



        )



        logger.info(f" Scored {len(scored_chunks)} chunks")







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
                    stmt = select(DocumentChunk, KnowledgeBase.parsed_path).outerjoin(
                        KnowledgeBase, DocumentChunk.kb_id == KnowledgeBase.id
                    ).where(DocumentChunk.id.in_([UUID(cid) for cid in needed_chunk_ids]))
                    res = await self.db.execute(stmt)
                    
                    db_chunks = {}
                    for db_c, parsed_path in res.all():
                        db_chunks[str(db_c.id)] = (db_c, parsed_path)
                    
                    for chunk in context_chunks:
                        if chunk.chunk_id in db_chunks:
                            db_c, parsed_path = db_chunks[chunk.chunk_id]
                            if not chunk.text:
                                chunk.text = db_c.text or ""
                            if not chunk.kb_id:
                                chunk.kb_id = str(db_c.kb_id)
                            if chunk.position == 0:
                                chunk.position = db_c.chunk_index
                            if parsed_path:
                                chunk.content_type = "text/html" if parsed_path.endswith(".html") else "text/plain"
                except Exception as db_err:
                    logger.error(f"Failed to bulk fetch chunk details from PostgreSQL: {db_err}")

            # 2. Bulk query from Neo4j to fetch source metadata and fallback values
            try:
                neo_query = """
                MATCH (c:Chunk {tenant_id: $tenant_id})
                WHERE c.id IN $chunk_ids
                OPTIONAL MATCH (kb:KnowledgeBase {tenant_id: $tenant_id})-[:HAS_CHUNK]->(c)
                RETURN c.id as chunk_id, c.text as text, c.kb_id as kb_id, c.position as position, COALESCE(kb.s3_path, c.source, kb.name) as source, kb.parsed_path as parsed_path
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
                        chunk.source = n_c.get("source")
                        parsed_path = n_c.get("parsed_path")
                        if parsed_path:
                            chunk.content_type = "text/html" if parsed_path.endswith(".html") else "text/plain"

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

            personal_memories=personal_memories



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
                    .limit(top_k)
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
                            if any(term in chunk_text for term in exact_terms):
                                boosted_similarity = max(similarity, 0.85)
                                weight = 1.5

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
                        conditions.append(DocumentChunk.text.like(f"%{term}%"))
                    
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
                            .limit(top_k)
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
                                pg_chunks.append({
                                    "chunk_id": chunk_id,
                                    "text": chunk_text,
                                    "position": row.chunk_index,
                                    "kb_id": str(row.kb_id),
                                    "embedding": None,
                                    "similarity": max(float(row.similarity) if row.similarity else 0.5, 0.7),
                                    "weight": 1.2,
                                    "source": None
                                })
                                retrieved_ids.add(chunk_id)
                                added_count += 1
                        if added_count > 0:
                            logger.info(f" Exact keyword search fetched {added_count} additional matching chunks")

                logger.info(f" PostgreSQL pgvector/keyword retrieved {len(pg_chunks)} seed chunks")
                if pg_chunks:
                    pg_chunks.sort(key=lambda x: x["similarity"], reverse=True)
                    return pg_chunks[:top_k]

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
                    if any(term in chunk_text for term in exact_terms):
                        similarity = max(similarity, 0.85)
                        weight = 1.5

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

            return sorted_chunks[:top_k]

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
        
        debug_mode = os.environ.get("DEBUG_ANALYTICS", "False").lower() == "true"
        trace_log = []
        if debug_mode:
            trace_log.append(f"User Query:\n{query}\n\nIntent:\nTABLE_ANALYTICS\n")
            
        t_start = time.perf_counter()
        
        # 1. Fetch schema and parsed_path
        kb_query = "SELECT dataset_schema, parsed_path, source FROM knowledge_bases WHERE id = ANY(CAST(:kb_ids AS uuid[])) LIMIT 1;"
        result = await self.db.execute(text(kb_query), {"kb_ids": kb_ids})
        row = result.fetchone()
        
        if row:
            dataset_schema, parsed_path, source = row
        else:
            return None
            
        # 1.5. HYBRID PANDAS ENGINE ROUTING FOR CSV FILES
        if parsed_path and str(parsed_path).lower().endswith('.csv'):
            logger.info(" CSV File detected! Routing TABLE_ANALYTICS to PandasQueryEngine.")
            from .pandas_engine import PandasQueryEngine
            engine = PandasQueryEngine(self.llm_client)
            return await engine.execute_query(query, str(parsed_path))

        # (If not CSV, fallback to standard SQL generation)
        if not dataset_schema:
            sample_query = "SELECT row_data FROM document_table_rows WHERE kb_id = ANY(CAST(:kb_ids AS uuid[])) LIMIT 1;"
            result = await self.db.execute(text(sample_query), {"kb_ids": kb_ids})
            sample_row = result.scalar()
            if sample_row:
                dataset_schema = {k: "unknown" for k in sample_row.keys()}
            else:
                return None
                
        # 2. Ask LLM to generate JSON AST
        t_ast_start = time.perf_counter()
        prompt = f"""You are a Structured Query Planner. Convert the user's natural language query into a JSON Abstract Syntax Tree (AST) for tabular analytics.

AVAILABLE COLUMNS & TYPES:
{json.dumps(dataset_schema, indent=2)}

USER QUERY: {query}

INSTRUCTIONS:
Return ONLY valid JSON matching this schema exactly:
{{
  "operation": "string", // MUST be one of: "COUNT", "AVG", "MAX", "MIN", "SUM", "GROUP", "SORT", "FILTER"
  "target_field": "string | null", // The field to aggregate or target, or null
  "filters": [
    {{
      "field": "string", // The exact column name
      "operator": "string", // MUST be one of: "=", "!=", ">", "<", ">=", "<=", "ILIKE", "LIKE". Use ILIKE for case-insensitive substring searches (e.g., %Action%).
      "value": "string | number" // The value to compare. For ILIKE, wrap in % like "%Action%".
    }}
  ],
  "group_by": "string | null", // Field to group by
  "sort_by": "string | null", // Field to sort by
  "sort_dir": "string", // "ASC" or "DESC"
  "limit": 50 // Integer limit
}}

Return ONLY JSON, no markdown formatting.
"""

        generated_ast_str = await self.llm_client.generate(
            prompt=prompt,
            system_prompt="You are a Structured Query Planner. Return only JSON.",
            temperature=0.0,
            max_tokens=4000
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
            return f"Validation Error: Unsupported operation '{operation}'."
            
        numeric_types = ["float", "integer", "currency", "percentage"]
        if operation in ["AVG", "MAX", "MIN", "SUM"]:
            if not target_field:
                return f"Validation Error: Operation '{operation}' requires a target_field."
            if target_field not in dataset_schema:
                return f"Validation Error: Field '{target_field}' does not exist in this dataset."
            if dataset_schema[target_field] not in numeric_types:
                return f"Validation Error: {operation} cannot be applied to string field '{target_field}'"
                
        if operation == "GROUP":
            group_by = ast.get("group_by")
            if not group_by or group_by not in dataset_schema:
                return f"Validation Error: Unknown or missing group_by field '{group_by}'."
                
        sort_by = ast.get("sort_by")
        if sort_by and sort_by not in dataset_schema:
            return f"Validation Error: Unknown sort_by field '{sort_by}'."
            
        for f in ast.get("filters", []):
            field = f.get("field")
            if not field or field not in dataset_schema:
                return f"Validation Error: Unknown filter field '{field}'."
            op = str(f.get("operator", "=")).upper()
            if op not in ["=", "!=", ">", "<", ">=", "<=", "ILIKE", "LIKE", "CONTAINS"]:
                return f"Validation Error: Unsupported filter operator '{op}' for field '{field}'."

        t_ast_val = time.perf_counter() - t_val_start
        if debug_mode:
            trace_log.append(f"Validated AST:\n{json.dumps(ast, indent=2)}\n")

        # 3. Secure Backend Query Builder
        t_sql_start = time.perf_counter()
        select_clause = "row_data"
        if operation == "COUNT":
            select_clause = "COUNT(*)"
        elif operation in ["AVG", "MAX", "MIN", "SUM"] and target_field:
            select_clause = f"{operation}((row_data->>'{target_field}')::numeric)"
        elif operation == "GROUP" and ast.get("group_by"):
            group_field = ast.get("group_by")
            select_clause = f"row_data->>'{group_field}' as group_key, COUNT(*) as count"
            
        where_clauses = ["kb_id = ANY(CAST(:kb_ids AS uuid[]))"]
        params = {"kb_ids": kb_ids}
        
        # Build explainability parts
        explain_filters = []
        for i, f in enumerate(ast.get("filters", [])):
            field = f.get("field")
            op = str(f.get("operator", "=")).upper()
            val = f.get("value")
            
            # Translate contains to ILIKE
            if op == "CONTAINS":
                op = "ILIKE"
                if isinstance(val, str) and not val.startswith("%"):
                    val = f"%{val}%"
                    
            field_type = dataset_schema.get(field, "string")
            if field_type in numeric_types and op in [">", "<", ">=", "<=", "=", "!="]:
                where_clauses.append(f"(row_data->>'{field}')::numeric {op} :val_{i}")
            else:
                where_clauses.append(f"row_data->>'{field}' {op} :val_{i}")
                
            params[f"val_{i}"] = val
            explain_filters.append(f"{field} {op} {val}")
            
        where_str = " AND ".join(where_clauses)
        query_str = f"SELECT {select_clause} FROM document_table_rows WHERE {where_str}"
        
        if operation == "GROUP" and ast.get("group_by"):
            query_str += f" GROUP BY row_data->>'{ast['group_by']}'"
            
        if ast.get("sort_by"):
            sort_dir = "ASC" if str(ast.get("sort_dir", "DESC")).upper() == "ASC" else "DESC"
            sort_field = ast["sort_by"]
            
            if dataset_schema.get(sort_field) in numeric_types:
                query_str += f" ORDER BY (row_data->>'{sort_field}')::numeric {sort_dir}"
            else:
                query_str += f" ORDER BY row_data->>'{sort_field}' {sort_dir}"
        elif operation == "GROUP":
            query_str += " ORDER BY count DESC"
            
        limit = min(int(ast.get("limit", 50) or 50), 100)
        if operation not in ["COUNT"]:
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
            
            if not rows:
                logger.warning(f"SQL execution returned no records: {query_str}")
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
            
            return formatted + explanation
            
        except Exception as e:
            logger.error(f" SQL Execution Failed: {e}")
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







    async def _score_chunks(



        self,



        seed_chunks: List[Dict],



        expanded_chunks: Dict[str, Dict],



        query_embedding: List[float],



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







        # Score seed chunks (already have embedding similarity)



        for seed in seed_chunks:



            # Graph score for seed: 1.0 (closest)



            graph_score = 1.0







            base_hybrid = 0.6 * seed["similarity"] + 0.4 * graph_score



            hybrid_score = min(1.0, base_hybrid * seed["weight"])







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







            base_hybrid = 0.6 * embedding_similarity + 0.4 * graph_score



            hybrid_score = min(1.0, base_hybrid * meta.get("weight", 1.0))







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



                # Over budget, stop



                break







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







                    # Heuristic: chunks with same reason are likely similar



                    if chunk.reason == selected_chunk.reason:



                        max_similarity_to_selected = max(



                            max_similarity_to_selected, 0.9



                        )  # High similarity



                    # Heuristic: chunks with embedding sim difference



                    elif (



                        abs(



                            chunk.embedding_similarity



                            - selected_chunk.embedding_similarity



                        )



                        < 0.1



                    ):



                        max_similarity_to_selected = max(



                            max_similarity_to_selected, 0.7



                        )  # Moderate similarity







                # Apply diversity penalty



                adjusted_score = (0.8 * adjusted_scores[i]) - (



                    0.2 * max_similarity_to_selected



                )







                if adjusted_score > best_adjusted_score:



                    best_adjusted_score = adjusted_score



                    best_idx = i







            if best_idx is not None:



                selected_indices.append(best_idx)



            else:



                break







        # Return chunks in original score order (highest first)



        result = [scored_chunks[i] for i in sorted(selected_indices)]



        result.sort(key=lambda x: x.hybrid_score, reverse=True)



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



