"""Grounded Answer Synthesizer for Database Knowledge Base

Transforms database query results into clear, detailed natural language passages,
highlighting task notes, progress, and accomplishments.
Provides comprehensive data lineage (source tables, columns, join paths, and filters).
"""

import json
import logging
import re
from typing import List, Dict, Any, Optional, Set
from openai import AsyncOpenAI
import sqlglot
from sqlglot import exp

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class GroundedAnswerSynthesizer:
    """Synthesizes rich, detailed natural language answers from query execution results with data provenance."""

    @classmethod
    def _get_client(cls, timeout: Optional[float] = None) -> AsyncOpenAI:
        req_timeout = timeout or getattr(settings, "synthesis_llm_timeout_seconds", 90.0)
        return AsyncOpenAI(
            api_key=settings.deepinfra_api_key or "anonymous",
            base_url=settings.deepinfra_api_url or "https://api.deepinfra.com/v1/openai",
            timeout=req_timeout,
            max_retries=2,
        )

    @classmethod
    def extract_provenance(cls, sql: str) -> Dict[str, Any]:
        """
        Dynamically extracts source tables, columns, joins, and filter conditions from SQL AST.
        Zero hardcoding, completely dialect-agnostic via sqlglot.
        """
        provenance = {
            "tables": [],
            "primary_table": None,
            "columns": [],
            "joins": [],
            "filters": [],
        }
        if not sql or not sql.strip():
            return provenance

        try:
            parsed = sqlglot.parse_one(sql, read="postgres")
        except Exception:
            try:
                parsed = sqlglot.parse_one(sql)
            except Exception:
                return provenance

        # 1. Alias map & tables
        alias_map = {}
        tables = []
        for tbl in parsed.find_all(exp.Table):
            t_name = tbl.name
            alias = tbl.alias
            if alias:
                alias_map[alias] = t_name
            alias_map[t_name] = t_name
            if t_name and t_name not in tables:
                tables.append(t_name)

        provenance["tables"] = tables
        provenance["primary_table"] = tables[0] if tables else None

        # 2. Joins
        joins = []
        for j in parsed.find_all(exp.Join):
            j_tbl = j.this.name if hasattr(j.this, "name") else str(j.this)
            on_clause = j.args.get("on")
            on_sql = on_clause.sql() if on_clause else ""
            # Clean alias references in on_clause for human clarity
            joins.append({"table": j_tbl, "condition": on_sql})
        provenance["joins"] = joins

        # 3. Columns referenced
        columns_set = set()
        for col in parsed.find_all(exp.Column):
            c_name = col.name
            t_ref = alias_map.get(col.table, col.table) if col.table else None
            full_col = f"{t_ref}.{c_name}" if t_ref else c_name
            columns_set.add(full_col)
        provenance["columns"] = sorted(list(columns_set))

        # 4. Filters (WHERE clauses)
        where_node = parsed.find(exp.Where)
        if where_node:
            where_expr = where_node.this
            # Split top-level AND conditions
            def _extract_and_conditions(expr):
                conds = []
                if isinstance(expr, exp.And):
                    conds.extend(_extract_and_conditions(expr.left))
                    conds.extend(_extract_and_conditions(expr.right))
                else:
                    conds.append(expr.sql())
                return conds
            provenance["filters"] = _extract_and_conditions(where_expr)

        return provenance

    @classmethod
    def _build_provenance_markdown(
        cls,
        provenance: Dict[str, Any],
        schema_interpretation: Optional[Any] = None,
    ) -> str:
        """Constructs a clean, human-readable data provenance block."""
        lines = ["\n\n### 📋 Data Source & Provenance"]
        
        tables = provenance.get("tables", [])
        primary_table = provenance.get("primary_table")
        if primary_table:
            other_tables = [t for t in tables if t != primary_table]
            lines.append(f"- **Primary Table:** `{primary_table}`")
            if other_tables:
                lines.append(f"- **Joined Tables:** {', '.join(f'`{t}`' for t in other_tables)}")
        elif tables:
            lines.append(f"- **Source Tables:** {', '.join(f'`{t}`' for t in tables)}")

        cols = provenance.get("columns", [])
        if cols:
            # Show up to 8 relevant columns
            col_display = ", ".join(f"`{c}`" for c in cols[:8])
            if len(cols) > 8:
                col_display += f" *(and {len(cols) - 8} more)*"
            lines.append(f"- **Source Columns:** {col_display}")

        joins = provenance.get("joins", [])
        if joins:
            join_strs = [f"`{j['table']}` on `{j['condition']}`" if j['condition'] else f"`{j['table']}`" for j in joins]
            lines.append(f"- **Relationship Joins:** {'; '.join(join_strs)}")

        filters = provenance.get("filters", [])
        if filters:
            clean_filters = [f"`{f}`" for f in filters[:5]]
            lines.append(f"- **Applied Filter Criteria:** {', '.join(clean_filters)}")

        # Add schema interpretation context if available
        if schema_interpretation:
            entities = getattr(schema_interpretation, "entities", [])
            resolved_terms = [
                f"`{e.resolved_value}` in `{e.candidate_table}.{e.candidate_column}`"
                for e in entities if getattr(e, "resolved_value", None)
            ]
            if resolved_terms:
                lines.append(f"- **Resolved Business Entities:** {', '.join(resolved_terms)}")

        return "\n".join(lines)

    @classmethod
    async def synthesize_answer(
        cls,
        question: str,
        sql: str,
        result: Dict[str, Any],
        model: Optional[str] = None,
        schema_interpretation: Optional[Any] = None,
    ) -> str:
        """
        Convert database query results into clear, detailed natural language passages
        accompanied by explicit table, column, and filter provenance.
        """
        if not result or "rows" not in result:
            return "No database results were obtained."

        rows = result.get("rows", [])
        row_count = result.get("row_count", len(rows))
        truncated = result.get("truncated", False)

        provenance = cls.extract_provenance(sql)
        provenance_md = cls._build_provenance_markdown(provenance, schema_interpretation=schema_interpretation)

        if row_count == 0:
            return f"No records were found in the database matching your question: '{question}'.{provenance_md}"

        # Fast-path for single scalar count if query is pure count
        cols = result.get("columns", [])
        if row_count == 1 and len(cols) == 1 and isinstance(rows[0], (list, tuple, dict)):
            val = rows[0][0] if isinstance(rows[0], (list, tuple)) else next(iter(rows[0].values()))
            col_name = cols[0].lower() if cols else "count"
            if "count" in col_name or any(w in question.lower() for w in ("how many", "total", "count")):
                # Format a rich, descriptive answer with table name if available
                entity_name = provenance.get("primary_table") or "records"
                base_answer = f"There are **{val}** {entity_name} matching your criteria."
                return f"{base_answer}{provenance_md}"

        # Clean sample records to prevent prompt bloating (cap at 15 rows, truncate long text fields)
        sample_records = []
        for r in rows[:15]:
            if isinstance(r, dict):
                r_clean = {}
                for k, v in r.items():
                    if isinstance(v, str) and len(v) > 250:
                        r_clean[k] = v[:250] + "..."
                    else:
                        r_clean[k] = v
                sample_records.append(r_clean)
            elif isinstance(r, (list, tuple)):
                sample_records.append([
                    (v[:250] + "...") if isinstance(v, str) and len(v) > 250 else v
                    for v in r
                ])
            else:
                sample_records.append(r)

        system_prompt = """You are an intelligent PostgreSQL database assistant.
The user asked a database question. SQL was generated and executed against the database.
Your job is to provide a concise, clear, and comprehensive natural language summary with bullet points.

Guidelines:
1. Do NOT output raw JSON.
2. Directly answer the question with bullet points.
3. Highlight specific details like names, dates, statuses, numbers, and progress indicators.
4. Keep the answer concise, fast to read, and professional.
"""

        user_prompt = f"""Question: {question}

Executed SQL:
{sql}

Database Result ({row_count} total rows{' (truncated to first 200)' if truncated else ''}):
{json.dumps(sample_records, default=str, ensure_ascii=False)}

Please provide a clear and concise answer in natural language:"""

        chosen_model = model or getattr(settings, "model_answer", None) or getattr(settings, "chat_model", "deepseek-ai/DeepSeek-V3")
        client = cls._get_client()

        try:
            response = await client.chat.completions.create(
                model=chosen_model,
                temperature=0.2,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw_answer = (response.choices[0].message.content or "").strip()
            return f"{raw_answer}{provenance_md}"
        except Exception as exc:
            logger.error(f"[GroundedAnswerSynthesizer] LLM answer generation failed: {exc}")
            # Fallback summary
            fallback_answer = f"Query returned {row_count} rows: {json.dumps(sample_records[:5], default=str)}"
            return f"{fallback_answer}{provenance_md}"
