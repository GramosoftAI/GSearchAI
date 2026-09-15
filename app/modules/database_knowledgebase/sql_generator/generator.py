"""Candidate SQL Generator

Generates candidate SQL strings from QueryPlanIR using LLM chat completions
or deterministic AST compilation.
"""

import logging
import re
import datetime
from typing import Optional, Any
import sqlglot
from sqlglot import exp

from ..planning.models import (
    AggregateFunction,
    ColumnProjectionPlan,
    IntentType,
    JoinPlan,
    PredicatePlan,
    QueryPlanIR,
)
from ..retrieval.retriever import SchemaRetrievalResult
from .prompt_templates import SQLPromptBuilder

logger = logging.getLogger(__name__)


class CandidateSQLGenerator:
    """
    Produces candidate SQL from QueryPlanIR.
    """

    @classmethod
    def compile_plan_to_ast(cls, plan: QueryPlanIR) -> exp.Select:
        """
        Deterministically compile a QueryPlanIR into a sqlglot Select AST.
        """
        if not plan.tables:
            raise ValueError("QueryPlanIR contains no tables")

        # 1. Primary Table (FROM)
        primary = plan.tables[0]
        primary_tbl_expr = exp.table_(primary.table_name, db=primary.schema_name, alias=primary.alias)
        query = exp.select().from_(primary_tbl_expr)

        # 2. Joins
        # Map table alias to table name
        alias_to_table = {t.alias: (t.schema_name, t.table_name) for t in plan.tables}
        joined_aliases = {primary.alias}

        # Ensure all joins that can connect are connected (multiple passes to handle arbitrary ordering)
        added = True
        while added:
            added = False
            for j in plan.joins:
                if j.target_table_alias not in joined_aliases and j.source_table_alias in joined_aliases:
                    new_alias = j.target_table_alias
                    existing_alias = j.source_table_alias
                    new_col = j.target_column
                    existing_col = j.source_column
                elif j.source_table_alias not in joined_aliases and j.target_table_alias in joined_aliases:
                    new_alias = j.source_table_alias
                    existing_alias = j.target_table_alias
                    new_col = j.source_column
                    existing_col = j.target_column
                else:
                    continue

                tgt_s, tgt_t = alias_to_table.get(new_alias, ("public", new_alias))
                join_tbl = exp.table_(tgt_t, db=tgt_s, alias=new_alias)

                on_cond = exp.EQ(
                    this=exp.column(existing_col, table=existing_alias),
                    expression=exp.column(new_col, table=new_alias),
                )
                join_kind = "LEFT" if j.join_type.value.upper() == "LEFT" else "INNER"
                query = query.join(join_tbl, on=on_cond, join_type=join_kind)
                joined_aliases.add(new_alias)
                added = True

        # Ensure any remaining plan tables are joined
        for t in plan.tables[1:]:
            if t.alias not in joined_aliases:
                join_tbl = exp.table_(t.table_name, db=t.schema_name, alias=t.alias)
                query = query.join(join_tbl, join_type="INNER")
                joined_aliases.add(t.alias)

        # 3. Projections (SELECT items)
        for proj in plan.projections:
            col_name_clean = proj.column_name.strip()
            if any(col_name_clean.upper().startswith(fn) for fn in ("SUM(", "AVG(", "COUNT(", "MIN(", "MAX(", "ROUND(", "COALESCE(")) or "/" in col_name_clean:
                try:
                    parsed_expr = sqlglot.parse_one(col_name_clean, read="postgres")
                    for c in parsed_expr.find_all(exp.Column):
                        if not c.table:
                            c.set("table", exp.to_identifier(proj.table_alias))
                    select_item = parsed_expr
                except Exception:
                    select_item = exp.column(proj.column_name, table=proj.table_alias)
            else:
                col_expr = exp.column(proj.column_name, table=proj.table_alias)
                if proj.aggregation == AggregateFunction.COUNT:
                    select_item = exp.Count(this=col_expr)
                elif proj.aggregation == AggregateFunction.COUNT_DISTINCT:
                    select_item = exp.Count(this=exp.Distinct(expressions=[col_expr]))
                elif proj.aggregation == AggregateFunction.SUM:
                    select_item = exp.Sum(this=col_expr)
                elif proj.aggregation == AggregateFunction.AVG:
                    select_item = exp.Avg(this=col_expr)
                elif proj.aggregation == AggregateFunction.MIN:
                    select_item = exp.Min(this=col_expr)
                elif proj.aggregation == AggregateFunction.MAX:
                    select_item = exp.Max(this=col_expr)
                else:
                    select_item = col_expr

            if proj.output_alias:
                select_item = exp.alias_(select_item, proj.output_alias)

            query = query.select(select_item)

        # If no projections added, select primary key or wildcard
        if not plan.projections:
            query = query.select(exp.Star())

        # 4. Predicates (WHERE)
        def _literal(val: Any) -> exp.Expression:
            if isinstance(val, (int, float)):
                return exp.Literal.number(val)
            val_str = str(val)
            upper_str = val_str.upper().strip()
            if any(upper_str.startswith(kw) for kw in ("CURRENT_DATE", "CURRENT_TIMESTAMP", "NOW()", "DATE_TRUNC(")):
                try:
                    return sqlglot.parse_one(val_str, read="postgres")
                except Exception:
                    pass
            try:
                float(val_str)
                if ":" not in val_str and "-" not in val_str:
                    return exp.Literal.number(val_str)
            except (ValueError, TypeError):
                pass
            return exp.Literal.string(val_str)

        where_conds = []
        for p in plan.predicates:
            col_expr = exp.column(p.column_name, table=p.table_alias)
            is_time_val = (
                isinstance(p.value, datetime.time)
                or (isinstance(p.value, str) and bool(re.match(r"^\d{1,2}:\d{2}(:\d{2})?(\.\d+)?$", p.value.strip())))
            )
            if is_time_val:
                col_expr = exp.Cast(this=col_expr, to=exp.DataType.build("time"))

            op = p.operator.upper().strip()

            if op == "EXTRACT_DOW":
                cond = exp.EQ(
                    this=sqlglot.parse_one(f"EXTRACT(DOW FROM {col_expr.sql(dialect='postgres')})"),
                    expression=exp.Literal.number(p.value),
                )
            elif op in {"=", "=="}:
                cond = exp.EQ(this=col_expr, expression=_literal(p.value))
            elif op == "!=":
                cond = exp.NEQ(this=col_expr, expression=_literal(p.value))
            elif op == ">":
                cond = exp.GT(this=col_expr, expression=_literal(p.value))
            elif op == "<":
                cond = exp.LT(this=col_expr, expression=_literal(p.value))
            elif op == ">=":
                cond = exp.GTE(this=col_expr, expression=_literal(p.value))
            elif op == "<=":
                cond = exp.LTE(this=col_expr, expression=_literal(p.value))
            elif op == "LIKE":
                cond = exp.Like(this=col_expr, expression=exp.Literal.string(str(p.value)))
            elif op == "ILIKE":
                cond = exp.ILike(this=col_expr, expression=exp.Literal.string(str(p.value)))
            elif op == "IS NULL":
                cond = exp.Is(this=col_expr, expression=exp.Null())
            elif op == "IS NOT NULL":
                cond = exp.Not(this=exp.Is(this=col_expr, expression=exp.Null()))
            elif op == "IN":
                # Support raw SQL subquery values like "(SELECT id FROM ... WHERE ...)"
                val_str = str(p.value).strip()
                if val_str.startswith("("):
                    try:
                        inner = sqlglot.parse_one(val_str, read="postgres")
                        cond = exp.In(this=col_expr, query=inner)
                    except Exception:
                        cond = exp.In(this=col_expr, expressions=[exp.Literal.string(val_str)])
                else:
                    # Comma-separated literal list
                    items = [v.strip().strip("'") for v in val_str.strip("()").split(",")]
                    cond = exp.In(this=col_expr, expressions=[exp.Literal.string(v) for v in items])
            elif op == "NOT IN":
                val_str = str(p.value).strip()
                if val_str.startswith("("):
                    try:
                        inner = sqlglot.parse_one(val_str, read="postgres")
                        cond = exp.Not(this=exp.In(this=col_expr, query=inner))
                    except Exception:
                        cond = exp.Not(this=exp.In(this=col_expr, expressions=[exp.Literal.string(val_str)]))
                else:
                    items = [v.strip().strip("'") for v in val_str.strip("()").split(",")]
                    cond = exp.Not(this=exp.In(this=col_expr, expressions=[exp.Literal.string(v) for v in items]))
            else:
                cond = exp.EQ(this=col_expr, expression=_literal(p.value))

            where_conds.append(cond)

        for cond in where_conds:
            query = query.where(cond)

        # 5. Group By
        group_by_cols = list(plan.group_by)
        if group_by_cols:
            non_agg_cols = [
                f"{proj.table_alias}.{proj.column_name}"
                for proj in plan.projections
                if proj.aggregation == AggregateFunction.NONE
                and not any(proj.column_name.strip().upper().startswith(fn) for fn in ("SUM(", "AVG(", "COUNT(", "MIN(", "MAX(", "ROUND(", "COALESCE("))
                and "/" not in proj.column_name
            ]
            for col_str in non_agg_cols:
                if col_str not in group_by_cols and col_str.split(".")[-1] not in group_by_cols:
                    group_by_cols.append(col_str)

        for g_expr_str in group_by_cols:
            parts = g_expr_str.split(".")
            if len(parts) == 2:
                g_col = exp.column(parts[1], table=parts[0])
            else:
                g_col = exp.column(g_expr_str)
            query = query.group_by(g_col)

        # 6. Order By
        for o in plan.order_by:
            expr_str = o.expression.strip()
            desc = o.direction.value.upper() == "DESC"
            if any(expr_str.upper().startswith(fn) for fn in ("SUM(", "COUNT(", "AVG(", "MIN(", "MAX(", "ROUND(")):
                try:
                    o_expr = sqlglot.parse_one(expr_str, read="postgres")
                except Exception:
                    o_expr = exp.column(expr_str)
            else:
                parts = expr_str.split(".")
                if len(parts) == 2:
                    o_expr = exp.column(parts[1], table=parts[0])
                else:
                    o_expr = exp.column(expr_str)
            query = query.order_by(exp.Ordered(this=o_expr, desc=desc))

        # 7. Limit
        if plan.limit:
            query = query.limit(plan.limit)

        return query

    @classmethod
    def compile_plan_to_sql(cls, plan: QueryPlanIR) -> Optional[str]:
        """Deterministically compile QueryPlanIR to PostgreSQL SQL string."""
        if not plan or not plan.tables:
            return None
        if not plan.projections and plan.confidence == 0.0:
            return None
        ast = cls.compile_plan_to_ast(plan)
        return ast.sql(dialect="postgres")

    @classmethod
    def _extract_sql_from_response(cls, text: str) -> str:
        """Extract clean SQL string from LLM markdown response."""
        # 1. Match ```sql ... ```
        sql_match = re.search(r"```(?:sql)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if sql_match:
            return sql_match.group(1).strip()

        # 2. Match raw SELECT statement
        select_match = re.search(r"\bSELECT\b[\s\S]*?(?:;|\Z)", text, re.IGNORECASE)
        if select_match:
            return select_match.group(0).strip()

        return text.strip()

    @classmethod
    async def generate_candidate_sql(
        cls,
        user_query: str,
        plan: QueryPlanIR,
        retrieval_result: SchemaRetrievalResult,
        use_llm: bool = True,
    ) -> str:
        """
        Generate candidate SQL for the given plan.
        Tries LLM if enabled; falls back to deterministic AST compilation.
        """
        if use_llm:
            try:
                from app.core.llm.deepinfra_llm import DeepInfraLLMClient
                from app.core.config import get_settings

                settings = get_settings()
                prompt = SQLPromptBuilder.build_generation_prompt(user_query, plan, retrieval_result)

                # Invoke LLM
                client = DeepInfraLLMClient()
                response_text = await client.generate_cloud(
                    prompt=prompt,
                    system_prompt=SQLPromptBuilder.SYSTEM_PROMPT,
                    temperature=0.0,
                    max_tokens=1024,
                    enable_thinking=False,
                )
                if response_text:
                    sql_candidate = cls._extract_sql_from_response(response_text)
                    if sql_candidate:
                        return sql_candidate
            except Exception as e:
                logger.warning(f"LLM candidate SQL generation failed, falling back to deterministic compiler: {e}")

        # Deterministic fallback compilation
        return cls.compile_plan_to_sql(plan)
