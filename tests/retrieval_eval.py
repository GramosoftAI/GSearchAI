"""Evaluation script for TableRetriever.

Evaluates table retrieval accuracy (Top-1 and Top-3) across:
1. Tuned benchmark set (14 questions)
2. Hold-out generalization set (16 questions, never used for tuning)
3. Negative set (6 out-of-domain questions with no data in this KB)
Calculates top1_score and margin distributions (min, median for positives vs max for negatives).
"""

import sys
import os
import argparse
import asyncio
import time
import statistics
from typing import List, Tuple, Dict, Any, Union
import uuid

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import select, text, event
from app.core.database import AsyncSessionLocal, engine
from app.modules.database_knowledgebase.models.database_knowledgebase import DatabaseKnowledgebase
from app.modules.database_knowledgebase.knowledge.models.knowledge_items import KB2KnowledgeItem
from app.modules.database_knowledgebase.knowledge.retrieval import (
    QuestionAnalyzer,
    TableRetriever,
)


TUNED_CASES: List[Tuple[str, List[str]]] = [
    ("how many projects are active", ["projects"]),
    ("who created the most tasks this month", ["work_packages"]),
    ("show overdue work packages", ["work_packages"]),
    ("how many meetings were held yesterday", ["meetings"]),
    ("how many hours did arun log yesterday", ["time_entries"]),
    ("list users who never logged in", ["users"]),
    ("how many work packages are in progress", ["work_packages"]),
    ("show the latest news", ["news"]),
    ("which wiki pages were updated last week", ["wiki_pages"]),
    ("list project members", ["members"]),
    ("what is the status of work package 123", ["work_packages"]),
    ("list attachments added today", ["attachments"]),
    ("show time entries for a project", ["time_entries"]),
    ("how many versions are open", ["versions"]),
]

HOLD_OUT_CASES: List[Tuple[str, List[str]]] = [
    ("who logged time on work package 123", ["time_entries"]),
    ("list overdue tasks assigned to arun", ["work_packages"]),
    ("how many users are active", ["users"]),
    ("show all projects created this year", ["projects"]),
    ("list open tickets", ["work_packages"]),
    ("what statuses exist", ["statuses"]),
    ("list news posted last month", ["news"]),
    ("which versions are closed", ["versions"]),
    ("show my notifications", ["notifications"]),
    ("list work package types", ["types"]),
    ("how many attachments does each work package have", ["attachments"]),
    ("show custom fields for work packages", ["custom_fields"]),
    ("list project phases", ["project_phases"]),
    ("who is assigned to the most issues", ["work_packages"]),
    ("how many wiki pages does each project have", ["wiki_pages"]),
    ("show roles of project members", ["roles", "members"]),
]

NEGATIVE_CASES: List[str] = [
    "how many employees are absent today",
    "what is the total salary paid this month",
    "list customers with unpaid invoices",
    "show inventory stock levels",
    "how many leave requests are pending",
    "what was last quarter's revenue",
]

DEFAULT_KB_ID = "c0f9fbc6-fdb1-49a1-bfe8-9b2aed3b25ae"
DEFAULT_TENANT_ID = "2b41fa8c-9c12-491d-8199-a75292e683ec"


