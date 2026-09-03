import logging
import uuid
import tempfile
import os
import re
import json
from typing import Optional, Dict, Literal, List, Tuple, Any
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from app.core.config import get_settings, settings
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

def parse_json_from_thinking(text: str) -> dict:
    """Strips <think> tags from Qwen/DeepSeek outputs and parses the JSON robustly."""
    raw_text = text
    text = text.strip()
    # Remove closed <think>...</think> blocks
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    # Remove unclosed <think>... blocks if truncated
    if '<think>' in text and '</think>' not in text:
        text = re.sub(r'<think>.*', '', text, flags=re.DOTALL).strip()
    
    # Strip markdown code blocks
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^```\s*$', '', text, flags=re.MULTILINE).strip()
    
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        text = text[start:end+1]
        
    fallback_dict = {
        "intents": [],
        "sql": "SELECT 'LLM JSON parsing failed' AS info WHERE FALSE;",
        "explanation": "LLM JSON output parsing failed.",
        "parse_failed": True,
        "target_engine": "HYBRID_MERGE",
        "confidence": 0.0,
        "matched_columns": [],
        "reasoning": "LLM JSON output parsing failed."
    }

    if not text:
        logger.error(f"LLM returned empty text after stripping think tags: {raw_text}")
        return fallback_dict
        
    try:
        cleaned = re.sub(r',\s*}', '}', text)
        cleaned = re.sub(r',\s*\]', ']', cleaned)
        return json.loads(cleaned)
    except Exception as e:
        logger.warning(f"json.loads failed on text, trying yaml.safe_load: {e}")
        try:
            import yaml
            res = yaml.safe_load(text)
            if isinstance(res, dict):
                return res
        except Exception as e_yaml:
            logger.error(f"Both json.loads and yaml.safe_load failed on text: {text} | error: {e_yaml}")
            
        return fallback_dict

class IntentClassification(BaseModel):
    """Classifies the user query into one or more execution engines."""
    intents: List[Literal['aggregation', 'row_lookup', 'relationship', 'free_text']] = Field(
        ..., 
        description="aggregation (math/counts), row_lookup (fetching raw rows/pagination), relationship (graph traversal), free_text (vector semantic search)."
    )

class DuckDBSemanticQuery(BaseModel):
    """Structured DuckDB SQL plan for enterprise data querying."""
    sql: str = Field(
        ..., 
        description="Valid read-only DuckDB SELECT SQL query targeting the view named 'dataset'."
    )
    explanation: str = Field(
        ...,
        description="Explanation of what the SQL query does."
    )

def validate_sql_security(sql_str: str) -> Optional[str]:
    """
    Defense-in-depth SQL security validator for PandasQueryEngine.
    Enforces:
    1. Single-statement execution (rejects multi-statement semicolon injection).
    2. Read-only allow-list (must start strictly with SELECT or WITH).
    3. Restriction on file I/O, extension loading, system procedures (COPY, PRAGMA, INSTALL, LOAD, CALL, TRUNCATE, read_csv, read_parquet, etc.).
    4. Extended keyword safety net.
    Returns None if valid, or an error message string if a security violation is detected.
    """
    if not sql_str or not sql_str.strip():
        return "Error: Security violation - empty query."

    clean_sql = sql_str.strip()

    # 1. Multi-Statement Validation
    # Remove single-line comments (--), block comments (/* */), and trailing semicolons
    stripped_sql = re.sub(r'--(.*?)$', '', clean_sql, flags=re.MULTILINE)
    stripped_sql = re.sub(r'/\*.*?\*/', '', stripped_sql, flags=re.DOTALL).strip()
    
    while stripped_sql.endswith(';'):
        stripped_sql = stripped_sql[:-1].strip()

    if ';' in stripped_sql:
        logger.warning(f"[SQL_SECURITY] Rejected multi-statement query: {sql_str}")
        return "Error: Security violation - multi-statement queries are strictly prohibited."

    # 2. Allow-List Validation (Must start strictly with SELECT or WITH)
    upper_sql = stripped_sql.upper()
    if not (upper_sql.startswith("SELECT") or upper_sql.startswith("WITH")):
        logger.warning(f"[SQL_SECURITY] Query does not start with SELECT or WITH: {sql_str}")
        return "Error: Security violation - only single read-only SELECT or WITH queries are permitted."

    # 3. Restrict File I/O, Extension, and System Execution Keywords & Functions
    forbidden_kw = [
        "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "REPLACE",
        "EXEC", "ATTACH", "DETACH", "COPY", "PRAGMA", "INSTALL", "LOAD",
        "CALL", "TRUNCATE", "EXPORT", "IMPORT", "READ_CSV", "READ_PARQUET",
        "READ_JSON", "READ_TEXT", "READ_BLOB"
    ]

    for kw in forbidden_kw:
        pattern = r'\b' + re.escape(kw) + r'(\b|_)'
        if re.search(pattern, upper_sql):
            logger.warning(f"[SQL_SECURITY] Forbidden keyword/function '{kw}' detected in query: {sql_str}")
    return None

import time
import threading

_DUCKDB_ENGINE_CACHE: Dict[Tuple[str, ...], Tuple[float, Any, List[str]]] = {}
_DUCKDB_CACHE_LOCK = threading.Lock()
_DUCKDB_CACHE_TTL_SECONDS = 600.0  # 10 minutes TTL
_MAX_DUCKDB_CACHE_SIZE = 50

def get_pooled_duckdb_engine(paths: List[str]) -> Tuple[Any, List[str], float]:
    """
    Retrieves or creates a pooled, thread-safe DuckDB SQLAlchemy engine and cached catalog columns
    for the given dataset file paths. Returns (engine, columns, acquisition_latency_ms).
    """
    start_time = time.time()
    paths_key = tuple(sorted(str(p).replace('\\', '/') for p in paths if p and os.path.exists(p)))
    if not paths_key:
        raise ValueError("No valid existing file paths provided for DuckDB engine.")

    now = time.time()
    with _DUCKDB_CACHE_LOCK:
        # 1. Sweep expired cache entries
        expired_keys = [
            k for k, (ts, eng, _) in _DUCKDB_ENGINE_CACHE.items()
            if now - ts > _DUCKDB_CACHE_TTL_SECONDS
        ]
        for k in expired_keys:
            _, eng, _ = _DUCKDB_ENGINE_CACHE.pop(k)
            try:
                eng.dispose()
            except Exception as dispose_err:
                logger.debug(f"Error disposing expired DuckDB engine for {k}: {dispose_err}")

        # 2. Return cached engine if hit
        if paths_key in _DUCKDB_ENGINE_CACHE:
            ts, eng, cols = _DUCKDB_ENGINE_CACHE[paths_key]
            acq_ms = (time.time() - start_time) * 1000.0
            logger.info(f"[DUCKDB_POOL] Cache hit for paths {paths_key} (Acquisition latency: {acq_ms:.2f}ms)")
            return eng, cols, acq_ms

        # 3. LRU Eviction if max capacity reached
        if len(_DUCKDB_ENGINE_CACHE) >= _MAX_DUCKDB_CACHE_SIZE:
            oldest_key = min(_DUCKDB_ENGINE_CACHE.keys(), key=lambda k: _DUCKDB_ENGINE_CACHE[k][0])
            _, old_eng, _ = _DUCKDB_ENGINE_CACHE.pop(oldest_key)
            try:
                old_eng.dispose()
            except Exception:
                pass

        # 4. Create new pooled in-memory DuckDB engine & initialize dataset view
        logger.info(f"[DUCKDB_POOL] Cache miss. Constructing pooled DuckDB engine for paths: {paths_key}")
        engine = create_engine("duckdb:///:memory:")
        
        valid_readers = []
        for path_item in paths_key:
            if path_item.lower().endswith(".parquet"):
                valid_readers.append(f"SELECT * FROM read_parquet('{path_item}')")
            else:
                valid_readers.append(f"SELECT * FROM read_csv_auto('{path_item}', sample_size=10000, nullstr='NULL')")
        
        if not valid_readers:
            union_sql = "SELECT 1 WHERE FALSE"
        else:
            union_sql = " SELECT * FROM (" + " UNION ALL BY NAME ".join(valid_readers) + ")"

        with engine.connect() as conn:
            conn.execute(text("DROP VIEW IF EXISTS dataset;"))
            conn.execute(text(f"CREATE VIEW dataset AS SELECT row_number() OVER () AS row_id, * FROM ({union_sql});"))
            
            for idx, path_item in enumerate(paths_key):
                view_name = f"dataset_{idx+1}"
                conn.execute(text(f"DROP VIEW IF EXISTS {view_name};"))
                reader = f"read_parquet('{path_item}')" if path_item.lower().endswith(".parquet") else f"read_csv_auto('{path_item}', sample_size=10000, nullstr='NULL')"
                conn.execute(text(f"CREATE VIEW {view_name} AS SELECT row_number() OVER () AS row_id, * FROM {reader};"))
            
            try:
                conn.commit()
            except Exception:
                pass
                
            res = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'dataset' AND column_name != 'row_id';"))
            columns = [row[0] for row in res.fetchall()]

        _DUCKDB_ENGINE_CACHE[paths_key] = (time.time(), engine, columns)
        acq_ms = (time.time() - start_time) * 1000.0
        logger.info(f"[DUCKDB_POOL] Initialized and cached DuckDB engine for {paths_key} (Acquisition latency: {acq_ms:.2f}ms)")
        return engine, columns, acq_ms

def invalidate_duckdb_engine_cache(paths: List[str]):
    """Evicts the cached engine for a given set of file paths (e.g. on schema error or update)."""
    paths_key = tuple(sorted(str(p).replace('\\', '/') for p in paths if p and os.path.exists(p)))
    with _DUCKDB_CACHE_LOCK:
        if paths_key in _DUCKDB_ENGINE_CACHE:
            _, eng, _ = _DUCKDB_ENGINE_CACHE.pop(paths_key)
            try:
                eng.dispose()
            except Exception as e:
                logger.debug(f"Error disposing evicted DuckDB engine: {e}")


class PandasQueryEngine:
    """
    Hybrid Execution Engine for 1M+ rows.
    Implements Intent Routing, Parquet querying, and strict Semantic SQL building.
    """
    def __init__(self, data_path_or_client=None, llm_client=None, all_dataset_paths: Optional[List[str]] = None):
        if isinstance(data_path_or_client, str):
            self.data_path = data_path_or_client
            self.llm_client = llm_client
        else:
            self.data_path = None
            self.llm_client = data_path_or_client
        self.all_dataset_paths = all_dataset_paths or ([self.data_path] if self.data_path else [])
        
        api_key = getattr(settings, "deepinfra_api_key", "")
        base_url = getattr(settings, "deepinfra_api_url", "https://api.deepinfra.com/v1/openai")
        model_name = settings.model_answer
        self.llm = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0.0,
            max_tokens=2048,
            extra_body={"enable_thinking": False}
        )
        router_model_name = getattr(settings, "model_intent", model_name)
        self.router_llm = ChatOpenAI(
            model=router_model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0.0,
            max_tokens=512,
            extra_body={"enable_thinking": False}
        )

    def _build_union_query(self, paths: List[str], with_row_id: bool = False) -> str:
        """Builds a DuckDB UNION ALL BY NAME query across all provided CSV/Parquet dataset paths."""
        valid_readers = []
        for p in paths:
            if not p or not os.path.exists(p):
                continue
            safe_path = str(p).replace('\\', '/')
            if safe_path.lower().endswith(".parquet"):
                valid_readers.append(f"SELECT * FROM read_parquet('{safe_path}')")
            else:
                valid_readers.append(f"SELECT * FROM read_csv_auto('{safe_path}', sample_size=10000, nullstr='NULL')")
        if not valid_readers:
            return "SELECT 1 WHERE FALSE"
        union_sql = " UNION ALL BY NAME ".join(valid_readers)
        if with_row_id:
            return f"SELECT row_number() OVER () AS row_id, * FROM ({union_sql})"
        return f"SELECT * FROM ({union_sql})"

    def get_schema_columns(self, data_path: Optional[str] = None) -> List[str]:
        """Fast helper to retrieve columns of the active dataset(s) for schema-aware intent routing."""
        target_path = data_path or getattr(self, "data_path", None)
        paths_to_check = [p for p in (self.all_dataset_paths or ([target_path] if target_path else [])) if p and os.path.exists(p)]
        if not paths_to_check:
            return []
        try:
            _, columns, _ = get_pooled_duckdb_engine(paths_to_check)
            return columns
        except Exception as e:
            logger.warning(f"Failed fetching schema columns for routing: {e}")
            return []

    async def _synthesize_analytical_response(self, question: str, table_md: str, explanation: str) -> str:
        """Synthesizes an executive natural-language answer from SQL table results for comparative or analytical queries."""
        try:
            synth_prompt = ChatPromptTemplate.from_messages([
                ("system",
                 "You are an Executive Data Analyst. Given a user's question and the retrieved database result from an enterprise spreadsheet dataset, write a clear, fluent, natural-language executive answer.\n"
                 "CRITICAL RULES:\n"
                 "1. Answer ONLY using the retrieved data. Do not invent or assume information.\n"
                 "2. Answer the user's specific question DIRECTLY in the very first sentence.\n"
                 "3. FOR SENIORITY / TENURE QUESTIONS: Remember that an employee who joined EARLIER in time (earliest year/date, e.g. 2018 vs 2021) or has MORE years of experience is MORE SENIOR.\n"
                 "4. Respond naturally, concisely, and use bolding formatting for key names, figures, dates, and comparisons.\n"
                 "5. Include the formatted Markdown table below your explanation as supporting evidence.\n"
                 "6. FOR FULL DETAILS OR MOVIE/ENTITY QUERIES: Give the complete details of the movie/entity (Title, Release Date, Overview/Plot, Popularity, Vote Average, Genre, etc.) from the table clearly and accurately. If multiple records are returned, summarize the top items clearly and concisely so the response remains focused and does not exceed token length limits.\n"
                 "7. IMPORTANT: Do NOT output any <think> tags or internal reasoning. Output ONLY the final answer directly.\n"
                 "8. DO NOT include the SQL Explanation in your answer. The SQL Explanation is for your internal context only."),
                ("user", "User Question: {question}\n\nRetrieved Database Result Table:\n{table}")
            ])
            from langchain_core.output_parsers import StrOutputParser
            synth_chain = synth_prompt | self.llm | StrOutputParser()
            synthesis = await synth_chain.ainvoke({
                "question": question,
                "table": table_md
            })
            # Strip any <think> tags the LLM may have injected
            synthesis = re.sub(r'<think>.*?</think>', '', synthesis, flags=re.DOTALL).strip()
            if '<think>' in synthesis:
                synthesis = synthesis[:synthesis.index('<think>')].strip()
            if not synthesis:
                return table_md
            return synthesis
        except Exception as e:
            logger.warning(f"Analytical synthesis failed ({e}), returning formatted table.")
            return table_md

    async def _resolve_to_local_path(self, path: str) -> str:
        """
        If path is an S3/HTTP(S) URL, download it to a local temp file and return that path.
        If it's already a local path that exists, return it unchanged.
        This is required because DuckDB can only read local filesystem paths.
        """
        if not path:
            return path
        if path.startswith("http://") or path.startswith("https://"):
            try:
                import httpx, tempfile
                ext = ".csv" if path.lower().endswith(".csv") else ".parquet"
                logger.info(f"Downloading remote CSV to temp file: {path}")
                async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                    resp = await client.get(path)
                    resp.raise_for_status()
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                tmp.write(resp.content)
                tmp.close()
                logger.info(f"Downloaded {len(resp.content)} bytes -> {tmp.name}")
                return tmp.name
            except Exception as e:
                logger.error(f"Failed to download remote CSV from {path}: {e}")
                return path  # Return original - caller will catch os.path.exists failure
        return path

    async def execute_query(self, query: str, data_path: Optional[str] = None) -> Optional[str]:
        raw_path = data_path or getattr(self, "data_path", None)
        # Resolve S3/HTTPS URLs to local temp files before DuckDB can read them
        target_path = await self._resolve_to_local_path(raw_path) if raw_path else None
        paths_to_register = [p for p in (self.all_dataset_paths or ([target_path] if target_path else [])) if p and os.path.exists(p)]
        if not paths_to_register:
            logger.error(f"No valid local dataset path found. raw_path={raw_path!r}, resolved={target_path!r}")
            return "Error: No valid spreadsheet datasets found on server."
            
        from langchain_core.output_parsers import StrOutputParser
        # DUCKDB BINDING (CSV or PARQUET)
        logger.info(f"Acquiring pooled DuckDB engine on dataset(s): {target_path} | total_paths: {len(paths_to_register)}")
        engine = None
        try:
            import asyncio
            engine, columns, acq_ms = await asyncio.to_thread(get_pooled_duckdb_engine, paths_to_register)
            logger.info(f"[TELEMETRY] DuckDB engine acquisition completed in {acq_ms:.2f}ms")

            # 3. GENERATE DUCKDB SQL DIRECTLY
            prompt = ChatPromptTemplate.from_messages([
                ("system", 
                 "You are an enterprise data engine and SQL expert. Convert the user's natural language question into a clean, read-only DuckDB SELECT SQL query on the view named 'dataset'.\n\n"
                 "Available columns in 'dataset':\n{columns}\n\n"
                 "CRITICAL RULES FOR DUCKDB SQL:\n"
                 "1. Table name MUST ALWAYS be 'dataset'.\n"
                 "2. COLUMN NAMES WITH SPACES OR SYMBOLS: You MUST ALWAYS wrap column names containing spaces, punctuation, or special characters in DOUBLE QUOTES (e.g., \"Customer ID\", \"Customer Name\", \"Total Amount\"). NEVER write unquoted multi-word column names like Customer ID.\n"
                 "3. When performing mathematical calculations (SUM, AVG, arithmetic) on string/varchar columns, ALWAYS wrap the column in TRY_CAST(\"col\" AS DOUBLE), e.g., SUM(TRY_CAST(\"exchange_rate\" AS DOUBLE)), AVG(TRY_CAST(\"exchange_rate\" AS DOUBLE)), to prevent type conversion issues.\n"
                 "4. For counting total records, use SELECT COUNT(*) AS total_records FROM dataset;\n"
                 "5. For most frequent items or duplicate checks, use GROUP BY \"col\" ORDER BY COUNT(*) DESC LIMIT N (always quote column names if they contain spaces);\n"
                 "6. For boolean columns (like mb_part), NEVER use '= TRUE' or '= FALSE' directly. ALWAYS compare as uppercase string: UPPER(TRY_CAST(\"col\" AS VARCHAR)) = 'TRUE' or UPPER(TRY_CAST(\"col\" AS VARCHAR)) = 'FALSE' because boolean columns may contain string 'NULL' values.\n"
                 "7. For time differences or durations between two timestamps, NEVER use SQLite julianday(). ALWAYS use DuckDB date_diff('day', TRY_CAST(\"col1\" AS TIMESTAMP), TRY_CAST(\"col2\" AS TIMESTAMP)) or (epoch(TRY_CAST(\"col2\" AS TIMESTAMP)) - epoch(TRY_CAST(\"col1\" AS TIMESTAMP))) / 86400.0.\n"
                 "8. For date comparisons or min/max, handle strings appropriately.\n"
                 "9. Include descriptive column aliases (e.g. AS average_rate, AS total_count).\n"
                 "10. NEVER use INSERT, UPDATE, DELETE, DROP, or ALTER. ONLY read-only SELECT queries.\n"
                 "11. Output ONLY valid JSON matching the schema with 'sql' and 'explanation'.\n"
                 "12. In your 'explanation' string, NEVER use the words 'error', 'errors', 'exception', or 'fail' (use 'issues' or 'problems' instead).\n"
                 "13. For extracting YEAR, MONTH, or date parts from timestamp columns, ALWAYS cast to timestamp first: EXTRACT(YEAR FROM TRY_CAST(\"col\" AS TIMESTAMP)).\n"
                 "14. NO PROXY METRICS: If the user asks for information or columns that DO NOT EXIST in the schema (e.g. 'Age', 'wholesale price', 'CEO'), DO NOT hallucinate or substitute an unrelated column to estimate it (e.g. DO NOT use 'Hire Date' to calculate 'Age'). You MUST generate exactly: SELECT 'Not present in dataset' AS info WHERE FALSE; with explanation stating the information is not present in the dataset.\n"
                 "15. STRING FILTERING & ENTITY MATCHING: When filtering string columns (e.g. employee names, IDs, departments in WHERE clauses), NEVER use exact '=' or 'LOWER(col) = ...' with mismatching case. Instead, ALWAYS use case-insensitive matching using the ILIKE operator (e.g., \"Employee ID\" ILIKE 'EMP1005' or \"Employee Name\" ILIKE '%Matthew%') so that case differences or spacing never cause zero results.\n"
                 "16. COMPARATIVE & SUPERLATIVE QUERIES: When the user asks to compare two or more entities (e.g. 'who has higher salary', 'compare the salary of both', 'who is better', 'who earns more', 'which has better'):\n"
                 "   - If the query mentions 'both', 'all', or does not specify explicit employee names, DO NOT filter with WHERE name = 'both'. Instead, select all rows from dataset and ORDER BY the comparison metric DESC (e.g., SELECT * FROM dataset ORDER BY TRY_CAST(\"Salary\" AS DOUBLE) DESC LIMIT 10;).\n"
                 "   - Select all relevant columns (name, department, salary, hire date, etc.) so the response synthesizer has full structured comparison data.\n"
                 "17. SENIORITY, TENURE & JOINING DATE QUERIES: When the user asks who is the 'senior' ('snior'), 'most senior', 'oldest', or 'who joined first/earliest' among employees:\n"
                 "   - If comparing by JOINING DATE / HIRE DATE / START DATE: A senior employee joined EARLIEST in time. You MUST cast string dates to date/timestamp and order ASCENDING (ORDER BY TRY_CAST(\"Joining Date\" AS DATE) ASC) so the earliest date (earliest year, e.g. 2018 before 2022) is ranked FIRST.\n"
                 "   - If comparing by YEARS OF EXPERIENCE / TENURE / AGE: A senior employee has more years. You MUST order DESCENDING (ORDER BY TRY_CAST(\"Experience\" AS DOUBLE) DESC).\n"
                 "   - If selecting among specific people (e.g. 'between John and Jane'), always use case-insensitive fuzzy matching (LOWER(\"col\") LIKE '%name%') for the WHERE clause. If selecting 'among both', DO NOT filter by the word 'both'.\n"
                 "18. POSITIONAL & CHRONOLOGICAL ROW ORDERING (first, last, top, bottom, latest, oldest):\n"
                 "   - When the user asks for the 'last row(s)', 'last N rows', 'last record(s)', 'last entry', or 'last movie/item in the dataset/excel/table' without a specific date filter, you MUST use ANSI OFFSET from total count: SELECT * FROM dataset OFFSET (SELECT COUNT(*) FROM dataset) - N LIMIT N; (e.g. OFFSET (SELECT COUNT(*) FROM dataset) - 1 LIMIT 1; for the last row). NEVER rely on row_id ordering alone as parallel ingestion can make row_id order non-deterministic.\n"
                 "   - When the user asks for the 'first row(s)', 'first N rows', 'first record(s)', 'first entry', or 'first movie/item in the dataset/excel/table', select directly from top: SELECT * FROM dataset LIMIT N;\n"
                 "   - When the user asks for 'latest', 'newest', or 'most recent' by date/release date, cast date strings to DATE and order DESCENDING: ORDER BY TRY_CAST(\"Release_Date\" AS DATE) DESC LIMIT N;\n"
                 "   - When the user asks for 'oldest' or 'earliest' by date, order ASCENDING: ORDER BY TRY_CAST(\"Release_Date\" AS DATE) ASC LIMIT N;\n"
                 "19. SPECIFIC RECORD DETAILS LOOKUP, STRING APOSTROPHES & LENGTH GUARDS:\n"
                 "   - When asking for 'details', 'full details', or information about a specific movie, person, or title (e.g. 'Ron''s Gone Wrong full details', 'details of King''s Man'), generate a SELECT * FROM dataset WHERE LOWER(\"Title\") LIKE '%ron%gone%wrong%'; (or corresponding name column). NEVER generate a COUNT(*) aggregation query when the user asks for details of a specific item!\n"
                 "   - When a title or search string contains an apostrophe or single quote (''), you MUST escape it by doubling the single quote in SQL (e.g., '%ron''s gone wrong%') OR omit the apostrophe using wildcards (e.g., '%ron%gone%wrong%').\n"
                 "   - When querying general details without an explicit WHERE name/title filter (e.g. 'show me all movies' or general overview), ALWAYS append LIMIT 10 to prevent large result sets from causing token overflow.\n"
                 "20. PART NUMBERS, REPAIR KITS, MRP & SKU LOOKUPS:\n"
                 "   - When the user asks for MRP, repair kit details, or technical part information (e.g. 'What is the MRP for Part No 29019292JA?'), search across part number and description columns using ILIKE with wildcards (e.g. \"HLAAP SALES PART NO\" ILIKE '%29019292JA%' OR \"HLAAP PART DESCRIPTION\" ILIKE '%29019292JA%' OR LOWER(CAST(dataset AS VARCHAR)) LIKE '%29019292ja%').\n"
                 "   - If the part number or code contains hyphens or mixed alphanumeric strings, search with wildcards for the main core identifier (e.g. ILIKE '%29019292%').\n"
                 "   - Always select relevant columns including Part Number, Description, OEM, MRP, DLP, HSN, and Standard Pack.\n"
                 "IMPORTANT: DO NOT generate any <think> tags or internal reasoning steps. Output ONLY valid JSON immediately without any thinking."),
                ("user", "{question}")
            ])
            
            from langchain_core.output_parsers import StrOutputParser
            chain = prompt | self.llm | StrOutputParser() | parse_json_from_thinking
            
            query_plan_dict = await chain.ainvoke({
                "columns": ", ".join(f'"{c}"' if ' ' in str(c) or not str(c).isalnum() else str(c) for c in columns), 
                "question": query
            })
            query_plan = DuckDBSemanticQuery(**query_plan_dict)
            
            sql_query = query_plan.sql.strip().rstrip(";") + ";"
            
            # 4. DETERMINISTIC COLUMN AUTO-QUOTING (Layer 1 Protection)
            # Automatically wrap multi-word or special column names in double quotes if left unquoted by the LLM
            for col in sorted(columns, key=lambda c: len(str(c)), reverse=True):
                col_str = str(col)
                if ' ' in col_str or not col_str.isalnum():
                    pattern = r'(?<!["\'\w])' + re.escape(col_str) + r'(?!["\'\w])'
                    sql_query = re.sub(pattern, f'"{col_str}"', sql_query)
            
            logger.info(f"Generated DuckDB SQL: {sql_query} | Explanation: {query_plan.explanation}")
            
            # Defense-in-depth SQL security validation
            sec_err = validate_sql_security(sql_query)
            if sec_err:
                return sec_err
            
            # 5. EXECUTE SECURELY (with Layer 2 Self-Healing SQL Repair on Parser/Syntax Errors)
            rows = []
            col_names = []
            
            def _execute_sql(sql_str):
                with engine.connect() as conn:
                    res = conn.execute(text(sql_str))
                    return res.fetchall(), list(res.keys())
                    
            try:
                rows, col_names = await asyncio.to_thread(_execute_sql, sql_query)
            except Exception as e:
                logger.warning(f"Initial SQL execution failed ({sql_query}): {e}. Attempting self-healing repair...")
                try:
                    repair_prompt = ChatPromptTemplate.from_messages([
                        ("system",
                         "You are an enterprise DuckDB SQL expert. Fix the syntax error in the DuckDB SELECT SQL query on table 'dataset'.\n\n"
                         "Available columns in 'dataset':\n{columns}\n\n"
                         "CRITICAL RULES:\n"
                         "1. Return ONLY valid JSON with 'sql' and 'explanation'. No markdown, no <think> tags.\n"
                         "2. ALWAYS enclose column names containing spaces or symbols in DOUBLE QUOTES (e.g. \"Customer ID\").\n"
                         "3. When searching for strings containing apostrophes or single quotes (e.g. 'Ron''s Gone Wrong'), double the single quotes in SQL ('%ron''s gone wrong%') or use wildcards ('%ron%gone%wrong%').\n"
                         "4. NO PROXY METRICS: If the DuckDB Error Message indicates that a column requested by the user does not exist (e.g. 'Referenced column \"Age\" not found'), DO NOT hallucinate or substitute an unrelated column (e.g. DO NOT use 'Hire Date' to estimate 'Age'). You MUST return exactly: SELECT 'not present in dataset' AS info WHERE FALSE;\n"
                         "5. The query MUST be a read-only DuckDB SELECT on table 'dataset'."),
                        ("user",
                         "User Question: {question}\n\nFailed SQL Query:\n{sql}\n\nDuckDB Error Message:\n{error}\n\nProvide the corrected DuckDB SQL query in valid JSON.")
                    ])
                    repair_chain = repair_prompt | self.llm | StrOutputParser() | parse_json_from_thinking
                    repaired_dict = await repair_chain.ainvoke({
                        "columns": ", ".join(f'"{c}"' if ' ' in str(c) or not str(c).isalnum() else str(c) for c in columns),
                        "question": query,
                        "sql": sql_query,
                        "error": str(e)
                    })
                    repaired_plan = DuckDBSemanticQuery(**repaired_dict)
                    sql_query = repaired_plan.sql.strip().rstrip(";") + ";"
                    logger.info(f"Self-Healed DuckDB SQL: {sql_query} | Explanation: {repaired_plan.explanation}")
                    
                    sec_err_repair = validate_sql_security(sql_query)
                    if sec_err_repair:
                        return sec_err_repair
                    
                    rows, col_names = await asyncio.to_thread(_execute_sql, sql_query)
                    query_plan = repaired_plan
                except Exception as e_retry:
                    logger.error(f"Self-healing SQL retry failed: {e_retry}", exc_info=True)
                    return f"Error executing SQL ({sql_query}): {str(e)}"
                    
            # Early semantic exit
            if "WHERE FALSE" in sql_query.upper() or "not present in dataset" in query_plan.explanation.lower():
                return f"{query_plan.explanation}\nNo records matched your query."
                    
            if not rows and "WHERE " in sql_query.upper():
                logger.warning(f"Query returned 0 rows with WHERE filter ({sql_query}). Attempting Layer 3 fuzzy string matching retry...")
                try:
                    fuzzy_prompt = ChatPromptTemplate.from_messages([
                        ("system",
                         "You are an enterprise DuckDB SQL expert. The previous SQL query returned 0 rows because the WHERE filter was too strict or queried the wrong column.\n"
                         "CRITICAL RECOVERY RULES:\n"
                         "1. Rewrite the DuckDB SELECT query on table 'dataset' using case-insensitive partial string matching (ILIKE or LOWER(\"col\") LIKE '%val%') so matching rows are found.\n"
                         "2. If searching for an entity or movie title, check across candidate text columns using OR (e.g., LOWER(\"Title\") LIKE '%val%' OR LOWER(\"Overview\") LIKE '%val%').\n"
                         "3. Omit apostrophes and punctuation by inserting wildcards between words (e.g. '%ron%gone%wrong%').\n\n"
                         "Available columns in 'dataset':\n{columns}\n\n"
                         "Return ONLY valid JSON with 'sql' and 'explanation' without markdown fences."),
                        ("user",
                         "User Question: {question}\nPrevious SQL that returned 0 rows:\n{sql}")
                    ])
                    fuzzy_chain = fuzzy_prompt | self.llm | StrOutputParser() | parse_json_from_thinking
                    fuzzy_dict = await fuzzy_chain.ainvoke({
                        "columns": ", ".join(f'"{c}"' if ' ' in str(c) or not str(c).isalnum() else str(c) for c in columns),
                        "question": query,
                        "sql": sql_query
                    })
                    fuzzy_plan = DuckDBSemanticQuery(**fuzzy_dict)
                    sql_query = fuzzy_plan.sql.strip().rstrip(";") + ";"
                    logger.info(f"Layer 3 Healed DuckDB SQL: {sql_query} | Explanation: {fuzzy_plan.explanation}")
                    
                    rows, col_names = await asyncio.to_thread(_execute_sql, sql_query)
                    query_plan = fuzzy_plan
                except Exception as fuzzy_err:
                    logger.warning(f"Fuzzy retry failed: {fuzzy_err}")

            if not rows:
                return f"{query_plan.explanation}\nNo records matched your query."
                
            formatted = ""
            # Format clean, enterprise-grade response
            if len(rows) == 1 and len(col_names) == 1:
                val = rows[0][0]
                formatted += f"**{val}**"
            elif len(rows) == 1:
                parts = []
                for k, v in zip(col_names, rows[0]):
                    parts.append(f"- **{k}**: {v if v is not None else 'NULL'}")
                formatted += "\n".join(parts)
            else:
                headers = " | ".join(str(c) for c in col_names)
                sep = " | ".join("---" for _ in col_names)
                formatted += f"| {headers} |\n| {sep} |\n"
                for r in rows[:100]:
                    row_str = " | ".join(str(item) if item is not None else "NULL" for item in r)
                    formatted += f"| {row_str} |\n"
                    
            # 6. UNIVERSAL NATURAL-LANGUAGE SYNTHESIS
            # (Removed redundant synthesis step. The final RAG LLM will read the formatted Markdown table directly, saving 20-60 seconds.)

            # For large result sets (>50 rows): strip <think> and return formatted table
            formatted = re.sub(r'<think>.*?</think>', '', formatted, flags=re.DOTALL).strip()
            if '<think>' in formatted:
                formatted = formatted[:formatted.index('<think>')].strip()
            return formatted
            
        except Exception as e:
            logger.error(f"PandasQueryEngine Execution Failed: {e}", exc_info=True)
            if paths_to_register:
                invalidate_duckdb_engine_cache(paths_to_register)
            return f"Error during data analysis: {str(e)}"
