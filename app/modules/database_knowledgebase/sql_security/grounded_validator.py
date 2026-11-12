"""Grounded SQL Validator using SQLGlot

Enforces strict single-statement, read-only SELECT/CTE safety invariants
without blocking legitimate analytical functions.
Directly implements the validator from D:\\DB\\main\\app\\pipeline\\sql_validator.py.
"""

import logging
from typing import Optional, List
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


STATUS_TERMS = {
    "approved", "pending", "rejected", "completed", "submitted",
    "closed", "draft", "cancelled", "declined", "passed"
}


class GroundedSQLValidator:
    """Validates generated SQL against read-only security invariants using SQLGlot."""

    @classmethod
    def fix_hallucinated_boolean_predicates(cls, sql: str, available_columns: Optional[list] = None, dialect: str = "postgres") -> str:
        """
        Dynamically repairs common LLM boolean hallucinations:
        1. Workflow states mistakenly written as boolean flags (e.g. `approved = TRUE` -> `stage ILIKE '%approved%'`)
        2. Numeric zero mistakenly written as boolean FALSE (e.g. `budgeted = FALSE` -> `budgeted = 0`)
        """
        if not sql:
            return sql
        clean_d = (dialect or "postgres").lower()
        d_name = "tsql" if any(k in clean_d for k in ("sqlserver", "mssql", "tsql")) else ("mysql" if any(k in clean_d for k in ("mysql", "mariadb")) else "postgres")

        try:
            tree = sqlglot.parse_one(sql, read=d_name)
        except Exception:
            try:
                tree = sqlglot.parse_one(sql)
            except Exception:
                return sql

        cols_lower = [c.lower() for c in (available_columns or []) if c]
        status_col = next((c for c in cols_lower if c in ("stage", "status", "state", "workflow_state", "workflow_status", "phase", "step")), "stage" if not cols_lower else None)

        modified = False
        for eq in list(tree.find_all(exp.EQ)):
            col_node = None
            val_node = None
            if isinstance(eq.this, exp.Column):
                col_node = eq.this
                val_node = eq.expression
            elif isinstance(eq.expression, exp.Column):
                col_node = eq.expression
                val_node = eq.this

            if not col_node or not val_node:
                continue

            c_name = col_node.name.lower()

            # Case 1: Status word as boolean column: approved = TRUE -> stage ILIKE '%approved%'
            if c_name in STATUS_TERMS and isinstance(val_node, exp.Boolean) and val_node.this is True:
                target_status_col = status_col or "stage"
                new_pred = exp.ILike(
                    this=exp.Column(this=exp.to_identifier(target_status_col), table=col_node.table),
                    expression=exp.Literal.string(f"%{c_name}%")
                )
                eq.replace(new_pred)
                modified = True
                logger.info(f"[GroundedSQLValidator] Repaired boolean status filter '{c_name} = TRUE' -> '{target_status_col} ILIKE %{c_name}%'")

            # Case 2: Status word as boolean FALSE: approved = FALSE -> stage NOT ILIKE '%approved%'
            elif c_name in STATUS_TERMS and isinstance(val_node, exp.Boolean) and val_node.this is False:
                target_status_col = status_col or "stage"
                new_pred = exp.Not(this=exp.ILike(
                    this=exp.Column(this=exp.to_identifier(target_status_col), table=col_node.table),
                    expression=exp.Literal.string(f"%{c_name}%")
                ))
                eq.replace(new_pred)
                modified = True
                logger.info(f"[GroundedSQLValidator] Repaired boolean status filter '{c_name} = FALSE' -> '{target_status_col} NOT ILIKE %{c_name}%'")

            # Case 3: Numeric zero turned into boolean FALSE: budgeted = FALSE -> budgeted = 0
            elif isinstance(val_node, exp.Boolean) and val_node.this is False:
                if any(k in c_name for k in ("budget", "amount", "balance", "count", "price", "cost", "total", "qty", "quantity")):
                    new_pred = exp.EQ(
                        this=col_node,
                        expression=exp.Literal.number(0)
                    )
                    eq.replace(new_pred)
                    modified = True
                    logger.info(f"[GroundedSQLValidator] Repaired numeric boolean false '{c_name} = FALSE' -> '{c_name} = 0'")

            # Case 4: Numeric metric turned into boolean TRUE: budgeted = TRUE -> budgeted > 0
            elif isinstance(val_node, exp.Boolean) and val_node.this is True:
                if any(k in c_name for k in ("budget", "amount", "balance", "price", "cost")) and c_name not in ("active", "enabled", "is_active", "deleted"):
                    new_pred = exp.GT(
                        this=col_node,
                        expression=exp.Literal.number(0)
                    )
                    eq.replace(new_pred)
                    modified = True
                    logger.info(f"[GroundedSQLValidator] Repaired numeric boolean true '{c_name} = TRUE' -> '{c_name} > 0'")

            # Case 5: Foreign key equated directly to a business code (e.g. budget_id = 5010172804 or budget_id = '5010172804')
            elif c_name.endswith("_id") and c_name not in ("id", "tenant_id", "pk", "parent_id"):
                val_raw = str(getattr(val_node, "this", ""))
                is_long_code = (isinstance(val_node, exp.Literal) and val_node.is_string and len(val_raw) >= 3) or (
                    isinstance(val_node, exp.Literal) and val_node.is_number and len(val_raw) >= 6
                )
                if is_long_code:
                    existing_tables = {t.name.lower() for t in tree.find_all(exp.Table) if t.name}
                    col_tbl = col_node.table.lower() if col_node.table else ""
                    fk_entity = c_name[:-3]
                    parent_candidate = next((t for t in existing_tables if (t.endswith(f"{fk_entity}s") or t == f"{fk_entity}s") and t != col_tbl), None)
                    if parent_candidate:
                        t_alias = None
                        for t in tree.find_all(exp.Table):
                            if t.name.lower() == parent_candidate:
                                t_alias = t.alias if t.alias else t.name
                                break
                        target_table_ref = t_alias or parent_candidate
                        new_pred = exp.ILike(
                            this=exp.Column(this=exp.to_identifier("code"), table=exp.to_identifier(target_table_ref)),
                            expression=exp.Literal.string(f"%{val_raw}%")
                        )
                        eq.replace(new_pred)
                        modified = True
                        logger.info(f"[GroundedSQLValidator] Repaired foreign key code filter '{c_name} = {val_raw}' -> '{target_table_ref}.code ILIKE %{val_raw}%'")
                    else:
                        tbl_prefix = ""
                        for t_name in existing_tables:
                            if "_" in t_name:
                                tbl_prefix = t_name.split("_")[0] + "_"
                                break
                        parent_table_inferred = f"{tbl_prefix}{fk_entity}s" if tbl_prefix else f"{fk_entity}s"
                        subq_sql = f"{col_node.sql(dialect=d_name)} IN (SELECT id FROM {parent_table_inferred} WHERE code ILIKE '%{val_raw}%')"
                        try:
                            subq_node = sqlglot.parse_one(subq_sql, read=d_name)
                            eq.replace(subq_node)
                            modified = True
                            logger.info(f"[GroundedSQLValidator] Repaired foreign key code filter with subquery: '{subq_sql}'")
                        except Exception as e:
                            logger.warning(f"[GroundedSQLValidator] Could not parse FK subquery '{subq_sql}': {e}")

        if modified:
            return tree.sql(dialect=d_name)
        return sql

    @classmethod
    def strip_table_alias_predicates(cls, sql: str, alias_words: Optional[list] = None, dialect: str = "postgres") -> str:
        """
        Dynamically strips any WHERE clause predicates where a literal value
        matches a user-configured table alias (e.g. lob ILIKE '%cream%' or name = 'cream').
        Table aliases identify tables, never column filter values.
        """
        if not sql or not alias_words:
            return sql

        aliases_lower = {a.strip().lower() for a in alias_words if a and a.strip()}
        if not aliases_lower:
            return sql

        clean_d = (dialect or "postgres").lower()
        if clean_d in ("sqlserver", "mssql", "tsql"):
            d_name = "tsql"
        elif clean_d in ("mysql", "mariadb"):
            d_name = "mysql"
        else:
            d_name = "postgres"

        try:
            tree = sqlglot.parse_one(sql, read=d_name)
        except Exception:
            try:
                tree = sqlglot.parse_one(sql)
            except Exception:
                return sql

        matched_any = False
        for node in list(tree.find_all((exp.ILike, exp.Like, exp.EQ, exp.NEQ))):
            for lit in node.find_all(exp.Literal):
                val = str(lit.this).strip().strip("%").strip().lower()
                if val in aliases_lower:
                    node.replace(exp.true())
                    matched_any = True
                    break

        if not matched_any:
            return sql

        try:
            from sqlglot.optimizer.simplify import simplify
            simp = simplify(tree)
            where = simp.find(exp.Where)
            if where and isinstance(where.this, exp.Boolean) and where.this.this is True:
                where.pop()
            return simp.sql(dialect=d_name)
        except Exception as simp_err:
            logger.debug(f"[GroundedSQLValidator] Simplify failed: {simp_err}")
            return sql

    @classmethod
    def strip_unrequested_boolean_predicates(
        cls,
        sql: str,
        user_query: Optional[str] = None,
        dialect: str = "postgres",
    ) -> str:
        """
        Strips automatic boolean predicates like `deleted = FALSE` or `active = TRUE`
        UNLESS the user explicitly mentioned active/deleted status in their question.
        """
        if not sql or not user_query:
            return sql

        q_lower = user_query.lower()
        user_asked_active = any(w in q_lower for w in ("active", "activate", "activated", "enabled", "inactive", "disabled"))
        user_asked_deleted = any(w in q_lower for w in ("delete", "deleted", "trash", "soft-delete", "soft_delete"))

        # If user explicitly asked for both, nothing to strip
        if user_asked_active and user_asked_deleted:
            return sql

        clean_d = (dialect or "postgres").lower()
        d_name = "tsql" if any(k in clean_d for k in ("sqlserver", "mssql", "tsql")) else ("mysql" if any(k in clean_d for k in ("mysql", "mariadb")) else "postgres")

        try:
            tree = sqlglot.parse_one(sql, read=d_name)
        except Exception:
            try:
                tree = sqlglot.parse_one(sql)
            except Exception:
                return sql

        matched_any = False
        for eq in list(tree.find_all(exp.EQ)):
            col_node = eq.this if isinstance(eq.this, exp.Column) else (eq.expression if isinstance(eq.expression, exp.Column) else None)
            val_node = eq.expression if col_node == eq.this else eq.this
            if not col_node or not val_node:
                continue
            c_name = col_node.name.lower()

            if c_name in ("active", "is_active", "enabled") and isinstance(val_node, exp.Boolean):
                if not user_asked_active:
                    eq.replace(exp.true())
                    matched_any = True
                    logger.info(f"[GroundedSQLValidator] Stripped unrequested active filter '{c_name} = {val_node.this}'")

            elif c_name in ("deleted", "is_deleted") and isinstance(val_node, exp.Boolean):
                if not user_asked_deleted:
                    eq.replace(exp.true())
                    matched_any = True
                    logger.info(f"[GroundedSQLValidator] Stripped unrequested deleted filter '{c_name} = {val_node.this}'")

        if not matched_any:
            return sql

        try:
            from sqlglot.optimizer.simplify import simplify
            simp = simplify(tree)
            where = simp.find(exp.Where)
            if where and isinstance(where.this, exp.Boolean) and where.this.this is True:
                where.pop()
            return simp.sql(dialect=d_name)
        except Exception as simp_err:
            logger.debug(f"[GroundedSQLValidator] Simplify failed: {simp_err}")
            return sql

    @classmethod
    def validate_readonly_sql(
        cls,
        sql: str,
        dialect: str = "postgres",
        table_alias_words: Optional[list] = None,
        available_columns: Optional[list] = None,
        user_query: Optional[str] = None,
    ) -> str:
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

        clean_d = (dialect or "postgres").lower()
        if clean_d in ("sqlserver", "mssql", "tsql"):
            read_dialect = "tsql"
            out_dialect = "tsql"
        elif clean_d in ("mysql", "mariadb"):
            read_dialect = "mysql"
            out_dialect = "mysql"
        else:
            read_dialect = "postgres"
            out_dialect = "postgres"

        try:
            statements = sqlglot.parse(cleaned, read=read_dialect)
        except Exception as exc:
            try:
                statements = sqlglot.parse(cleaned)
            except Exception:
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

        # Convert string literal equality checks to case-insensitive ILIKE only in PostgreSQL
        if out_dialect in ("postgres", "postgresql"):
            for eq in list(tree.find_all(exp.EQ)):
                if isinstance(eq.expression, exp.Literal) and eq.expression.is_string:
                    eq.replace(exp.ILike(this=eq.this, expression=eq.expression))
                elif isinstance(eq.this, exp.Literal) and eq.this.is_string:
                    eq.replace(exp.ILike(this=eq.expression, expression=eq.this))

            for neq in list(tree.find_all(exp.NEQ)):
                if isinstance(neq.expression, exp.Literal) and neq.expression.is_string:
                    neq.replace(exp.Not(this=exp.ILike(this=neq.this, expression=neq.expression)))
                elif isinstance(neq.this, exp.Literal) and neq.this.is_string:
                    neq.replace(exp.Not(this=exp.ILike(this=neq.expression, expression=neq.this)))

        validated_sql = tree.sql(dialect=out_dialect)
        if available_columns:
            validated_sql = cls.fix_hallucinated_boolean_predicates(validated_sql, available_columns, dialect=out_dialect)
        if table_alias_words:
            validated_sql = cls.strip_table_alias_predicates(validated_sql, table_alias_words, dialect=out_dialect)
        if user_query:
            validated_sql = cls.strip_unrequested_boolean_predicates(validated_sql, user_query, dialect=out_dialect)
        return validated_sql
