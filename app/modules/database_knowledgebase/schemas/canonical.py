"""Canonical Normalized Relational Schema Representation

Provides an engine-independent, structured, deterministic representation of relational
database metadata. Designed for schema retrieval, LLM context construction,
security policy enforcement, and offline schema cataloging.
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


class ColumnDataType(str, Enum):
    """Normalized canonical relational data types."""
    INTEGER = "INTEGER"
    BIGINT = "BIGINT"
    SMALLINT = "SMALLINT"
    NUMERIC = "NUMERIC"
    DECIMAL = "DECIMAL"
    FLOAT = "FLOAT"
    REAL = "REAL"
    DOUBLE = "DOUBLE"
    VARCHAR = "VARCHAR"
    TEXT = "TEXT"
    CHAR = "CHAR"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    TIMESTAMP = "TIMESTAMP"
    TIMESTAMPTZ = "TIMESTAMPTZ"
    TIME = "TIME"
    JSON = "JSON"
    JSONB = "JSONB"
    UUID = "UUID"
    ARRAY = "ARRAY"
    BYTEA = "BYTEA"
    OTHER = "OTHER"


class ColumnSchema(BaseModel):
    """Canonical representation of a table column."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Column name")
    data_type: ColumnDataType = Field(..., description="Normalized canonical data type")
    raw_data_type: str = Field(..., description="Engine-specific native data type string (e.g. 'character varying(255)')")
    is_nullable: bool = Field(default=True, description="Whether column permits NULL values")
    default_value: Optional[str] = Field(default=None, description="Column default expression or value")
    is_primary_key: bool = Field(default=False, description="Whether column is part of the primary key")
    is_foreign_key: bool = Field(default=False, description="Whether column references another table")
    comment: Optional[str] = Field(default=None, description="Database comment / description for this column")
    ordinal_position: int = Field(default=0, description="1-indexed column position in table")
    extra_metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional engine metadata")


class PrimaryKeySchema(BaseModel):
    """Canonical representation of a primary key constraint."""
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, description="Constraint name")
    constrained_columns: List[str] = Field(..., min_length=1, description="List of column names forming the primary key")


class ForeignKeySchema(BaseModel):
    """Canonical representation of a foreign key constraint."""
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, description="Constraint name")
    constrained_columns: List[str] = Field(..., min_length=1, description="Source table column names")
    referred_schema: str = Field(default="public", description="Referenced schema name")
    referred_table: str = Field(..., min_length=1, description="Referenced target table name")
    referred_columns: List[str] = Field(..., min_length=1, description="Referenced target column names")
    on_delete: Optional[str] = Field(default=None, description="ON DELETE action rule (e.g. CASCADE, RESTRICT)")
    on_update: Optional[str] = Field(default=None, description="ON UPDATE action rule")


class RelationshipType(str, Enum):
    """Semantic relationship cardinalities."""
    ONE_TO_MANY = "ONE_TO_MANY"
    MANY_TO_ONE = "MANY_TO_ONE"
    ONE_TO_ONE = "ONE_TO_ONE"
    MANY_TO_MANY = "MANY_TO_MANY"


class RelationshipSchema(BaseModel):
    """Normalized relationship between two tables derived from foreign keys."""
    model_config = ConfigDict(extra="forbid")

    source_schema: str = Field(default="public")
    source_table: str = Field(..., description="Source table name")
    source_columns: List[str] = Field(..., description="Source column names")
    target_schema: str = Field(default="public")
    target_table: str = Field(..., description="Target table name")
    target_columns: List[str] = Field(..., description="Target column names")
    relationship_type: RelationshipType = Field(default=RelationshipType.MANY_TO_ONE)
    foreign_key_name: Optional[str] = None
    description: Optional[str] = None


