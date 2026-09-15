"""Schema-Grounded Entity Resolver

Resolves candidate query tokens and bigrams against actual schema elements
(tables and columns) using embedding-primary semantic matching and RapidFuzz
tiebreaking, with explicit score normalization and confidence tiers.
"""

from enum import Enum
import math
from typing import Any, Dict, List, Literal, Optional, Set, Tuple
from pydantic import BaseModel, ConfigDict, Field
try:
    from rapidfuzz import fuzz
except ImportError:
    import difflib

    class _FuzzFallback:
        @staticmethod
        def token_sort_ratio(s1: str, s2: str) -> float:
            w1 = " ".join(sorted(s1.split()))
            w2 = " ".join(sorted(s2.split()))
            return difflib.SequenceMatcher(None, w1, w2).ratio() * 100.0

        @staticmethod
        def partial_ratio(s1: str, s2: str) -> float:
            if not s1 or not s2:
                return 0.0
            if len(s1) > len(s2):
                s1, s2 = s2, s1
            return max((difflib.SequenceMatcher(None, s1, s2[i:i+len(s1)]).ratio() for i in range(len(s2) - len(s1) + 1)), default=0.0) * 100.0

    fuzz = _FuzzFallback()

from ..schemas.canonical import DatabaseSchema, TableSchema
from .pos_extractor import Candidate


class EntityConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNRESOLVED = "UNRESOLVED"


class ResolvedEntity(BaseModel):
    """Result of resolving a query candidate token against schema elements."""
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., description="Query token or bigram text")
    resolved_to: Optional[str] = Field(default=None, description="Fully-qualified table or column name")
    entity_type: Literal["TABLE", "COLUMN"] = Field(default="TABLE")
    confidence: EntityConfidence = Field(default=EntityConfidence.UNRESOLVED)
    embedding_score: float = Field(default=0.0, ge=0.0, le=1.0)
    fuzzy_score: float = Field(default=0.0, ge=0.0, le=1.0)
    combined_score: float = Field(default=0.0, ge=0.0, le=1.0)
    resolution_scope: Literal["candidate_tables", "full_schema"] = Field(default="candidate_tables")
    metadata: Dict[str, Any] = Field(default_factory=dict)


_PROCESS_TOKEN_CACHE: Dict[str, List[float]] = {}
_PROCESS_TARGET_CACHE: Dict[str, List[float]] = {}


