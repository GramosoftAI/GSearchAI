import asyncio
import uuid

from app.core.database import AsyncSessionLocal
from app.modules.database_knowledgebase.knowledge.jobs.pipeline import (
    execute_phase2_pipeline,
    set_rls_tenant_context,
)


async def run_phase2():
    tenant_id = uuid.UUID("2b41fa8c-9c12-491d-8199-a75292e683ec")
    kb_id = uuid.UUID("594b579b-d6be-4b15-a554-14d7225f39cc")

    async with AsyncSessionLocal() as session:
        await set_rls_tenant_context(session, tenant_id)

        print("Starting Phase 2 Knowledge Layer extraction...")

        ctx = await execute_phase2_pipeline(
            tenant_id=tenant_id,
            kb_id=kb_id,
            session=session,
        )

        print("Phase 2 Pipeline Finished!")
        print(f"Processed tables: {len(getattr(ctx, 'tables', []))}")


if __name__ == "__main__":
    asyncio.run(run_phase2())