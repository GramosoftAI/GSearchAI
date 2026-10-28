"""Phase 3 Step 3.4 TableRetriever

Multi-signal Table Retrieval combining:
1. kb2_schema_docs Full-Text Search (AND query first, OR + prefix fallback)
2. Vector search via EmbeddingGenerator
3. Glossary hits: (glossary doc -> target table)
4. Metric hits: (metric doc -> tables it depends on)
5. Value-index hits: (matched entity value -> its table, with frequency boost)
6. Graded token & synonym matching (scaled to RRF magnitude)

Signals combined with Reciprocal Rank Fusion (RRF):
    score = sum( weight / (k + rank) )
Multipliers:
- kind multipliers (entity 1.0, lookup 0.9, link 0.5, journal 0.4, system 0.1)
  with dynamic restoration for journal (history cues) and link (association cues).
- emptiness penalty (0.3x unless exact match).
Outputs top K tables with score, explanation reasons, and gap signals.
"""

import uuid
import re
import time
import logging
from typing import Optional, List, Dict, Any, Set, Tuple, Union
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.embeddings import EmbeddingGenerator
from ..repositories.schema_doc_repository import SchemaDocRepository
from ..repositories.entity_value_repository import EntityValueRepository
from ..repositories.knowledge_item_repository import KnowledgeItemRepository
from ..models.knowledge_items import KB2SchemaDoc, KB2KnowledgeItem
from app.modules.database_knowledgebase.models.table_alias import KBTableAlias
from app.modules.database_knowledgebase.models.database_knowledgebase import (
    DatabaseKnowledgebase,
    DatabaseSchemaSnapshot,
)
from .analyzer import QuestionFrame

logger = logging.getLogger(__name__)

RRF_K = 60

DEFAULT_NON_STRIPPING_S_WORDS: Set[str] = {
    "news", "status", "series", "address", "access", "analysis",
    "bus", "basis", "data", "canvas", "class", "process", "business",
    "lens", "species", "corpus",
}


