"""SQL Parameterizer

Separates SQL query structure from literal values into parameterized SQL and binding parameters.
Protects against SQL injection and prepares queries for safe parameterized execution in Phase 2C.
"""

from typing import Any, Dict, Tuple
from pydantic import BaseModel, ConfigDict, Field
from sqlglot import exp
from ..sql_parser.ast_parser import SQLASTParser


class ParameterizedSQL(BaseModel):
    """Result of SQL parameterization containing structural template and parameter dict."""
    model_config = ConfigDict(extra="forbid")

    parameterized_sql: str = Field(..., description="SQL string with :p1, :p2 parameter placeholders")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Dictionary of parameter name -> literal value")
    raw_sql: str = Field(..., description="Original raw SQL string")


class SQLParameterizer:
    """
    Transforms AST literals in WHERE/HAVING clauses into named parameters.
    """

    @classmethod
    def parameterize(cls, root: exp.Expression) -> ParameterizedSQL:
        """
        Extract literal numbers and strings from AST into a parameter map.
        """
        raw_sql = SQLASTParser.to_sql(root)
        param_ast = root.copy()
        parameters: Dict[str, Any] = {}
        param_counter = 1

        # Parameterize literal expressions in WHERE clause
        for where_expr in param_ast.find_all(exp.Where):
            for literal in list(where_expr.find_all(exp.Literal)):
                # Do not parameterize LIMIT / OFFSET / INTERVAL literals
                if literal.find_ancestor(exp.Limit) or literal.find_ancestor(exp.Offset) or literal.find_ancestor(exp.Interval):
                    continue

                param_name = f"p{param_counter}"
                param_counter += 1

                # Extract typed value
                if literal.is_number:
                    val = float(literal.this) if "." in literal.this else int(literal.this)
                elif literal.is_string:
                    val = literal.this
                else:
                    val = literal.this

                parameters[param_name] = val
                # Replace with placeholder :p1
                var_expr = exp.var(f":{param_name}")
                literal.replace(var_expr)

        param_sql = SQLASTParser.to_sql(param_ast)

        return ParameterizedSQL(
            parameterized_sql=param_sql,
            parameters=parameters,
            raw_sql=raw_sql,
        )
