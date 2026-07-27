import asyncio
from app.core.neo4j import get_neo4j_driver

async def main():
    driver = await get_neo4j_driver()
    async with driver.session() as session:
        # Get count of all labels and their tenants
        query = '''
        MATCH (n)
        RETURN labels(n) AS lbls, n.tenant_id AS tid, count(n) AS cnt
        '''
        res = await session.run(query)
        data = await res.data()
        print('Nodes count by label and tenant:')
        for row in data:
            print(f"  Labels: {row['lbls']}, Tenant: {row['tid']}, Count: {row['cnt']}")

if __name__ == '__main__':
    asyncio.run(main())
