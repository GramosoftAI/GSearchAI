import asyncio
import sys
sys.path.append('/app')
from schema.database import AsyncSessionLocal, UserPreference
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(UserPreference).filter(UserPreference.preference_key == 'exam_date'))
        p = result.scalars().first()
        if p:
            p.preference_key = 'last_faa_medical_exam_date'
            await db.commit()
            print("Changed key to last_faa_medical_exam_date")
        else:
            print("Key not found")

if __name__ == "__main__":
    asyncio.run(main())
