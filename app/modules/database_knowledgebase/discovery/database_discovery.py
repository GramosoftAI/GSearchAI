"""Structural Database Discovery Abstraction

Defines the contract and canonical data models for introspecting any supported
relational database engine directly from authoritative database catalogs.
Strictly read-only; no full table scans permitted.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, ConfigDict, Field

from ..schemas.connection import DatabaseConnectionConfig
from ..schemas.canonical import ColumnDataType


class DiscoveredTableType(str, Enum):
    TABLE = "TABLE"
    VIEW = "VIEW"
    MATERIALIZED_VIEW = "MATERIALIZED_VIEW"
    FOREIGN_TABLE = "FOREIGN_TABLE"
    UNKNOWN = "UNKNOWN"


class DiscoveredColumn(BaseModel):
    """Metadata representing a single discovered database column."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Physical column name")
    data_type: ColumnDataType = Field(..., description="Normalized canonical data type")
    raw_data_type: str = Field(..., description="Engine native data type string")
    is_nullable: bool = Field(default=True, description="Whether column accepts NULL")
    default_value: Optional[str] = Field(default=None, description="Default expression or value")
    ordinal_position: int = Field(default=0, description="1-indexed position in table")
    is_primary_key: bool = Field(default=False, description="Whether column is part of PK")
    is_foreign_key: bool = Field(default=False, description="Whether column references another table")
    is_unique: bool = Field(default=False, description="Whether column has unique constraint")
    comment: Optional[str] = Field(default=None, description="Catalog description / comment")
    extra_metadata: Dict[str, Any] = Field(default_factory=dict, description="Engine specific metadata")


class DiscoveredForeignKey(BaseModel):
    """Discovered declared foreign key constraint."""
    model_config = ConfigDict(extra="forbid")

    constraint_name: str = Field(..., description="Name of foreign key constraint")
    source_schema: str = Field(..., description="Source schema name")
    source_table: str = Field(..., description="Source table name")
    source_columns: List[str] = Field(..., description="Constrained columns in source table")
    target_schema: str = Field(..., description="Target / referenced schema name")
    target_table: str = Field(..., description="Target / referenced table name")
    target_columns: List[str] = Field(..., description="Referenced columns in target table")
    on_delete: Optional[str] = Field(default=None, description="ON DELETE action rule")
    on_update: Optional[str] = Field(default=None, description="ON UPDATE action rule")


class DiscoveredIndex(BaseModel):
    """Discovered table index definition."""
    model_config = ConfigDict(extra="forbid")

    index_name: str = Field(..., description="Name of index")
    table_schema: str = Field(..., description="Table schema name")
    table_name: str = Field(..., description="Table name")
    columns: List[str] = Field(..., description="Indexed column names")
    is_unique: bool = Field(default=False, description="Whether unique index")
    index_type: str = Field(default="btree", description="Index access method (btree, gin, etc.)")


class DiscoveredTable(BaseModel):
    """Discovered database table or view."""
    model_config = ConfigDict(extra="forbid")

    schema_name: str = Field(..., description="Schema namespace")
    table_name: str = Field(..., description="Physical table name")
    table_type: DiscoveredTableType = Field(default=DiscoveredTableType.TABLE, description="Table vs View")
    comment: Optional[str] = Field(default=None, description="Catalog description / comment")
    row_count_estimate: Optional[int] = Field(default=None, description="Catalog statistic estimate (no full scan)")
    columns: Dict[str, DiscoveredColumn] = Field(default_factory=dict, description="Columns keyed by column name")
    primary_key_columns: List[str] = Field(default_factory=list, description="Primary key column names")
    foreign_keys: List[DiscoveredForeignKey] = Field(default_factory=list, description="Outgoing foreign keys")
    unique_constraints: Dict[str, List[str]] = Field(default_factory=dict, description="Unique constraint name -> cols")
    indexes: List[DiscoveredIndex] = Field(default_factory=list, description="Table indexes")

    @property
    def unique_columns(self) -> List[str]:
        """Flattens all columns involved in unique constraints."""
        cols: List[str] = []
        for u_cols in self.unique_constraints.values():
            cols.extend(u_cols)
        return list(dict.fromkeys(cols))


class DiscoveredCatalog(BaseModel):
    """Complete canonical structural discovery output for an entire database."""
    model_config = ConfigDict(extra="forbid")

    database_name: str = Field(..., description="Introspected database name")
    database_type: str = Field(default="postgresql", description="Engine type")
    schemas: List[str] = Field(default_factory=list, description="Active schemas discovered")
    tables: Dict[str, DiscoveredTable] = Field(default_factory=dict, description="Tables keyed by 'schema.table'")
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_catalog_counts: Dict[str, int] = Field(default_factory=dict, description="Summary counts of elements")

    @property
    def foreign_keys(self) -> List[DiscoveredForeignKey]:
        """Collect all foreign keys across all discovered tables."""
        fks: List[DiscoveredForeignKey] = []
        for t in self.tables.values():
            fks.extend(t.foreign_keys)
        return fks

    def get_table(self, table_name: str, schema_name: str = "public") -> Optional[DiscoveredTable]:
        """Lookup table by schema.table or just table name."""
        key = f"{schema_name}.{table_name}"
        if key in self.tables:
            return self.tables[key]
        for t in self.tables.values():
            if t.table_name == table_name:
                return t
        return None


class DatabaseDiscoveryService(ABC):
    """Abstract contract for engine-specific structural metadata discovery."""

    @abstractmethod
    async def discover_catalog(
        self,
        config: DatabaseConnectionConfig,
        schemas: Optional[List[str]] = None,
    ) -> DiscoveredCatalog:
        """
        Inspect the database catalogs and produce a comprehensive DiscoveredCatalog.
        Must strictly avoid full table scans.
        """
        pass
