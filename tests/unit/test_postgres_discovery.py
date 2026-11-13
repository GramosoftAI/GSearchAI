import pytest
from app.modules.database_knowledgebase.schemas.canonical import (
    DatabaseSchema, SchemaSnapshot, TableSchema, ColumnSchema, IndexSchema, ColumnDataType
)
from app.modules.database_knowledgebase.discovery.postgres_discovery import PostgresDiscoveryService

def test_from_canonical_schema_indexes():
    # Create canonical schema with one table, PK index, and unique index
    table = TableSchema(
        schema_name="public",
        table_name="users",
        columns={
            "id": ColumnSchema(
                name="id",
                data_type=ColumnDataType.INTEGER,
                raw_data_type="int4",
                is_nullable=False,
                is_primary_key=True
            ),
            "email": ColumnSchema(
                name="email",
                data_type=ColumnDataType.VARCHAR,
                raw_data_type="varchar",
                is_nullable=False
            )
        },
        indexes=[
            IndexSchema(
                name="users_pkey",
                column_names=["id"],
                is_unique=True,
                is_primary=True
            ),
            IndexSchema(
                name="users_email_key",
                column_names=["email"],
                is_unique=True,
                is_primary=False
            )
        ]
    )
    
    schema = DatabaseSchema(
        database_name="test_db",
        database_type="postgresql",
        schemas={"public": SchemaSnapshot(tables={"users": table})}
    )
    
    # Convert
    catalog = PostgresDiscoveryService.from_canonical_schema(schema)
    
    # Assert
    assert len(catalog.tables) == 1
    discovered_table = catalog.tables["public.users"]
    assert len(discovered_table.indexes) == 2
    
    idx_pkey = next(i for i in discovered_table.indexes if i.index_name == "users_pkey")
    assert idx_pkey.columns == ["id"]
    assert idx_pkey.is_unique is True
    assert idx_pkey.index_type == "btree"
    
    idx_email = next(i for i in discovered_table.indexes if i.index_name == "users_email_key")
    assert idx_email.columns == ["email"]
    assert idx_email.is_unique is True
    assert idx_email.index_type == "btree"
