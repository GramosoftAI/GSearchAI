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
        target_user: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
    ) -> str:
        """
        Generate grounded PostgreSQL SQL from schema markdown docs and entity context.
        """
        if not retrieved_docs:
            raise ValueError("No schema context was retrieved. Index schema docs before asking questions.")

        context = "\n\n---\n\n".join(
            f"Source: {d.get('source', '')}\nTitle: {d.get('title', '')}\n{d.get('text', '')}"
            for d in retrieved_docs
        )

        system_prompt = """You generate accurate PostgreSQL SELECT queries for a database question.
Rules:
1. Use only tables and columns explicitly present in the supplied schema context.
2. Strictly check the Columns table of each schema document. Never assume or invent columns that are not listed.
3. INCLUDE DESCRIPTIVE COLUMNS: When querying tasks, work packages, or issues for progress, details, or status, ALWAYS include `description`, `subject`, `name`, `status_id`, `updated_at`, etc. so the actual work done can be read. Do NOT omit the `description` column!
4. BOOLEAN OPERATOR PRECEDENCE (MANDATORY): When combining OR conditions with AND in a WHERE clause, you MUST wrap all OR conditions in parentheses!
   Example: WHERE (u.firstname ILIKE '%girinath%' OR u.lastname ILIKE '%girinath%' OR u.login ILIKE '%girinath%') AND wp.updated_at::date = '2026-10-16'
   Never omit parentheses around the OR group, as AND binds tighter than OR.
5. DATE HANDLING: If a specific date like '16/10/2026' or '2026-10-16' is requested, match with date casting (e.g. `(wp.updated_at::date = '2026-10-16' OR wp.start_date = '2026-10-16' OR wp.due_date = '2026-10-16')`).
6. MANDATORY LIMIT: Always include a LIMIT clause at the end of the query (e.g. `LIMIT 50` for lists, or `LIMIT 1` for single-row aggregates) to ensure safety.
7. Return only one single SQL query without Markdown code fences, commentary, or multiple statements.
"""

        user_content = f"Schema context:\n{context}\n\nQuestion: {question}"
        if target_user:
            user_content += (
                f"\n\nResolved Target User Information:\n"
                f"- User ID: {target_user.get('id')}\n"
                f"- Name: {target_user.get('firstname', '')} {target_user.get('lastname', '')}\n"
                f"- Login: {target_user.get('login', '')}\n"
                f"- Email: {target_user.get('mail', '')}\n"
                f"IMPORTANT: Filter directly for this person using their User ID: {target_user.get('id')} "
                f"(e.g. `wp.assigned_to_id = {target_user.get('id')}` or `u.id = {target_user.get('id')}`)."
            )
        user_content += "\nSQL:"

        chosen_model = model or getattr(settings, "sql_generation_model", "deepseek-ai/DeepSeek-V4-Flash-0731")
        client = cls._get_client()

        response = await client.chat.completions.create(
            model=chosen_model,
            temperature=0.0,
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
