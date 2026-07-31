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
        return {"intents": ["aggregation"], "sql": "SELECT COUNT(*) AS total_records FROM dataset;", "explanation": "Total records in dataset"}
        
    try:
        return json.loads(text)
    except Exception as e:
        logger.warning(f"json.loads failed on text, trying yaml.safe_load: {e}")
        try:
            import yaml
            res = yaml.safe_load(text)
            if isinstance(res, dict):
                return res
        except Exception as e_yaml:
            logger.error(f"Both json.loads and yaml.safe_load failed on text: {text} | error: {e_yaml}")
            
        return {"intents": ["aggregation"], "sql": "SELECT COUNT(*) AS total_records FROM dataset;", "explanation": "Total records in dataset"}

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
    def __init__(self, data_path_or_client=None, llm_client=None, all_dataset_paths: Optional[List[str]] = None, file_names: Optional[List[str]] = None):
        if isinstance(data_path_or_client, str):
            self.data_path = data_path_or_client
            self.llm_client = llm_client
        else:
            self.data_path = None
            self.llm_client = data_path_or_client
        self.all_dataset_paths = all_dataset_paths or ([self.data_path] if self.data_path else [])
        self.file_names = file_names or []
        
        if not self.llm_client:
            from app.core.llm.deepinfra_llm import DeepInfraLLMClient
            self.llm_client = DeepInfraLLMClient()
            
        from langchain_core.runnables import RunnableLambda
        import os
        sql_model = os.environ.get("SQL_GENERATION_MODEL", "Qwen/Qwen2.5-72B-Instruct")
        
        async def _ainvoke(prompt_val, config=None, **kwargs):
            text = prompt_val.to_string() if hasattr(prompt_val, 'to_string') else str(prompt_val)
            return await self.llm_client.generate_cloud(prompt=text, model=sql_model)
            
        self.llm = RunnableLambda(_ainvoke)

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
                 "6. IMPORTANT: Do NOT output any <think> tags or internal reasoning. Output ONLY the final answer directly."),
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

            # 3. GENERATE DUCKDB SQL DIRECTLY
            prompt = ChatPromptTemplate.from_messages([
                ("system", 
                 "You are an enterprise data engine and SQL expert. Convert the user's natural language question into a clean, read-only DuckDB SELECT SQL query.\n\n"
                 "AVAILABLE DUCKDB TABLES & SCHEMAS:\n{tables_schema}\n\n"
                 "CRITICAL RULES FOR DUCKDB SQL:\n"
                 "1. You may query the merged 'dataset' view OR query individual named tables (e.g. \"Employees\", \"Sales\") directly.\n"
                 "2. MULTI-TABLE JOIN QUERIES: You CAN write SQL JOIN queries across multiple individual named tables when foreign keys match (e.g., SELECT e.name, s.amount FROM \"Employees\" e JOIN \"Sales\" s ON e.emp_id = s.emp_id).\n"
                 "3. COLUMN & TABLE NAMES WITH SPACES OR SYMBOLS: You MUST ALWAYS wrap column names and table names containing spaces, punctuation, or special characters in DOUBLE QUOTES (e.g., \"Customer ID\", \"Customer Name\", \"Total Amount\").\n"
                 "4. When performing mathematical calculations (SUM, AVG, arithmetic) on string/varchar columns, ALWAYS wrap the column in TRY_CAST(\"col\" AS DOUBLE), e.g., SUM(TRY_CAST(\"exchange_rate\" AS DOUBLE)).\n"
                 "5. For counting total records, use SELECT COUNT(*) AS total_records FROM dataset;\n"
                 "6. GENERIC SUMMARY & OVERVIEW QUERIES: If the user asks generic summary questions (e.g., 'summarize dataset', 'tell me about this file', 'overview of data', 'what does this dataset contain'), generate: SELECT * FROM dataset LIMIT 10; with an executive explanation.\n"
                 "7. For boolean columns, compare as uppercase string: UPPER(TRY_CAST(\"col\" AS VARCHAR)) = 'TRUE'.\n"
                 "8. Include descriptive column aliases (e.g. AS average_rate, AS total_count).\n"
                 "9. NEVER use INSERT, UPDATE, DELETE, DROP, or ALTER. ONLY read-only SELECT queries.\n"
                 "10. Output ONLY valid JSON matching the schema with 'sql' and 'explanation'.\n"
                 "11. STRING FILTERING & ENTITY MATCHING: When filtering string columns, ALWAYS use case-insensitive matching using ILIKE (e.g., \"Employee Name\" ILIKE '%Matthew%').\n"
                 "12. COMPARATIVE & SUPERLATIVE QUERIES: When comparing entities, DO NOT filter with WHERE name = 'both'. Select all relevant rows and ORDER BY the comparison metric DESC LIMIT 10.\n"
                 "IMPORTANT: DO NOT generate any <think> tags or internal reasoning steps. Output ONLY valid JSON immediately without any thinking."),
                ("user", "{question}")
            ])
            
            from langchain_core.output_parsers import StrOutputParser
            chain = prompt | self.llm | StrOutputParser() | parse_json_from_thinking
            
            query_plan_dict = await chain.ainvoke({
                "tables_schema": full_schema_str, 
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
                             "3. The query MUST be a read-only DuckDB SELECT on table 'dataset'."),
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
                             "You are an enterprise DuckDB SQL expert. The previous SQL query returned 0 rows because the WHERE filter was too strict.\n"
                             "Rewrite the DuckDB SELECT query on table 'dataset' using case-insensitive partial string matching (ILIKE or LOWER(\"col\") LIKE '%val%') so matching rows are found.\n\n"
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
            # (Removed redundant synthesis step. The final RAG LLM will read the formatted Markdown table directly, saving 20-60 seconds.)

            # For large result sets (>50 rows): strip <think> and return formatted table
            formatted = re.sub(r'<think>.*?</think>', '', formatted, flags=re.DOTALL).strip()
            if '<think>' in formatted:
                formatted = formatted[:formatted.index('<think>')].strip()
            return formatted
            
        except Exception as e:
            logger.error(f"PandasQueryEngine Execution Failed: {e}", exc_info=True)
            return f"Error during data analysis: {str(e)}"
