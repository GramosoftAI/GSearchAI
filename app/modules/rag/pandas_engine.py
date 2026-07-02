import pandas as pd
import json
import logging
import traceback
import re

logger = logging.getLogger(__name__)

class PandasQueryEngine:
    """
    Executes analytical queries directly on CSV datasets using Pandas and LLMs via a secure JSON AST.
    """
    def __init__(self, llm_client):
        self.llm_client = llm_client

    async def execute_query(self, query: str, csv_path: str) -> str:
        """
        Reads CSV, generates JSON AST from LLM, and builds pandas query safely.
        """
        logger.info(f" PandasEngine: Loading CSV from {csv_path}")
        try:
            df = pd.read_csv(csv_path)
        except Exception as e:
            logger.error(f" Failed to load CSV {csv_path}: {e}")
            return f"Error loading dataset: {e}"

        # Clean column names to string just in case
        df.columns = [str(c).strip() for c in df.columns]

        columns_info = {col: str(df[col].dtype) for col in df.columns}
        schema_json = json.dumps(columns_info, indent=2)

        prompt = f"""You are a data analyst. Generate a JSON Abstract Syntax Tree (AST) to answer the user's question using Pandas.
You have a DataFrame named `df`.
Schema:
{schema_json}

USER QUESTION: {query}

INSTRUCTIONS:
Return ONLY valid JSON matching this structure:
{{
  "action": "aggregate" | "top_n" | "filter",
  "filters": [
    {{"column": "col_name", "operator": "==" | "!=" | ">" | "<" | ">=" | "<=" | "contains", "value": "some_value"}}
  ],
  "aggregate": {{
    "column": "col_name",
    "function": "mean" | "max" | "min" | "sum" | "count"
  }},
  "top_n": {{
    "n": 10,
    "sort_column": "col_name",
    "ascending": false,
    "columns_to_return": ["col1", "col2"]
  }}
}}

Notes:
- "filters" is optional.
- If "action" is "aggregate", you MUST provide the "aggregate" object.
- If "action" is "top_n", you MUST provide the "top_n" object.
- Use "contains" for substring search on text columns.
"""

        try:
            ast_response = await self.llm_client.generate(
                prompt=prompt,
                system_prompt="You are a Pandas JSON AST generator. Return only JSON.",
                temperature=0.0,
                max_tokens=500
            )
            
            ast_response = ast_response.strip()
            if ast_response.startswith("```json"):
                ast_response = ast_response[7:]
            if ast_response.startswith("```"):
                ast_response = ast_response[3:]
            if ast_response.endswith("```"):
                ast_response = ast_response[:-3]
            ast_response = ast_response.strip()
            
            logger.info(f" PandasEngine: Generated AST: {ast_response}")
            ast = json.loads(ast_response)

            # Apply filters
            if "filters" in ast and ast["filters"]:
                for f in ast["filters"]:
                    col = f["column"]
                    op = f["operator"]
                    val = f["value"]
                    
                    if col not in df.columns:
                        continue
                        
                    # Handle numeric conversion if column is numeric
                    if pd.api.types.is_numeric_dtype(df[col]):
                        try:
                            val = float(val)
                        except ValueError:
                            pass
                    
                    if op == "==":
                        df = df[df[col] == val]
                    elif op == "!=":
                        df = df[df[col] != val]
                    elif op == ">":
                        df = df[df[col] > val]
                    elif op == "<":
                        df = df[df[col] < val]
                    elif op == ">=":
                        df = df[df[col] >= val]
                    elif op == "<=":
                        df = df[df[col] <= val]
                    elif op == "contains":
                        df = df[df[col].astype(str).str.contains(str(val), case=False, na=False)]

            action = ast.get("action")
            result_str = ""
            
            if action == "aggregate":
                agg = ast.get("aggregate", {})
                col = agg.get("column")
                func = agg.get("function")
                
                if col and func and col in df.columns:
                    if func == "mean":
                        val = df[col].mean()
                    elif func == "max":
                        val = df[col].max()
                    elif func == "min":
                        val = df[col].min()
                    elif func == "sum":
                        val = df[col].sum()
                    elif func == "count":
                        val = df[col].count()
                    else:
                        val = "Unknown aggregate function"
                    result_str = str(val)
                elif func == "count":
                    result_str = str(len(df))
                else:
                    result_str = "Invalid aggregate configuration"
                    
            elif action == "top_n":
                top = ast.get("top_n", {})
                n = top.get("n", 5)
                sort_col = top.get("sort_column")
                ascending = top.get("ascending", False)
                cols_to_return = top.get("columns_to_return", list(df.columns))
                
                # Filter valid columns
                cols_to_return = [c for c in cols_to_return if c in df.columns]
                if not cols_to_return:
                    cols_to_return = list(df.columns)
                    
                if sort_col and sort_col in df.columns:
                    df = df.sort_values(by=sort_col, ascending=ascending).head(n)
                else:
                    df = df.head(n)
                    
                result_str = df[cols_to_return].to_json(orient="records")
                
            elif action == "filter":
                result_str = df.head(50).to_json(orient="records")
            else:
                result_str = f"Unknown action: {action}"

            explanation = (
                f"\n\n---\n**Data Analytics Pipeline (Secure Pandas Engine)**\n"
                f"- **CSV Source**: {csv_path.split('/')[-1].split(chr(92))[-1]}\n"
                f"- **AST Action**: {action}\n"
            )
            
            return result_str + explanation

        except json.JSONDecodeError:
            logger.error(f" PandasEngine Error: Failed to parse LLM JSON AST.")
            return "Error: LLM generated invalid JSON AST."
        except Exception as e:
            logger.error(f" PandasEngine Error: {e}\n{traceback.format_exc()}")
            return f"Error executing analytics query: {str(e)}"
