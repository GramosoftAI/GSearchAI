"""Grounded SQL Validator using SQLGlot

Enforces strict single-statement, read-only SELECT/CTE safety invariants
without blocking legitimate analytical functions.
Directly implements the validator from D:\\DB\\main\\app\\pipeline\\sql_validator.py.
"""

import logging
import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)

ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)

BLOCKED_FUNCTIONS = {
    "PG_READ_FILE",
    "PG_READ_BINARY_FILE",
    "PG_LS_DIR",
    "PG_SLEEP",
    "PG_TERMINATE_BACKEND",
    "PG_CANCEL_BACKEND",
    "LO_IMPORT",
    "DBLINK",
}

FORBIDDEN_STATEMENTS = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,
    exp.Copy,
    exp.Merge,
    exp.TruncateTable,
    exp.Grant,
    exp.Revoke,
)


class GroundedSQLValidator:
    """Validates generated SQL against read-only security invariants using SQLGlot."""

    @classmethod
    def validate_readonly_sql(cls, sql: str) -> str:
        """
        Validate that SQL is a single, safe, read-only SELECT or CTE query.
        Raises ValueError if invalid or unsafe.
        """
        cleaned = sql.strip()
        if not cleaned:
            raise ValueError("The model returned an empty SQL query.")

        if cleaned.endswith(";"):
            cleaned = cleaned[:-1].rstrip()

        if ";" in cleaned:
            raise ValueError("Multiple SQL statements are not permitted.")

        try:
            statements = sqlglot.parse(cleaned, read="postgres")
        except Exception as exc:
            raise ValueError(f"Could not parse generated SQL safely: {exc}") from exc

        if len(statements) != 1 or statements[0] is None:
            raise ValueError("Only one SQL statement is allowed.")

        tree = statements[0]
        if not isinstance(tree, ALLOWED_ROOTS):
            raise ValueError(f"Only SELECT or CTE queries are allowed, got '{type(tree).__name__}'.")

        if any(tree.find(node_type) for node_type in FORBIDDEN_STATEMENTS):
            raise ValueError("The query contains a disallowed modifying operation (DML/DDL).")

        for func in tree.find_all(exp.Func):
            name = (getattr(func, "name", "") or func.sql_name() or "").upper()
            if name in BLOCKED_FUNCTIONS:
                raise ValueError(f"Database function '{name}' is forbidden for security policy.")

        return cleaned
