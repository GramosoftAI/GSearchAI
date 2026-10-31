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
    def _get_client(cls, timeout: Optional[float] = None) -> AsyncOpenAI:
        req_timeout = timeout or getattr(settings, "sql_llm_timeout_seconds", 90.0)
        return AsyncOpenAI(
            api_key=settings.deepinfra_api_key or "anonymous",
            base_url=settings.deepinfra_api_url or "https://api.deepinfra.com/v1/openai",
            timeout=req_timeout,
            max_retries=2,
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
   - Only join tables along valid foreign key paths and bridge tables present in the schema context. NEVER invent direct joins between unrelated tables (e.g., `types.id = projects.id`) or invent columns like `p.creator_id`. Always join through intermediate fact/transaction tables (e.g. `work_packages`) that contain foreign keys to both tables.
3. INCLUDE DESCRIPTIVE COLUMNS: When querying records for details, status, or progress, always project meaningful human-readable columns (e.g., name, subject, title, description, status, dates, assignees) alongside IDs so the answer can be clearly understood.
4. BOOLEAN OPERATOR PRECEDENCE (MANDATORY): When combining OR conditions with AND in a WHERE clause, you MUST wrap all OR conditions in parentheses!
   Example: WHERE (col1 ILIKE '%term%' OR col2 ILIKE '%term%') AND date_col = '2026-10-16'
   Never omit parentheses around the OR group, as AND binds tighter than OR.
5. DATE HANDLING: If a specific date like 'YYYY-MM-DD' is requested, match with date casting (e.g. `col::date = 'YYYY-MM-DD'`).
6. MANDATORY LIMIT: Always include a LIMIT clause at the end of the query (e.g. `LIMIT 50` for lists, or `LIMIT 1` for single-row aggregates) to ensure safety.
7. Return only one single SQL query without Markdown code fences, commentary, or multiple statements.
8. SINGLE TABLE SUFFICIENCY & MINIMAL JOINS (CRITICAL):
   - Check if the requested projection attribute (e.g. COUNT(*), amount, code, status, price) AND an entity/filter column (e.g. status, name, title) both exist directly on one of the candidate tables.
   - If a candidate table already has the required columns (e.g. table `ipa_budget_clarification` has `status` and can directly answer `COUNT(*)` with `WHERE status = 'pending'`), query that table DIRECTLY!
   - NEVER join additional tables (such as `ipa_budget`, `ipa_auditlog`, or master tables) unless the question explicitly asks for attributes from those other tables! Unnecessary joins filter out valid rows and produce 0 results.
   - Only perform JOINs when the requested information is genuinely split across multiple tables.
9. DYNAMIC MULTI-WORD & SEPARATOR-AGNOSTIC STRING MATCHING:
   When matching any free-text, entity names, product items, brands, titles, categories, or literal phrases (such as 'cream & IPA', 'red wine', person names, or item codes):
   - NEVER fragment a multi-word literal across multiple different columns using AND (e.g. NEVER do `col1 ILIKE '%part1%' AND col2 ILIKE '%part2%' AND col3 ILIKE '%part3%'`).
   - Match the target string against a single candidate column using ILIKE:
     * For arbitrary multi-word or separated phrases: `(col ILIKE '%word1%' AND col ILIKE '%word2%')` or `col ILIKE '%word1%word2%'` ON THE SAME COLUMN.
     * Or test across alternative candidate columns using OR: `(col_a ILIKE '%literal%' OR col_b ILIKE '%literal%')`.
   - If matching split name fields (like `firstname` and `lastname`), match against the concatenated whole:
     `CONCAT_WS(' ', col_first, col_last) ILIKE '%full literal%'` or `(col_first ILIKE '%word1%' AND col_last ILIKE '%word2%')`.
   - This ensures dynamic and robust matching for any names, products, items, or descriptions regardless of spacing, special characters (&, -), or casing.
10. "WORKING ON / UNDER" vs "MEMBERS OF" A PROJECT:
   - When the user asks who is "working on", "working under", "doing work on", or "assigned to" a project/entity, join the active tasks/work items table (e.g., `work_packages`, `tasks`, `issues`, `tickets` via `assigned_to_id` or `author_id`) where actual work assignments reside.
   - Use the membership roster table (e.g., `members`) only when the user specifically asks for "members", "membership list", or "team permissions".
11. MANDATORY DISTINCT & ORDER BY IN POSTGRESQL:
   - When joining across one-to-many relationship tables, use `SELECT DISTINCT` to prevent duplicate rows.
   - CRITICAL POSTGRESQL SYNTAX RULE: When using `SELECT DISTINCT`, every expression in `ORDER BY` MUST appear in the `SELECT` list.
     For example, `SELECT DISTINCT col::date ... ORDER BY col::date DESC` is valid; `SELECT DISTINCT col::date ... ORDER BY col DESC` will throw a syntax error.
     If you only need the latest or earliest single record with `LIMIT 1`, write: `SELECT col::date ... ORDER BY col DESC LIMIT 1` without `DISTINCT`.
11. SPLIT NAME COLUMNS:
   - Check the columns of the `users` table: if it contains `firstname` and `lastname` instead of `name`, match using `(u.firstname ILIKE '%...%' OR u.lastname ILIKE '%...%')` and select using `CONCAT(u.firstname, ' ', u.lastname)`. NEVER reference `u.name` unless `name` actually exists in its schema!
12. POLYMORPHIC AND DUAL ASSOCIATIONS (`entity_type` / `entity_id`):
   - Tables tracking activities, timesheets, or logs (e.g. `time_entries`, `journals`, `activities`) often support polymorphic links where direct foreign keys (like `work_package_id`) may be NULL in favor of `(entity_type = 'WorkPackage' AND entity_id = wp.id)` or `(journable_type = 'WorkPackage' AND journable_id = wp.id)`.
   - When joining between work items and time/activity logs, accommodate both columns:
     `ON (te.work_package_id = wp.id OR (te.entity_type = 'WorkPackage' AND te.entity_id = wp.id))`
   - When the question asks for primary entities (e.g. "Who updated tasks...") with their logged hours, use `LEFT JOIN` for optional time logs and check the direct `project_id` on the logged table (`te.project_id = p.id`).
13. COLUMN ALIAS RESOLUTION (CRITICAL):
   - If a "CRITICAL COLUMN ALIAS RESOLUTION" section is provided below, it lists user-defined alternative names (aliases) for database columns.
   - These alias tokens are COLUMN REFERENCES, NOT filter values. NEVER use an alias token (e.g. 'cape_stage') as a WHERE clause value.
   - Map the alias to the actual column name and extract the real filter value from the rest of the question.
   - Example: User says "how many completed in cape_stage column" where 'cape_stage' is an alias for column 'stage'.
     CORRECT: WHERE stage ILIKE 'completed'
     WRONG:  WHERE stage = 'cape_stage'
14. ENTITY NOUNS VS STATUS VALUES (CRITICAL):
   - In questions like "how many request pending" or "count open tasks", distinguish the entity concept ("request", "task", "budget") from the state/status value ("pending", "open", "active").
   - The status column values are typically single states like `'pending'`, `'open'`, `'approved'`, `'closed'`, or `'completed'`.
   - NEVER combine the entity noun with the status value into the filter (e.g. NEVER do `WHERE status = 'request pending'` or `WHERE status = 'task open'`).
   - Use the exact identified filter from the Structured Schema-Aware Interpretation (e.g., `WHERE status ILIKE 'pending'`).
15. MANDATORY CASE-INSENSITIVE STRING MATCHING (USE ILIKE ONLY):
   - In PostgreSQL, `=` is strictly case-sensitive. If the database stores lowercase (e.g. 'submitted' or 'capex'), but the query uses 'Submitted' or 'CAPEX', `= '...'` fails and returns 0 rows!
   - You MUST ALWAYS use `ILIKE` for all string/text/varchar value checks, statuses, categories, stages, types, names, codes, and literal filters.
   - NEVER use `=` for string/text/varchar columns! ALWAYS use `ILIKE`!
     * CORRECT: WHERE stage ILIKE 'Submitted' AND capex_revex ILIKE 'CAPEX' AND finance_year ILIKE '2026'
     * WRONG:   WHERE stage = 'Submitted' AND capex_revex = 'CAPEX' AND finance_year = '2026'
   - For numeric IDs (e.g. `id = 123`) and booleans (`active = TRUE`), use `=`. But for ALL text/character/enum values, use ONLY `ILIKE`.
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
                "1. When dimension entities are resolved above (e.g. Table 'projects' ID 95, Table 'types' ID 7, Table 'users' ID 104):\n"
                "   - Filter using the resolved entity IDs on the fact table foreign key columns (e.g. `work_packages.project_id = 95`, `work_packages.type_id = 7`, `work_packages.author_id = 104`) or join the dimension table on its primary key.\n"
                "   - DO NOT filter project names or type names inside `work_packages.subject`! The project name belongs to `projects.name` (or `project_id`), NOT the work package title/subject.\n"
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

        # Consume column alias mappings and execution strategy
        execution_strategy = kwargs.get("execution_strategy")

        # Consume structured schema-aware interpretation if provided
        schema_interpretation = kwargs.get("schema_interpretation")
        if schema_interpretation:
            user_content += "\n\nStructured Schema-Aware Interpretation:\n"
            if hasattr(schema_interpretation, "rephrased_question") and schema_interpretation.rephrased_question:
                user_content += f"- Grounded Rephrasing: {schema_interpretation.rephrased_question}\n"
            if hasattr(schema_interpretation, "filters") and schema_interpretation.filters:
                filter_descs = [
                    f"{f.column} {f.operator} {f.expression}" + (" [EXCLUDED/NEGATED]" if f.is_negated else "")
                    for f in schema_interpretation.filters
                ]
                user_content += f"- Identified Filters: {', '.join(filter_descs)}\n"
            # Only include relationships if user explicitly needs attributes across tables or did not select tables directly
            if hasattr(schema_interpretation, "relationships_required") and schema_interpretation.relationships_required:
                if execution_strategy != "union" and len(retrieved_docs) > 1 and not (kwargs.get("selected_tables") and len(kwargs.get("selected_tables")) == 1):
                    rel_descs = [f"{r.source_table} <-> {r.target_table} ({r.join_type} JOIN on {r.join_columns})" for r in schema_interpretation.relationships_required]
                    user_content += f"- Available Join Paths (use ONLY if needed across multiple tables): {'; '.join(rel_descs)}\n"

        target_tables = kwargs.get("selected_tables") or [d.get("table_name") for d in retrieved_docs if d.get("table_name")]
        if execution_strategy == "union":
            tbl_list_str = ", ".join(f"'{t}'" for t in target_tables if t)
            user_content += "\n\nCRITICAL MANDATORY INSTRUCTION - UNION ALL REQUIRED:\n"
            user_content += (
                f"The user explicitly selected multiple tables and chose the 'UNION' execution strategy.\n"
                f"Target tables: [{tbl_list_str}].\n"
                "You MUST generate a single SQL query that uses UNION ALL to combine the results across ALL of these target tables.\n"
                "DO NOT query only one table! You MUST write a query of the form:\n"
                "  SELECT 'table_1' AS source_table, COUNT(*) AS count FROM table_1 WHERE <condition>\n"
                "  UNION ALL\n"
                "  SELECT 'table_2' AS source_table, COUNT(*) AS count FROM table_2 WHERE <condition>\n"
                "All branches of the UNION ALL must have identical column names and compatible types.\n"
                "Failure to include all target tables in the UNION ALL will violate the user's explicit request.\n"
            )

        column_alias_mappings = kwargs.get("column_alias_mappings")
        if column_alias_mappings:
            user_content += "\n\nCRITICAL COLUMN ALIAS RESOLUTION:\n"
            user_content += (
                "The following tokens in the user's question are ALTERNATIVE NAMES (aliases) for database columns.\n"
                "They are NOT filter values. You MUST:\n"
                "1. Replace each alias with the actual column name in the SQL query.\n"
                "2. Extract the actual filter/condition value from the OTHER words in the question.\n"
                "3. NEVER use the alias token as a WHERE clause value.\n\n"
            )
            for mapping in column_alias_mappings:
                alias = mapping.get("alias", "")
                table = mapping.get("table", "")
                column = mapping.get("column", "")
                user_content += (
                    f"- '{alias}' is an alternative name for column '{column}' in table '{table}'.\n"
                    f"  In the SQL, use '{table}.{column}' (NOT '{alias}' as a value).\n"
                    f"  The filter value should come from the rest of the question (e.g., if user says "
                    f"'how many completed in {alias}', the SQL should be: WHERE {column} ILIKE 'completed').\n"
                )


        user_content += "\nSQL:"

        chosen_model = model or getattr(settings, "sql_generation_model", "deepseek-ai/DeepSeek-V3")
        client = cls._get_client()

        try:
            response = await client.chat.completions.create(
                model=chosen_model,
                temperature=0.0,
                max_tokens=256,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            )
        except Exception as llm_err:
            fallback_model = getattr(settings, "sql_generation_model_fallback", "meta-llama/Llama-3.3-70B-Instruct-Turbo")
            if "timeout" in str(llm_err).lower() and fallback_model != chosen_model:
                logger.warning(
                    f"[GroundedSQLGenerator] Primary SQL model '{chosen_model}' timed out ({llm_err}). "
                    f"Failing over to fallback model: '{fallback_model}'..."
                )
                response = await client.chat.completions.create(
                    model=fallback_model,
                    temperature=0.0,
                    max_tokens=256,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                )
            else:
                raise

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
3. DYNAMIC MULTI-WORD & SEPARATOR-AGNOSTIC STRING MATCHING:
   When matching free-text, entity names, products, items, titles, or categories:
   - NEVER split a multi-word entity or literal into conjoined AND conditions across multiple different columns.
   - Match the target string against a single candidate column with ILIKE: `(column_name ILIKE '%word1%' AND column_name ILIKE '%word2%')` or `column_name ILIKE '%word1%word2%'`.
   - Or test across alternative candidate columns with OR: `(col_a ILIKE '%term%' OR col_b ILIKE '%term%')`.
   - If a table has split names, match against `CONCAT_WS(' ', first, last) ILIKE '%full term%'`.
4. SINGLE TABLE SUFFICIENCY:
   - If the requested projection column and the filter column both exist directly on one table, remove unnecessary joins and query that table directly.
5. "WORKING ON / UNDER" vs "MEMBERS OF" A PROJECT:
   - When the user asks who is "working on", "working under", "doing work on", or "assigned to" a project/entity, join the active tasks/work items table (e.g., `work_packages`, `tasks`, `issues`, `tickets` via `assigned_to_id` or `author_id`) where actual work assignments reside.
   - Use the membership roster table (e.g., `members`) only when the user specifically asks for "members", "membership list", or "team permissions".
5. POSTGRESQL SELECT DISTINCT & ORDER BY RULE:
   - In PostgreSQL, when using `SELECT DISTINCT`, every expression in `ORDER BY` MUST appear in the `SELECT` list.
     For example: `SELECT DISTINCT col::date ... ORDER BY col::date DESC` is valid; `SELECT DISTINCT col::date ... ORDER BY col DESC` will throw a syntax error.
     If selecting the single latest or earliest record with `LIMIT 1`, use `SELECT col::date ... ORDER BY col DESC LIMIT 1` without `DISTINCT`.
6. POLYMORPHIC AND DUAL ASSOCIATIONS (`entity_type` / `entity_id`):
   - Tables tracking activities, timesheets, or logs (e.g. `time_entries`, `journals`) frequently store parent object links in `(entity_type = 'WorkPackage' AND entity_id = wp.id)` where direct foreign keys like `work_package_id` can be NULL. Check both columns:
     `ON (te.work_package_id = wp.id OR (te.entity_type = 'WorkPackage' AND te.entity_id = wp.id))`
   - Also prefer joining `projects` via `te.project_id = p.id` and using `LEFT JOIN` for optional time logs.
7. Always include LIMIT 50 (or LIMIT 1 for aggregates) at the end.
8. MANDATORY CASE-INSENSITIVE STRING MATCHING (USE ILIKE ONLY):
   - In PostgreSQL, `=` is strictly case-sensitive. Always use `ILIKE` for all string/text/varchar value checks, statuses, categories, stages, types, names, codes, and literal filters (e.g. `stage ILIKE 'Submitted'`, `capex_revex ILIKE 'CAPEX'`). NEVER use `=` for string/text values!
9. Return ONLY one single corrected PostgreSQL SELECT query without Markdown code fences, commentary, or multiple statements.
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
                e_id = ent.get("id")
                e_name = ent.get("name", "")
                role_str = f" [Role: '{ent['role']}']" if ent.get("role") else ""
                col_hints = ent.get("suggested_columns")
                col_str = f" -> Suggested column(s): {', '.join(col_hints)}" if col_hints else ""
                user_content += f"- Table '{tbl}' (Key: {pk}) -> ID: {e_id}, Value: '{e_name}'{role_str}{col_str}\n"

            user_content += (
                "\nCRITICAL ENTITY FILTERING INSTRUCTIONS:\n"
                "1. When dimension entities are resolved above (e.g. Table 'projects' ID 95, Table 'types' ID 7, Table 'users' ID 104):\n"
                "   - Filter using the resolved entity IDs on the fact table foreign key columns (e.g. `work_packages.project_id = 95`, `work_packages.type_id = 7`, `work_packages.author_id = 104`) or join the dimension table on its primary key.\n"
                "   - DO NOT filter project names or type names inside `work_packages.subject`! The project name belongs to `projects.name` (or `project_id`), NOT the work package title/subject.\n"
                "2. When multiple people or entities are mentioned, map each to their respective role and column.\n"
            )

        # Column alias context for repair as well
        column_alias_mappings = kwargs.get("column_alias_mappings")
        if column_alias_mappings:
            user_content += "\n\nCRITICAL COLUMN ALIAS RESOLUTION:\n"
            user_content += (
                "The following tokens in the user's question are ALTERNATIVE NAMES (aliases) for database columns.\n"
                "They are NOT filter values. You MUST:\n"
                "1. Replace each alias with the actual column name in the SQL query.\n"
                "2. Extract the actual filter/condition value from the OTHER words in the question.\n"
                "3. NEVER use the alias token as a WHERE clause value.\n\n"
            )
            for mapping in column_alias_mappings:
                alias = mapping.get("alias", "")
                table = mapping.get("table", "")
                column = mapping.get("column", "")
                user_content += (
                    f"- '{alias}' is an alternative name for column '{column}' in table '{table}'.\n"
                    f"  In the SQL, use '{table}.{column}' (NOT '{alias}' as a value).\n"
                )

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
