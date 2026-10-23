"""AI-Understandable Schema Markdown Document Generator

Transforms canonical TableSchema and DatabaseSchema objects into rich,
structured Markdown documents optimized for LLM semantic understanding,
vector indexing, and text-to-SQL generation.
Inspired by D:\\DB\\main architecture.
"""

import re
from typing import List, Dict, Any, Optional
from ..schemas.canonical import TableSchema, DatabaseSchema, ColumnSchema


def split_markdown(text: str, max_chars: int = 1500, overlap: int = 150) -> List[str]:
    """
    Chunk Markdown while retaining a small overlap for context and fitting
    comfortably within embedding token limits (e.g. BAAI/bge-large-en-v1.5).
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    paragraphs = re.split(r"\n\s*\n", text)
    chunks: List[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            start = 0
            while start < len(para):
                end = min(start + max_chars, len(para))
                chunks.append(para[start:end].strip())
                if end == len(para):
                    break
                start = end - overlap
            continue

        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current.strip())
            tail = current[-overlap:] if current else ""
            current = f"{tail}\n\n{para}".strip() if tail else para
    if current:
        chunks.append(current.strip())
    return [c for c in chunks if c]


class SchemaMarkdownGenerator:
    """Generates structured, AI-understandable Markdown documentation for tables."""

    @classmethod
    def generate_table_markdown(cls, table: TableSchema) -> str:
        """
        Generate complete, human- and LLM-readable Markdown documentation for a table.
        Includes table facts, full column specifications, constraints, foreign keys,
        and indexes.
        """
        schema_name = table.schema_name or "public"
        table_name = table.table_name
        lines = [
            f"# {schema_name}.{table_name}",
            "",
            f"- **Object type:** {table.table_type or 'BASE TABLE'}",
            f"- **Schema:** `{schema_name}`",
            f"- **Table:** `{table_name}`",
            f"- **Description:** {table.comment or 'Not documented'}",
            f"- **Column count:** {len(table.columns)}",
            "",
            "## Columns",
            "",
            "| # | Column | Data type | Nullable | Default | Description |",
            "|---:|---|---|---|---|---|",
        ]

        # Sort columns by ordinal position if available, else name
        sorted_cols = sorted(
            table.columns.values(),
            key=lambda c: (c.ordinal_position if c.ordinal_position > 0 else 999, c.name),
        )

        for idx, col in enumerate(sorted_cols, 1):
            dtype = col.raw_data_type or (col.data_type.value if hasattr(col.data_type, "value") else str(col.data_type))
            nullable = "YES" if col.is_nullable else "NO"
            default = str(col.default_value or "").replace("|", "\\|").replace("\n", " ")
            desc = col.comment or ""
            if col.is_primary_key:
                desc = f"PRIMARY KEY. {desc}".strip()
            elif col.is_foreign_key:
                desc = f"FOREIGN KEY. {desc}".strip()

            lines.append(f"| {idx} | `{col.name}` | {dtype} | {nullable} | {default} | {desc} |")

        lines.extend(["", "## Constraints and Relationships", ""])
        has_constraints = False

        if table.primary_key and table.primary_key.constrained_columns:
            pk_cols = ", ".join(f"`{c}`" for c in table.primary_key.constrained_columns)
            lines.append(f"- PRIMARY KEY ({pk_cols})")
            has_constraints = True

        for fk in table.foreign_keys:
            src_cols = ", ".join(f"`{c}`" for c in fk.constrained_columns)
            tgt_ref = f"`{fk.referred_schema}.{fk.referred_table}`({', '.join(f'`{c}`' for c in fk.referred_columns)})"
            fk_name_info = f" (constraint `{fk.name}`)" if fk.name else ""
            lines.append(f"- FOREIGN KEY ({src_cols}) REFERENCES {tgt_ref}{fk_name_info}")
            has_constraints = True

        # Fallback to relationship models if foreign_keys is empty
        if not table.foreign_keys and table.relationships:
            for rel in table.relationships:
                src_cols = ", ".join(f"`{c}`" for c in rel.source_columns)
                tgt_ref = f"`{rel.target_schema}.{rel.target_table}`({', '.join(f'`{c}`' for c in rel.target_columns)})"
                lines.append(f"- FOREIGN KEY ({src_cols}) REFERENCES {tgt_ref} [{rel.relationship_type}]")
                has_constraints = True

        if not has_constraints:
            lines.append("- No foreign key constraints discovered.")

        if table.indexes:
            lines.extend(["", "## Indexes", ""])
            for idx in table.indexes:
                cols_str = ", ".join(idx.column_names)
                unique_str = "UNIQUE " if idx.is_unique else ""
                lines.append(f"- **{idx.name}:** {unique_str}INDEX on ({cols_str})")

        lines.extend([
            "",
            "## Semantic Notes",
            "",
            "Business meaning and column usage should be interpreted accurately according to the table columns and constraints.",
            "Always prefer documented primary and foreign keys for multi-table relationships.",
            "",
        ])

        return "\n".join(lines)

    generate_table_document = generate_table_markdown

    @classmethod
    def generate_all_table_documents(
        cls, schema: DatabaseSchema
    ) -> List[Dict[str, Any]]:
        """
        Generate a list of document dicts ready for chunking and vector indexing.
        Each dict has: text, source, title, chunk_index, table_name, schema_name.
        """
        all_docs: List[Dict[str, Any]] = []

        for schema_name, s_info in schema.schemas.items():
            for table_name, table in s_info.tables.items():
                full_md = cls.generate_table_markdown(table)
                chunks = split_markdown(full_md, max_chars=1500, overlap=150)
                
                for idx, chunk in enumerate(chunks):
                    first_line = chunk.splitlines()[0].lstrip("# ").strip() if chunk.splitlines() else table_name
                    all_docs.append({
                        "text": chunk,
                        "source": f"{schema_name}/{table_name}.md",
                        "title": first_line[:250],
                        "chunk_index": idx,
                        "schema_name": schema_name,
                        "table_name": table_name,
                        "entity_key": f"{schema_name}.{table_name}",
                        "is_primary_chunk": (idx == 0),
                        "column_names": [c.name for c in table.columns.values()],
                    })

        return all_docs
