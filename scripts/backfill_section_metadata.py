import asyncio
import os
import sys
from sqlalchemy import text
from dotenv import load_dotenv
from neo4j import GraphDatabase
import logging

# Ensure the root directory is in the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.core.config import get_settings

load_dotenv()
settings = get_settings()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def backfill_sections():
    logger.info("Starting section metadata backfill from Neo4j to PostgreSQL...")
    
    # 1. Connect to Neo4j
    neo4j_uri = settings.neo4j_uri
    neo4j_user = settings.neo4j_user
    neo4j_password = settings.neo4j_password
    
    if not all([neo4j_uri, neo4j_user, neo4j_password]):
        logger.error("Missing Neo4j connection settings.")
        return
        
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    
    # 2. Query Neo4j for chunks with a section
    query = """
    MATCH (c:Chunk)
    WHERE c.section IS NOT NULL
    RETURN c.id AS chunk_id, c.section AS section
    """
    
    chunks_to_update = []
    with driver.session() as session:
        result = session.run(query)
        for record in result:
            chunks_to_update.append({
                "chunk_id": record["chunk_id"],
                "section": record["section"]
            })
            
    driver.close()
    
    if not chunks_to_update:
        logger.info("No chunks with section metadata found in Neo4j. Nothing to backfill.")
        return
        
    logger.info(f"Found {len(chunks_to_update)} chunks in Neo4j with section metadata.")
    
    # 3. Update PostgreSQL
    async with AsyncSessionLocal() as db_session:
        updated_count = 0
        batch_size = 100
        
        for i in range(0, len(chunks_to_update), batch_size):
            batch = chunks_to_update[i:i+batch_size]
            
            # Using parameterized query for safety
            update_query = text("""
            UPDATE document_chunks
            SET section = :section
            WHERE id = :chunk_id AND (section IS NULL OR section != :section)
            """)
            
            for item in batch:
                res = await db_session.execute(
                    update_query, 
                    {"section": item["section"], "chunk_id": item["chunk_id"]}
                )
                updated_count += res.rowcount
            
            await db_session.commit()
            logger.info(f"Processed batch {i//batch_size + 1}, updated {updated_count} chunks so far.")
            
        logger.info(f"Backfill complete! Updated {updated_count} rows in PostgreSQL.")

if __name__ == "__main__":
    asyncio.run(backfill_sections())
