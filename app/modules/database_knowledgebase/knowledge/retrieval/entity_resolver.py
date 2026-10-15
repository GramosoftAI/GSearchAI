"""Phase 3 Step 3.6 Live Entity Value Resolver

Replaces weak matching in the old ValueResolver for Phase 3:
1. Match whole tokens only. Ignore stop-words and tokens equal to a table
   or column name ("customer" must NOT match CUSTOMER_TIER). "Chennai"
   must resolve to branches.city.
2. Candidate entity columns come from the value index, role name/enum/code,
   never sensitive or PII columns.
3. Split names: when a table has first_name + last_name (or similar),
   match the question span against each and against the combined name
   ("Girinath R" -> one row).
4. Typos via trigram similarity with a minimum threshold (min_similarity >= 0.50).
5. Live disambiguation: for a matched value in an entity column, run a
   parameterized, read-only, LIMIT 10 query on the customer DB through
   Phase1Adapter.open_readonly_connection (5s timeout), selecting the PK
   and up to 3 display columns (names, branch/department via FK label when
   available). Identifiers must be validated against the snapshot, values
   always bound as parameters. If more than one row matches, return
   ambiguous=true with the choices; if exactly one, return resolved with
   the PK. Never guess between rows.
6. If the question targets a sensitive/PII column ("salary", "password"),
   return unanswerable=true with a reason, no data.
7. Literals from the analyzer (email, phone, numbers) are returned as
   literal_filters with candidate columns by name/role. No lookup of
   PII values in any index.
"""

import uuid
import re
import logging
from typing import Optional, List, Dict, Any, Set, Tuple
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from ..adapters.phase1_adapter import Phase1Adapter, SchemaView, TableView
from ..repositories.entity_value_repository import EntityValueRepository
from ..repositories.knowledge_item_repository import KnowledgeItemRepository
from ..models.knowledge_items import KB2EntityValue, KB2KnowledgeItem
from ..sensitivity import (
    is_sensitive_column,
    is_sensitive_for_values,
    is_pii_column,
    PII_VALUE_TOKENS,
)
from .analyzer import QuestionFrame, extract_literals

logger = logging.getLogger(__name__)

# Stopwords set loaded
_STOPWORDS_SET = {
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "is", "are", "was", "were", "and", "or", "what", "which", "who", "whom",
    "where", "when", "why", "how", "all", "each", "every", "both", "few",
    "oda", "sollu", "kela", "la", "ku", "enna", "yaar", "inga", "enga", "nethu", "inniku",
}


class DisambiguationChoice(BaseModel):
    pk_value: Any
    display_label: str
    row_data: Dict[str, Any] = Field(default_factory=dict)


class ResolvedEntity(BaseModel):
    table_name: str
    column_name: str
    matched_value: str
    pk_column: str
    pk_value: Optional[Any] = None
    ambiguous: bool = False
    choices: List[DisambiguationChoice] = Field(default_factory=list)
    match_type: str = "exact"  # exact, fuzzy, composite_name
    similarity: float = 1.0


class LiteralFilter(BaseModel):
    literal_value: str
    literal_type: str  # email, phone, number
    candidate_columns: List[str] = Field(default_factory=list)


class EntityResolutionResult(BaseModel):
    resolved_entities: List[ResolvedEntity] = Field(default_factory=list)
    literal_filters: List[LiteralFilter] = Field(default_factory=list)
    unanswerable: bool = False
    unanswerable_reason: Optional[str] = None


