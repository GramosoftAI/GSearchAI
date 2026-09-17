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
Your ONLY task is to generate a single, valid, read-only PostgreSQL SELECT query based strictly on the provided Query Plan and Sub-Schema.

STRICT CONSTRAINTS:
1. ONLY produce a SELECT query. Never generate INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, or transaction commands.
2. Use ONLY the tables and columns explicitly present in the provided <untrusted_database_schema>. Never invent tables or columns.
3. Every table join MUST use explicit INNER JOIN or LEFT JOIN with exact foreign key ON conditions. Never create Cartesian (CROSS) joins.
4. Use standard table aliases as specified in the Query Plan.
5. All queries must include a LIMIT clause (maximum 1000).
6. Select descriptive and requested columns (e.g. first/last names, cities, states, countries, dates, titles, metrics) needed to directly and informatively answer the user query.
7. MINIMAL & RELEVANT JOINS: Only join tables strictly necessary to satisfy the user query. Do NOT join 1-to-many child tables (such as employee_projects, employee_contacts, employee_addresses, attendance, payroll) unless the user query explicitly requests project, contact, address, attendance, or payroll data.
8. PREVENT DUPLICATE ROWS: When querying primary entities (like employees), do NOT cause duplicate parent rows via 1-to-many joins; use LEFT JOIN or SELECT DISTINCT when necessary.
9. GROUP BY CONSISTENCY: Whenever any aggregation function (SUM, AVG, MIN, MAX, COUNT) is present alongside non-aggregated columns in SELECT, EVERY single non-aggregated column in the SELECT clause MUST be explicitly included in the GROUP BY clause.
10. CANONICAL DURATION & NUMERIC COMPARISONS:
    - ALWAYS use integer `at_work_second` for working time comparisons, filters, SUM, and AVG (1 hr = 3600s, 6 hrs = 21600s, 8 hrs = 28800s, 10 hrs = 36000s).
      Example: "worked more than 8 hours" -> `at_work_second > 28800`.
      Example: "worked less than 6 hours" -> `at_work_second < 21600`.
    - Columns `attendance_worked_hour`, `minimum_hour`, and `attendance_overtime` are VARCHAR display strings (e.g. '09:58', '08:00'). NEVER use them with arithmetic or comparison operators (<, >, <=, >=, SUM, AVG). ALWAYS use `at_work_second` or `overtime_second` instead.
    - ALWAYS use `overtime_second` or `approved_overtime_second` for overtime calculations (e.g. "more than 10 hours overtime" -> `overtime_second > 36000`).
    - NEVER compare VARCHAR columns against numerical float or integer values.
11. POSTGRESQL SYNTAX ONLY (NO MYSQL FUNCTIONS):
    - NEVER use MySQL `IF(condition, val1, val2)`. In PostgreSQL, ALWAYS use standard SQL `CASE WHEN condition THEN val1 ELSE val2 END`.
    - For conditional aggregations / percentages (e.g. "% completing 8 hours"):
      Use: `ROUND(COUNT(CASE WHEN at_work_second >= 28800 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0), 2)`.
    - For null checks, use `column IS NULL` or `column IS NOT NULL` (never `IFNULL()` or `ISNULL()`; use standard `COALESCE()`).
12. Output ONLY the raw SQL query inside ```sql ... ``` code block. Do NOT include markdown explanations or conversational text.
"""

    @classmethod
    def build_generation_prompt(
        cls,
        user_query: str,
        plan: QueryPlanIR,
        retrieval_result: SchemaRetrievalResult,
    ) -> str:
        """Construct generation prompt containing query, plan, and retrieved sub-schema."""
        plan_json = plan.model_dump_json(indent=2)
        schema_xml = retrieval_result.untrusted_boundary_text

        prompt = f"""Generate a PostgreSQL SELECT query to answer the user query based on the plan and sub-schema below.

<user_query>
{user_query}
</user_query>

<query_plan>
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
- NEVER use the MySQL `IF()` function. In PostgreSQL, ALWAYS use standard SQL `CASE WHEN condition THEN val1 ELSE val2 END`.
- For conditional aggregations / percentages, use `ROUND(COUNT(CASE WHEN at_work_second >= 28800 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0), 2)`.
- If combining aggregates (SUM, AVG, MIN, MAX, COUNT) with scalar columns, include ALL scalar columns in GROUP BY.
- Use canonical integer `at_work_second` for working time comparisons (e.g. at_work_second < 28800 for 8 hours). Never do arithmetic on VARCHAR duration columns.
- Output ONLY the corrected SQL query inside a ```sql ... ``` block."""
        return prompt
