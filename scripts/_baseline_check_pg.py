"""One-off connectivity check for STEP 2 baseline. Safe to delete later."""
import asyncio
import os
import asyncpg


async def check(user, password, database):
    host = os.getenv("TEST_PG_HOST", "localhost")
    port = int(os.getenv("TEST_PG_PORT", "5433"))
    try:
        conn = await asyncpg.connect(
            host=host, port=port, user=user, password=password, database=database, timeout=5
        )
        tables = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1"
        )
        print(f"OK {database} as {user}: tables={[r['tablename'] for r in tables]}")
        for t in [r["tablename"] for r in tables]:
            try:
                n = await conn.fetchval(f'SELECT COUNT(*) FROM "{t}"')
                print(f"  COUNT {t}={n}")
            except Exception as e:
                print(f"  COUNT {t} ERR {e}")
        await conn.close()
    except Exception as e:
        print(f"FAIL {database} as {user}: {type(e).__name__}: {e}")


async def main():
    await check("test_ro_user", "test_ro_password", "gsearch_test_db")
    # also try postgres admin for golden DB creation later
    for user, pw in [("postgres", "postgres"), ("postgres", "password"), ("gsearch", "gsearch")]:
        try:
            host = os.getenv("TEST_PG_HOST", "localhost")
            port = int(os.getenv("TEST_PG_PORT", "5433"))
            conn = await asyncpg.connect(
                host=host, port=port, user=user, password=pw, database="postgres", timeout=3
            )
            print(f"ADMIN_OK user={user}")
            await conn.close()
            break
        except Exception as e:
            print(f"ADMIN_FAIL user={user}: {type(e).__name__}")


if __name__ == "__main__":
    asyncio.run(main())
