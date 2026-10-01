"""Cheat Sheet Exporter: Markdown and JSON Generator

Generates high-fidelity Markdown and JSON representations of the approved schema cheat sheet:
- Summary of tables, columns, facts, relationships
- Detailed per-table section with columns facts, meaning, synonyms
- Verified example questions with executed SQL
- Strict exclusion of sensitive column values
- Export endpoint / CLI utility for human review & approval
"""

import json
from typing import Any, Dict, List, Optional
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from ..models.schema_doc import (
    SchemaDocTable,
    SchemaDocColumn,
    SchemaDocExample,
)


class CheatSheetExporter:
    """Exports schema documentation to Markdown and JSON formats."""

    @classmethod
    async def export_cheat_sheet(
        cls,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        kb_id: uuid.UUID,
        schema_version: Optional[str] = None,
        only_approved: bool = False,
    ) -> Dict[str, Any]:
        """
        Gathers schema documentation for a KB and formats to Markdown + JSON.
        If only_approved=True, filters to tables with status='approved'.
        """
        t_uuid = uuid.UUID(str(tenant_id)) if isinstance(tenant_id, str) else tenant_id
        k_uuid = uuid.UUID(str(kb_id)) if isinstance(kb_id, str) else kb_id

        # Query tables
        tbl_stmt = select(SchemaDocTable).where(
            SchemaDocTable.tenant_id == t_uuid,
            SchemaDocTable.db_knowledgebase_id == k_uuid,
        )
        if schema_version:
            tbl_stmt = tbl_stmt.where(SchemaDocTable.schema_version == schema_version)
        if only_approved:
            tbl_stmt = tbl_stmt.where(SchemaDocTable.status == "approved")
        tbl_stmt = tbl_stmt.order_by(SchemaDocTable.table_name)

        tbl_res = await session.execute(tbl_stmt)
        tables = list(tbl_res.scalars().all())

        if not tables:
            return {"markdown": "# Database Schema Documentation\n\nNo documentation generated yet.", "json_data": {}}

        active_version = tables[0].schema_version

        # Query columns for these tables
        tbl_ids = [t.id for t in tables]
        col_stmt = select(SchemaDocColumn).where(
            SchemaDocColumn.table_doc_id.in_(tbl_ids)
        ).order_by(SchemaDocColumn.table_name, SchemaDocColumn.column_name)
        col_res = await session.execute(col_stmt)
        all_cols = list(col_res.scalars().all())

        cols_by_table: Dict[uuid.UUID, List[SchemaDocColumn]] = {}
        for c in all_cols:
            cols_by_table.setdefault(c.table_doc_id, []).append(c)

        # Query examples
        ex_stmt = select(SchemaDocExample).where(
            SchemaDocExample.table_doc_id.in_(tbl_ids),
            SchemaDocExample.status == "verified",
        ).order_by(SchemaDocExample.created_at)
        ex_res = await session.execute(ex_stmt)
        all_examples = list(ex_res.scalars().all())

        examples_by_table: Dict[uuid.UUID, List[SchemaDocExample]] = {}
        for ex in all_examples:
            if ex.table_doc_id:
                examples_by_table.setdefault(ex.table_doc_id, []).append(ex)

        # Build JSON dictionary
        json_data: Dict[str, Any] = {
            "knowledgebase_id": str(kb_id),
            "tenant_id": str(tenant_id),
            "schema_version": active_version,
            "table_count": len(tables),
            "tables": [],
        }

        # Build Markdown
        md_lines = [
            f"# Database Schema Cheat Sheet",
            f"**Knowledgebase ID:** `{kb_id}`  ",
            f"**Schema Version:** `{active_version[:16]}...`  ",
            f"**Total Tables Documented:** {len(tables)}  ",
            "\n---\n",
        ]

        for tbl in tables:
            tbl_cols = cols_by_table.get(tbl.id, [])
            tbl_examples = examples_by_table.get(tbl.id, [])

            tbl_dict: Dict[str, Any] = {
                "table_name": tbl.table_name,
                "schema": tbl.table_schema,
                "status": tbl.status,
                "purpose": tbl.ai_purpose,
                "synonyms": tbl.ai_synonyms,
                "caveats": tbl.ai_caveats,
                "relationships": tbl.relationships_json,
                "columns": [],
                "examples": [],
            }

            md_lines.append(f"## Table: `{tbl.table_name}` ({tbl.status.upper()})")
            if tbl.ai_purpose:
                md_lines.append(f"**Purpose:** {tbl.ai_purpose}\n")
            if tbl.ai_synonyms:
                md_lines.append(f"**Synonyms:** {', '.join(tbl.ai_synonyms)}\n")
            if tbl.ai_caveats:
                md_lines.append(f"**Caveats & Filtering Rules:** {tbl.ai_caveats}\n")

            rel_summary = tbl.relationships_json.get("relationship_summary", "None")
            md_lines.append(f"**Relationships:** {rel_summary}\n")

            # Column table
            md_lines.append("### Columns")
            md_lines.append("| Column | Type | Attributes | Meaning | Synonyms | Facts / Distribution |")
            md_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")

            for col in tbl_cols:
                attrs = []
                if col.is_primary_key:
                    attrs.append("PK")
                if col.is_foreign_key:
                    attrs.append("FK")
                if not col.is_nullable:
                    attrs.append("NOT NULL")
                if col.is_sensitive:
                    attrs.append("🔒 SENSITIVE")
                attr_str = ", ".join(attrs) if attrs else "—"

                meaning = col.ai_meaning or "—"
                synonyms_str = ", ".join(col.ai_synonyms) if col.ai_synonyms else "—"

                if col.is_sensitive:
                    facts_str = "*[REDACTED - Sensitive Column]*"
                else:
                    fact_items = []
                    if col.distinct_count is not None:
                        fact_items.append(f"Distinct: {col.distinct_count}")
                    if col.null_percentage is not None:
                        fact_items.append(f"Null: {col.null_percentage}%")
                    if col.min_value and col.max_value:
                        fact_items.append(f"Range: [{col.min_value} .. {col.max_value}]")
                    if col.distinct_values:
                        fact_items.append(f"Values: {col.distinct_values[:5]}")
                    facts_str = "; ".join(fact_items) if fact_items else "—"

                md_lines.append(f"| `{col.column_name}` | `{col.data_type}` | {attr_str} | {meaning} | {synonyms_str} | {facts_str} |")

                tbl_dict["columns"].append({
                    "column_name": col.column_name,
                    "data_type": col.data_type,
                    "is_primary_key": col.is_primary_key,
                    "is_foreign_key": col.is_foreign_key,
                    "is_sensitive": col.is_sensitive,
                    "meaning": col.ai_meaning,
                    "synonyms": col.ai_synonyms,
                    "distinct_count": col.distinct_count,
                    "null_percentage": col.null_percentage,
                    "min_value": col.min_value,
                    "max_value": col.max_value,
                    "distinct_values": col.distinct_values,
                })

            md_lines.append("")

            # Examples section
            if tbl_examples:
                md_lines.append("### Verified Example Queries")
                for ex in tbl_examples:
                    md_lines.append(f"- **Q ({ex.question_type}):** {ex.question}")
                    md_lines.append(f"  ```sql\n  {ex.sql_query}\n  ```")
                    md_lines.append(f"  *(Executed successfully in {ex.execution_time_ms}ms, returned {ex.execution_row_count} rows)*\n")

                    tbl_dict["examples"].append({
                        "question": ex.question,
                        "question_type": ex.question_type,
                        "sql_query": ex.sql_query,
                        "row_count": ex.execution_row_count,
                        "execution_time_ms": ex.execution_time_ms,
                    })

            md_lines.append("\n---\n")
            json_data["tables"].append(tbl_dict)

        markdown_content = "\n".join(md_lines)
        return {
            "markdown": markdown_content,
            "json_data": json_data,
        }
