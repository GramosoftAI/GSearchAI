# RAG Pipeline Architecture & Knowledge Base

*Last Updated: 2026-08-29*
*Purpose: A standing reference document of the RAG pipeline's structural flow, routing logic, fallbacks, and known quirks to accelerate future debugging sessions.*

## 1. Request Flow (end-to-end)
The end-to-end execution path for a user query:

1. **WebSocket Ingress (`websocket_routes.py` / `service.py`)**: Receives the query and initializes `stream_rag_answer`.
2. **Concurrent Initialization (`pipeline.py::RAGPipeline.query`)**:
   - `_fetch_metadata()`: Queries Postgres (`KnowledgeBase` model) to load `name`, `total_chunks`, `summary_embedding`, and `description` (used for `excel_parquet` detection) into `self._kb_metadata`.
   - `analyze_query()` (`query_analyzer.py`): Calls LLM to determine `QueryIntent`, `is_tabular`, `keywords`, and structured variations.
   - `embedding_task`: Computes the vector embedding of the original query.
3. **Semantic File Gate (`pipeline.py`)**: Uses the query embedding against KB `summary_embedding`s to filter out definitively irrelevant documents.
4. **Routing Decision (`service.py`)**: Computes `schema_overlap` (via `schema_utils.py`) to decide if a Tabular Override is necessary.
5. **Tabular Intercept / Cascade (`pipeline.py`)**: If `is_tabular` is true, intercepts the query before vector search and routes it to `_execute_table_analytics`.
6. **Vector/Graph Fallback (`pipeline.py`)**: If tabular fails (or isn't triggered), executes standard semantic RRF search (Vector, Keyword, Graph traversal).
7. **Reranking (`section_ranker.py`)**: Reranks the retrieved chunks.
8. **LLM Generation (`service.py`)**: Injects the final context into the prompt and streams the response back to the user via WebSocket.

*Latency Notes:* Total latency can spike to 45-50s due to sequential bottlenecks: QueryAnalyzer timeout takes ~10.5s before falling back to heuristics, and the SQL Cascade executes DuckDB queries sequentially.

## 2. Routing Decision Logic
The pipeline must decide whether to query a file semantically (Vector/Graph) or via SQL (Tabular).

* **Schema Scoring (`schema_utils.py`)**: Computes two scores per candidate KB:
  * `cat_score`: Categorical overlap (checks query terms against `categorical_values` extracted during ingestion).
  * `gen_score`: General schema overlap.
* **The High-Cardinality Blind Spot**: `parquet_ingester.py` intentionally excludes columns with >50 unique values from the `categorical_values` registry. Consequently, queries for specific part numbers (e.g., `26080231`) will **always** yield `cat_score = 0`.
* **True ID Tiebreaker (`service.py`)**: Because of the blind spot, the system relies on a regex pattern (`ID_REGEX_PATTERN = r'(?=.*\d)[a-zA-Z0-9-]{5,}'`) to detect part numbers. If triggered, it reads a localized `_idindex.json` to prove exact membership. This overrides the arbitrary tiebreaker logic and forcibly pins the correct `target_kb_id`.

## 3. SQL Cascade Behavior (current, post-fix)
When the pipeline enters the `TABLE_ANALYTICS` block in `pipeline.py`, it executes a fallback cascade to prevent missing data in tied spreadsheet candidates:

1. **Candidate Discovery**: Queries `self._kb_metadata` to find KBs where `description == "excel_parquet"`.
2. **Prioritization**: Places the `target_kb_id` (pinned by the router) first, then appends up to 2 other tabular KBs.
3. **Sequential Execution**: Calls `_execute_table_analytics` on each candidate.
4. **Early Exit**: If any KB returns a valid SQL result, the cascade halts and returns the data to the LLM.
5. **Fallback on Exhaustion/Crash**: If *all* KBs return 0 rows (`"not present in dataset"`), or if a hard SQL/Python exception occurs, the cascade gracefully terminates, restores the full `original_kb_ids` list, and falls through to the RRF Vector Search.

## 4. Known Data Quirks Per KB
* **GATES-NEW PRICELIST**: The `partno` column contains mixed data types (e.g., numeric `26080231` and alphanumeric `7803-9636473A`). DuckDB occasionally infers `INT32` for the column and throws a Conversion Error when casting from source string `partno`. The `pandas_engine.py` layer successfully catches this and self-heals by rewriting the query.
* **Missing Ground Truth**: The specific part number `26080231` genuinely does not exist in any of the active tabular datasets (Ceekay, MAS, GATES).

## 5. Fallback Chain Map
* **Query Intent → Tabular Mode**: Controlled by QueryAnalyzer and Schema Overlap.
* **Tabular Execution → Match**: Returns `TABLE_ANALYTICS` context.
* **Tabular Execution → 0 Rows / "Not Present"**: Continues SQL Cascade to next tabular KB.
* **Tabular Execution → SQL Crash / Exception**: Continues SQL Cascade to next tabular KB.
* **Cascade Exhausted**: Drops out of Tabular mode, restores all KBs (including PDFs), and falls back to RRF Semantic Search.
* **RRF Semantic Search → 0 Chunks**: Returns insufficient knowledge context to LLM.
* **No Files Relevant (Semantic File Gate)**: Immediately returns `INSUFFICIENT_KNOWLEDGE`.

## 6. Known Fixed Bugs (Changelog)
* **`re` Shadowing (`schema_utils.py`)**: An inline `import re` inside a function body shadowed the module-level import, raising `UnboundLocalError` and silently failing the fast schema check.
* **`os` Shadowing (`service.py`)**: An inline `import os` on line 696 shadowed the global import, breaking the ID Index Loader and silently defeating the True ID Tiebreaker.
* **`kb_repo` AttributeError (`pipeline.py`)**: An attempt to call `self.kb_repo` in the cascade loop crashed the pipeline. Fixed by iterating over the pre-fetched `self._kb_metadata`.
* **Metadata `source_type` Error (`pipeline.py`)**: The metadata fetch query failed because `source_type` doesn't exist on the `KnowledgeBase` model. Fixed by querying `description` instead, which is where the `"excel_parquet"` flag is stored.
* **Tabular Crash Dead-End (`pipeline.py`)**: A generic exception handler for `TABLE_ANALYTICS` returned `TABLE_ANALYTICS_FAILED`, acting as a hard stop and bypassing semantic fallback. Fixed to fall through to RRF vector search on crash.
* **Prompt Leakage (`pipeline.py`)**: The tabular exception handler was injecting raw Python traceback strings (`str(e)`) directly into the LLM context. Fixed with generic user-safe error messages.

## 7. Architectural Limitations & Open Items (Backlog)
* **Exact Match Gap in Semantic Fallback**: The system has no exact-match capability for specific IDs/part numbers inside PDFs or unstructured text. If an ID query falls through to the RRF vector search (e.g. searching for `26080231` in `sundram.pdf`), the vector embeddings cannot distinguish it from structurally similar strings (like `26080286`). As a result, exact ID lookups on non-tabular KBs often return highly ranked but incorrect rows. (Potential fix: Add a literal `LIKE '%X%'` keyword layer to the fallback).
* **No File-Specific Scoping**: The pipeline currently lacks the ability to restrict a search to a single specific file. The vector fallback merges results across *all* KBs based purely on cosine similarity.
* **LLM Timeout Latency**: `QueryAnalyzer` times out after ~10s on `asyncio.TimeoutError` before falling back to heuristics, adding heavy latency to the critical path.
* **Sequential Tabular Cascade**: The SQL cascade executes DuckDB queries sequentially rather than concurrently.
* **Sequential Graph Traversal**: Neo4j graph traversal (`_execute_graph_traversal`) runs queries in a synchronous loop.
* **Inline Import Audit**: There are still 12 remaining inline imports (e.g. `import time`, `import pyarrow`, `import json`) across `service.py`, `pipeline.py`, and `pandas_engine.py` that have not been vetted for scoping hazards or circular import requirements.
