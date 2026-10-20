"""AST Security Validator for NEW_DB

Uses sqlglot to parse the generated SQL Abstract Syntax Tree (AST),
guaranteeing strictly read-only SELECT execution, blocking injection,
and enforcing mandatory result limits.
"""

import re
import logging
import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)

FORBIDDEN_COMMANDS = {
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter,
    exp.Create, exp.Command,
}


class SQLValidator:
    """Validates generated SQL for read-only safety using sqlglot AST."""

    @classmethod
    def validate_and_sanitize(cls, sql: str, default_limit: int = 50) -> str:
        """
        Validates that SQL is strictly a single read-only SELECT statement.
        Automatically injects LIMIT if omitted.
        """
        clean_sql = sql.strip().rstrip(";")

        # 1. Regex check for obvious destructive commands
        hostile = re.search(
            r"\b(drop\s+table|delete\s+from|update\s+\w+\s+set|truncate\s+table|alter\s+table|grant\s+all|revoke\s+all)\b",
            clean_sql,
            re.IGNORECASE,
        )
        if hostile:
            raise ValueError(f"Security Policy Rejection: Destructive command detected: {hostile.group(0)}")

        # 2. Parse AST using sqlglot
        try:
            expressions = sqlglot.parse(clean_sql, read="postgres")
        except Exception as e:
            raise ValueError(f"Invalid SQL Syntax: {e}")

        if not expressions:
            raise ValueError("Empty SQL query")

        if len(expressions) > 1:
            raise ValueError("Multi-statement SQL queries are not permitted")

        ast = expressions[0]

        # 3. Verify it is a SELECT statement
        if not isinstance(ast, exp.Select):
            raise ValueError(f"Security Policy Rejection: Only SELECT statements are permitted, got {type(ast).__name__}")

        # Check for any forbidden inner expressions
        for forbidden in FORBIDDEN_COMMANDS:
            if ast.find(forbidden):
                raise ValueError(f"Security Policy Rejection: Forbidden command detected: {forbidden.__name__}")

        # 4. Check system catalog access
        for table_expr in ast.find_all(exp.Table):
            t_name = table_expr.name.lower()
            if t_name in ("pg_shadow", "pg_authid", "pg_user", "information_schema"):
                raise ValueError(f"Security Policy Rejection: Access to system catalog '{t_name}' is forbidden")

        # 5. Enforce LIMIT
        has_limit = ast.args.get("limit") is not None
        if not has_limit and "LIMIT" not in clean_sql.upper():
            limit_val = 1 if "count(" in clean_sql.lower() else default_limit
            clean_sql = f"{clean_sql} LIMIT {limit_val}"

        return clean_sql
