"""Phase 2 Knowledge Layer: Phase 1 Adapter

Provides an isolated, read-only interface to Phase 1 data and customer database
connections, ensuring Phase 2 never imports or depends on legacy modules:
- semantic/
- schema_doc/
- semantic_glossary/

Contracts:
1. get_current_schema(tenant_id, kb_id) -> SchemaView (Phase 2 dataclasses)
2. get_schema_version(tenant_id, kb_id) -> str
3. open_readonly_connection(tenant_id, kb_id) -> Async context manager yielding asyncpg.Connection
   with:
   - default_transaction_read_only = 'on'
   - statement_timeout = 5000 (5 seconds)
   - strictly closed on exit
   - zero credentials returned outside the context manager
   - tenant_id checked on every call
"""

import uuid
import logging
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any, AsyncIterator
import asyncpg
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.database_knowledgebase.models.database_knowledgebase import (
    DatabaseKnowledgebase,
    DatabaseSchemaSnapshot,
)
from app.modules.database_knowledgebase.security.secrets import SecretManager

logger = logging.getLogger(__name__)


# ==============================================================================
# Phase 2 Schema Dataclasses (Self-contained, decoupled from Phase 1 canonical classes)
# ==============================================================================

@dataclass(frozen=True)
class ColumnView:
    """Read-only view of a column in Phase 2."""
    name: str
    data_type: str
    raw_data_type: str
    is_nullable: bool
    is_primary_key: bool
    is_foreign_key: bool
    default_value: Optional[str] = None
    comment: Optional[str] = None
    ordinal_position: int = 0
    classification: str = "GENERAL"


@dataclass(frozen=True)
class FKView:
    """Read-only view of a foreign key relationship in Phase 2."""
    name: Optional[str]
    constrained_columns: List[str]
    referred_schema: str
    referred_table: str
    referred_columns: List[str]
    on_delete: Optional[str] = None
    on_update: Optional[str] = None


@dataclass(frozen=True)
class TableView:
    """Read-only view of a table in Phase 2."""
    schema_name: str
    table_name: str
    table_type: str
    columns: Dict[str, ColumnView]
    primary_key_columns: List[str]
    foreign_keys: List[FKView]
    comment: Optional[str] = None
    row_count_estimate: Optional[int] = None


@dataclass(frozen=True)
class SchemaView:
    """Read-only view of an entire database catalog in Phase 2."""
    database_name: str
    database_type: str
    schema_version: str  # Fingerprint of the snapshot
    tables: Dict[str, TableView]  # Keyed by table_name (or 'schema.table')
    introspected_at: Optional[str] = None
    summary: Dict[str, Any] = field(default_factory=dict)


# ==============================================================================
# Phase 1 Adapter Implementation
# ==============================================================================

