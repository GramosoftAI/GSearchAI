import asyncio
from neo4j import GraphDatabase
from app.core.config import get_settings

settings = get_settings()

def get_stats():
    driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
    with driver.session() as session:
        # Get kb names mapped to kb_id from Postgres since Neo4j might just store kb_id
        # Let's see what is stored on Chunk nodes
        res = session.run("MATCH (c:Chunk) RETURN c.kb_id as kb_id, count(c) as chunk_count").data()
        
        for record in res:
            kb_id = record['kb_id']
            chunk_count = record['chunk_count']
            
            # Count triplets
            triplet_res = session.run(
                "MATCH (c:Chunk {kb_id: $kb_id})-[:HAS_TRIPLET]->(t:Triplet) RETURN count(t) as triplet_count",
                kb_id=kb_id
            ).single()
            triplet_count = triplet_res['triplet_count']
            
            triplets_per_chunk = triplet_count / chunk_count if chunk_count > 0 else 0
            
            print(f"KB ID: {kb_id}")
            print(f"Chunk count: {chunk_count}")
            print(f"Triplet count: {triplet_count}")
            print(f"Triplets per chunk: {triplets_per_chunk:.2f}\n")

if __name__ == "__main__":
    get_stats()
