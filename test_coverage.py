import re
from app.modules.rag.file_router.adapters import parse_gdocz_markdown
from app.modules.rag.file_router.adaptive_chunking import AdaptiveChunker

def mock_breadcrumb(sec):
    title = sec.get('title', '')
    if title: return f'Section: {title}'
    return 'Source Document'

def norm(text: str) -> str:
    # Remove markdown headings, tables, etc., and just compare words.
    words = re.findall(r'\b\w+\b', text.lower())
    return " ".join(words)

def test_coverage():
    chunker = AdaptiveChunker()
    with open("md_false.md", "r", encoding="utf-8") as f:
        md_text = f.read()
        
    sections = parse_gdocz_markdown(md_text)
    results = chunker.chunk_document(sections, mock_breadcrumb)
    
    parents = [r for r in results if r.is_parent]
    children = [r for r in results if not r.is_parent]
    
    print(f"Parents: {len(parents)}")
    print(f"Children: {len(children)}")
    
    # Assert exact breadcrumb string is NOT in child or parent text
    for r in results:
        exact_breadcrumb = mock_breadcrumb(r.metadata) if 'metadata' in r.__dict__ else None
        if exact_breadcrumb and exact_breadcrumb != 'Source Document':
            # We don't have the section object here, but we can verify it doesn't have "Section: "
            assert "Section: " not in r.text, f"Found 'Section: ' in text: {r.text[:50]}"
            
    # Coverage: Concatenate parent text
    concat_parents = " ".join([p.text for p in parents])
    
    norm_source = norm(md_text)
    norm_parents = norm(concat_parents)
    
    # We should have all the words. Let's compare sets of words or sequences.
    # Because of markdown parsing, some formatting is lost.
    source_words = norm_source.split()
    parent_words = norm_parents.split()
    
    missing_words = [w for w in source_words if w not in parent_words]
    
    print(f"Source words: {len(source_words)}")
    print(f"Parent words: {len(parent_words)}")
    
    if len(missing_words) < 50:
        print("Coverage is extremely high. Missing words:")
        print(missing_words[:20])
    else:
        print(f"Missing {len(missing_words)} words! Loss detected.")
        print(missing_words[:20])
        
if __name__ == "__main__":
    test_coverage()
