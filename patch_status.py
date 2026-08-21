import asyncio
from sqlalchemy import text
from app.core.database import engine

async def main():
    async with engine.begin() as conn:
        print('Adding status to knowledge_bases...')
        try:
            await conn.execute(text('ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT ''INGESTED'' NOT NULL'))
        except Exception as e:
            print(f'Error: {e}')

if __name__ == '__main__':
    asyncio.run(main())
