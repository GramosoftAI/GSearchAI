"""Deterministic Schema Introspection Engine for NEW_DB

Queries PostgreSQL system catalogs (information_schema and pg_catalog) directly,
extracting structural tables, views, columns, primary keys, and foreign keys.
Fast, deterministic, and free of heavyweight background jobs.
"""

import hashlib
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from .schemas import DBConnectionConfig, CanonicalSchema, TableInfo, ColumnInfo, ForeignKeyInfo
from .connection import DatabaseConnector

logger = logging.getLogger(__name__)

SENSITIVE_KEYWORDS = {
    "password", "passwd", "secret", "token", "hash", "salt", "api_key",
    "private_key", "credit_card", "ssn", "cvv", "auth_token"
}


class SchemaIntrospector:
    """Extracts clean canonical schema metadata from target databases."""

    @classmethod
    async def introspect(cls, config: DBConnectionConfig) -> CanonicalSchema:
        """Introspect tables, columns, PKs, and FKs from target PostgreSQL database."""
        conn = await DatabaseConnector.get_asyncpg_connection(config)
        try:
            schemas_filter = config.schemas or ["public"]

            # 1. Fetch tables and views
            tables_query = """
                SELECT 
                    table_schema, 
                    table_name, 
                    table_type
                FROM information_schema.tables
                WHERE table_schema = ANY($1::text[])
                  AND table_type IN ('BASE TABLE', 'VIEW')
                ORDER BY table_schema, table_name;
            """
            table_rows = await conn.fetch(tables_query, schemas_filter)

            # 2. Fetch all columns
            cols_query = """
                SELECT 
                    table_schema, 
                    table_name, 
                    column_name, 
                    data_type, 
                    is_nullable, 
                    column_default,
                    ordinal_position
                FROM information_schema.columns
                WHERE table_schema = ANY($1::text[])
                ORDER BY table_schema, table_name, ordinal_position;
            """
            col_rows = await conn.fetch(cols_query, schemas_filter)

            # 3. Fetch primary keys
            pk_query = """
                SELECT 
                    tc.table_schema, 
                    tc.table_name, 
                    kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                  AND tc.table_schema = ANY($1::text[]);
            """
            pk_rows = await conn.fetch(pk_query, schemas_filter)

            # 4. Fetch foreign keys
            fk_query = """
                SELECT
                    tc.table_schema AS source_schema,
                    tc.table_name AS source_table,
                    kcu.column_name AS source_column,
                    ccu.table_schema AS target_schema,
                    ccu.table_name AS target_table,
                    ccu.column_name AS target_column
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = ANY($1::text[]);
            """
            fk_rows = await conn.fetch(fk_query, schemas_filter)

            # Group PKs by (schema, table)
            pks_by_table: Dict[str, List[str]] = {}
            for r in pk_rows:
                key = f"{r['table_schema']}.{r['table_name']}"
                pks_by_table.setdefault(key, []).append(r['column_name'])

            # Group FKs by (schema, table)
            fks_by_table: Dict[str, List[ForeignKeyInfo]] = {}
            for r in fk_rows:
                key = f"{r['source_schema']}.{r['source_table']}"
                fks_by_table.setdefault(key, []).append(
                    ForeignKeyInfo(
                        column_name=r['source_column'],
                        target_schema=r['target_schema'],
                        target_table=r['target_table'],
                        target_column=r['target_column'],
                    )
                )

            # Group columns by (schema, table)
            cols_by_table: Dict[str, List[ColumnInfo]] = {}
            for r in col_rows:
                key = f"{r['table_schema']}.{r['table_name']}"
                is_pk = r['column_name'] in pks_by_table.get(key, [])
                is_fk = any(fk.column_name == r['column_name'] for fk in fks_by_table.get(key, []))

                cols_by_table.setdefault(key, []).append(
                    ColumnInfo(
                        name=r['column_name'],
                        data_type=r['data_type'],
                        is_nullable=(r['is_nullable'] == "YES"),
                        is_primary_key=is_pk,
                        is_foreign_key=is_fk,
                        default_value=str(r['column_default']) if r['column_default'] else None,
                    )
                )

            # Assemble tables
            tables_list: List[TableInfo] = []
            fingerprint_builder = []

            for tr in table_rows:
                t_schema = tr['table_schema']
                t_name = tr['table_name']
                key = f"{t_schema}.{t_name}"

                tbl_cols = cols_by_table.get(key, [])
                tbl_pks = pks_by_table.get(key, [])
                tbl_fks = fks_by_table.get(key, [])

                # Fast sample query for non-sensitive enum/status columns
                for c in tbl_cols:
                    if c.name.lower() in ("status", "type", "state", "category", "role", "priority", "kind"):
                        if not any(k in c.name.lower() for k in SENSITIVE_KEYWORDS):
                            try:
                                sample_recs = await conn.fetch(
                                    f'SELECT DISTINCT "{c.name}" FROM "{t_schema}"."{t_name}" WHERE "{c.name}" IS NOT NULL LIMIT 8;'
                                )
                                c.sample_values = [str(sr[0]) for sr in sample_recs if sr[0] is not None]
                            except Exception:
                                pass

                table_info = TableInfo(
                    schema_name=t_schema,
                    table_name=t_name,
                    is_view=(tr['table_type'] == "VIEW"),
                    columns=tbl_cols,
                    primary_keys=tbl_pks,
                    foreign_keys=tbl_fks,
                )
                tables_list.append(table_info)

                # Signature for fingerprint
                col_sig = ",".join(f"{c.name}:{c.data_type}" for c in tbl_cols)
                fingerprint_builder.append(f"{t_schema}.{t_name}|{col_sig}")

            raw_fp = ";".join(fingerprint_builder)
            fingerprint = hashlib.sha256(raw_fp.encode("utf-8")).hexdigest()

            return CanonicalSchema(
                database_name=config.database_name,
                database_type=config.db_type.value,
                fingerprint=fingerprint,
                introspected_at=datetime.utcnow(),
                tables=tables_list,
            )

        finally:
            await conn.close()
