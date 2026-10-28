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
        Resolves candidate names against the LOCAL kb2_entity_values table (app DB)
        via the unified resolve_entities function.
        """
        if not session or not kb_entity:
            return None

        from ..knowledge.retrieval.entity_resolver import resolve_entities

        kb_id = getattr(kb_entity, "id", None) or kb_entity
        tenant_id = getattr(kb_entity, "tenant_id", None)

        try:
            res = await resolve_entities(
                question=extracted_name,
                kb_id=kb_id,
                session=session,
                canonical_schema=canonical_schema,
                tenant_id=tenant_id,
            )
            if res.resolved_entities:
                best = res.resolved_entities[0]
                return {
                    "ids": best.matched_value,
                    "table": best.table_name,
                    "pk_column": best.column_name,
                    "is_multiple": len(res.resolved_entities) > 1,
                }
            return None
        except Exception as e:
            logger.warning(f"[CollisionDetector] resolve_entities failed: {e}")
            return None
