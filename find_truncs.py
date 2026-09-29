import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.config import get_settings
from app.modules.rag.file_router.adaptive_chunking import AdaptiveChunker

settings = get_settings()

def mock_breadcrumb(sec):
    title = sec.get('title', '')
    if title: return f'Section: {title}'
    return 'Source Document'

async def find_truncated():
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    chunker = AdaptiveChunker()
    
    async with async_session() as db:
        res = await db.execute(text('SELECT id, name FROM knowledge_bases'))
        kbs = res.fetchall()
        
        for kb in kbs:
            kb_id, kb_name = kb[0], kb[1]
            if 'apple' not in kb_name.lower() and 'henry' not in kb_name.lower():
                continue
            
            # document_chunks doesnt have 'kind' column natively. Let's just assume text
            res_chunks = await db.execute(text(f"SELECT text, section FROM document_chunks WHERE kb_id = '{kb_id}' ORDER BY chunk_index ASC"))
            rows = res_chunks.fetchall()
            if not rows: continue
            
            sections = []
            for r in rows:
                sections.append({'text': r[0], 'kind': 'text', 'title': r[1] or 'Unknown'})
            
            # Monkey-patch _trim
            orig_trim = chunker._trim
            def logging_trim(text_val, max_t):
                count = chunker.profile.count(text_val)
                if count > max_t:
                    print(f"TRUNCATED in {kb_name}: Kind: text | Text[:100]: {text_val[:100].replace(chr(10), ' ')} | Tokens: {count}")
                return orig_trim(text_val, max_t)
            chunker._trim = logging_trim
            
            chunker.chunk_document(sections, mock_breadcrumb)

if __name__ == '__main__':
    asyncio.run(find_truncated())