class IndexSchema(BaseModel):
    """Canonical representation of a database index."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Index name")
    column_names: List[str] = Field(..., description="Indexed column names in order")
    is_unique: bool = Field(default=False, description="Whether index enforces uniqueness")
    is_primary: bool = Field(default=False, description="Whether index backs the primary key")


class TableSchema(BaseModel):
    """Canonical representation of a relational table or view."""
    model_config = ConfigDict(extra="forbid")

    schema_name: str = Field(default="public", description="Schema / namespace name")
    table_name: str = Field(..., min_length=1, description="Table name")
    table_type: str = Field(default="TABLE", description="Object type: TABLE or VIEW")
    comment: Optional[str] = Field(default=None, description="Database comment / description for this table")
    columns: Dict[str, ColumnSchema] = Field(default_factory=dict, description="Dictionary of columns keyed by column name")
    primary_key: Optional[PrimaryKeySchema] = Field(default=None, description="Primary key constraint")
    foreign_keys: List[ForeignKeySchema] = Field(default_factory=list, description="Foreign key constraints")
    relationships: List[RelationshipSchema] = Field(default_factory=list, description="Computed relational links")
    indexes: List[IndexSchema] = Field(default_factory=list, description="Indexes defined on this table")
    row_count_estimate: Optional[int] = Field(default=None, description="Optional metadata row count estimate (without full scan)")

    def get_column(self, col_name: str) -> Optional[ColumnSchema]:
        return self.columns.get(col_name)

    @property
    def name(self) -> str:
        return self.table_name

    @property
    def primary_key_columns(self) -> List[str]:
        if self.primary_key:
            return self.primary_key.constrained_columns
        return [c.name for c in self.columns.values() if c.is_primary_key]

    @property
    def has_primary_key(self) -> bool:
        return bool(self.primary_key and self.primary_key.constrained_columns) or any(c.is_primary_key for c in self.columns.values())

    @property
    def has_declared_fk(self) -> bool:
        return bool(self.foreign_keys) or any(c.is_foreign_key for c in self.columns.values())

    @property
    def has_id_like_fk_columns(self) -> bool:
        import re
        id_pattern = re.compile(r"(_id|_id_id)$", re.IGNORECASE)
        for col_name in self.columns.keys():
            if col_name.lower() in ("id", "pk"):
                continue
            if id_pattern.search(col_name):
                return True
        return False


class SchemaInfo(BaseModel):
    """Catalog of tables within a specific database schema namespace."""
    model_config = ConfigDict(extra="forbid")

    schema_name: str = Field(..., description="Schema namespace name (e.g. 'public')")
    tables: Dict[str, TableSchema] = Field(default_factory=dict, description="Dictionary of tables keyed by table name")

    def get_table(self, table_name: str) -> Optional[TableSchema]:
        return self.tables.get(table_name)


class DatabaseSchema(BaseModel):
    """
    Root canonical representation of an entire database catalog.
    
    CRITICAL PROPERTIES:
    - Independent of specific DB driver/engine.
    - Serializes deterministically for SHA-256 fingerprinting.
    - Provides convenient lookups across schemas and tables.
    """
    model_config = ConfigDict(extra="forbid")

    database_name: str = Field(..., description="Name of the introspected database")
    database_type: str = Field(default="postgresql", description="Database engine type (e.g. postgresql)")
    schemas: Dict[str, SchemaInfo] = Field(default_factory=dict, description="Dictionary of schemas keyed by schema name")
    fingerprint: str = Field(default="", description="Deterministic SHA-256 hash of schema structure")
    introspected_at: datetime = Field(default_factory=datetime.utcnow, description="UTC timestamp of introspection")
    summary: Dict[str, int] = Field(default_factory=dict, description="Summary counts: tables, columns, relations")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional environment / introspector metadata")

    def get_schema(self, schema_name: str = "public") -> Optional[SchemaInfo]:
        return self.schemas.get(schema_name)

    def get_table(self, table_name: str, schema_name: str = "public") -> Optional[TableSchema]:
        sch = self.get_schema(schema_name)
        if sch:
            return sch.get_table(table_name)
        return None

    @property
    def all_tables(self) -> List[TableSchema]:
        """Convenience list of all tables across all schemas."""
        result = []
        for s in self.schemas.values():
            result.extend(s.tables.values())
        return result

    def compute_summary(self) -> Dict[str, int]:
        total_tables = len(self.all_tables)
        total_columns = sum(len(t.columns) for t in self.all_tables)
        total_fks = sum(len(t.foreign_keys) for t in self.all_tables)
        total_relations = sum(len(t.relationships) for t in self.all_tables)
        self.summary = {
            "schema_count": len(self.schemas),
            "table_count": total_tables,
            "column_count": total_columns,
            "foreign_key_count": total_fks,
            "relationship_count": total_relations,
        }
        return self.summary
