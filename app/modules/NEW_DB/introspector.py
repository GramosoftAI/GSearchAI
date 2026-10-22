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

            # 3. Fetch primary keys from pg_catalog (avoids information_schema permission filters)
            pk_query = """
                SELECT 
                    n.nspname AS table_schema, 
                    c.relname AS table_name, 
                    a.attname AS column_name
                FROM pg_catalog.pg_constraint con
                JOIN pg_catalog.pg_class c ON c.oid = con.conrelid
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(con.conkey)
                WHERE con.contype = 'p'
                  AND n.nspname = ANY($1::text[])
                ORDER BY n.nspname, c.relname;
            """
            try:
                pk_rows = await conn.fetch(pk_query, schemas_filter)
            except Exception as e:
                logger.warning(f"pg_catalog PK query failed ({e}), falling back to information_schema")
                fallback_pk = """
                    SELECT tc.table_schema, tc.table_name, kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.table_schema = kcu.table_schema
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                      AND tc.table_schema = ANY($1::text[]);
                """
                pk_rows = await conn.fetch(fallback_pk, schemas_filter)

            # 4. Fetch declared foreign keys from pg_catalog
            fk_query = """
                SELECT 
                    src_ns.nspname AS source_schema,
                    src_cl.relname AS source_table,
                    src_att.attname AS source_column,
                    tgt_ns.nspname AS target_schema,
                    tgt_cl.relname AS target_table,
                    tgt_att.attname AS target_column
                FROM pg_catalog.pg_constraint con
                JOIN pg_catalog.pg_class src_cl ON src_cl.oid = con.conrelid
                JOIN pg_catalog.pg_namespace src_ns ON src_ns.oid = src_cl.relnamespace
                JOIN pg_catalog.pg_class tgt_cl ON tgt_cl.oid = con.confrelid
                JOIN pg_catalog.pg_namespace tgt_ns ON tgt_ns.oid = tgt_cl.relnamespace
                CROSS JOIN LATERAL unnest(con.conkey, con.confkey) WITH ORDINALITY AS pos(src_attnum, tgt_attnum, ord)
                JOIN pg_catalog.pg_attribute src_att ON src_att.attrelid = src_cl.oid AND src_att.attnum = pos.src_attnum
                JOIN pg_catalog.pg_attribute tgt_att ON tgt_att.attrelid = tgt_cl.oid AND tgt_att.attnum = pos.tgt_attnum
                WHERE con.contype = 'f'
                  AND src_ns.nspname = ANY($1::text[])
                ORDER BY src_ns.nspname, src_cl.relname, pos.ord;
            """
            try:
                fk_rows = await conn.fetch(fk_query, schemas_filter)
            except Exception as e:
                logger.warning(f"pg_catalog FK query failed ({e}), falling back to information_schema")
                fallback_fk = """
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
                     AND tc.constraint_schema = kcu.constraint_schema
                    JOIN information_schema.constraint_column_usage AS ccu
                      ON ccu.constraint_name = tc.constraint_name
                     AND ccu.constraint_schema = tc.constraint_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                      AND tc.table_schema = ANY($1::text[]);
                """
                fk_rows = await conn.fetch(fallback_fk, schemas_filter)

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

                # If table has no formal PK from constraints, deduce PK from standard columns (id, uuid, etc.)
                if not tbl_pks:
                    for col in tbl_cols:
                        if col.name.lower() in ("id", "uuid", f"{t_name.lower()}_id", f"{t_name.lower()}id"):
                            tbl_pks.append(col.name)
                            col.is_primary_key = True
                            break

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

            # 5. Fast Automatic Heuristic Relationship Inference
            # Automatically discovers connections for databases lacking formal DB constraints (e.g. ORM schemas)
            table_map: Dict[str, TableInfo] = {t.table_name.lower(): t for t in tables_list}

            def resolve_target_table(col_name: str, src_table_name: str) -> Optional[TableInfo]:
                col_lower = col_name.lower()
                if not col_lower.endswith("_id") or col_lower in ("id", "pk"):
                    return None
                
                target_stem = col_lower[:-3]  # e.g. 'issue' from 'issue_id', 'user' from 'user_id'
                if not target_stem:
                    return None

                # Exact matches: stem, plural 's', plural 'es'
                direct_candidates = [
                    target_stem,
                    f"{target_stem}s",
                    f"{target_stem}es",
                ]
                for cand in direct_candidates:
                    if cand in table_map and table_map[cand].table_name.lower() != src_table_name.lower():
                        return table_map[cand]

                # Suffix or prefix matches:
                # e.g. 'issue' matches 'bcf_issues', 'journal' matches 'budget_journals', 'crawl' matches 'crawl_jobs'
                for t_name_lower, t_info in table_map.items():
                    if t_name_lower == src_table_name.lower():
                        continue
                    if (
                        t_name_lower.endswith(f"_{target_stem}s")
                        or t_name_lower.endswith(f"_{target_stem}es")
                        or t_name_lower.endswith(f"_{target_stem}")
                        or t_name_lower.startswith(f"{target_stem}_")
                    ):
                        return t_info

                return None

            for tbl in tables_list:
                existing_fk_cols = {fk.column_name.lower() for fk in tbl.foreign_keys}
                for c in tbl.columns:
                    if c.name.lower() in existing_fk_cols or c.is_primary_key:
                        continue
                    
                    target = resolve_target_table(c.name, tbl.table_name)
                    if target:
                        tgt_col = target.primary_keys[0] if target.primary_keys else "id"
                        target_col_names = [tc.name.lower() for tc in target.columns]
                        if tgt_col.lower() not in target_col_names:
                            if "id" in target_col_names:
                                tgt_col = "id"
                            else:
                                continue

                        tbl.foreign_keys.append(
                            ForeignKeyInfo(
                                column_name=c.name,
                                target_schema=target.schema_name or "public",
                                target_table=target.table_name,
                                target_column=tgt_col,
                            )
                        )
                        c.is_foreign_key = True
                        existing_fk_cols.add(c.name.lower())

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
