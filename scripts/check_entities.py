import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres%40docker@localhost:5433/graphmind')
    result = await conn.fetch('''
        SELECT DISTINCT entity_type, entity_value FROM document_entities LIMIT 20;
    ''')
    for r in result:
        print(f"type='{r['entity_type']}', value='{r['entity_value']}'")
    await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
