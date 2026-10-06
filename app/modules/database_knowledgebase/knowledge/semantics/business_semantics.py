"""Phase 2 Knowledge Layer: Business Semantics (Glossary, Metrics, Business Rules)

Implements:
1. kb2_knowledge_items items:
   - glossary: term, aliases, target (table|column|metric|value_filter), target_key, description
   - metric: name, aliases, expression, grain, unit, depends_on (item_keys).
     Validated with sqlglot and checked that it references existing columns.
   - rule: scope, condition, instruction text, precedence
2. Auto-seed glossary and metrics from Step 7 suggestions as source='llm', status='draft'.
3. Stale check: metrics / rules referencing dropped objects become stale.
4. GlossaryResolver.resolve(terms): matches ranked confirmed over draft, with target keys.
"""

import uuid
import re
import hashlib
import json
import logging
from typing import Optional, Dict, Any, List, Set, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, field

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

try:
    import sqlglot
    import sqlglot.expressions as exp
    SQLGLOT_AVAILABLE = True
except ImportError:
    SQLGLOT_AVAILABLE = False

from ..repositories.knowledge_item_repository import KnowledgeItemRepository
from ..models.knowledge_items import KB2KnowledgeItem

logger = logging.getLogger(__name__)


def validate_metric_expression(
    expression: str,
    available_columns: Set[str],
) -> Tuple[bool, List[str], Optional[str]]:
    """Validate metric SQL expression using sqlglot and extract column dependencies.
    
    Returns: (is_valid, column_dependencies, error_message)
    """
    if not expression or not expression.strip():
        return False, [], "Expression cannot be empty"

    expr_str = expression.strip()
    columns_found: Set[str] = set()

    if SQLGLOT_AVAILABLE:
        try:
            parsed = sqlglot.parse_one(expr_str, read="postgres")
            for col in parsed.find_all(exp.Column):
                col_name = col.name.lower()
                columns_found.add(col_name)
        except Exception as exc:
            # Fallback regex parsing if complex fragment
            col_matches = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", expr_str)
            # Filter sql keywords
            sql_kw = {"sum", "avg", "count", "min", "max", "case", "when", "then", "else", "end", "coalesce", "null", "as", "distinct"}
            for cm in col_matches:
                if cm.lower() not in sql_kw:
                    columns_found.add(cm.lower())
    else:
        # Regex fallback
        col_matches = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", expr_str)
        sql_kw = {"sum", "avg", "count", "min", "max", "case", "when", "then", "else", "end", "coalesce", "null", "as", "distinct"}
        for cm in col_matches:
            if cm.lower() not in sql_kw:
                columns_found.add(cm.lower())

    # Check if all columns exist in available columns (case-insensitive)
    norm_avail = {c.lower() for c in available_columns}
    missing = [c for c in columns_found if c not in norm_avail]
    if missing:
        return False, list(columns_found), f"Expression references unknown column(s): {', '.join(missing)}"

    return True, list(columns_found), None


async def seed_suggested_glossary_and_metrics(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    schema_version: str,
    item_repo: KnowledgeItemRepository,
    suggested_metrics: List[Dict[str, Any]],
    candidate_glossary: List[Dict[str, Any]],
    existing_column_keys: Set[str],
) -> Dict[str, int]:
    """Auto-seed glossary terms and metrics from LLM suggestions as source='llm', status='draft'."""
    seeded_metrics = 0
    seeded_glossary = 0

    # Extract column names from existing keys (schema.table.column -> column)
    avail_cols = {k.split(".")[-1] for k in existing_column_keys}

    # 1. Seed Metrics
    for m in suggested_metrics:
        name = m.get("name", "").strip()
        expr = m.get("expression", "").strip()
        if not name or not expr:
            continue

        is_valid, deps, err = validate_metric_expression(expr, avail_cols)
        if not is_valid:
            logger.debug(f"[Seed Metrics] Skipping invalid metric {name}: {err}")
            continue

        item_key = f"metric:{re.sub(r'[^a-zA-Z0-9_]+', '_', name.lower())}"
        # Map column dependencies to item_keys
        dep_keys = [k for k in existing_column_keys if k.split(".")[-1].lower() in deps]

        payload = {
            "name": name,
            "aliases": m.get("aliases", []),
            "expression": expr,
            "grain": m.get("grain"),
            "unit": m.get("unit"),
            "depends_on": dep_keys,
            "description": m.get("description"),
        }
        obj_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

        await item_repo.upsert_item(
            db_knowledgebase_id=kb_id,
            item_type="metric",
            item_key=item_key,
            valid_from_version=schema_version,
            object_hash=obj_hash,
            source="llm",
            payload=payload,
            confidence=0.80,
            status="draft",
        )
        seeded_metrics += 1

    # 2. Seed Glossary Terms
    for g in candidate_glossary:
        term = g.get("term", "").strip()
        target_name = g.get("target_name", "").strip()
        if not term:
            continue

        item_key = f"glossary:{re.sub(r'[^a-zA-Z0-9_]+', '_', term.lower())}"
        payload = {
            "term": term,
            "aliases": g.get("aliases", []),
            "target": g.get("target_type", "table"),
            "target_key": target_name,
            "description": g.get("description", ""),
        }
        obj_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

        await item_repo.upsert_item(
            db_knowledgebase_id=kb_id,
            item_type="glossary",
            item_key=item_key,
            valid_from_version=schema_version,
            object_hash=obj_hash,
            source="llm",
            payload=payload,
            confidence=0.85,
            status="draft",
        )
        seeded_glossary += 1

    await item_repo.db.commit()
    return {"metrics_seeded": seeded_metrics, "glossary_seeded": seeded_glossary}


