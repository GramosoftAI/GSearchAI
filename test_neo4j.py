import asyncio
from neo4j import GraphDatabase

async def main():
    uri = "bolt://localhost:7687"
    username = "neo4j"
    password = "password" # default
    driver = GraphDatabase.driver(uri, auth=(username, password))
    
    cypher = """
    MATCH (c:Chunk)
    RETURN count(c) as count
    """
    
    with driver.session() as session:
        res = session.run(cypher)
        record = res.single()
        print(f"Total Chunk nodes in Neo4j: {record['count']}")

    cypher2 = """
    MATCH (kb:KnowledgeBase)
    RETURN count(kb) as count
    """
    with driver.session() as session:
        res = session.run(cypher2)
        record = res.single()
        print(f"Total KnowledgeBase nodes in Neo4j: {record['count']}")

if __name__ == "__main__":
    asyncio.run(main())
