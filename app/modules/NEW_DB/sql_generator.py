"""Grounded SQL Generator for NEW_DB

Generates accurate PostgreSQL queries grounded directly in retrieved AI-understandable
Markdown schema documentation and resolved entity context.
Directly implements the proven design from D:\\DB\\main.
"""

import re
import logging
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class SQLGenerator:
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
        resolved_users: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
    ) -> str:
        """
        Generate grounded PostgreSQL SQL from schema Markdown docs and entity context.
        """
        if not retrieved_docs:
            raise ValueError("No schema context was retrieved. Please sync the database schema first.")

        context = "\n\n---\n\n".join(
            f"Source: {d.get('source', '')}\nTitle: {d.get('title', '')}\n{d.get('text', '')}"
            for d in retrieved_docs
        )

        system_prompt = """You generate accurate PostgreSQL SELECT queries for a database question.
Rules:
1. Use only tables and columns explicitly present in the supplied schema context.
2. Strictly check the Columns table of each schema document. Never assume or invent columns that are not listed.
   - For OpenProject/Redmine schemas:
     * User email address is stored in column `mail` (e.g. `u.mail`), NOT `email`.
     * In `public.work_packages`, user foreign keys are ONLY `author_id`, `assigned_to_id`, and `responsible_id`. There is NO `updated_by_id` or `updater_id` column.
     * When filtering work packages by update date, use `wp.updated_at::date = 'YYYY-MM-DD'`.
   Always use the exact column names present in the schema.
3. INCLUDE DESCRIPTIVE COLUMNS: When querying tasks, work packages, or issues for progress, details, or status, ALWAYS include `description`, `subject`, `status_id`, `author_id`, `assigned_to_id`, `updated_at`, `created_at`, `start_date`, `due_date`, `done_ratio`, etc. so the actual work done and assignments can be read. Do NOT omit the `description` column!
4. BOOLEAN OPERATOR PRECEDENCE (MANDATORY): When combining OR conditions with AND in a WHERE clause, you MUST wrap all OR conditions in parentheses!
   Example: WHERE (u.firstname ILIKE '%arun%' OR u.lastname ILIKE '%arun%' OR u.login ILIKE '%arun%') AND wp.updated_at::date = '2026-10-20'
   Never omit parentheses around the OR group, as AND binds tighter than OR.
5. DATE HANDLING: If a specific date like '20/10/2026' or '2026-10-20' is requested, match with date casting (e.g. `(wp.updated_at::date = '2026-10-20' OR wp.start_date = '2026-10-20' OR wp.due_date = '2026-10-20')`).
6. MANDATORY LIMIT: Always include a LIMIT clause at the end of the query (e.g. `LIMIT 50` for lists, or `LIMIT 1` for single-row aggregates) to ensure safety.
7. Return only one single SQL query without Markdown code fences, commentary, or multiple statements.
8. MULTI-ENTITY ROLE DISTINCTION: When multiple persons or entities are mentioned in the question (such as author vs. assignee), carefully respect each entity's distinct role and corresponding ID. Never conflate different people into the same column.
"""

        user_content = f"Schema context:\n{context}\n\nQuestion: {question}"

        users_list: List[Dict[str, Any]] = []
        if resolved_users:
            users_list.extend(resolved_users)
        elif target_user:
            users_list.append(target_user)

        if users_list:
            user_content += "\n\nResolved Entity & User Identifiers in Query:\n"
            for u in users_list:
                u_id = u.get("id")
                u_name = u.get("name") or f"{u.get('firstname', '')} {u.get('lastname', '')}".strip() or u.get("login", "")
                role_hint = u.get("role")
                role_str = f" [Role in query: '{role_hint}']" if role_hint else ""
                col_hints = u.get("suggested_columns")
                col_str = f" -> Suggested column(s): {', '.join(col_hints)}" if col_hints else ""
                user_content += f"- User '{u_name}' -> ID: {u_id}{role_str}{col_str}\n"

            user_content += (
                "\nCRITICAL MULTI-ENTITY AND ROLE MAPPING CONSTRAINTS:\n"
                "1. ROLE MATCHING: Map each user to the exact column matching their role in the question:\n"
                "   - 'authored by X' / 'created by X' / 'reported by X' -> filter using author_id / created_by_id = <X_id>\n"
                "   - 'assigned to Y' / 'for Y' / 'assignee Y' -> filter using assigned_to_id = <Y_id> (or user_id = <Y_id>)\n"
                "   - 'responsible Y' -> filter using responsible_id = <Y_id>\n"
                "   - Note: work_packages does NOT have updated_by_id! For updates by a person, check assigned_to_id or author_id, or filter by updated_at date.\n"
                "2. NO FALSE CONFLATION: When multiple different users are mentioned (e.g. authored by X and assigned to Y), "
                "you MUST filter with distinct IDs (e.g. `wp.author_id = <X_id> AND wp.assigned_to_id = <Y_id>`). "
                "NEVER use the same user ID for both author and assignee unless the user specifically asked for self-authored / self-assigned tasks!\n"
                "3. If multiple people are mentioned under the SAME role (e.g. 'authored by X or Y'), use `IN` or `OR` (e.g. `wp.author_id IN (<X_id>, <Y_id>)`).\n"
            )

        user_content += "\nSQL:"

        chosen_model = model or getattr(settings, "sql_generation_model", "deepseek-ai/DeepSeek-V4-Flash")
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

        # Strip markdown fences if any
        if sql.startswith("```"):
            sql = re.sub(r"^```(?:sql|postgresql)?\s*", "", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\s*```$", "", sql).strip()

        logger.info(f"[NEW_DB] Generated SQL: {sql}")
        return sql
