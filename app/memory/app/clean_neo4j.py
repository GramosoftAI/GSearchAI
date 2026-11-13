import asyncio
import sys
from neo4j import AsyncGraphDatabase

async def clean_neo4j():
    driver = AsyncGraphDatabase.driver("bolt://neo4j:7687", auth=("neo4j", "graphmind_password"))
    try:
        async with driver.session() as session:
            # First, check what exists
            result = await session.run("MATCH (n:MemoryEntity) WHERE n.name CONTAINS '06/01/2007' RETURN n.name AS name")
            nodes = await result.data()
            print("Found nodes to delete:", nodes)
            
            # Delete them
            result = await session.run("MATCH (n:MemoryEntity) WHERE n.name CONTAINS '06/01/2007' DETACH DELETE n")
            print("Deleted old 06/01/2007 nodes from Neo4j.")
            
            # Also clean up 'last faa medical exam' if it's pointing to anything else just in case
            result = await session.run("MATCH (n:MemoryEntity {name: 'last faa medical exam'})-[r]->(o) SET o.name = '06/07/2026' RETURN o.name AS name")
            nodes = await result.data()
            print("Updated 'last faa medical exam' target to 06/07/2026:", nodes)
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await driver.close()

if __name__ == "__main__":
    asyncio.run(clean_neo4j())
