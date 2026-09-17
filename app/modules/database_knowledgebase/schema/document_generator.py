"""Schema Document Generator: Transforms Canonical Schema into Semantic Documents

Extracts and serializes:
1. DatabaseDocument
2. SchemaDocument
3. TableDocuments
4. ColumnDocuments
5. RelationshipDocuments

Strictly separates technical facts from business metadata and builds dense embedding text.
"""

from typing import List, Union, Optional, Dict, Tuple, Any
from ..schemas.canonical import (
    DatabaseSchema,
    SchemaInfo,
    TableSchema,
    ColumnSchema,
    RelationshipSchema,
    RelationshipType,
)
from ..schemas.documents import (
    BaseSchemaDocument,
    DatabaseDocument,
    DatabaseTechnicalFacts,
    DatabaseBusinessSemantics,
    SchemaDocument,
    SchemaTechnicalFacts,
    SchemaBusinessSemantics,
    TableDocument,
    TableTechnicalFacts,
    TableBusinessSemantics,
    ColumnDocument,
    ColumnTechnicalFacts,
    ColumnBusinessSemantics,
    RelationshipDocument,
    RelationshipTechnicalFacts,
    RelationshipBusinessSemantics,
    SchemaDocumentType,
)


class SchemaDocumentGenerator:
    """Generates structured semantic documents from a canonical DatabaseSchema."""

    @classmethod
    def generate_all_documents(
        cls,
        schema: DatabaseSchema,
        database_description: str = "",
        glossary_entries: Optional[Dict[Tuple[str, str], Any]] = None,
    ) -> List[BaseSchemaDocument]:
        """Generate full hierarchy of semantic schema documents from canonical DatabaseSchema."""
        documents: List[BaseSchemaDocument] = []

        all_schemas = list(schema.schemas.keys())
        total_tables = sum(len(s.tables) for s in schema.schemas.values())

        # 1. Database Document
        db_doc = cls.generate_database_document(schema, database_description)
        documents.append(db_doc)

        seen_rel_keys = set()
        for s_name, s_info in schema.schemas.items():
            # 2. Schema Document
            schema_doc = cls.generate_schema_document(s_name, s_info)
            documents.append(schema_doc)

            # 3. Table & Column Documents
            for t_name, table in s_info.tables.items():
                table_doc = cls.generate_table_document(table)
                documents.append(table_doc)

                for c_name, col in table.columns.items():
                    glossary_entry = None
                    if glossary_entries:
                        glossary_entry = glossary_entries.get((table.table_name, col.name))
                    col_doc = cls.generate_column_document(table, col, glossary_entry=glossary_entry)
                    documents.append(col_doc)

                # 4. Relationship Documents from table relationships or foreign keys
                if table.relationships:
                    for rel in table.relationships:
                        rel_key = f"{rel.source_schema}.{rel.source_table}->{rel.target_schema}.{rel.target_table}:{','.join(rel.source_columns)}"
                        if rel_key not in seen_rel_keys:
                            seen_rel_keys.add(rel_key)
                            rel_doc = cls.generate_relationship_document(rel)
                            documents.append(rel_doc)
                else:
                    for fk in table.foreign_keys:
                        rel_key = f"{table.schema_name}.{table.table_name}->{fk.referred_schema}.{fk.referred_table}:{','.join(fk.constrained_columns)}"
                        if rel_key not in seen_rel_keys:
                            seen_rel_keys.add(rel_key)
                            rel = RelationshipSchema(
                                source_schema=table.schema_name,
                                source_table=table.table_name,
                                source_columns=fk.constrained_columns,
                                target_schema=fk.referred_schema,
                                target_table=fk.referred_table,
                                target_columns=fk.referred_columns,
                                foreign_key_name=fk.name,
                                relationship_type=RelationshipType.MANY_TO_ONE,
                            )
                            rel_doc = cls.generate_relationship_document(rel)
                            documents.append(rel_doc)

        return documents

    @classmethod
    def generate_database_document(
        cls,
        schema: DatabaseSchema,
        description: str = "",
    ) -> DatabaseDocument:
        all_schemas = sorted(list(schema.schemas.keys()))
        all_tables = []
        for s_info in schema.schemas.values():
            all_tables.extend([f"{s_info.schema_name}.{t}" for t in sorted(s_info.tables.keys())])

        total_tables = len(all_tables)
        total_relationships = sum(len(t.relationships) + len(t.foreign_keys) for s in schema.schemas.values() for t in s.tables.values())

        tech_facts = DatabaseTechnicalFacts(
            database_name=schema.database_name,
            database_type=schema.database_type,
            schema_names=all_schemas,
            table_count=total_tables,
            relationship_count=total_relationships,
        )
        business_semantics = DatabaseBusinessSemantics(
            description=description or f"{schema.database_type.capitalize()} database '{schema.database_name}'",
            comment=None,
        )

        embed_text = (
            f"Database: {schema.database_name} | Type: {schema.database_type} | "
            f"Schemas: {', '.join(all_schemas)} | Tables ({total_tables}): {', '.join(all_tables[:30])} | "
            f"Description: {business_semantics.description}"
        )

        return DatabaseDocument(
            entity_key=f"db:{schema.database_name}",
            embedding_text=embed_text,
            technical_facts=tech_facts,
            business_semantics=business_semantics,
        )

    @classmethod
    def generate_schema_document(
        cls,
        schema_name: str,
        schema_info: SchemaInfo,
    ) -> SchemaDocument:
        table_names = sorted(list(schema_info.tables.keys()))
        tech_facts = SchemaTechnicalFacts(
            schema_name=schema_name,
            tables=table_names,
            table_count=len(table_names),
        )
        business_semantics = SchemaBusinessSemantics(
            description=f"Schema '{schema_name}' containing {len(table_names)} tables.",
            comment=None,
        )

        embed_text = (
            f"Schema: {schema_name} | Tables ({len(table_names)}): {', '.join(table_names)} | "
            f"Description: {business_semantics.description}"
        )

        return SchemaDocument(
            entity_key=f"schema:{schema_name}",
            embedding_text=embed_text,
            technical_facts=tech_facts,
            business_semantics=business_semantics,
        )

    @classmethod
    def generate_table_document(
        cls,
        table: TableSchema,
    ) -> TableDocument:
        pk_cols = table.primary_key_columns
        col_names = sorted(list(table.columns.keys()))
        
        fk_refs = []
        for fk in table.foreign_keys:
            src = ", ".join(fk.constrained_columns)
            tgt = f"{fk.referred_schema}.{fk.referred_table}.{', '.join(fk.referred_columns)}"
            fk_refs.append(f"{src} -> {tgt}")

        idx_cols = []
        for idx in table.indexes:
            idx_cols.extend(idx.column_names)
        idx_cols = sorted(list(set(idx_cols)))

        tech_facts = TableTechnicalFacts(
            schema_name=table.schema_name,
            table_name=table.table_name,
            table_type=table.table_type,
            primary_key_columns=pk_cols,
            foreign_key_references=fk_refs,
            column_names=col_names,
            indexed_columns=idx_cols,
        )
        business_semantics = TableBusinessSemantics(
            comment=table.comment,
            synonyms=[],
        )

        parts = [
            f"Table: {table.schema_name}.{table.table_name}",
            f"Columns: {', '.join(col_names)}",
        ]
        if pk_cols:
            parts.append(f"Primary Key: {', '.join(pk_cols)}")
        if fk_refs:
            parts.append(f"Foreign Keys: {'; '.join(fk_refs)}")
        if table.comment:
            parts.append(f"Comment: {table.comment}")

        embed_text = " | ".join(parts)

        return TableDocument(
            entity_key=f"{table.schema_name}.{table.table_name}",
            embedding_text=embed_text,
            technical_facts=tech_facts,
            business_semantics=business_semantics,
        )

    @classmethod
    def generate_column_document(
        cls,
        table: TableSchema,
        col: ColumnSchema,
        glossary_entry: Optional[Any] = None,
    ) -> ColumnDocument:
        fk_target = None
        for fk in table.foreign_keys:
            if col.name in fk.constrained_columns:
                fk_target = f"{fk.referred_schema}.{fk.referred_table}.{', '.join(fk.referred_columns)}"
                break

        tech_facts = ColumnTechnicalFacts(
            schema_name=table.schema_name,
            table_name=table.table_name,
            column_name=col.name,
            data_type=col.data_type,
            raw_data_type=col.raw_data_type,
            is_primary_key=col.is_primary_key,
            is_foreign_key=col.is_foreign_key,
            is_nullable=col.is_nullable,
            foreign_key_target=fk_target,
        )

        # LOAD-BEARING GUARANTEE: strictly require is_published=True
        if glossary_entry is not None and getattr(glossary_entry, "is_published", False) is True:
            desc = getattr(glossary_entry, "business_description", "") or col.comment or ""
            synonyms = getattr(glossary_entry, "synonyms", []) or []
            role = getattr(glossary_entry, "semantic_role", "")

            business_semantics = ColumnBusinessSemantics(
                comment=desc if desc else None,
                synonyms=synonyms,
            )

            parts = [
                f"Column: {table.schema_name}.{table.table_name}.{col.name}",
                f"Description: {desc}",
            ]
            if synonyms:
                parts.append(f"Synonyms: {', '.join(synonyms)}")
            if role and role != "UNKNOWN":
                parts.append(f"Role: {role}")
            if col.is_primary_key:
                parts.append("PRIMARY KEY")
            if col.is_foreign_key and fk_target:
                parts.append(f"FOREIGN KEY -> {fk_target}")
        else:
            business_semantics = ColumnBusinessSemantics(
                comment=col.comment,
                synonyms=[],
            )

            parts = [
                f"Column: {table.schema_name}.{table.table_name}.{col.name}",
                f"Type: {col.data_type.value.lower()} ({col.raw_data_type})",
                f"Table: {table.table_name}",
            ]
            if col.is_primary_key:
                parts.append("PRIMARY KEY")
            if col.is_foreign_key and fk_target:
                parts.append(f"FOREIGN KEY -> {fk_target}")
            if col.comment:
                parts.append(f"Comment: {col.comment}")

        embed_text = " | ".join(parts)

        return ColumnDocument(
            entity_key=f"{table.schema_name}.{table.table_name}.{col.name}",
            embedding_text=embed_text,
            technical_facts=tech_facts,
            business_semantics=business_semantics,
        )

    @classmethod
    def generate_relationship_document(
        cls,
        rel: RelationshipSchema,
    ) -> RelationshipDocument:
        tech_facts = RelationshipTechnicalFacts(
            relationship_type=rel.relationship_type,
            source_schema=rel.source_schema,
            source_table=rel.source_table,
            source_columns=rel.source_columns,
            target_schema=rel.target_schema,
            target_table=rel.target_table,
            target_columns=rel.target_columns,
            foreign_key_name=rel.foreign_key_name,
        )
        business_semantics = RelationshipBusinessSemantics(
            description=rel.description or (
                f"{rel.source_schema}.{rel.source_table} connects to "
                f"{rel.target_schema}.{rel.target_table} ({rel.relationship_type.value})"
            ),
        )

        embed_text = (
            f"Relationship: {rel.source_schema}.{rel.source_table} ({', '.join(rel.source_columns)}) -> "
            f"{rel.target_schema}.{rel.target_table} ({', '.join(rel.target_columns)}) | "
            f"Type: {rel.relationship_type.value} | Description: {business_semantics.description}"
        )

        entity_key = f"rel:{rel.source_schema}.{rel.source_table}->{rel.target_schema}.{rel.target_table}"

        return RelationshipDocument(
            entity_key=entity_key,
            embedding_text=embed_text,
            technical_facts=tech_facts,
            business_semantics=business_semantics,
        )
