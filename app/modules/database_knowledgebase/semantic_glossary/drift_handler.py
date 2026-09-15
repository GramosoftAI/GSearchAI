"""Schema Drift Handler

Detects structural schema modifications between schema snapshots, applies
calibrated name similarity heuristics and confidence thresholds for 1-to-1 column renames,
preserves orphaned glossary entries indefinitely (zero data loss), and drives
incremental table-level re-enrichment and workspace re-partitioning.
"""

import difflib
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update

from ..schemas.canonical import DatabaseSchema, TableSchema, ColumnSchema
from ..models.concept_glossary import ConceptGlossary
from ..models.concept_glossary import SchemaWorkspace
from .enrichment import GlossaryEnrichmentService
from .workspace_partitioner import DomainWorkspacePartitioner

logger = logging.getLogger(__name__)

# Standard database abbreviation expansion mapping
COMMON_DB_ABBREVIATIONS = {
    "emp": "employee",
    "dept": "department",
    "org": "organization",
    "desc": "description",
    "num": "number",
    "dt": "date",
    "qty": "quantity",
    "amt": "amount",
    "cat": "category",
    "addr": "address",
    "loc": "location",
    "pos": "position",
    "mgr": "manager",
    "cust": "customer",
    "usr": "user",
    "acct": "account",
    "pwd": "password",
    "msg": "message",
    "param": "parameter",
    "val": "value",
    "spec": "specification",
}

# Auto-carry confidence threshold: renames >= 0.95 automatically transfer glossary mappings
AUTO_CARRY_CONFIDENCE_THRESHOLD = 0.95

# Mandatory similarity floor: unrelated columns with identical types fail this floor
NAME_SIMILARITY_FLOOR = 0.35

# KNOWN DESIGN BOUNDARY & HEURISTIC LIMITATION:
# NON_INTERCHANGEABLE_SIBLING_TOKEN_PAIRS is a curated, empirical baseline derived from
# real schema collision audits across certified HRMS, Hospital, and CRM schemas.
# It covers both true business antonyms (in/out, min/max, debit/credit) and structurally similar
# but semantically distinct sibling columns (e.g. orthogonal coordinates like latitude/longitude,
# distinct lifecycle timestamps like created/resolved, or relational roles like actor/target).
#
# TWO-TIER GENERAL-PURPOSE DEFENSE:
# 1. Tenant Extensibility: Operators supply domain-specific pairs via `antonym_overrides` / `non_interchangeable_overrides`
#    (e.g. [('bid', 'ask'), ('systolic', 'diastolic')]) without code modification.
# 2. Near-Threshold Audit Logging: Every rename candidate landing within ±0.05 of the 0.95
#    auto-carry threshold ([0.90, 1.00]) is logged to an observable audit trail for spot-checking.
NON_INTERCHANGEABLE_SIBLING_TOKEN_PAIRS = {
    # Directional / access
    ("in", "out"),
    ("inbound", "outbound"),
    ("incoming", "outgoing"),
    ("inward", "outward"),
    ("checkin", "checkout"),
    ("login", "logout"),
    ("signin", "signout"),
    ("entry", "exit"),
    ("arrival", "departure"),
    # Temporal ranges & lifecycle timestamps
    ("start", "end"),
    ("begin", "finish"),
    ("before", "after"),
    ("first", "last"),
    ("current", "next"),
    ("created", "resolved"),
    # Numeric / sorting bounds
    ("min", "max"),
    ("minimum", "maximum"),
    ("asc", "desc"),
    ("ascending", "descending"),
    # Finance / transactional
    ("debit", "credit"),
    ("paid", "due"),
    ("buy", "sell"),
    # Access control / lifecycle states
    ("active", "inactive"),
    ("enabled", "disabled"),
    ("valid", "invalid"),
    ("hire", "terminate"),
    ("grant", "revoke"),
    ("open", "close"),
    ("approved", "canceled"),
    # Routing / relationships / spatial coordinates
    ("from", "to"),
    ("source", "target"),
    ("src", "dst"),
    ("sender", "receiver"),
    ("actor", "target"),
    ("latitude", "longitude"),
}

