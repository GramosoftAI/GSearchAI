"""SQL AST Parser using sqlglot

Parses raw candidate SQL strings into PostgreSQL AST expressions.
Rejects multi-statement payloads and syntax errors.
"""

from typing import List, Optional
import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from ..exceptions import SQLSyntaxError


class SQLASTParser:
    """
    PostgreSQL dialect SQL parser using sqlglot.
    """

    @classmethod
    def parse_sql(cls, sql_text: str) -> exp.Expression:
        """
        Parse a single PostgreSQL SQL statement into a sqlglot Expression AST.
        
        Raises:
            SQLSyntaxError if parsing fails or multiple statements are supplied.
        """
        if not sql_text or not sql_text.strip():
            raise SQLSyntaxError("SQL query string is empty")

        clean_sql = sql_text.strip()
        # Remove trailing semicolon if present
        if clean_sql.endswith(";"):
            clean_sql = clean_sql[:-1].strip()

        try:
            expressions = sqlglot.parse(clean_sql, read="postgres")
        except (ParseError, TokenError, Exception) as e:
            raise SQLSyntaxError(f"SQL Syntax Error: {str(e)}")

        if not expressions:
            raise SQLSyntaxError("No valid SQL expression could be parsed from input")

        if len(expressions) > 1:
            raise SQLSyntaxError(
                f"Multi-statement SQL execution is strictly forbidden: found {len(expressions)} statements"
            )

        return expressions[0]

    @classmethod
    def to_sql(cls, expression: exp.Expression, pretty: bool = False) -> str:
        """Transpile or format an AST back to PostgreSQL SQL string."""
        return expression.sql(dialect="postgres", pretty=pretty)
