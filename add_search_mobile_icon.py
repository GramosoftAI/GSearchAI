import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def alter_db():
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(text("ALTER TABLE widget_embed_configs ADD COLUMN search_mobile_icon BOOLEAN NOT NULL DEFAULT FALSE;"))
            print("Added search_mobile_icon to widget_embed_configs")
        except Exception as e:
            print("Error adding search_mobile_icon:", e)
        await db.commit()

if __name__ == "__main__":
    asyncio.run(alter_db())
