"""Smoke test for Phase 3 Build B (Steps 3.6 - 3.7).

Checks:
- Live entity resolution:
  - "Girinath" (expect ambiguous with choices)
  - "Girinath R" (resolved, one PK)
  - "Girnath" (typo -> ambiguous or closest)
  - "Chennai"
  - "customer" (no match)
  - "salary" (unanswerable)
- JoinPathFinder:
  - [employees, attendance]
  - [employees, branches, attendance]
  - [orders, customers, payments]
  - [employees, tx_log] (or disconnected pair)
Report timing.
"""

import sys
import os
import asyncio
import time
import uuid

# Setup sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.modules.database_knowledgebase.models.database_knowledgebase import DatabaseKnowledgebase
from app.modules.database_knowledgebase.knowledge.retrieval import (
    QuestionAnalyzer,
    LiveEntityResolver,
    JoinPathFinder,
)
from sqlalchemy import select


ENTITY_QUERIES = [
    "Girinath",
    "Girinath R",
    "Girnath",
    "Chennai",
    "customer",
    "salary",
]

JOIN_SETS = [
    ["employees", "attendance"],
    ["employees", "branches", "attendance"],
    ["orders", "customers", "payments"],
    ["ref_codes", "attendance"],  # disconnected pair
]


async def run_smoke():
    print("=" * 110)
    print("PHASE 3 BUILD B SMOKE TEST (Steps 3.6 - 3.7)")
    print("=" * 110)

    analyzer = QuestionAnalyzer()

    async with AsyncSessionLocal() as db:
        stmt = select(DatabaseKnowledgebase).order_by(DatabaseKnowledgebase.created_at.desc()).limit(1)
        res = await db.execute(stmt)
        kb = res.scalar_one_or_none()

        if not kb:
            print("ERROR: No DatabaseKnowledgebase found!")
            return

        tenant_id = kb.tenant_id
        kb_id = kb.id

        resolver = LiveEntityResolver(db=db, tenant_id=tenant_id)
        finder = JoinPathFinder(db=db, tenant_id=tenant_id)
        await finder.build_graph(db_knowledgebase_id=kb_id)

        print(f"Target KB: {kb.name} (id: {kb_id})")
        print("-" * 110)
        print("PART 1: LIVE ENTITY RESOLUTION")
        print("-" * 110)

        for q in ENTITY_QUERIES:
            t0 = time.perf_counter()
            frame = analyzer.analyze(q)
            res_entity = await resolver.resolve(db_knowledgebase_id=kb_id, frame=frame)
            elapsed = (time.perf_counter() - t0) * 1000

            if res_entity.unanswerable:
                status_str = f"UNANSWERABLE: {res_entity.unanswerable_reason}"
            elif not res_entity.resolved_entities:
                status_str = "NO_MATCH"
            else:
                details = []
                for re in res_entity.resolved_entities:
                    if re.ambiguous:
                        choice_labels = [c.display_label for c in re.choices]
                        details.append(f"{re.table_name}.{re.column_name} AMBIGUOUS choices={choice_labels}")
                    else:
                        details.append(f"{re.table_name}.{re.column_name} RESOLVED (PK={re.pk_value})")
                status_str = " | ".join(details)

            print(f"Query: \"{q}\" -> {status_str} (Timing: {elapsed:.1f}ms)")

        print("-" * 110)
        print("PART 2: JOIN PATH FINDER")
        print("-" * 110)

        for tables in JOIN_SETS:
            t0 = time.perf_counter()
            join_res = finder.find_join_tree(tables)
            elapsed = (time.perf_counter() - t0) * 1000

            if not join_res.success:
                print(f"Tables: {tables} -> DISCONNECTED (Unreachable: {join_res.unreachable_tables}) (Timing: {elapsed:.1f}ms)")
            else:
                joins_summary = [
                    f"{j.left_table}.{j.left_col} -> {j.right_table}.{j.right_col} [{j.cardinality}, {j.source}]"
                    for j in join_res.joins
                ]
                bridges_str = f"Bridges: {join_res.bridge_tables}" if join_res.bridge_tables else "No bridges"
                print(f"Tables: {tables} -> Joins: {', '.join(joins_summary)} | {bridges_str} | Cost: {join_res.total_cost} (Timing: {elapsed:.1f}ms)")

        print("=" * 110)


if __name__ == "__main__":
    asyncio.run(run_smoke())
