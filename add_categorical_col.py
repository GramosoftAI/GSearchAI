import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import engine
from sqlalchemy import text

async def run():
    async with engine.begin() as conn:
        try:
            await conn.execute(text("ALTER TABLE knowledge_bases ADD COLUMN categorical_values JSONB;"))
            print("Column 'categorical_values' added successfully to 'knowledge_bases' table.")
        except Exception as e:
            print(f"Error adding column: {e}")

if __name__ == "__main__":
    asyncio.run(run())
