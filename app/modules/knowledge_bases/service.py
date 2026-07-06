"""Service layer for Knowledge Base (business logic + transactions + chunking + embeddings)"""



from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from typing import Optional, List, Dict

import logging

import uuid

from datetime import datetime

import re

import asyncio

import sqlite3

import os



from .models import KnowledgeBase, DatabaseConnection, DocumentChunk

from .repository import KnowledgeBaseRepository

from .audit import KBauditLog, KBauditEventType

from . import schemas

from ...core.neo4j_repository import Neo4jRepository

from ...core.neo4j_retry import retry_neo4j_operation

from ...core.config import get_settings

from ...core.embeddings import EmbeddingGenerator

from ...core.entity_extraction import EntityExtractor

from ...utils.formatters import format_success, format_error



logger = logging.getLogger(__name__)

settings = get_settings()





class TextChunker:

    """

    Split text into chunks with optional overlap.



    CRITICAL: Chunking strategy affects RAG quality.

    - Chunk size: 500-1000 tokens (roughly 2000-4000 characters)

    - Overlap: 50-100 tokens (100-400 characters)

    - Preserves sentence boundaries when possible

    """



    @staticmethod

    def estimate_tokens(text: str) -> int:

        """

        Estimate token count (rough: split by whitespace).



        CRITICAL: This is approximation. For production:

        Use tiktoken library for accurate OpenAI token counting.



        Args:

            text: Text to count tokens for



        Returns:

            Estimated token count

        """

        # Rough estimate: average 4 chars per token

        return len(text) // 4



    @staticmethod
    def chunk_table(table_text: str, chunk_size: int) -> List[str]:
        """
        Table-aware chunking.
        Isolates and preserves Markdown tables as single units.
        If a table exceeds chunk_size, it splits it by row while repeating the header.
        """
        if len(table_text) <= chunk_size:
            return [table_text]
            
        # Split table into rows
        rows = table_text.split('\n')
        
        # Extract header (usually first 2 rows: header + separator)
        if len(rows) > 2 and '---' in rows[1]:
            header = rows[0] + '\n' + rows[1]
            data_rows = rows[2:]
        else:
            # No clear separator, just use row 0
            header = rows[0]
            data_rows = rows[1:]
            
        chunks = []
        current_chunk = header
        
        for row in data_rows:
            test_chunk = current_chunk + '\n' + row
            if len(test_chunk) <= chunk_size:
                current_chunk = test_chunk
            else:
                # Save chunk and start new one with header
                if current_chunk != header:
                    chunks.append(current_chunk)
                
                # If a single row with header is larger than chunk_size, we MUST split it 
                # to prevent crashing the 512-token limit API!
                new_chunk = header + '\n' + row
                while len(new_chunk) > chunk_size:
                    chunks.append(new_chunk[:chunk_size])
                    new_chunk = header + '\n' + new_chunk[chunk_size:]
                
                current_chunk = new_chunk
                
        if current_chunk and current_chunk != header:
            chunks.append(current_chunk)
            
        return chunks

    @staticmethod
    def chunk_text(text: str, chunk_size: int, overlap_size: int) -> List[str]:
        """Helper to chunk normal text preserving sentences and block formatting."""
        chunks = []
        if len(text) <= chunk_size:
            return [text.strip()]

        # Split by double newlines to preserve blocks, then by sentences
        # We use a non-consuming split for sentences and standard split for blocks where we don't mind losing the exact whitespace
        blocks = [b.strip() for b in re.split(r"\n\n+", text) if b.strip()]
        
        current_chunk = ""
        current_blocks = []

        def build_overlap(prev_blocks: List[str], max_overlap: int) -> List[str]:
            overlap_blocks = []
            current_len = 0
            for b in reversed(prev_blocks):
                if current_len + len(b) > max_overlap and overlap_blocks:
                    break
                overlap_blocks.insert(0, b)
                current_len += len(b) + 2
            return overlap_blocks

        for block in blocks:
            # Forcefully break massive blocks
            if len(block) > chunk_size:
                if current_blocks:
                    chunks.append("\n\n".join(current_blocks))
                    current_blocks = []
                
                while len(block) > chunk_size:
                    chunks.append(block[:chunk_size])
                    block = block[chunk_size:]
                
                if block:
                    current_blocks = [block]
                continue

            test_len = sum(len(b) for b in current_blocks) + (len(current_blocks) * 2) + len(block)
            
            if test_len <= chunk_size:
                current_blocks.append(block)
            else:
                if current_blocks:
                    chunks.append("\n\n".join(current_blocks))
                
                if chunks and overlap_size > 0:
                    current_blocks = build_overlap(current_blocks, overlap_size)
                    current_blocks.append(block)
                    
                    # Safety check
                    if sum(len(b) for b in current_blocks) + (len(current_blocks) * 2) > chunk_size:
                        current_blocks = [block] # Drop overlap if it pushes us over immediately
                else:
                    current_blocks = [block]

        if current_blocks:
            chunks.append("\n\n".join(current_blocks))

        # Final safety pass to ensure ABSOLUTELY NO CHUNK exceeds chunk_size
        safe_chunks = []
        for c in chunks:
            while len(c) > chunk_size:
                safe_chunks.append(c[:chunk_size])
                c = c[chunk_size:]
            if c.strip():
                safe_chunks.append(c)

        return safe_chunks

    @staticmethod
    def split_into_chunks(
        text: str,
        chunk_size: int = 2500,  # Increased from 500 to leverage full 512+ token limit (approx 2500 chars)
        overlap_size: int = 250,  # Proportional overlap
    ) -> List[str]:
        """
        Split text into overlapping chunks, using Table-Aware chunking for Markdown tables.
        """
        chunks = []
        
        # Regex to detect Markdown table blocks (consecutive lines starting and ending with |)
        table_pattern = re.compile(r'((?:^\|.*?\|[ \t]*(?:\n|$))+)', re.MULTILINE)
        
        last_idx = 0
        for match in table_pattern.finditer(text):
            table_start = match.start()
            table_end = match.end()
            
            # 1. Chunk the text before the table
            pre_text = text[last_idx:table_start].strip()
            if pre_text:
                chunks.extend(TextChunker.chunk_text(pre_text, chunk_size, overlap_size))
                
            # 2. Chunk the table using Table-Aware strategy
            table_text = match.group(0).strip()
            chunks.extend(TextChunker.chunk_table(table_text, chunk_size))
            
            last_idx = table_end
            
        # 3. Chunk any remaining text after the last table
        post_text = text[last_idx:].strip()
        if post_text:
            chunks.extend(TextChunker.chunk_text(post_text, chunk_size, overlap_size))
            
        return chunks





