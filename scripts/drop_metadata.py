import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres%40docker@localhost:5433/graphmind')
    await conn.execute('''
        ALTER TABLE document_chunks
        DROP COLUMN IF EXISTS metadata_json;
    ''')
    print('metadata_json dropped!')
    await conn.close()

asyncio.run(main())
