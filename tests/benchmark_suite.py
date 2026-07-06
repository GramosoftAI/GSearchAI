import asyncio
import os
import sys
import uuid
import time
from unittest.mock import patch
from sqlalchemy.orm import Session
from sqlalchemy import select

# Add app to sys path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.modules.knowledge_bases.service import KnowledgeBaseService
from app.modules.knowledge_bases.models import DocumentIngestionRun, KnowledgeBase
from app.core.database import SessionLocal

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "benchmark_docs")

async def run_ingestion_for_file(filepath: str, tenant_id: str, disable_fast_path: bool = False) -> DocumentIngestionRun:
    filename = os.path.basename(filepath)
    print(f"  -> Ingesting {filename} (Fast-Path {'OFF' if disable_fast_path else 'ON'})...")
    
    with open(filepath, "rb") as f:
        file_bytes = f.read()

    kb_service = KnowledgeBaseService(tenant_id)
    
    # We create a dummy document record in DB
    db: Session = SessionLocal()
    new_doc = KnowledgeBase(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        filename=filename,
        document_type="pdf",
        status="pending"
    )
    db.add(new_doc)
    db.commit()
    doc_id = str(new_doc.id)
    db.close()

    try:
        if disable_fast_path:
            # We patch is_dense_chunk inside the service module to always return True (i.e. NEVER skip)
            with patch('app.modules.knowledge_bases.service.is_dense_chunk', return_value=True):
                await kb_service.ingest_document(doc_id, file_bytes, filename)
        else:
            await kb_service.ingest_document(doc_id, file_bytes, filename)
            
    except Exception as e:
        print(f"     [!] Extraction error during {filename}: {e}")
        # Continue so we can at least query the run if it partially completed
        
    # Fetch the run metrics from DB
    db = SessionLocal()
    run = db.execute(select(DocumentIngestionRun).where(DocumentIngestionRun.document_id == doc_id).order_by(DocumentIngestionRun.started_at.desc())).scalar_one_or_none()
    db.close()
    
    return run

async def main():
    if not os.path.exists(FIXTURES_DIR):
        print(f"Fixtures directory missing: {FIXTURES_DIR}")
        return
        
    docs = [f for f in os.listdir(FIXTURES_DIR) if f.endswith(".pdf")]
    if not docs:
        print(f"No PDFs found in {FIXTURES_DIR}. Please add the 5 representative document classes.")
        return
        
    print(f"Found {len(docs)} documents for benchmarking.")
    tenant_id = str(uuid.uuid4()) # Use a dummy tenant for the test run
    
    results = {}
    
    for doc in docs:
        filepath = os.path.join(FIXTURES_DIR, doc)
        print(f"\n=== Benchmarking Document Class: {doc} ===")
        
        # 1. Baseline (Optimization OFF)
        baseline_run = await run_ingestion_for_file(filepath, tenant_id, disable_fast_path=True)
        
        # 2. Optimized (Optimization ON)
        optimized_run = await run_ingestion_for_file(filepath, tenant_id, disable_fast_path=False)
        
        results[doc] = {
            "baseline": baseline_run,
            "optimized": optimized_run
        }
        
    print("\n\n" + "="*80)
    print("                    END-TO-END VALIDATION BENCHMARK REPORT")
    print("="*80)
    
    print("\n### Certification Matrix\n")
    print("| Document Type | Runtime Gain | Extr. Reduction | Entity Variance | Triple Variance | Integrity Score | Result |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    
    for doc, runs in results.items():
        b = runs["baseline"]
        o = runs["optimized"]
        
        if not b or not o:
            print(f"| {doc} | [FAILED] | N/A | N/A | N/A | Execution Error |")
            continue
            
        runtime_b = (b.completed_at - b.started_at).total_seconds() if b.completed_at else b.total_duration_ms / 1000
        runtime_o = (o.completed_at - o.started_at).total_seconds() if o.completed_at else o.total_duration_ms / 1000
        
        runtime_gain = ((runtime_b - runtime_o) / runtime_b * 100) if runtime_b else 0
        entity_var = (abs(b.entity_count - o.entity_count) / max(b.entity_count, 1)) * 100
        triple_var = (abs(b.triplet_count - o.triplet_count) / max(b.triplet_count, 1)) * 100
        
        extraction_reduction = ((b.kg_extraction_calls - o.kg_extraction_calls) / b.kg_extraction_calls * 100) if b.kg_extraction_calls else 0
        
        # Calculate Integrity Score
        integrity_score = max(0, 100 - max(entity_var, triple_var))
        
        # Evaluate Gates (Per-Document)
        passed = integrity_score >= 95
        result_str = "PASSED ✅" if passed else "FAILED ❌"
        
        print(f"| {doc} | {runtime_gain:.1f}% | {extraction_reduction:.1f}% | {entity_var:.1f}% | {triple_var:.1f}% | {integrity_score:.1f}% | {result_str} |")

    # Calculate Aggregates
    total_runtime_b = sum(((runs["baseline"].completed_at - runs["baseline"].started_at).total_seconds() if runs["baseline"].completed_at else runs["baseline"].total_duration_ms / 1000) for runs in results.values() if runs["baseline"])
    total_runtime_o = sum(((runs["optimized"].completed_at - runs["optimized"].started_at).total_seconds() if runs["optimized"].completed_at else runs["optimized"].total_duration_ms / 1000) for runs in results.values() if runs["optimized"])
    
    total_entities_b = sum((runs["baseline"].entity_count for runs in results.values() if runs["baseline"]))
    total_entities_o = sum((runs["optimized"].entity_count for runs in results.values() if runs["optimized"]))
    
    total_triples_b = sum((runs["baseline"].triplet_count for runs in results.values() if runs["baseline"]))
    total_triples_o = sum((runs["optimized"].triplet_count for runs in results.values() if runs["optimized"]))
    
    total_kg_b = sum((runs["baseline"].kg_extraction_calls for runs in results.values() if runs["baseline"]))
    total_kg_o = sum((runs["optimized"].kg_extraction_calls for runs in results.values() if runs["optimized"]))
    
    agg_runtime_gain = ((total_runtime_b - total_runtime_o) / total_runtime_b * 100) if total_runtime_b else 0
    agg_extraction_reduction = ((total_kg_b - total_kg_o) / total_kg_b * 100) if total_kg_b else 0
    agg_entity_var = (abs(total_entities_b - total_entities_o) / max(total_entities_b, 1)) * 100
    agg_triple_var = (abs(total_triples_b - total_triples_o) / max(total_triples_b, 1)) * 100
    agg_integrity_score = max(0, 100 - max(agg_entity_var, agg_triple_var))
    
    agg_passed = agg_integrity_score >= 95 and agg_runtime_gain >= 25
    agg_result_str = "PASSED ✅" if agg_passed else "FAILED ❌"
    
    print("| **OVERALL (Aggregate)** | **{:.1f}%** | **{:.1f}%** | **{:.1f}%** | **{:.1f}%** | **{:.1f}%** | **{}** |".format(agg_runtime_gain, agg_extraction_reduction, agg_entity_var, agg_triple_var, agg_integrity_score, agg_result_str))

if __name__ == "__main__":
    asyncio.run(main())
