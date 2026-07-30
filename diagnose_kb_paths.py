import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
import os, sys

AGENT_ID = "b4f5bac9-2ecb-485b-bab5-4d75feba2f45"
DB_URL = "postgresql+asyncpg://graphmind:graphmind_password@localhost:5433/graphmind"

async def diagnose():
    engine = create_async_engine(DB_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # 1. Find knowledge bases linked to this agent
        res = await session.execute(text("""
            SELECT id, name, parsed_path, s3_path, source
            FROM knowledge_bases
            WHERE agent_id = :agent_id AND is_active = TRUE
        """), {"agent_id": AGENT_ID})
        rows = res.fetchall()
        
        print(f"\n{'='*70}")
        print(f"Knowledge Bases for Agent: {AGENT_ID}")
        print(f"{'='*70}")
        for r in rows:
            print(f"\n  KB ID      : {r[0]}")
            print(f"  Name       : {r[1]}")
            print(f"  parsed_path: {r[2]}")
            print(f"  s3_path    : {r[3]}")
            print(f"  source     : {r[4]}")
            
            if r[2]:
                local_exists = os.path.exists(str(r[2]))
                print(f"  [LOCAL] parsed_path exists on disk: {local_exists}")
            if r[3]:
                local_exists_s3 = os.path.exists(str(r[3]))
                print(f"  [LOCAL] s3_path exists on disk    : {local_exists_s3}")

        print(f"\n{'='*70}")
        print("Checking document_chunks table for CSV KB rows...")
        if rows:
            for r in rows:
                if r[2] and str(r[2]).lower().endswith('.csv'):
                    res2 = await session.execute(text("""
                        SELECT id, chunk_index, text FROM document_chunks
                        WHERE kb_id = :kb_id LIMIT 5
                    """), {"kb_id": r[0]})
                    chunks = res2.fetchall()
                    print(f"\n  CSV KB '{r[1]}' has {len(chunks)} sample chunk(s) in document_chunks table:")
                    for c in chunks:
                        print(f"    chunk #{c[1]}: {str(c[2])[:120]!r}")

asyncio.run(diagnose())
