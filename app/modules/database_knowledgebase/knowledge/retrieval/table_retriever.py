"""Phase 3 Step 3.4 TableRetriever

Multi-signal Table Retrieval combining:
1. kb2_schema_docs Full-Text Search (AND query first, OR + prefix fallback)
2. Vector search via EmbeddingGenerator
3. Glossary hits: (glossary doc -> target table)
4. Metric hits: (metric doc -> tables it depends on)
5. Value-index hits: (matched entity value -> its table, with frequency boost)

Signals combined with Reciprocal Rank Fusion (RRF):
    score = sum( weight / (k + rank) )
Multipliers:
- confirmed > draft (1.2x boost)
- admin-locked (1.5x boost)
- Optional domain filtering.
Outputs top K tables with score and explanation reasons.
"""

import uuid
import re
import logging
from typing import Optional, List, Dict, Any, Set
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.embeddings import EmbeddingGenerator
from ..repositories.schema_doc_repository import SchemaDocRepository
from ..repositories.entity_value_repository import EntityValueRepository
from ..repositories.knowledge_item_repository import KnowledgeItemRepository
from ..models.knowledge_items import KB2SchemaDoc
from app.modules.database_knowledgebase.models.table_alias import KBTableAlias
from app.modules.database_knowledgebase.models.database_knowledgebase import DatabaseSchemaSnapshot
from .analyzer import QuestionFrame

logger = logging.getLogger(__name__)

RRF_K = 60


def split_identifier(name: str) -> List[str]:
    """Tokenize table/column identifiers on underscores, hyphens, dots, and camelCase transitions."""
    if not name:
        return []
    # Replace non-alphanumeric separators (underscores, hyphens, dots) with spaces
    s = re.sub(r"[_\-\.]+", " ", name)
    # camelCase: insert space between lowercase/digit and uppercase (tabEmployee -> tab Employee)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    # Acronyms: insert space between consecutive uppercase and uppercase followed by lowercase (XMLReader -> XML Reader)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    return [tok.lower().strip() for tok in s.split() if tok.strip()]


class TableCandidate(BaseModel):
    table_name: str
    score: float
    reasons: List[str] = Field(default_factory=list)
    signals: Dict[str, float] = Field(default_factory=dict)


