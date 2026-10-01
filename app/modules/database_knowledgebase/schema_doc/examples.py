"""Example Question Generator and SQL Executor

Generates realistic user example questions across multiple query styles:
- short, vague, synonyms, typos, multi-table joins
- Generates one read-only SELECT per question
- Executes each SQL with read-only connection, LIMIT, and timeout
- Keeps ONLY SQL that executes cleanly AND returns rows (> 0 rows)
- Rejects the rest (execution error or 0 rows returned)
- Strictly enforces that NO sensitive columns are projected in example SQL
"""

import json
import logging
from typing import Any, Dict, List, Optional
import asyncpg
from pydantic import BaseModel, Field

from app.core.llm.deepinfra_llm import DeepInfraLLMClient, strip_think_tags
from ..schemas.canonical import DatabaseSchema, TableSchema
from .mapper import TableRelationshipMap
from .sensitivity import SensitivityGuard

logger = logging.getLogger(__name__)

STATEMENT_TIMEOUT_MS = 5000  # 5s timeout
DEFAULT_QUERY_LIMIT = 10


class CandidateExample(BaseModel):
    """Candidate example question and SQL query."""
    question: str = Field(..., description="Example natural language user query")
    question_type: str = Field(..., description="Query style: short, vague, synonym, typo, or multi_table")
    sql_query: str = Field(..., description="Read-only SELECT SQL query")


class VerifiedExample(BaseModel):
    """Example question that was executed and returned rows."""
    question: str
    question_type: str
    sql_query: str
    row_count: int
    execution_time_ms: int
    status: str = "verified"


