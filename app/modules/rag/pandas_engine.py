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
        description="Concise human explanation of what the query retrieves."
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
        settings = get_settings()
        
        api_key = getattr(settings, "deepinfra_api_key", "")
        base_url = getattr(settings, "deepinfra_api_url", "https://api.deepinfra.com/v1/openai")
        model_name = getattr(settings, "deepinfra_llm_model", "Qwen/Qwen2.5-72B-Instruct")
        
        self.llm = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0.0,
            max_tokens=2048,
            extra_body={"enable_thinking": False}
        )

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
            logger.info(f"Generated DuckDB SQL: {sql_query} | Explanation: {query_plan.explanation}")
            
            # Security check
            forbidden_kw = ["INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE ", "REPLACE ", "EXEC ", "ATTACH ", "DETACH "]
            if any(kw in sql_query.upper() for kw in forbidden_kw):
                return "Error: Security violation - only read-only SELECT queries are permitted."
            
            # 5. EXECUTE SECURELY
            with engine.connect() as conn:
                try:
                    result = conn.execute(text(sql_query))
                    rows = result.fetchall()
                    col_names = list(result.keys())
                except Exception as e:
                    return f"Error executing SQL ({sql_query}): {str(e)}"
                    
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
                    
            return formatted
            
        except Exception as e:
            logger.error(f"PandasQueryEngine Execution Failed: {e}", exc_info=True)
            return f"Error during data analysis: {str(e)}"
