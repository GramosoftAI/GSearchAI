import asyncio
import logging
from uuid import UUID

logging.basicConfig(level=logging.DEBUG)

import sys
sys.path.append(r'V:\graphmind')

from sqlalchemy import text
from app.core.database import async_sessionmaker, engine
from app.modules.analytics.repository import AnalyticsRepository
from app.modules.analytics.models import ResponseStatus

async def main():
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as db:
        # Get a real tenant_id
        result = await db.execute(text("SELECT id FROM tenants LIMIT 1"))
        tenant_row = result.first()
        if not tenant_row:
            print("No tenant found!")
            return
        
        tenant_id = tenant_row[0]
        print(f"Using Tenant ID: {tenant_id}")
        
        repo = AnalyticsRepository(db, UUID(str(tenant_id)))
        try:
            await repo.create_query_log({
                "query": "Test UNANSWERED query",
                "response_status": ResponseStatus.UNANSWERED,
                "confidence_score": 0.0,
                "latency_ms": 1500.5
            })
            await db.commit()
            print("Successfully created query log!")
        except Exception as e:
            print(f"Error creating log: {e}")
            await db.rollback()

if __name__ == '__main__':
    asyncio.run(main())