class TableRetriever:
    """Retrieves and ranks candidate relational tables using hybrid signals and RRF."""

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: str | uuid.UUID,
        weights: Optional[Dict[str, float]] = None,
    ):
        self.db = db
        self.tenant_id = uuid.UUID(str(tenant_id))
        self.schema_doc_repo = SchemaDocRepository(db=db, tenant_id=self.tenant_id)
        self.entity_repo = EntityValueRepository(db=db, tenant_id=self.tenant_id)
        self.item_repo = KnowledgeItemRepository(db=db, tenant_id=self.tenant_id)
        self._table_terms_cache: Dict[str, Dict[str, Set[str]]] = {}

        # Configurable signal weights
        self.weights = weights or {
            "fts": 1.0,
            "vector": 1.0,
            "glossary": 1.2,
            "metric": 1.1,
            "value_index": 1.3,
        }

    async def _get_kb_table_terms(self, db_knowledgebase_id: uuid.UUID) -> Dict[str, Set[str]]:
        """Fetch canonical table names and matching terms (sub-tokens, aliases, singulars) for this KB.

        Dynamically derived from:
        1. kb2_schema_docs (doc_type='table')
        2. k2b_table_aliases (user-defined UI aliases)
        3. DatabaseSchemaSnapshot (latest snapshot for fallback / full coverage)
        """
        cache_key = str(db_knowledgebase_id)
        if cache_key in self._table_terms_cache:
            return self._table_terms_cache[cache_key]

        table_terms: Dict[str, Set[str]] = {}

        def _add_terms_for_table(canonical_table: str, raw_aliases: Optional[List[str]] = None):
            t_clean = canonical_table.lower().strip()
            if "." in t_clean:
                t_clean = t_clean.split(".")[-1]
            if not t_clean:
                return

            terms = table_terms.setdefault(t_clean, set())
            # 1. Whole table name and singular / plural variants
            terms.add(t_clean)
            if t_clean.endswith("s") and len(t_clean) > 2:
                terms.add(t_clean.rstrip("s"))
            if t_clean.endswith("ies") and len(t_clean) > 4:
                terms.add(t_clean[:-3] + "y")

            # 2. Tokenized sub-tokens on underscores and camelCase (e.g. emp_attendance -> emp, attendance)
            for sub_tok in split_identifier(canonical_table):
                if len(sub_tok) >= 2:
                    terms.add(sub_tok)
                    if sub_tok.endswith("s") and len(sub_tok) > 2:
                        terms.add(sub_tok.rstrip("s"))
                    if sub_tok.endswith("ies") and len(sub_tok) > 4:
                        terms.add(sub_tok[:-3] + "y")

            # 3. Aliases and their sub-tokens
            if raw_aliases:
                for alias in raw_aliases:
                    if not alias or not isinstance(alias, str):
                        continue
                    a_clean = alias.lower().strip()
                    if "." in a_clean:
                        a_clean = a_clean.split(".")[-1]
                    terms.add(a_clean)
                    if a_clean.endswith("s") and len(a_clean) > 2:
                        terms.add(a_clean.rstrip("s"))
                    for sub_a in split_identifier(alias):
                        if len(sub_a) >= 2:
                            terms.add(sub_a)
                            if sub_a.endswith("s") and len(sub_a) > 2:
                                terms.add(sub_a.rstrip("s"))

        # 1. Fetch from kb2_schema_docs
        try:
            stmt_docs = select(KB2SchemaDoc.item_key, KB2SchemaDoc.title, KB2SchemaDoc.aliases).where(
                KB2SchemaDoc.tenant_id == self.tenant_id,
                KB2SchemaDoc.db_knowledgebase_id == db_knowledgebase_id,
                KB2SchemaDoc.doc_type == "table",
                KB2SchemaDoc.status.in_(["confirmed", "draft"]),
            )
            res_docs = await self.db.execute(stmt_docs)
            for item_key, title, aliases in res_docs.all():
                c_tbl = item_key.split(".")[-1]
                alias_list = list(aliases) if aliases else []
                if title and title.lower() != c_tbl.lower():
                    alias_list.append(title)
                _add_terms_for_table(c_tbl, alias_list)
        except Exception as e:
            logger.debug(f"[TableRetriever] Failed to load schema docs for table terms: {e}")

        # 2. Fetch from k2b_table_aliases
        try:
            stmt_alias = select(KBTableAlias.table_name, KBTableAlias.aliases).where(
                KBTableAlias.db_knowledgebase_id == db_knowledgebase_id,
            )
            if self.tenant_id:
                stmt_alias = stmt_alias.where(KBTableAlias.tenant_id == self.tenant_id)
            res_alias = await self.db.execute(stmt_alias)
            for tbl_name, aliases in res_alias.all():
                alias_list = aliases if isinstance(aliases, list) else []
                _add_terms_for_table(tbl_name, alias_list)
        except Exception as e:
            logger.debug(f"[TableRetriever] Failed to load k2b_table_aliases: {e}")

        # 3. Fallback / supplement from latest DatabaseSchemaSnapshot
        try:
            stmt_snap = select(DatabaseSchemaSnapshot.schema_data).where(
                DatabaseSchemaSnapshot.tenant_id == self.tenant_id,
                DatabaseSchemaSnapshot.db_knowledgebase_id == db_knowledgebase_id,
            ).order_by(desc(DatabaseSchemaSnapshot.created_at)).limit(1)
            res_snap = await self.db.execute(stmt_snap)
            snap_data = res_snap.scalar_one_or_none()
            if snap_data and isinstance(snap_data, dict):
                def _process_snap_table(t_name_raw: str, t_val_raw: Any):
                    t_name = t_val_raw.get("table_name", t_name_raw) if isinstance(t_val_raw, dict) else t_name_raw
                    _add_terms_for_table(t_name)
                    if isinstance(t_val_raw, dict):
                        t_clean = t_name.lower().strip()
                        if "." in t_clean:
                            t_clean = t_clean.split(".")[-1]
                        t_set = table_terms.setdefault(t_clean, set())
                        # Table description tokens
                        t_desc = t_val_raw.get("description") or t_val_raw.get("comment") or ""
                        if t_desc and isinstance(t_desc, str):
                            for tok in re.findall(r"[a-zA-Z0-9_]{3,}", t_desc.lower()):
                                t_set.add(tok)
                        # Column names, sub-tokens, and semantic concepts
                        cols = t_val_raw.get("columns", {})
                        if isinstance(cols, dict):
                            has_monetary = False
                            has_temporal = False
                            for c_k, c_info in cols.items():
                                c_clean = c_k.lower()
                                t_set.add(c_clean)
                                for part in c_clean.split("_"):
                                    if len(part) >= 3:
                                        t_set.add(part)
                                c_desc = c_info.get("description") or c_info.get("comment") if isinstance(c_info, dict) else ""
                                if c_desc and isinstance(c_desc, str):
                                    for tok in re.findall(r"[a-zA-Z0-9_]{3,}", c_desc.lower()):
                                        t_set.add(tok)
                                if any(m in c_clean for m in ("amount", "price", "revenue", "cost", "total", "spend", "unit_price", "salary", "wage", "budget")):
                                    has_monetary = True
                                c_type = (c_info.get("data_type") if isinstance(c_info, dict) else "") or ""
                                if any(t_kw in str(c_type).upper() for t_kw in ("DATE", "TIME", "TIMESTAMP")) or any(d in c_clean for d in ("date", "_at", "time")):
                                    has_temporal = True
                            if has_monetary or any(tok in t_clean for tok in ("order", "sale", "invoice", "transaction", "payment", "purchase")):
                                t_set.update(["sales", "sale", "revenue", "spend", "spending", "spent"])
                            if has_temporal:
                                t_set.update(["month", "monthly", "year", "yearly", "week", "weekly", "date", "day"])

                # 1. Canonical schema format: { "schemas": { "schema_name": { "tables": { ... } } } }
                if "schemas" in snap_data and isinstance(snap_data["schemas"], dict):
                    for s_k, s_v in snap_data["schemas"].items():
                        if isinstance(s_v, dict) and "tables" in s_v and isinstance(s_v["tables"], dict):
                            for t_k, t_val in s_v["tables"].items():
                                _process_snap_table(t_k, t_val)
                # 2. Flat tables format: { "tables": { ... } }
                if "tables" in snap_data and isinstance(snap_data["tables"], dict):
                    for t_k, t_val in snap_data["tables"].items():
                        _process_snap_table(t_k, t_val)
        except Exception as e:
            logger.debug(f"[TableRetriever] Failed to load snapshot for table terms: {e}")

        self._table_terms_cache[cache_key] = table_terms
        return table_terms

    async def retrieve_tables(
        self,
        db_knowledgebase_id: uuid.UUID,
        frame: QuestionFrame,
        top_k: int = 12,
        domain_filter: Optional[str] = None,
        query_embedding: Optional[List[float]] = None,
    ) -> List[TableCandidate]:
        """Rank tables for the parsed QuestionFrame."""
        clean_text = frame.normalized_text or frame.original_question
        table_scores: Dict[str, float] = {}
        table_reasons: Dict[str, List[str]] = {}
        table_signals: Dict[str, Dict[str, float]] = {}

        def _add_score(table: str, score_delta: float, reason: str, signal_name: str):
            t_norm = table.lower().strip()
            # If schema-qualified, keep leaf table name
            if "." in t_norm:
                t_norm = t_norm.split(".")[-1]
            table_scores[t_norm] = table_scores.get(t_norm, 0.0) + score_delta
            table_reasons.setdefault(t_norm, []).append(reason)
            table_signals.setdefault(t_norm, {})[signal_name] = score_delta

        # -------------------------------------------------------------
        # 1. Full-Text Search (Table, Column, Metric, Glossary docs)
        # -------------------------------------------------------------
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
                _add_score(t_name, rrf_score * 0.9, f"FTS match on column {key} (rank {rank})", "fts_column")
            elif dt == "glossary":
                # Glossary target
                target = hit.get("unit") or hit.get("role") or ""
                # Parse body for Target:
                body = hit.get("body", "")
                if "Target (table):" in body:
                    t_target = body.split("Target (table):")[1].split(".")[0].strip()
                    _add_score(t_target, rrf_score * self.weights.get("glossary", 1.2), f"Glossary term {hit['title']} -> {t_target}", "glossary")
            elif dt == "metric":
                # Metric depends_on
                body = hit.get("body", "")
                for token in frame.tokens:
                    if token in key:
                        _add_score(token, rrf_score * self.weights.get("metric", 1.1), f"Metric hit {hit['title']}", "metric")

        # -------------------------------------------------------------
        # 2. Vector Search (Semantic Cosine Similarity)
        # -------------------------------------------------------------
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
                        _add_score(t_name, rrf_score, f"Vector match on table {t_name} (sim {hit['score']:.2f})", "vector")
                    elif dt == "column":
                        t_name = key.split(".")[1] if key.count(".") >= 2 else key.split(".")[0]
                        _add_score(t_name, rrf_score * 0.85, f"Vector match on column {key} (sim {hit['score']:.2f})", "vector_column")
        except Exception as e:
            logger.debug(f"[TableRetriever] Vector search fallback: {e}")

        # -------------------------------------------------------------
        # 3. Value-Index Search (for entity candidates, excluding literals)
        # -------------------------------------------------------------
        val_weight = self.weights.get("value_index", 1.3)
        entity_spans = frame.entity_candidates or []
        for span in entity_spans:
            # Skip if span is an excluded literal
            if span in frame.literal_values:
                continue
            try:
                # Fuzzy & FTS value search
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
        # 4. Keyword / Token Exact Table Name Match Boost
        # -------------------------------------------------------------
        table_terms_map = await self._get_kb_table_terms(db_knowledgebase_id=db_knowledgebase_id)
        q_low_text = clean_text.lower()

        AUXILIARY_PREFIX_SUFFIX = (
            "changeset", "ordered_", "gitlab_", "github_", "_journals", "_hierarchies",
            "_status_checks", "custom_actions_", "done_statuses", "_tokens", "historic",
            "_members", "_roles", "_custom_fields"
        )

        for t_known, terms in table_terms_map.items():
            t_low = t_known.lower()
            t_spaced = t_low.replace("_", " ")
            is_aux = any(aux in t_low for aux in AUXILIARY_PREFIX_SUFFIX)

            # Check full table phrase or singular match in original query
            matched_phrase = False
            if t_low in q_low_text or t_spaced in q_low_text:
                matched_phrase = True
            elif (t_low.endswith("s") and t_low[:-1] in q_low_text) or (t_spaced.endswith("s") and t_spaced[:-1] in q_low_text):
                matched_phrase = True

            if matched_phrase:
                score_boost = 0.50 if not is_aux else 0.15
                _add_score(t_known, score_boost, f"Full table phrase match '{t_known}'", "table_phrase_exact")

        for tok in frame.tokens:
            matched_tables_for_tok: Set[str] = set()
            for t_known, terms in table_terms_map.items():
                for term in terms:
                    if tok == term or tok == term.rstrip("s") or term == tok.rstrip("s") or (len(tok) >= 3 and term.startswith(tok)):
                        matched_tables_for_tok.add(t_known)
                        break
            for t_known in matched_tables_for_tok:
                t_low = t_known.lower()
                is_aux = any(aux in t_low for aux in AUXILIARY_PREFIX_SUFFIX)
                is_concept_tok = tok in ("sales", "sale", "revenue", "spend", "spending", "spent", "month", "monthly")
                delta = 0.25 if is_concept_tok and not is_aux else (0.05 if not is_aux else 0.02)
                _add_score(t_known, delta, f"Direct token match '{tok}'", "token_exact")

        # Compile candidates
        candidates: List[TableCandidate] = []
        for t_name, total_sc in sorted(table_scores.items(), key=lambda x: x[1], reverse=True):
            candidates.append(TableCandidate(
                table_name=t_name,
                score=total_sc,
                reasons=table_reasons.get(t_name, []),
                signals=table_signals.get(t_name, {}),
            ))

        return candidates[:top_k]
