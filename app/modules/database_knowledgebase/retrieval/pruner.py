"""Hierarchical Sub-Schema Pruning & Context Formatting

Prunes large canonical schemas into minimal, compact, and token-bounded sub-schemas
suitable for downstream LLMs, with prompt-injection security encapsulation.
"""

from typing import Dict, List, Set, Tuple
from ..schemas.canonical import (
    DatabaseSchema,
    SchemaInfo,
    TableSchema,
    ColumnSchema,
    RelationshipSchema,
)
from .scorer import TableRetrievalScore
from ..security.boundary import wrap_untrusted_metadata


class SchemaPruner:
    """
    Prunes canonical database schema into a compact sub-schema containing only
    relevant tables, essential columns (PKs, FKs, matched columns), and active joins.
    """

    @classmethod
    def prune_schema(
        cls,
        canonical_schema: DatabaseSchema,
        selected_scores: Dict[str, TableRetrievalScore],
        active_relationships: List[RelationshipSchema],
        top_k_columns_per_table: int = 25,
    ) -> Tuple[List[TableSchema], List[RelationshipSchema], str]:
        """
        Produce pruned TableSchema list, relevant relationships, and untrusted XML boundary text.

        Returns:
            Tuple of (pruned_tables, pruned_relationships, untrusted_xml_context)
        """
        pruned_tables: List[TableSchema] = []
        selected_table_keys = set(selected_scores.keys())

        # Determine which foreign keys are actively used between selected tables
        used_fk_cols_by_table: Dict[str, Set[str]] = {}
        for rel in active_relationships:
            src_key = f"{rel.source_schema}.{rel.source_table}"
            tgt_key = f"{rel.target_schema}.{rel.target_table}"

            if src_key not in used_fk_cols_by_table:
                used_fk_cols_by_table[src_key] = set()
            if tgt_key not in used_fk_cols_by_table:
                used_fk_cols_by_table[tgt_key] = set()

            used_fk_cols_by_table[src_key].update(rel.source_columns)
            used_fk_cols_by_table[tgt_key].update(rel.target_columns)

        # Build pruned table representations
        for s_name, s_info in canonical_schema.schemas.items():
            for t_name, orig_table in s_info.tables.items():
                t_key = f"{orig_table.schema_name}.{orig_table.table_name}"
                if t_key not in selected_table_keys:
                    continue

                score_info = selected_scores[t_key]
                pk_cols = set(orig_table.primary_key_columns)
                active_fk_cols = used_fk_cols_by_table.get(t_key, set())
                matched_cols = set(score_info.matched_columns)

                # Prioritize columns: PKs first, active FKs second, matched columns third, then others
                mandatory_cols = pk_cols | active_fk_cols | matched_cols

                ordered_col_names: List[str] = []
                for c in orig_table.primary_key_columns:
                    if c not in ordered_col_names and c in orig_table.columns:
                        ordered_col_names.append(c)

                for c in sorted(list(active_fk_cols)):
                    if c not in ordered_col_names and c in orig_table.columns:
                        ordered_col_names.append(c)

                for c in score_info.matched_columns:
                    if c not in ordered_col_names and c in orig_table.columns:
                        ordered_col_names.append(c)

                for c_name in orig_table.columns.keys():
                    if c_name not in ordered_col_names:
                        if len(ordered_col_names) < top_k_columns_per_table:
                            ordered_col_names.append(c_name)

                # Construct pruned columns dict capped strictly at top_k_columns_per_table
                capped_col_names = ordered_col_names[:top_k_columns_per_table]
                pruned_cols: Dict[str, ColumnSchema] = {}
                for c_name in capped_col_names:
                    pruned_cols[c_name] = orig_table.columns[c_name]

                # Filter foreign keys to only those referencing selected tables
                pruned_fks = []
                for fk in orig_table.foreign_keys:
                    ref_key = f"{fk.referred_schema}.{fk.referred_table}"
                    if ref_key in selected_table_keys:
                        pruned_fks.append(fk)

                pruned_table = TableSchema(
                    table_name=orig_table.table_name,
                    schema_name=orig_table.schema_name,
                    table_type=orig_table.table_type,
                    columns=pruned_cols,
                    primary_key=orig_table.primary_key,
                    foreign_keys=pruned_fks,
                    indexes=orig_table.indexes,
                    comment=orig_table.comment,
                )
                pruned_tables.append(pruned_table)

        # Format sub-schema XML text
        raw_xml_parts = [
            f"<database name=\"{canonical_schema.database_name}\" type=\"{canonical_schema.database_type}\">"
        ]

        for tbl in pruned_tables:
            raw_xml_parts.append(
                f"  <table name=\"{tbl.table_name}\" schema=\"{tbl.schema_name}\">"
            )
            if tbl.comment:
                raw_xml_parts.append(f"    <!-- comment: {tbl.comment} -->")

            for c_name, col in tbl.columns.items():
                flags = []
                if col.is_primary_key:
                    flags.append("PK")
                if col.is_foreign_key:
                    flags.append("FK")
                flag_str = f" [{', '.join(flags)}]" if flags else ""
                col_comment = f" -- {col.comment}" if col.comment else ""
                raw_xml_parts.append(
                    f"    <column name=\"{c_name}\" type=\"{col.raw_data_type}\"{flag_str}/>{col_comment}"
                )

            for fk in tbl.foreign_keys:
                raw_xml_parts.append(
                    f"    <foreign_key name=\"{fk.name}\" columns=\"{', '.join(fk.constrained_columns)}\" "
                    f"references=\"{fk.referred_schema}.{fk.referred_table}({', '.join(fk.referred_columns)})\"/>"
                )

            raw_xml_parts.append("  </table>")

        # Prune active relationships to only those connecting the selected tables
        selected_base_tables = {t_key.split(".")[-1] for t_key in selected_table_keys}
        pruned_active_rels: List[RelationshipSchema] = []
        for rel in active_relationships:
            src_full = f"{rel.source_schema}.{rel.source_table}"
            tgt_full = f"{rel.target_schema}.{rel.target_table}"
            if (src_full in selected_table_keys or rel.source_table in selected_base_tables) and (
                tgt_full in selected_table_keys or rel.target_table in selected_base_tables
            ):
                pruned_active_rels.append(rel)

        if pruned_active_rels:
            raw_xml_parts.append("  <relationships>")
            for rel in pruned_active_rels:
                raw_xml_parts.append(
                    f"    <join type=\"{rel.relationship_type.value}\" "
                    f"from=\"{rel.source_schema}.{rel.source_table}({', '.join(rel.source_columns)})\" "
                    f"to=\"{rel.target_schema}.{rel.target_table}({', '.join(rel.target_columns)})\"/>"
                )
            raw_xml_parts.append("  </relationships>")

        raw_xml_parts.append("</database>")

        raw_schema_text = "\n".join(raw_xml_parts)
        untrusted_xml = wrap_untrusted_metadata(raw_schema_text)

        return pruned_tables, pruned_active_rels, untrusted_xml
