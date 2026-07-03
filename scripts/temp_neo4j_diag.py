import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.core.neo4j import get_neo4j_context

async def check_neo4j():
    async with get_neo4j_context() as session:
        print('=== NEO4J RAJAT TESTIMONIAL CHUNKS ===')
        query = """
        MATCH (c:Chunk)
        WHERE c.text CONTAINS 'Rajat' OR c.text CONTAINS 'Mithunn'
        RETURN c.id as chunk_id, c.kb_id as kb_id, substring(c.text, 0, 200) as text
        """
        
        result = await session.run(query)
        records = await result.data()
        
        if not records:
            print("No Rajat/Mithunn chunks found in Neo4j.")
        else:
            for r in records:
                print(f"CHUNK ID: {r['chunk_id']}")
                print(f"KB ID: {r['kb_id']}")
                print(f"TEXT: {r['text']}...\n")

asyncio.run(check_neo4j())