def split_identifier(name: str) -> List[str]:
    """Tokenize table/column identifiers on underscores, hyphens, dots, and camelCase transitions."""
    if not name:
        return []
    s = re.sub(r"[_\-\.]+", " ", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    return [tok.lower().strip() for tok in s.split() if tok.strip()]


def get_singular_plural_variants(
    term: str,
    exception_words: Optional[Set[str]] = None,
    known_vocab: Optional[Set[str]] = None,
) -> Set[str]:
    """Generate normalized singular and plural forms for a word or phrase.

    Guards against stripping trailing 's' when it would produce a non-word stem
    for known exception words (e.g., news, status, series, address, access, analysis, bus).
    Only generates singular variants that equal a known vocab term (if provided) or
    represent common English morphology.
    """
    term = term.lower().strip()
    if not term:
        return set()
    variants = {term}
    exceptions = exception_words if exception_words is not None else DEFAULT_NON_STRIPPING_S_WORDS

    # Plural to singular
    if term.endswith("ies") and len(term) > 4:
        cand = term[:-3] + "y"
        if known_vocab is None or cand in known_vocab or len(cand) >= 3:
            variants.add(cand)
    elif term.endswith(("ses", "xes", "zes", "ches", "shes")) and len(term) > 4:
        cand = term[:-2]
        if known_vocab is None or cand in known_vocab or len(cand) >= 3:
            variants.add(cand)
    elif term.endswith("s") and len(term) > 2 and not term.endswith("ss"):
        if term not in exceptions:
            cand = term[:-1]
            if known_vocab is None or cand in known_vocab or len(cand) >= 3:
                variants.add(cand)

    # Singular to plural
    if term.endswith("y") and len(term) > 2 and term[-2] not in "aeiou":
        variants.add(term[:-1] + "ies")
    elif term.endswith(("s", "x", "z", "ch", "sh")):
        variants.add(term + "es")
    else:
        variants.add(term + "s")

    return variants


class TableCandidate(BaseModel):
    table_name: str
    score: float
    reasons: List[str] = Field(default_factory=list)
    signals: Dict[str, float] = Field(default_factory=dict)


class TableRankingResult(list):
    """List of TableCandidate with gap signal metadata for confidence gating (STEP 4)."""

    def __init__(
        self,
        candidates: List[TableCandidate],
        top1_score: float = 0.0,
        margin: float = 0.0,
        top3_signals: Optional[List[Dict[str, Any]]] = None,
        stage_timings: Optional[Dict[str, float]] = None,
    ):
        super().__init__(candidates)
        self.top1_score = round(float(top1_score), 4)
        self.margin = round(float(margin), 4)
        self.top3_signals = top3_signals or []
        self.stage_timings = stage_timings or {}

    @property
    def ranking(self) -> List[TableCandidate]:
        return list(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "top1_score": self.top1_score,
            "margin": self.margin,
            "top3_signals": self.top3_signals,
            "candidates": [c.model_dump() if hasattr(c, "model_dump") else c.dict() for c in self],
        }


class TableMetadata(BaseModel):
    table_name: str
    kind: str = "entity"
    is_empty: bool = False
    aliases: Set[str] = Field(default_factory=set)
    parts: List[str] = Field(default_factory=list)


class TableRetrieverConfig(BaseModel):
    """Configuration knobs for TableRetriever signals, graded token boosts, and multipliers."""

    # RRF Signal Weights
    weights: Dict[str, float] = Field(
        default_factory=lambda: {
            "fts": 1.0,
            "vector": 1.0,
            "glossary": 1.2,
            "metric": 1.1,
            "value_index": 1.3,
        }
    )

    # Graded Token Match Boosts (scaled to same order of magnitude as RRF signals: ~0.01 - 0.02)
    boost_exact_table: float = 0.02       # Full table-name match (singular/plural normalised)
    boost_synonym: float = 0.02           # Match against a stored unique synonym/alias
    boost_compound_part: float = 0.004    # Token matches only ONE part of compound name (about 1/5 of strong)

    # Kind Multipliers (STEP 2: entity 1.0, lookup 0.9, link 0.5, journal 0.4, system 0.1)
    kind_multipliers: Dict[str, float] = Field(
        default_factory=lambda: {
            "entity": 1.0,
            "lookup": 0.9,
            "link": 0.5,
            "journal": 0.4,
            "system": 0.1,
        }
    )
    default_kind_multiplier: float = 1.0

    # History words that restore journal multiplier to 1.0
    history_words: List[str] = Field(
        default_factory=lambda: [
            "history", "changed", "change log", "changelog", "audit",
            "journal", "previous", "versions of", "who changed"
        ]
    )

    # Association words that restore link multiplier to 1.0
    association_words: List[str] = Field(
        default_factory=lambda: [
            "assigned", "member of", "member", "members", "membership",
            "mapping", "mapped", "associated", "linked", "belongs to"
        ]
    )

    # Emptiness multiplier (STEP 2: is_empty tables: x0.3, unless question tokens match table name exactly)
    empty_table_multiplier: float = 0.3

    # Column evidence combination: 2nd best column bonus (applied to max column score)
    second_column_bonus_multiplier: float = 0.2

    # Maximum vector rank for table-doc to be counted as table-level evidence
    table_vector_top_rank: int = 3

    # Column-only damping multiplier (applied when table evidence has no table-level signals)
    column_only_multiplier: float = 0.5

    # Non-stripping "s" words (do not strip trailing 's' to avoid non-word stems)
    non_stripping_s_words: Set[str] = Field(
        default_factory=lambda: set(DEFAULT_NON_STRIPPING_S_WORDS)
    )

    # Process-level metadata cache TTL in seconds
    cache_ttl_seconds: float = 300.0


# Process-level cache for table metadata:
# Key: (kb_id_str, schema_version_str)
# Value: (cached_at_timestamp, table_meta, ambiguous_synonyms)
_PROCESS_TABLE_METADATA_CACHE: Dict[Tuple[str, str], Tuple[float, Dict[str, TableMetadata], Set[str]]] = {}


class TableRetriever:
    """Retrieves and ranks candidate relational tables using hybrid signals and RRF."""

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: str | uuid.UUID,
        weights: Optional[Dict[str, float]] = None,
        config: Optional[TableRetrieverConfig] = None,
    ):
        self.db = db
        self.tenant_id = uuid.UUID(str(tenant_id))
        self.schema_doc_repo = SchemaDocRepository(db=db, tenant_id=self.tenant_id)
        self.entity_repo = EntityValueRepository(db=db, tenant_id=self.tenant_id)
        self.item_repo = KnowledgeItemRepository(db=db, tenant_id=self.tenant_id)
        self.config = config or TableRetrieverConfig()
        if weights:
            self.config.weights.update(weights)
        self.weights = self.config.weights

        self.last_ranking_result: Optional[TableRankingResult] = None

    @classmethod
    def clear_cache(cls, kb_id: Optional[uuid.UUID] = None):
        """Clear process-level table metadata cache for a specific KB or entirely."""
        if kb_id is None:
            _PROCESS_TABLE_METADATA_CACHE.clear()
        else:
            kb_str = str(kb_id)
            for k in list(_PROCESS_TABLE_METADATA_CACHE.keys()):
                if k[0] == kb_str:
                    del _PROCESS_TABLE_METADATA_CACHE[k]

    async def _get_kb_table_metadata(
        self, db_knowledgebase_id: uuid.UUID
    ) -> Tuple[Dict[str, TableMetadata], Set[str]]:
        """Fetch table metadata (kind, is_empty, aliases/synonyms, parts) and ambiguous synonyms for this KB.

        Cached at process level keyed by (kb_id, schema_version) with TTL.
        Invalidates automatically when schema_version changes.
        """
        kb_id_str = str(db_knowledgebase_id)

        # 0. Get current schema_version for cache key and invalidation check
        current_schema_version = ""
        try:
            stmt_ver = select(DatabaseKnowledgebase.schema_version).where(
                DatabaseKnowledgebase.id == db_knowledgebase_id
            )
            res_ver = await self.db.execute(stmt_ver)
            current_schema_version = res_ver.scalar_one_or_none() or ""
        except Exception as e:
            logger.debug(f"[TableRetriever] Could not fetch schema_version: {e}")

        cache_key = (kb_id_str, str(current_schema_version))

        # Check process-level cache
        if cache_key in _PROCESS_TABLE_METADATA_CACHE:
            cached_at, table_meta, ambiguous_synonyms = _PROCESS_TABLE_METADATA_CACHE[cache_key]
            if time.monotonic() - cached_at < self.config.cache_ttl_seconds:
                return table_meta, ambiguous_synonyms
            else:
                logger.debug(f"[TableRetriever] Cache TTL expired for {cache_key}")
                del _PROCESS_TABLE_METADATA_CACHE[cache_key]

        # Invalidate any stale cache entries for this kb_id with different schema_version
        for sk in list(_PROCESS_TABLE_METADATA_CACHE.keys()):
            if sk[0] == kb_id_str and sk[1] != current_schema_version:
                logger.debug(
                    f"[TableRetriever] Schema version change detected: invalidating old cache for KB {kb_id_str} "
                    f"(old: {sk[1]}, new: {current_schema_version})"
                )
                del _PROCESS_TABLE_METADATA_CACHE[sk]

        table_meta: Dict[str, TableMetadata] = {}

        # 1. Fetch from kb2_knowledge_items (item_type = 'table')
        try:
            stmt_ki = select(KB2KnowledgeItem.item_key, KB2KnowledgeItem.payload).where(
                KB2KnowledgeItem.tenant_id == self.tenant_id,
                KB2KnowledgeItem.db_knowledgebase_id == db_knowledgebase_id,
                KB2KnowledgeItem.item_type == "table",
            )
            res_ki = await self.db.execute(stmt_ki)
            for item_key, payload in res_ki.all():
                payload = payload or {}
                t_clean = (payload.get("table_name") or item_key.split(".")[-1]).lower().strip()
                if "." in t_clean:
                    t_clean = t_clean.split(".")[-1]
                if not t_clean:
                    continue

                kind = (
                    payload.get("kind")
                    or (payload.get("semantic") or {}).get("kind")
                    or "entity"
                ).lower().strip()

                # Requirement 6: confirm every table item has stats.row_count from exact bounded count.
                # If any table lacks it, do not fall back to row_estimate; treat as unknown (no penalty / is_empty=False).
                stats = payload.get("stats") or {}
                exact_row_cnt = stats.get("row_count")
                if exact_row_cnt is not None:
                    is_empty = int(exact_row_cnt) == 0
                else:
                    is_empty = False
                    logger.debug(
                        f"[TableRetriever] Table '{t_clean}' lacks stats.row_count; treating as unknown (is_empty=False)"
                    )

                aliases: Set[str] = set()
                raw_aliases = (
                    (payload.get("aliases") or [])
                    + ((payload.get("semantic") or {}).get("synonyms") or [])
                    + ((payload.get("semantic") or {}).get("aliases") or [])
                )
                for a in raw_aliases:
                    if a and isinstance(a, str):
                        clean_a = a.lower().strip()
                        if clean_a and clean_a != t_clean:
                            aliases.add(clean_a)

                parts = split_identifier(t_clean)
                table_meta[t_clean] = TableMetadata(
                    table_name=t_clean,
                    kind=kind,
                    is_empty=is_empty,
                    aliases=aliases,
                    parts=parts,
                )
        except Exception as e:
            logger.debug(f"[TableRetriever] Failed to load table items for metadata: {e}")

        # 2. Fetch from kb2_schema_docs (doc_type='table') to supplement
        try:
            stmt_docs = select(
                KB2SchemaDoc.item_key, KB2SchemaDoc.title, KB2SchemaDoc.aliases, KB2SchemaDoc.body
            ).where(
                KB2SchemaDoc.tenant_id == self.tenant_id,
                KB2SchemaDoc.db_knowledgebase_id == db_knowledgebase_id,
                KB2SchemaDoc.doc_type == "table",
                KB2SchemaDoc.status.in_(["confirmed", "draft"]),
            )
            res_docs = await self.db.execute(stmt_docs)
            for item_key, title, doc_aliases, doc_body in res_docs.all():
                c_tbl = item_key.split(".")[-1].lower().strip()
                if c_tbl not in table_meta:
                    kind = "entity"
                    if doc_body and "Kind: " in doc_body:
                        k_match = re.search(r"Kind:\s*([a-zA-Z_]+)", doc_body)
                        if k_match:
                            kind = k_match.group(1).lower().strip()
                    is_empty = False
                    if doc_body and ("Empty database table" in doc_body or "Approx Rows: 0" in doc_body):
                        is_empty = True
                    table_meta[c_tbl] = TableMetadata(
                        table_name=c_tbl,
                        kind=kind,
                        is_empty=is_empty,
                        aliases=set(),
                        parts=split_identifier(c_tbl),
                    )

                meta = table_meta[c_tbl]
                if doc_aliases:
                    for a in doc_aliases:
                        if a and a.lower().strip() != c_tbl:
                            meta.aliases.add(a.lower().strip())
                if title:
                    t_title = re.sub(r"^table\s+", "", title, flags=re.IGNORECASE).lower().strip()
                    if t_title and t_title != c_tbl:
                        meta.aliases.add(t_title)
        except Exception as e:
            logger.debug(f"[TableRetriever] Failed to load schema docs for metadata: {e}")

        # 3. Fetch from k2b_table_aliases (user-defined UI aliases)
        try:
            stmt_alias = select(KBTableAlias.table_name, KBTableAlias.aliases).where(
                KBTableAlias.db_knowledgebase_id == db_knowledgebase_id,
            )
            if self.tenant_id:
                stmt_alias = stmt_alias.where(KBTableAlias.tenant_id == self.tenant_id)
            res_alias = await self.db.execute(stmt_alias)
            for tbl_name, aliases in res_alias.all():
                c_tbl = tbl_name.split(".")[-1].lower().strip()
                if c_tbl in table_meta and aliases:
                    for a in aliases:
                        if a and a.lower().strip() != c_tbl:
                            table_meta[c_tbl].aliases.add(a.lower().strip())
        except Exception as e:
            logger.debug(f"[TableRetriever] Failed to load k2b_table_aliases: {e}")

        # 4. Fallback from DatabaseSchemaSnapshot
        try:
            stmt_snap = select(DatabaseSchemaSnapshot.schema_data).where(
                DatabaseSchemaSnapshot.tenant_id == self.tenant_id,
                DatabaseSchemaSnapshot.db_knowledgebase_id == db_knowledgebase_id,
            ).order_by(desc(DatabaseSchemaSnapshot.created_at)).limit(1)
            res_snap = await self.db.execute(stmt_snap)
            snap_data = res_snap.scalar_one_or_none()
            if snap_data and isinstance(snap_data, dict):
                def _register_snap_table(tbl_k: str):
                    clean = tbl_k.split(".")[-1].lower().strip()
                    if clean and clean not in table_meta:
                        table_meta[clean] = TableMetadata(
                            table_name=clean,
                            kind="entity",
                            is_empty=False,
                            aliases=set(),
                            parts=split_identifier(clean),
                        )
                if "schemas" in snap_data and isinstance(snap_data["schemas"], dict):
                    for s_v in snap_data["schemas"].values():
                        if isinstance(s_v, dict) and "tables" in s_v and isinstance(s_v["tables"], dict):
                            for t_k, t_val in s_v["tables"].items():
                                _register_snap_table(t_val.get("table_name", t_k) if isinstance(t_val, dict) else t_k)
                if "tables" in snap_data and isinstance(snap_data["tables"], dict):
                    for t_k, t_val in snap_data["tables"].items():
                        _register_snap_table(t_val.get("table_name", t_k) if isinstance(t_val, dict) else t_k)
        except Exception as e:
            logger.debug(f"[TableRetriever] Failed to load snapshot for metadata: {e}")

        # 5. Precompute ambiguous synonyms across all tables (STEP 1)
        # "A synonym that appears on more than one table (e.g. 'task' on both work_packages and projects) must not receive a boost on any of them."
        synonym_to_tables: Dict[str, Set[str]] = {}
        for t_name, meta in table_meta.items():
            for alias in meta.aliases:
                alias_clean = alias.lower().strip()
                if not alias_clean:
                    continue
                for v in get_singular_plural_variants(alias_clean, exception_words=self.config.non_stripping_s_words):
                    synonym_to_tables.setdefault(v, set()).add(t_name)

        ambiguous_synonyms = {syn for syn, tables in synonym_to_tables.items() if len(tables) > 1}

        _PROCESS_TABLE_METADATA_CACHE[cache_key] = (time.monotonic(), table_meta, ambiguous_synonyms)
        return table_meta, ambiguous_synonyms

    async def retrieve_tables(
        self,
        db_knowledgebase_id: uuid.UUID,
        frame: QuestionFrame,
        top_k: int = 12,
        domain_filter: Optional[str] = None,
        query_embedding: Optional[List[float]] = None,
        return_gap_signal: bool = False,
    ) -> Union[TableRankingResult, Tuple[TableRankingResult, Dict[str, Any]]]:
        """Rank tables for the parsed QuestionFrame with graded token boosts and kind/emptiness multipliers."""
        clean_text = frame.normalized_text or frame.original_question
        table_scores: Dict[str, float] = {}
        table_reasons: Dict[str, List[str]] = {}
        table_signals: Dict[str, Dict[str, float]] = {}

        # Column evidence tracking (PART B.1) & Vector rank tracking (PART B.2)
        table_column_scores: Dict[str, Dict[str, float]] = {}
        table_column_types: Dict[str, Set[str]] = {}
        table_vector_ranks: Dict[str, int] = {}

        # Load metadata and ambiguity index
        table_meta, ambiguous_synonyms = await self._get_kb_table_metadata(db_knowledgebase_id=db_knowledgebase_id)

        def _add_score(table: str, score_delta: float, reason: str, signal_name: str):
            t_norm = table.lower().strip()
            if "." in t_norm:
                t_norm = t_norm.split(".")[-1]
            if not t_norm:
                return
            # Candidate Validation (Requirement 1): drop any candidate not in table_meta and log at debug level
            if t_norm not in table_meta:
                logger.debug(
                    f"[TableRetriever] Dropped non-table candidate during scoring: '{t_norm}' (signal: {signal_name})"
                )
                return
            table_scores[t_norm] = table_scores.get(t_norm, 0.0) + score_delta
            table_reasons.setdefault(t_norm, []).append(reason)
            table_signals.setdefault(t_norm, {})[signal_name] = score_delta

        # -------------------------------------------------------------
        # 1. Full-Text Search (Table, Column, Metric, Glossary docs)
        # -------------------------------------------------------------
        t_fts_start = time.perf_counter()
        fts_weight = self.weights.get("fts", 1.0)
        fts_hits = await self.schema_doc_repo.search_fts(
            db_knowledgebase_id=db_knowledgebase_id,
            query=clean_text,
            limit=30,
        )
        for rank, hit in enumerate(fts_hits, start=1):
            rrf_score = fts_weight * (1.0 / (RRF_K + rank))
            dt = hit["doc_type"]
            key = hit["item_key"]

            if dt == "table":
                t_name = key.split(".")[-1]
                _add_score(t_name, rrf_score, f"FTS match on table doc (rank {rank})", "fts")
            elif dt == "column":
                t_name = key.split(".")[1] if key.count(".") >= 2 else key.split(".")[0]
                t_clean = t_name.lower().strip()
                if t_clean in table_meta:
                    col_score = rrf_score * 0.9
                    prev = table_column_scores.setdefault(t_clean, {}).get(key, 0.0)
                    table_column_scores[t_clean][key] = max(prev, col_score)
                    table_column_types.setdefault(t_clean, set()).add("fts_column")
            elif dt == "glossary":
                # STEP 3: Glossary items of category domain must never contribute to table scoring
                item_key = hit.get("item_key", "")
                role = (hit.get("role") or "").lower()
                unit = (hit.get("unit") or "").lower()
                body = hit.get("body", "")
                title = (hit.get("title") or "").lower()

                if (
                    item_key.startswith("domain:")
                    or role == "domain"
                    or unit == "domain"
                    or "category: domain" in body.lower()
                    or "target (domain):" in body.lower()
                    or "domain:" in title
                ):
                    continue

                if "Target (table):" in body:
                    m = re.search(r"Target\s*\((?:table|schema\.table)\):\s*([a-zA-Z0-9_\.]+)", body, re.IGNORECASE)
                    if m:
                        raw_target = m.group(1).strip().rstrip(".")
                        t_target = raw_target.split(".")[-1].lower().strip()
                        if t_target and t_target in table_meta:
                            target_meta = table_meta[t_target]
                            target_kind = target_meta.kind.lower()
                            # Glossary hits must not boost link, journal or system tables beyond what their kind multiplier allows
                            kind_bound = self.config.kind_multipliers.get(target_kind, 1.0)
                            effective_glossary_score = rrf_score * self.weights.get("glossary", 1.2) * (kind_bound if kind_bound < 1.0 else 1.0)
                            _add_score(t_target, effective_glossary_score, f"Glossary term {hit['title']} -> {t_target}", "glossary")
            elif dt == "metric":
                # Requirement 1: Only resolve real tables from target or table_meta, never raw question tokens
                body = hit.get("body", "")
                metric_tables: Set[str] = set()
                if "Target (table):" in body:
                    m = re.search(r"Target\s*\((?:table|schema\.table)\):\s*([a-zA-Z0-9_\.]+)", body, re.IGNORECASE)
                    if m:
                        raw_target = m.group(1).strip().rstrip(".")
                        mt = raw_target.split(".")[-1].lower().strip()
                        if mt in table_meta:
                            metric_tables.add(mt)
                for t_candidate in table_meta.keys():
                    if t_candidate in key or t_candidate in body:
                        metric_tables.add(t_candidate)
                for mt in metric_tables:
                    _add_score(mt, rrf_score * self.weights.get("metric", 1.1), f"Metric hit {hit['title']} -> {mt}", "metric")
        t_fts_ms = (time.perf_counter() - t_fts_start) * 1000.0

        # -------------------------------------------------------------
        # 2. Vector Search (Semantic Cosine Similarity)
        # -------------------------------------------------------------
        t_vec_start = time.perf_counter()
        vec_weight = self.weights.get("vector", 1.0)
        try:
            q_emb = query_embedding
            if q_emb is None:
                q_emb = await EmbeddingGenerator.generate_embedding(frame.original_question, is_query=True)
            if q_emb:
                vec_hits = await self.schema_doc_repo.search_vector(
                    db_knowledgebase_id=db_knowledgebase_id,
                    embedding=q_emb,
                    limit=30,
                )
                for rank, hit in enumerate(vec_hits, start=1):
                    rrf_score = vec_weight * (1.0 / (RRF_K + rank))
                    dt = hit["doc_type"]
                    key = hit["item_key"]

                    if dt == "table":
                        t_name = key.split(".")[-1]
                        t_clean = t_name.lower().strip()
                        if t_clean not in table_vector_ranks:
                            table_vector_ranks[t_clean] = rank
                        _add_score(t_clean, rrf_score, f"Vector match on table {t_name} (sim {hit['score']:.2f}, rank {rank})", "vector")
                    elif dt == "column":
                        t_name = key.split(".")[1] if key.count(".") >= 2 else key.split(".")[0]
                        t_clean = t_name.lower().strip()
                        if t_clean in table_meta:
                            col_score = rrf_score * 0.85
                            prev = table_column_scores.setdefault(t_clean, {}).get(key, 0.0)
                            table_column_scores[t_clean][key] = max(prev, col_score)
                            table_column_types.setdefault(t_clean, set()).add("vector_column")
                    elif dt == "glossary":
                        # STEP 3: Vector glossary hits with domain check and kind damping
                        item_key = hit.get("item_key", "")
                        role = (hit.get("role") or "").lower()
                        unit = (hit.get("unit") or "").lower()
                        body = hit.get("body", "")
                        title = (hit.get("title") or "").lower()

                        if (
                            item_key.startswith("domain:")
                            or role == "domain"
                            or unit == "domain"
                            or "category: domain" in body.lower()
                            or "target (domain):" in body.lower()
                            or "domain:" in title
                        ):
                            continue

                        if "Target (table):" in body:
                            m = re.search(r"Target\s*\((?:table|schema\.table)\):\s*([a-zA-Z0-9_\.]+)", body, re.IGNORECASE)
                            if m:
                                raw_target = m.group(1).strip().rstrip(".")
                                t_target = raw_target.split(".")[-1].lower().strip()
                                if t_target and t_target in table_meta:
                                    target_meta = table_meta[t_target]
                                    target_kind = target_meta.kind.lower()
                                    kind_bound = self.config.kind_multipliers.get(target_kind, 1.0)
                                    effective_glossary_score = rrf_score * self.weights.get("glossary", 1.2) * (kind_bound if kind_bound < 1.0 else 1.0)
                                    _add_score(t_target, effective_glossary_score, f"Vector glossary match {hit['title']} -> {t_target}", "glossary_vector")
                    elif dt == "metric":
                        body = hit.get("body", "")
                        metric_tables: Set[str] = set()
                        if "Target (table):" in body:
                            m = re.search(r"Target\s*\((?:table|schema\.table)\):\s*([a-zA-Z0-9_\.]+)", body, re.IGNORECASE)
                            if m:
                                raw_target = m.group(1).strip().rstrip(".")
                                mt = raw_target.split(".")[-1].lower().strip()
                                if mt in table_meta:
                                    metric_tables.add(mt)
                        for t_candidate in table_meta.keys():
                            if t_candidate in key or t_candidate in body:
                                metric_tables.add(t_candidate)
                        for mt in metric_tables:
                            _add_score(mt, rrf_score * self.weights.get("metric", 1.1), f"Vector metric hit {hit['title']} -> {mt}", "metric")
        except Exception as e:
            logger.debug(f"[TableRetriever] Vector search fallback: {e}")
        t_vec_ms = (time.perf_counter() - t_vec_start) * 1000.0

        # -------------------------------------------------------------
        # 2b. Aggregate Column Evidence per Table (PART B.1)
        # Column evidence must not be summed across columns.
        # Per table, use max over its column signals plus small bonus for 2nd best.
        # -------------------------------------------------------------
        for t_clean, col_map in table_column_scores.items():
            sorted_col_scores = sorted(col_map.values(), reverse=True)
            best_col = sorted_col_scores[0]
            second_col = sorted_col_scores[1] if len(sorted_col_scores) > 1 else 0.0
            bonus = self.config.second_column_bonus_multiplier * second_col
            total_col_ev = best_col + bonus

            for c_type in table_column_types.get(t_clean, set()):
                table_signals.setdefault(t_clean, {})[c_type] = best_col

            _add_score(
                t_clean,
                total_col_ev,
                f"Column evidence (max={best_col:.4f}" + (f", 2nd_bonus={bonus:.4f}" if bonus > 0 else "") + ")",
                "column_aggregate",
            )

        # -------------------------------------------------------------
        # 3. Value-Index Search (for entity candidates, excluding literals)
        # -------------------------------------------------------------
        val_weight = self.weights.get("value_index", 1.3)
        entity_spans = set(frame.entity_candidates or [])
        _LOCAL_STOPWORDS = {
            "the", "a", "an", "in", "on", "at", "to", "for", "of", "with", "by", "from",
            "is", "are", "was", "were", "and", "or", "what", "which", "who", "whom",
            "where", "when", "why", "how", "all", "each", "every", "both", "few",
            "many", "much", "more", "most", "did", "does", "do", "can", "tell", "show",
            "list", "worked", "work", "log", "logged", "hours", "hour", "yesterday", "today",
        }
        for tok in frame.tokens:
            if len(tok) >= 3 and tok.lower() not in _LOCAL_STOPWORDS:
                entity_spans.add(tok)

        for span in entity_spans:
            if span in frame.literal_values:
                continue
            try:
                val_matches = await self.entity_repo.search_fuzzy(
                    db_knowledgebase_id=db_knowledgebase_id,
                    query_text=span,
                    limit=5,
                    min_similarity=0.3,
                )
                for rank, vm in enumerate(val_matches, start=1):
                    t_val = vm["table_name"].split(".")[-1]
                    sim = vm.get("similarity", 1.0)
                    score_delta = val_weight * sim * (1.0 / (RRF_K + rank))
                    _add_score(t_val, score_delta, f"Value match '{span}' in {vm['table_name']}.{vm['column_name']} (sim {sim:.2f})", "value_index")
            except Exception as e:
                logger.debug(f"[TableRetriever] Value lookup error: {e}")

        # -------------------------------------------------------------
        # 4. Graded Token & Synonym Table Match Boost (STEP 1)
        # -------------------------------------------------------------
        q_raw_lower = f" {frame.original_question.lower()} "
        q_norm_lower = f" {frame.normalized_text.lower()} "
        question_token_variants = {
            v for tok in frame.tokens
            for v in get_singular_plural_variants(tok, exception_words=self.config.non_stripping_s_words)
        }

        for t_name, meta in table_meta.items():
            t_variants = get_singular_plural_variants(t_name, exception_words=self.config.non_stripping_s_words)
            is_full = False
            full_match_reason = ""

            # Check 1: Single-word table name exact match (singular/plural normalised)
            matched_single = t_variants & question_token_variants
            if matched_single and len(meta.parts) <= 1:
                is_full = True
                full_match_reason = f"Full table-name match '{t_name}' ({list(matched_single)[0]})"

            # Check 2: Compound table name full match
            if not is_full and len(meta.parts) > 1:
                phrase = " ".join(meta.parts)
                phrase_variants = {phrase}
                for lv in get_singular_plural_variants(meta.parts[-1], exception_words=self.config.non_stripping_s_words):
                    phrase_variants.add(" ".join(meta.parts[:-1] + [lv]))

                for pv in phrase_variants:
                    pattern = r"\b" + re.escape(pv) + r"\b"
                    if re.search(pattern, q_raw_lower) or re.search(pattern, q_norm_lower):
                        is_full = True
                        full_match_reason = f"Full compound table-name match '{pv}'"
                        break

                if not is_full:
                    # Check if ALL parts are present in question tokens
                    matched_parts_count = sum(
                        1 for p in meta.parts
                        if get_singular_plural_variants(p, exception_words=self.config.non_stripping_s_words) & question_token_variants
                    )
                    if matched_parts_count == len(meta.parts):
                        is_full = True
                        full_match_reason = f"All compound parts present for '{t_name}'"

            if is_full:
                _add_score(t_name, self.config.boost_exact_table, full_match_reason, "token_exact")
                continue

            # Check 3: Match against a stored unique synonym/alias (strong)
            matched_unique_syn = None
            for alias in meta.aliases:
                alias_clean = alias.lower().strip()
                if not alias_clean:
                    continue
                alias_vars = get_singular_plural_variants(alias_clean, exception_words=self.config.non_stripping_s_words)
                # Disqualify if ambiguous (appears on more than one table)
                if any(v in ambiguous_synonyms for v in alias_vars):
                    continue

                if " " not in alias_clean:
                    if alias_vars & question_token_variants:
                        matched_unique_syn = alias_clean
                        break
                else:
                    for av in alias_vars:
                        pattern = r"\b" + re.escape(av) + r"\b"
                        if re.search(pattern, q_raw_lower) or re.search(pattern, q_norm_lower):
                            matched_unique_syn = av
                            break
                    if matched_unique_syn:
                        break

            if matched_unique_syn:
                _add_score(
                    t_name,
                    self.config.boost_synonym,
                    f"Unique synonym/alias match '{matched_unique_syn}'",
                    "token_synonym",
                )
                continue

            # Check 4: Token matches only ONE part of a compound name (underscore-split) = weak
            # Substring-inside-a-word = none.
            if len(meta.parts) > 1:
                matched_compound_parts = [
                    p for p in meta.parts
                    if get_singular_plural_variants(p, exception_words=self.config.non_stripping_s_words) & question_token_variants
                ]
                if matched_compound_parts:
                    _add_score(
                        t_name,
                        self.config.boost_compound_part,
                        f"Compound table part match on '{matched_compound_parts[0]}'",
                        "token_part",
                    )

        # -------------------------------------------------------------
        # 5. Apply Kind, Emptiness, Column-Only, and Link Multipliers (STEP 2 & Requirements 2, 3)
        # -------------------------------------------------------------
        q_lower = frame.original_question.lower()
        final_table_scores: Dict[str, float] = {}

        TABLE_LEVEL_SIGNALS = {
            "fts", "vector", "token_exact", "token_synonym",
            "token_part", "glossary", "glossary_vector", "metric", "value_index",
        }

        for t_name, base_score in table_scores.items():
            meta = table_meta.get(t_name, TableMetadata(table_name=t_name, parts=split_identifier(t_name)))
            t_kind = meta.kind.lower()

            # Base kind multiplier from config
            kind_mult = self.config.kind_multipliers.get(t_kind, self.config.default_kind_multiplier)

            # Journal multiplier returns to 1.0 only when question contains history words
            if t_kind == "journal":
                if any(hw in q_lower for hw in self.config.history_words):
                    kind_mult = 1.0
                    table_reasons.setdefault(t_name, []).append("Journal multiplier restored to 1.0 due to history cues")

            # Link multiplier (Requirement 3): restore to 1.0 only if:
            # (a) its own name or both parent names appear in the question, or
            # (b) an association word appears AND at least one parent part of that link table matches a question token.
            # A bare association word alone must not restore any link table.
            if t_kind == "link":
                has_assoc_word = any(
                    re.search(r"\b" + re.escape(aw) + r"\b", q_lower)
                    for aw in self.config.association_words
                )
                matched_parents_count = 0
                if len(meta.parts) >= 2:
                    matched_parents_count = sum(
                        1 for p in meta.parts
                        if get_singular_plural_variants(p, exception_words=self.config.non_stripping_s_words) & question_token_variants
                    )
                has_both_parents = matched_parents_count >= 2

                is_explicitly_named = bool(
                    (get_singular_plural_variants(t_name, exception_words=self.config.non_stripping_s_words) & question_token_variants)
                    or (
                        len(meta.parts) > 1
                        and any(
                            re.search(r"\b" + re.escape(pv) + r"\b", q_raw_lower)
                            for pv in {" ".join(meta.parts), " ".join(meta.parts[:-1] + [meta.parts[-1].rstrip("s")])}
                        )
                    )
                )

                restore_link = (is_explicitly_named or has_both_parents) or (has_assoc_word and matched_parents_count >= 1)
                if restore_link:
                    kind_mult = 1.0
                    table_reasons.setdefault(t_name, []).append("Link multiplier restored to 1.0 due to association cues")

            # Emptiness multiplier
            empty_mult = 1.0
            if meta.is_empty:
                # Unless question tokens match table name exactly
                is_exact_empty_match = bool(
                    (get_singular_plural_variants(t_name, exception_words=self.config.non_stripping_s_words) & question_token_variants)
                    or (
                        len(meta.parts) > 1
                        and any(
                            re.search(r"\b" + re.escape(pv) + r"\b", q_raw_lower)
                            for pv in {" ".join(meta.parts), " ".join(meta.parts[:-1] + [meta.parts[-1].rstrip("s")])}
                        )
                    )
                )
                if not is_exact_empty_match:
                    empty_mult = self.config.empty_table_multiplier
                    table_reasons.setdefault(t_name, []).append(f"Emptiness multiplier applied (x{self.config.empty_table_multiplier})")

            # Column-only damping (PART B.2):
            # A table has table-level evidence only if:
            # - table-doc FTS hit ("fts"), OR
            # - table-vector RANK in top 3 (rank <= config.table_vector_top_rank), OR
            # - exact/synonym match ("token_exact", "token_synonym"), OR
            # - glossary hit ("glossary", "glossary_vector"), OR
            # - value_index hit ("value_index").
            # Tables without it get the column-only multiplier (default 0.5).
            signals_present = set(table_signals.get(t_name, {}).keys())
            has_table_level = (
                "fts" in signals_present
                or ("vector" in signals_present and table_vector_ranks.get(t_name, 999) <= self.config.table_vector_top_rank)
                or "token_exact" in signals_present
                or "token_synonym" in signals_present
                or "glossary" in signals_present
                or "glossary_vector" in signals_present
                or "value_index" in signals_present
            )

            col_mult = 1.0
            if signals_present and not has_table_level:
                col_mult = self.config.column_only_multiplier
                table_reasons.setdefault(t_name, []).append(
                    f"Column-only damping applied (x{self.config.column_only_multiplier}) - no table-level evidence"
                )
                table_signals.setdefault(t_name, {})["column_damping"] = col_mult

            total_mult = kind_mult * empty_mult * col_mult
            final_table_scores[t_name] = base_score * total_mult
            table_signals.setdefault(t_name, {})["multiplier"] = total_mult

        # -------------------------------------------------------------
        # 6. Rank Candidates & Compute Gap Signals (STEP 4)
        # -------------------------------------------------------------
        candidates: List[TableCandidate] = []
        for t_name, total_sc in sorted(final_table_scores.items(), key=lambda x: x[1], reverse=True):
            # Candidate Validation (Requirement 1): drop any candidate not in table_meta as final safety net
            if t_name not in table_meta:
                logger.debug(f"[TableRetriever] Dropped non-table candidate from final results: '{t_name}'")
                continue
            candidates.append(TableCandidate(
                table_name=t_name,
                score=total_sc,
                reasons=table_reasons.get(t_name, []),
                signals=table_signals.get(t_name, {}),
            ))

        top1_score = candidates[0].score if candidates else 0.0
        margin = (candidates[0].score - candidates[1].score) if len(candidates) >= 2 else (top1_score if candidates else 0.0)
        top3_signals = [{"table": c.table_name, "signals": list(c.signals.keys())} for c in candidates[:3]]

        stage_timings = {
            "table_fts_ms": round(t_fts_ms, 2),
            "table_vector_ms": round(t_vec_ms, 2),
        }

        ranked_result = TableRankingResult(
            candidates=candidates[:top_k],
            top1_score=top1_score,
            margin=margin,
            top3_signals=top3_signals,
            stage_timings=stage_timings,
        )
        self.last_ranking_result = ranked_result

        if return_gap_signal:
            return ranked_result, {
                "top1_score": top1_score,
                "margin": margin,
                "top3_signals": top3_signals,
            }

        return ranked_result