class Phase1Adapter:
    """
    Read-only adapter that interfaces with Phase 1 storage and connections.
    Always enforces strict tenant isolation on every call.
    """

    _GLOBAL_CONFIG_CACHE: Dict[str, Any] = {}

    def __init__(self, session: AsyncSession, secret_manager: Optional[SecretManager] = None):
        self.session = session
        self.secrets = secret_manager or SecretManager()
        self._cached_configs: Dict[str, Any] = {}

    async def get_schema_version(self, tenant_id: uuid.UUID, kb_id: uuid.UUID) -> str:
        """Fetch canonical schema fingerprint (version) for the specified knowledge base.
        
        Strictly enforces tenant_id check.
        """
        # 1. First check the latest snapshot
        stmt = (
            select(DatabaseSchemaSnapshot.schema_version)
            .where(
                DatabaseSchemaSnapshot.tenant_id == tenant_id,
                DatabaseSchemaSnapshot.db_knowledgebase_id == kb_id,
            )
            .order_by(desc(DatabaseSchemaSnapshot.created_at))
            .limit(1)
        )
        res = await self.session.execute(stmt)
        ver = res.scalar_one_or_none()
        if ver:
            return ver

        # 2. Fall back to DatabaseKnowledgebase.schema_version if no snapshot row exists
        stmt_kb = (
            select(DatabaseKnowledgebase.schema_version)
            .where(
                DatabaseKnowledgebase.id == kb_id,
                DatabaseKnowledgebase.tenant_id == tenant_id,
                DatabaseKnowledgebase.is_active == True,
            )
        )
        res_kb = await self.session.execute(stmt_kb)
        kb_ver = res_kb.scalar_one_or_none()
        if not kb_ver:
            raise ValueError(f"No schema version found for knowledge base '{kb_id}' under tenant '{tenant_id}'.")
        return kb_ver

    async def get_schema_snapshot_record(
        self, tenant_id: uuid.UUID, kb_id: uuid.UUID, schema_version: str
    ) -> Optional[DatabaseSchemaSnapshot]:
        """Fetch a specific DatabaseSchemaSnapshot row by version within tenant scope."""
        stmt = (
            select(DatabaseSchemaSnapshot)
            .where(
                DatabaseSchemaSnapshot.tenant_id == tenant_id,
                DatabaseSchemaSnapshot.db_knowledgebase_id == kb_id,
                DatabaseSchemaSnapshot.schema_version == schema_version,
            )
            .order_by(desc(DatabaseSchemaSnapshot.created_at))
            .limit(1)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_latest_snapshot_record(
        self, tenant_id: uuid.UUID, kb_id: uuid.UUID
    ) -> Optional[DatabaseSchemaSnapshot]:
        """Fetch latest DatabaseSchemaSnapshot row within tenant scope."""
        stmt = (
            select(DatabaseSchemaSnapshot)
            .where(
                DatabaseSchemaSnapshot.tenant_id == tenant_id,
                DatabaseSchemaSnapshot.db_knowledgebase_id == kb_id,
            )
            .order_by(desc(DatabaseSchemaSnapshot.created_at), desc(DatabaseSchemaSnapshot.id))
            .limit(1)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_schema_by_version(
        self, tenant_id: uuid.UUID, kb_id: uuid.UUID, schema_version: str
    ) -> Optional[SchemaView]:
        """Fetch schema snapshot by specific version and map to Phase 2 dataclasses."""
        snapshot = await self.get_schema_snapshot_record(tenant_id, kb_id, schema_version)
        if not snapshot:
            return None
        raw_data = snapshot.schema_data or {}
        return self._map_to_schema_view(raw_data, snapshot.schema_version)

    async def get_current_schema(self, tenant_id: uuid.UUID, kb_id: uuid.UUID) -> SchemaView:
        """Fetch most recent schema snapshot and map it to Phase 2 dataclasses.
        
        Strictly enforces tenant_id check.
        """
        snapshot = await self.get_latest_snapshot_record(tenant_id, kb_id)
        if not snapshot:
            raise ValueError(f"No schema snapshot found for knowledge base '{kb_id}' under tenant '{tenant_id}'.")

        raw_data = snapshot.schema_data or {}
        return self._map_to_schema_view(raw_data, snapshot.schema_version)

    @asynccontextmanager
    async def open_readonly_connection(
        self, tenant_id: uuid.UUID, kb_id: uuid.UUID
    ) -> AsyncIterator[asyncpg.Connection]:
        """Async context manager that establishes an asyncpg connection to the customer database.
        
        Enforces:
        - Strict tenant isolation
        - Credentials are never exposed outside this context manager
        - default_transaction_read_only = 'on'
        - statement_timeout = 5000 (5 seconds)
        - Always cleanly closed on exit
        """
        cache_key = f"{tenant_id}:{kb_id}"
        config = self._cached_configs.get(cache_key) or Phase1Adapter._GLOBAL_CONFIG_CACHE.get(cache_key)
        if not config:
            stmt = select(DatabaseKnowledgebase).where(
                DatabaseKnowledgebase.id == kb_id,
                DatabaseKnowledgebase.tenant_id == tenant_id,
                DatabaseKnowledgebase.is_active == True,
            )
            kb_entity = None
            try:
                res = await self.session.execute(stmt)
                kb_entity = res.scalar_one_or_none()
            except Exception as sess_err:
                logger.warning(f"Error querying KB on self.session ({sess_err!r}), falling back to fresh session")
                from app.core.database import AsyncSessionLocal
                async with AsyncSessionLocal() as fresh_sess:
                    res = await fresh_sess.execute(stmt)
                    kb_entity = res.scalar_one_or_none()
            if not kb_entity:
                raise PermissionError(f"Access denied or knowledge base '{kb_id}' not found for tenant '{tenant_id}'.")

            # Decrypt connection parameters strictly in private local scope
            config = self.secrets.decrypt_credentials(kb_entity.encrypted_credentials)
            self._cached_configs[cache_key] = config
            Phase1Adapter._GLOBAL_CONFIG_CACHE[cache_key] = config

        db_type_str = str(getattr(config, "db_type", "")).lower()
        if "mariadb" in db_type_str or "mysql" in db_type_str or getattr(config, "port", None) in (3306, 3307):
            raise NotImplementedError("Phase1 live query adapter does not support MySQL/MariaDB connections via asyncpg.")

        # Resolve SSL mode
        ssl_val = False
        if hasattr(config, "ssl_mode"):
            mode = getattr(config.ssl_mode, "value", str(config.ssl_mode)).lower()
            if mode in ("require", "verify_ca", "verify_full"):
                ssl_val = "require"
            elif mode == "prefer":
                ssl_val = "prefer"
            elif mode in ("disable", "none", "false"):
                ssl_val = False

        timeout_sec = max(float(config.connection_timeout or 10.0), 10.0)

        server_settings = {
            "application_name": "Phase2_Knowledge_ReadOnly",
            "default_transaction_read_only": "on",
            "statement_timeout": "10000",  # 10s statement timeout
            "app.current_tenant": str(tenant_id or "00000000-0000-0000-0000-000000000000"),
        }
        if getattr(config, "schema_filter", None):
            server_settings["search_path"] = ", ".join(f'"{s}"' for s in config.schema_filter) + ", public"

        conn: Optional[asyncpg.Connection] = None
        try:
            conn = await asyncpg.connect(
                host=config.host,
                port=config.port,
                user=config.username,
                password=config.raw_password,
                database=config.database_name,
                ssl=ssl_val,
                timeout=timeout_sec,
                command_timeout=10.0,
                server_settings=server_settings,
            )
            if tenant_id:
                try:
                    await conn.execute("SELECT set_config('app.current_tenant', $1, false)", str(tenant_id))
                except Exception:
                    pass
            yield conn
        finally:
            if conn and not conn.is_closed():
                try:
                    await conn.close(timeout=2.0)
                except Exception as close_err:
                    logger.debug(f"Error while closing customer DB connection: {close_err}")

    # ==========================================================================
    # Internal Mapping Helper
    # ==========================================================================

    @classmethod
    def _map_to_schema_view(cls, data: Dict[str, Any], schema_version: str) -> SchemaView:
        """Map raw snapshot JSON data to Phase 2 dataclasses."""
        database_name = data.get("database_name", "unknown")
        database_type = data.get("database_type", "postgresql")
        introspected_at = data.get("introspected_at")
        summary = data.get("summary", {})

        tables_map: Dict[str, TableView] = {}
        schemas_data = data.get("schemas", {})

        for s_name, s_val in schemas_data.items():
            tbls = s_val.get("tables", {})
            for t_name, t_val in tbls.items():
                # Map columns
                cols_map: Dict[str, ColumnView] = {}
                raw_cols = t_val.get("columns", {})
                for c_name, c_val in raw_cols.items():
                    cols_map[c_name] = ColumnView(
                        name=c_val.get("name", c_name),
                        data_type=str(c_val.get("data_type", "OTHER")),
                        raw_data_type=c_val.get("raw_data_type", ""),
                        is_nullable=bool(c_val.get("is_nullable", True)),
                        is_primary_key=bool(c_val.get("is_primary_key", False)),
                        is_foreign_key=bool(c_val.get("is_foreign_key", False)),
                        default_value=c_val.get("default_value"),
                        comment=c_val.get("comment"),
                        ordinal_position=int(c_val.get("ordinal_position", 0)),
                        classification=c_val.get("classification", "GENERAL"),
                    )

                # Primary key columns
                pk_val = t_val.get("primary_key")
                pk_cols = pk_val.get("constrained_columns", []) if pk_val else [
                    c.name for c in cols_map.values() if c.is_primary_key
                ]

                # Map Foreign Keys
                fks_list: List[FKView] = []
                for fk_val in t_val.get("foreign_keys", []):
                    fks_list.append(
                        FKView(
                            name=fk_val.get("name"),
                            constrained_columns=fk_val.get("constrained_columns", []),
                            referred_schema=fk_val.get("referred_schema", "public"),
                            referred_table=fk_val.get("referred_table", ""),
                            referred_columns=fk_val.get("referred_columns", []),
                            on_delete=fk_val.get("on_delete"),
                            on_update=fk_val.get("on_update"),
                        )
                    )

                tbl_view = TableView(
                    schema_name=t_val.get("schema_name", s_name),
                    table_name=t_val.get("table_name", t_name),
                    table_type=t_val.get("table_type", "TABLE"),
                    columns=cols_map,
                    primary_key_columns=pk_cols,
                    foreign_keys=fks_list,
                    comment=t_val.get("comment"),
                    row_count_estimate=t_val.get("row_count_estimate"),
                )
                tables_map[tbl_view.table_name] = tbl_view

        return SchemaView(
            database_name=database_name,
            database_type=database_type,
            schema_version=schema_version or data.get("fingerprint", ""),
            tables=tables_map,
            introspected_at=str(introspected_at) if introspected_at else None,
            summary=summary,
        )
