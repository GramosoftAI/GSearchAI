"""SQL Security Policy Engine

Enforces deterministic, multi-layered security gates on parsed SQL ASTs:
1. SELECT-only Root Statement Gate (Strictly rejects DML/DDL/TCL/DCL)
2. System Catalog & Metadata Protection Gate
3. Sub-Schema Table Whitelist Gate
4. Sub-Schema Column Whitelist Gate
5. Relational Join Integrity & Anti-Cartesian Gate
6. Function Allowlist Gate (Blocks filesystem, network, and arbitrary code execution)
7. Query Complexity Bounding Gate
8. Mandatory LIMIT Enforcement Gate
"""

from typing import Dict, List, Optional, Set
import sqlglot
from sqlglot import exp

from ..schemas.canonical import DatabaseSchema, TableSchema
from ..retrieval.retriever import SchemaRetrievalResult
from ..sql_parser.ast_parser import SQLASTParser
from ..sql_parser.inspector import ASTInspector, ASTInspectionReport
from .diagnostics import DiagnosticError, DiagnosticErrorCode, DiagnosticSeverity, ValidationResult


class SQLSecurityPolicyEngine:
    """
    Deterministic AST Security Validator.
    Independent of LLM instructions and fail-closed.
    """

    # Safe SQL functions allowlist (uppercase)
    ALLOWED_FUNCTIONS: Set[str] = {
        # Aggregates
        "COUNT", "SUM", "AVG", "MIN", "MAX",
        # Math & Formatting
        "ROUND", "CEIL", "CEILING", "FLOOR", "ABS", "COALESCE", "NULLIF", "LEAST", "GREATEST",
        # Temporal
        "EXTRACT", "DATE_TRUNC", "TIMESTAMP_TRUNC", "DATETIME_TRUNC", "NOW", "CURRENT_DATE", "CURRENT_TIMESTAMP", "AGE", "INTERVAL",
        # String
        "LOWER", "UPPER", "CONCAT", "LENGTH", "TRIM", "LTRIM", "RTRIM", "SUBSTRING", "POSITION",
        # Conditional & Casting
        "CASE", "CAST", "TRY_CAST",
    }

    # Forbidden System Catalogs and Metadata schemas/tables
    FORBIDDEN_CATALOGS: Set[str] = {
        "pg_catalog", "information_schema", "pg_toast", "pg_temp",
    }
    FORBIDDEN_TABLES: Set[str] = {
        "pg_shadow", "pg_authid", "pg_user", "pg_database", "pg_tables",
        "pg_stat_activity", "pg_settings", "pg_class", "pg_proc",
        "pg_attribute", "pg_type", "pg_namespace",
    }

    # Complexity Limits
    MAX_JOINS = 5
    MAX_SUBQUERY_DEPTH = 2
    MAX_UNION_BRANCHES = 3
    MAX_CTE_COUNT = 2
    MAX_LIMIT = 1000
    DEFAULT_LIMIT = 100

    @classmethod
    def validate_ast(
        cls,
        root: exp.Expression,
        canonical_schema: DatabaseSchema,
        retrieval_result: SchemaRetrievalResult,
    ) -> ValidationResult:
        """
        Evaluate all security policies against the parsed SQL AST.
        """
        errors: List[DiagnosticError] = []
        warnings: List[str] = []

        report = ASTInspector.inspect(root)

        # 1. Statement Type Gate: SELECT-only
        if not report.is_select_root or report.statement_type not in {"SELECT", "UNION"}:
            errors.append(
                DiagnosticError(
                    error_code=DiagnosticErrorCode.NON_SELECT_STATEMENT,
                    severity=DiagnosticSeverity.ERROR,
                    message=f"Only SELECT queries are permitted. Found forbidden statement type: '{report.statement_type}'",
                    offending_node=report.statement_type,
                    suggested_action="Reformulate query as a read-only SELECT statement",
                )
            )
            # If DML/DDL detected, stop immediately
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

        # 2. System Catalog & Metadata Protection Gate
        for tbl in report.tables:
            if tbl.schema_name.lower() in cls.FORBIDDEN_CATALOGS or tbl.table_name.lower() in cls.FORBIDDEN_TABLES:
                errors.append(
                    DiagnosticError(
                        error_code=DiagnosticErrorCode.CATALOG_ACCESS_FORBIDDEN,
                        severity=DiagnosticSeverity.ERROR,
                        message=f"Access to system catalog '{tbl.schema_name}.{tbl.table_name}' is strictly forbidden",
                        offending_node=f"{tbl.schema_name}.{tbl.table_name}",
                        suggested_action="Query approved application business tables only",
                    )
                )

        # 3. Table Whitelist Gate (Must exist in Phase 2A retrieved sub-schema or Canonical Schema)
        approved_table_names: Set[str] = {t.table_name.lower() for t in retrieval_result.retrieved_tables}
        approved_table_map: Dict[str, TableSchema] = {t.table_name.lower(): t for t in retrieval_result.retrieved_tables}

        # Index canonical schema tables if available
        canonical_tables_map: Dict[str, TableSchema] = {}
        if canonical_schema:
            for s_name, s_info in getattr(canonical_schema, "schemas", {}).items():
                for t_name, t_obj in getattr(s_info, "tables", {}).items():
                    canonical_tables_map[t_name.lower()] = t_obj
                    canonical_tables_map[f"{t_obj.schema_name.lower()}.{t_name.lower()}"] = t_obj

        def _get_table_columns(tbl_name: str) -> Optional[Set[str]]:
            clean_name = tbl_name.lower().split(".")[-1]
            if clean_name in canonical_tables_map:
                return {c.lower() for c in canonical_tables_map[clean_name].columns.keys()}
            if tbl_name.lower() in canonical_tables_map:
                return {c.lower() for c in canonical_tables_map[tbl_name.lower()].columns.keys()}
            if clean_name in approved_table_map:
                return {c.lower() for c in approved_table_map[clean_name].columns.keys()}
            if tbl_name.lower() in approved_table_map:
                return {c.lower() for c in approved_table_map[tbl_name.lower()].columns.keys()}
            return None

        for tbl in report.tables:
            t_clean = tbl.table_name.lower().split(".")[-1]
            # If table is part of system catalog, already caught above
            if t_clean in cls.FORBIDDEN_TABLES or tbl.schema_name.lower() in cls.FORBIDDEN_CATALOGS:
                continue

            if (
                t_clean not in approved_table_names
                and tbl.table_name.lower() not in approved_table_names
                and t_clean not in canonical_tables_map
                and tbl.table_name.lower() not in canonical_tables_map
            ):
                errors.append(
                    DiagnosticError(
                        error_code=DiagnosticErrorCode.UNAPPROVED_TABLE,
                        severity=DiagnosticSeverity.ERROR,
                        message=f"Table '{tbl.table_name}' was not retrieved in the sub-schema for this query",
                        offending_node=tbl.table_name,
                        suggested_action=f"Use only approved tables: {', '.join(sorted(list(approved_table_names)))}",
                    )
                )

        # 4. Column Whitelist Gate (Must exist in approved table schema or canonical schema)
        all_approved_cols: Set[str] = set()
        cols_by_table_alias: Dict[str, Set[str]] = {}

        for tbl in retrieval_result.retrieved_tables:
            t_low = tbl.table_name.lower()
            tbl_cols = _get_table_columns(t_low) or {c.lower() for c in tbl.columns.keys()}
            all_approved_cols.update(tbl_cols)
            cols_by_table_alias[t_low] = tbl_cols
            cols_by_table_alias[t_low.split(".")[-1]] = tbl_cols

        # Map aliases from AST to table names
        for alias, inspected_tbl in report.table_aliases.items():
            target_cols = _get_table_columns(inspected_tbl.table_name)
            if target_cols:
                cols_by_table_alias[alias.lower()] = target_cols
                all_approved_cols.update(target_cols)

        for col in report.columns:
            c_clean = col.column_name.lower()
            if c_clean in {"*", "1"}:
                continue

            qualifier = col.table_qualifier.lower() if col.table_qualifier else None

            if qualifier and qualifier in cols_by_table_alias:
                if c_clean not in cols_by_table_alias[qualifier]:
                    errors.append(
                        DiagnosticError(
                            error_code=DiagnosticErrorCode.UNAPPROVED_COLUMN,
                            severity=DiagnosticSeverity.ERROR,
                            message=f"Column '{col.column_name}' does not exist on table '{qualifier}'",
                            offending_node=f"{qualifier}.{col.column_name}",
                            suggested_action=f"Select from available columns: {', '.join(sorted(list(cols_by_table_alias[qualifier])))}",
                        )
                    )
            elif not qualifier:
                approved_aliases = {a.lower() for a in report.projection_aliases}
                if c_clean not in all_approved_cols and c_clean not in approved_aliases:
                    errors.append(
                        DiagnosticError(
                            error_code=DiagnosticErrorCode.UNAPPROVED_COLUMN,
                            severity=DiagnosticSeverity.ERROR,
                            message=f"Unqualified column '{col.column_name}' is not in approved sub-schema",
                            offending_node=col.column_name,
                            suggested_action="Use explicit table alias and valid column name",
                        )
                    )

        # 5. Join Integrity & Anti-Cartesian Gate
        if report.has_cartesian_join or (len(report.tables) > 1 and len(report.joins) == 0):
            errors.append(
                DiagnosticError(
                    error_code=DiagnosticErrorCode.CARTESIAN_JOIN,
                    severity=DiagnosticSeverity.ERROR,
                    message="Cartesian product detected: multiple tables are queried without explicit join ON conditions",
                    offending_node="CROSS JOIN / Comma Join",
                    suggested_action="Use explicit INNER JOIN or LEFT JOIN with foreign key ON conditions",
                )
            )

        # 6. Function Allowlist Gate
        for func in report.functions:
            f_clean = func.function_name.upper()
            if f_clean not in cls.ALLOWED_FUNCTIONS:
                errors.append(
                    DiagnosticError(
                        error_code=DiagnosticErrorCode.FORBIDDEN_FUNCTION,
                        severity=DiagnosticSeverity.ERROR,
                        message=f"Function '{func.function_name}' is not in the approved SQL function allowlist",
                        offending_node=func.function_name,
                        suggested_action=f"Use standard allowed functions: {', '.join(sorted(list(cls.ALLOWED_FUNCTIONS)[:10]))}...",
                    )
                )

        # 7. Complexity Bounds Gate
        if len(report.joins) > cls.MAX_JOINS:
            errors.append(
                DiagnosticError(
                    error_code=DiagnosticErrorCode.COMPLEXITY_EXCEEDED,
                    severity=DiagnosticSeverity.ERROR,
                    message=f"Query contains {len(report.joins)} joins, exceeding maximum allowed of {cls.MAX_JOINS}",
                    offending_node="Joins count",
                    suggested_action=f"Reduce join complexity to at most {cls.MAX_JOINS} joins",
                )
            )

        if report.subquery_depth > cls.MAX_SUBQUERY_DEPTH:
            errors.append(
                DiagnosticError(
                    error_code=DiagnosticErrorCode.COMPLEXITY_EXCEEDED,
                    severity=DiagnosticSeverity.ERROR,
                    message=f"Subquery depth {report.subquery_depth} exceeds maximum depth of {cls.MAX_SUBQUERY_DEPTH}",
                    offending_node="Subquery nesting",
                    suggested_action="Flatten nested subqueries",
                )
            )

        if report.union_count > cls.MAX_UNION_BRANCHES:
            errors.append(
                DiagnosticError(
                    error_code=DiagnosticErrorCode.COMPLEXITY_EXCEEDED,
                    severity=DiagnosticSeverity.ERROR,
                    message=f"UNION count {report.union_count} exceeds maximum of {cls.MAX_UNION_BRANCHES}",
                    offending_node="UNION",
                    suggested_action="Reduce UNION branches",
                )
            )

        if report.cte_count > cls.MAX_CTE_COUNT:
            errors.append(
                DiagnosticError(
                    error_code=DiagnosticErrorCode.COMPLEXITY_EXCEEDED,
                    severity=DiagnosticSeverity.ERROR,
                    message=f"CTE count {report.cte_count} exceeds maximum of {cls.MAX_CTE_COUNT}",
                    offending_node="WITH / CTE",
                    suggested_action="Inline CTE expressions",
                )
            )

        # 8. Mandatory LIMIT Enforcement Gate
        sanitized_ast = root.copy()
        if isinstance(sanitized_ast, exp.Select):
            if report.has_limit and report.limit_value is not None:
                if report.limit_value > cls.MAX_LIMIT:
                    warnings.append(f"LIMIT {report.limit_value} exceeded {cls.MAX_LIMIT}; clamped to {cls.MAX_LIMIT}")
                    sanitized_ast = sanitized_ast.limit(cls.MAX_LIMIT)
            elif not report.has_limit:
                # Aggregate queries with no GROUP BY return exactly 1 row, but enforcing LIMIT 100 is harmless & safe
                warnings.append(f"No LIMIT specified in candidate query; auto-injected LIMIT {cls.DEFAULT_LIMIT}")
                sanitized_ast = sanitized_ast.limit(cls.DEFAULT_LIMIT)

        sanitized_sql = SQLASTParser.to_sql(sanitized_ast)

        is_valid = len(errors) == 0
        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            sanitized_sql=sanitized_sql if is_valid else None,
        )

    @classmethod
    def validate_sql(
        cls,
        sql_text: str,
        canonical_schema: DatabaseSchema,
        retrieval_result: SchemaRetrievalResult,
    ) -> ValidationResult:
        """
        Parse and validate raw SQL string.
        """
        try:
            ast = SQLASTParser.parse_sql(sql_text)
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                errors=[
                    DiagnosticError(
                        error_code=DiagnosticErrorCode.SYNTAX_ERROR,
                        severity=DiagnosticSeverity.ERROR,
                        message=str(e),
                        offending_node="SQL String",
                        suggested_action="Ensure valid PostgreSQL SQL syntax",
                    )
                ],
                warnings=[],
            )

        return cls.validate_ast(ast, canonical_schema, retrieval_result)
