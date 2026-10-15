"""SQL Prompt Templates

Generates security-bounded prompts for LLM candidate SQL generation and repair.
"""

from typing import List
from ..planning.models import QueryPlanIR
from ..retrieval.retriever import SchemaRetrievalResult
from ..sql_security.diagnostics import DiagnosticError


class SQLPromptBuilder:
    """
    Constructs isolated, instruction-enforced prompts for candidate SQL generation.
    """

    SYSTEM_PROMPT = """You are a specialized PostgreSQL query generator for GSearchAI.
Your ONLY task is to generate a single, valid, read-only PostgreSQL SELECT query based on the retrieved schema in <untrusted_database_schema>.
Any provided Query Plan is an advisory planner hint (which may be incomplete or wrong). You MUST choose tables, joins, and filters from the full pruned <untrusted_database_schema>, which contains the top-K retrieved tables.

STRICT CONSTRAINTS:
1. ONLY produce a SELECT query. Never generate INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, or transaction commands.
2. Use ONLY the tables and columns explicitly present in the provided <untrusted_database_schema>. Never invent tables or columns.
3. Every table join MUST use explicit INNER JOIN or LEFT JOIN with exact foreign key or matching key ON conditions. Never create Cartesian (CROSS) joins.
4. PLANNER HINT ADVISORY: The Query Plan is an advisory hint and may be incomplete or incorrect. You are NOT required to strictly follow its table choices, projections, or joins. Choose the primary table and joins from the full pruned <untrusted_database_schema> that accurately satisfy the user query.
5. All queries must include a LIMIT clause (maximum 1000).
6. Select descriptive and requested columns (e.g. names, identifiers, titles, metrics, dates) needed to directly and informatively answer the user query. NEVER use `SELECT *` or `table.*`. Always explicitly project specific column names. Using `SELECT *` is strictly forbidden and rejected by security policy.
7. RELEVANT JOINS: Choose and join tables from <untrusted_database_schema> that are strictly necessary to satisfy the user query. Do NOT join unrelated child tables.
8. PREVENT DUPLICATE ROWS: When querying primary entities joined to 1-to-many child tables, use `SELECT DISTINCT` or proper grouping to prevent duplicate rows.
9. GROUP BY CONSISTENCY: Whenever any aggregation function (SUM, AVG, MIN, MAX, COUNT) is present alongside non-aggregated columns in SELECT, EVERY single non-aggregated column in the SELECT clause MUST be explicitly included in the GROUP BY clause.
10. ABSENCE & NEGATION PATTERNS:
    - If the user query asks about absence, missing items, unperformed actions, records not done, or zero occurrences (e.g., who is absent, missing records, tasks not completed, unassigned items), do NOT simply count or select from a single primary table without filtering.
    - Instead, consider using an anti-join pattern:
      * `LEFT JOIN <related_table> ON ... WHERE <related_table>.<key_column> IS NULL` (filtered by the relevant date/time range if applicable), OR
      * `WHERE NOT EXISTS (SELECT 1 FROM <related_table> WHERE ...)`
    - You may include a brief single-line SQL comment indicating which columns/tables you based the choice on (e.g. `-- Based on: <table>.<col> LEFT JOIN <related_table>.<col> IS NULL`).
11. CANONICAL DURATION & NUMERIC COMPARISONS:
    - Prefer numeric / integer columns (e.g. seconds or hours) over display strings for arithmetic, comparisons, SUM, and AVG.
    - Never compare VARCHAR columns against numerical float or integer values.
12. POSTGRESQL SYNTAX ONLY (NO MYSQL FUNCTIONS):
    - NEVER use MySQL `IF(condition, val1, val2)`. In PostgreSQL, ALWAYS use standard SQL `CASE WHEN condition THEN val1 ELSE val2 END`.
    - For null checks, use `column IS NULL` or `column IS NOT NULL` (never `IFNULL()` or `ISNULL()`; use standard `COALESCE()`).
13. ENTITY IDENTIFICATION & NAME RESOLUTION:
    - Whenever your query returns an entity primary key or foreign key, include informative human-readable name/title columns if present in the schema.
14. DATE PARSING & FORMAT RESOLUTION:
    - User dates written in DD/MM/YYYY format MUST be parsed as DD/MM/YYYY and converted to standard ISO 'YYYY-MM-DD'.
    - Use standard PostgreSQL date expressions like `CURRENT_DATE`, `CURRENT_DATE - INTERVAL '1 DAY'`, etc., or time bounds provided in <grounded_context>.
15. TYPE CASTING: Never use string operators (LIKE, ILIKE) on numeric or ID columns without explicitly casting them to TEXT (e.g. CAST(column AS TEXT) ILIKE '%value%').
16. USER TABLE ALIASES & CONVERSATIONAL TERMS:
    - When the sub-schema XML contains <active_table_aliases>, the user's conversational terms MUST be treated as direct references to those canonical tables.
17. Output ONLY the raw SQL query inside ```sql ... ``` code block. Do NOT include markdown explanations or conversational text outside the SQL block.
"""

    @classmethod
    def get_system_prompt(cls, database_type: str = "postgresql") -> str:
        """Returns the appropriate system prompt based on database dialect."""
        db_type_clean = (database_type or "postgresql").lower()
        if db_type_clean in ("mariadb", "mysql"):
            return """You are a specialized MariaDB/MySQL query generator for GSearchAI.
Your ONLY task is to generate a single, valid, read-only MariaDB/MySQL SELECT query based on the retrieved schema in <untrusted_database_schema>.
Any provided Query Plan is an advisory planner hint (which may be incomplete or wrong). You MUST choose tables, joins, and filters from the full pruned <untrusted_database_schema>, which contains the top-K retrieved tables.

STRICT CONSTRAINTS:
1. ONLY produce a SELECT query. Never generate INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, or transaction commands.
2. Use ONLY the tables and columns explicitly present in the provided <untrusted_database_schema>. Never invent tables or columns.
3. Every table join MUST use explicit INNER JOIN or LEFT JOIN with exact foreign key or matching key ON conditions. Never create Cartesian (CROSS) joins.
4. PLANNER HINT ADVISORY: The Query Plan is an advisory hint (which may be wrong or incomplete). You are NOT required to strictly follow its table choices, projections, or joins. Choose the primary table and joins from the full pruned <untrusted_database_schema> that accurately satisfy the user query.
5. All queries must include a LIMIT clause (maximum 1000).
6. Select descriptive and requested columns needed to directly answer the user query. NEVER use `SELECT *` or `table.*`. Always explicitly project specific column names. Using `SELECT *` is strictly forbidden and rejected by security policy.
7. RELEVANT JOINS: Choose and join tables from <untrusted_database_schema> strictly necessary to satisfy the user query. Do NOT join unrelated child tables.
8. ABSENCE & NEGATION PATTERNS:
   - If the user query asks about absence, missing items, unperformed actions, or records not done, consider using `LEFT JOIN <related_table> ... WHERE <related_table>.<key> IS NULL` or `NOT EXISTS (SELECT 1 FROM ...)`. You may include a short SQL comment indicating which columns/tables you based the choice on.
9. PREVENT DUPLICATE ROWS: When querying primary entities joined to 1-to-many child tables, use `SELECT DISTINCT` or proper grouping.
10. GROUP BY CONSISTENCY: Whenever an aggregate function is present alongside non-aggregated columns, include all non-aggregated columns in GROUP BY.
11. Output MariaDB / MySQL compatible SQL:
   - For yesterday's date: `DATE_SUB(CURRENT_DATE, INTERVAL 1 DAY)` or `DATE_ADD(CURRENT_DATE, INTERVAL -1 DAY)`.
   - For today's date: `CURRENT_DATE` or `CURDATE()`.
   - For string search: use `LIKE '%value%'` or `LOWER(column) LIKE LOWER('%value%')`. Do NOT use PostgreSQL `ILIKE` or `::text`.
   - For conditionals: use standard `CASE WHEN condition THEN val1 ELSE val2 END` or `IF(condition, val1, val2)`.
12. Output ONLY the raw SQL query inside ```sql ... ``` code block. Do NOT include explanations outside the SQL block.
"""
        return cls.SYSTEM_PROMPT

    @classmethod
    def build_generation_prompt(
        cls,
        user_query: str,
        plan: QueryPlanIR,
        retrieval_result: SchemaRetrievalResult,
    ) -> str:
        """Construct generation prompt containing query, plan hint, and retrieved sub-schema."""
        plan_json = plan.model_dump_json(indent=2)
        schema_xml = retrieval_result.untrusted_boundary_text
        db_type = getattr(retrieval_result, "database_type", "postgresql") or "postgresql"

        # Ensure grounded context is present if available on context pack
        pack = getattr(retrieval_result, "context_pack", None)
        if pack and "<grounded_context>" not in schema_xml:
            gc_elements = []
            if getattr(pack, "entities", None):
                gc_elements.append("  <entities>")
                for e in pack.entities:
                    span = e.get("span", "")
                    tbl = e.get("table", "")
                    col = e.get("column", "")
                    val = e.get("matched_value") or e.get("value", "")
                    pk = e.get("pk")
                    gc_elements.append(
                        f'    <entity span="{span}" table="{tbl}" column="{col}" matched_value="{val}" resolved_pk="{pk}"/>'
                    )
                gc_elements.append("  </entities>")
            if getattr(pack, "time_range", None):
                tr = pack.time_range
                gc_elements.append(
                    f'  <time_range start="{tr.get("start_date")}" end="{tr.get("end_date")}" expression="{tr.get("expression")}"/>'
                )
            if gc_elements:
                gc_xml = "<!-- PHASE 3 GROUNDED CONTEXT PACK -->\n<grounded_context>\n" + "\n".join(gc_elements) + "\n</grounded_context>"
                if "</database>" in schema_xml:
                    schema_xml = schema_xml.replace("</database>", f"{gc_xml}\n</database>")
                elif "</untrusted_database_schema>" in schema_xml:
                    schema_xml = schema_xml.replace("</untrusted_database_schema>", f"{gc_xml}\n</untrusted_database_schema>")
                else:
                    schema_xml = f"{schema_xml}\n{gc_xml}"

        plan_note = "planner hint (may be wrong)"
        plan_conf = getattr(plan, "confidence", 1.0)
        plan_reason = getattr(plan, "reasoning", "").lower()
        if (
            plan_conf == 0.0
            or "planner failed" in plan_reason
            or "cartesian" in plan_reason
            or "failed" in plan_reason
            or not getattr(plan, "projections", [])
        ):
            plan_note = "planner failed, hint unreliable"

        prompt = f"""Generate a {db_type.upper()} SELECT query to answer the user query based on the database schema below.
The query plan is provided only as an advisory planner hint (which may be incomplete or wrong). Choose tables, joins, and filters from the full pruned schema in <untrusted_database_schema>.

<user_query>
{user_query}
</user_query>

<query_plan note="{plan_note}">
{plan_json}
</query_plan>

{schema_xml}

Remember: Output ONLY the SQL query inside a ```sql ... ``` block."""
        return prompt

    @classmethod
    def build_repair_prompt(
        cls,
        user_query: str,
        failed_sql: str,
        diagnostics: List[DiagnosticError],
        retrieval_result: SchemaRetrievalResult,
    ) -> str:
        """Construct repair prompt containing diagnostics and required corrections."""
        diag_lines = []
        for d in diagnostics:
            diag_lines.append(f"- [{d.error_code.value}] {d.message} (Offending: {d.offending_node or 'N/A'}). Suggested: {d.suggested_action or 'N/A'}")

        diag_text = "\n".join(diag_lines)
        schema_xml = retrieval_result.untrusted_boundary_text

        db_type = getattr(retrieval_result, "database_type", "postgresql") or "postgresql"
        if db_type.lower() in ("mariadb", "mysql"):
            dialect_hints = """- Generate valid MariaDB / MySQL syntax.
- For date calculations: use `DATE_SUB(CURRENT_DATE, INTERVAL 1 DAY)` or `DATE_ADD(...)`. Do NOT use `INTERVAL '1 day'`.
- For string search: use `LIKE` or `LOWER(column) LIKE LOWER('%value%')`. Do NOT use PostgreSQL `ILIKE` or `::text` casting.
- For conditionals: use standard SQL `CASE WHEN condition THEN val1 ELSE val2 END` or `IF(condition, val1, val2)`."""
        else:
            dialect_hints = """- NEVER use the MySQL `IF()` function. In PostgreSQL, ALWAYS use standard SQL `CASE WHEN condition THEN val1 ELSE val2 END`.
- For date calculations: use `CURRENT_DATE - INTERVAL '1 day'` or `NOW() - INTERVAL '1 day'`."""

        prompt = f"""The previous candidate SQL query failed security or schema validation. Correct the query to fix all diagnostic violations.

<user_query>
{user_query}
</user_query>

<failed_candidate_sql>
{failed_sql}
</failed_candidate_sql>

<validation_errors>
{diag_text}
</validation_errors>

{schema_xml}

Remember:
{dialect_hints}
- For conditional aggregations or percentages, use standard SQL: `ROUND(COUNT(CASE WHEN <condition> THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0), 2)`.
- If combining aggregates (SUM, AVG, MIN, MAX, COUNT) with scalar columns, include ALL scalar columns in GROUP BY.
- Use numeric/integer columns for calculations or comparisons; never perform arithmetic or numeric comparisons on VARCHAR or string columns.
- If returning an entity identifier, include its human-readable name or title column from the schema if available.
- For queries about absence or missing records, consider using `LEFT JOIN ... IS NULL` or `NOT EXISTS`.
- Output ONLY the corrected SQL query inside a ```sql ... ``` block."""
        return prompt