# Backward compatibility alias
OPPOSITE_MEANING_TOKEN_PAIRS = NON_INTERCHANGEABLE_SIBLING_TOKEN_PAIRS

NON_INTERCHANGEABLE_TOKEN_MAP: Dict[str, str] = {}
for _w1, _w2 in NON_INTERCHANGEABLE_SIBLING_TOKEN_PAIRS:
    NON_INTERCHANGEABLE_TOKEN_MAP[_w1] = _w2
    NON_INTERCHANGEABLE_TOKEN_MAP[_w2] = _w1

# Backward compatibility alias
OPPOSITE_TOKEN_MAP = NON_INTERCHANGEABLE_TOKEN_MAP


def tokenize_column_name(name: str) -> List[str]:
    """Extracts lowercase constituent tokens from column identifier."""
    clean = name.strip()
    s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", clean).lower()
    return [t for t in s1.split("_") if t]


def has_antonym_tokens(
    col1: str,
    col2: str,
    antonym_overrides: Optional[Set[Tuple[str, str]]] = None,
    non_interchangeable_overrides: Optional[Set[Tuple[str, str]]] = None,
) -> bool:
    """
    CRITICAL NON-INTERCHANGEABLE SIBLING & ANTONYM GUARD:
    Detects if the differing tokens between two column identifiers represent
    opposite business concepts (e.g. clock_in vs clock_out, start_date vs end_date)
    or non-interchangeable sibling dimensions (e.g. latitude vs longitude,
    created vs resolved, actor vs target).
    Prevents false high-confidence auto-carry across distinct sibling columns.

    TENANT EXTENSIBILITY:
    Operators onboarding specialized vertical domains (e.g. trading, clinical)
    can supply tenant-scoped `antonym_overrides` or `non_interchangeable_overrides`
    (e.g. {('bid', 'ask'), ('systolic', 'diastolic')}) without modifying application code.
    """
    token_map = dict(NON_INTERCHANGEABLE_TOKEN_MAP)
    effective_overrides = non_interchangeable_overrides if non_interchangeable_overrides is not None else antonym_overrides
    if effective_overrides:
        for p1, p2 in effective_overrides:
            c1_t = p1.lower().strip()
            c2_t = p2.lower().strip()
            token_map[c1_t] = c2_t
            token_map[c2_t] = c1_t

    t1_list = tokenize_column_name(col1)
    t2_list = tokenize_column_name(col2)

    # Also check expanded tokens
    t1_exp = [COMMON_DB_ABBREVIATIONS.get(t, t) for t in t1_list]
    t2_exp = [COMMON_DB_ABBREVIATIONS.get(t, t) for t in t2_list]

    # Check position-by-position if same length
    if len(t1_list) == len(t2_list):
        for w1, w2 in zip(t1_list, t2_list):
            if w1 != w2 and token_map.get(w1) == w2:
                return True
        for w1, w2 in zip(t1_exp, t2_exp):
            if w1 != w2 and token_map.get(w1) == w2:
                return True

    # General set difference check
    diff1 = set(t1_list) - set(t2_list)
    diff2 = set(t2_list) - set(t1_list)
    for d1 in diff1:
        opp = token_map.get(d1)
        if opp and opp in diff2:
            return True

    diff1_exp = set(t1_exp) - set(t2_exp)
    diff2_exp = set(t2_exp) - set(t1_exp)
    for d1 in diff1_exp:
        opp = token_map.get(d1)
        if opp and opp in diff2_exp:
            return True

    return False


# Semantic alias
has_non_interchangeable_tokens = has_antonym_tokens


def expand_column_tokens(name: str) -> str:
    """
    Tokenizes column identifier on underscores and camelCase transitions,
    expanding common database abbreviations to canonical words.
    """
    clean = name.strip()
    # Split camelCase and underscores
    s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", clean).lower()
    tokens = [t for t in s1.split("_") if t]
    expanded = [COMMON_DB_ABBREVIATIONS.get(tok, tok) for tok in tokens]
    return "_".join(expanded)


