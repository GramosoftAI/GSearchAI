import asyncio
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..knowledge.models.knowledge_items import KB2EntityValue
from ..observability.logger import DatabaseAuditLogger
from .exceptions import DisambiguationRequiredError
from ..sql_security.policy import DenyPolicyConfig

logger = logging.getLogger(__name__)


class CollisionDetector:
    """
    Detects name collisions against the local kb2_entity_values table (app DB).
    
    CRITICAL ARCHITECTURAL CONSTRAINTS:
    - Zero connections to external customer databases on the query path.
    - Resolves candidate names strictly from indexed kb2_entity_values in the local app DB.
    - If no local match is found, returns None (no collision, drops candidate).
    - Discovers person-table and name-columns dynamically from introspected schema or per-KB config.
    - Emits structured audit events: DISAMBIGUATION_UNAVAILABLE and DISAMBIGUATION_SKIPPED.
    """

    @classmethod
    def discover_person_table_and_columns(
        cls,
        canonical_schema: Any,
        table_override: Optional[str] = None,
        column_overrides: Optional[List[str]] = None,
        security_overrides: Optional[Dict[str, Any]] = None,
    ) -> Optional[Tuple[str, str, List[str], List[str]]]:
        """
        Dynamically discover candidate person table, its primary key, name columns, and distinguishing columns.
        Returns (table_name, pk_col, name_cols, distinguishing_cols) or None if no person table is identified.
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
            dist_cols = [
                c.name for c in target_table.columns.values()
                if re.search(r"(email|login|department|org|title|role|username)", c.name, re.IGNORECASE)
                and not c.name.lower().endswith(('_id', '_id_id', '_pk'))
                and not DenyPolicyConfig.is_denied(c.name, overrides=security_overrides, is_column=True)
            ][:3]
            if cols:
                return table_override, pk, cols, dist_cols

        # Dynamic discovery based on column names across tables
        best_candidate = None
        best_score = 0
        best_pk = "id"
        best_cols = []
        distinguishing_cols = []
        for t_name, t_schema in tables.items():
            t_lower = t_name.lower()
            name_cols = [
                c.name for c in t_schema.columns.values()
                if re.search(r"(^name$|_name$|first_?name|last_?name|full_?name|user_?name|display_?name|login)", c.name, re.IGNORECASE)
                and not c.name.lower().endswith(('_id', '_id_id', '_pk'))
            ]
            if not name_cols:
                continue

            score = len(name_cols) * 10
            if re.search(r"(employee|staff|worker)", t_lower):
                score += 80
            elif re.search(r"(customer|client)", t_lower):
                score += 65
            elif re.search(r"(user|person|member|account|contact)", t_lower):
                score += 40
            if t_schema.primary_key_columns:
                score += 10

            if score > best_score:
                best_score = score
                best_candidate = t_name
                best_pk = t_schema.primary_key_columns[0] if t_schema.primary_key_columns else "id"
                best_cols = name_cols
                
                # Get non-denied distinguishing columns
                distinguishing_cols = [
                    c.name for c in t_schema.columns.values()
                    if re.search(r"(email|login|department|org|title|role|username|phone)", c.name, re.IGNORECASE)
                    and not c.name.lower().endswith(('_id', '_id_id', '_pk'))
                    and not DenyPolicyConfig.is_denied(c.name, overrides=security_overrides, is_column=True)
                ][:3]

        if best_candidate and best_cols:
            return best_candidate, best_pk, best_cols, distinguishing_cols

        return None

    @classmethod
    async def check_for_user_collisions(
        cls,
        extracted_name: str,
        kb_entity: Any,
        secret_manager: Optional[Any] = None,
        canonical_schema: Optional[Any] = None,
        audit_context: Optional[Dict[str, Any]] = None,
        entity_table_override: Optional[str] = None,
        entity_columns_override: Optional[List[str]] = None,
        notices_out: Optional[List[str]] = None,
        session: Optional[AsyncSession] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Resolves candidate names against the LOCAL kb2_entity_values table (app DB).
        Does NOT open any connection to the external customer database.
        If no local match is found, returns None (no collision).
        """
        ctx = audit_context or {}
        query_id = ctx.get("query_id", "unknown")
        tenant_id = ctx.get("tenant_id", getattr(kb_entity, "tenant_id", "unknown"))
        kb_id = ctx.get("knowledgebase_id", getattr(kb_entity, "id", "unknown"))

        # Step 1: Discover person table & columns from canonical schema
        discovery = cls.discover_person_table_and_columns(
            canonical_schema=canonical_schema,
            table_override=entity_table_override,
            column_overrides=entity_columns_override,
            security_overrides=kb_entity.settings.get("security_overrides", {}) if hasattr(kb_entity, "settings") and kb_entity.settings else {},
        )
        if not discovery:
            reason = "Could not determine a person/entity table from schema or settings."
            DatabaseAuditLogger.emit_event(
                event_name="DISAMBIGUATION_SKIPPED",
                query_id=query_id,
                tenant_id=str(tenant_id),
                knowledgebase_id=str(kb_id),
                data={"reason": reason, "candidate_name": extracted_name},
                level=logging.INFO,
            )
            logger.info(f"[DISAMBIGUATION_SKIPPED] {reason}")
            return None

        table_name, pk_col, name_cols, distinguishing_cols = discovery

        # Step 2: Resolve names strictly from the local kb2_entity_values table (app DB)
        if not session:
            logger.info("[DISAMBIGUATION] No app database session provided for local collision check.")
            return None

        try:
            tenant_uuid = uuid.UUID(str(tenant_id)) if tenant_id else None
            kb_uuid = uuid.UUID(str(kb_id)) if kb_id else None
        except Exception:
            tenant_uuid = tenant_id
            kb_uuid = kb_id

        tbl_names = [table_name]
        if "." in table_name:
            tbl_names.append(table_name.split(".")[-1])

        clean_name = extracted_name.strip().lower()

        try:
            conds = [
                KB2EntityValue.db_knowledgebase_id == kb_uuid,
                KB2EntityValue.table_name.in_(tbl_names),
                or_(
                    KB2EntityValue.normalized_value == clean_name,
                    KB2EntityValue.normalized_value.ilike(f"%{clean_name}%"),
                ),
            ]
            if tenant_uuid:
                conds.append(KB2EntityValue.tenant_id == tenant_uuid)
            if name_cols:
                conds.append(KB2EntityValue.column_name.in_(name_cols))

            stmt = select(KB2EntityValue).where(*conds)
            res = await session.execute(stmt)
            matched_records = res.scalars().all()

            # Fallback if no match with column restriction
            if not matched_records and name_cols:
                fallback_conds = [
                    KB2EntityValue.db_knowledgebase_id == kb_uuid,
                    KB2EntityValue.table_name.in_(tbl_names),
                    or_(
                        KB2EntityValue.normalized_value == clean_name,
                        KB2EntityValue.normalized_value.ilike(f"%{clean_name}%"),
                    ),
                ]
                if tenant_uuid:
                    fallback_conds.append(KB2EntityValue.tenant_id == tenant_uuid)
                res_fb = await session.execute(select(KB2EntityValue).where(*fallback_conds))
                matched_records = res_fb.scalars().all()

            if not matched_records:
                # 0 rows matched: candidate name is NOT in local entity values, return no collision
                logger.info(f"[DISAMBIGUATION] Candidate '{extracted_name}' matched 0 rows in local kb2_entity_values for '{table_name}'. Dropping candidate.")
                return None

            # Deduplicate matches by normalized value / raw value
            unique_matches: Dict[str, KB2EntityValue] = {}
            for r in matched_records:
                k = r.normalized_value.strip().lower()
                if k not in unique_matches:
                    unique_matches[k] = r

            matched_col = matched_records[0].column_name or pk_col

            if len(unique_matches) > 1:
                all_vals = [r.raw_value for r in unique_matches.values()]
                logger.info(
                    f"[DISAMBIGUATION] Found {len(unique_matches)} matching entity values for '{extracted_name}' "
                    f"in local kb2_entity_values ({table_name}): {all_vals}. Collision detected."
                )
                return {
                    "ids": all_vals,
                    "table": table_name,
                    "pk_column": matched_col,
                    "is_multiple": True,
                }
            elif len(unique_matches) == 1:
                resolved_rec = list(unique_matches.values())[0]
                resolved_val = resolved_rec.raw_value
                resolved_col = resolved_rec.column_name or pk_col
                logger.info(f"[DISAMBIGUATION] Resolved '{extracted_name}' -> '{resolved_val}' in {table_name}.{resolved_col}")
                return {
                    "ids": resolved_val,
                    "table": table_name,
                    "pk_column": resolved_col,
                    "is_multiple": False,
                }

            return None
        except Exception as e:
            reason = f"Local kb2_entity_values lookup failed against table '{table_name}': {e}"
            DatabaseAuditLogger.emit_event(
                event_name="DISAMBIGUATION_UNAVAILABLE",
                query_id=query_id,
                tenant_id=str(tenant_id),
                knowledgebase_id=str(kb_id),
                data={"reason": reason, "candidate_name": extracted_name, "table": table_name},
                level=logging.WARNING,
            )
            if notices_out is not None:
                notices_out.append(f"Entity disambiguation unavailable: {reason}")
            logger.warning(f"[DISAMBIGUATION_UNAVAILABLE] {reason}")
            return None
