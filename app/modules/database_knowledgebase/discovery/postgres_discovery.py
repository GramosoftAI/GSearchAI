"""PostgreSQL Structural Database Discovery Implementation

Performs comprehensive metadata extraction from PostgreSQL system catalogs
(information_schema, pg_catalog, pg_constraint, pg_class, pg_indexes).
Guarantees zero full-table scans, read-only transaction isolation, and timeout controls.
"""

import logging
from typing import Dict, List, Optional, Any
import asyncpg

from .database_discovery import (
    DatabaseDiscoveryService,
    DiscoveredCatalog,
    DiscoveredColumn,
    DiscoveredForeignKey,
    DiscoveredIndex,
    DiscoveredTable,
    DiscoveredTableType,
)
from ..schemas.connection import DatabaseConnectionConfig
from ..schemas.canonical import DatabaseSchema, ColumnDataType
from ..schema.normalizer import SchemaNormalizer
from ..connectors.factory import ConnectorFactory
from ..connectors.postgresql import PostgreSQLConnector

logger = logging.getLogger(__name__)


class PostgresDiscoveryService(DatabaseDiscoveryService):
    """
    Engine-specific discovery service for PostgreSQL.
    Extracts structural definitions directly from PostgreSQL system catalogs.
    """

    async def discover_catalog(
        self,
        config: DatabaseConnectionConfig,
        schemas: Optional[List[str]] = None,
    ) -> DiscoveredCatalog:
        """
        Inspect PostgreSQL system catalogs and return DiscoveredCatalog.
        """
        connector = ConnectorFactory.create_connector(config)
        if not isinstance(connector, PostgreSQLConnector):
            raise TypeError(f"Expected PostgreSQLConnector, got {type(connector)}")

        try:
            raw_meta = await connector.introspect_raw_metadata(schemas=schemas)
            return self.normalize_raw_to_discovered_catalog(
                raw_meta=raw_meta,
                database_name=config.database_name,
            )
        finally:
            await connector.close()

    @classmethod
    def from_canonical_schema(cls, schema: DatabaseSchema) -> DiscoveredCatalog:
        """
        Convert an existing canonical DatabaseSchema snapshot into DiscoveredCatalog.
        Allows zero-DB-overhead adaptation when schema snapshot is already loaded.
        """
        discovered_tables: Dict[str, DiscoveredTable] = {}
        active_schemas: List[str] = list(schema.schemas.keys())

        for s_name, s_info in schema.schemas.items():
            for t_name, tbl in s_info.tables.items():
                table_key = f"{s_name}.{t_name}"

                cols: Dict[str, DiscoveredColumn] = {}
                for c_name, c in tbl.columns.items():
                    cols[c_name] = DiscoveredColumn(
                        name=c.name,
                        data_type=c.data_type,
                        raw_data_type=c.raw_data_type,
                        is_nullable=c.is_nullable,
                        default_value=c.default_value,
                        ordinal_position=c.ordinal_position,
                        is_primary_key=c.is_primary_key,
                        is_foreign_key=c.is_foreign_key,
                        is_unique=False,
                        comment=c.comment,
                        extra_metadata=c.extra_metadata or {},
                    )

                pks = tbl.primary_key_columns
                fks = [
                    DiscoveredForeignKey(
                        constraint_name=fk.name,
                        source_schema=s_name,
                        source_table=t_name,
                        source_columns=fk.constrained_columns,
                        target_schema=fk.referred_schema,
                        target_table=fk.referred_table,
                        target_columns=fk.referred_columns,
                    )
                    for fk in tbl.foreign_keys
                ]

                idxs = [
                    DiscoveredIndex(
                        index_name=idx.name,
                        table_schema=s_name,
                        table_name=t_name,
                        columns=idx.columns,
                        is_unique=idx.is_unique,
                        index_type=idx.index_type or "btree",
                    )
                    for idx in tbl.indexes
                ]

                # Populate is_primary_key and is_foreign_key flags on columns
                for pk_col in pks:
                    if pk_col in cols:
                        cols[pk_col].is_primary_key = True

                for fk in fks:
                    for fk_col in fk.source_columns:
                        if fk_col in cols:
                            cols[fk_col].is_foreign_key = True

                discovered_tables[table_key] = DiscoveredTable(
                    schema_name=s_name,
                    table_name=t_name,
                    table_type=DiscoveredTableType.TABLE,
                    comment=tbl.comment,
                    row_count_estimate=tbl.row_count_estimate,
                    columns=cols,
                    primary_key_columns=pks,
                    foreign_keys=fks,
                    indexes=idxs,
                )

        return DiscoveredCatalog(
            database_name=schema.database_name,
            database_type="postgresql",
            schemas=active_schemas,
            tables=discovered_tables,
            raw_catalog_counts={
                "tables": len(discovered_tables),
                "columns": sum(len(t.columns) for t in discovered_tables.values()),
                "foreign_keys": sum(len(t.foreign_keys) for t in discovered_tables.values()),
            },
        )

    @classmethod
    def normalize_raw_to_discovered_catalog(
        cls,
        raw_meta: Dict[str, Any],
        database_name: str,
    ) -> DiscoveredCatalog:
        """
        Normalize raw catalog dictionary from PostgreSQLConnector into DiscoveredCatalog.
        """
        schemas = raw_meta.get("schemas", ["public"])
        raw_tables = raw_meta.get("tables", [])
        raw_columns = raw_meta.get("columns", [])
        raw_pks = raw_meta.get("primary_keys", [])
        raw_fks = raw_meta.get("foreign_keys", [])
        raw_uniques = raw_meta.get("unique_constraints", [])
        raw_indexes = raw_meta.get("indexes", [])

        discovered_tables: Dict[str, DiscoveredTable] = {}

        # 1. Initialize Tables
        for r_tbl in raw_tables:
            s_name = r_tbl["table_schema"]
            t_name = r_tbl["table_name"]
            t_type_raw = (r_tbl.get("table_type") or "").upper()
            t_type = (
                DiscoveredTableType.VIEW
                if "VIEW" in t_type_raw
                else DiscoveredTableType.TABLE
            )

            key = f"{s_name}.{t_name}"
            discovered_tables[key] = DiscoveredTable(
                schema_name=s_name,
                table_name=t_name,
                table_type=t_type,
                comment=r_tbl.get("table_comment"),
                columns={},
                primary_key_columns=[],
                foreign_keys=[],
                unique_constraints={},
                indexes=[],
            )

        # 2. Add Columns
        for r_col in raw_columns:
            s_name = r_col["table_schema"]
            t_name = r_col["table_name"]
            c_name = r_col["column_name"]
            key = f"{s_name}.{t_name}"
            if key not in discovered_tables:
                continue

            c_type = SchemaNormalizer.map_data_type(
                r_col.get("data_type", ""),
                r_col.get("udt_name", ""),
            )
            col = DiscoveredColumn(
                name=c_name,
                data_type=c_type,
                raw_data_type=r_col.get("data_type", ""),
                is_nullable=r_col.get("is_nullable", "YES").upper() == "YES",
                default_value=r_col.get("column_default"),
                ordinal_position=int(r_col.get("ordinal_position", 0)),
                comment=r_col.get("column_comment"),
            )
            discovered_tables[key].columns[c_name] = col

        # 3. Add Primary Keys
        for r_pk in raw_pks:
            key = f"{r_pk['table_schema']}.{r_pk['table_name']}"
            c_name = r_pk["column_name"]
            if key in discovered_tables:
                discovered_tables[key].primary_key_columns.append(c_name)
                if c_name in discovered_tables[key].columns:
                    discovered_tables[key].columns[c_name].is_primary_key = True

        # 4. Add Unique Constraints
        for r_u in raw_uniques:
            key = f"{r_u['table_schema']}.{r_u['table_name']}"
            c_name = r_u["column_name"]
            con_name = r_u.get("constraint_name", "unique")
            if key in discovered_tables:
                discovered_tables[key].unique_constraints.setdefault(con_name, []).append(c_name)
                if c_name in discovered_tables[key].columns:
                    discovered_tables[key].columns[c_name].is_unique = True

        # 5. Add Foreign Keys
        for r_fk in raw_fks:
            key = f"{r_fk['source_schema']}.{r_fk['source_table']}"
            if key in discovered_tables:
                fk = DiscoveredForeignKey(
                    constraint_name=r_fk["constraint_name"],
                    source_schema=r_fk["source_schema"],
                    source_table=r_fk["source_table"],
                    source_columns=r_fk["source_columns"],
                    target_schema=r_fk["target_schema"],
                    target_table=r_fk["target_table"],
                    target_columns=r_fk["target_columns"],
                    on_delete=r_fk.get("on_delete"),
                    on_update=r_fk.get("on_update"),
                )
                discovered_tables[key].foreign_keys.append(fk)
                for sc in fk.source_columns:
                    if sc in discovered_tables[key].columns:
                        discovered_tables[key].columns[sc].is_foreign_key = True

        # 6. Add Indexes
        for r_idx in raw_indexes:
            key = f"{r_idx['table_schema']}.{r_idx['table_name']}"
            if key in discovered_tables:
                idx = DiscoveredIndex(
                    index_name=r_idx["index_name"],
                    table_schema=r_idx["table_schema"],
                    table_name=r_idx["table_name"],
                    columns=r_idx.get("columns", []),
                    is_unique=r_idx.get("is_unique", False),
                    index_type=r_idx.get("index_type", "btree"),
                )
                discovered_tables[key].indexes.append(idx)

        return DiscoveredCatalog(
            database_name=database_name,
            database_type="postgresql",
            schemas=schemas,
            tables=discovered_tables,
            raw_catalog_counts={
                "tables": len(discovered_tables),
                "columns": sum(len(t.columns) for t in discovered_tables.values()),
                "foreign_keys": sum(len(t.foreign_keys) for t in discovered_tables.values()),
            },
        )
