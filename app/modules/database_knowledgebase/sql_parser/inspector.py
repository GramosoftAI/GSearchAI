"""AST Inspector for PostgreSQL Expressions

Recursively extracts structured metadata from a parsed sqlglot AST:
- Referenced tables and schemas
- Referenced columns and qualifications
- Joins and ON predicates
- Functions invoked
- Subquery nesting depth
- CTE and UNION complexity
- LIMIT / OFFSET specifications
"""

from typing import Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, ConfigDict, Field
from sqlglot import exp


class InspectedTable(BaseModel):
    """Table reference extracted from AST."""
    model_config = ConfigDict(extra="forbid")

    schema_name: str = "public"
    table_name: str
    alias: Optional[str] = None


class InspectedColumn(BaseModel):
    """Column reference extracted from AST."""
    model_config = ConfigDict(extra="forbid")

    column_name: str
    table_qualifier: Optional[str] = None  # Table name or alias qualifier


class InspectedJoin(BaseModel):
    """Join construct extracted from AST."""
    model_config = ConfigDict(extra="forbid")

    join_type: str
    table_name: str
    schema_name: str = "public"
    alias: Optional[str] = None
    has_on_condition: bool = False


class InspectedFunction(BaseModel):
    """Function call extracted from AST."""
    model_config = ConfigDict(extra="forbid")

    function_name: str
    is_aggregate: bool = False


class ASTInspectionReport(BaseModel):
    """Comprehensive inspection report of an AST."""
    model_config = ConfigDict(extra="forbid")

    is_select_root: bool
    statement_type: str
    tables: List[InspectedTable] = Field(default_factory=list)
    columns: List[InspectedColumn] = Field(default_factory=list)
    joins: List[InspectedJoin] = Field(default_factory=list)
    functions: List[InspectedFunction] = Field(default_factory=list)
    table_aliases: Dict[str, InspectedTable] = Field(default_factory=dict)
    subquery_depth: int = 0
    cte_count: int = 0
    union_count: int = 0
    limit_value: Optional[int] = None
    has_limit: bool = False
    has_cartesian_join: bool = False
    projection_aliases: List[str] = Field(default_factory=list)


class ASTInspector:
    """
    Performs deep recursive AST analysis on sqlglot PostgreSQL expressions.
    """

    @classmethod
    def inspect(cls, root: exp.Expression) -> ASTInspectionReport:
        """
        Inspect complete AST and return structured ASTInspectionReport.
        """
        is_select = isinstance(root, (exp.Select, exp.Union))
        stmt_type = root.key.upper() if hasattr(root, "key") else type(root).__name__

        tables: List[InspectedTable] = []
        table_aliases: Dict[str, InspectedTable] = {}
        columns: List[InspectedColumn] = []
        joins: List[InspectedJoin] = []
        functions: List[InspectedFunction] = []

        # 1. Extract Tables and Aliases
        for tbl_expr in root.find_all(exp.Table):
            t_name = tbl_expr.name
            s_name = tbl_expr.db if tbl_expr.db else "public"
            alias = tbl_expr.alias if tbl_expr.alias else None

            inspected_t = InspectedTable(
                schema_name=s_name,
                table_name=t_name,
                alias=alias,
            )
            tables.append(inspected_t)

            if alias:
                table_aliases[alias] = inspected_t
            table_aliases[t_name] = inspected_t

        # 2. Extract Columns
        for col_expr in root.find_all(exp.Column):
            c_name = col_expr.name
            t_qualifier = col_expr.table if col_expr.table else None

            columns.append(
                InspectedColumn(
                    column_name=c_name,
                    table_qualifier=t_qualifier,
                )
            )

        # 3. Extract Joins & Check for ON condition
        has_cartesian = False
        for join_expr in root.find_all(exp.Join):
            j_tbl = join_expr.this
            t_name = j_tbl.name if isinstance(j_tbl, exp.Table) else str(j_tbl)
            s_name = j_tbl.db if isinstance(j_tbl, exp.Table) and j_tbl.db else "public"
            alias = j_tbl.alias if isinstance(j_tbl, exp.Table) and j_tbl.alias else None

            on_clause = join_expr.args.get("on")
            has_on = on_clause is not None

            # CROSS JOIN or explicit Join without ON is cartesian
            j_kind = join_expr.kind or "INNER"
            if j_kind.upper() == "CROSS" or not has_on:
                has_cartesian = True

            joins.append(
                InspectedJoin(
                    join_type=j_kind.upper(),
                    table_name=t_name,
                    schema_name=s_name,
                    alias=alias,
                    has_on_condition=has_on,
                )
            )

        # Check for comma joins in FROM (e.g. FROM customers, orders)
        for from_expr in root.find_all(exp.From):
            if len(from_expr.expressions) > 1:
                # Comma join without explicit join ON
                has_cartesian = True

        # 4. Extract Functions (Exclude binary/connector operators like AND, OR, arithmetic)
        for func_expr in root.find_all(exp.Func):
            if isinstance(func_expr, (exp.Binary, exp.Connector)):
                continue
            f_name = func_expr.sql_name().upper() if hasattr(func_expr, "sql_name") else type(func_expr).__name__.upper()
            is_agg = isinstance(func_expr, (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max))

            functions.append(
                InspectedFunction(
                    function_name=f_name,
                    is_aggregate=is_agg,
                )
            )

        for anon_func in root.find_all(exp.Anonymous):
            f_name = anon_func.name.upper()
            functions.append(
                InspectedFunction(
                    function_name=f_name,
                    is_aggregate=False,
                )
            )

        # 5. Measure Subquery Depth
        def get_select_depth(node: exp.Expression, current_depth: int = 0) -> int:
            max_d = current_depth
            for child in node.args.values():
                if isinstance(child, list):
                    for item in child:
                        if isinstance(item, exp.Expression):
                            if isinstance(item, exp.Select):
                                max_d = max(max_d, get_select_depth(item, current_depth + 1))
                            else:
                                max_d = max(max_d, get_select_depth(item, current_depth))
                elif isinstance(child, exp.Expression):
                    if isinstance(child, exp.Select):
                        max_d = max(max_d, get_select_depth(child, current_depth + 1))
                    else:
                        max_d = max(max_d, get_select_depth(child, current_depth))
            return max_d

        subquery_depth = get_select_depth(root, 0)

        # 6. CTE and UNION counts
        cte_count = len(list(root.find_all(exp.CTE)))
        union_count = len(list(root.find_all(exp.Union)))

        # 7. Extract LIMIT
        has_limit = False
        limit_val = None
        for limit_expr in root.find_all(exp.Limit):
            has_limit = True
            try:
                limit_val = int(limit_expr.expression.this)
            except Exception:
                limit_val = None

        # 8. Extract Projection Aliases (SELECT ... AS alias)
        projection_aliases = []
        for alias_expr in root.find_all(exp.Alias):
            if alias_expr.alias:
                projection_aliases.append(alias_expr.alias)

        return ASTInspectionReport(
            is_select_root=is_select,
            statement_type=stmt_type,
            tables=tables,
            columns=columns,
            joins=joins,
            functions=functions,
            table_aliases=table_aliases,
            subquery_depth=subquery_depth,
            cte_count=cte_count,
            union_count=union_count,
            limit_value=limit_val,
            has_limit=has_limit,
            has_cartesian_join=has_cartesian,
            projection_aliases=projection_aliases,
        )
