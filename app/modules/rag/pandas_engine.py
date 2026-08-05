import logging
from typing import Optional, Dict, Literal
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from app.core.config import get_settings
import tempfile
import os
import re
import json
from typing import Optional, Dict, Literal, List
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
        
    if not text:
        logger.error(f"LLM returned empty text after stripping think tags: {raw_text}")
        return {"intents": ["row_lookup"], "sql": "SELECT * FROM dataset LIMIT 10;", "explanation": "Retrieved sample records from dataset"}
        
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
            
        return {"intents": ["row_lookup"], "sql": "SELECT * FROM dataset LIMIT 10;", "explanation": "Retrieved sample records from dataset"}

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

class PandasQueryEngine:
    """
    Hybrid Execution Engine for 1M+ rows.
    Implements Intent Routing, Parquet querying, and strict Semantic SQL building.
    """
    def __init__(self, data_path_or_client=None, llm_client=None, all_dataset_paths: Optional[List[str]] = None, file_names: Optional[List[str]] = None, path_mapping: Optional[Dict[str, str]] = None):
        if isinstance(data_path_or_client, str):
            self.data_path = data_path_or_client
            self.llm_client = llm_client
        else:
            self.data_path = None
            self.llm_client = data_path_or_client
        self.all_dataset_paths = all_dataset_paths or ([self.data_path] if self.data_path else [])
        self.file_names = file_names or []
        self.path_mapping = path_mapping or {}
        
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
        """Builds a DuckDB UNION ALL BY NAME query across all provided CSV/Parquet dataset paths, tracking source files."""
        valid_readers = []
        for p in paths:
            if not p or not os.path.exists(p):
                continue
            safe_path = str(p).replace('\\', '/')
            filename = os.path.basename(safe_path)
            display_name = self.path_mapping.get(filename, filename)
            if safe_path.lower().endswith(".parquet"):
                valid_readers.append(f"SELECT *, '{display_name}' AS source_file FROM read_parquet('{safe_path}')")
            else:
                valid_readers.append(f"SELECT *, '{display_name}' AS source_file FROM read_csv_auto('{safe_path}', sample_size=10000, nullstr='NULL')")
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
            temp_db_path = os.path.join(tempfile.gettempdir(), f"duckdb_{id(self)}.db")
            engine = create_engine(f"duckdb:///{temp_db_path}")
            with engine.connect() as conn:
                union_sql = self._build_union_query(paths_to_check, with_row_id=False)
                conn.execute(text("DROP VIEW IF EXISTS dataset;"))
                conn.execute(text(f"CREATE VIEW dataset AS {union_sql};"))
                result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'dataset';"))
                return [row[0] for row in result.fetchall()]
        except Exception as e:
            logger.warning(f"Failed fetching schema columns for routing: {e}")
            return []

    async def _synthesize_analytical_response(self, question: str, table_md: str, explanation: str, episodic_guidance: str = "") -> str:
        """Synthesizes an executive natural-language answer from SQL table results for comparative or analytical queries."""
        try:
            system_instruction = (
                "You are an Executive Data Analyst. Given a user's question and the retrieved database result from an enterprise spreadsheet dataset, write a clear, fluent, natural-language executive answer.\n"
                "CRITICAL RULES:\n"
                "1. Answer ONLY using the retrieved data. Do not invent or assume information.\n"
                "2. Answer the user's specific question DIRECTLY in the very first sentence.\n"
                "3. FOR SENIORITY / TENURE QUESTIONS: Remember that an employee who joined EARLIER in time (earliest year/date, e.g. 2018 vs 2021) or has MORE years of experience is MORE SENIOR.\n"
                "4. ALWAYS format the explanation and findings in clear, concise bullet points instead of a continuous paragraph/passage. Each key metric, value, or comparative detail must be a separate bullet point.\n"
                "5. Include the formatted Markdown table below your explanation as supporting evidence.\n"
                "6. FOR FULL DETAILS OR MOVIE/ENTITY QUERIES: Give the complete details of the movie/entity (Title, Release Date, Overview/Plot, Popularity, Vote Average, Genre, etc.) from the table clearly and accurately. If multiple records are returned, summarize the top items clearly and concisely so the response remains focused and does not exceed token length limits.\n"
                "7. IMPORTANT: Do NOT output any <think> tags or internal reasoning. Output ONLY the final answer directly."
            )
            if episodic_guidance:
                system_instruction += f"\n8. STRICT USER PREFERENCES: You must strictly format the response to adhere to the following user instructions:\n{episodic_guidance}\n"

            synth_prompt = ChatPromptTemplate.from_messages([
                ("system", system_instruction),
                ("user", "User Question: {question}\n\nSQL Explanation: {explanation}\n\nRetrieved Database Result Table:\n{table}")
            ])
            from langchain_core.output_parsers import StrOutputParser
            synth_chain = synth_prompt | self.llm | StrOutputParser()
            synthesis = await synth_chain.ainvoke({
                "question": question,
                "explanation": explanation,
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
                return path  # Return original — caller will catch os.path.exists failure
        return path

    async def execute_query(self, query: str, data_path: Optional[str] = None, synthesize: bool = False, episodic_guidance: str = "") -> Optional[str]:
        raw_path = data_path or getattr(self, "data_path", None)
        # Resolve S3/HTTPS URLs to local temp files before DuckDB can read them
        target_path = await self._resolve_to_local_path(raw_path) if raw_path else None
        paths_to_register = [p for p in (self.all_dataset_paths or ([target_path] if target_path else [])) if p and os.path.exists(p)]
        if not paths_to_register:
            logger.error(f"No valid local dataset path found. raw_path={raw_path!r}, resolved={target_path!r}")
            return "Error: No valid spreadsheet datasets found on server."
            
        from langchain_core.output_parsers import StrOutputParser
        # DUCKDB BINDING (CSV or PARQUET)
        logger.info(f"Initializing DuckDB on dataset(s): {target_path} | total_paths: {len(paths_to_register)}")
        try:
            temp_db_path = os.path.join(tempfile.gettempdir(), f"duckdb_{id(self)}.db")
            engine = create_engine(f"duckdb:///{temp_db_path}")
            
            with engine.connect() as conn:
                union_sql = self._build_union_query(paths_to_register, with_row_id=True)
                conn.execute(text("DROP VIEW IF EXISTS dataset;"))
                conn.execute(text(f"CREATE VIEW dataset AS {union_sql};"))
                
                registered_view_names = []
                # Register distinct named views for each uploaded spreadsheet file
                for idx, path_item in enumerate(paths_to_register):
                    safe_path = str(path_item).replace('\\', '/')
                    reader = f"read_parquet('{safe_path}')" if safe_path.lower().endswith(".parquet") else f"read_csv_auto('{safe_path}', sample_size=10000, nullstr='NULL')"
                    
                    # Backward-compatible numbered views
                    conn.execute(text(f"DROP VIEW IF EXISTS dataset_{idx+1};"))
                    conn.execute(text(f"CREATE VIEW dataset_{idx+1} AS SELECT row_number() OVER () AS row_id, * FROM {reader};"))
                    
                    # Generate clean, sanitized named view from source filename
                    raw_fn = self.file_names[idx] if idx < len(self.file_names) and self.file_names[idx] else os.path.basename(path_item)
                    base_name = os.path.splitext(os.path.basename(raw_fn))[0]
                    sanitized_name = re.sub(r'[^a-zA-Z0-9_]', '_', base_name).strip('_')
                    if not sanitized_name or sanitized_name.isdigit():
                        sanitized_name = f"table_{idx+1}"
                    
                    if sanitized_name.lower() != "dataset" and sanitized_name not in registered_view_names:
                        try:
                            conn.execute(text(f'DROP VIEW IF EXISTS "{sanitized_name}";'))
                            conn.execute(text(f'CREATE VIEW "{sanitized_name}" AS SELECT row_number() OVER () AS row_id, * FROM {reader};'))
                            registered_view_names.append(sanitized_name)
                        except Exception as view_err:
                            logger.warning(f"Failed to create named view '{sanitized_name}': {view_err}")
                        
                try:
                    conn.commit()
                except:
                    pass
                    
                # Extract schema across all registered views
                tables_schema_text = []
                # 1. Main 'dataset' view
                res_dataset = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'dataset';"))
                columns = [row[0] for row in res_dataset.fetchall()]
                tables_schema_text.append(f"- Table 'dataset' (Unified view combining all uploaded spreadsheets):\n  Columns: " + ", ".join(f'"{c}"' for c in columns))
                
                # 2. Individual named views
                for vname in registered_view_names:
                    res_v = conn.execute(text(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{vname}';"))
                    v_cols = [row[0] for row in res_v.fetchall()]
                    if v_cols:
                        tables_schema_text.append(f"- Table \"{vname}\" (Individual spreadsheet file view):\n  Columns: " + ", ".join(f'"{c}"' for c in v_cols))
                        
                full_schema_str = "\n".join(tables_schema_text)

                schema_desc_parts = []
                for idx, path_item in enumerate(paths_to_register):
                    filename = os.path.basename(path_item)
                    display_name = self.path_mapping.get(filename, filename)
                    view_name = f"dataset_{idx+1}"
                    res = conn.execute(text(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{view_name}';"))
                    view_cols = [r[0] for r in res.fetchall() if r[0] not in ('row_id', 'source_file') and not r[0].startswith('_duplicated') and not re.match(r'^C\d+$', r[0])]
                    schema_desc_parts.append(f"- View '{view_name}' maps to '{display_name}' (contains columns: {', '.join(view_cols)})")
                schema_description = "\n".join(schema_desc_parts)

            # 3. GENERATE DUCKDB SQL DIRECTLY
            prompt = ChatPromptTemplate.from_messages([
                ("system", 
                 "You are an enterprise data engine and SQL expert. Convert the user's natural language question into a clean, read-only DuckDB SELECT SQL query on the view named 'dataset'.\n\n"
                 "Available columns in 'dataset':\n{columns}\n\n"
                 "Registered Source Files:\n{schema_description}\n\n"
                 "CRITICAL RULES FOR DUCKDB SQL:\n"
                 "1. Table name MUST ALWAYS be 'dataset' (unless querying schema metadata from 'information_schema.columns' as described in Rule 20).\n"
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
                 "14. If the user asks for information or columns that DO NOT EXIST in the schema (e.g. wholesale price, CEO, warehouse, email, warranty), generate: SELECT 'Not present in dataset' AS info WHERE FALSE; with explanation stating the information is not present in the dataset.\n"
                 "15. STRING FILTERING & ENTITY MATCHING: When filtering columns in WHERE clauses or using string functions like LOWER() or ILIKE, ALWAYS wrap the column name in TRY_CAST(\"col\" AS VARCHAR) first (e.g. LOWER(TRY_CAST(\"col\" AS VARCHAR)) ILIKE '%val%') to prevent DuckDB binder errors on numeric or bigint columns.\n"
                 "16. COMPARATIVE & SUPERLATIVE QUERIES: When the user asks to compare two or more entities (e.g. 'who has higher salary', 'compare the salary of both', 'who is better', 'who earns more', 'which has better'):\n"
                 "   - If the query mentions 'both', 'all', or does not specify explicit employee names, DO NOT filter with WHERE name = 'both'. Instead, select all rows from dataset and ORDER BY the comparison metric DESC (e.g., SELECT * FROM dataset ORDER BY TRY_CAST(\"Salary\" AS DOUBLE) DESC LIMIT 10;).\n"
                 "   - Select all relevant columns (name, department, salary, hire date, etc.) so the response synthesizer has full structured comparison data.\n"
                 "17. SENIORITY, TENURE & JOINING DATE QUERIES: When the user asks who is the 'senior' ('snior'), 'most senior', 'oldest', or 'who joined first/earliest' among employees:\n"
                 "   - If comparing by JOINING DATE / HIRE DATE / START DATE: A senior employee joined EARLIEST in time. You MUST cast string dates to date/timestamp and order ASCENDING (ORDER BY TRY_CAST(\"Joining Date\" AS DATE) ASC) so the earliest date (earliest year, e.g. 2018 before 2022) is ranked FIRST.\n"
                 "   - If comparing by YEARS OF EXPERIENCE / TENURE / AGE: A senior employee has more years. You MUST order DESCENDING (ORDER BY TRY_CAST(\"Experience\" AS DOUBLE) DESC).\n"
                 "   - If selecting among specific people (e.g. 'between John and Jane'), always use case-insensitive fuzzy matching (LOWER(\"col\") LIKE '%name%') for the WHERE clause. If selecting 'among both', DO NOT filter by the word 'both'.\n"
                 "18. MULTI-DATASET / SOURCE FILE FILTERING: 'source_file' is a special string column injected automatically that contains the original CSV or Parquet filename (e.g., 'employees.csv', 'payroll_2.csv'). If the user's query mentions or implies a specific file or dataset (e.g., '1st CSV file', 'second dataset', or matches a specific filename pattern), you MUST filter on the 'source_file' column using ILIKE (e.g., source_file ILIKE '%1%' or source_file ILIKE '%payroll%').\n"
                 "19. MULTI-COLUMN KEYWORD SEARCH: If the query contains search terms/keywords (e.g. 'zuni', 'glitz') and it is ambiguous which column they belong to, you MUST search across all potentially relevant text/identifying columns using OR (e.g., LOWER(TRY_CAST(\"COMPANY NAME\" AS VARCHAR)) ILIKE '%zuni%' OR LOWER(TRY_CAST(\"CITY\" AS VARCHAR)) ILIKE '%zuni%' OR LOWER(TRY_CAST(\"ADD\" AS VARCHAR)) ILIKE '%zuni%') so that you do not miss the record due to a wrong guess.\n"
                 "20. METADATA, COLUMN LISTS, AND SCHEMA QUERIES: If the user asks about the schema, the number of columns, column names, or column types:\n"
                 "   - The system automatically injects `row_id` (at position 1) and `source_file` (at the end). Also, dirty CSVs might contain auto-generated empty columns like `_duplicated_X` or `C7` (represented as columns starting with `_duplicated` or a single 'C' followed by digits).\n"
                 "   - You MUST FILTER OUT these internal/duplicate columns: `'row_id'`, `'source_file'`, `'_duplicated_%'`, and `regexp_matches(column_name, '^C\\d+$')` when counting or listing columns.\n"
                 "   - If the user asks to count or list columns per individual file/dataset, you MUST query the columns of each individual view (`dataset_1` for the first file, `dataset_2` for the second file, etc.).\n"
                 "   - E.g., to count the number of columns in the first file: SELECT COUNT(*) AS column_count FROM information_schema.columns WHERE table_name = 'dataset_1' AND column_name NOT IN ('row_id', 'source_file') AND column_name NOT LIKE '_duplicated_%' AND NOT regexp_matches(column_name, '^C\\d+$');\n"
                 "   - E.g., to list columns for each individual file: SELECT table_name, column_name FROM information_schema.columns WHERE table_name LIKE 'dataset_%' AND column_name NOT IN ('row_id', 'source_file') AND column_name NOT LIKE '_duplicated_%' AND NOT regexp_matches(column_name, '^C\\d+$') ORDER BY table_name, ordinal_position;\n"
                 "   - E.g., to count columns for each individual file: SELECT table_name, COUNT(*) AS column_count FROM information_schema.columns WHERE table_name LIKE 'dataset_%' AND column_name NOT IN ('row_id', 'source_file') AND column_name NOT LIKE '_duplicated_%' AND NOT regexp_matches(column_name, '^C\\d+$') GROUP BY table_name ORDER BY table_name;\n"
                 "   - E.g., to find the name of column X (1-indexed CSV column): calculate its offset by ignoring `row_id` (e.g. column 1 in CSV is position 2 in DB, column 2 in CSV is position 3 in DB). To get column 2: SELECT column_name FROM information_schema.columns WHERE table_name = 'dataset' AND column_name NOT IN ('row_id', 'source_file') AND column_name NOT LIKE '_duplicated_%' AND NOT regexp_matches(column_name, '^C\\d+$') ORDER BY ordinal_position LIMIT 1 OFFSET 1;\n"
                 "21. NUMERICAL SORTING: When ordering/sorting (ORDER BY) a column containing numeric values (such as 'S.No', serial numbers, employee IDs, counts, sums, or ages), you MUST wrap the column name in TRY_CAST(\"col\" AS INTEGER) or TRY_CAST(\"col\" AS DOUBLE) (e.g., ORDER BY TRY_CAST(\"S.No\" AS INTEGER) ASC) to prevent alphabetical string sorting (which places '10' before '2').\n"
                 "22. POSITIONAL & CHRONOLOGICAL ROW ORDERING (first, last, top, bottom, latest, oldest):\n"
                 "   - When the user asks for the 'last row(s)', 'last N rows', 'last record(s)', 'last entry', or 'last movie/item in the dataset/excel/table' without a specific date filter, you MUST use ANSI OFFSET from total count: SELECT * FROM dataset OFFSET (SELECT COUNT(*) FROM dataset) - N LIMIT N; (e.g. OFFSET (SELECT COUNT(*) FROM dataset) - 1 LIMIT 1; for the last row). NEVER rely on row_id ordering alone as parallel ingestion can make row_id order non-deterministic.\n"
                 "   - When the user asks for the 'first row(s)', 'first N rows', 'first record(s)', 'first entry', or 'first movie/item in the dataset/excel/table', select directly from top: SELECT * FROM dataset LIMIT N;\n"
                 "   - When the user asks for 'latest', 'newest', or 'most recent' by date/release date, cast date strings to DATE and order DESCENDING: ORDER BY TRY_CAST(\"Release_Date\" AS DATE) DESC LIMIT N;\n"
                 "   - When the user asks for 'oldest' or 'earliest' by date, order ASCENDING: ORDER BY TRY_CAST(\"Release_Date\" AS DATE) ASC LIMIT N;\n"
                 "23. SPECIFIC RECORD DETAILS LOOKUP, STRING APOSTROPHES & LENGTH GUARDS:\n"
                 "   - When asking for 'details', 'full details', or information about a specific movie, person, or title (e.g. 'Ron''s Gone Wrong full details', 'details of King''s Man'), generate a SELECT * FROM dataset WHERE LOWER(\"Title\") LIKE '%ron%gone%wrong%'; (or corresponding name column). NEVER generate a COUNT(*) aggregation query when the user asks for details of a specific item!\n"
                 "   - When a title or search string contains an apostrophe or single quote (''), you MUST escape it by doubling the single quote in SQL (e.g., '%ron''s gone wrong%') OR omit the apostrophe using wildcards (e.g., '%ron%gone%wrong%').\n"
                 "   - When querying general details without an explicit WHERE name/title filter (e.g. 'show me all movies' or general overview), ALWAYS append LIMIT 10 to prevent large result sets from causing token overflow.\n"
                 "IMPORTANT: DO NOT generate any <think> tags or internal reasoning steps. Output ONLY valid JSON immediately without any thinking."),
                ("user", "{question}")
            ])
            
            from langchain_core.output_parsers import StrOutputParser
            chain = prompt | self.llm | StrOutputParser() | parse_json_from_thinking
            
            query_plan_dict = await chain.ainvoke({
                "tables_schema": full_schema_str, 
                "columns": ", ".join(f'"{c}"' if ' ' in str(c) or not str(c).isalnum() else str(c) for c in columns), 
                "schema_description": schema_description,
                "question": query
            })
            query_plan = DuckDBSemanticQuery(**query_plan_dict)
            
            sql_query = query_plan.sql.strip().rstrip(";") + ";"
            
            # Enforce safety limit on SELECT queries without LIMIT (OOM protection)
            if "LIMIT " not in sql_query.upper() and "SELECT " in sql_query.upper() and "COUNT(" not in sql_query.upper() and "SUM(" not in sql_query.upper():
                sql_query = sql_query.rstrip(";").strip() + " LIMIT 100;"
            
            # 4. DETERMINISTIC COLUMN AUTO-QUOTING (Layer 1 Protection)
            # Automatically wrap multi-word or special column names in double quotes if left unquoted by the LLM
            for col in sorted(columns, key=lambda c: len(str(c)), reverse=True):
                col_str = str(col)
                if ' ' in col_str or not col_str.isalnum():
                    pattern = r'(?<!["\'\w])' + re.escape(col_str) + r'(?!["\'\w])'
                    sql_query = re.sub(pattern, f'"{col_str}"', sql_query)
            
            logger.info(f"Generated DuckDB SQL: {sql_query} | Explanation: {query_plan.explanation}")
            
            # Security check
            forbidden_kw = ["INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE ", "REPLACE ", "EXEC ", "ATTACH ", "DETACH "]
            if any(kw in sql_query.upper() for kw in forbidden_kw):
                return "Error: Security violation - only read-only SELECT queries are permitted."
            
            # 5. EXECUTE SECURELY (with Layer 2 Self-Healing SQL Repair on Parser/Syntax Errors)
            with engine.connect() as conn:
                try:
                    result = conn.execute(text(sql_query))
                    rows = result.fetchall()
                    col_names = list(result.keys())
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
                             "4. The query MUST be a read-only DuckDB SELECT on table 'dataset' (or information_schema.columns for metadata queries)."),
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
                        result = conn.execute(text(sql_query))
                        rows = result.fetchall()
                        col_names = list(result.keys())
                        query_plan = repaired_plan
                    except Exception as e_retry:
                        logger.error(f"Self-healing SQL retry failed: {e_retry}", exc_info=True)
                        return f"Error executing SQL ({sql_query}): {str(e)}"
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
                    result = conn.execute(text(sql_query))
                    rows = result.fetchall()
                    col_names = list(result.keys())
                    query_plan = fuzzy_plan
                except Exception as fuzzy_err:
                    logger.warning(f"Fuzzy retry failed: {fuzzy_err}")

            if not rows:
                logger.info("   -> Query returned 0 rows. Triggering DuckDB Dataset Summary Fallback (SELECT * FROM dataset LIMIT 10)...")
                try:
                    result = conn.execute(text("SELECT * FROM dataset LIMIT 10;"))
                    rows = result.fetchall()
                    col_names = list(result.keys())
                    query_plan.explanation = "Executive Dataset Structure & Sample Data Overview"
                except Exception as fallback_err:
                    logger.warning(f"Dataset preview fallback failed: {fallback_err}")
                    return f"{query_plan.explanation}\nNo records matched your query."
                
            formatted = ""
            # Format clean, enterprise-grade response
            if len(rows) == 1 and len(col_names) == 1:
                val = rows[0][0]
                formatted += f"**{val}**\n\n_{query_plan.explanation}_"
            elif len(rows) == 1:
                parts = [f"_{query_plan.explanation}_\n"]
                for k, v in zip(col_names, rows[0]):
                    parts.append(f"- **{k}**: {v if v is not None else 'NULL'}")
                formatted += "\n".join(parts)
            else:
                headers = " | ".join(str(c) for c in col_names)
                sep = " | ".join("---" for _ in col_names)
                formatted += f"_{query_plan.explanation}_\n\n| {headers} |\n| {sep} |\n"
                for r in rows[:100]:
                    row_str = " | ".join(str(item) if item is not None else "NULL" for item in r)
                    formatted += f"| {row_str} |\n"
                    
            # 6. UNIVERSAL NATURAL-LANGUAGE SYNTHESIS
            if synthesize:
                try:
                    table_for_synth = ""
                    if len(rows) == 1 and len(col_names) == 1:
                        table_for_synth = str(rows[0][0])
                    elif len(rows) == 1:
                        table_for_synth = "\n".join(f"- {k}: {v if v is not None else 'NULL'}" for k, v in zip(col_names, rows[0]))
                    else:
                        table_for_synth = f"| {' | '.join(str(c) for c in col_names)} |\n| {' | '.join('---' for _ in col_names)} |\n"
                        for r in rows[:100]:
                            table_for_synth += f"| {' | '.join(str(item) if item is not None else 'NULL' for item in r)} |\n"
                    
                    synthesized = await self._synthesize_analytical_response(query, table_for_synth, query_plan.explanation, episodic_guidance)
                    # Clean up thinking tags
                    synthesized = re.sub(r'<think>.*?</think>', '', synthesized, flags=re.DOTALL).strip()
                    if '<think>' in synthesized:
                        synthesized = synthesized[:synthesized.index('<think>')].strip()
                    return synthesized
                except Exception as synth_err:
                    logger.warning(f"Synthesis failed, falling back to formatted table: {synth_err}")

            # For large result sets (>50 rows): strip <think> and return formatted table
            formatted = re.sub(r'<think>.*?</think>', '', formatted, flags=re.DOTALL).strip()
            if '<think>' in formatted:
                formatted = formatted[:formatted.index('<think>')].strip()
            return formatted
            
        except Exception as e:
            logger.error(f"PandasQueryEngine Execution Failed: {e}", exc_info=True)
            return f"Error during data analysis: {str(e)}"
