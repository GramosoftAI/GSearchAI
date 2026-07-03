import asyncio
import asyncpg
import sys

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres%40docker@localhost:5433/graphmind')
    try:
        # Check enum types
        result = await conn.fetch('''
            SELECT unnest(enum_range(NULL::responsestatus))
        ''')
        print("Enum values in DB:")
        for r in result:
            print(f"- {r[0]}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
