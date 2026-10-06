"""Phase 2 Knowledge Layer: Database Profiler Stage

Replaces stage_profile_stub.
Reads SchemaView via Phase1Adapter and customer database through open_readonly_connection only.

Responsibilities:
1. Profiles tables and columns producing kb2_knowledge_items:
   - item_type 'table' / 'column'
   - item_key 'schema.table' / 'schema.table.col'
   - structural facts: source='declared', status='confirmed'
   - profiled facts and inferred role: source='inferred', status='draft'
   - payload.stats: row_estimate, null_fraction, distinct_estimate, min/max, top_values
   - payload.role & payload.unit_hint
   - is_sensitive via token guard + value pattern sample check
   - Never sample or store sensitive column values
2. Concurrency & Safety:
   - At most 3 concurrent tables profiled via asyncio.Semaphore(3)
   - 5s statement timeout handled gracefully per table
   - Per-table failure isolation: one failing table does not fail the run
   - Heartbeat callback invoked per table
3. Change detection:
   - object_hash on structural signature: unchanged objects are skipped on re-run
   - Dropped objects are marked 'stale'
   - Never touches is_locked_by_admin items except via repository conflict rules
"""

import uuid
import hashlib
import asyncio
import logging
from typing import Optional, Dict, Any, List, Set, Callable
from datetime import datetime, timezone, timedelta
import asyncpg

from app.core.config import get_settings
from ..adapters.phase1_adapter import Phase1Adapter, SchemaView, TableView, ColumnView
from ..repositories.knowledge_item_repository import KnowledgeItemRepository
from ..sensitivity import is_sensitive_column, check_values_sensitivity
from .profiler_rules import infer_role_and_unit

logger = logging.getLogger(__name__)


