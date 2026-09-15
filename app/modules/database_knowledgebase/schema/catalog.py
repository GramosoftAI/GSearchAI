"""Schema Catalog Abstraction

Provides query and retrieval interfaces for canonical database schemas,
independent of live database execution.
"""

from typing import Optional, List, Dict
from ..schemas.canonical import DatabaseSchema, TableSchema, ColumnSchema, RelationshipSchema


class SchemaCatalog:
    """
    In-memory and cached catalog for a canonical database schema.
    """

    def __init__(self, schema: DatabaseSchema):
        self.schema = schema

    @property
    def fingerprint(self) -> str:
        return self.schema.fingerprint

    @property
    def database_name(self) -> str:
        return self.schema.database_name

    def list_tables(self, schema_name: str = "public") -> List[str]:
        """List table names within a schema namespace."""
        s = self.schema.get_schema(schema_name)
        return list(s.tables.keys()) if s else []

    def get_table(self, table_name: str, schema_name: str = "public") -> Optional[TableSchema]:
        """Retrieve table schema by name."""
        return self.schema.get_table(table_name, schema_name)

    def get_columns(self, table_name: str, schema_name: str = "public") -> Dict[str, ColumnSchema]:
        """Retrieve all column definitions for a table."""
        t = self.get_table(table_name, schema_name)
        return t.columns if t else {}

    def get_relationships(self, table_name: str, schema_name: str = "public") -> List[RelationshipSchema]:
        """Retrieve all relationships (foreign keys and references) for a table."""
        t = self.get_table(table_name, schema_name)
        return t.relationships if t else []

    def check_drift(self, other_fingerprint: str) -> bool:
        """Return True if schema has drifted compared to another version hash."""
        return self.schema.fingerprint != other_fingerprint
