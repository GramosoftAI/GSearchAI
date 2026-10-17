"""CLI script to run Phase 2/3 Knowledge Pipeline manually without Redis.

Usage:
    python -m app.modules.database_knowledgebase.knowledge.jobs.run_pipeline_cli --kb-id <KB_ID> [--force-recompute]
"""

import sys
import argparse
import asyncio
import uuid
import logging
import json
from sqlalchemy import text
from app.core.database import AsyncSessionLocal
from app.modules.database_knowledgebase.knowledge.jobs.pipeline import run_pipeline_for_kb_local

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logger = logging.getLogger("run_pipeline_cli")


async def main():
    parser = argparse.ArgumentParser(description="Run Phase 2/3 knowledge pipeline for a KB without Redis.")
    parser.add_argument("--kb-id", required=True, help="Knowledge Base UUID")
    parser.add_argument("--tenant-id", default=None, help="Tenant UUID (optional)")
    parser.add_argument("--force-recompute", action="store_true", help="Force recomputation of all stages")
    parser.add_argument("--stage", default=None, help="Target a specific stage (e.g. profile)")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without calling the LLM")
    args = parser.parse_args()

    kb_id = uuid.UUID(args.kb_id)
    tenant_id = uuid.UUID(args.tenant_id) if args.tenant_id else None
    target_stages = [s.strip() for s in args.stage.split(",") if s.strip()] if args.stage else (["enrich"] if args.dry_run else None)

    print(f"\n=======================================================")
    print(f"Starting Phase 2/3 Pipeline for KB: {kb_id}")
    print(f"Force recompute: {args.force_recompute}")
    print(f"Target stages: {target_stages or 'all'}")
    print(f"Dry run: {args.dry_run}")
    print(f"=======================================================\n")

    result = await run_pipeline_for_kb_local(
        kb_id=kb_id,
        tenant_id=tenant_id,
        force_recompute=args.force_recompute,
        target_stages=target_stages,
        dry_run=args.dry_run,
    )

    print(f"\n=======================================================")
    print(f"Pipeline Finished. Overall Status: {result.status.value}")
    print(f"Run ID: {result.run_id}")
    print(f"Error: {result.error}")
    print(f"=======================================================\n")

    if args.dry_run:
        enrich_stage = result.stages.get("enrich")
        if enrich_stage and enrich_stage.metrics:
            metrics = enrich_stage.metrics
            summary = metrics.get("dry_run_summary") or {}
            print("\n" + "=" * 65)
            print("                DRY RUN REPORT SUMMARY                 ")
            print("=" * 65)
            print(f"Total Tables in Schema:              {metrics.get('tables_total', 0)}")
            print(f"Tables That WILL Call LLM:           {metrics.get('tables_will_call_llm', 0)}")
            print(f"Tables Skipped (Structural/System):  {metrics.get('tables_skipped', 0)}")
            print("\n--- Tables per Kind (Rule-Based Pre-Classification) ---")
            for kind, count in sorted((metrics.get("kind_distribution") or {}).items()):
                print(f"  - {kind:<12}: {count:>3} tables")

            sb = metrics.get("skipped_breakdown", {})
            print("\n--- Skipped Tables Breakdown ---")
            print(f"  - System tables:                   {sb.get('system_tables', 0)}")
            print(f"  - Empty tables (no FK parents):    {sb.get('empty_tables_no_fk_parents', 0)}")

            print("\n--- Estimated Token Usage (Rough Chars / 4) ---")
            print(f"  - Prompt / Input Tokens:           {metrics.get('input_tokens', 0):,}")
            print(f"  - Expected Completion Tokens:      {metrics.get('output_tokens', 0):,}")
            print(f"  - Total Estimated Tokens:          {metrics.get('approx_tokens_used', 0):,}")
            
            print("\n--- LLM Calls Planned ---")
            print(f"  - Table Semantic Enrichment:       {metrics.get('tables_will_call_llm', 0)} calls (1 call per table, batched columns)")
            print(f"  - Domain Grouping Clustering:      1 call (clusters entity & lookup tables into <= 15 domains)")
            print(f"  - Total LLM Calls:                 {metrics.get('tables_will_call_llm', 0) + 1} calls")
            print("=" * 65 + "\n")

    print("Stage breakdown:")
    for stage_name, srec in result.stages.items():
        dur = srec.metrics.get("duration_seconds", "N/A")
        print(f"  Stage: {stage_name:<16} | Status: {srec.status.value:<22} | Duration: {str(dur):<6}s")
        if srec.error:
            print(f"    Error: {srec.error}")
        if srec.metrics:
            compact_metrics = {k: v for k, v in srec.metrics.items() if k not in ("duration_seconds", "table_errors", "employees_enrich_prompt")}
            print(f"    Metrics: {json.dumps(compact_metrics)}")

    # Database verification
    async with AsyncSessionLocal() as session:
        # Schema docs by doc_type
        res_sdocs = await session.execute(text(f"""
            SELECT doc_type, COUNT(*) 
            FROM kb2_schema_docs 
            WHERE db_knowledgebase_id = '{kb_id}'
            GROUP BY doc_type
        """))
        print("\n--- Current kb2_schema_docs row counts by doc_type ---")
        total_sdocs = 0
        for r in res_sdocs.fetchall():
            print(f"  {r[0]}: {r[1]}")
            total_sdocs += r[1]
        print(f"  Total kb2_schema_docs: {total_sdocs}")

        # Query memory count
        res_qmem = await session.execute(text(f"""
            SELECT COUNT(*) 
            FROM kb2_query_memory 
            WHERE db_knowledgebase_id = '{kb_id}'
        """))
        print(f"\n--- Current kb2_query_memory count: {res_qmem.scalar()} ---")


if __name__ == "__main__":
    asyncio.run(main())
