import os
import sys
import logging
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("StartupValidator")

def validate_imports():
    logger.info("Validating critical imports...")
    try:
        from app.core.database import AsyncSessionLocal
        from app.core.llm.deepinfra_llm import DeepInfraLLMClient
        # Attempting basic imports just to verify no syntax errors prevent booting
        logger.info("Critical imports successful.")
        return True
    except Exception as e:
        logger.error(f"Failed to import critical modules: {e}")
        return False

async def validate_database():
    logger.info("Validating database connectivity...")
    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        logger.info("Database connectivity successful.")
        return True
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        return False

async def main():
    logger.info("Starting deployment startup validation...")
    
    if not validate_imports():
        sys.exit(1)
        
    if not await validate_database():
        sys.exit(1)
        
    logger.info("Startup validation passed.")
    sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
