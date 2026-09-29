import asyncio
import collections
import statistics
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.core.config import get_settings
from tokenizers import Tokenizer

settings = get_settings()

async def analyze():
    engine = create_async_engine(settings.database_url)
    tokenizer_path = os.path.join(os.path.dirname(__file__), 'models', 'tokenizer.json')
    try:
        tokenizer = Tokenizer.from_file(tokenizer_path)
    except Exception as e:
        print(f"Error loading tokenizer: {e}")
        return

    async with engine.begin() as conn:
        res = await conn.execute(text("""
            SELECT kb.name, dc.text 
            FROM document_chunks dc
            JOIN knowledge_bases kb ON dc.kb_id = kb.id
        """))
        chunks = res.fetchall()

    if not chunks:
        print("No chunks found.")
        return

    stats_by_kb = collections.defaultdict(list)
    for kb_name, txt in chunks:
        stats_by_kb[str(kb_name)].append(txt)

    for kb, texts in stats_by_kb.items():
        print(f"\nKB: {kb}")
        print(f"Chunk count: {len(texts)}")
        
        token_counts = []
        duplicates = 0
        seen = set()
        for t in texts:
            if t in seen:
                duplicates += 1
            seen.add(t)
            tokens = tokenizer.encode(t).ids
            token_counts.append(len(tokens))
        
        token_counts.sort()
        count = len(token_counts)
        print(f"Token min: {token_counts[0]}")
        print(f"Token median: {statistics.median(token_counts)}")
        print(f"Token p95: {token_counts[int(count * 0.95)]}")
        print(f"Token max: {token_counts[-1]}")
        
        over_limit = sum(1 for x in token_counts if x > 512)
        under_80 = sum(1 for x in token_counts if x < 80)
        
        print(f"% over 512 limit: {(over_limit/count)*100:.2f}%")
        print(f"% under 80 tokens: {(under_80/count)*100:.2f}%")
        print(f"Duplicate rate: {(duplicates/count)*100:.2f}%")

if __name__ == "__main__":
    asyncio.run(analyze())
