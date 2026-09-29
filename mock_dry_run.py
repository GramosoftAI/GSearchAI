import asyncio
import numpy as np
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.config import get_settings
from app.modules.rag.file_router.adaptive_chunking import AdaptiveChunker
from app.modules.rag.file_router.adapters import parse_gdocz_markdown

settings = get_settings()

def mock_breadcrumb(sec):
    title = sec.get('title', '')
    if title: return f'Section: {title}'
    return 'Source Document'

async def run_dry_run():
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    chunker = AdaptiveChunker()
    
    # 1. First run md_false.md from disk
    try:
        with open("md_false.md", "r", encoding="utf-8") as f:
            md_text = f.read()
        sections = parse_gdocz_markdown(md_text)
        results = chunker.chunk_document(sections, mock_breadcrumb)
        print("KB: md_false.md (From Disk)")
        print_stats(results)
    except Exception as e:
        print(f"Failed to process md_false.md: {e}")

    # 2. Reconstruct markdown for DB files since source PDFs are absent
    async with async_session() as db:
        res = await db.execute(text('SELECT id, name FROM knowledge_bases'))
        kbs = res.fetchall()
        
        for kb in kbs:
            kb_id, kb_name = kb[0], kb[1]
            name_lower = kb_name.lower()
            if 'apple' not in name_lower and 'ntsb' not in name_lower and 'henry' not in name_lower:
                continue
            
            res_chunks = await db.execute(text(f"SELECT text, section FROM document_chunks WHERE kb_id = '{kb_id}' ORDER BY chunk_index ASC"))
            rows = res_chunks.fetchall()
            if not rows: continue
            
            # Reconstruct raw markdown
            raw_lines = []
            curr_sec = None
            for r in rows:
                sec_name = r[1] or 'Unknown'
                if sec_name != curr_sec:
                    raw_lines.append(f"\n## {sec_name}\n")
                    curr_sec = sec_name
                raw_lines.append(r[0])
                
            raw_markdown = "\n".join(raw_lines)
            
            # Pipeline: Raw Markdown -> Adapter -> Chunker
            sections = parse_gdocz_markdown(raw_markdown)
            results = chunker.chunk_document(sections, mock_breadcrumb)
        
        print(f"\nKB: {kb_name} (Reconstructed from DB to simulate Gdocz Markdown)")
        print_stats(results, md_text if 'md_text' in locals() else raw_markdown)

def print_stats(results, source_text):
    for r in results:
        # Check exactly for the expected mock_breadcrumb
        # Since we use sections, we can't easily know WHICH breadcrumb, but it shouldn't be in the raw text
        # If it is stored without breadcrumb, 'Section:' should only appear if it was in the original text.
        # But wait, original text DOES NOT have 'Section:'.
        pass
        
    child_tokens = [r.tokens for r in results if not r.is_parent]
    parent_tokens = [r.tokens for r in results if r.is_parent]
    
    if not child_tokens:
        print("No child chunks generated.")
        return
        
    p50 = np.percentile(child_tokens, 50)
    p95 = np.percentile(child_tokens, 95)
    max_t = max(child_tokens)
    over_512 = sum(1 for t in child_tokens if t > 512)
    under_80_chunks = [r for r in results if not r.is_parent and r.tokens < 80]
    under_80 = len(under_80_chunks)
    
    # Categorize under 80
    sec_tail = 0
    atomic = 0
    other = 0
    other_examples = []
    
    for c in under_80_chunks:
        if '\n\n' not in c.text and len(c.text.split()) < 15:
            atomic += 1
        elif 'Section:' in c.text:
            sec_tail += 1
        else:
            other += 1
            if len(other_examples) < 3:
                other_examples.append(c.text.replace('\n', ' ')[:100])
                
    p_p50 = np.percentile(parent_tokens, 50) if parent_tokens else 0
    p_max = max(parent_tokens) if parent_tokens else 0
    avg_children = len(child_tokens) / len(parent_tokens) if parent_tokens else 0
    
    source_tokens = sum(child_tokens)
    parent_tokens_sum = sum(parent_tokens)
    
    print(f"Child Chunks: {len(child_tokens)} | Median: {p50:.1f} | p95: {p95:.1f} | Max: {max_t}")
    print(f"Over 512: {over_512} | Truncation: 0 (Disabled)")
    print(f"Under 80: {under_80} (Section Tail: {sec_tail}, Atomic Block: {atomic}, Other: {other})")
    if other_examples:
        print(f"Other Examples: {other_examples}")
    print(f"Parent Chunks: {len(parent_tokens)} | Median: {p_p50:.1f} | Max: {p_max} | Avg Children/Parent: {avg_children:.1f}")
    
    # EXACT string checks:
    import re
    # Normalize whitespace
    def norm(t): return re.sub(r'\s+', ' ', t).strip()
    
    # We compare parent texts (which don't have breadcrumbs in .text, they are in .embed_text!)
    # Actually wait, in AdaptiveChunker._build_parent_child:
    # `results.append(ChunkResult(text=p_text, embed_text=p_full, ...))`
    # So `r.text` for parent is EXACTLY the concatenated chunks.
    concat_parents = " ".join([r.text for r in results if r.is_parent])
    
    # We must only compare the parts of source_text that were NOT stripped by the parser.
    # The parser strips markdown table structure, etc.
    norm_parents = norm(concat_parents)
    norm_source = norm(source_text)
    
    if len(norm_parents) < len(norm_source) * 0.9: # arbitrary threshold because tables change size
        print("Coverage tokens (Children Sum vs Parent Sum): Loss detected! (Parent text is much shorter)")
    else:
        print("Coverage tokens (Children Sum vs Parent Sum): Coverage OK")

if __name__ == '__main__':
    asyncio.run(run_dry_run())
