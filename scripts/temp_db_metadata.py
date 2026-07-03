import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres%40docker@localhost:5433/graphmind')
    await conn.execute('''
        ALTER TABLE document_chunks
        ADD COLUMN IF NOT EXISTS metadata_json JSONB;
    ''')
    print('metadata_json column added successfully!')
    await conn.close()

asyncio.run(main())
