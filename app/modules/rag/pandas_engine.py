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
    def __init__(self, data_path_or_client=None, llm_client=None, all_dataset_paths: Optional[List[str]] = None):
        if isinstance(data_path_or_client, str):
            self.data_path = data_path_or_client
            self.llm_client = llm_client
        else:
            self.data_path = None
            self.llm_client = data_path_or_client
        self.all_dataset_paths = all_dataset_paths or ([self.data_path] if self.data_path else [])
        
        if not self.llm_client:
            from app.core.llm.deepinfra_llm import DeepInfraLLMClient
            self.llm_client = DeepInfraLLMClient()
            
        from langchain_core.runnables import RunnableLambda
        
        async def _ainvoke(prompt_val, config=None, **kwargs):
            text = prompt_val.to_string() if hasattr(prompt_val, 'to_string') else str(prompt_val)
            return await self.llm_client.generate_cloud(prompt=text)
            
        self.llm = RunnableLambda(_ainvoke)

    def get_schema_columns(self, data_path: Optional[str] = None) -> List[str]:
        """Fast helper to retrieve columns of the active dataset for schema-aware intent routing."""
        target_path = data_path or getattr(self, "data_path", None)
        if not target_path or not os.path.exists(target_path):
            return []
        try:
            temp_db_path = os.path.join(tempfile.gettempdir(), f"duckdb_{id(self)}.db")
            engine = create_engine(f"duckdb:///{temp_db_path}")
            with engine.connect() as conn:
                safe_path = str(target_path).replace('\\', '/')
                conn.execute(text("DROP VIEW IF EXISTS dataset;"))
                reader = f"read_parquet('{safe_path}')" if safe_path.lower().endswith(".parquet") else f"read_csv_auto('{safe_path}', sample_size=1000, nullstr='NULL')"
                conn.execute(text(f"CREATE VIEW dataset AS SELECT * FROM {reader};"))
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

    async def execute_query(self, query: str, data_path: Optional[str] = None) -> Optional[str]:
        target_path = data_path or getattr(self, "data_path", None)
        if not target_path or not os.path.exists(target_path):
            return f"Error: Dataset {target_path} not found on server."
            
        from langchain_core.output_parsers import StrOutputParser
        # DUCKDB BINDING (CSV or PARQUET)
        logger.info(f"Initializing DuckDB on dataset: {target_path} | total_paths: {len(self.all_dataset_paths)}")
        try:
            temp_db_path = os.path.join(tempfile.gettempdir(), f"duckdb_{id(self)}.db")
            engine = create_engine(f"duckdb:///{temp_db_path}")
            
            with engine.connect() as conn:
                paths_to_register = self.all_dataset_paths if self.all_dataset_paths else [target_path]
                for idx, path_item in enumerate(paths_to_register):
                    if not path_item or not os.path.exists(path_item):
                        continue
                    safe_path = str(path_item).replace('\\', '/')
                    view_name = "dataset" if idx == 0 else f"dataset_{idx+1}"
                    conn.execute(text(f"DROP VIEW IF EXISTS {view_name};"))
                    reader = f"read_parquet('{safe_path}')" if safe_path.lower().endswith(".parquet") else f"read_csv_auto('{safe_path}', sample_size=10000, nullstr='NULL')"
                    conn.execute(text(f"CREATE VIEW {view_name} AS SELECT row_number() OVER () AS row_id, * FROM {reader};"))
                try:
                    conn.commit()
                except:
                    pass
                    
                result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'dataset';"))
                columns = [row[0] for row in result.fetchall()]

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
                 "14. If the user asks for information or columns that DO NOT EXIST in the schema (e.g. wholesale price, CEO, warehouse, email, warranty), generate: SELECT 'Not present in dataset' AS info WHERE FALSE; with explanation stating the information is not present in the dataset.\n"
                 "15. STRING FILTERING & ENTITY MATCHING: When filtering string columns (e.g. employee names, departments, products in WHERE clauses), NEVER use exact '=' or 'IN (...)'. ALWAYS use case-insensitive matching with ILIKE or LOWER(str) LIKE '%val%' (e.g., WHERE LOWER(\"Employee Name\") LIKE '%john%' OR LOWER(\"Employee Name\") LIKE '%jane%') so that minor spacing or case differences do not cause zero results.\n"
                 "16. COMPARATIVE & SUPERLATIVE QUERIES: When the user asks to compare two or more entities (e.g. 'who has higher salary', 'compare the salary of both', 'who is better', 'who earns more', 'which has better'):\n"
                 "   - If the query mentions 'both', 'all', or does not specify explicit employee names, DO NOT filter with WHERE name = 'both'. Instead, select all rows from dataset and ORDER BY the comparison metric DESC (e.g., SELECT * FROM dataset ORDER BY TRY_CAST(\"Salary\" AS DOUBLE) DESC LIMIT 10;).\n"
                 "   - Select all relevant columns (name, department, salary, hire date, etc.) so the response synthesizer has full structured comparison data.\n"
                 "17. SENIORITY, TENURE & JOINING DATE QUERIES: When the user asks who is the 'senior' ('snior'), 'most senior', 'oldest', or 'who joined first/earliest' among employees:\n"
                 "   - If comparing by JOINING DATE / HIRE DATE / START DATE: A senior employee joined EARLIEST in time. You MUST cast string dates to date/timestamp and order ASCENDING (ORDER BY TRY_CAST(\"Joining Date\" AS DATE) ASC) so the earliest date (earliest year, e.g. 2018 before 2022) is ranked FIRST.\n"
                 "   - If comparing by YEARS OF EXPERIENCE / TENURE / AGE: A senior employee has more years. You MUST order DESCENDING (ORDER BY TRY_CAST(\"Experience\" AS DOUBLE) DESC).\n"
                 "   - If selecting among specific people (e.g. 'between John and Jane'), always use case-insensitive fuzzy matching (LOWER(\"col\") LIKE '%name%') for the WHERE clause. If selecting 'among both', DO NOT filter by the word 'both'.\n"
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
                    
            # 6. UNIVERSAL NATURAL-LANGUAGE SYNTHESIS (rows <= 50)
            if len(rows) <= 50:
                logger.info(f"[PandasQueryEngine] Executing natural-language synthesis for: '{query}'...")
                return await self._synthesize_analytical_response(query, formatted, query_plan.explanation)

            # For large result sets (>50 rows): strip <think> and return formatted table
            formatted = re.sub(r'<think>.*?</think>', '', formatted, flags=re.DOTALL).strip()
            if '<think>' in formatted:
                formatted = formatted[:formatted.index('<think>')].strip()
            return formatted
            
        except Exception as e:
            logger.error(f"PandasQueryEngine Execution Failed: {e}", exc_info=True)
            return f"Error during data analysis: {str(e)}"
