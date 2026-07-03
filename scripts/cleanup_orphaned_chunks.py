import asyncio
import os
import sys

# Add the app directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.database import AsyncSessionLocal
from app.core.neo4j import get_neo4j_context
from sqlalchemy import text

async def cleanup_orphaned_data():
    print("Starting Orphaned Data Cleanup...")
    
    async with AsyncSessionLocal() as session:
        # 1. Clean PostgreSQL Vector DB (pgvector)
        # Find all chunks whose parent KB or Agent is deleted (is_active = False) or missing
        pg_query = """
        DELETE FROM document_chunks
        WHERE kb_id IN (
            SELECT dc.kb_id FROM document_chunks dc
            LEFT JOIN knowledge_bases kb ON dc.kb_id = kb.id
            LEFT JOIN agents a ON kb.agent_id = a.id
            WHERE kb.id IS NULL OR kb.is_active = FALSE OR a.id IS NULL OR a.is_active = FALSE
        )
        RETURNING kb_id;
        """
        try:
            result = await session.execute(text(pg_query))
            deleted_pg_chunks = result.fetchall()
            await session.commit()
            print(f" PostgreSQL: Cleaned up {len(deleted_pg_chunks)} orphaned document chunks.")
        except Exception as e:
            await session.rollback()
            print(f" PostgreSQL cleanup failed: {e}")

    # 2. Clean Neo4j Graph Database
    async with get_neo4j_context() as neo4j_session:
        # Delete chunks that have no parent KB, or whose parent KB has no Agent
        neo4j_query = """
        MATCH (c:Chunk)
        OPTIONAL MATCH (c)<-[:HAS_CHUNK]-(kb:KnowledgeBase)
        OPTIONAL MATCH (kb)<-[:OWNS_KB]-(a:Agent)
        WITH c, kb, a
        WHERE kb IS NULL OR a IS NULL
        DETACH DELETE c
        RETURN count(c) as deleted_count
        """
        try:
            result = await neo4j_session.run(neo4j_query)
            record = await result.single()
            count = record['deleted_count'] if record else 0
            print(f" Neo4j: Cleaned up {count} orphaned graph chunks.")
        except Exception as e:
            print(f" Neo4j cleanup failed: {e}")

    print("Cleanup Complete!")

if __name__ == "__main__":
    asyncio.run(cleanup_orphaned_data())