class SchemaEntityResolver:
    """
    Production-grade Schema-Grounded Entity Resolver.
    Uses embedding similarity as the primary signal (e.g. 'earning' -> 'basic_salary')
    and RapidFuzz as a secondary tiebreaker/booster.
    """

    @staticmethod
    def cosine_similarity(v1: List[float], v2: List[float]) -> float:
        """Compute cosine similarity between two float vectors."""
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        if norm1 <= 1e-9 or norm2 <= 1e-9:
            return 0.0
        return dot / (norm1 * norm2)

    @classmethod
    def compute_combined_score(
        cls,
        embedding_cosine: float,
        fuzzy_ratio: float,
        embedding_weight: float = 0.75,
        fuzzy_weight: float = 0.25,
    ) -> Tuple[float, float, float]:
        """
        Compute normalized scores and weighted combination.

        Clipped to [0.0, 1.0]: Domain text embeddings for relevant concepts are non-negative;
        negative cosine distance indicates semantic divergence and is floored at 0.0.
        """
        normalized_emb = max(0.0, min(1.0, embedding_cosine))
        normalized_fuzz = max(0.0, min(1.0, fuzzy_ratio / 100.0))
        combined = (embedding_weight * normalized_emb) + (fuzzy_weight * normalized_fuzz)
        return normalized_emb, normalized_fuzz, round(combined, 4)

    @classmethod
    async def resolve_candidates(
        cls,
        candidates: List[Candidate],
        canonical_schema: DatabaseSchema,
        candidate_tables: Optional[List[TableSchema]] = None,
        embedding_weight: Optional[float] = None,
        fuzzy_weight: Optional[float] = None,
        high_threshold: Optional[float] = None,
        medium_threshold: Optional[float] = None,
        low_threshold: Optional[float] = None,
        token_embeddings: Optional[Dict[str, List[float]]] = None,
        target_embeddings: Optional[Dict[str, List[float]]] = None,
    ) -> List[ResolvedEntity]:
        """
        Resolve candidate tokens against schema elements.
        First searches within candidate_tables; falls back to full schema if score < low_threshold.
        """
        if embedding_weight is None or fuzzy_weight is None or high_threshold is None or medium_threshold is None or low_threshold is None:
            try:
                from app.core.config import get_settings
                s = get_settings()
                embedding_weight = embedding_weight if embedding_weight is not None else s.entity_resolution_embedding_weight
                fuzzy_weight = fuzzy_weight if fuzzy_weight is not None else s.entity_resolution_fuzzy_weight
                high_threshold = high_threshold if high_threshold is not None else s.entity_resolution_high_threshold
                medium_threshold = medium_threshold if medium_threshold is not None else s.entity_resolution_medium_threshold
                low_threshold = low_threshold if low_threshold is not None else s.entity_resolution_low_threshold
            except Exception:
                embedding_weight = embedding_weight if embedding_weight is not None else 0.75
                fuzzy_weight = fuzzy_weight if fuzzy_weight is not None else 0.25
                high_threshold = high_threshold if high_threshold is not None else 0.75
                medium_threshold = medium_threshold if medium_threshold is not None else 0.50
                low_threshold = low_threshold if low_threshold is not None else 0.30

        resolved_results: List[ResolvedEntity] = []
        token_emb_cache: Dict[str, List[float]] = token_embeddings if token_embeddings is not None else _PROCESS_TOKEN_CACHE
        target_emb_cache: Dict[str, List[float]] = target_embeddings if target_embeddings is not None else _PROCESS_TARGET_CACHE

        # Prepare candidate table scope
        in_scope_tables = candidate_tables if candidate_tables else []
        all_tables: List[TableSchema] = []
        for s_info in canonical_schema.schemas.values():
            all_tables.extend(s_info.tables.values())

        from ..semantic_glossary.canonicality import is_canonical_table
        canonical_tables = [t for t in all_tables if is_canonical_table(t)]
        search_tables = canonical_tables if canonical_tables else all_tables

        # Batch pre-fetch missing embeddings in one shot
        missing_texts: List[str] = []
        text_to_cache_keys: Dict[str, List[Tuple[str, str]]] = {}

        for cand in candidates:
            c_text = cand.text.lower().strip()
            if c_text and c_text not in token_emb_cache:
                if c_text not in text_to_cache_keys:
                    missing_texts.append(c_text)
                    text_to_cache_keys[c_text] = []
                text_to_cache_keys[c_text].append(("token", c_text))

        tables_to_embed = in_scope_tables if in_scope_tables else search_tables
        for tbl in tables_to_embed:
            t_clean = tbl.table_name.lower().replace("_", " ")
            t_key = f"table:{tbl.table_name}"
            if t_key not in target_emb_cache:
                if t_clean not in text_to_cache_keys:
                    missing_texts.append(t_clean)
                    text_to_cache_keys[t_clean] = []
                text_to_cache_keys[t_clean].append(("target", t_key))

        if missing_texts:
            try:
                from app.core.embeddings import EmbeddingGenerator
                vectors = await asyncio.wait_for(
                    EmbeddingGenerator.generate_embeddings_batch(missing_texts),
                    timeout=0.8,
                )
                for txt, vec in zip(missing_texts, vectors):
                    for c_type, key in text_to_cache_keys[txt]:
                        if c_type == "token":
                            token_emb_cache[key] = vec
                        else:
                            target_emb_cache[key] = vec
            except Exception:
                pass

        for cand in candidates:
            # Step 1: Search within candidate tables
            best_res = await cls._score_candidate_against_tables(
                cand=cand,
                tables=in_scope_tables if in_scope_tables else search_tables,
                scope="candidate_tables" if in_scope_tables else "full_schema",
                embedding_weight=embedding_weight,
                fuzzy_weight=fuzzy_weight,
                high_threshold=high_threshold,
                medium_threshold=medium_threshold,
                low_threshold=low_threshold,
                token_emb_cache=token_emb_cache,
                target_emb_cache=target_emb_cache,
            )

            # Step 2: Fall back to full schema if candidate-table scope produced UNRESOLVED
            if in_scope_tables and best_res.confidence == EntityConfidence.UNRESOLVED:
                fallback_res = await cls._score_candidate_against_tables(
                    cand=cand,
                    tables=search_tables,
                    scope="full_schema",
                    embedding_weight=embedding_weight,
                    fuzzy_weight=fuzzy_weight,
                    high_threshold=high_threshold,
                    medium_threshold=medium_threshold,
                    low_threshold=low_threshold,
                    token_emb_cache=token_emb_cache,
                    target_emb_cache=target_emb_cache,
                )
                if fallback_res.confidence != EntityConfidence.UNRESOLVED:
                    best_res = fallback_res

            # Step 3: Safety Valve for likely verbs
            # A candidate with likely_verb=True must clear HIGH threshold (>= 0.75) to resolve as an entity
            if cand.likely_verb and best_res.confidence != EntityConfidence.HIGH:
                best_res.confidence = EntityConfidence.UNRESOLVED
                best_res.metadata["verb_safety_downgraded"] = True

            resolved_results.append(best_res)

        return resolved_results

    @classmethod
    def resolve_candidates_sync(
        cls,
        candidates: List[Candidate],
        canonical_schema: DatabaseSchema,
        candidate_tables: Optional[List[TableSchema]] = None,
        embedding_weight: Optional[float] = None,
        fuzzy_weight: Optional[float] = None,
        high_threshold: Optional[float] = None,
        medium_threshold: Optional[float] = None,
        low_threshold: Optional[float] = None,
        token_embeddings: Optional[Dict[str, List[float]]] = None,
        target_embeddings: Optional[Dict[str, List[float]]] = None,
    ) -> List[ResolvedEntity]:
        """Synchronous wrapper for resolve_candidates."""
        import asyncio
        import concurrent.futures

        def _runner():
            return asyncio.run(
                cls.resolve_candidates(
                    candidates=candidates,
                    canonical_schema=canonical_schema,
                    candidate_tables=candidate_tables,
                    embedding_weight=embedding_weight,
                    fuzzy_weight=fuzzy_weight,
                    high_threshold=high_threshold,
                    medium_threshold=medium_threshold,
                    low_threshold=low_threshold,
                    token_embeddings=token_embeddings,
                    target_embeddings=target_embeddings,
                )
            )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is None:
            return _runner()
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(_runner).result()

    @classmethod
    async def _score_candidate_against_tables(
        cls,
        cand: Candidate,
        tables: List[TableSchema],
        scope: Literal["candidate_tables", "full_schema"],
        embedding_weight: float,
        fuzzy_weight: float,
        high_threshold: float,
        medium_threshold: float,
        low_threshold: float,
        token_emb_cache: Dict[str, List[float]],
        target_emb_cache: Dict[str, List[float]],
    ) -> ResolvedEntity:
        """Score candidate against a collection of tables and their columns."""
        token_text = cand.text.lower().strip()
        # Accurate English singularization
        token_stem = token_text
        if token_stem.endswith("ees"):
            token_stem = token_stem[:-1]
        elif token_stem.endswith("ies") and len(token_stem) > 4:
            token_stem = token_stem[:-3] + "y"
        elif (token_stem.endswith("xes") or token_stem.endswith("shes") or token_stem.endswith("ches") or token_stem.endswith("sses") or token_stem.endswith("zes")) and len(token_stem) > 4:
            token_stem = token_stem[:-2]
        elif token_stem.endswith("s") and len(token_stem) > 3 and not token_stem.endswith("ss"):
            token_stem = token_stem[:-1]

        best_target = None
        best_type: Literal["TABLE", "COLUMN"] = "TABLE"
        best_emb_score = 0.0
        best_fuzz_score = 0.0
        best_combined = -1.0
        best_meta: Dict[str, Any] = {}

        # Fetch or compute embedding for the query candidate token
        # Get pre-fetched embedding for the query candidate token from cache
        cand_vec = token_emb_cache.get(token_text)

        for tbl in tables:
            t_raw = tbl.table_name.lower()
            t_tokens = [p for p in t_raw.split("_") if p]
            t_clean = " ".join(t_tokens)

            # 1. Match against table name
            # Check canonical model patterns:
            # - Exact name: "departments" or "department"
            # - Duplicate model tokens: "employee_employee", "patient_patient"
            # - Common ORM prefixes: "base_department", "tbl_patients", "dim_customers"
            has_duplicate_tokens = len(t_tokens) == 2 and t_tokens[0] == t_tokens[1] and (
                t_tokens[0] == token_text or t_tokens[0] == token_stem
            )
            stripped_prefix_match = False
            for pfx in ("base_", "tbl_", "dim_", "fact_", "ref_", "core_", "app_"):
                if t_raw.startswith(pfx):
                    remainder = t_raw[len(pfx):]
                    if remainder == token_text or remainder == token_stem or remainder == f"{token_stem}s":
                        stripped_prefix_match = True
                        break

            is_canonical_model = (
                t_raw == token_text
                or t_raw == token_stem
                or t_clean == token_text
                or t_clean == token_stem
                or has_duplicate_tokens
                or stripped_prefix_match
            )

            # Use token_sort_ratio; NEVER partial_ratio which causes false positives on multi-word tables!
            t_fuzz = max(
                fuzz.token_sort_ratio(token_text, t_clean),
                fuzz.token_sort_ratio(token_stem, t_clean),
            )

            if is_canonical_model:
                t_fuzz = 100.0
                t_cos = 1.0
                combined = 1.0
                norm_emb = 1.0
                norm_fuzz = 1.0
            else:
                t_vec = target_emb_cache.get(f"table:{tbl.table_name}")
                t_cos = cls.cosine_similarity(cand_vec, t_vec) if (cand_vec and t_vec) else (t_fuzz / 100.0)
                norm_emb, norm_fuzz, combined = cls.compute_combined_score(
                    t_cos, t_fuzz, embedding_weight, fuzzy_weight
                )

                # Penalize extra extraneous tokens on non-canonical tables
                if len(t_tokens) > 2:
                    combined = max(0.0, combined - 0.05 * (len(t_tokens) - 2))

                # Penalize auxiliary, audit, history, or junction tables unless explicitly asked
                if any(p in t_tokens for p in (
                    "answer", "historical", "override", "specific", "dashboard", "charts",
                    "audit", "history", "log", "logs", "migration", "migrations", "version"
                )):
                    combined = max(0.0, combined - 0.25)

            if combined > best_combined:
                best_combined = combined
                best_target = f"{tbl.schema_name}.{tbl.table_name}"
                best_type = "TABLE"
                best_emb_score = norm_emb
                best_fuzz_score = norm_fuzz
                best_meta = {"matched_name": tbl.table_name}

            # 2. Match against table columns
            for c_name in tbl.columns.keys():
                c_raw = c_name.lower()
                c_clean = c_raw.replace("_", " ")

                is_exact_col = (
                    token_text == c_raw
                    or token_stem == c_raw
                    or token_text == c_clean
                    or token_stem == c_clean
                )

                c_fuzz = max(
                    fuzz.token_sort_ratio(token_text, c_clean),
                    fuzz.token_sort_ratio(token_stem, c_clean),
                )

                if is_exact_col:
                    c_fuzz = 100.0
                    c_cos = 1.0
                    c_comb = 1.0
                    norm_emb = 1.0
                    norm_fuzz = 1.0
                else:
                    c_vec = target_emb_cache.get(f"col:{tbl.table_name}.{c_name}")
                    c_cos = cls.cosine_similarity(cand_vec, c_vec) if (cand_vec and c_vec) else (c_fuzz / 100.0)
                    norm_emb, norm_fuzz, c_comb = cls.compute_combined_score(
                        c_cos, c_fuzz, embedding_weight, fuzzy_weight
                    )

                    # Boost attribute FK column matches (e.g. reporting_manager_id_id for manager)
                    if c_raw == f"{token_stem}_id" or c_raw == f"{token_stem}_id_id" or c_raw == f"reporting_{token_stem}_id_id":
                        c_comb = max(c_comb, 0.90)

                if c_comb > best_combined:
                    best_combined = c_comb
                    best_target = f"{tbl.schema_name}.{tbl.table_name}.{c_name}"
                    best_type = "COLUMN"
                    best_emb_score = norm_emb
                    best_fuzz_score = norm_fuzz
                    best_meta = {"table_name": tbl.table_name, "column_name": c_name}

        # Determine confidence tier
        if best_combined >= high_threshold:
            confidence = EntityConfidence.HIGH
        elif best_combined >= medium_threshold:
            confidence = EntityConfidence.MEDIUM
        elif best_combined >= low_threshold:
            confidence = EntityConfidence.LOW
        else:
            confidence = EntityConfidence.UNRESOLVED

        best_meta["is_ngram"] = cand.is_ngram
        best_meta["likely_verb"] = cand.likely_verb

        return ResolvedEntity(
            token=cand.text,
            resolved_to=best_target if confidence != EntityConfidence.UNRESOLVED else None,
            entity_type=best_type,
            confidence=confidence,
            embedding_score=best_emb_score,
            fuzzy_score=best_fuzz_score,
            combined_score=max(0.0, best_combined),
            resolution_scope=scope,
            metadata=best_meta,
        )