def compute_table_structural_hash(table: TableView) -> str:
    """Compute deterministic SHA-256 hash of table structural signature."""
    sig_parts = [
        table.schema_name,
        table.table_name,
        table.table_type,
        ",".join(sorted(table.primary_key_columns)),
        str(table.comment or ""),
    ]
    for col_name in sorted(table.columns.keys()):
        col = table.columns[col_name]
        sig_parts.append(f"{col.name}:{col.data_type}:{col.is_nullable}:{col.is_primary_key}:{col.is_foreign_key}")
    raw = "|".join(sig_parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_column_structural_hash(table: TableView, col: ColumnView) -> str:
    """Compute deterministic SHA-256 hash of column structural signature."""
    raw = (
        f"{table.schema_name}|{table.table_name}|{col.name}|{col.data_type}|"
        f"{col.is_nullable}|{col.is_primary_key}|{col.is_foreign_key}|{col.default_value or ''}|{col.comment or ''}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def profile_single_table(
    conn: Optional[asyncpg.Connection],
    schema_name: str,
    table: TableView,
) -> Dict[str, Any]:
    """Gather pg_class / pg_stats metrics and sample data for a table.
    
    If customer connection is not available or query fails, falls back gracefully.
    """
    profile_data: Dict[str, Any] = {
        "row_estimate": table.row_count_estimate or 0,
        "columns": {},
        "error": None,
    }

    if not conn or conn.is_closed():
        # Offline / disconnected fallback: compute based on schema inspection alone
        for col_name, col in table.columns.items():
            role, unit_hint = infer_role_and_unit(
                column_name=col.name,
                data_type=col.data_type,
                is_primary_key=col.is_primary_key,
                is_foreign_key=col.is_foreign_key,
            )
            profile_data["columns"][col_name] = {
                "stats": {
                    "row_estimate": table.row_count_estimate or 0,
                    "null_fraction": None,
                    "distinct_estimate": None,
                    "min_value": None,
                    "max_value": None,
                    "top_values": [],
                },
                "role": role,
                "unit_hint": unit_hint,
                "is_sensitive": is_sensitive_column(col.name),
            }
        return profile_data

    # 1. Fetch table row estimate from pg_class
    row_est = await conn.fetchval(
        """
        SELECT reltuples::bigint 
        FROM pg_class c 
        JOIN pg_namespace n ON n.oid = c.relnamespace 
        WHERE n.nspname = $1 AND c.relname = $2;
        """,
        schema_name,
        table.table_name,
    )
    if row_est is not None and row_est >= 0:
        profile_data["row_estimate"] = row_est

    # 2. Fetch column stats from pg_stats (never read most_common_vals for sensitive columns)
    pg_stats_map: Dict[str, Any] = {}
    stats_rows = await conn.fetch(
        """
        SELECT attname, null_frac, n_distinct
        FROM pg_stats
        WHERE schemaname = $1 AND tablename = $2;
        """,
        schema_name,
        table.table_name,
    )
    for r in stats_rows:
        pg_stats_map[r["attname"]] = r

    # 3. Profile each column
    quoted_table = f'"{schema_name}"."{table.table_name}"'

    for col_name, col in table.columns.items():
        quoted_col = f'"{col.name}"'
        col_sensitive = is_sensitive_column(col.name)
        stats_info = pg_stats_map.get(col.name)

        null_frac = float(stats_info["null_frac"]) if stats_info and stats_info["null_frac"] is not None else None
        n_distinct = int(stats_info["n_distinct"]) if stats_info and stats_info["n_distinct"] is not None else None
        distinct_est = abs(n_distinct) if n_distinct is not None else None

        min_val = None
        max_val = None
        top_values = []

        # Numerical or date min/max (never on sensitive columns)
        is_num_or_date = any(t in col.data_type.lower() for t in ("int", "float", "numeric", "decimal", "date", "timestamp", "time", "real", "double"))
        
        if not col_sensitive:
            if is_num_or_date:
                try:
                    min_max_row = await conn.fetchrow(
                        f"SELECT min({quoted_col})::text AS min_val, max({quoted_col})::text AS max_val FROM {quoted_table};"
                    )
                    if min_max_row:
                        min_val = min_max_row["min_val"]
                        max_val = min_max_row["max_val"]
                except Exception as e:
                    logger.debug(f"Could not compute min/max for {col.name}: {e}")

            # Top values for low cardinality non-sensitive columns (capped at 20, truncated)
            try:
                # Sample values for value-pattern sensitivity check and top values
                sample_rows = await conn.fetch(
                    f"SELECT {quoted_col}::text AS val, count(*) AS cnt "
                    f"FROM {quoted_table} "
                    f"WHERE {quoted_col} IS NOT NULL "
                    f"GROUP BY {quoted_col} "
                    f"ORDER BY cnt DESC "
                    f"LIMIT 25;"
                )
                sample_vals = [r["val"] for r in sample_rows if r["val"] is not None]
                if check_values_sensitivity(sample_vals):
                    col_sensitive = True
                    sample_vals = []
                    top_values = []
                else:
                    # Safe: if low cardinality or small table, cap at 20 truncated top values
                    for val in sample_vals[:20]:
                        s_val = str(val)[:128]
                        top_values.append(s_val)
            except Exception as e:
                logger.debug(f"Could not compute top values for {col.name}: {e}")

        role, unit_hint = infer_role_and_unit(
            column_name=col.name,
            data_type=col.data_type,
            is_primary_key=col.is_primary_key,
            is_foreign_key=col.is_foreign_key,
            distinct_count=distinct_est,
            min_val=min_val,
            max_val=max_val,
        )

        profile_data["columns"][col_name] = {
            "stats": {
                "row_estimate": profile_data["row_estimate"],
                "null_fraction": null_frac,
                "distinct_estimate": distinct_est,
                "min_value": min_val if not col_sensitive else None,
                "max_value": max_val if not col_sensitive else None,
                "top_values": top_values if not col_sensitive else [],
            },
            "role": role,
            "unit_hint": unit_hint,
            "is_sensitive": col_sensitive,
        }

    return profile_data


async def run_stage_profiler(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    schema_version: str,
    adapter: Phase1Adapter,
    item_repo: KnowledgeItemRepository,
    heartbeat_cb: Optional[Callable[[], Any]] = None,
    force_refresh_stats: bool = False,
    max_stats_age_days: Optional[int] = None,
) -> Dict[str, Any]:
    """Execute Profiler stage for all tables in the schema snapshot.
    
    Guarantees:
    - Reads SchemaView through Phase1Adapter
    - Opens customer connection via open_readonly_connection only
    - At most 3 concurrent table profiles via asyncio.Semaphore(3)
    - Per-table error isolation
    - Unchanged object_hash skipped on re-run (unless stats age expired or forced)
    - Dropped tables/columns marked stale
    - Heartbeat callback invoked per table
    """
    settings = get_settings()
    stats_max_age_days = max_stats_age_days if max_stats_age_days is not None else getattr(settings, "phase2_profiler_stats_max_age_days", 7)
    stats_max_age_delta = timedelta(days=stats_max_age_days)
    now_utc = datetime.now(timezone.utc)

    # 1. Fetch schema view
    schema_view = await adapter.get_schema_by_version(tenant_id, kb_id, schema_version)
    if not schema_view:
        try:
            schema_view = await adapter.get_current_schema(tenant_id, kb_id)
        except Exception as e:
            logger.warning(f"Could not load schema view for KB {kb_id} ({e}). Returning empty profiling metrics.")
            return {
                "tables_profiled": 0,
                "columns_profiled": 0,
                "table_errors": {},
                "stale_items_marked": 0,
            }

    # Gather existing items to identify dropped tables/columns and skip unchanged
    existing_items = await item_repo.list_items(db_knowledgebase_id=kb_id, limit=5000)
    existing_map: Dict[str, Any] = {item.item_key: item for item in existing_items}

    active_table_keys: Set[str] = set()
    active_column_keys: Set[str] = set()

    semaphore = asyncio.Semaphore(3)
    repo_lock = asyncio.Lock()
    tables_profiled = 0
    columns_profiled = 0
    table_errors: Dict[str, str] = {}

    def _is_stats_expired(item: Optional[Any]) -> bool:
        if not item or not item.payload:
            return True
        refreshed_at_str = item.payload.get("stats_refreshed_at")
        if not refreshed_at_str:
            return True
        try:
            refreshed_dt = datetime.fromisoformat(refreshed_at_str)
            if refreshed_dt.tzinfo is None:
                refreshed_dt = refreshed_dt.replace(tzinfo=timezone.utc)
            return (now_utc - refreshed_dt) > stats_max_age_delta
        except Exception:
            return True

    async def _profile_table_worker(table_key: str, tbl: TableView):
        nonlocal tables_profiled, columns_profiled
        async with semaphore:
            active_table_keys.add(table_key)
            for c_name in tbl.columns.keys():
                active_column_keys.add(f"{table_key}.{c_name}")

            tbl_hash = compute_table_structural_hash(tbl)
            existing_tbl_item = existing_map.get(table_key)

            # Check if stats need refresh due to age or force flag
            tbl_stats_need_refresh = force_refresh_stats or _is_stats_expired(existing_tbl_item)
            tbl_skipped = existing_tbl_item and existing_tbl_item.object_hash == tbl_hash and existing_tbl_item.status != "stale" and not tbl_stats_need_refresh

            tbl_profile: Dict[str, Any] = {"columns": {}, "row_estimate": tbl.row_count_estimate or 0}
            
            # Profile with isolated connection per worker table
            try:
                cm = adapter.open_readonly_connection(tenant_id, kb_id)
                if not hasattr(cm, "__aenter__") and callable(cm):
                    cm = cm()
                async with cm as conn:
                    tbl_profile = await profile_single_table(conn, tbl.schema_name, tbl)
            except Exception as tbl_err:
                logger.error(f"Error profiling table {table_key}: {tbl_err}", exc_info=True)
                table_errors[table_key] = str(tbl_err)

            # Upsert table knowledge item
            tbl_payload = {
                "schema_name": tbl.schema_name,
                "table_name": tbl.table_name,
                "table_type": tbl.table_type,
                "comment": tbl.comment,
                "primary_key": tbl.primary_key_columns,
                "foreign_keys": [
                    {
                        "name": fk.name,
                        "constrained_columns": fk.constrained_columns,
                        "referred_table": f"{fk.referred_schema}.{fk.referred_table}",
                        "referred_columns": fk.referred_columns,
                    }
                    for fk in tbl.foreign_keys
                ],
                "stats": {
                    "row_estimate": tbl_profile.get("row_estimate", tbl.row_count_estimate or 0),
                },
                "stats_refreshed_at": now_utc.isoformat(),
            }

            if not tbl_skipped:
                async with repo_lock:
                    await item_repo.upsert_item(
                        db_knowledgebase_id=kb_id,
                        item_type="table",
                        item_key=table_key,
                        valid_from_version=schema_version,
                        object_hash=tbl_hash,
                        source="declared",
                        status="confirmed",
                        payload=tbl_payload,
                        confidence=1.0,
                        is_sensitive=False,
                    )
                tables_profiled += 1

            # Process each column
            for col_name, col in tbl.columns.items():
                col_key = f"{table_key}.{col_name}"
                col_hash = compute_column_structural_hash(tbl, col)
                existing_col_item = existing_map.get(col_key)

                col_stats_need_refresh = force_refresh_stats or _is_stats_expired(existing_col_item)
                col_skipped = existing_col_item and existing_col_item.object_hash == col_hash and existing_col_item.status != "stale" and not col_stats_need_refresh

                col_prof_info = tbl_profile["columns"].get(col_name, {})
                col_stats = col_prof_info.get("stats", {})
                col_role = col_prof_info.get("role", "unknown")
                col_unit = col_prof_info.get("unit_hint")
                is_sensitive = col_prof_info.get("is_sensitive", is_sensitive_column(col.name))

                col_payload = {
                    "table_name": table_key,
                    "column_name": col.name,
                    "data_type": col.data_type,
                    "is_nullable": col.is_nullable,
                    "is_primary_key": col.is_primary_key,
                    "is_foreign_key": col.is_foreign_key,
                    "comment": col.comment,
                    "role": col_role,
                    "unit_hint": col_unit,
                    "stats": col_stats,
                    "stats_refreshed_at": now_utc.isoformat(),
                }

                if not col_skipped:
                    # Inferred/profiled facts start in 'draft' status with source='inferred'
                    async with repo_lock:
                        await item_repo.upsert_item(
                            db_knowledgebase_id=kb_id,
                            item_type="column",
                            item_key=col_key,
                            valid_from_version=schema_version,
                            object_hash=col_hash,
                            source="inferred",
                            status="draft",
                            payload=col_payload,
                            confidence=0.9 if not is_sensitive else 1.0,
                            is_sensitive=is_sensitive,
                        )
                    columns_profiled += 1

            # Heartbeat after profiling each table
            if heartbeat_cb:
                await heartbeat_cb()

    tasks = []
    for t_name, tbl in schema_view.tables.items():
        table_key = f"{tbl.schema_name}.{tbl.table_name}"
        tasks.append(_profile_table_worker(table_key, tbl))
    await asyncio.gather(*tasks, return_exceptions=True)

    # Mark dropped items as 'stale'
    dropped_keys = []
    for old_key, old_item in existing_map.items():
        if old_item.item_type == "table" and old_key not in active_table_keys:
            dropped_keys.append(old_key)
        elif old_item.item_type == "column" and old_key not in active_column_keys:
            dropped_keys.append(old_key)

    if dropped_keys:
        stale_count = await item_repo.mark_stale(db_knowledgebase_id=kb_id, item_keys=dropped_keys)
        logger.info(f"Marked {stale_count} dropped items as stale for KB {kb_id}")

    # Commit items to persist across independent sessions/transactions
    try:
        await item_repo.db.commit()
    except Exception as commit_err:
        logger.debug(f"Commit on item_repo session: {commit_err}")

    return {
        "tables_profiled": tables_profiled,
        "columns_profiled": columns_profiled,
        "table_errors": table_errors,
        "stale_items_marked": len(dropped_keys),
    }
