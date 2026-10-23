"""Grounded SQL Generator for Database Knowledge Base

Generates accurate PostgreSQL queries grounded directly in retrieved AI-understandable
Markdown schema documentation and resolved entity context.
Directly implements the design from D:\\DB\\main\\app\\pipeline\\sql_generator.py.
"""

import re
import logging
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class GroundedSQLGenerator:
    """Generates accurate PostgreSQL SQL grounded in Markdown schema docs."""

    @classmethod
    def _get_client(cls) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=settings.deepinfra_api_key or "anonymous",
            base_url=settings.deepinfra_api_url or "https://api.deepinfra.com/v1/openai",
            timeout=60.0,
        )

    @classmethod
    async def generate_sql(
        cls,
        question: str,
        retrieved_docs: List[Dict[str, Any]],
        resolved_entities: Optional[List[Dict[str, Any]]] = None,
        intent_analysis: Optional[Any] = None,
        model: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        Generate grounded PostgreSQL SQL from schema markdown docs, dynamic intent,
        and dynamically resolved entities.
        """
        if not retrieved_docs:
            raise ValueError("No schema context was retrieved. Index schema docs before asking questions.")

        context = "\n\n---\n\n".join(
            f"Source: {d.get('source', '')}\nTitle: {d.get('title', '')}\n{d.get('text', '')}"
            for d in retrieved_docs
        )

        system_prompt = """You generate accurate PostgreSQL SELECT queries for a database question.
Rules:
1. Use only tables and columns explicitly present in the supplied schema context. NEVER invent or hallucinate table names or columns.
2. Strictly check the Columns table of each schema document. Always use the exact column names present in the schema.
   - If a table does not have a single 'name' column but has split name columns (e.g., 'firstname'/'lastname' or 'first_name'/'last_name'), project CONCAT(first, ' ', last) or the username/login column. Never invent a 'name' column if it does not appear in the Columns table.
   - Only join tables along valid foreign key paths and bridge tables present in the schema context.
3. INCLUDE DESCRIPTIVE COLUMNS: When querying records for details, status, or progress, always project meaningful human-readable columns (e.g., name, subject, title, description, status, dates, assignees) alongside IDs so the answer can be clearly understood.
4. BOOLEAN OPERATOR PRECEDENCE (MANDATORY): When combining OR conditions with AND in a WHERE clause, you MUST wrap all OR conditions in parentheses!
   Example: WHERE (col1 ILIKE '%term%' OR col2 ILIKE '%term%') AND date_col = '2026-10-16'
   Never omit parentheses around the OR group, as AND binds tighter than OR.
5. DATE HANDLING: If a specific date like 'YYYY-MM-DD' is requested, match with date casting (e.g. `col::date = 'YYYY-MM-DD'`).
6. MANDATORY LIMIT: Always include a LIMIT clause at the end of the query (e.g. `LIMIT 50` for lists, or `LIMIT 1` for single-row aggregates) to ensure safety.
7. Return only one single SQL query without Markdown code fences, commentary, or multiple statements.
8. MULTI-WORD & SEPARATOR-AGNOSTIC STRING MATCHING:
   When matching free-text, names, titles, or categories where the user enters words separated by spaces while the database may store underscores, hyphens, or camelCase (e.g., user typed 'cream reward', but database stores 'CREAM_Reward' or 'cream-reward'):
   - NEVER use strict equality like `p.name = 'cream reward'`.
   - ALWAYS split the phrase into individual words and match each word with ILIKE:
     `(column_name ILIKE '%cream%' AND column_name ILIKE '%reward%')`
     or `column_name ILIKE '%cream%reward%'`
     This guarantees matching regardless of underscores, hyphens, case, or extra internal characters!
"""

        user_content = f"Schema context:\n{context}\n\nQuestion: {question}"

        # Consolidate all resolved entities dynamically
        all_resolved: List[Dict[str, Any]] = list(resolved_entities) if resolved_entities else []
        for legacy_key in ("resolved_users", "resolved_projects"):
            if kwargs.get(legacy_key):
                for item in kwargs[legacy_key]:
                    if not any(e.get("id") == item.get("id") and e.get("table") == item.get("table") for e in all_resolved):
                        all_resolved.append(item)
        if kwargs.get("target_user"):
            tu = kwargs["target_user"]
            if not any(e.get("id") == tu.get("id") for e in all_resolved):
                all_resolved.append(tu)

        if all_resolved:
            user_content += "\n\nResolved Dimension Entities in Query:\n"
            for ent in all_resolved:
                tbl = ent.get("table", "entity")
                pk = ent.get("column", "id")
                e_id = ent.get("id")
                e_name = ent.get("name", "")
                role_str = f" [Role: '{ent['role']}']" if ent.get("role") else ""
                col_hints = ent.get("suggested_columns")
                col_str = f" -> Suggested column(s): {', '.join(col_hints)}" if col_hints else ""
                user_content += f"- Table '{tbl}' (Key: {pk}) -> ID: {e_id}, Value: '{e_name}'{role_str}{col_str}\n"

            user_content += (
                "\nCRITICAL ENTITY FILTERING INSTRUCTIONS:\n"
                "1. Filter using the resolved entity IDs directly in WHERE / JOIN clauses "
                "(e.g. `{alias}.{fk_column} = {id}`) instead of performing loose string matching on names or guessing IDs.\n"
                "2. When multiple people or entities are mentioned, map each to their respective role and column.\n"
            )

        if intent_analysis:
            intent_val = getattr(intent_analysis, "intent", None)
            intent_str = intent_val.value if hasattr(intent_val, "value") else str(intent_val or "SELECT_FILTER")
            aggs = getattr(intent_analysis, "aggregations", [])
            agg_str = ", ".join(f"{a.function.value}({a.target_concept or '*'})" for a in aggs) if aggs else "None (Select individual records)"
            user_content += (
                f"\n\nAnalyzed User Intent:\n"
                f"- Primary Intent: {intent_str}\n"
                f"- Required Aggregations: {agg_str}\n"
            )

        user_content += "\nSQL:"

        chosen_model = model or getattr(settings, "sql_generation_model", "deepseek-ai/DeepSeek-V3")
        client = cls._get_client()

        response = await client.chat.completions.create(
            model=chosen_model,
            temperature=0.0,
            max_tokens=256,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )

        sql = (response.choices[0].message.content or "").strip()
        if sql == "NEED_MORE_SCHEMA":
            raise ValueError("The retrieved schema context is insufficient to answer this question.")

        # Strip markdown fences if any
        if sql.startswith("```"):
            sql = re.sub(r"^```(?:sql|postgresql)?\s*", "", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\s*```$", "", sql).strip()

        logger.info(f"[GroundedSQLGenerator] Generated SQL: {sql}")
        return sql

    @classmethod
    async def repair_sql(
        cls,
        question: str,
        failed_sql: str,
        error_message: str,
        retrieved_docs: List[Dict[str, Any]],
        resolved_entities: Optional[List[Dict[str, Any]]] = None,
        intent_analysis: Optional[Any] = None,
        model: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        Dynamically repairs a failed SQL query using PostgreSQL's exact error message
        and the retrieved schema documentation.
        """
        context = "\n\n---\n\n".join(
            f"Source: {d.get('source', '')}\nTitle: {d.get('title', '')}\n{d.get('text', '')}"
            for d in retrieved_docs
        )

        system_prompt = """You are an expert PostgreSQL database engineer repairing a failed SQL query.
The user asked a question, but the generated SQL query failed when executed against PostgreSQL with a specific error.
Your task is to fix the SQL query so that it successfully executes and accurately answers the question.
Rules:
1. Examine the error message carefully. If a column or table does not exist, consult the supplied Schema context and find the actual columns in that table (e.g. check for split name fields like firstname/lastname or alternate column names) or adjust the join/projections. If a table stores names as separate fields (e.g. firstname/lastname), use CONCAT or login/username instead of a non-existent name column.
2. Strictly check the Columns table and types of each schema document. Always use the exact column names present in the schema. Never guess column names that are not listed.
3. MULTI-WORD & SEPARATOR-AGNOSTIC STRING MATCHING:
   When filtering text or name columns by user-entered strings that may contain spaces instead of underscores/hyphens (e.g., user typed 'cream reward', but DB has 'CREAM_Reward' or 'cream-reward'):
   - NEVER use strict equality like `p.name = 'cream reward'`.
   - ALWAYS split the phrase into individual words and match each word with ILIKE:
     `(column_name ILIKE '%cream%' AND column_name ILIKE '%reward%')`
     or `column_name ILIKE '%cream%reward%'`
4. Always include LIMIT 50 (or LIMIT 1 for aggregates) at the end.
5. Return ONLY one single corrected PostgreSQL SELECT query without Markdown code fences, commentary, or multiple statements.
"""

        user_content = (
            f"Schema context:\n{context}\n\n"
            f"Question: {question}\n\n"
            f"Failed SQL Query:\n{failed_sql}\n\n"
            f"PostgreSQL Execution Error:\n{error_message}\n\n"
        )

        all_resolved: List[Dict[str, Any]] = list(resolved_entities) if resolved_entities else []
        for legacy_key in ("resolved_users", "resolved_projects"):
            if kwargs.get(legacy_key):
                for item in kwargs[legacy_key]:
                    if not any(e.get("id") == item.get("id") and e.get("table") == item.get("table") for e in all_resolved):
                        all_resolved.append(item)

        if all_resolved:
            user_content += "\nResolved Dimension Entities:\n"
            for ent in all_resolved:
                tbl = ent.get("table", "entity")
                pk = ent.get("column", "id")
                user_content += f"- Table '{tbl}' -> {pk}: {ent.get('id')}, Name: '{ent.get('name')}'\n"

        user_content += "\nCorrected SQL:"

        chosen_model = model or getattr(settings, "sql_generation_model", "deepseek-ai/DeepSeek-V3")
        client = cls._get_client()

        response = await client.chat.completions.create(
            model=chosen_model,
            temperature=0.0,
            max_tokens=256,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )

        repaired_sql = (response.choices[0].message.content or "").strip()
        if repaired_sql.startswith("```"):
            repaired_sql = re.sub(r"^```(?:sql|postgresql)?\s*", "", repaired_sql, flags=re.IGNORECASE)
            repaired_sql = re.sub(r"\s*```$", "", repaired_sql).strip()

        logger.info(f"[GroundedSQLGenerator] Repaired SQL: {repaired_sql}")
        return repaired_sql