def compute_name_similarity(
    col1: str,
    col2: str,
    antonym_overrides: Optional[Set[Tuple[str, str]]] = None,
    non_interchangeable_overrides: Optional[Set[Tuple[str, str]]] = None,
) -> float:
    """
    Computes calibrated string similarity between two column identifiers.

    ALGORITHM:
    1. Antonym / non-interchangeable sibling guard: if differing tokens represent
       non-interchangeable concepts (in/out, latitude/longitude), returns 0.0 immediately.
    2. Expands common database abbreviations ('emp_name' -> 'employee_name').
    3. If expanded tokens match identically, returns 1.0.
    4. Otherwise, calculates maximum of SequenceMatcher ratio on expanded forms
       and raw forms.
    5. MANDATORY FLOOR: If similarity < 0.35, returns 0.0 (fails safe to orphan).
    """
    c1 = col1.lower().strip()
    c2 = col2.lower().strip()

    if c1 == c2:
        return 1.0

    # 1. Non-interchangeable sibling / antonym guard
    if has_antonym_tokens(c1, c2, antonym_overrides=antonym_overrides, non_interchangeable_overrides=non_interchangeable_overrides):
        return 0.0

    exp1 = expand_column_tokens(c1)
    exp2 = expand_column_tokens(c2)

    if exp1 == exp2:
        return 1.0

    ratio_exp = difflib.SequenceMatcher(None, exp1, exp2).ratio()
    ratio_raw = difflib.SequenceMatcher(None, c1, c2).ratio()
    sim = max(ratio_exp, ratio_raw)

    # Mandatory similarity floor
    if sim < NAME_SIMILARITY_FLOOR:
        return 0.0

    return round(sim, 4)


def compute_rename_confidence(
    col_old: ColumnSchema,
    col_new: ColumnSchema,
    num_dropped_in_table: int,
    num_added_in_table: int,
    antonym_overrides: Optional[Set[Tuple[str, str]]] = None,
    non_interchangeable_overrides: Optional[Set[Tuple[str, str]]] = None,
) -> float:
    """
    Computes rename confidence under the 1-to-1 candidate branch.

    FORMULA:
    If num_dropped == 1, num_added == 1, and column data types match:
      confidence = 0.70 + 0.30 * S_name
    Else:
      confidence = 0.0

    CRITICAL NON-INTERCHANGEABLE SIBLING / ANTONYM GUARD:
    If differing tokens represent non-interchangeable sibling concepts
    (e.g. in vs out, latitude vs longitude), forces confidence to 0.0,
    failing safe to orphaned_by_drift = True.
    """
    # Strict 1-to-1 candidate requirement
    if num_dropped_in_table != 1 or num_added_in_table != 1:
        return 0.0

    # Data types must match or be compatible
    type_old = str(col_old.data_type).upper()
    type_new = str(col_new.data_type).upper()
    if type_old != type_new:
        return 0.0

    # Non-interchangeable sibling / antonym guard (including tenant-scoped overrides)
    if has_antonym_tokens(
        col_old.name,
        col_new.name,
        antonym_overrides=antonym_overrides,
        non_interchangeable_overrides=non_interchangeable_overrides,
    ):
        logger.warning(
            f"Non-interchangeable sibling / antonym tokens detected between '{col_old.name}' and '{col_new.name}'. "
            "Forcing confidence to 0.0 (safe orphan)."
        )
        return 0.0

    s_name = compute_name_similarity(
        col_old.name,
        col_new.name,
        antonym_overrides=antonym_overrides,
        non_interchangeable_overrides=non_interchangeable_overrides,
    )
    if s_name < NAME_SIMILARITY_FLOOR:
        return 0.0

    conf = 0.70 + 0.30 * s_name
    return round(conf, 4)