class LiveEntityResolver:
    """Phase 3 Live Entity Value Resolver with live customer DB disambiguation."""

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: str | uuid.UUID,
        adapter: Optional[Phase1Adapter] = None,
        min_fuzzy_similarity: float = 0.50,
    ):
        self.db = db
        self.tenant_id = uuid.UUID(str(tenant_id))
        self.adapter = adapter or Phase1Adapter(session=db)
        self.entity_repo = EntityValueRepository(db=db, tenant_id=self.tenant_id)
        self.item_repo = KnowledgeItemRepository(db=db, tenant_id=self.tenant_id)
        self.min_fuzzy_similarity = min_fuzzy_similarity

    async def resolve(
        self,
        db_knowledgebase_id: uuid.UUID,
        frame: QuestionFrame,
        session: Optional[AsyncSession] = None,
    ) -> EntityResolutionResult:
        """Resolve entity values and literal filters from QuestionFrame."""
        target_db = session or self.db
        entity_repo = EntityValueRepository(db=target_db, tenant_id=self.tenant_id) if session else self.entity_repo
        item_repo = KnowledgeItemRepository(db=target_db, tenant_id=self.tenant_id) if session else self.item_repo
        adapter = Phase1Adapter(session=target_db) if session else self.adapter

        # 1. Check if the question targets sensitive or PII column values (e.g., salary, password)
        raw_lower = frame.original_question.lower()
        question_tokens = set(frame.tokens)

        # Sensitive check: unanswerable if asking for sensitive secrets/passwords/salary
        for tok in question_tokens:
            if is_sensitive_column(tok) or tok in ("salary", "password", "hash", "secret", "cvv", "token"):
                return EntityResolutionResult(
                    unanswerable=True,
                    unanswerable_reason=f"Question asks for restricted sensitive/protected field '{tok}'. Access denied.",
                )

        # 2. Extract literals from analyzer (emails, phones, numbers) -> literal_filters
        # Never look up PII values in any index
        literal_filters: List[LiteralFilter] = []
        schema_view: Optional[SchemaView] = None
        try:
            schema_view = await adapter.get_current_schema(self.tenant_id, db_knowledgebase_id)
        except Exception as e:
            logger.warning(f"Could not load schema view: {e}")

        # Catalog known table and column names to ignore tokens equal to schema names
        known_tables: Set[str] = set()
        known_columns: Set[str] = set()
        if schema_view and schema_view.tables:
            for t_k, t_val in schema_view.tables.items():
                known_tables.add(t_val.table_name.lower())
                for c_k in t_val.columns.keys():
                    known_columns.add(c_k.lower())

        for lit in frame.literal_values:
            lit_type = "plain"
            candidate_cols = []
            if "@" in lit:
                lit_type = "email"
                if schema_view:
                    for t_name, t_val in schema_view.tables.items():
                        for c_name in t_val.columns.keys():
                            if "email" in c_name.lower():
                                candidate_cols.append(f"{t_val.table_name}.{c_name}")
            elif re.sub(r"\D", "", lit) and len(re.sub(r"\D", "", lit)) >= 7:
                lit_type = "phone"
                if schema_view:
                    for t_name, t_val in schema_view.tables.items():
                        for c_name in t_val.columns.keys():
                            if "phone" in c_name.lower() or "mobile" in c_name.lower():
                                candidate_cols.append(f"{t_val.table_name}.{c_name}")
            else:
                lit_type = "number"

            literal_filters.append(
                LiteralFilter(
                    literal_value=lit,
                    literal_type=lit_type,
                    candidate_columns=candidate_cols,
                )
            )

        # 3. Candidate Spans for entity lookup
        # Form candidate spans: entity_candidates, multi-word spans from tokens, and individual tokens
        candidate_spans: List[str] = []
        if frame.entity_candidates:
            candidate_spans.extend(frame.entity_candidates)

        # Also add capitalized or consecutive token phrases from raw text
        raw_words = frame.original_question.split()
        for i in range(len(raw_words)):
            for j in range(i + 1, min(i + 4, len(raw_words) + 1)):
                span = " ".join(raw_words[i:j]).strip()
                clean_span = re.sub(r"[^\w\s]", "", span).strip()
                if clean_span and clean_span.lower() not in _STOPWORDS_SET and clean_span not in candidate_spans:
                    candidate_spans.append(clean_span)

        # Remove spans that exactly match known table or column names ("customer", "order", etc.)
        filtered_spans: List[str] = []
        for span in candidate_spans:
            s_low = span.lower().strip()
            if s_low in _STOPWORDS_SET:
                continue
            if s_low in known_tables or s_low in known_columns:
                continue
            filtered_spans.append(span)

        resolved_entities: List[ResolvedEntity] = []
        processed_keys: Set[Tuple[str, str, str]] = set()

        # 4. Search and Resolve against Entity Value Index & Split Names
        # Collect all valid candidate spans first and batch-fetch exact matches in one query
        valid_spans: List[Tuple[str, str]] = []
        norm_spans_set: Set[str] = set()
        for span in filtered_spans:
            norm_span = span.lower().strip()
            if len(norm_span) >= 2:
                valid_spans.append((span, norm_span))
                norm_spans_set.add(norm_span)

        exact_hits_by_norm: Dict[str, List[Dict[str, Any]]] = {}
        if norm_spans_set:
            stmt_all = select(KB2EntityValue).where(
                KB2EntityValue.tenant_id == self.tenant_id,
                KB2EntityValue.db_knowledgebase_id == db_knowledgebase_id,
                KB2EntityValue.normalized_value.in_(list(norm_spans_set)),
            )
            res_all = await target_db.execute(stmt_all)
            for ev in res_all.scalars().all():
                exact_hits_by_norm.setdefault(ev.normalized_value, []).append({
                    "table_name": ev.table_name,
                    "column_name": ev.column_name,
                    "raw_value": ev.raw_value,
                    "normalized_value": ev.normalized_value,
                    "similarity": 1.0,
                    "match_type": "exact",
                })

        for span, norm_span in valid_spans:
            # (A) Match pre-fetched exact hits in Python
            exact_hits: List[Dict[str, Any]] = exact_hits_by_norm.get(norm_span, [])

            # (B) Check fuzzy trigram similarity only if no exact hits
            fuzzy_hits: List[Dict[str, Any]] = []
            if not exact_hits:
                try:
                    async with target_db.begin_nested():
                        f_res = await entity_repo.search_fuzzy(
                            db_knowledgebase_id=db_knowledgebase_id,
                            query_text=norm_span,
                            limit=5,
                            min_similarity=self.min_fuzzy_similarity,
                        )
                        for fh in f_res:
                            if fh["similarity"] >= self.min_fuzzy_similarity:
                                fuzzy_hits.append({
                                    "table_name": fh["table_name"],
                                    "column_name": fh["column_name"],
                                    "raw_value": fh["raw_value"],
                                    "normalized_value": fh["normalized_value"],
                                    "similarity": fh["similarity"],
                                    "match_type": "fuzzy",
                                })
                except Exception as e:
                    logger.warning(f"Fuzzy entity search failed: {e}")

            all_hits = exact_hits or fuzzy_hits

            # (C) Handle split names check on tables with first_name + last_name
            # If span has multiple parts (e.g. "Girinath R") or is a single name, match against composite
            span_parts = norm_span.split()
            if schema_view and len(span_parts) >= 2:
                for t_k, t_val in schema_view.tables.items():
                    col_names = {c.lower(): c for c in t_val.columns.keys()}
                    if "first_name" in col_names and "last_name" in col_names:
                        # Composite query directly against customer DB table
                        table_ref = f'"{t_val.schema_name}"."{t_val.table_name}"' if t_val.schema_name else f'"{t_val.table_name}"'
                        pk_col = t_val.primary_key_columns[0] if t_val.primary_key_columns else "id"
                        fn_col = col_names["first_name"]
                        ln_col = col_names["last_name"]
                        
                        try:
                            async with adapter.open_readonly_connection(self.tenant_id, db_knowledgebase_id) as conn:
                                q_composite = f"""
                                    SELECT "{pk_col}", "{fn_col}", "{ln_col}"
                                    FROM {table_ref}
                                    WHERE LOWER(CONCAT("{fn_col}", ' ', "{ln_col}")) = $1
                                       OR LOWER(CONCAT("{fn_col}", "{ln_col}")) = $1
                                    LIMIT 10;
                                """
                                comp_rows = await conn.fetch(q_composite, norm_span)
                                if comp_rows:
                                    pk_val = comp_rows[0][pk_col] if len(comp_rows) == 1 else None
                                    is_ambig = len(comp_rows) > 1
                                    choices = [
                                        DisambiguationChoice(
                                            pk_value=r[pk_col],
                                            display_label=f"{r[fn_col]} {r[ln_col]}",
                                            row_data=dict(r),
                                        )
                                        for r in comp_rows
                                    ]
                                    t_clean = t_val.table_name
                                    dedup_k = (t_clean, "full_name", norm_span)
                                    if dedup_k not in processed_keys:
                                        processed_keys.add(dedup_k)
                                        resolved_entities.append(
                                            ResolvedEntity(
                                                table_name=t_clean,
                                                column_name=f"{fn_col}+{ln_col}",
                                                matched_value=span,
                                                pk_column=pk_col,
                                                pk_value=pk_val,
                                                ambiguous=is_ambig,
                                                choices=choices,
                                                match_type="composite_name",
                                                similarity=1.0,
                                            )
                                        )
                                        continue
                        except NotImplementedError:
                            pass
                        except Exception as e:
                            logger.warning(f"Composite name query failed: {e}")

            # (D) Process matched entity hits with Live Disambiguation
            for hit in all_hits:
                tbl = hit["table_name"]
                col = hit["column_name"]
                # Clean table name
                clean_t = tbl.split(".")[-1]
                val = hit["raw_value"]

                dedup_k = (clean_t, col, val.lower())
                if dedup_k in processed_keys:
                    continue
                processed_keys.add(dedup_k)

                # Live Disambiguation via customer DB parameterized query (5s timeout)
                if not schema_view or clean_t not in schema_view.tables:
                    # Fallback without live query
                    resolved_entities.append(
                        ResolvedEntity(
                            table_name=clean_t,
                            column_name=col,
                            matched_value=val,
                            pk_column="id",
                            pk_value=None,
                            ambiguous=False,
                            match_type=hit["match_type"],
                            similarity=hit["similarity"],
                        )
                    )
                    continue

                table_meta: TableView = schema_view.tables[clean_t]
                pk_col = table_meta.primary_key_columns[0] if table_meta.primary_key_columns else list(table_meta.columns.keys())[0]
                table_ref = f'"{table_meta.schema_name}"."{table_meta.table_name}"' if table_meta.schema_name else f'"{table_meta.table_name}"'

                # Choose up to 4 display columns, prioritizing label-like columns
                LABEL_COLS_PRIORITY = (
                    "firstname", "first_name", "lastname", "last_name", "login",
                    "name", "full_name", "title", "subject", "identifier", "city"
                )
                display_cols = [pk_col]
                for prio in LABEL_COLS_PRIORITY:
                    for c in table_meta.columns.keys():
                        if c.lower() == prio and c not in display_cols and not is_sensitive_column(c) and not is_sensitive_for_values(c):
                            display_cols.append(c)
                for c in table_meta.columns.keys():
                    if c != pk_col and c not in display_cols and not is_sensitive_column(c) and not is_sensitive_for_values(c):
                        display_cols.append(c)
                    if len(display_cols) >= 5:
                        break

                disp_cols_sql = ", ".join(f'"{c}"' for c in display_cols)
                live_query = f"""
                    SELECT {disp_cols_sql}
                    FROM {table_ref}
                    WHERE LOWER("{col}"::text) = $1
                    LIMIT 10;
                """

                def _build_display_label(row_dict: Dict[str, Any], fallback_pk: Any) -> str:
                    fn = row_dict.get("firstname") or row_dict.get("first_name")
                    ln = row_dict.get("lastname") or row_dict.get("last_name")
                    login = row_dict.get("login")
                    if fn and ln:
                        return f"{fn} {ln} ({login})" if login else f"{fn} {ln}"
                    if fn:
                        return f"{fn} ({login})" if login else str(fn)
                    for k in ("name", "full_name", "title", "subject", "login", "city"):
                        if row_dict.get(k):
                            return str(row_dict[k])
                    return str(fallback_pk)

                try:
                    async with adapter.open_readonly_connection(self.tenant_id, db_knowledgebase_id) as conn:
                        rows = await conn.fetch(live_query, val.lower())
                        if len(rows) == 1:
                            # Exactly one row -> resolved
                            pk_v = rows[0][pk_col]
                            resolved_entities.append(
                                ResolvedEntity(
                                    table_name=clean_t,
                                    column_name=col,
                                    matched_value=val,
                                    pk_column=pk_col,
                                    pk_value=pk_v,
                                    ambiguous=False,
                                    choices=[
                                        DisambiguationChoice(
                                            pk_value=pk_v,
                                            display_label=_build_display_label(dict(rows[0]), pk_v),
                                            row_data=dict(rows[0]),
                                        )
                                    ],
                                    match_type=hit["match_type"],
                                    similarity=hit["similarity"],
                                )
                            )
                        elif len(rows) > 1:
                            # More than one row -> ambiguous=True with choices
                            choices = [
                                DisambiguationChoice(
                                    pk_value=r[pk_col],
                                    display_label=_build_display_label(dict(r), r[pk_col]),
                                    row_data=dict(r),
                                )
                                for r in rows
                            ]
                            resolved_entities.append(
                                ResolvedEntity(
                                    table_name=clean_t,
                                    column_name=col,
                                    matched_value=val,
                                    pk_column=pk_col,
                                    pk_value=None,
                                    ambiguous=True,
                                    choices=choices,
                                    match_type=hit["match_type"],
                                    similarity=hit["similarity"],
                                )
                            )
                except NotImplementedError:
                    pass
                except Exception as exc:
                    logger.warning(f"Live disambiguation query failed for {clean_t}.{col}: {exc}")

        return EntityResolutionResult(
            resolved_entities=resolved_entities,
            literal_filters=literal_filters,
            unanswerable=False,
        )
