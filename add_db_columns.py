import asyncio
from sqlalchemy import text
from app.core.database import engine

async def main():
    async with engine.begin() as conn:
        print("Adding columns to analytics_query_logs...")
        await conn.execute(text("ALTER TABLE analytics_query_logs ADD COLUMN IF NOT EXISTS llm_input_tokens INTEGER DEFAULT 0 NOT NULL"))
        await conn.execute(text("ALTER TABLE analytics_query_logs ADD COLUMN IF NOT EXISTS llm_output_tokens INTEGER DEFAULT 0 NOT NULL"))
        await conn.execute(text("ALTER TABLE analytics_query_logs ADD COLUMN IF NOT EXISTS embedding_tokens INTEGER DEFAULT 0 NOT NULL"))
        await conn.execute(text("ALTER TABLE analytics_query_logs ADD COLUMN IF NOT EXISTS llm_cost_usd DOUBLE PRECISION DEFAULT 0.0 NOT NULL"))
        await conn.execute(text("ALTER TABLE analytics_query_logs ADD COLUMN IF NOT EXISTS embedding_cost_usd DOUBLE PRECISION DEFAULT 0.0 NOT NULL"))
        await conn.execute(text("ALTER TABLE analytics_query_logs ADD COLUMN IF NOT EXISTS total_cost_usd DOUBLE PRECISION DEFAULT 0.0 NOT NULL"))
        await conn.execute(text("ALTER TABLE analytics_query_logs ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL"))
        
        print("Adding columns to document_ingestion_runs...")
        await conn.execute(text("ALTER TABLE document_ingestion_runs ADD COLUMN IF NOT EXISTS embedding_tokens INTEGER DEFAULT 0 NOT NULL"))
        await conn.execute(text("ALTER TABLE document_ingestion_runs ADD COLUMN IF NOT EXISTS embedding_cost_usd DOUBLE PRECISION DEFAULT 0.0 NOT NULL"))
        
        print("Successfully updated database schema!")

if __name__ == "__main__":
    asyncio.run(main())