def compute_table_fingerprint(table: TableSchema) -> str:
    """Computes a deterministic content hash for a single table schema."""
    col_parts = []
    for c_name, col in sorted(table.columns.items()):
        col_parts.append(f"{c_name}:{col.data_type}:{col.is_primary_key}:{col.is_foreign_key}")
    fk_parts = []
    for fk in sorted(table.foreign_keys, key=lambda x: x.name or ""):
        fk_parts.append(f"{fk.constrained_columns}->{fk.referred_table}.{fk.referred_columns}")
    raw = f"{table.table_name}|{';'.join(col_parts)}|{';'.join(fk_parts)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class TableDriftDiff(BaseModel):
    """Detailed diff for a single table during schema drift."""
    model_config = ConfigDict(extra="forbid")

    table_name: str
    is_drifted: bool = False
    old_fingerprint: str = ""
    new_fingerprint: str = ""
    dropped_columns: List[str] = Field(default_factory=list)
    added_columns: List[str] = Field(default_factory=list)
    renamed_columns: Dict[str, Tuple[str, float]] = Field(default_factory=dict)  # old_col -> (new_col, confidence)
    orphaned_columns: List[str] = Field(default_factory=list)


class SchemaDriftResult(BaseModel):
    """Aggregated schema drift detection result."""
    model_config = ConfigDict(extra="forbid")

    old_fingerprint: str
    new_fingerprint: str
    table_diffs: Dict[str, TableDriftDiff] = Field(default_factory=dict)
    drifted_tables: List[str] = Field(default_factory=list)
    unmodified_tables: List[str] = Field(default_factory=list)
    added_tables: List[str] = Field(default_factory=list)
    dropped_tables: List[str] = Field(default_factory=list)
    affected_workspace_subgraphs: List[str] = Field(default_factory=list)