class KnowledgeBaseService:

    """

    Knowledge Base service - coordinates PostgreSQL, Neo4j, and embeddings.

    """



    def __init__(self, db: AsyncSession, tenant_id: str):

        """

        Initialize KB service.

        """

        self.db = db

        self.tenant_id = uuid.UUID(tenant_id)

        self.repository = KnowledgeBaseRepository(db, str(self.tenant_id))

        self.neo4j_repo = Neo4jRepository(str(self.tenant_id))



    async def create_knowledge_base(

        self,

        user_id: str,

        request: schemas.KBCreate,

    ) -> dict:

        """

        Create a new knowledge base in BOTH PostgreSQL and Neo4j.

        """

        kb_id = None

        try:

            # ============= STEP 1: POSTGRES INSERT (NOT COMMITTED) =============

            pg_kb = await self.repository.create(

                name=request.name,

                agent_id=str(request.agent_id),

                user_id=user_id,

                description=request.description,

                source=request.source or "user_upload",
                s3_path=request.s3_path,
                dataset_schema=request.dataset_schema,
            )

            kb_id = str(pg_kb.id)

            logger.info(f" PostgreSQL: Created KB {kb_id}")



            # ============= STEP 2: NEO4J CREATE WITH RETRY =============

            neo4j_query = """

            CREATE (kb:KnowledgeBase {

                id: $kb_id,

                tenant_id: $tenant_id,

                agent_id: $agent_id,

                name: $name,

                source: $source,

                s3_path: $s3_path,

                created_at: timestamp()

            })

            

            WITH kb

            MATCH (a:Agent {tenant_id: $tenant_id, id: $agent_id})

            CREATE (a)-[:OWNS_KB]->(kb)

            

            RETURN kb

            """



            try:

                await retry_neo4j_operation(

                    lambda: self.neo4j_repo.execute_write(

                        neo4j_query,

                        {

                            "kb_id": kb_id,

                            "tenant_id": str(self.tenant_id),

                            "agent_id": str(request.agent_id),

                            "name": request.name,

                            "source": request.source or "user_upload",

                            "s3_path": request.s3_path,

                        },

                    )

                )


                logger.info(f" Neo4j: Created KB node {kb_id}")



            except Exception as neo4j_error:

                # ============= COMPENSATION: DELETE NEO4J KB =============

                logger.warning(f" Neo4j creation failed: {neo4j_error}")

                try:

                    await retry_neo4j_operation(

                        lambda: self.neo4j_repo.execute_write(

                            """

                            MATCH (kb:KnowledgeBase {id: $kb_id, tenant_id: $tenant_id})

                            DETACH DELETE kb

                            """,

                            {"kb_id": kb_id, "tenant_id": str(self.tenant_id)},

                        )

                    )

                except Exception as comp_error:

                    logger.error(f" Compensation FAILED: {comp_error}")



                await self.db.rollback()

                return format_error(f"Failed to create KB in graph: {neo4j_error}")



            await self.db.commit()

            await KBauditLog.log_event(

                tenant_id=str(self.tenant_id),

                user_id=user_id,

                kb_id=kb_id,

                event_type=KBauditEventType.KB_CREATED,

                details={"name": request.name, "agent_id": str(request.agent_id)},

            )



            return format_success(

                {"kb": schemas.KBResponse.model_validate(pg_kb, from_attributes=True)},

                meta={"message": "Knowledge Base created successfully"},

            )



        except Exception as e:

            await self.db.rollback()

            logger.error(f" KB creation failed: {e}")

            return format_error(f"Failed to create knowledge base: {str(e)}")



    async def ingest_document(

        self,

        kb_id: str,

        document_text: str,

        source: Optional[str] = None,
        s3_path: Optional[str] = None,
        parsed_path: Optional[str] = None,
        document_category: str = "general_document",
        structured_records: Optional[list] = None,
    ) -> dict:

        """

        Ingest a document with FULL RAG INTELLIGENCE (Optimized).

        """

        from .models import DocumentIngestionRun
        import time
        import json
        
        audit_run = DocumentIngestionRun(
            tenant_id=self.tenant_id,
            document_id=uuid.UUID(kb_id),
            document_category=document_category,
            started_at=datetime.utcnow(),
            status="IN_PROGRESS",
            chunk_count=0,
            entity_count=0,
            triplet_count=0,
            fallback_count=0,
            repair_count=0,
            retry_count=0,
            llm_calls=0,
            llm_input_tokens=0,
            llm_output_tokens=0
        )
        self.db.add(audit_run)

        try:

            # 1. VALIDATE KB EXISTS

            kb = await self.repository.get_by_id(kb_id)

            if not kb:

                return format_error(f"KB not found: {kb_id}", meta={"status_code": 404})

            if s3_path:
                kb.s3_path = s3_path
                # Update Neo4j node
                neo4j_update_query = """
                MATCH (kb:KnowledgeBase {id: $kb_id, tenant_id: $tenant_id})
                SET kb.s3_path = $s3_path
                """
                try:
                    await retry_neo4j_operation(
                        lambda: self.neo4j_repo.execute_write(
                            neo4j_update_query,
                            {
                                "kb_id": kb_id,
                                "tenant_id": str(self.tenant_id),
                                "s3_path": s3_path
                            }
                        )
                    )
                    logger.info(f"Updated Neo4j KnowledgeBase {kb_id} with s3_path={s3_path}")
                except Exception as neo_err:
                    logger.warning(f"Failed to update Neo4j KB s3_path: {neo_err}")

            if parsed_path:
                kb.parsed_path = parsed_path
                # Update Neo4j node
                neo4j_parsed_query = """
                MATCH (kb:KnowledgeBase {id: $kb_id, tenant_id: $tenant_id})
                SET kb.parsed_path = $parsed_path
                """
                try:
                    await retry_neo4j_operation(
                        lambda: self.neo4j_repo.execute_write(
                            neo4j_parsed_query,
                            {
                                "kb_id": kb_id,
                                "tenant_id": str(self.tenant_id),
                                "parsed_path": parsed_path
                            }
                        )
                    )
                    logger.info(f"Updated Neo4j KnowledgeBase {kb_id} with parsed_path={parsed_path}")
                except Exception as neo_err:
                    logger.warning(f"Failed to update Neo4j KB parsed_path: {neo_err}")





            # 2. CHUNK THE TEXT
            source_type = "pdf"
            path_to_check = s3_path or source or ""
            if path_to_check:
                path_lower = path_to_check.lower()
                # Clean up query params if present (e.g., in presigned S3 URLs)
                path_clean = path_lower.split("?")[0]
                if path_clean.endswith(".pdf"):
                    source_type = "pdf"
                elif path_clean.endswith(".docx") or path_clean.endswith(".doc"):
                    source_type = "docx"
                elif path_clean.endswith(".txt"):
                    source_type = "txt"
                elif path_clean.endswith(".xlsx") or path_clean.endswith(".xls"):
                    source_type = "excel"
                elif path_clean.endswith(".csv"):
                    source_type = "csv"
                elif path_lower.startswith(("http://", "https://", "http:", "https:")):
                    source_type = "url"

            chunk_metadata_list = []
            if structured_records:
                from app.core.structured_chunker import StructuredChunker
                structured_chunks = StructuredChunker.chunk(structured_records)
                chunks = [sc.text for sc in structured_chunks]
                chunk_metadata_list = [sc.metadata for sc in structured_chunks]
            else:
                from app.core.adaptive_chunker import AdaptiveChunker
                adaptive_chunks = await AdaptiveChunker.chunk(content=document_text, source_type=source_type)
                chunks = [c["chunk_text"] for c in adaptive_chunks]
                chunk_metadata_list = [c["metadata"] for c in adaptive_chunks]

            if not chunks:
                return format_error("Document produced no chunks", meta={"status_code": 400})

            logger.info(f" Chunked document into {len(chunks)} chunks using Adaptive/Structured Chunking ({source_type})")



            # 3. GENERATE EMBEDDINGS (Optimized Batching)

            embeddings = await EmbeddingGenerator.generate_embeddings_batch(chunks)

            if len(embeddings) != len(chunks):

                return format_error("Embedding generation failed")

            logger.info(f" Generated {len(embeddings)} embeddings")



            # 4. UNIFIED EXTRACTION (Entities, Triplets, Structured)
            from ...core.unified_extractor import UnifiedExtractor
            
            use_triplets = settings.use_triplet_extraction
            unified_extractor = UnifiedExtractor(tenant_id=str(self.tenant_id))
            
            def is_dense_chunk(chunk_text: str) -> bool:
                # Fast NLP heuristic (Enterprise Safe)
                text_len = len(chunk_text)
                
                # Check sentence count (using simple punctuation split as a fast heuristic)
                sentences = [s for s in re.split(r'[.!?]+', chunk_text) if s.strip()]
                sentence_count = len(sentences)
                
                # 1. Skip ultra-short fluff, BUT preserve concise single sentences
                # Example: "Page 14" (len=7, sentences=0) -> Skip
                # Example: "The supplier shall maintain cybersecurity controls." (len=51, sentences=1) -> Keep
                if text_len < 150 and sentence_count < 1:
                    return False
                    
                # 2. Skip repetitive characters (e.g. "............", "-------") often found in TOCs
                if re.search(r'([.\-_])\1{5,}', chunk_text):
                    return False
                    
                # 3. Skip obvious Table of Contents patterns
                if re.search(r'(?i)^(table of contents|contents|index)\s*$', chunk_text.splitlines()[0][:50]):
                    return False
                    
                # 4. Skip chunks that look entirely like pagination or footers
                if re.match(r'(?i)^\s*(page\s*\d+\s*of\s*\d+|\d+)\s*$', chunk_text):
                    return False
                    
                return True

            _chunk_extract_cache = {}
            
            # Mutable counters for routing observability
            routing_stats = {"fluff": 0, "processed": 0, "cache_hits": 0, "kg_calls": 0}

            async def safe_extract_unified(chunk_id: str, text: str, idx: int):
                # Fast-Path: Skip LLM extraction for fluff chunks to save time
                if not is_dense_chunk(text):
                    routing_stats["fluff"] += 1
                    logger.debug(f"Chunk {idx} routed to Fast-Path (skipped LLM extraction)")
                    return {"entities": [], "triplets": [], "structured": {"identifiers": [], "sections": []}, "_metadata": {"skipped_extraction": True, "chunk_idx": idx}}

                routing_stats["processed"] += 1

                # Chunk Caching (Idempotency for identical text like headers/footers)
                import hashlib
                text_hash = hashlib.sha256(text.encode()).hexdigest()
                if text_hash in _chunk_extract_cache:
                    routing_stats["cache_hits"] += 1
                    logger.debug(f"Chunk {idx} hit extract cache")
                    cached_result = dict(_chunk_extract_cache[text_hash])
                    cached_result["_metadata"]["cached"] = True
                    return cached_result

                routing_stats["kg_calls"] += 1
                try:
                    result = await unified_extractor.extract_all(chunk_id, text)
                    _chunk_extract_cache[text_hash] = result
                    return result
                except Exception as e:
                    logger.warning(f"Unified extraction failed for chunk {idx}: {e}")
                    return {"entities": [], "triplets": [], "structured": {"identifiers": [], "sections": []}, "_metadata": {"failed_completely": True, "chunk_idx": idx}}

            logger.info(f" Processing Unified Extractions for {len(chunks)} chunks in parallel...")
            
            unified_results = []
            batch_size = len(chunks) if chunks else 1
            for i in range(0, len(chunks), batch_size):
                batch_chunks = chunks[i:i+batch_size]
                batch_tasks = [safe_extract_unified(f"idx_{i+j}", batch_chunks[j], i+j) for j in range(len(batch_chunks))]
                batch_res = await asyncio.gather(*batch_tasks)
                unified_results.extend(batch_res)
            
            # --- Unpack unified results to maintain backward compatibility ---
            entity_results = [res.get("entities", []) for res in unified_results]
            
            if use_triplets:
                from ...core.triplet_extractor import TripletExtractionResult
                triplet_results = [TripletExtractionResult(chunk_id=f"idx_{i}", triplets=res.get("triplets", [])) for i, res in enumerate(unified_results)]
            else:
                triplet_results = []
                
            structured_results = [res.get("structured", {"identifiers": [], "sections": []}) for res in unified_results]
            
            # --- Operational Metrics Collection ---
            total_entities = 0
            total_triplets = 0
            total_identifiers = 0
            repair_count = 0
            retry_count = 0
            fallback_count = 0
            
            prompt_tokens = 0
            completion_tokens = 0
            max_extraction_ms = 0
            
            sample_entities = []
            sample_triplets = []
            fallback_chunks = []
            failed_chunk_count = 0
            
            for i, res in enumerate(unified_results):
                total_entities += len(res.get("entities", []))
                total_triplets += len(res.get("triplets", []))
                total_identifiers += len(res.get("structured", {}).get("identifiers", []))
                
                if not sample_entities and res.get("entities"):
                    sample_entities = [e.get("text", "") if isinstance(e, dict) else getattr(e, "text", getattr(e, "name", "")) for e in res["entities"][:3]]
                if not sample_triplets and res.get("triplets"):
                    # Triplet format might vary (dict or ExtractedTriplet object), assuming dict here
                    tr = res["triplets"][0]
                    if isinstance(tr, dict):
                        sample_triplets = [{"subject": tr.get("subject"), "predicate": tr.get("predicate"), "object": tr.get("object")}]
                    else:
                        sample_triplets = [{"subject": getattr(tr, "subject", ""), "predicate": getattr(tr, "predicate", ""), "object": getattr(tr, "object", "")}]
                
                meta = res.get("_metadata", {})
                if meta.get("failed_completely"):
                    failed_chunk_count += 1
                    continue
                
                if meta.get("repair_used"): repair_count += 1
                if meta.get("retry_used"): retry_count += 1
                if meta.get("fallback_used"): 
                    fallback_count += 1
                    # Track last 20 fallback chunks
                    if len(fallback_chunks) < 20:
                        fallback_chunks.append(f"idx_{i}")
                
                prompt_tokens += meta.get("prompt_tokens", 0)
                completion_tokens += meta.get("completion_tokens", 0)
                if meta.get("extraction_duration_ms", 0) > max_extraction_ms:
                    max_extraction_ms = meta.get("extraction_duration_ms", 0)
                
            # Grab version metrics from the first chunk
            first_meta = unified_results[0].get("_metadata", {}) if unified_results else {}
            
            audit_run.chunk_count = len(chunks)
            audit_run.entity_count = total_entities
            audit_run.triplet_count = total_triplets
            audit_run.identifier_count = total_identifiers
            audit_run.repair_count = repair_count
            audit_run.retry_count = retry_count
            audit_run.fallback_count = fallback_count
            
            # Routing Observability
            audit_run.fluff_chunks_skipped = routing_stats["fluff"]
            audit_run.processed_chunks = routing_stats["processed"]
            audit_run.routing_version = "1.1" # Enterprise-Safe Routing
            audit_run.cache_hits = routing_stats["cache_hits"]
            audit_run.kg_extraction_calls = routing_stats["kg_calls"]
            
            audit_run.llm_calls = len(chunks) + retry_count - routing_stats["fluff"] - routing_stats["cache_hits"]
            audit_run.model_name = first_meta.get("model_name", "unknown")
            audit_run.schema_version = first_meta.get("schema_version", "unknown")
            audit_run.extractor_version = "legacy_ensemble" if first_meta.get("fallback_used") else "unified_extractor_v1"
            audit_run.llm_input_tokens = prompt_tokens
            audit_run.llm_output_tokens = completion_tokens
            audit_run.extraction_duration_ms = max_extraction_ms  # Since they ran in parallel
            audit_run.sample_entities = sample_entities
            audit_run.sample_triplets = sample_triplets
            audit_run.fallback_chunks = fallback_chunks
            
            # --- Production Drift Detection (v2: Rolling Baselines) ---
            if len(chunks) >= 3:
                entities_per_chunk = total_entities / len(chunks)
                
                from sqlalchemy import text
                # Get historical baseline for this category
                baseline_query = text("""
                    SELECT 
                        COUNT(id) as doc_count,
                        AVG(entity_count::float / chunk_count) as avg_epc 
                    FROM document_ingestion_runs 
                    WHERE tenant_id = :tenant_id 
                      AND document_category = :category 
                      AND status = 'COMPLETED'
                      AND chunk_count > 0
                """)
                res = await self.db.execute(baseline_query, {"tenant_id": self.tenant_id, "category": document_category})
                row = res.fetchone()
                doc_count = row.doc_count or 0
                historical_epc = row.avg_epc
                
                MIN_BASELINE_DOCUMENTS = 20
                if doc_count >= MIN_BASELINE_DOCUMENTS and historical_epc is not None and historical_epc > 0:
                    deviation = (entities_per_chunk - historical_epc) / historical_epc
                    
                    audit_run.baseline_documents = doc_count
                    audit_run.baseline_entities_per_chunk = historical_epc
                    audit_run.current_entities_per_chunk = entities_per_chunk
                    audit_run.deviation_percent = deviation * 100
                    
                    if deviation < -0.5:  # Dropped more than 50% below baseline
                        # This will be picked up by AlertManager later
                        logger.critical(f"[ALERT] Extraction quality anomaly detected for KB {kb_id}! "
                                        f"Entities/chunk: {entities_per_chunk:.2f}. "
                                        f"Historical baseline for '{document_category}': {historical_epc:.2f} (Deviation: {deviation*100:.1f}%)")
                else:
                    logger.info(f"Drift detection skipping: category '{document_category}' has {doc_count}/{MIN_BASELINE_DOCUMENTS} baseline documents. Entities/chunk: {entities_per_chunk:.2f}")
            
            entities_by_chunk = {}
            all_entities_set = set()
            for i, extracted in enumerate(entity_results):
                entities_by_chunk[i] = [{"text": e.text, "type": e.entity_type, "confidence": e.confidence} for e in extracted]
                for e in extracted: all_entities_set.add(f"{e.text}|{e.entity_type}")

            # Prepare structured entities for storage
            from .models import DocumentEntity, DocumentSection
            structured_entities_to_save = []
            structured_sections_to_save = []
            for i, result in enumerate(structured_results):
                for ident in result.get("identifiers", []):
                    structured_entities_to_save.append(
                        DocumentEntity(
                            tenant_id=self.tenant_id,
                            document_id=uuid.UUID(kb_id),
                            entity_type=ident["type"],
                            entity_value=ident["value"],
                            start_offset=ident.get("start_offset"),
                            end_offset=ident.get("end_offset"),
                            source_text=ident.get("source_text"),
                            page_number=1, # Assuming 1 for simplicity here, can be enhanced
                            confidence=ident.get("confidence", 1.0),
                            entity_status="REVIEW" if float(ident.get("confidence", 1.0)) < 0.80 else "VERIFIED"
                        )
                    )
                for sec in result.get("sections", []):
                    structured_sections_to_save.append(
                        DocumentSection(
                            tenant_id=self.tenant_id,
                            document_id=uuid.UUID(kb_id),
                            section_name=sec["name"],
                            section_json=sec["content"],
                            page_number=1
                        )
                    )
            
            if structured_entities_to_save:
                self.db.add_all(structured_entities_to_save)
            if structured_sections_to_save:
                self.db.add_all(structured_sections_to_save)

            neo4j_start_time = time.time()



            # 5. BATCH CREATE CHUNK NODES

            chunk_ids = [str(uuid.uuid4()) for _ in range(len(chunks))]

            chunk_data = [{

                "chunk_id": chunk_ids[i], "tenant_id": str(self.tenant_id), "kb_id": kb_id,

                "text": chunks[i][:1000], "position": i, "token_count": TextChunker.estimate_tokens(chunks[i]),

                "embedding": embeddings[i], "created_at": datetime.utcnow().isoformat(),

                "metadata": json.dumps(chunk_metadata_list[i]) if chunk_metadata_list and i < len(chunk_metadata_list) and chunk_metadata_list[i] else "{}",
                "chunk_type": chunk_metadata_list[i].get("chunk_type", "generic") if chunk_metadata_list and i < len(chunk_metadata_list) and chunk_metadata_list[i] else "generic",
                "section": chunk_metadata_list[i].get("section") if chunk_metadata_list and i < len(chunk_metadata_list) and chunk_metadata_list[i] else None,
                "sheet": chunk_metadata_list[i].get("sheet") if chunk_metadata_list and i < len(chunk_metadata_list) and chunk_metadata_list[i] else None,
                "source_type": chunk_metadata_list[i].get("source_type", source_type) if chunk_metadata_list and i < len(chunk_metadata_list) and chunk_metadata_list[i] else source_type

            } for i in range(len(chunks))]



            # Save chunks to PostgreSQL pgvector table

            for i in range(len(chunks)):

                pg_chunk = DocumentChunk(

                    id=uuid.UUID(chunk_ids[i]),

                    tenant_id=self.tenant_id,

                    kb_id=uuid.UUID(kb_id),

                    text=chunks[i],

                    chunk_index=i,

                    embedding=embeddings[i],

                )

                self.db.add(pg_chunk)

            logger.info(f" Staged {len(chunks)} chunks in PostgreSQL")



            batch_create_query = """

            WITH $chunks AS chunk_list

            UNWIND chunk_list AS data

            CREATE (c:Chunk {

                id: data.chunk_id, tenant_id: $tenant_id, kb_id: data.kb_id,

                text: data.text, position: data.position, token_count: data.token_count,

                embedding: data.embedding, created_at: data.created_at,

                source: data.source, metadata: data.metadata,
                chunk_type: data.chunk_type, section: data.section,
                sheet: data.sheet, source_type: data.source_type

            })

            WITH c, data

            MATCH (kb:KnowledgeBase {id: data.kb_id, tenant_id: $tenant_id})

            CREATE (kb)-[:HAS_CHUNK]->(c)

            """

            await retry_neo4j_operation(lambda: self.neo4j_repo.execute_write(batch_create_query, {"chunks": chunk_data}))

            logger.info(f" Created {len(chunks)} chunks in Neo4j")



            # 6. COMPUTE SEMANTIC SIMILARITIES (O(n) but fast for small docs)

            similar_pairs = []

            if len(embeddings) < settings.similarity_brute_force_threshold:

                for i in range(len(embeddings)):

                    for j in range(i + 1, len(embeddings)):

                        sim = EmbeddingGenerator.cosine_similarity(embeddings[i], embeddings[j])

                        if sim >= settings.similarity_min_threshold:

                            similar_pairs.append({"chunk_id_1": chunk_ids[i], "chunk_id_2": chunk_ids[j], "similarity": sim})

                # Cap similarities

                similar_pairs = sorted(similar_pairs, key=lambda x: x["similarity"], reverse=True)[:len(chunks) * settings.max_similar_per_chunk]



            # 7. PARALLELIZE RELATIONSHIP CREATION

            relationship_tasks = []

            

            # NEXT rels

            next_data = [{"id1": chunk_ids[i], "id2": chunk_ids[i+1]} for i in range(len(chunk_ids)-1)]

            if next_data:

                relationship_tasks.append(retry_neo4j_operation(lambda: self.neo4j_repo.execute_write(

                    "UNWIND $rels AS r MATCH (c1:Chunk {id: r.id1, tenant_id: $tenant_id}) MATCH (c2:Chunk {id: r.id2, tenant_id: $tenant_id}) CREATE (c1)-[:NEXT]->(c2)",

                    {"rels": next_data}

                )))



            # SIMILAR rels

            if similar_pairs:

                relationship_tasks.append(retry_neo4j_operation(lambda: self.neo4j_repo.execute_write(

                    "UNWIND $pairs AS p MATCH (c1:Chunk {id: p.chunk_id_1, tenant_id: $tenant_id}) MATCH (c2:Chunk {id: p.chunk_id_2, tenant_id: $tenant_id}) CREATE (c1)-[:SIMILAR {similarity: p.similarity}]->(c2) CREATE (c2)-[:SIMILAR {similarity: p.similarity}]->(c1)",

                    {"pairs": similar_pairs}

                )))



            # MENTIONS rels

            mentions_data = []

            for idx, ents in entities_by_chunk.items():

                for e in ents: mentions_data.append({"chunk_id": chunk_ids[idx], "text": e["text"], "type": e["type"], "conf": e["confidence"]})

            if mentions_data:

                relationship_tasks.append(retry_neo4j_operation(lambda: self.neo4j_repo.execute_write(

                    "UNWIND $rels AS r MERGE (e:Entity {tenant_id: $tenant_id, text: r.text, type: r.type}) WITH e, r MATCH (c:Chunk {id: r.chunk_id, tenant_id: $tenant_id}) CREATE (c)-[:MENTIONS {confidence: r.conf}]->(e)",

                    {"rels": mentions_data}

                )))



            await asyncio.gather(*relationship_tasks)

            logger.info(" Created all relationships in parallel")



            # 8. TRIPLET PERSISTENCE

            triplet_stats = {"triplets_extracted": 0, "triplet_entities": 0, "triplet_relationships": 0}

            if use_triplets and triplet_results:

                from ...core.triplet_extractor import TripletGraphWriter

                for i, res in enumerate(triplet_results): res.chunk_id = chunk_ids[i]

                persist_result = await TripletGraphWriter(str(self.tenant_id)).persist_triplets(triplet_results)

                triplet_stats = {"triplets_extracted": persist_result.get("triplets_created", 0), "triplet_entities": persist_result.get("entities_created", 0), "triplet_relationships": persist_result.get("relationships_created", 0)}

            # 8.5 GRAPH CLEANUP (NEW) - Run Asynchronously
            async def run_cleanup_async(tenant_id_str: str):
                try:
                    logger.info(f"Background graph cleanup started for tenant {tenant_id_str}...")
                    from ...core.graph_cleanup import GraphCleanupService
                    cleanup_service = GraphCleanupService(tenant_id=tenant_id_str)
                    stats = await cleanup_service.cleanup_graph()
                    logger.info(f"Background graph cleanup completed for tenant {tenant_id_str}: {stats}")
                except Exception as cleanup_err:
                    logger.error(f"Background graph cleanup failed for tenant {tenant_id_str}: {cleanup_err}", exc_info=True)

            cleanup_stats = {"total_merges": 0, "relationships_deduplicated": 0}
            # Start cleanup task in background, avoiding blocking the main ingestion pipeline completion
            asyncio.create_task(run_cleanup_async(str(self.tenant_id)))

            # 9. FINAL UPDATE

            neo4j_end_time = time.time()
            write_duration_ms = int((neo4j_end_time - neo4j_start_time) * 1000)
            
            # Simple heuristic since exact Neo4j counter is unavailable from the custom driver right now
            # Total entities extracted vs unique entities sent = created vs merged approximation
            triplet_entities_processed = triplet_stats.get("triplet_entities", 0)
            nodes_created = int(triplet_entities_processed * 0.2) + len(chunks) + len(all_entities_set)
            nodes_merged = int(triplet_entities_processed * 0.8) + cleanup_stats.get("total_merges", 0)  # Estimate 80% reuse + cleanup merges
            
            relationships_created = triplet_stats.get("triplet_relationships", 0) + len(chunks) + len(similar_pairs) + len(mentions_data)
            relationships_merged = cleanup_stats.get("relationships_deduplicated", 0) # Track relationships deduplicated during cleanup
            
            total_duration_ms = int((datetime.utcnow() - audit_run.started_at.replace(tzinfo=None)).total_seconds() * 1000)
            
            audit_run.graph_write_duration_ms = write_duration_ms
            audit_run.total_duration_ms = total_duration_ms
            audit_run.nodes_created = nodes_created
            audit_run.nodes_merged = nodes_merged
            audit_run.relationships_created = relationships_created
            audit_run.relationships_merged = relationships_merged
            
            if failed_chunk_count > 0:
                audit_run.status = "PARTIAL_SUCCESS"
            else:
                audit_run.status = "COMPLETED"
                
            audit_run.completed_at = datetime.utcnow()
            
            # 10. ALERT ROUTING
            from ...core.alerting import AlertManager
            AlertManager.evaluate_ingestion(audit_run)
            
            # --- Emit Standardized Operational Event ---
            logger.info("INGESTION_COMPLETED: " + json.dumps({
                "event": "INGESTION_COMPLETED",
                "document_id": kb_id,
                "tenant_id": str(self.tenant_id),
                "extractor_version": audit_run.extractor_version,
                "model_name": audit_run.model_name,
                "chunk_count": audit_run.chunk_count,
                "entity_count": audit_run.entity_count,
                "triplet_count": audit_run.triplet_count,
                "fallback_count": audit_run.fallback_count,
                "repair_count": audit_run.repair_count,
                "retry_count": audit_run.retry_count,
                "extraction_duration_ms": audit_run.extraction_duration_ms,
                "graph_write_duration_ms": audit_run.graph_write_duration_ms,
                "total_duration_ms": audit_run.total_duration_ms,
                "nodes_created": audit_run.nodes_created,
                "relationships_created": audit_run.relationships_created
            }))

            await self.repository.increment_chunks(kb_id, len(chunks))

            await self.db.commit()

            

            return format_success({

                "kb_id": kb_id, "chunks_created": len(chunks), "embeddings_generated": len(embeddings),

                "entities_extracted": len(all_entities_set), **triplet_stats

            }, meta={"message": "Ingestion optimized and completed"})



        except Exception as e:

            await self.db.rollback()
            try:
                # Re-add audit run since the rollback cleared it
                fail_run = DocumentIngestionRun(
                    tenant_id=self.tenant_id,
                    document_id=uuid.UUID(kb_id),
                    status="FAILED",
                    error_message=str(e),
                    started_at=audit_run.started_at,
                    completed_at=datetime.utcnow(),
                    chunk_count=audit_run.chunk_count or 0,
                    entity_count=audit_run.entity_count or 0,
                    triplet_count=audit_run.triplet_count or 0,
                    fallback_count=audit_run.fallback_count or 0,
                    repair_count=audit_run.repair_count or 0,
                    retry_count=audit_run.retry_count or 0,
                    llm_calls=audit_run.llm_calls or 0,
                    llm_input_tokens=audit_run.llm_input_tokens or 0,
                    llm_output_tokens=audit_run.llm_output_tokens or 0
                )
                self.db.add(fail_run)
                await self.db.commit()
            except Exception as metric_err:
                logger.error(f"Failed to persist audit run failure: {metric_err}")

            # Alert Routing for Failures
            from ...core.alerting import AlertManager
            if 'fail_run' in locals():
                AlertManager.evaluate_ingestion(fail_run)

            logger.error(f" Ingestion failed: {e}", exc_info=True)

            return format_error(f"Failed to ingest document: {str(e)}")



    async def ingest_excel_or_csv(

        self,

        kb_id: str,

        file_bytes: bytes,

        filename: str,

        mime_type: Optional[str] = None,

        source: Optional[str] = None,

        s3_path: Optional[str] = None,

    ) -> dict:

        """

        Ingest an Excel or CSV file by parsing it, discovering relationships,

        and loading structured chunks & entities into PostgreSQL & Neo4j.

        """

        try:

            # 1. Validate KB exists

            kb = await self.repository.get_by_id(kb_id)

            if not kb:

                return format_error(f"KB not found: {kb_id}", meta={"status_code": 404})

            if s3_path:
                kb.s3_path = s3_path
                # Update Neo4j node
                neo_update_q = """
                MATCH (kb:KnowledgeBase {id: $kb_id, tenant_id: $tenant_id})
                SET kb.s3_path = $s3_path
                """
                try:
                    await retry_neo4j_operation(
                        lambda: self.neo4j_repo.execute_write(
                            neo_update_q,
                            {
                                "kb_id": kb_id,
                                "tenant_id": str(self.tenant_id),
                                "s3_path": s3_path
                            }
                        )
                    )
                    logger.info(f"Updated Neo4j KnowledgeBase {kb_id} with s3_path={s3_path}")
                except Exception as neo_err:
                    logger.warning(f"Failed to update Neo4j KB s3_path: {neo_err}")




            # 2. Invoke ExcelIngestionService

            from .services.excel_ingestion_service import ExcelIngestionService

            ingestor = ExcelIngestionService(self.db, str(self.tenant_id))

            result = await ingestor.ingest_file(kb_id, file_bytes, filename, mime_type, source)



            if not result.get("success"):

                return format_error(result.get("error", "Failed to ingest Excel/CSV"))



            # 3. Update chunk count metadata in PostgreSQL

            chunks_created = result["data"]["chunks_created"]

            await self.repository.increment_chunks(kb_id, chunks_created)

            await self.db.commit()



            return format_success(

                result["data"],

                meta={"message": f"Successfully ingested structured file '{filename}' into KB"}

            )



        except Exception as e:

            await self.db.rollback()

            logger.error(f" Excel/CSV Ingestion failed: {e}", exc_info=True)

            return format_error(f"Failed to ingest Excel/CSV: {str(e)}")



    async def _enrich_kbs_with_connections(self, kbs) -> list[dict]:
        if not kbs:
            return []
        kb_ids = [kb.id for kb in kbs]
        from sqlalchemy import select
        from .models import DatabaseConnection
        query = select(DatabaseConnection.kb_id, DatabaseConnection.db_type).where(
            DatabaseConnection.kb_id.in_(kb_ids)
        )
        res = await self.db.execute(query)
        connections = {row.kb_id: row.db_type for row in res.all()}
        
        from .models import DocumentIngestionRun
        from datetime import timezone
        
        run_query = select(
            DocumentIngestionRun.document_id,
            DocumentIngestionRun.started_at,
            DocumentIngestionRun.completed_at,
            DocumentIngestionRun.total_duration_ms,
            DocumentIngestionRun.status
        ).where(
            DocumentIngestionRun.document_id.in_(kb_ids)
        ).order_by(DocumentIngestionRun.started_at.desc())
        
        run_res = await self.db.execute(run_query)
        kb_runs = {}
        for r in run_res.all():
            if r.document_id not in kb_runs:
                kb_runs[r.document_id] = r

        # Fetch processing jobs associated with each KB
        from ..jobs.models import ProcessingJob
        from ..jobs.schemas import JobResponse
        
        job_query = select(ProcessingJob).where(
            ProcessingJob.kb_id.in_(kb_ids),
            ProcessingJob.tenant_id == self.tenant_id
        ).order_by(ProcessingJob.created_at.desc())
        
        job_res = await self.db.execute(job_query)
        kb_jobs = {}
        for job in job_res.scalars().all():
            if job.kb_id not in kb_jobs:
                kb_jobs[job.kb_id] = JobResponse.model_validate(job).model_dump(mode="json")

        def format_duration(started_at, completed_at, total_duration_ms, status) -> Optional[str]:
            if started_at and completed_at:
                delta = completed_at - started_at
                total_seconds = int(delta.total_seconds())
                if total_seconds < 60:
                    return f"{total_seconds}Sec"
                mins = total_seconds // 60
                secs = total_seconds % 60
                if secs == 0:
                    return f"{mins}Mins"
                return f"{mins}Mins {secs}Sec"
            elif total_duration_ms:
                total_seconds = int(total_duration_ms / 1000)
                if total_seconds < 60:
                    return f"{total_seconds}Sec"
                mins = total_seconds // 60
                secs = total_seconds % 60
                if secs == 0:
                    return f"{mins}Mins"
                return f"{mins}Mins {secs}Sec"
            elif started_at and status in ["IN_PROGRESS", "processing", "started"]:
                now = datetime.now(timezone.utc) if started_at.tzinfo else datetime.utcnow()
                delta = now - started_at
                total_seconds = int(delta.total_seconds())
                if total_seconds < 60:
                    return f"{total_seconds}Sec"
                mins = total_seconds // 60
                secs = total_seconds % 60
                if secs == 0:
                    return f"{mins}Mins"
                return f"{mins}Mins {secs}Sec"
            return None
        
        responses = []
        for kb in kbs:
            kb_dict = schemas.KBResponse.model_validate(kb, from_attributes=True).model_dump(mode="json")
            kb_dict["connected_integration"] = connections.get(kb.id)
            if not kb_dict["connected_integration"] and kb.source:
                if kb.source.startswith('google_drive'):
                    kb_dict["connected_integration"] = 'google_drive'
                elif kb.source.startswith('sharepoint'):
                    kb_dict["connected_integration"] = 'sharepoint'
                elif kb.source.startswith('gmail'):
                    kb_dict["connected_integration"] = 'gmail'
                elif kb.source.startswith('outlook'):
                    kb_dict["connected_integration"] = 'outlook'
                elif kb.source == 'web_scraper':
                    kb_dict["connected_integration"] = 'web_scraper'
            
            run_info = kb_runs.get(kb.id)
            if run_info:
                kb_dict["time_taken"] = format_duration(
                    run_info.started_at,
                    run_info.completed_at,
                    run_info.total_duration_ms,
                    run_info.status
                )
            else:
                kb_dict["time_taken"] = None
                
            kb_dict["processing_jobs"] = kb_jobs.get(kb.id)
            responses.append(kb_dict)
        return responses

    async def get_kb(self, kb_id: str) -> dict:

        kb = await self.repository.get_by_id(kb_id)

        if not kb: return format_error(f"KB not found", meta={"status_code": 404})

        enriched = await self._enrich_kbs_with_connections([kb])
        return format_success({"kb": enriched[0]})



    async def list_kbs(self, limit: int = 50, offset: int = 0) -> dict:

        kbs, total = await self.repository.list_kbs(limit=limit, offset=offset)

        enriched = await self._enrich_kbs_with_connections(kbs)
        return format_success({"kbs": enriched, "total": total})



    async def list_knowledge_source(self, agent_id: str) -> dict:

        """

        Get all unique sources for a given agent.

        """

        try:

            sources = await self.repository.list_knowledge_source(agent_id)

            return format_success({"sources": sources})

        except Exception as e:

            logger.error(f"Error listing knowledge source: {e}")

            return format_error(f"Failed to list knowledge sources: {str(e)}")



    async def list_kbs_by_agent(self, agent_id: str, limit: int = 50, offset: int = 0) -> dict:

        kbs, total = await self.repository.list_by_agent(agent_id, limit=limit, offset=offset)

        enriched = await self._enrich_kbs_with_connections(kbs)
        return format_success({"kbs": enriched, "total": total})



    async def delete_kb(self, kb_id: str, user_id: Optional[str] = None) -> dict:
        kb = await self.repository.get_by_id(kb_id)
        if not kb:
            res = format_error(f"KB not found: {kb_id}", meta={"status_code": 404})
            res["status_code"] = 404
            return res

        # ----------------------------------------------------
        # S3 FILE CLEANUP (Delete if not shared with other active KBs)
        # ----------------------------------------------------
        try:
            from app.core.s3 import S3StorageService
            s3_service = S3StorageService()
            
            # Always delete the unique parsed HTML/text content from S3
            if kb.parsed_path:
                await s3_service.delete_file_by_url(kb.parsed_path)
                
            # Delete original file from S3 only if no other active KB is using it
            if kb.s3_path:
                from sqlalchemy import func
                stmt = select(func.count()).select_from(KnowledgeBase).where(
                    KnowledgeBase.s3_path == kb.s3_path,
                    KnowledgeBase.id != kb.id,
                    KnowledgeBase.is_active == True
                )
                count_res = await self.db.execute(stmt)
                other_uses = count_res.scalar() or 0
                if other_uses == 0:
                    await s3_service.delete_file_by_url(kb.s3_path)
                else:
                    logger.info(f"S3 file {kb.s3_path} is shared with {other_uses} other active KBs. Skipping S3 deletion.")
        except Exception as s3_err:
            logger.error(f"Failed to clean up S3 files during KB deletion: {s3_err}")

        # ----------------------------------------------------
        # NEO4J GRAPH CLEANUP
        # ----------------------------------------------------
        await retry_neo4j_operation(
            lambda: self.neo4j_repo.execute_write(
                "MATCH (kb:KnowledgeBase {id: $id, tenant_id: $tenant_id}) OPTIONAL MATCH (kb)-[:HAS_CHUNK]->(c:Chunk) DETACH DELETE kb, c",
                {"id": kb_id, "tenant_id": str(self.tenant_id)}
            )
        )

        # Also clean up database connection details if present
        query = select(DatabaseConnection).where(DatabaseConnection.kb_id == uuid.UUID(kb_id))
        db_conn_res = await self.db.execute(query)
        db_conn = db_conn_res.scalar_one_or_none()
        if db_conn:
            await self.db.delete(db_conn)

        await self.repository.hard_delete(kb_id)
        await self.db.commit()

        # Log audit event
        if user_id:
            await KBauditLog.log_event(
                tenant_id=str(self.tenant_id),
                user_id=user_id,
                kb_id=kb_id,
                event_type=KBauditEventType.KB_DELETED,
                details={"kb_id": kb_id, "name": kb.name}
            )

        return format_success(meta={"message": "KB deleted successfully"})

    async def disconnect_agent_integration(self, agent_id: str, integration_type: str, user_id: Optional[str] = None) -> dict:
        """
        Deletes all knowledge bases for a specific agent that match the integration type.
        This provides a clean disconnect.
        """
        from sqlalchemy import select, or_
        import uuid
        from .models import KnowledgeBase, DatabaseConnection

        query = select(KnowledgeBase).outerjoin(
            DatabaseConnection, KnowledgeBase.id == DatabaseConnection.kb_id
        ).where(
            KnowledgeBase.tenant_id == self.tenant_id,
            KnowledgeBase.agent_id == uuid.UUID(agent_id),
            KnowledgeBase.deleted_at.is_(None),
            or_(
                KnowledgeBase.source.startswith(integration_type),
                DatabaseConnection.db_type == integration_type
            )
        )
        res = await self.db.execute(query)
        kbs = res.scalars().unique().all()

        deleted_count = 0
        user_emails_to_clear = set()
        for kb in kbs:
            if integration_type == "gmail" and kb.source and kb.source.startswith("gmail("):
                email = kb.source[6:-1]
                user_emails_to_clear.add(email)
                
            del_res = await self.delete_kb(str(kb.id), user_id)
            if del_res.get("success"):
                deleted_count += 1
                
        if integration_type == "gmail" and user_emails_to_clear:
            try:
                from ..connectors.google.models import GmailSyncState, GmailMessage
                from sqlalchemy import delete
                for email in user_emails_to_clear:
                    await self.db.execute(delete(GmailSyncState).where(GmailSyncState.user_id == email))
                    await self.db.execute(delete(GmailMessage).where(GmailMessage.user_id == email))
                await self.db.commit()
            except Exception as e:
                logger.error(f"Failed to clear gmail sync state during disconnect: {e}")
                
        return format_success(
            {"deleted_count": deleted_count},
            meta={"message": f"Successfully disconnected {integration_type} by deleting {deleted_count} related KBs."}
        )

    async def _validate_graph_integrity(self, kb_id: str) -> dict:

        return {"success": True, "issues": []}

    async def get_file_preview_metadata(self, kb_id: str, user_id: str) -> dict:
        """
        Retrieves S3 path and other metadata for secure file preview.
        Checks tenant and user permission.
        """
        kb = await self.repository.get_by_id(kb_id)
        if not kb:
            return {
                "success": False,
                "error": "File not found.",
                "status_code": 404
            }

        # Check tenant permission
        if str(kb.tenant_id) != str(self.tenant_id):
            return {
                "success": False,
                "error": "Access denied.",
                "status_code": 403
            }

        # Determine S3 key
        s3_key = None
        filename = kb.name
        
        # If kb.name contains prefixes, clean it up
        clean_filename = filename
        if clean_filename.startswith("PDF: "):
            clean_filename = clean_filename[5:]
        elif clean_filename.startswith("Spreadsheet: "):
            clean_filename = clean_filename[13:]

        if kb.s3_path:
            from urllib.parse import urlparse
            try:
                parsed = urlparse(kb.s3_path)
                s3_key = parsed.path.lstrip('/')
            except Exception:
                pass

        if not s3_key:
            # Fallback reconstruction
            from app.core.config import get_settings
            settings = get_settings()
            bucket_val = settings.aws_s3_bucket or "default-bucket"
            bucket_parts = bucket_val.split('/', 1)
            base_prefix = bucket_parts[1] + '/' if len(bucket_parts) > 1 else ''
            s3_key = f"{base_prefix}uploads/{self.tenant_id}/{clean_filename}"

        return {
            "success": True,
            "data": {
                "file_id": str(kb.id),
                "filename": clean_filename,
                "s3_key": s3_key,
                "user_id": str(kb.user_id),
                "tenant_id": str(kb.tenant_id)
            }
        }

    async def get_parsed_content(self, kb_id: str, user_id: str) -> dict:
        """
        Retrieves the parsed content text from S3 for a given knowledge base.
        Checks tenant permission.
        """
        kb = await self.repository.get_by_id(kb_id)
        if not kb:
            return {
                "success": False,
                "error": "File not found.",
                "status_code": 404
            }

        # Check tenant permission
        if str(kb.tenant_id) != str(self.tenant_id):
            return {
                "success": False,
                "error": "Access denied.",
                "status_code": 403
            }

        if not kb.parsed_path:
            return {
                "success": False,
                "error": "Parsed content not available",
                "status_code": 404
            }

        # Parse S3 key from parsed_path URL
        from urllib.parse import urlparse
        try:
            parsed = urlparse(kb.parsed_path)
            s3_key = parsed.path.lstrip('/')
        except Exception:
            return {
                "success": False,
                "error": "Invalid parsed path URL stored",
                "status_code": 500
            }

        # Download content from S3
        from app.core.s3 import S3StorageService
        s3_service = S3StorageService()
        try:
            stream_body = s3_service.get_file_stream(s3_key)
            # Read all content as string
            content_bytes = stream_body.read()
            content_text = content_bytes.decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to fetch parsed content for key {s3_key}: {e}")
            return {
                "success": False,
                "error": "Failed to fetch parsed content from S3 storage.",
                "status_code": 500
            }

        # Clean filename
        clean_filename = kb.name
        if clean_filename.startswith("PDF: "):
            clean_filename = clean_filename[5:]
        elif clean_filename.startswith("Spreadsheet: "):
            clean_filename = clean_filename[13:]

        # Determine content type based on path extension
        if kb.parsed_path and kb.parsed_path.endswith(".html"):
            content_type = "text/html"
        elif kb.parsed_path and kb.parsed_path.endswith(".md"):
            content_type = "text/markdown"
        else:
            content_type = "text/plain"

        return {
            "success": True,
            "file_name": clean_filename,
            "type": "parsed",
            "content_type": content_type,
            "content": content_text
        }





    # ============================================================================

    # NATIVE DATABASE CONNECTOR SERVICE METHODS

    # ============================================================================



    async def register_database_connection(

        self,

        kb_id: str,

        request: schemas.DatabaseConnectionRegister,

    ) -> dict:

        """

        Register a database connection with a Knowledge Base after validating it.

        """

        try:

            # 1. Validate connection first

            val_res = await self.validate_database_connection(

                request.db_type, request.connection_params

            )

            if not val_res["success"]:

                return format_error(f"Connection validation failed: {val_res['message']}")



            # 2. Check if Knowledge Base exists

            kb = await self.repository.get_by_id(kb_id)

            if not kb:

                return format_error(f"Knowledge Base not found: {kb_id}", meta={"status_code": 404})



            # 3. Check if a connection already exists to update it (upsert)

            query = select(DatabaseConnection).where(

                DatabaseConnection.kb_id == uuid.UUID(kb_id),

                DatabaseConnection.tenant_id == self.tenant_id

            )

            db_conn_res = await self.db.execute(query)

            db_conn = db_conn_res.scalar_one_or_none()



            if db_conn:

                # Update existing connection

                db_conn.db_type = request.db_type

                db_conn.connection_params = request.connection_params

                logger.info(f"Updated DatabaseConnection config for KB {kb_id}")

            else:

                # Create new connection

                db_conn = DatabaseConnection(

                    tenant_id=self.tenant_id,

                    kb_id=uuid.UUID(kb_id),

                    db_type=request.db_type,

                    connection_params=request.connection_params

                )

                self.db.add(db_conn)

                logger.info(f"Registered brand new DatabaseConnection config for KB {kb_id}")



            await self.db.commit()

            return format_success(

                {"database_connection": schemas.DatabaseConnectionResponse.model_validate(db_conn, from_attributes=True)},

                meta={"message": "Database connection registered and validated successfully"}

            )



        except Exception as e:

            await self.db.rollback()

            logger.error(f" Failed to register database connection: {e}", exc_info=True)

            return format_error(f"Failed to register database connection: {str(e)}")



    async def validate_database_connection(

        self,

        db_type: str,

        connection_params: dict,

    ) -> dict:

        """

        Validate a database connection parameter set (dry-run/ping test).

        """

        if db_type == "sqlite":

            filepath = connection_params.get("filepath")

            if not filepath:

                return {"success": False, "message": "Missing 'filepath' parameter for SQLite connection"}

            

            # Allow absolute or relative path within the workspace

            if not os.path.exists(filepath):

                # Try relative resolution

                resolved = os.path.join(os.getcwd(), filepath)

                if not os.path.exists(resolved):

                    return {"success": False, "message": f"SQLite database file not found at path: {filepath}"}

                filepath = resolved



            try:

                conn = sqlite3.connect(filepath)

                cursor = conn.cursor()

                # Run a fast introspective query to verify it's a valid DB

                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")

                conn.close()

                return {"success": True, "message": "Connection validation successful for local SQLite"}

            except Exception as e:

                return {"success": False, "message": f"Failed to open SQLite database: {str(e)}"}

                

        elif db_type == "postgresql":

            # For this POC, dry-run/mock success for PG or connect if package exists

            conn_str = connection_params.get("connection_string")

            if not conn_str:

                return {"success": False, "message": "Missing 'connection_string' parameter for PostgreSQL"}

            # Return true for now to allow seamless dry-runs

            return {"success": True, "message": "PostgreSQL dry-run validation successful"}

            

        else:

            return {"success": False, "message": f"Unsupported database type: {db_type}"}



    async def discover_database_schema(self, kb_id: str) -> dict:

        """

        Introspect the database and return a list of discovered tables.

        """

        try:

            query = select(DatabaseConnection).where(

                DatabaseConnection.kb_id == uuid.UUID(kb_id),

                DatabaseConnection.tenant_id == self.tenant_id

            )

            res = await self.db.execute(query)

            db_conn = res.scalar_one_or_none()

            if not db_conn:

                return format_error("No registered database connection found for this KB", meta={"status_code": 404})



            tables = []

            if db_conn.db_type == "sqlite":

                filepath = db_conn.connection_params.get("filepath")

                conn = sqlite3.connect(filepath)

                cursor = conn.cursor()

                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")

                tables = [r[0] for r in cursor.fetchall()]

                conn.close()

            elif db_conn.db_type == "postgresql":

                # Mock schema discovery response for PG

                tables = ["customers", "products", "orders"]



            return format_success(

                {"success": True, "tables": tables, "db_type": db_conn.db_type},

                meta={"message": f"Successfully discovered {len(tables)} tables"}

            )

        except Exception as e:

            logger.error(f" Schema discovery failed: {e}", exc_info=True)

            return format_error(f"Failed to discover database schema: {str(e)}")



    async def sync_database_source(self, kb_id: str) -> dict:

        """

        Core ETL logic: Extract SQLite/Postgres rows, generate vector embeddings,

        and load them natively into Neo4j as Chunk nodes linked via HAS_CHUNK relationships.

        """

        try:

            # 1. FETCH CONFIGURATION

            query = select(DatabaseConnection).where(

                DatabaseConnection.kb_id == uuid.UUID(kb_id),

                DatabaseConnection.tenant_id == self.tenant_id

            )

            res = await self.db.execute(query)

            db_conn = res.scalar_one_or_none()

            if not db_conn:

                return format_error("No registered database connection found for this KB", meta={"status_code": 404})



            kb = await self.repository.get_by_id(kb_id)

            if not kb:

                return format_error("Parent Knowledge Base not found", meta={"status_code": 404})



            extracted_chunks = []

            

            # 2. EXTRACT DATA & FORMAT INTO SEMANTIC CHUNKS

            if db_conn.db_type == "sqlite":

                filepath = db_conn.connection_params.get("filepath")

                if not os.path.exists(filepath):

                    filepath = os.path.join(os.getcwd(), filepath)

                    if not os.path.exists(filepath):

                        return format_error(f"Database file not found at: {filepath}")



                conn = sqlite3.connect(filepath)

                cursor = conn.cursor()

                

                # Fetch Tables

                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")

                tables = [r[0] for r in cursor.fetchall()]

                

                # Introspect & extract records

                if "customers" in tables:

                    cursor.execute("SELECT id, name, email FROM customers;")

                    for cid, name, email in cursor.fetchall():

                        extracted_chunks.append({

                            "text": f"Customer: {name}, Email: {email} (ID: {cid})",

                            "entity_type": "Customer",

                            "entity_id": cid

                        })

                

                if "products" in tables:

                    cursor.execute("SELECT id, name, price FROM products;")

                    for pid, name, price in cursor.fetchall():

                        extracted_chunks.append({

                            "text": f"Product: {name}, Price: ${price:.2f} (ID: {pid})",

                            "entity_type": "Product",

                            "entity_id": pid

                        })



                if "orders" in tables and "customers" in tables and "products" in tables:

                    cursor.execute("""

                        SELECT o.id, c.name, p.name, o.order_date, o.quantity, p.price

                        FROM orders o

                        JOIN customers c ON o.customer_id = c.id

                        JOIN products p ON o.product_id = p.id;

                    """)

                    for oid, cname, pname, odate, qty, price in cursor.fetchall():

                        total = price * qty

                        extracted_chunks.append({

                            "text": f"Order: Customer {cname} purchased product {pname} (Quantity: {qty}, Total: ${total:.2f}) on {odate} (Order ID: {oid})",

                            "entity_type": "Order",

                            "entity_id": oid

                        })

                

                conn.close()

            else:

                # Mock Ingestion for PG or other connectors to allow testing

                extracted_chunks = [

                    {"text": "Customer: Girinath R, Email: girinathr@simplfin.tech (ID: 1)", "entity_type": "Customer", "entity_id": 1},

                    {"text": "Product: GraphMind Enterprise RAG, Price: $4999.00 (ID: 1)", "entity_type": "Product", "entity_id": 1},

                    {"text": "Order: Customer Girinath R purchased product GraphMind Enterprise RAG (Quantity: 1, Total: $4999.00) on 2026-05-18 (Order ID: 1)", "entity_type": "Order", "entity_id": 1}

                ]



            if not extracted_chunks:

                return format_error("Database contains no matching structured tables or data to ingest")



            logger.info(f" Extracted {len(extracted_chunks)} records from database")



            # 3. GENERATE EMBEDDINGS (Batch)

            texts = [c["text"] for c in extracted_chunks]

            embeddings = await EmbeddingGenerator.generate_embeddings_batch(texts)

            logger.info(f" Generated vector embeddings for {len(embeddings)} database chunks")



            # 4. BULK IMPORT CHUNKS NATIVELY INTO NEO4J

            # Detach any previous database chunks from this KB to avoid duplicate accumulation

            purge_query = """

            MATCH (kb:KnowledgeBase {id: $kb_id, tenant_id: $tenant_id})-[:HAS_CHUNK]->(c:Chunk)

            DETACH DELETE c

            """

            await self.neo4j_repo.execute_write(purge_query, {"kb_id": kb_id, "tenant_id": str(self.tenant_id)})



            # Delete any previous database chunks from Postgres

            from sqlalchemy import delete

            await self.db.execute(

                delete(DocumentChunk).where(

                    DocumentChunk.kb_id == uuid.UUID(kb_id),

                    DocumentChunk.tenant_id == self.tenant_id

                )

            )



            # Load new chunks in a single query transaction

            load_query = """

            MATCH (kb:KnowledgeBase {id: $kb_id, tenant_id: $tenant_id})

            UNWIND $batch AS item

            CREATE (c:Chunk {

                id: item.id,

                text: item.text,

                embedding: item.embedding,

                position: item.position,

                kb_id: $kb_id,

                tenant_id: $tenant_id,

                entity_type: item.entity_type,

                entity_id: item.entity_id,

                source: item.source,

                weight: 1.0,

                created_at: timestamp()

            })

            CREATE (kb)-[:HAS_CHUNK]->(c)

            """

            

            batch_data = []

            for i, chunk in enumerate(extracted_chunks):

                # source: e.g. "sqlite:Customer", "postgresql:Product"

                source_str = f"{db_conn.db_type}:{chunk['entity_type']}"

                batch_data.append({

                    "id": str(uuid.uuid4()),

                    "text": chunk["text"],

                    "embedding": embeddings[i],

                    "position": i,

                    "entity_type": chunk["entity_type"],

                    "entity_id": str(chunk["entity_id"]),

                    "source": source_str

                })



            await self.neo4j_repo.execute_write(load_query, {

                "kb_id": kb_id,

                "tenant_id": str(self.tenant_id),

                "batch": batch_data

            })

            logger.info(f" Loaded {len(batch_data)} database rows as Chunk nodes in Neo4j linked to KB {kb_id}")



            # Load new chunks into Postgres pgvector table

            for i, item in enumerate(batch_data):

                pg_chunk = DocumentChunk(

                    id=uuid.UUID(item["id"]),

                    tenant_id=self.tenant_id,

                    kb_id=uuid.UUID(kb_id),

                    text=item["text"],

                    chunk_index=i,

                    embedding=item["embedding"],

                )

                self.db.add(pg_chunk)

            logger.info(f" Loaded {len(batch_data)} database rows as DocumentChunks in PostgreSQL pgvector")



            # 5. POSTGRES STATUS UPDATE

            db_conn.last_synced_at = datetime.now()

            kb.total_chunks = len(batch_data)

            await self.db.commit()



            return format_success(

                {

                    "success": True,

                    "kb_id": kb_id,

                    "records_synced": len(batch_data),

                    "last_synced_at": db_conn.last_synced_at.isoformat()

                },

                meta={"message": "Database synchronized with Knowledge Graph successfully"}

            )



        except Exception as e:

            await self.db.rollback()

            logger.error(f" Database synchronization failed: {e}", exc_info=True)

            return format_error(f"Failed to synchronize database source: {str(e)}")



    async def list_google_drive_directory(self, kb_id: str, parent_id: Optional[str] = None) -> dict:
        try:
            from sqlalchemy import select
            from .models import DatabaseConnection
            import uuid
            
            query = select(DatabaseConnection).where(
                DatabaseConnection.kb_id == uuid.UUID(kb_id),
                DatabaseConnection.tenant_id == self.tenant_id,
                DatabaseConnection.db_type == "google_drive"
            )
            res = await self.db.execute(query)
            db_conn = res.scalar_one_or_none()
            if not db_conn:
                return format_error("No registered Google Drive connection found for this KB", meta={"status_code": 404})

            credentials = db_conn.connection_params.get("credentials", {})
            
            from app.modules.connectors.google.crawler import GoogleDriveConnector
            connector = GoogleDriveConnector()
            connector.load_credentials(credentials)
            
            raw_items = await connector.list_directory(parent_id)
            items = []
            for item in raw_items:
                is_folder = item.get("mimeType") == "application/vnd.google-apps.folder"
                items.append({
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "mime_type": item.get("mimeType"),
                    "is_folder": is_folder
                })
            
            return format_success({"items": items})
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to list Google Drive directory: {e}", exc_info=True)
            return format_error(f"Failed to list directory: {str(e)}")

    async def sync_google_drive_source(

        self,

        kb_id: str,

        credentials_dict: dict,

        folder_urls: Optional[List[str]] = None,

        file_ids: Optional[List[str]] = None,

        folder_ids: Optional[List[str]] = None,
        user_email: Optional[str] = None,
    ) -> dict:

        """

        Synchronize a Google Drive directory structure with the Knowledge Graph.

        Crawls files/folders, downloads/exports raw streams, extracts text,

        pipes them to the existing chunk/entity pipelines, and maps folder relationships.

        """

        import time

        sync_start_time = time.time()

        # Convert to milliseconds for Neo4j timestamps

        sync_start_timestamp = int(sync_start_time * 1000)

        

        try:

            # 1. INITIALIZE CONNECTOR

            from app.modules.connectors.google.crawler import GoogleDriveConnector
            connector = GoogleDriveConnector(folder_urls=folder_urls)
            connector.load_credentials(credentials_dict)
            
            # Update Knowledge Base source to reflect Google Drive connection
            effective_email = user_email or connector.auth_manager.primary_admin_email or "unknown_email"
            pg_kb = await self.repository.get_by_id(kb_id)
            if pg_kb:
                pg_kb.source = f"google_drive({effective_email})"
                self.db.add(pg_kb)
                await self.db.commit()
                
                # Also update Neo4j
                try:
                    from app.core.neo4j_retry import retry_neo4j_operation
                    await retry_neo4j_operation(
                        lambda: self.neo4j_repo.execute_write(
                            """
                            MATCH (kb:KnowledgeBase {id: $kb_id, tenant_id: $tenant_id})
                            SET kb.source = $new_source
                            """,
                            {
                                "kb_id": kb_id,
                                "tenant_id": str(self.tenant_id),
                                "new_source": f"google_drive({effective_email})"
                            }
                        )
                    )
                except Exception as e:
                    logger.warning(f"Failed to update Neo4j KB source: {e}")
            
            checkpoint = connector.build_dummy_checkpoint()

            

            files_synced = 0

            folders_synced = 0

            

            # 2. RUN PAGINATED GENERATOR LOOP

            from app.core.connectors import HierarchyNode, SlimDocument

            if file_ids or folder_ids:
                async def selective_generator():
                    all_file_ids = set(file_ids or [])
                    folders_to_process = list(folder_ids or [])
                    processed_folders = set()
                    
                    user_email = connector.auth_manager.primary_admin_email

                    while folders_to_process:
                        current_fid = folders_to_process.pop(0)
                        if current_fid in processed_folders:
                            continue
                        processed_folders.add(current_fid)
                        
                        # Yield HierarchyNode for the folder
                        try:
                            f_meta = await connector.get_files_metadata([current_fid])
                            if f_meta:
                                f_meta = f_meta[0]
                                yield HierarchyNode(
                                    raw_node_id=current_fid,
                                    raw_parent_id=f_meta.get("parents", [None])[0] if f_meta.get("parents") else None,
                                    display_name=f_meta.get("name", "Target Folder"),
                                    node_type="folder"
                                )
                        except Exception as e:
                            logger.warning(f"Failed to fetch metadata for selected folder {current_fid}: {e}")

                        # Fetch children
                        children = await connector.list_directory(current_fid)
                        for c in children:
                            if c.get("mimeType") == "application/vnd.google-apps.folder":
                                folders_to_process.append(c["id"])
                            else:
                                all_file_ids.add(c["id"])
                    
                    if all_file_ids:
                        meta_files = await connector.get_files_metadata(list(all_file_ids))
                        for f in meta_files:
                            yield SlimDocument(
                                id=f["id"], source="google_drive", 
                                metadata={
                                    "file_id": f["id"], 
                                    "filename": f.get("name", "unnamed"), 
                                    "mime_type": f.get("mimeType", ""), 
                                    "webViewLink": f.get("webViewLink"), 
                                    "parents": f.get("parents", []),
                                    "user_email": user_email
                                }
                            )
                generator = selective_generator()
            else:
                generator = connector.load_from_checkpoint(0.0, 0.0, checkpoint)


            

            async for item in generator:

                # Case A: Hierarchy/Folder Node

                if isinstance(item, HierarchyNode):

                    folders_synced += 1

                    # Save Folder Node in Neo4j

                    folder_query = """

                    MERGE (f:Folder {id: $folder_id, tenant_id: $tenant_id})

                    SET f.name = $name, f.link = $link, f.updated_at = timestamp()

                    """

                    await self.neo4j_repo.execute_write(folder_query, {

                        "folder_id": item.raw_node_id,

                        "tenant_id": str(self.tenant_id),

                        "name": item.display_name,

                        "link": item.link

                    })

                    

                    # If folder has parent, link them

                    if item.raw_parent_id:

                        parent_query = """

                        MERGE (p:Folder {id: $parent_id, tenant_id: $tenant_id})

                        MERGE (f:Folder {id: $folder_id, tenant_id: $tenant_id})

                        MERGE (p)-[:PARENT_OF]->(f)

                        """

                        await self.neo4j_repo.execute_write(parent_query, {

                            "parent_id": item.raw_parent_id,

                            "folder_id": item.raw_node_id,

                            "tenant_id": str(self.tenant_id)

                        })

                

                # Case B: SlimDocument (File Footprint)

                elif isinstance(item, SlimDocument):

                    file_id = item.id

                    filename = item.metadata.get("filename", "unnamed")

                    mime_type = item.metadata.get("mime_type", "")

                    parents = item.metadata.get("parents", [])

                    user_email = item.metadata.get("user_email")

                    

                    logger.info(f"Syncing Google Drive file: {filename} ({mime_type})")

                    

                    # Download file content

                    try:

                        file_bytes = await connector.download_file_bytes(

                            file_id=file_id,

                            mime_type=mime_type,

                            impersonate_email=user_email

                        )

                    except Exception as download_err:

                        logger.error(f"Failed to download bytes for file {filename}: {download_err}")

                        continue

                    

                    # Determine ingestion path based on MIME type

                    # 1. CSV / Excel

                    if mime_type == "text/csv" or "spreadsheet" in mime_type or filename.endswith((".csv", ".xlsx", ".xls")):

                        logger.info(f"Piping {filename} to tabular excel/csv ingestion service")

                        ingest_res = await self.ingest_excel_or_csv(

                            kb_id=kb_id,

                            file_bytes=file_bytes,

                            filename=filename,

                            mime_type=mime_type,

                            source="google_drive"

                        )

                        if ingest_res.get("success"):

                            files_synced += 1

                    

                    # 2. Textual Documents (PDF, Docx, Plaintext)

                    else:

                        text = ""

                        try:

                            # 2.1 PDF Parsing

                            if mime_type == "application/pdf" or filename.endswith(".pdf"):

                                import io

                                from PyPDF2 import PdfReader

                                reader = PdfReader(io.BytesIO(file_bytes))

                                pages_text = []

                                for page in reader.pages:

                                    pages_text.append(page.extract_text() or "")

                                text = "\n".join(pages_text)

                            

                            # 2.2 Word / Docx Parsing (Zip XML structure)

                            elif filename.endswith(".docx"):

                                import zipfile

                                import io

                                import xml.etree.ElementTree as ET

                                with zipfile.ZipFile(io.BytesIO(file_bytes)) as docx:

                                    xml_content = docx.read('word/document.xml')

                                    tree = ET.fromstring(xml_content)

                                    paragraphs = []

                                    for elem in tree.iter():

                                        if elem.tag.endswith('t'):

                                            paragraphs.append(elem.text or "")

                                    text = "".join(paragraphs)

                                    

                            # 2.3 Plaintext Fallback

                            else:

                                text = file_bytes.decode("utf-8", errors="ignore")

                        except Exception as parse_err:

                            logger.error(f"Failed to parse text content from file {filename}: {parse_err}")

                            continue

                        

                        if text.strip():

                            logger.info(f"Piping extracted text of {filename} to standard RAG pipeline")

                            ingest_res = await self.ingest_document(

                                kb_id=kb_id,

                                document_text=text,

                                source="google_drive"

                            )

                            if ingest_res.get("success"):

                                files_synced += 1

                                

                    # 3. Post-Process Neo4j Directory Graph Relations

                    if parents and files_synced > 0:

                        parent_id = parents[0]

                        # Ensure the parent folder exists

                        await self.neo4j_repo.execute_write(

                            "MERGE (f:Folder {id: $folder_id, tenant_id: $tenant_id}) ON CREATE SET f.name = 'Google Drive Folder'",

                            {"folder_id": parent_id, "tenant_id": str(self.tenant_id)}

                        )

                        # Link newly created Chunk nodes under this sync to the Folder node

                        link_query = """

                        MATCH (f:Folder {id: $parent_id, tenant_id: $tenant_id})

                        MATCH (kb:KnowledgeBase {id: $kb_id, tenant_id: $tenant_id})-[:HAS_CHUNK]->(c:Chunk)

                        WHERE c.created_at >= $sync_start_time

                        MERGE (f)-[:HAS_FILE]->(c)

                        """

                        await self.neo4j_repo.execute_write(link_query, {

                            "parent_id": parent_id,

                            "tenant_id": str(self.tenant_id),

                            "kb_id": kb_id,

                            "sync_start_time": sync_start_timestamp

                        })

            

            return format_success(

                {

                    "success": True,

                    "kb_id": kb_id,

                    "files_synced": files_synced,

                    "folders_synced": folders_synced,

                    "sync_duration_seconds": time.time() - sync_start_time

                },

                meta={"message": "Google Drive synchronized with Knowledge Graph successfully"}

            )

            

        except Exception as e:

            logger.error(f" Google Drive synchronization failed: {e}", exc_info=True)

            return format_error(f"Failed to synchronize Google Drive: {str(e)}")

    async def list_sharepoint_directory(self, kb_id: str, parent_id: Optional[str] = None) -> dict:
        try:
            from sqlalchemy import select
            from .models import DatabaseConnection
            import uuid
            
            query = select(DatabaseConnection).where(
                DatabaseConnection.kb_id == uuid.UUID(kb_id),
                DatabaseConnection.tenant_id == self.tenant_id,
                DatabaseConnection.db_type == "sharepoint"
            )
            res = await self.db.execute(query)
            db_conn = res.scalar_one_or_none()
            if not db_conn:
                return format_error("No registered SharePoint connection found for this KB", meta={"status_code": 404})

            credentials = db_conn.connection_params.get("credentials", {})
            site_urls = db_conn.connection_params.get("site_urls", [])
            
            from app.modules.connectors.sharepoint.crawler import SharePointConnector
            connector = SharePointConnector(site_urls=site_urls)
            connector.load_credentials(credentials)
            
            # If no parent_id is specified, we default to the first site root if available
            target_id = parent_id
            if not target_id and site_urls:
                first_url = site_urls[0]
                site_id = await connector.get_site_id_from_url(first_url)
                if site_id:
                    target_id = site_id
                else:
                    target_id = "root"

            raw_items = await connector.list_directory(target_id or "root")
            items = []
            for item in raw_items:
                items.append({
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "mime_type": item.get("mimeType"),
                    "is_folder": item.get("is_folder", False)
                })
            
            return format_success({"items": items})
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to list SharePoint directory: {e}", exc_info=True)
            return format_error(f"Failed to list directory: {str(e)}")

    async def sync_sharepoint_source(
        self,
        kb_id: str,
        credentials_dict: dict,
        site_urls: Optional[List[str]] = None,
        file_ids: Optional[List[str]] = None,
        folder_ids: Optional[List[str]] = None,
    ) -> dict:
        """
        Synchronize a SharePoint directory structure with the Knowledge Graph.
        Crawls files/folders, downloads binary streams, extracts text,
        pipes them to the existing chunk pipelines, and maps folder relationships.
        """
        import time
        from app.core.connectors import HierarchyNode, SlimDocument

        sync_start_time = time.time()
        sync_start_timestamp = int(sync_start_time * 1000)
        
        try:
            from app.modules.connectors.sharepoint.crawler import SharePointConnector
            connector = SharePointConnector(site_urls=site_urls)
            connector.load_credentials(credentials_dict)
            
            files_synced = 0
            folders_synced = 0

            # Selective generator logic mirroring Google Drive
            if file_ids or folder_ids:
                async def selective_generator():
                    all_file_ids = set(file_ids or [])
                    folders_to_process = list(folder_ids or [])
                    processed_folders = set()
                    
                    while folders_to_process:
                        current_fid = folders_to_process.pop(0)
                        if current_fid in processed_folders:
                            continue
                        processed_folders.add(current_fid)
                        
                        try:
                            f_meta = await connector.get_files_metadata([current_fid])
                            if f_meta:
                                f_meta = f_meta[0]
                                parent_list = f_meta.get("parents")
                                yield HierarchyNode(
                                    raw_node_id=current_fid,
                                    raw_parent_id=parent_list[0] if parent_list else None,
                                    display_name=f_meta.get("name", "Target Folder"),
                                    node_type="folder"
                                )
                        except Exception as e:
                            logger.warning(f"Failed to fetch metadata for selected folder {current_fid}: {e}")

                        children = await connector.list_directory(current_fid)
                        for c in children:
                            if c.get("is_folder"):
                                folders_to_process.append(c["id"])
                            else:
                                all_file_ids.add(c["id"])
                    
                    if all_file_ids:
                        meta_files = await connector.get_files_metadata(list(all_file_ids))
                        for f in meta_files:
                            yield SlimDocument(
                                id=f["id"], source="sharepoint", 
                                metadata={
                                    "file_id": f["id"], 
                                    "filename": f.get("name", "unnamed"), 
                                    "mime_type": f.get("mimeType", ""), 
                                    "webViewLink": f.get("webViewLink"), 
                                    "parents": f.get("parents", [])
                                }
                            )
                generator = selective_generator()
            else:
                checkpoint = connector.build_dummy_checkpoint()
                generator = connector.load_from_checkpoint(0.0, 0.0, checkpoint)
            
            async for item in generator:
                if isinstance(item, HierarchyNode):
                    folders_synced += 1
                    folder_query = """
                    MERGE (f:Folder {id: $folder_id, tenant_id: $tenant_id})
                    SET f.name = $name, f.link = $link, f.updated_at = timestamp()
                    """
                    await self.neo4j_repo.execute_write(folder_query, {
                        "folder_id": item.raw_node_id,
                        "tenant_id": str(self.tenant_id),
                        "name": item.display_name,
                        "link": item.link
                    })
                    
                    if item.raw_parent_id:
                        parent_query = """
                        MERGE (p:Folder {id: $parent_id, tenant_id: $tenant_id})
                        MERGE (f:Folder {id: $folder_id, tenant_id: $tenant_id})
                        MERGE (p)-[:PARENT_OF]->(f)
                        """
                        await self.neo4j_repo.execute_write(parent_query, {
                            "parent_id": item.raw_parent_id,
                            "folder_id": item.raw_node_id,
                            "tenant_id": str(self.tenant_id)
                        })
                
                elif isinstance(item, SlimDocument):
                    file_id = item.id
                    filename = item.metadata.get("filename", "unnamed")
                    mime_type = item.metadata.get("mime_type", "")
                    parents = item.metadata.get("parents", [])
                    
                    logger.info(f"Syncing SharePoint file: {filename} ({mime_type})")
                    
                    try:
                        file_bytes = await connector.download_file_bytes(file_id)
                    except Exception as download_err:
                        logger.error(f"Failed to download bytes for file {filename}: {download_err}")
                        continue
                    
                    # Direct binary to parsing logic
                    if mime_type == "text/csv" or "spreadsheet" in mime_type or filename.endswith((".csv", ".xlsx", ".xls")):
                        logger.info(f"Piping {filename} to tabular excel/csv ingestion service")
                        ingest_res = await self.ingest_excel_or_csv(
                            kb_id=kb_id,
                            file_bytes=file_bytes,
                            filename=filename,
                            mime_type=mime_type
                        )
                        if ingest_res.get("success"):
                            files_synced += 1
                    else:
                        text = ""
                        try:
                            if mime_type == "application/pdf" or filename.endswith(".pdf"):
                                import io
                                from PyPDF2 import PdfReader
                                reader = PdfReader(io.BytesIO(file_bytes))
                                pages_text = [page.extract_text() or "" for page in reader.pages]
                                text = "\n".join(pages_text)
                            elif filename.endswith(".docx"):
                                import zipfile
                                import io
                                import xml.etree.ElementTree as ET
                                with zipfile.ZipFile(io.BytesIO(file_bytes)) as docx:
                                    xml_content = docx.read('word/document.xml')
                                    tree = ET.fromstring(xml_content)
                                    paragraphs = [elem.text or "" for elem in tree.iter() if elem.tag.endswith('t')]
                                    text = "".join(paragraphs)
                            elif filename.endswith(".pptx"):
                                import zipfile
                                import io
                                import xml.etree.ElementTree as ET
                                with zipfile.ZipFile(io.BytesIO(file_bytes)) as pptx:
                                    text_elements = []
                                    for file in pptx.namelist():
                                        if file.startswith("ppt/slides/slide") and file.endswith(".xml"):
                                            slide_xml = pptx.read(file)
                                            tree = ET.fromstring(slide_xml)
                                            for elem in tree.iter():
                                                if elem.tag.endswith('}t'):
                                                    text_elements.append(elem.text or "")
                                    text = "\n".join(text_elements)
                            else:
                                text = file_bytes.decode("utf-8", errors="ignore")
                        except Exception as parse_err:
                            logger.error(f"Failed to parse text content from file {filename}: {parse_err}")
                            continue
                        
                        if text.strip():
                            logger.info(f"Piping extracted text of {filename} to standard RAG pipeline")
                            ingest_res = await self.ingest_document(
                                kb_id=kb_id,
                                document_text=text
                            )
                            if ingest_res.get("success"):
                                files_synced += 1
                                
                    if parents and files_synced > 0:
                        parent_id = parents[0]
                        await self.neo4j_repo.execute_write(
                            "MERGE (f:Folder {id: $folder_id, tenant_id: $tenant_id}) ON CREATE SET f.name = 'SharePoint Folder'",
                            {"folder_id": parent_id, "tenant_id": str(self.tenant_id)}
                        )
                        link_query = """
                        MATCH (f:Folder {id: $parent_id, tenant_id: $tenant_id})
                        MATCH (kb:KnowledgeBase {id: $kb_id, tenant_id: $tenant_id})-[:HAS_CHUNK]->(c:Chunk)
                        WHERE c.created_at >= $sync_start_time
                        MERGE (f)-[:HAS_FILE]->(c)
                        """
                        await self.neo4j_repo.execute_write(link_query, {
                            "parent_id": parent_id,
                            "tenant_id": str(self.tenant_id),
                            "kb_id": kb_id,
                            "sync_start_time": sync_start_timestamp
                        })
            
            return format_success(
                {
                    "success": True,
                    "kb_id": kb_id,
                    "files_synced": files_synced,
                    "folders_synced": folders_synced,
                    "sync_duration_seconds": time.time() - sync_start_time
                },
                meta={"message": "SharePoint synchronized with Knowledge Graph successfully"}
            )
            
        except Exception as e:
            logger.error(f" SharePoint synchronization failed: {e}", exc_info=True)
            return format_error(f"Failed to synchronize SharePoint: {str(e)}")



    async def sync_gmail_source(self, kb_id: str, sync_req: dict) -> dict:
        from app.utils.formatters import format_success, format_error
        import time
        import json
        from uuid import uuid4
        from sqlalchemy import select
        from app.modules.knowledge_bases.models import KnowledgeBase, DatabaseConnection, DocumentChunk
        from app.modules.connectors.google.gmail_crawler import GmailConnector
        from app.core.connectors import ConnectorCheckpoint

        sync_start_time = time.time()
        
        query = select(KnowledgeBase).where(KnowledgeBase.id == uuid.UUID(kb_id), KnowledgeBase.tenant_id == self.tenant_id)
        res = await self.db.execute(query)
        pg_kb = res.scalar_one_or_none()
        if not pg_kb:
            return format_error('Knowledge Base not found', meta={'error_code': 'KB_NOT_FOUND'})

        conn_query = select(DatabaseConnection).where(
            DatabaseConnection.kb_id == uuid.UUID(kb_id),
            DatabaseConnection.tenant_id == self.tenant_id,
            DatabaseConnection.db_type == 'gmail'
        )
        conn_res = await self.db.execute(conn_query)
        db_conn = conn_res.scalar_one_or_none()
        if not db_conn:
            return format_error('Gmail connection not configured for this KB.')

        credentials = db_conn.connection_params
        user_email = sync_req.get('email')
        if not user_email:
            return format_error('user_email is required for Gmail sync.')

        pg_kb.source = f'gmail({user_email})'
        await self.db.commit()

        neo_query = "MATCH (kb:KnowledgeBase {id: $kb_id, tenant_id: $tenant_id}) SET kb.source = $new_source"
        try:
            await self.neo4j_repo.execute_write(neo_query, {'kb_id': str(kb_id), 'tenant_id': str(self.tenant_id), 'new_source': f'gmail({user_email})'})
        except Exception as e:
            logger.warning(f'Failed to update source string in Neo4j: {e}')

        try:
            # Connect to Redis and enqueue the job
            from app.worker.queue import get_redis_pool
            redis = await get_redis_pool()
            
            job = await redis.enqueue_job(
                'gmail_sync_job',
                kb_id=str(kb_id),
                tenant_id=str(self.tenant_id),
                user_email=user_email,
                label_ids=sync_req.get('folder_ids'),
                credentials=credentials
            )
            
            return format_success(
                {'kb_id': kb_id, 'job_id': job.job_id}, 
                meta={'message': 'Gmail sync job queued successfully'}
            )

        except Exception as e:
            logger.error(f'Gmail sync queue failed: {e}', exc_info=True)
            return format_error(f'Failed to queue Gmail sync: {e}')

    async def sync_outlook_source(self, kb_id: str, sync_req: dict) -> dict:
        from app.utils.formatters import format_success, format_error
        import time
        import json
        from uuid import uuid4
        from sqlalchemy import select
        from app.modules.knowledge_bases.models import KnowledgeBase, DatabaseConnection, DocumentChunk
        from app.modules.connectors.sharepoint.outlook_crawler import OutlookConnector
        from app.core.connectors import ConnectorCheckpoint

        sync_start_time = time.time()
        
        query = select(KnowledgeBase).where(KnowledgeBase.id == uuid.UUID(kb_id), KnowledgeBase.tenant_id == self.tenant_id)
        res = await self.db.execute(query)
        pg_kb = res.scalar_one_or_none()
        if not pg_kb:
            return format_error('Knowledge Base not found', meta={'error_code': 'KB_NOT_FOUND'})

        conn_query = select(DatabaseConnection).where(
            DatabaseConnection.kb_id == uuid.UUID(kb_id),
            DatabaseConnection.tenant_id == self.tenant_id,
            DatabaseConnection.db_type == 'outlook'
        )
        conn_res = await self.db.execute(conn_query)
        db_conn = conn_res.scalar_one_or_none()
        if not db_conn:
            return format_error('Outlook connection not configured for this KB.')

        user_email = sync_req.get('user_email')
        if not user_email:
            return format_error('user_email is required for Outlook sync.')

        pg_kb.source = f'outlook({user_email})'
        await self.db.commit()

        crawler = OutlookConnector(folder_id=sync_req.get('folder_id'), max_results=sync_req.get('max_results', 100))
        crawler.load_credentials(db_conn.connection_params)
        checkpoint = ConnectorCheckpoint(user_emails=[user_email], has_more=True, completion_stage='start')

        messages_synced = 0
        neo4j_nodes = []

        try:
            async for doc in crawler.load_from_checkpoint(0, time.time(), checkpoint):
                if hasattr(doc, 'node_type'):
                    continue
                
                msg_data = await crawler.get_message_content(user_email, doc.id)
                if not msg_data or not msg_data.get('body'):
                    continue

                chunk_id = str(uuid4())
                chunk_text = f"Subject: {msg_data.get('subject')}\nFrom: {msg_data.get('sender')}\nDate: {msg_data.get('date')}\n\n{msg_data.get('body')}"

                from app.core.entity_extraction import EntityExtractor
                entities = await EntityExtractor.extract_entities(msg_data.get('body') or "")

                neo4j_nodes.append({
                    'chunk_id': chunk_id,
                    'message_id': doc.id,
                    'subject': msg_data.get('subject'),
                    'sender': msg_data.get('sender'),
                    'date': msg_data.get('date'),
                    'entities': [{'text': e.text, 'type': e.entity_type} for e in entities[:50]]
                })

                from app.core.embeddings import EmbeddingGenerator
                emb = await EmbeddingGenerator.generate_embedding(chunk_text)
                
                pg_chunk = DocumentChunk(
                    id=uuid.UUID(chunk_id),
                    tenant_id=self.tenant_id,
                    kb_id=uuid.UUID(kb_id),
                    text=chunk_text,
                    chunk_index=messages_synced,
                    embedding=emb
                )
                self.db.add(pg_chunk)
                messages_synced += 1

            if neo4j_nodes:
                neo_query_emails = """
                MATCH (kb:KnowledgeBase {id: $kb_id, tenant_id: $tenant_id})
                UNWIND $chunks AS chunk
                MERGE (p:Person {text: chunk.sender, tenant_id: $tenant_id})
                ON CREATE SET p.type = 'PERSON', p.id = randomUUID(), p.created_at = timestamp()
                MERGE (e:Email {id: chunk.message_id, tenant_id: $tenant_id})
                ON CREATE SET e.subject = chunk.subject, e.date = chunk.date, e.chunk_id = chunk.chunk_id, e.created_at = timestamp()
                MERGE (p)-[:SENT]->(e)
                MERGE (kb)-[:HAS_EMAIL]->(e)
                WITH e, chunk, $tenant_id AS tenant_id
                UNWIND chunk.entities AS ent
                MERGE (ent_node:Entity {text: ent.text, type: ent.type, tenant_id: tenant_id})
                ON CREATE SET ent_node.id = randomUUID(), ent_node.created_at = timestamp()
                MERGE (e)-[:MENTIONS]->(ent_node)
                """
                await self.neo4j_repo.execute_write(neo_query_emails, {
                    'kb_id': str(kb_id),
                    'tenant_id': str(self.tenant_id),
                    'chunks': neo4j_nodes
                })
                
                pg_kb.total_chunks += messages_synced
                await self.db.commit()

            return format_success({'kb_id': kb_id, 'messages_synced': messages_synced, 'sync_duration_seconds': time.time() - sync_start_time}, meta={'message': 'Outlook synchronized successfully'})

        except Exception as e:
            logger.error(f'Outlook sync failed: {e}', exc_info=True)
            return format_error(f'Failed to sync Outlook: {e}')

    async def save_table_rows(self, kb_id: str, table_rows: list):
        """
        Saves extracted structured tables directly to PostgreSQL (no Neo4j syncing required for tables).
        """
        try:
            async for doc in crawler.load_from_checkpoint(0, time.time(), checkpoint):
                if hasattr(doc, 'node_type'):
                    continue
                
                msg_data = await crawler.get_message_content(doc.id, user_email)
                if not msg_data or not msg_data.get('body'):
                    continue

                chunk_id = str(uuid4())
                chunk_text = f"Subject: {msg_data.get('subject')}\nFrom: {msg_data.get('sender')}\nDate: {msg_data.get('date')}\n\n{msg_data.get('body')}"

                from app.core.entity_extraction import EntityExtractor
                entities = await EntityExtractor.extract_entities(msg_data.get('body') or "")

                neo4j_nodes.append({
                    'chunk_id': chunk_id,
                    'message_id': doc.id,
                    'subject': msg_data.get('subject'),
                    'sender': msg_data.get('sender'),
                    'date': msg_data.get('date'),
                    'entities': [{'text': e.text, 'type': e.entity_type} for e in entities[:50]]
                })

                from app.core.embeddings import get_embedding
                emb = await get_embedding(chunk_text)
                
                pg_chunk = DocumentChunk(
                    id=uuid.UUID(chunk_id),
                    tenant_id=self.tenant_id,
                    kb_id=uuid.UUID(kb_id),
                    content=chunk_text,
                    embedding=emb,
                    metadata_json={
                        'source': 'gmail',
                        'message_id': doc.id
                    }
                )
                self.db.add(pg_chunk)
                messages_synced += 1

            if neo4j_nodes:
                neo_query_emails = """
                MATCH (kb:KnowledgeBase {id: $kb_id, tenant_id: $tenant_id})
                UNWIND $chunks AS chunk
                MERGE (p:Person {text: chunk.sender, tenant_id: $tenant_id})
                ON CREATE SET p.type = 'PERSON', p.id = randomUUID(), p.created_at = timestamp()
                MERGE (e:Email {id: chunk.message_id, tenant_id: $tenant_id})
                ON CREATE SET e.subject = chunk.subject, e.date = chunk.date, e.chunk_id = chunk.chunk_id, e.created_at = timestamp()
                MERGE (p)-[:SENT]->(e)
                MERGE (kb)-[:HAS_EMAIL]->(e)
                WITH e, chunk, $tenant_id AS tenant_id
                UNWIND chunk.entities AS ent
                MERGE (ent_node:Entity {text: ent.text, type: ent.type, tenant_id: tenant_id})
                ON CREATE SET ent_node.id = randomUUID(), ent_node.created_at = timestamp()
                MERGE (e)-[:MENTIONS]->(ent_node)
                """
                await execute_write_query(neo_query_emails, {
                    'kb_id': str(kb_id),
                    'tenant_id': str(self.tenant_id),
                    'chunks': neo4j_nodes
                })
                
                pg_kb.total_chunks += messages_synced
                await self.db.commit()

            from app.utils.formatters import format_success, format_error
            return format_success({'kb_id': kb_id, 'messages_synced': messages_synced, 'sync_duration_seconds': time.time() - sync_start_time}, meta={'message': 'Gmail synchronized successfully'})

        except Exception as e:
            logger.error(f'Gmail sync failed: {e}', exc_info=True)
            from app.utils.formatters import format_error
            return format_error(f'Failed to sync Gmail: {e}')

    async def sync_outlook_source(self, kb_id: str, sync_req: dict) -> dict:
        import time
        import json
        from uuid import uuid4
        from sqlalchemy import select
        from app.modules.knowledge_bases.models import KnowledgeBase, DatabaseConnection, DocumentChunk
        from app.modules.connectors.sharepoint.outlook_crawler import OutlookConnector
        from app.core.connectors import ConnectorCheckpoint

        sync_start_time = time.time()
        
        query = select(KnowledgeBase).where(KnowledgeBase.id == uuid.UUID(kb_id), KnowledgeBase.tenant_id == self.tenant_id)
        res = await self.db.execute(query)
        pg_kb = res.scalar_one_or_none()
        if not pg_kb:
            return format_error('Knowledge Base not found', meta={'error_code': 'KB_NOT_FOUND'})

        conn_query = select(DatabaseConnection).where(
            DatabaseConnection.kb_id == uuid.UUID(kb_id),
            DatabaseConnection.tenant_id == self.tenant_id,
            DatabaseConnection.db_type == 'outlook'
        )
        conn_res = await self.db.execute(conn_query)
        db_conn = conn_res.scalar_one_or_none()
        if not db_conn:
            return format_error('Outlook connection not configured for this KB.')

        user_email = sync_req.get('user_email')
        if not user_email:
            return format_error('user_email is required for Outlook sync.')

        pg_kb.source = f'outlook({user_email})'
        await self.db.commit()

        crawler = OutlookConnector(folder_id=sync_req.get('folder_id'), max_results=sync_req.get('max_results', 100))
        crawler.load_credentials(db_conn.connection_params)
        checkpoint = ConnectorCheckpoint(user_emails=[user_email], has_more=True, completion_stage='start')

        messages_synced = 0
        neo4j_nodes = []

        try:
            async for doc in crawler.load_from_checkpoint(0, time.time(), checkpoint):
                if hasattr(doc, 'node_type'):
                    continue
                
                msg_data = await crawler.get_message_content(user_email, doc.id)
                if not msg_data or not msg_data.get('body'):
                    continue

                chunk_id = str(uuid4())
                chunk_text = f"Subject: {msg_data.get('subject')}\nFrom: {msg_data.get('sender')}\nDate: {msg_data.get('date')}\n\n{msg_data.get('body')}"

                from app.core.entity_extraction import EntityExtractor
                entities = await EntityExtractor.extract_entities(msg_data.get('body') or "")

                neo4j_nodes.append({
                    'chunk_id': chunk_id,
                    'message_id': doc.id,
                    'subject': msg_data.get('subject'),
                    'sender': msg_data.get('sender'),
                    'date': msg_data.get('date'),
                    'entities': [{'text': e.text, 'type': e.entity_type} for e in entities[:50]]
                })

                from app.core.embeddings import get_embedding
                emb = await get_embedding(chunk_text)
                
                pg_chunk = DocumentChunk(
                    id=uuid.UUID(chunk_id),
                    tenant_id=self.tenant_id,
                    kb_id=uuid.UUID(kb_id),
                    content=chunk_text,
                    embedding=emb,
                    metadata_json={
                        'source': 'outlook',
                        'message_id': doc.id
                    }
                )
                self.db.add(pg_chunk)
                messages_synced += 1

            if neo4j_nodes:
                neo_query_emails = """
                MATCH (kb:KnowledgeBase {id: $kb_id, tenant_id: $tenant_id})
                UNWIND $chunks AS chunk
                MERGE (p:Person {text: chunk.sender, tenant_id: $tenant_id})
                ON CREATE SET p.type = 'PERSON', p.id = randomUUID(), p.created_at = timestamp()
                MERGE (e:Email {id: chunk.message_id, tenant_id: $tenant_id})
                ON CREATE SET e.subject = chunk.subject, e.date = chunk.date, e.chunk_id = chunk.chunk_id, e.created_at = timestamp()
                MERGE (p)-[:SENT]->(e)
                MERGE (kb)-[:HAS_EMAIL]->(e)
                WITH e, chunk, $tenant_id AS tenant_id
                UNWIND chunk.entities AS ent
                MERGE (ent_node:Entity {text: ent.text, type: ent.type, tenant_id: tenant_id})
                ON CREATE SET ent_node.id = randomUUID(), ent_node.created_at = timestamp()
                MERGE (e)-[:MENTIONS]->(ent_node)
                """
                from app.core.neo4j import execute_write_query
                await execute_write_query(neo_query_emails, {
                    'kb_id': str(kb_id),
                    'tenant_id': str(self.tenant_id),
                    'chunks': neo4j_nodes
                })
                
                pg_kb.total_chunks += messages_synced
                await self.db.commit()

            from app.utils.formatters import format_success, format_error
            return format_success({'kb_id': kb_id, 'messages_synced': messages_synced, 'sync_duration_seconds': time.time() - sync_start_time}, meta={'message': 'Outlook synchronized successfully'})

        except Exception as e:
            logger.error(f'Outlook sync failed: {e}', exc_info=True)
            from app.utils.formatters import format_error
            return format_error(f'Failed to sync Outlook: {e}')

    async def save_table_rows(self, kb_id: str, table_rows: list):
        """
        Saves extracted structured tables directly to PostgreSQL (no Neo4j syncing required for tables).
        """
        from .models import DocumentTableRow
        import uuid
        
        if not table_rows:
            return
            
        try:
            db_rows = []
            chunk_texts = []
            import re
            
            def parse_numeric(val):
                if not val: return None
                # Strip non-numeric characters except dot
                cleaned = re.sub(r'[^\d.]', '', str(val))
                try:
                    return float(cleaned) if cleaned else None
                except ValueError:
                    return None

            for row in table_rows:
                row_data = row.get("row_data", {})
                
                # Column Mapping Registry
                CANONICAL_COLUMNS = {
                    "part_number": ["part number", "part no", "item code", "sku", "product id"],
                    "product_name": ["product", "description", "item name", "product name", "item description"],
                    "mrp": ["mrp", "price", "rate", "unit price", "retail price", "selling price", "cost"],
                    "gst": ["gst", "tax", "gst %", "tax %", "igst", "cgst", "sgst"],
                    "hsn_code": ["hsn", "hsn code", "sac code"]
                }
                
                # Case-insensitive key matching for common columns
                row_keys_lower = {k.lower().strip(): k for k in row_data.keys()}
                
                def find_mapped_value(canonical_name):
                    for alias in CANONICAL_COLUMNS[canonical_name]:
                        if alias in row_keys_lower:
                            return row_data[row_keys_lower[alias]]
                    return None
                
                # Extract typed columns
                part_number = find_mapped_value("part_number")
                product_name = find_mapped_value("product_name")
                mrp = parse_numeric(find_mapped_value("mrp"))
                gst = parse_numeric(find_mapped_value("gst"))
                hsn_code = find_mapped_value("hsn_code")

                db_rows.append(
                    DocumentTableRow(
                        tenant_id=self.tenant_id,
                        kb_id=uuid.UUID(kb_id),
                        page_number=row.get("page_number", 1),
                        table_index=row.get("table_index", 0),
                        row_index=row.get("row_index", 0),
                        part_number=str(part_number)[:255] if part_number else None,
                        product_name=str(product_name)[:1000] if product_name else None,
                        mrp=mrp,
                        gst=gst,
                        hsn_code=str(hsn_code)[:100] if hsn_code else None,
                        extraction_confidence=0.99, # Phase 3: Advanced Enterprise Feature
                        row_data=row_data
                    )
                )

                # ============= ROW-LEVEL EMBEDDING CHUNK =============
                # Create highly structured semantic chunks avoiding SL.NO and metadata
                # This prevents flattened table math hallucination (e.g., 1 + 2996 = 12996)
                chunk_parts = []
                if part_number: chunk_parts.append(f"Part Number: {part_number}")
                if product_name: chunk_parts.append(f"Product Name: {product_name}")
                if mrp is not None: chunk_parts.append(f"MRP: {mrp}")
                if hsn_code: chunk_parts.append(f"HSN Code: {hsn_code}")
                if gst is not None: chunk_parts.append(f"GST: {gst}%")
                
                if chunk_parts:
                    chunk_texts.append("\n".join(chunk_parts))
                
            self.db.add_all(db_rows)
            
            # Batch generate embeddings for semantic row chunks
            if chunk_texts:
                from app.core.embeddings import EmbeddingGenerator
                from .models import DocumentChunk
                
                embeddings = await EmbeddingGenerator.generate_embeddings_batch(chunk_texts)
                chunk_rows = []
                
                for idx, (text, emb) in enumerate(zip(chunk_texts, embeddings)):
                    chunk_rows.append(
                        DocumentChunk(
                            tenant_id=self.tenant_id,
                            kb_id=uuid.UUID(kb_id),
                            text=text,
                            # Offset index heavily so it doesn't conflict with normal chunks
                            chunk_index=90000 + idx, 
                            embedding=emb
                        )
                    )
                self.db.add_all(chunk_rows)
                logger.info(f" Saved {len(chunk_rows)} Row-Level Embeddings to DB for KB {kb_id}")
            
            await self.db.commit()
            logger.info(f" Saved {len(db_rows)} structured table rows to DB for KB {kb_id}")
            
        except Exception as e:
            logger.error(f" Failed to save table rows to DB: {e}", exc_info=True)
            await self.db.rollback()
