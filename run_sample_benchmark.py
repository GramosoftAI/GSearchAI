import asyncio
import sys
import uuid
import time
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SampleBenchmark")

load_dotenv('e:/graphmind/graphmind/.env')
sys.path.append('e:/graphmind/graphmind')

import argparse
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings
from app.core.unified_extractor import UnifiedExtractor
from app.modules.rag.semantic.pipeline.semantic_ingestion_pipeline import SemanticIngestionPipeline
from app.modules.rag.semantic.models import Provenance, ExtractionMethod
from app.modules.knowledge_bases.services.esdip.domain.pipeline_context import PipelineContext
from app.modules.rag.semantic.validation.shadow_comparator import ShadowComparator

async def run_sample_benchmark(kb_id: str, sample_size: int):
    s = get_settings()
    engine = create_async_engine(f'postgresql+asyncpg://{s.postgres_user}:{s.postgres_password}@{s.postgres_host}:{s.postgres_port}/{s.postgres_db}')
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as db:
        res = await db.execute(text("SELECT tenant_id FROM knowledge_bases WHERE id = :kb_id LIMIT 1"), {"kb_id": kb_id})
        row = res.fetchone()
        if not row:
            logger.error("KB not found.")
            return
            
        tenant_id = str(row.tenant_id)
        
        res = await db.execute(text("SELECT text FROM document_chunks WHERE kb_id = :kb_id ORDER BY chunk_index ASC"), {"kb_id": kb_id})
        all_chunks = [row.text for row in res.fetchall()]
        
        if not all_chunks:
            logger.error("No chunks found.")
            return
            
        step = max(1, len(all_chunks) // sample_size)
        sample_chunks = [all_chunks[i] for i in range(0, len(all_chunks), step)][:sample_size]
        
        logger.info(f"Selected {len(sample_chunks)} representative chunks for benchmarking.")
        
        legacy_entities = []
        legacy_triplets = []
        legacy_metrics = {"llm_calls": 0, "llm_tokens": 0}
        
        extractor = UnifiedExtractor(tenant_id)
        
        logger.info("Running Legacy Extraction...")
        for i, chunk in enumerate(sample_chunks):
            start = time.time()
            res = await extractor.extract_all(f"idx_{i}", chunk)
            end = time.time()
            logger.info(f"Legacy Chunk {i} took {end-start:.2f}s")
            
            legacy_entities.append(res.get("entities", []))
            
            from app.core.triplet_extractor import TripletExtractionResult
            legacy_triplets.append(TripletExtractionResult(chunk_id=f"idx_{i}", triplets=res.get("triplets", [])))
            
            # Rough metrics for legacy
            if len(res.get("entities", [])) > 0:
                legacy_metrics["llm_calls"] += 1
                legacy_metrics["llm_tokens"] += len(chunk) // 4
                
        logger.info("Running Semantic Extraction...")
        semantic_pipeline = SemanticIngestionPipeline(tenant_id)
        base_prov = Provenance(
            tenant_id=tenant_id,
            knowledge_base_id=kb_id,
            document_id=kb_id,
            chunk_ids=[],
            source="benchmark",
            ontology_version="1.0",
            extraction_method=ExtractionMethod.HYBRID,
            confidence=1.0
        )
        
        pipeline_ctx = PipelineContext(tenant_id=tenant_id, kb_id=kb_id, file_bytes=b"", filename="benchmark")
        pipeline_ctx = await semantic_pipeline.process_chunks(sample_chunks, base_prov, pipeline_ctx)
        
        semantic_ctx = pipeline_ctx.semantic
        
        ShadowComparator.compare_and_report(kb_id, tenant_id, legacy_entities, legacy_triplets, semantic_ctx, legacy_metrics)
        logger.info("Sample Benchmark Complete. Reports generated in shadow_reports/")
        
        print("\n\n--- SEMANTIC PIPELINE TELEMETRY ---")
        for k, v in semantic_ctx.telemetry.items():
            print(f"{k}: {v}")
            
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--kb-id", required=True)
    parser.add_argument("--sample-size", type=int, default=15)
    args = parser.parse_args()
    asyncio.run(run_sample_benchmark(args.kb_id, args.sample_size))
