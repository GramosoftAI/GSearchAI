import asyncio
from neo4j import AsyncGraphDatabase

async def check():
    uri = "bolt://localhost:7687"
    user = "neo4j"
    password = "nKFhg55qmg9BsDu"
    
    async with AsyncGraphDatabase.driver(uri, auth=(user, password)) as driver:
        async with driver.session() as session:
            result = await session.run("MATCH (c:Chunk) RETURN count(c) AS count")
            record = await result.single()
            print("Total Chunks in Neo4j:", record["count"])

            result = await session.run("MATCH (kb:KnowledgeBase {id: 'c936905e-68c6-471f-9395-62b39692a12e'})-[:HAS_DOCUMENT]->(d)-[:HAS_SECTION*0..2]->(s)-[:HAS_TEXT]->(c:Chunk) RETURN count(c) AS count")
            record = await result.single()
            print("Chunks in target KB:", record["count"] if record else 0)

asyncio.run(check())
