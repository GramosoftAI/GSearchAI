import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import engine
from app.core.config import get_settings
import json

async def benchmark():
    settings = get_settings()
    
    # Generate a dummy 1024-d vector
    dummy_vector = [0.01] * 1024
    vector_str = f"[{','.join(map(str, dummy_vector))}]"

    async with engine.begin() as conn:
        # Check row count
        cnt = await conn.execute(text("SELECT count(*) FROM document_chunks;"))
        row_count = cnt.scalar()
        
        print(f"--- HNSW BENCHMARK SCRIPT ---")
        print(f"Row count: {row_count}")
        if row_count < 1000:
            print("WARNING: Table is extremely small. EXPLAIN ANALYZE latency differences will be sub-millisecond noise.")
            print("The planner might even prefer a Seq Scan over an Index Scan on a tiny table. This is normal Postgres behavior.")
            print("Results are directional only. Revisit at production scale (e.g. >100k rows).\n")

        # We must disable enable_seqscan to force the planner to use the index if possible on small tables
        await conn.execute(text("SET enable_seqscan = off;"))

        ef_search_values = [40, 80, 100, 150]
        
        for ef in ef_search_values:
            print(f"--- Benchmarking with ef_search = {ef} ---")
            await conn.execute(text(f"SET LOCAL hnsw.ef_search = {ef};"))
            
            # Using <-> for cosine distance (vector_cosine_ops)
            query = f"""
            EXPLAIN ANALYZE
            SELECT id, 1 - (embedding_bge <=> '{vector_str}'::vector) as similarity
            FROM document_chunks
            ORDER BY embedding_bge <=> '{vector_str}'::vector
            LIMIT 15;
            """
            
            result = await conn.execute(text(query))
            plans = result.fetchall()
            for plan in plans:
                print(plan[0])
            print("\n")

if __name__ == "__main__":
    asyncio.run(benchmark())