async def find_target_kb(db) -> Tuple[uuid.UUID, uuid.UUID, str]:
    """Find the target knowledge base ID and tenant ID."""
    try:
        def_id = uuid.UUID(DEFAULT_KB_ID)
        stmt = select(DatabaseKnowledgebase).where(DatabaseKnowledgebase.id == def_id)
        res = await db.execute(stmt)
        kb = res.scalar_one_or_none()
        if kb:
            return kb.id, kb.tenant_id, kb.name
    except Exception:
        pass

    stmt = text("""
        SELECT db_knowledgebase_id, tenant_id, count(*) as c 
        FROM kb2_knowledge_items 
        WHERE item_type = 'table' AND item_key IN ('public.work_packages', 'public.projects', 'public.time_entries')
        GROUP BY db_knowledgebase_id, tenant_id
        ORDER BY c DESC LIMIT 1
    """)
    res = await db.execute(stmt)
    row = res.fetchone()
    if row:
        kb_stmt = select(DatabaseKnowledgebase).where(DatabaseKnowledgebase.id == row[0])
        kb_res = await db.execute(kb_stmt)
        kb_obj = kb_res.scalar_one_or_none()
        kb_name = kb_obj.name if kb_obj else "unknown"
        return row[0], row[1], kb_name

    raise RuntimeError("Could not locate a suitable Database Knowledgebase with expected tables.")


async def verify_is_empty_stats(session, kb_id: uuid.UUID, tenant_id: uuid.UUID):
    """Verify that every table item has stats.row_count from bounded count."""
    stmt = select(KB2KnowledgeItem.item_key, KB2KnowledgeItem.payload).where(
        KB2KnowledgeItem.tenant_id == tenant_id,
        KB2KnowledgeItem.db_knowledgebase_id == kb_id,
        KB2KnowledgeItem.item_type == "table",
    )
    res = await session.execute(stmt)
    total_tables = 0
    tables_with_exact_count = 0
    tables_lacking_exact_count = []

    for item_key, payload in res.all():
        total_tables += 1
        payload = payload or {}
        t_name = payload.get("table_name") or item_key.split(".")[-1]
        stats = payload.get("stats") or {}
        if stats.get("row_count") is not None:
            tables_with_exact_count += 1
        else:
            tables_lacking_exact_count.append(t_name)

    return total_tables, tables_with_exact_count, tables_lacking_exact_count


async def measure_cache_query_counts(kb_id: uuid.UUID, tenant_id: uuid.UUID) -> Tuple[int, int]:
    """Measure query count for table metadata retrieval: cold vs warm request."""
    query_count = 0

    def count_queries(conn, cursor, statement, parameters, context, executemany):
        nonlocal query_count
        query_count += 1

    event.listen(engine.sync_engine, "before_cursor_execute", count_queries)

    # 1. Cold cache
    TableRetriever.clear_cache(kb_id)
    query_count = 0
    async with AsyncSessionLocal() as session:
        retriever1 = TableRetriever(db=session, tenant_id=tenant_id)
        await retriever1._get_kb_table_metadata(kb_id)
        cold_count = query_count

    # 2. Warm cache (new retriever instance in a new request session)
    query_count = 0
    async with AsyncSessionLocal() as session:
        retriever2 = TableRetriever(db=session, tenant_id=tenant_id)
        await retriever2._get_kb_table_metadata(kb_id)
        warm_count = query_count

    event.remove(engine.sync_engine, "before_cursor_execute", count_queries)
    return cold_count, warm_count