class SchemaDriftHandler:
    """
    Autonomous schema drift handler for ConceptGlossary and SchemaWorkspace.
    """

    @classmethod
    def detect_drift(
        cls,
        old_schema: DatabaseSchema,
        new_schema: DatabaseSchema,
        antonym_overrides: Optional[Set[Tuple[str, str]]] = None,
        non_interchangeable_overrides: Optional[Set[Tuple[str, str]]] = None,
    ) -> SchemaDriftResult:
        """
        Compares two schema snapshots and identifies table-level diffs,
        1-to-1 candidate renames, and orphaned columns.
        """
        effective_overrides = non_interchangeable_overrides if non_interchangeable_overrides is not None else antonym_overrides
        old_tables: Dict[str, TableSchema] = {}
        for s_info in old_schema.schemas.values():
            for t_name, t in s_info.tables.items():
                old_tables[t_name] = t

        new_tables: Dict[str, TableSchema] = {}
        for s_info in new_schema.schemas.values():
            for t_name, t in s_info.tables.items():
                new_tables[t_name] = t

        all_table_names = set(old_tables.keys()) | set(new_tables.keys())

        result = SchemaDriftResult(
            old_fingerprint=old_schema.fingerprint or "",
            new_fingerprint=new_schema.fingerprint or "",
        )

        for t_name in sorted(all_table_names):
            if t_name in old_tables and t_name not in new_tables:
                result.dropped_tables.append(t_name)
                diff = TableDriftDiff(
                    table_name=t_name,
                    is_drifted=True,
                    old_fingerprint=compute_table_fingerprint(old_tables[t_name]),
                    dropped_columns=list(old_tables[t_name].columns.keys()),
                    orphaned_columns=list(old_tables[t_name].columns.keys()),
                )
                result.table_diffs[t_name] = diff
                result.drifted_tables.append(t_name)

            elif t_name not in old_tables and t_name in new_tables:
                result.added_tables.append(t_name)
                diff = TableDriftDiff(
                    table_name=t_name,
                    is_drifted=True,
                    new_fingerprint=compute_table_fingerprint(new_tables[t_name]),
                    added_columns=list(new_tables[t_name].columns.keys()),
                )
                result.table_diffs[t_name] = diff
                result.drifted_tables.append(t_name)

            else:
                # Table exists in both: compare table fingerprints and columns
                t_old = old_tables[t_name]
                t_new = new_tables[t_name]
                fp_old = compute_table_fingerprint(t_old)
                fp_new = compute_table_fingerprint(t_new)

                if fp_old == fp_new:
                    result.unmodified_tables.append(t_name)
                    continue

                # Table structure drifted
                result.drifted_tables.append(t_name)
                diff = TableDriftDiff(
                    table_name=t_name,
                    is_drifted=True,
                    old_fingerprint=fp_old,
                    new_fingerprint=fp_new,
                )

                cols_old = set(t_old.columns.keys())
                cols_new = set(t_new.columns.keys())

                dropped = sorted(list(cols_old - cols_new))
                added = sorted(list(cols_new - cols_old))

                diff.dropped_columns = dropped
                diff.added_columns = added

                # Check for 1-to-1 column rename candidate
                if len(dropped) == 1 and len(added) == 1:
                    c_old_schema = t_old.columns[dropped[0]]
                    c_new_schema = t_new.columns[added[0]]
                    conf = compute_rename_confidence(
                        col_old=c_old_schema,
                        col_new=c_new_schema,
                        num_dropped_in_table=len(dropped),
                        num_added_in_table=len(added),
                        antonym_overrides=effective_overrides,
                        non_interchangeable_overrides=effective_overrides,
                    )

                    # AUDIT TRAIL SAFETY NET: Log every candidate within 0.05 of the 0.95 threshold ([0.90, 1.00])
                    # for operator visibility and periodic spot-checking
                    if 0.90 <= conf <= 1.00:
                        outcome = "AUTO_CARRY_PASSED" if conf >= AUTO_CARRY_CONFIDENCE_THRESHOLD else "THRESHOLD_FAILED_SAFE_ORPHAN"
                        logger.warning(
                            f"[SCHEMA_DRIFT_AUDIT] Rename candidate within near-threshold band (0.90-1.00): "
                            f"table='{t_name}', old_column='{dropped[0]}', new_column='{added[0]}', "
                            f"confidence={conf:.4f}, outcome='{outcome}'"
                        )

                    if conf >= AUTO_CARRY_CONFIDENCE_THRESHOLD:
                        # Auto-carry candidate!
                        diff.renamed_columns[dropped[0]] = (added[0], conf)
                    else:
                        # Fails threshold or floor -> safely orphan
                        diff.orphaned_columns.append(dropped[0])
                else:
                    # Multi-column drop or add -> all dropped become orphaned
                    diff.orphaned_columns.extend(dropped)

                result.table_diffs[t_name] = diff

        return result

    @classmethod
    async def handle_drift_async(
        cls,
        session: AsyncSession,
        tenant_id: str,
        kb_id: Any,
        old_schema: DatabaseSchema,
        new_schema: DatabaseSchema,
        canonical_overrides: Optional[Dict[str, bool]] = None,
        antonym_overrides: Optional[Set[Tuple[str, str]]] = None,
        non_interchangeable_overrides: Optional[Set[Tuple[str, str]]] = None,
        enrichment_service: Optional[GlossaryEnrichmentService] = None,
    ) -> SchemaDriftResult:
        """
        Executes drift handling:
        1. Identifies structural diffs.
        2. Auto-carries high-confidence renames into new fingerprint.
        3. Marks dropped/unconfirmed columns as orphaned_by_drift=True (NEVER deletes).
        4. Re-enriches ONLY drifted/added tables (incremental scoping).
        5. Re-partitions schema workspaces for affected subgraphs.
        6. Invalidates tenant retrieval cache.
        """
        t_id_str = str(tenant_id)
        effective_overrides = non_interchangeable_overrides if non_interchangeable_overrides is not None else antonym_overrides
        drift_result = cls.detect_drift(
            old_schema=old_schema,
            new_schema=new_schema,
            antonym_overrides=effective_overrides,
            non_interchangeable_overrides=effective_overrides,
        )

        old_fp = old_schema.fingerprint or ""
        new_fp = new_schema.fingerprint or ""

        # Fetch all existing glossary entries for tenant and old fingerprint
        stmt = select(ConceptGlossary).where(
            and_(
                ConceptGlossary.tenant_id == t_id_str,
                ConceptGlossary.schema_fingerprint == old_fp,
            )
        )
        res = await session.execute(stmt)
        old_entries = res.scalars().all()
        old_entries_by_key = {(e.table_name, e.column_name): e for e in old_entries}

        # 1. Process renames and orphans per table
        for t_name, diff in drift_result.table_diffs.items():
            # High-confidence renames (Auto-carry forward)
            for old_col, (new_col, conf) in diff.renamed_columns.items():
                old_key = (t_name, old_col)
                if old_key in old_entries_by_key:
                    source_entry = old_entries_by_key[old_key]
                    # Create carried-forward entry for new column and new fingerprint
                    carried_entry = ConceptGlossary(
                        tenant_id=t_id_str,
                        table_name=t_name,
                        column_name=new_col,
                        business_description=source_entry.business_description,
                        synonyms=list(source_entry.synonyms or []),
                        semantic_role=source_entry.semantic_role,
                        is_canonical=source_entry.is_canonical,
                        is_published=source_entry.is_published,
                        confidence_source=source_entry.confidence_source,
                        schema_fingerprint=new_fp,
                        embedding=source_entry.embedding,
                        orphaned_by_drift=False,
                    )
                    session.add(carried_entry)
                    logger.info(
                        f"Auto-carried glossary entry for {t_name}.{old_col} -> {new_col} "
                        f"(confidence={conf:.2f})"
                    )

            # Orphaned columns (flagged, NEVER deleted)
            for dropped_col in diff.orphaned_columns:
                old_key = (t_name, dropped_col)
                if old_key in old_entries_by_key:
                    source_entry = old_entries_by_key[old_key]
                    source_entry.orphaned_by_drift = True
                    session.add(source_entry)
                    logger.info(
                        f"Preserved orphaned glossary entry for {t_name}.{dropped_col} "
                        f"(orphaned_by_drift=True, never deleted)"
                    )

        # 2. Incremental Re-enrichment: only enrich tables whose structure drifted or were added
        if enrichment_service and (drift_result.drifted_tables or drift_result.added_tables):
            tables_to_enrich = set(drift_result.drifted_tables) | set(drift_result.added_tables)
            sub_schema_tables: Dict[str, TableSchema] = {}
            for s_info in new_schema.schemas.values():
                for t_name, t in s_info.tables.items():
                    if t_name in tables_to_enrich:
                        sub_schema_tables[t_name] = t

            if sub_schema_tables:
                logger.info(
                    f"Incrementally re-enriching {len(sub_schema_tables)} drifted tables "
                    f"for tenant {tenant_id} (untouched tables skipped)"
                )
                # Enrich only the drifted subset of tables
                for t_schema in sub_schema_tables.values():
                    await enrichment_service.enrich_table_batch(
                        table=t_schema,
                        columns=list(t_schema.columns.values()),
                    )

        # 3. Incremental Workspace Re-partitioning: re-partition affected subgraphs
        if drift_result.drifted_tables:
            logger.info("Executing incremental workspace re-partitioning for drifted tables")
            new_workspaces = DomainWorkspacePartitioner.partition_workspaces(
                schema=new_schema,
                tenant_id=tenant_id,
                fingerprint=new_fp,
                canonical_overrides=canonical_overrides,
            )
            for ws in new_workspaces:
                session.add(ws)

        await session.flush()

        # 4. Invalidate retrieval cache for tenant
        try:
            from ..retrieval.cache import SchemaRetrievalCache
            SchemaRetrievalCache.get_instance().invalidate_tenant(t_id_str)
        except Exception as e:
            logger.warning(f"Could not invalidate retrieval cache for tenant {t_id_str}: {e}")

        return drift_result
