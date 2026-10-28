"""Markdown Cheat Sheet Generator for NEW_DB

Generates AI-understandable Markdown documentation for tables and columns,
explicitly detailing business purpose, data types, sample values, primary keys,
and join paths so the SQL generator LLM writes accurate queries without hallucinating.
"""

import re
import logging
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI

from app.core.config import get_settings
from .schemas import TableInfo, CanonicalSchema

logger = logging.getLogger(__name__)
settings = get_settings()


class MarkdownDocGenerator:
    """Generates AI-understandable Markdown cheat sheets for database tables."""

    @classmethod
    def _get_client(cls) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=settings.deepinfra_api_key or "anonymous",
            base_url=settings.deepinfra_api_url or "https://api.deepinfra.com/v1/openai",
            timeout=60.0,
        )

    @classmethod
    def generate_table_markdown_deterministic(cls, table: TableInfo, all_tables: Optional[List[TableInfo]] = None) -> str:
        """
        Generate comprehensive, rich Markdown cheat sheet deterministically from table metadata.
        Fast, robust, and zero LLM latency overhead.
        """
        lines = []
        lines.append(f"# Table: {table.schema_name}.{table.table_name}")
        lines.append(f"**Schema:** `{table.schema_name}` | **Type:** `{'View' if table.is_view else 'Base Table'}`\n")

        # Inferred Business Description
        clean_name = table.table_name.replace("_", " ").title()
        lines.append(f"### Description\nStores record data for **{clean_name}** in the `{table.schema_name}` namespace.\n")

        # Columns Table
        lines.append("### Columns")
        lines.append("| Column | Data Type | Nullable | Role | Sample Values / Description |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")

        for col in table.columns:
            roles = []
            if col.is_primary_key:
                roles.append("PRIMARY KEY")
            if col.is_foreign_key:
                roles.append("FOREIGN KEY")
            role_str = ", ".join(roles) if roles else "Data Column"

            sample_str = ""
            if col.sample_values:
                sample_str = f"Values: {', '.join(col.sample_values[:5])}"

            lines.append(
                f"| `{col.name}` | `{col.data_type}` | `{'YES' if col.is_nullable else 'NO'}` | {role_str} | {sample_str} |"
            )

        lines.append("")

        # Foreign Keys & Explicit Join Syntax
        lines.append("### Relationships & Common Joins")
        has_joins = False

        if table.foreign_keys:
            has_joins = True
            for fk in table.foreign_keys:
                lines.append(
                    f"- **{table.table_name}.{fk.column_name}** ➔ **{fk.target_table}.{fk.target_column}**\n"
                    f"  ```sql\n"
                    f"  JOIN {fk.target_schema}.{fk.target_table} "
                    f"ON {table.table_name}.{fk.column_name} = {fk.target_table}.{fk.target_column}\n"
                    f"  ```"
                )

        # Detect Implicit Joins (e.g. assigned_to_id, user_id, author_id)
        table_lookup = {t.table_name.lower(): t for t in (all_tables or [])}
        for col in table.columns:
            c_low = col.name.lower()
            if (c_low.endswith("_id") or c_low.endswith("_id_id")) and not any(fk.column_name == col.name for fk in table.foreign_keys):
                stem = re.sub(r"_id(_id)?$", "", c_low)
                cand_tables = [stem, stem + "s", stem + "es"]
                if stem in ("assigned_to", "author", "creator", "user", "owner", "responsible"):
                    cand_tables.extend(["users", "user", "members", "employees"])

                target_tbl_name = next((t for t in cand_tables if t in table_lookup), None)
                if target_tbl_name and target_tbl_name != table.table_name.lower():
                    has_joins = True
                    lines.append(
                        f"- **Implicit Join:** `{table.table_name}.{col.name}` ➔ `{target_tbl_name}.id`\n"
                        f"  ```sql\n"
                        f"  JOIN {table.schema_name}.{target_tbl_name} "
                        f"ON {table.table_name}.{col.name} = {target_tbl_name}.id\n"
                        f"  ```"
                    )

        if not has_joins:
            lines.append("No explicit foreign keys declared.")

        lines.append("")

        # Query Guidelines
        lines.append("### Query Guidelines & Rules")
        lines.append(f"1. When querying `{table.table_name}`, always select relevant descriptive fields (`subject`, `description`, `name`, `status_id`).")
        lines.append(f"2. Always apply `LIMIT 50` unless an explicit aggregate like `COUNT(*)` is requested.")
        lines.append(f"3. When combining `OR` with `AND`, wrap the `OR` conditions in parentheses.")

        return "\n".join(lines)

    @classmethod
    async def enrich_table_with_llm(cls, table_doc: str, model: Optional[str] = None) -> str:
        """Optionally enhance deterministic Markdown doc using LLM for even richer business context."""
        chosen_model = model or getattr(settings, "model_extraction", "deepseek-ai/DeepSeek-V4-Flash")
        client = cls._get_client()

        prompt = (
            "You are a database architect. Review the following raw table documentation and add 2-3 sentences "
            "summarizing its exact real-world business purpose and common analytical queries. "
            "Keep the existing Markdown structure intact.\n\n"
            f"{table_doc}"
        )

        try:
            resp = await client.chat.completions.create(
                model=chosen_model,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )
            enhanced = (resp.choices[0].message.content or "").strip()
            return enhanced if len(enhanced) > 50 else table_doc
        except Exception as e:
            logger.debug(f"[NEW_DB] LLM enrichment skipped: {e}")
            return table_doc