async def run_evaluation(kb_id_str: str = None, tenant_id_str: str = None):
    analyzer = QuestionAnalyzer()

    async with AsyncSessionLocal() as session:
        if kb_id_str and tenant_id_str:
            kb_id = uuid.UUID(kb_id_str)
            tenant_id = uuid.UUID(tenant_id_str)
            kb_name = kb_id_str
        else:
            kb_id, tenant_id, kb_name = await find_target_kb(session)

        print("=" * 110)
        print("TABLE RETRIEVER HARDENING & BENCHMARK EVALUATION")
        print(f"Target KB: {kb_name} (ID: {kb_id}, Tenant: {tenant_id})")
        print("=" * 110)

        # 1. Verify stats.row_count
        tot_tbls, with_exact, lacking = await verify_is_empty_stats(session, kb_id, tenant_id)
        print(f"\n[IS_EMPTY VERIFICATION] Exact Bounded Row Count:")
        print(f"  Total tables checked : {tot_tbls}")
        print(f"  With stats.row_count : {with_exact}/{tot_tbls} ({(with_exact/tot_tbls)*100:.1f}%)")
        if lacking:
            print(f"  Tables lacking stats.row_count (treated as unknown): {lacking}")
        else:
            print(f"  Tables lacking stats.row_count : None (All {tot_tbls} have exact stats.row_count)")

        # 2. Measure cache query count before and after
        cold_q, warm_q = await measure_cache_query_counts(kb_id, tenant_id)
        print(f"\n[PROCESS CACHE VERIFICATION] Table Metadata Query Count on Single Request:")
        print(f"  Cold request (no cache) : {cold_q} queries")
        print(f"  Warm request (cached)   : {warm_q} query (only lightweight schema_version validation check)")
        print(f"  Query reduction         : -{cold_q - warm_q} queries ({(1 - warm_q/cold_q)*100:.1f}% reduction)")

        retriever = TableRetriever(db=session, tenant_id=tenant_id)

        # -------------------------------------------------------------
        # 3. Evaluate Tuned Benchmark Set (14 questions)
        # -------------------------------------------------------------
        print("\n" + "=" * 110)
        print("PART 1: TUNED SET (14 questions)")
        print("=" * 110)

        tuned_top1_correct = 0
        tuned_top3_correct = 0
        tuned_results = []
        positive_scores = []
        positive_margins = []

        for idx, (question, expected_tables) in enumerate(TUNED_CASES, 1):
            t0 = time.perf_counter()
            frame = analyzer.analyze(question)
            candidates = await retriever.retrieve_tables(
                db_knowledgebase_id=kb_id,
                frame=frame,
                top_k=5,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            retrieved_names = [c.table_name for c in candidates]
            top1_hit = len(retrieved_names) > 0 and retrieved_names[0] in expected_tables
            top3_hit = any(t in expected_tables for t in retrieved_names[:3])

            if top1_hit:
                tuned_top1_correct += 1
            if top3_hit:
                tuned_top3_correct += 1

            top1_score = candidates.top1_score
            margin = candidates.margin
            positive_scores.append(top1_score)
            positive_margins.append(margin)

            tuned_results.append({
                "idx": idx,
                "question": question,
                "expected": expected_tables,
                "top1": retrieved_names[0] if retrieved_names else "None",
                "top5": retrieved_names[:5],
                "top1_score": top1_score,
                "margin": margin,
                "top1_hit": top1_hit,
                "top3_hit": top3_hit,
                "candidates": candidates,
                "elapsed_ms": elapsed_ms,
            })

            top5_display = ", ".join(f"{c.table_name} ({c.score:.4f})" for c in candidates[:5])
            print(f"[{idx:02d}] \"{question}\"")
            print(f"     Expected   : {expected_tables}")
            print(f"     Top-1      : {'PASS' if top1_hit else 'FAIL'} -> {retrieved_names[0] if retrieved_names else 'None'}")
            print(f"     Top-3      : {'PASS' if top3_hit else 'FAIL'}")
            print(f"     top1_score : {top1_score:.4f} | margin: {margin:.4f} | Latency: {elapsed_ms:.1f}ms")
            print(f"     Top-5      : {top5_display}\n")

        tuned_total = len(TUNED_CASES)
        tuned_top1_acc = (tuned_top1_correct / tuned_total) * 100.0
        tuned_top3_acc = (tuned_top3_correct / tuned_total) * 100.0

        # -------------------------------------------------------------
        # 4. Evaluate Hold-Out Benchmark Set (16 questions)
        # -------------------------------------------------------------
        print("=" * 110)
        print("PART 2: HOLD-OUT SET (16 questions, never tuned)")
        print("=" * 110)

        holdout_top1_correct = 0
        holdout_top3_correct = 0
        holdout_results = []
        holdout_misses = []

        for idx, (question, expected_tables) in enumerate(HOLD_OUT_CASES, 1):
            t0 = time.perf_counter()
            frame = analyzer.analyze(question)
            candidates = await retriever.retrieve_tables(
                db_knowledgebase_id=kb_id,
                frame=frame,
                top_k=5,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            retrieved_names = [c.table_name for c in candidates]
            top1_hit = len(retrieved_names) > 0 and retrieved_names[0] in expected_tables
            top3_hit = any(t in expected_tables for t in retrieved_names[:3])

            if top1_hit:
                holdout_top1_correct += 1
            if top3_hit:
                holdout_top3_correct += 1

            top1_score = candidates.top1_score
            margin = candidates.margin
            positive_scores.append(top1_score)
            positive_margins.append(margin)

            item = {
                "idx": idx,
                "question": question,
                "expected": expected_tables,
                "top1": retrieved_names[0] if retrieved_names else "None",
                "top5": retrieved_names[:5],
                "top1_score": top1_score,
                "margin": margin,
                "top1_hit": top1_hit,
                "top3_hit": top3_hit,
                "candidates": candidates,
                "elapsed_ms": elapsed_ms,
            }
            holdout_results.append(item)

            if not top3_hit or not top1_hit:
                holdout_misses.append(item)

            top5_display = ", ".join(f"{c.table_name} ({c.score:.4f})" for c in candidates[:5])
            print(f"[{idx:02d}] \"{question}\"")
            print(f"     Expected   : {expected_tables}")
            print(f"     Top-1      : {'PASS' if top1_hit else 'FAIL'} -> {retrieved_names[0] if retrieved_names else 'None'}")
            print(f"     Top-3      : {'PASS' if top3_hit else 'FAIL'}")
            print(f"     top1_score : {top1_score:.4f} | margin: {margin:.4f} | Latency: {elapsed_ms:.1f}ms")
            print(f"     Top-5      : {top5_display}\n")

        holdout_total = len(HOLD_OUT_CASES)
        holdout_top1_acc = (holdout_top1_correct / holdout_total) * 100.0
        holdout_top3_acc = (holdout_top3_correct / holdout_total) * 100.0

        # -------------------------------------------------------------
        # 5. Evaluate Negative Benchmark Set (6 questions)
        # -------------------------------------------------------------
        print("=" * 110)
        print("PART 3: NEGATIVE SET (6 out-of-domain questions)")
        print("=" * 110)

        negative_results = []
        negative_scores = []
        negative_margins = []

        for idx, question in enumerate(NEGATIVE_CASES, 1):
            t0 = time.perf_counter()
            frame = analyzer.analyze(question)
            candidates = await retriever.retrieve_tables(
                db_knowledgebase_id=kb_id,
                frame=frame,
                top_k=5,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            top1_score = candidates.top1_score
            margin = candidates.margin
            negative_scores.append(top1_score)
            negative_margins.append(margin)

            retrieved_names = [c.table_name for c in candidates]
            negative_results.append({
                "idx": idx,
                "question": question,
                "top1": retrieved_names[0] if retrieved_names else "None",
                "top5": retrieved_names[:5],
                "top1_score": top1_score,
                "margin": margin,
                "candidates": candidates,
                "elapsed_ms": elapsed_ms,
            })

            top5_display = ", ".join(f"{c.table_name} ({c.score:.4f})" for c in candidates[:5])
            print(f"[{idx:02d}] \"{question}\"")
            print(f"     top1_score : {top1_score:.4f} | margin: {margin:.4f} | Latency: {elapsed_ms:.1f}ms")
            print(f"     Top-5      : {top5_display}\n")

        # -------------------------------------------------------------
        # 6. Top 5 for Hold-Out Misses
        # -------------------------------------------------------------
        print("=" * 110)
        print("HOLD-OUT MISSES (TOP 5 CANDIDATES)")
        print("=" * 110)
        if holdout_misses:
            for m in holdout_misses:
                miss_type = "Top-1 Miss" if m["top3_hit"] else "Top-3 Miss"
                print(f"[{m['idx']:02d}] \"{m['question']}\" ({miss_type})")
                print(f"     Expected : {m['expected']}")
                print(f"     Got Top1 : {m['top1']}")
                print(f"     Top-5    :")
                for rank, c in enumerate(m["candidates"][:5], 1):
                    sigs = list(c.signals.keys())
                    print(f"       {rank}. {c.table_name:30s} score={c.score:.4f} | signals={sigs}")
                print()
        else:
            print("No hold-out misses! 100% accuracy achieved.\n")

        # -------------------------------------------------------------
        # 7. Overall Accuracy Summary Table
        # -------------------------------------------------------------
        print("=" * 110)
        print("RETRIEVAL ACCURACY SUMMARY")
        print("=" * 110)
        print(f"  Tuned Set    (14 questions) : Top-1 = {tuned_top1_correct}/{tuned_total} ({tuned_top1_acc:.1f}%) | Top-3 = {tuned_top3_correct}/{tuned_total} ({tuned_top3_acc:.1f}%)")
        print(f"  Hold-Out Set (16 questions) : Top-1 = {holdout_top1_correct}/{holdout_total} ({holdout_top1_acc:.1f}%) | Top-3 = {holdout_top3_correct}/{holdout_total} ({holdout_top3_acc:.1f}%)")
        total_pos = tuned_total + holdout_total
        total_pos_t1 = tuned_top1_correct + holdout_top1_correct
        total_pos_t3 = tuned_top3_correct + holdout_top3_correct
        print(f"  All Positives(30 questions) : Top-1 = {total_pos_t1}/{total_pos} ({(total_pos_t1/total_pos)*100:.1f}%) | Top-3 = {total_pos_t3}/{total_pos} ({(total_pos_t3/total_pos)*100:.1f}%)")
        print("=" * 110)

        # -------------------------------------------------------------
        # 8. Positives vs Negatives Score Distribution Summary
        # -------------------------------------------------------------
        pos_min_score = min(positive_scores)
        pos_med_score = statistics.median(positive_scores)
        pos_min_margin = min(positive_margins)
        pos_med_margin = statistics.median(positive_margins)

        neg_max_score = max(negative_scores)
        neg_med_score = statistics.median(negative_scores)
        neg_max_margin = max(negative_margins)
        neg_med_margin = statistics.median(negative_margins)

        print("\n" + "=" * 110)
        print("POSITIVES VS NEGATIVES SCORE DISTRIBUTION SUMMARY")
        print("=" * 110)
        print(f"{'Metric':<25} | {'Positives (30 queries)':<35} | {'Negatives (6 queries)':<25}")
        print("-" * 110)
        print(f"{'top1_score MIN':<25} | {pos_min_score:<35.4f} | {'N/A':<25}")
        print(f"{'top1_score MEDIAN':<25} | {pos_med_score:<35.4f} | {neg_med_score:<25.4f}")
        print(f"{'top1_score MAX':<25} | {max(positive_scores):<35.4f} | {neg_max_score:<25.4f}")
        print("-" * 110)
        print(f"{'margin MIN':<25} | {pos_min_margin:<35.4f} | {'N/A':<25}")
        print(f"{'margin MEDIAN':<25} | {pos_med_margin:<35.4f} | {neg_med_margin:<25.4f}")
        print(f"{'margin MAX':<25} | {max(positive_margins):<35.4f} | {neg_max_margin:<25.4f}")
        print("=" * 110)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run TableRetriever retrieval eval")
    parser.add_argument("--kb-id", type=str, default=None, help="Database Knowledgebase UUID")
    parser.add_argument("--tenant-id", type=str, default=None, help="Tenant UUID")
    args = parser.parse_args()

    asyncio.run(run_evaluation(kb_id_str=args.kb_id, tenant_id_str=args.tenant_id))