class ExampleGenerator:
    """Generates and verifies example questions and executable SQL."""

    def __init__(self, llm_client: Optional[DeepInfraLLMClient] = None):
        self.llm = llm_client or DeepInfraLLMClient.get_instance()

    async def generate_and_verify_examples(
        self,
        conn: asyncpg.Connection,
        tenant_id: str,
        table: TableSchema,
        schema: DatabaseSchema,
        relationship_map: TableRelationshipMap,
        total_tokens_tracker: Dict[str, Any],
    ) -> List[VerifiedExample]:
        """
        Generates candidate questions + SQL, validates against sensitive columns,
        executes against the live database, and retains only working queries with rows > 0.
        """
        # 1. Ask LLM to generate candidate examples
        candidates = await self._generate_candidates(
            tenant_id=tenant_id,
            table=table,
            schema=schema,
            relationship_map=relationship_map,
            total_tokens_tracker=total_tokens_tracker,
        )

        if not candidates:
            return []

        # 2. Verify each candidate against live database
        verified: List[VerifiedExample] = []
        for cand in candidates:
            # Check for sensitive column selection
            if self._selects_sensitive_columns(cand.sql_query, schema):
                logger.info(f"Rejected candidate example (selects sensitive columns): {cand.sql_query}")
                continue

            # Ensure query has LIMIT
            sql = cand.sql_query.strip().rstrip(";")
            if "limit" not in sql.lower():
                sql = f"{sql} LIMIT {DEFAULT_QUERY_LIMIT}"

            # Execute query with timeout
            import time
            t0 = time.perf_counter()
            try:
                rows = await conn.fetch(sql, timeout=STATEMENT_TIMEOUT_MS / 1000.0)
                dur_ms = int((time.perf_counter() - t0) * 1000)

                # GATE: Keep only SQL that runs AND returns rows (> 0)
                if rows and len(rows) > 0:
                    verified.append(
                        VerifiedExample(
                            question=cand.question,
                            question_type=cand.question_type,
                            sql_query=sql,
                            row_count=len(rows),
                            execution_time_ms=dur_ms,
                            status="verified",
                        )
                    )
                else:
                    logger.info(f"Rejected candidate example (returned 0 rows): {sql}")
            except Exception as exec_err:
                logger.info(f"Rejected candidate example (execution failed): {sql} - Error: {exec_err}")

        return verified

    def _selects_sensitive_columns(self, sql: str, schema: DatabaseSchema) -> bool:
        """Check if SQL explicitly selects any denied sensitive columns."""
        sql_lower = sql.lower()
        for p in SensitivityGuard.is_sensitive_column.__globals__["SENSITIVE_COLUMN_PATTERNS"]:
            # If pattern appears in the query (e.g. salary, national_id, password)
            if p in sql_lower:
                return True
        return False

    async def _generate_candidates(
        self,
        tenant_id: str,
        table: TableSchema,
        schema: DatabaseSchema,
        relationship_map: TableRelationshipMap,
        total_tokens_tracker: Dict[str, Any],
    ) -> List[CandidateExample]:
        """Call LLM to propose 4-6 diverse candidate questions and SELECT queries."""
        # Safe columns list
        safe_cols = [
            c.name for c in table.columns.values()
            if not SensitivityGuard.is_sensitive_column(c.name)
        ]

        # Connected parent/child tables
        related_tables = relationship_map.parent_tables + relationship_map.child_tables
        related_info = []
        for r_name in related_tables[:3]:
            r_tbl = schema.get_table(r_name)
            if r_tbl:
                r_safe_cols = [c.name for c in r_tbl.columns.values() if not SensitivityGuard.is_sensitive_column(c.name)]
                related_info.append(f"Related Table '{r_name}' (safe columns: {', '.join(r_safe_cols[:6])})")

        related_str = "\n".join(related_info) if related_info else "None"

        prompt = f"""Generate 5 realistic user example queries for the database table '{table.table_name}'.
Safe Columns Available: {', '.join(safe_cols)}
{related_str}

CRITICAL RULES:
1. Every query must be a valid read-only PostgreSQL SELECT statement.
2. Under NO CIRCUMSTANCES select sensitive columns like salary, national_id, date_of_birth, passwords, etc.
3. Make sure the queries join on proper keys (e.g. employee_id = employees.id) if multi-table.
4. Include diverse styles:
   - "short": concise query (e.g. "list engineers")
   - "vague": conversational query
   - "synonym": using alternative terminology
   - "typo": realistic user typo in question
   - "multi_table": join with a related table if available
5. Queries must be likely to return actual rows from the database.

Output strictly a JSON list of objects:
[
  {{
    "question": "natural language question",
    "question_type": "short | vague | synonym | typo | multi_table",
    "sql_query": "SELECT ... FROM ... LIMIT 10"
  }}
]
"""
        try:
            res_dict = await self.llm.generate_with_usage(
                prompt=prompt,
                system_prompt="You are a SQL query generator. Output strictly JSON.",
                max_tokens=1500,
                temperature=0.2,
            )
            raw_text = res_dict.get("content", "")
            inp_tok = res_dict.get("prompt_tokens", 0)
            out_tok = res_dict.get("completion_tokens", 0)

            total_tokens_tracker["input_tokens"] = total_tokens_tracker.get("input_tokens", 0) + inp_tok
            total_tokens_tracker["output_tokens"] = total_tokens_tracker.get("output_tokens", 0) + out_tok
            total_tokens_tracker["llm_calls"] = total_tokens_tracker.get("llm_calls", 0) + 1

            # Log to analytics
            try:
                from app.modules.analytics.repository import AnalyticsRepository
                from app.core.database import AsyncSessionLocal
                async with AsyncSessionLocal() as session:
                    repo = AnalyticsRepository(session)
                    await repo.log_usage(
                        tenant_id=tenant_id,
                        user_id="",
                        model_name=self.llm.model_extraction,
                        query_text=f"Schema cheat sheet example questions: {table.table_name}",
                        input_tokens=inp_tok,
                        output_tokens=out_tok,
                        task_name="schema_doc_examples",
                    )
            except Exception:
                pass

            cleaned_json = strip_think_tags(raw_text).strip()
            if cleaned_json.startswith("```json"):
                cleaned_json = cleaned_json[7:]
            if cleaned_json.startswith("```"):
                cleaned_json = cleaned_json[3:]
            if cleaned_json.endswith("```"):
                cleaned_json = cleaned_json[:-3]
            cleaned_json = cleaned_json.strip()

            parsed = json.loads(cleaned_json)
            candidates = []
            if isinstance(parsed, list):
                for item in parsed:
                    try:
                        candidates.append(CandidateExample.model_validate(item))
                    except Exception:
                        pass
            return candidates

        except Exception as e:
            logger.error(f"Failed to generate example questions for {table.table_name}: {e}")
            return []
