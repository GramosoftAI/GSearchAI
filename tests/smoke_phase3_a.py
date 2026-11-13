"""Smoke test for Phase 3 Build A (Steps 3.3 - 3.5).

Runs 13 test questions:
1. Girinath attendance
2. Girnath
3. working hours
4. employees in Chennai branch
5. late arrivals
6. total orders per customer
7. delivered orders
8. cancelled orders
9. salary
10. salry
11. nonsense
12. last month attendance
13. Girinath oda last month 8 hours kela work panna dates sollu

Outputs one line each:
frame summary | top 3 tables | top 3 columns | timing per stage
"""

import sys
import os
import asyncio
import time
from datetime import date
from typing import List

# Setup sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.modules.database_knowledgebase.models.database_knowledgebase import DatabaseKnowledgebase
from app.modules.database_knowledgebase.knowledge.retrieval import (
    QuestionAnalyzer,
    QuestionFrame,
    TableRetriever,
    ColumnRetriever,
)
from sqlalchemy import select


QUESTIONS = [
    "Girinath attendance",
    "Girnath",
    "working hours",
    "employees in Chennai branch",
    "late arrivals",
    "total orders per customer",
    "delivered orders",
    "cancelled orders",
    "salary",
    "salry",
    "nonsense",
    "last month attendance",
    "Girinath oda last month 8 hours kela work panna dates sollu",
]


async def run_smoke():
    analyzer = QuestionAnalyzer()
    ref_date = date(2026, 4, 1)

    print("=" * 110)
    print("PHASE 3 BUILD A SMOKE TEST (Steps 3.3 - 3.5)")
    print("=" * 110)

    async with AsyncSessionLocal() as db:
        # Fetch knowledgebase id for customer_sim
        stmt = select(DatabaseKnowledgebase).order_by(DatabaseKnowledgebase.created_at.desc()).limit(1)
        res = await db.execute(stmt)
        kb = res.scalar_one_or_none()

        if not kb:
            print("ERROR: No DatabaseKnowledgebase found in test_throwaway_kb2!")
            return

        tenant_id = kb.tenant_id
        kb_id = kb.id

        table_retriever = TableRetriever(db=db, tenant_id=tenant_id)
        col_retriever = ColumnRetriever(db=db, tenant_id=tenant_id)

        print(f"Target KB: {kb.name} (id: {kb_id}, tenant: {tenant_id})")
        print("-" * 110)

        for idx, q in enumerate(QUESTIONS, 1):
            # 1. Question Analysis
            t0 = time.perf_counter()
            frame: QuestionFrame = analyzer.analyze(q, reference_date=ref_date)
            t_analyzer = (time.perf_counter() - t0) * 1000

            # 2. Table Retrieval
            t1 = time.perf_counter()
            table_cands = await table_retriever.retrieve_tables(
                db_knowledgebase_id=kb_id,
                frame=frame,
                top_k=3,
            )
            t_table = (time.perf_counter() - t1) * 1000

            # 3. Column Retrieval
            t2 = time.perf_counter()
            bundles = await col_retriever.retrieve_for_tables(
                db_knowledgebase_id=kb_id,
                frame=frame,
                candidate_tables=table_cands,
                top_k_columns_per_table=3,
            )
            t_col = (time.perf_counter() - t2) * 1000

            # Format frame summary
            f_summary = []
            if frame.tokens:
                f_summary.append(f"tokens:{','.join(frame.tokens[:3])}")
            if frame.time_range:
                f_summary.append(f"time:[{frame.time_range.start_date}..{frame.time_range.end_date}]")
            if frame.unit_values:
                f_summary.append(f"units:{','.join(f'{u.numeric_value}{u.unit}' for u in frame.unit_values)}")
            if frame.comparison:
                f_summary.append(f"op:{frame.comparison.operator}")
            if frame.aggregation_cues:
                f_summary.append(f"agg:{','.join(frame.aggregation_cues)}")
            if frame.entity_candidates:
                f_summary.append(f"ent:{','.join(frame.entity_candidates)}")
            frame_str = " ".join(f_summary) if f_summary else "raw"

            # Format tables
            top_tables = [c.table_name for c in table_cands[:3]]
            tables_str = ", ".join(top_tables) if top_tables else "none"

            # Format columns across top candidate tables
            top_cols = []
            for b in bundles:
                for c in b.columns[:2]:
                    top_cols.append(f"{b.table_name}.{c.column_name}")
            cols_str = ", ".join(top_cols[:3]) if top_cols else "none"

            # Timing
            timing_str = f"A:{t_analyzer:.1f}ms | T:{t_table:.1f}ms | C:{t_col:.1f}ms"

            print(f"[{idx:02d}] \"{q}\"")
            print(f"     Frame: {frame_str}")
            print(f"     Top Tables: {tables_str}")
            print(f"     Top Columns: {cols_str}")
            print(f"     Timing: {timing_str}")
            print("-" * 110)


if __name__ == "__main__":
    asyncio.run(run_smoke())
