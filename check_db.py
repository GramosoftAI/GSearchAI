import asyncio
import sys
import os
sys.path.append('.')

from app.memory.app.schema.database import AsyncSessionLocal, UserPreference
from sqlalchemy import select
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv("app/memory/.env")

async def main():
    print("--- Postgres UserPreference (test-tenant-2) ---")
    async with AsyncSessionLocal() as db:
        stmt = select(UserPreference).filter(
            UserPreference.tenant_id == "test-tenant-2",
            UserPreference.user_id == "test-user-2",
            UserPreference.agent_id == "test-agent-2"
        )
        result = await db.execute(stmt)
        prefs = result.scalars().all()
        for p in prefs:
            print(f"Key: {p.preference_key}, Value: {p.preference_value}")
        if not prefs:
            print("No Postgres rows found.")

    print("--- Neo4j MemoryEntity (test-tenant-2) ---")
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "graphmind_password")
    
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            result = session.run("MATCH (s:MemoryEntity {tenant_id: 'test-tenant-2', user_id: 'test-user-2'})-[r]->(o) RETURN s.name, type(r), o.name")
            records = list(result)
            for record in records:
                print(f"{record['s.name']} -[{record['type(r)']}]-> {record['o.name']}")
            if not records:
                print("No Neo4j relationships found.")
        driver.close()
    except Exception as e:
        print("Neo4j error:", e)

if __name__ == "__main__":
    asyncio.run(main())
