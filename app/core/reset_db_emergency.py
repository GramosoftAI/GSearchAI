"""Database reset utility - use with caution!"""

import asyncio
import asyncpg
import logging
from .config import get_settings

logger = logging.getLogger(__name__)


async def reset_database_schema():
    """
    DANGEROUS: Drop and recreate the database schema completely.
    Only call this during development when you really need to reset!
    """
    settings = get_settings()
    conn = None
    try:
        # Connect WITHOUT specifying the target database
        conn = await asyncpg.connect(
            user=settings.postgres_user,
            password=settings.postgres_password,
            host=settings.postgres_host,
            port=settings.postgres_port,
            database="postgres",  # Connect to default postgres db first
        )

        # Terminate connections to target database
        await conn.execute(
            f"SELECT pg_terminate_backend(pg_stat_activity.pid) "
            f"FROM pg_stat_activity "
            f"WHERE pg_stat_activity.datname = '{settings.postgres_db}' "
            f"AND pid <> pg_backend_pid()"
        )
        logger.info(f" Terminated connections to {settings.postgres_db}")

        # Drop the database
        await conn.execute(f"DROP DATABASE IF EXISTS {settings.postgres_db}")
        logger.info(f" Dropped {settings.postgres_db} database")

        # Recreate the database
        await conn.execute(f"CREATE DATABASE {settings.postgres_db} OWNER {settings.postgres_user}")
        logger.info(f" Recreated {settings.postgres_db} database")

        await conn.close()
        logger.info(" Database schema reset complete")

    except Exception as e:
        logger.error(f" Failed to reset database: {e}")
        if conn:
            await conn.close()
        raise


if __name__ == "__main__":
    asyncio.run(reset_database_schema())
