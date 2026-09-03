import asyncio
from app.core.database import engine
from sqlalchemy import text

async def main():
    async with engine.begin() as conn:
        try:
            await conn.execute(text("ALTER TABLE knowledge_bases ADD COLUMN metadata_json JSONB;"))
            print("Successfully added metadata_json column.")
        except Exception as e:
            print(f"Error: {e}")
            
if __name__ == "__main__":
    asyncio.run(main())
