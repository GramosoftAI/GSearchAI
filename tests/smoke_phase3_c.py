"""Smoke test for Phase 3 Build C (Steps 3.8 - 3.10).

Calls ContextPackBuilder for 8 questions:
1. "Girinath oda last month 8 hours kela work panna dates sollu"
2. "employees in Chennai branch"
3. "total orders per customer"
4. "delivered orders last week"
5. "working hours of Girinath R"
6. "salary of employees" (unanswerable)
7. "show customers"
8. "nonsense question"

Prints compact summary of each pack:
tables, joins, entities status, confidence, clarifications, unanswerable,
trimmed items, tokens used, total latency.
"""

import sys
import os
import asyncio
import time
import subprocess
from datetime import date

# Setup sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.modules.database_knowledgebase.models.database_knowledgebase import DatabaseKnowledgebase
from app.modules.database_knowledgebase.knowledge.retrieval import (
    ContextPackBuilder,
    ContextPack,
)
from sqlalchemy import select


QUESTIONS = [
    "Girinath oda last month 8 hours kela work panna dates sollu",
    "employees in Chennai branch",
    "total orders per customer",
    "delivered orders last week",
    "working hours of Girinath R",
    "salary of employees",
    "show customers",
    "flubb dubb zap blorp nonsense query",
]


async def run_smoke():
    print("=" * 115)
    print("PHASE 3 BUILD C SMOKE TEST (Steps 3.8 - 3.10)")
    print("=" * 115)

    ref_date = date(2026, 4, 1)

    async with AsyncSessionLocal() as db:
        stmt = select(DatabaseKnowledgebase).order_by(DatabaseKnowledgebase.created_at.desc()).limit(1)
        res = await db.execute(stmt)
        kb = res.scalar_one_or_none()

        if not kb:
            print("ERROR: No DatabaseKnowledgebase found!")
            return

        tenant_id = kb.tenant_id
        kb_id = kb.id

        builder = ContextPackBuilder(db=db, tenant_id=tenant_id)

        print(f"Target KB: {kb.name} (id: {kb_id})")
        print("-" * 115)

        for idx, q in enumerate(QUESTIONS, 1):
            t0 = time.perf_counter()
            pack: ContextPack = await builder.build(
                db_knowledgebase_id=kb_id,
                question=q,
                reference_date=ref_date,
            )
            total_elapsed = (time.perf_counter() - t0) * 1000

            # Summary elements
            tbls = [t["name"] for t in pack.tables[:3]]
            tbls_str = ", ".join(tbls) if tbls else "none"

            joins_list = [f"{j['left_table']}->{j['right_table']}" for j in pack.joins]
            joins_str = ", ".join(joins_list) if joins_list else "none"

            ent_statuses = [f"{e['table']}.{e['column']} ({e['status']})" for e in pack.entities]
            ent_str = ", ".join(ent_statuses) if ent_statuses else "none"

            unans_str = f"UNANSWERABLE ({pack.unanswerable['reason']})" if pack.unanswerable.get("flag") else "False"
            clar_count = len(pack.clarifications)
            trimmed_count = len(pack.trimmed_items)

            print(f"[{idx:02d}] \"{q}\"")
            print(f"     Tables: {tbls_str} | Joins: {joins_str} | Entities: {ent_str}")
            print(f"     Confidence: {pack.confidence} | Clarifications: {clar_count} | Unanswerable: {unans_str}")
            print(f"     Trimmed: {trimmed_count} items | Tokens: {pack.tokens_used} | Latency: {total_elapsed:.1f}ms")
            print("-" * 115)


if __name__ == "__main__":
    asyncio.run(run_smoke())
