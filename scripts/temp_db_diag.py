import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres%40docker@localhost:5433/graphmind')
    await conn.execute('''
        ALTER TABLE chat_messages
        ADD COLUMN IF NOT EXISTS feedback_type VARCHAR,
        ADD COLUMN IF NOT EXISTS feedback_reason VARCHAR,
        ADD COLUMN IF NOT EXISTS feedback_at TIMESTAMP WITH TIME ZONE,
        ADD COLUMN IF NOT EXISTS feedback_score INTEGER;
    ''')
    print('Columns added successfully!')
    await conn.close()

asyncio.run(main())
