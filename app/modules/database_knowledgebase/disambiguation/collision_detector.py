import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from ..execution.connection_helper import connect_to_database
from ..observability.logger import DatabaseAuditLogger
from .exceptions import DisambiguationRequiredError

logger = logging.getLogger(__name__)


class CollisionDetector:
    """
    Detects name collisions in the user's EXTERNAL connected database.
    
    CRITICAL ARCHITECTURAL CONSTRAINTS:
    - Never uses a string DSN with credentials. Uses connect_to_database with discrete args.
    - Zero hardcoded database-specific table or column names in code.
    - Discovers person-table and name-columns dynamically from introspected schema or per-KB config.
    - Emits structured audit events: DISAMBIGUATION_UNAVAILABLE and DISAMBIGUATION_SKIPPED.
    - If a candidate name matches no row, it is dropped.
    """

    @classmethod
    def discover_person_table_and_columns(
        cls,
        canonical_schema: Any,
        table_override: Optional[str] = None,
        column_overrides: Optional[List[str]] = None,
    ) -> Optional[Tuple[str, str, List[str]]]:
        """
        Dynamically discover candidate person table, its primary key, and name columns.
        Returns (table_name, pk_col, name_cols) or None if no person table is identified.
        """
        if not canonical_schema or not hasattr(canonical_schema, "schemas"):
            return None

        # Build table dictionary
        tables = {}
        for s in canonical_schema.schemas.values():
            for t_name, t_schema in s.tables.items():
                tables[t_name] = t_schema

        if table_override and table_override in tables:
            target_table = tables[table_override]
            pk = target_table.primary_key_columns[0] if target_table.primary_key_columns else "id"
            if column_overrides:
                valid_cols = [c for c in column_overrides if c in target_table.columns]
                if valid_cols:
                    return table_override, pk, valid_cols
            # Find name columns in override table
            cols = [
                c.name for c in target_table.columns.values()
                if re.search(r"(name|login|email)", c.name, re.IGNORECASE)
                and not c.name.lower().endswith(('_id', '_id_id', '_pk'))
            ]
            if cols:
                return table_override, pk, cols

        # Dynamic discovery based on column names across tables
        best_candidate = None
        best_score = 0
        best_pk = "id"
        best_cols = []

        for t_name, t_schema in tables.items():
            t_lower = t_name.lower()
            name_cols = [
                c.name for c in t_schema.columns.values()
                if re.search(r"(first_?name|last_?name|full_?name|user_?name|display_?name|login)", c.name, re.IGNORECASE)
                and not c.name.lower().endswith(('_id', '_id_id', '_pk'))
            ]
            if not name_cols:
                continue

            score = len(name_cols) * 10
            if re.search(r"(user|employee|person|member|account|contact)", t_lower):
                score += 50
            if t_schema.primary_key_columns:
                score += 10

            if score > best_score:
                best_score = score
                best_candidate = t_name
                best_pk = t_schema.primary_key_columns[0] if t_schema.primary_key_columns else "id"
                best_cols = name_cols

        if best_candidate and best_cols:
            return best_candidate, best_pk, best_cols

        return None

    @classmethod
    async def check_for_user_collisions(
        cls,
        extracted_name: str,
        kb_entity: Any,
        secret_manager: Any,
        canonical_schema: Optional[Any] = None,
        audit_context: Optional[Dict[str, Any]] = None,
        entity_table_override: Optional[str] = None,
        entity_columns_override: Optional[List[str]] = None,
        notices_out: Optional[List[str]] = None,
    ) -> Optional[int]:
        """
        Checks the EXTERNAL connected database for users matching the extracted name.
        Uses shared discrete connection helper, discovers person table from schema/config,
        and logs audit events on failure or skip.
        """
        ctx = audit_context or {}
        query_id = ctx.get("query_id", "unknown")
        tenant_id = ctx.get("tenant_id", getattr(kb_entity, "tenant_id", "unknown"))
        kb_id = ctx.get("knowledgebase_id", getattr(kb_entity, "id", "unknown"))

        # Step 1: Discover person table & columns
        discovery = cls.discover_person_table_and_columns(
            canonical_schema=canonical_schema,
            table_override=entity_table_override,
            column_overrides=entity_columns_override,
        )
        if not discovery:
            reason = "Could not determine a person/entity table from schema or settings."
            DatabaseAuditLogger.emit_event(
                event_name="DISAMBIGUATION_SKIPPED",
                query_id=query_id,
                tenant_id=tenant_id,
                knowledgebase_id=kb_id,
                data={"reason": reason, "candidate_name": extracted_name},
                level=logging.INFO,
            )
            logger.info(f"[DISAMBIGUATION_SKIPPED] {reason}")
            return None

        table_name, pk_col, name_cols = discovery

        # Step 2: Connect using shared discrete connection helper
        try:
            config = secret_manager.decrypt_credentials(kb_entity.encrypted_credentials)
        except Exception as e:
            reason = f"Credential decryption failure: {e}"
            DatabaseAuditLogger.emit_event(
                event_name="DISAMBIGUATION_UNAVAILABLE",
                query_id=query_id,
                tenant_id=tenant_id,
                knowledgebase_id=kb_id,
                data={"reason": reason, "candidate_name": extracted_name},
                level=logging.WARNING,
            )
            if notices_out is not None:
                notices_out.append(f"Entity disambiguation unavailable: {reason}")
            logger.warning(f"[DISAMBIGUATION_UNAVAILABLE] {reason}")
            return None

        conn = None
        try:
            conn = await connect_to_database(
                db_config=config,
                timeout_seconds=5.0,
                read_only=True,
            )
        except Exception as e:
            reason = f"Connection failed: {e}"
            DatabaseAuditLogger.emit_event(
                event_name="DISAMBIGUATION_UNAVAILABLE",
                query_id=query_id,
                tenant_id=tenant_id,
                knowledgebase_id=kb_id,
                data={"reason": reason, "candidate_name": extracted_name},
                level=logging.WARNING,
            )
            if notices_out is not None:
                notices_out.append(f"Entity disambiguation unavailable: {reason}")
            logger.warning(f"[DISAMBIGUATION_UNAVAILABLE] {reason}")
            return None

        # Step 3: Query external database using discovered table & columns
        try:
            select_cols = ", ".join(dict.fromkeys([pk_col] + name_cols))
            where_clause = " OR ".join([f"CAST({col} AS TEXT) ILIKE $1" for col in name_cols])
            query = f"SELECT {select_cols} FROM {table_name} WHERE {where_clause}"
            pattern = f"%{extracted_name}%"
            rows = await conn.fetch(query, pattern)
        except Exception as e:
            reason = f"Lookup failed against table '{table_name}': {e}"
            DatabaseAuditLogger.emit_event(
                event_name="DISAMBIGUATION_UNAVAILABLE",
                query_id=query_id,
                tenant_id=tenant_id,
                knowledgebase_id=kb_id,
                data={"reason": reason, "candidate_name": extracted_name, "table": table_name},
                level=logging.WARNING,
            )
            if notices_out is not None:
                notices_out.append(f"Entity disambiguation unavailable: {reason}")
            logger.warning(f"[DISAMBIGUATION_UNAVAILABLE] {reason}")
            return None
        finally:
            if conn:
                await conn.close()

        # Step 4: Disambiguation evaluation
        if len(rows) > 1:
            options = []
            for row in rows:
                label_parts = [str(row[c]) for c in name_cols if row.get(c)]
                label = " ".join(label_parts) if label_parts else f"ID {row[pk_col]}"
                options.append({"id": row[pk_col], "label": label})

            raise DisambiguationRequiredError(
                message=f"I found {len(rows)} people matching '{extracted_name}'. Which one do you mean?",
                options=options,
                entity_type="user",
            )
        elif len(rows) == 1:
            resolved_id = rows[0][pk_col]
            logger.info(f"[DISAMBIGUATION] Resolved '{extracted_name}' -> ID {resolved_id} in {table_name}")
            return resolved_id

        # 0 rows matched: candidate name is NOT a person, drop it
        logger.info(f"[DISAMBIGUATION] Candidate '{extracted_name}' matched 0 rows in '{table_name}'. Dropping candidate.")
        return None