async def mark_stale_business_semantics(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    db_session: AsyncSession,
    current_item_keys: Set[str],
) -> int:
    """Mark metrics and rules as 'stale' if any object they depend on was dropped."""
    stmt = select(KB2KnowledgeItem).where(
        KB2KnowledgeItem.tenant_id == tenant_id,
        KB2KnowledgeItem.db_knowledgebase_id == kb_id,
        KB2KnowledgeItem.item_type.in_(["metric", "rule"]),
        KB2KnowledgeItem.status != "stale",
    )
    res = await db_session.execute(stmt)
    items = res.scalars().all()

    stale_count = 0
    for it in items:
        payload = it.payload or {}
        depends_on = payload.get("depends_on", [])
        if depends_on:
            # Check if any dependency is missing from current active items
            missing = [d for d in depends_on if d not in current_item_keys]
            if missing:
                it.status = "stale"
                it.updated_at = datetime.now(timezone.utc)
                stale_count += 1

    if stale_count > 0:
        await db_session.commit()
    return stale_count


# ==============================================================================
# Glossary Resolver
# ==============================================================================

@dataclass
class ResolvedGlossaryMatch:
    term: str
    target_type: str
    target_key: str
    description: str
    status: str  # 'confirmed' or 'draft'
    score: float
    matched_alias: Optional[str] = None


class GlossaryResolver:
    """Resolves business terms / jargon to database targets (tables, columns, metrics)."""

    def __init__(self, db_session: AsyncSession, tenant_id: uuid.UUID):
        self.db_session = db_session
        self.tenant_id = tenant_id

    async def resolve(
        self,
        db_knowledgebase_id: uuid.UUID,
        terms: List[str],
    ) -> Dict[str, List[ResolvedGlossaryMatch]]:
        """Resolve list of query terms against confirmed and draft glossary items.
        
        Rank confirmed matches over draft matches.
        """
        if not terms:
            return {}

        # Fetch active glossary items
        stmt = select(KB2KnowledgeItem).where(
            KB2KnowledgeItem.tenant_id == self.tenant_id,
            KB2KnowledgeItem.db_knowledgebase_id == db_knowledgebase_id,
            KB2KnowledgeItem.item_type == "glossary",
            KB2KnowledgeItem.status.in_(["confirmed", "draft"]),
        )
        res = await self.db_session.execute(stmt)
        items = res.scalars().all()

        results: Dict[str, List[ResolvedGlossaryMatch]] = {}

        for query_term in terms:
            q_norm = query_term.strip().lower()
            matches = []

            for it in items:
                payload = it.payload or {}
                t_val = payload.get("term", "").lower().strip()
                aliases = [a.lower().strip() for a in payload.get("aliases", [])]

                matched_alias = None
                score = 0.0

                if q_norm == t_val:
                    score = 1.0
                elif q_norm in aliases:
                    score = 0.95
                    matched_alias = q_norm
                elif q_norm in t_val or t_val in q_norm:
                    score = 0.70

                if score > 0.0:
                    # Confirmed boost
                    rank_score = score + (0.50 if it.status == "confirmed" else 0.0)
                    matches.append(
                        ResolvedGlossaryMatch(
                            term=payload.get("term", ""),
                            target_type=payload.get("target", "table"),
                            target_key=payload.get("target_key", ""),
                            description=payload.get("description", ""),
                            status=it.status,
                            score=rank_score,
                            matched_alias=matched_alias,
                        )
                    )

            # Sort confirmed first, then highest score
            matches.sort(key=lambda m: (m.status == "confirmed", m.score), reverse=True)
            results[query_term] = matches

        return results
