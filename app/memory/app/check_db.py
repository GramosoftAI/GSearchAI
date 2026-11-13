import asyncio
import sys
sys.path.append('/app')
from schema.database import AsyncSessionLocal, UserPreference
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(UserPreference))
        prefs = result.scalars().all()
        for p in prefs:
            print(f"Key: {p.preference_key}, Value: {p.preference_value}")

if __name__ == "__main__":
    asyncio.run(main())
