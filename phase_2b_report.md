# Phase 2b Report: Adaptive Chunking Refinements

## 1. Truncation Fix
**Analysis:** Truncation occurred 4 times on Apple 10-K (none on O. Henry before crash in monkey patch). The chunks were massive sections without sentence boundaries (e.g., `Section: Events of Default Each of the following events are defined in...`, `Section: Term Debt Document Total Number Of Shares...`).

**Fix:** Rewrote `_chunk_text`, `_chunk_table`, and `_chunk_list` to use a new `_split_to_budget` hierarchical method. It recursively attempts to split by `["SENTENCE", "LINE", "WORD"]` for text, `["WORD"]` for table rows, and `["LINE", "WORD"]` for lists before ever resorting to truncation. Truncation is now strictly a fallback for unbreakable monolithic strings (like a 600-token base64 string). 
**Result:** **0** truncations fired in the new dry run.

## 2. Tests (10/10 Passed)
The test suite in `tests/test_adaptive_chunking.py` was heavily expanded and now covers:
- `test_sentence_splitting_abbreviations` (Dr., e.g., 9.00)
- `test_non_adjacent_duplicate_removal`
- `test_giant_paragraph`
- `test_empty_input` (fixed to not emit empty chunks)
- `test_unknown_kind`
- `test_idempotent_ids`
- `test_tables` (header repeated)
- `test_lists` (lead-in kept)
- `test_tiny_merge_forward` (merges forward, but not into tables)
- `test_coverage` (original text fully present in parents)

**Pytest Output:**
```text
============================= test session starts =============================
platform win32 -- Python 3.12.0, pytest-7.4.3, pluggy-1.6.0
rootdir: C:\Users\hp\Desktop\GSOFT\RAG\GSearchAI
configfile: pytest.ini
plugins: anyio-4.13.0, Faker-21.0.0, langsmith-0.10.11, logfire-4.32.1, asyncio-0.21.1, cov-4.1.0
asyncio: mode=Mode.AUTO
collected 10 items

tests\test_adaptive_chunking.py ..........                               [100%]

======================== 10 passed, 1 warning in 8.75s ========================
```

## 3. Dry Run Numbers (with `child_target=350`)
I bumped the `child_target` from 300 to 350 to align with your 250-350 median requirement. 

**Apple 10-K Corpus:**
- **Child Chunks**: 372
- **Median Tokens**: 307.5 
- **p95 Tokens**: 356.0
- **Max Tokens**: 398
- **Over 512 Tokens**: **0** (Without truncation)
- **Under 80 Tokens**: **11** 
- **Parent Chunks**: 198 (Median: 333.0, Max: 1193)
- **Coverage**: OK (100% of chunks processed). 

**O. Henry Corpus:**
- **Child Chunks**: 264
- **Median Tokens**: 320.0 
- **p95 Tokens**: 353.0
- **Max Tokens**: 357
- **Over 512 Tokens**: **0** (Without truncation)
- **Under 80 Tokens**: **27** 
- **Parent Chunks**: 109 (Median: 701.0, Max: 833)
- **Coverage**: OK (100% of chunks processed). 

*Note: The NTSB proxy and Scraped Site KBs were skipped as they were not populated in the DB during this run. The metrics on Apple and O. Henry represent the exact edge cases (tiny tables vs monolithic text).*

## 4. Type Support & Adapters
I created `app/modules/rag/file_router/adapters.py` containing:
- **`parse_gdocz_markdown`**: Parses raw markdown into `text`, `table`, and `list` blocks based on markdown headers and content heuristics (`|` ratio for tables, `-/*` ratio for lists).
- **`parse_pdf_structure`**: Adapts dictionaries matching the `PDFStructureParser` output. 
- **`_apply_table_prose_fixture`**: Explicitly fixes the "table-then-prose" bug by scanning 'table' blocks for trailing lines missing `|` and ejecting them into follow-up `text` blocks. No LLM used. 
- **Status of other parsers**: Slides, chat, web, form/invoice, and code adapters **are not built yet**. They will follow after wiring.

## 5. Production Change (`app/modules/rag/service.py`)
I ran `git diff`, reviewed the change, and committed it separately as requested.
```diff
--- a/app/modules/rag/service.py
+++ b/app/modules/rag/service.py
@@ -2343,6 +2343,8 @@ RESPONSE FORMAT
 
         if episodic_guidance:
             logger.debug("Episodic guidance retrieved; will inject into RAG context.")
+            
+        analysis = None
 
         # Step 2: Cache check
         cache_key = self._make_cache_key(
```
*(Commit: `a8c8889`)*

## 6. Baseline & Next Steps
- The 30 golden questions have been explicitly noted as DRAFT. 
- The filename-match rule has been preserved. 
- Snippets will be retained downstream. 
- No database migrations (`alembic upgrade`) have been run anywhere. 

Phase 2b complete. Please advise on whether to proceed with Phase 3 wiring.
