"""Query Planner Orchestrator

Transforms user natural language queries and Phase 2A retrieved sub-schemas
into machine-validated QueryPlanIR objects.
"""

import re
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple
from ..schemas.canonical import ColumnDataType, ColumnSchema, DatabaseSchema, TableSchema
from ..retrieval.retriever import SchemaRetrievalResult
from .models import (
    AggregateFunction,
    ColumnProjectionPlan,
    IntentType,
    JoinPlan,
    JoinType,
    OrderByPlan,
    OrderDirection,
    PredicatePlan,
    QueryPlanIR,
    TablePlan,
)
from .intent_analyzer import QueryIntentAnalyzer, QueryIntentAnalysis, TemporalIntent
from .validator import QueryPlanValidator, QueryPlanValidationError
from ..schema.graph import SchemaGraph
from ..security.security_classifier import SecurityClassificationEngine, DataClassification


class QueryPlanner:
    """
    Constructs and validates a QueryPlanIR from user query and retrieved sub-schema.
    """

    @classmethod
    def _generate_alias(cls, table_name: str, used_aliases: Set[str]) -> str:
        """Generate a short, deterministic table alias."""
        # Common database abbreviation mappings
        presets = {
            "customers": "c",
            "orders": "o",
            "order_items": "oi",
            "products": "p",
            "payments": "pay",
            "users": "u",
            "items": "i",
        }
        if table_name.lower() in presets and presets[table_name.lower()] not in used_aliases:
            return presets[table_name.lower()]

        # Fallback initials
        parts = table_name.lower().split("_")
        initials = "".join([p[0] for p in parts if p])
        SQL_RESERVED_WORDS = {
            "or", "and", "in", "is", "as", "by", "on", "to", "not", "all",
            "any", "do", "if", "at", "no", "for", "set", "use", "end",
            "select", "from", "where", "group", "order", "limit", "offset",
            "join", "inner", "left", "right", "outer", "cross", "table", "case"
        }
        if initials and initials not in used_aliases and initials not in SQL_RESERVED_WORDS:
            return initials

        # Numbered alias
        base = parts[0][:3] if parts else "t"
        idx = 1
        while f"{base}{idx}" in used_aliases:
            idx += 1
        return f"{base}{idx}"

    @classmethod
    def _decompose_table_name(cls, table_name: str) -> Set[str]:
        """Extract semantic component tokens from physical table name, stripping noise prefixes."""
        NOISE = {"base", "tbl", "horilla", "django", "auth", "hist", "historical", "dim", "fact", "rel", "view"}
        parts = [p.lower() for p in re.split(r"[_\W]+", table_name) if p]
        tokens = set()
        for p in parts:
            if p in NOISE:
                continue
            tokens.add(p)
            if p.endswith("ies") and len(p) > 4:
                tokens.add(p[:-3] + "y")
            elif p.endswith("es") and len(p) > 4 and not p.endswith("ses"):
                tokens.add(p[:-2])
            elif p.endswith("s") and len(p) > 3 and not p.endswith("ss"):
                tokens.add(p[:-1])
        return tokens

    @classmethod
    def _resolve_aggregation_column(
        cls,
        agg_func: AggregateFunction,
        user_query: str,
        alias_to_table: Dict[str, TableSchema],
        primary_alias: str,
    ) -> Optional[Tuple[str, str]]:
        """
        Resolves target (table_alias, column_name) for an aggregation function.
        Enforces strict priority:
        1. Explicit semantic match (column name or exact stem mentioned in query)
        2. Schema/metadata-supported synonym (narrow, well-defined synonym mapping)
        3. Unambiguous numeric candidate (table has exactly one numeric metric column)
        4. Fail closed / return None (fall back to LLM, never guess among ambiguous candidates)
        """
        q_lower = user_query.lower()
        q_tokens = set(re.findall(r"\b[a-zA-Z0-9_]+\b", q_lower))

        # 1. COUNT Handling
        if agg_func in (AggregateFunction.COUNT, AggregateFunction.COUNT_DISTINCT):
            # If primary table entity is explicitly named in query tokens, count primary table
            prim_tbl = alias_to_table.get(primary_alias)
            if prim_tbl:
                p_lower = prim_tbl.table_name.lower()
                if p_lower in q_tokens or (p_lower.endswith("s") and p_lower[:-1] in q_tokens):
                    pk_col = next((c_name for c_name, c in prim_tbl.columns.items() if c.is_primary_key or c_name.lower() == "id"), None)
                    if pk_col:
                        return primary_alias, pk_col
                    if prim_tbl.columns:
                        return primary_alias, next(iter(prim_tbl.columns.keys()))

            # Check if an entity other than the primary table is explicitly named (e.g. "count office locations")
            for alias, tbl in alias_to_table.items():
                if alias == primary_alias:
                    continue
                t_lower = tbl.table_name.lower()
                if t_lower in q_tokens or (t_lower.endswith("s") and t_lower[:-1] in q_tokens):
                    pk_col = next((c_name for c_name, c in tbl.columns.items() if c.is_primary_key or c_name.lower() == "id"), None)
                    if pk_col:
                        return alias, pk_col

            # Default to primary table primary key or id
            if prim_tbl:
                pk_col = next((c_name for c_name, c in prim_tbl.columns.items() if c.is_primary_key or c_name.lower() == "id"), None)
                if pk_col:
                    return primary_alias, pk_col
                if prim_tbl.columns:
                    return primary_alias, next(iter(prim_tbl.columns.keys()))
            return None

        # 2. Metric Aggregations: SUM, AVG, MIN, MAX
        # Collect non-key numeric candidate columns
        numeric_candidates: List[Tuple[str, str, TableSchema, ColumnSchema]] = []
        for alias, tbl in alias_to_table.items():
            for c_name, col in tbl.columns.items():
                if col.is_primary_key or col.is_foreign_key:
                    continue
                if col.data_type in {ColumnDataType.BOOLEAN, ColumnDataType.TIMESTAMP, ColumnDataType.DATE, ColumnDataType.TIME}:
                    continue
                if any(c_name.lower().endswith(sfx) for sfx in ("_date", "_type", "_status", "_id", "_code", "_name", "_text", "_comment", "_description", "_mode", "_frequency")):
                    continue
                is_numeric = False
                if col.data_type in {ColumnDataType.INTEGER, ColumnDataType.DECIMAL, ColumnDataType.FLOAT}:
                    is_numeric = True
                elif col.raw_data_type:
                    raw_low = col.raw_data_type.lower()
                    if any(num_kw in raw_low for num_kw in ("int", "dec", "num", "float", "double", "real", "money", "serial")):
                        is_numeric = True
                if not is_numeric:
                    c_low = c_name.lower()
                    if any(m in c_low for m in ("hour", "wage", "salary", "amount", "price", "rate", "cost", "bonus", "duration")):
                        is_numeric = True

                if is_numeric:
                    numeric_candidates.append((alias, c_name, tbl, col))

        # Filter metric tokens in query (excluding grammatical and structural stopwords)
        STOPWORDS = {
            "what", "which", "where", "when", "who", "whom", "this", "that", "these", "those",
            "have", "has", "had", "does", "done", "show", "list", "tell", "find", "give",
            "average", "total", "count", "maximum", "minimum", "highest", "lowest", "least", "most",
            "company", "organization", "table", "record", "records", "there", "their", "each", "every",
            "for", "of", "in", "on", "at", "to", "by", "with", "from", "active", "inactive", "all", "the", "a", "an",
        }
        # Dynamically exclude schema table names and decomposed tokens from metric candidates
        table_nouns = {t.table_name.lower() for t in alias_to_table.values()}
        for t_name in list(table_nouns):
            for part in t_name.split("_"):
                table_nouns.add(part)
        metric_tokens = {t for t in q_tokens if len(t) > 2 and t not in STOPWORDS and t not in table_nouns}

        # Priority 1: Explicit semantic match
        explicit_matches: List[Tuple[str, str]] = []
        for alias, c_name, tbl, col in numeric_candidates:
            c_low = c_name.lower()
            c_words = set(c_low.split("_"))
            if c_low in q_tokens or (c_words & metric_tokens):
                explicit_matches.append((alias, c_name))

        # Priority 2: Schema/metadata-supported synonym mapping
        SYNONYM_MAP = {
            "wage": {"salary", "pay", "compensation", "wage", "earnings", "expenditure", "spending", "payroll", "salaries"},
            "salary": {"pay", "compensation", "earnings", "wage", "salaries", "expenditure", "spending", "payroll"},
            "budget": {"budget", "spending", "allowance", "funding"},
            "total_amount": {"revenue", "sales", "spending", "total", "turnover", "cost", "amount", "price", "subtotal", "expenditure"},
            "amount": {"spending", "spend", "cost", "value", "price", "expenditure"},
            "hours_worked": {"hours", "duration", "time", "worktime", "worked_hour", "worked", "working"},
            "hour": {"hours", "duration", "time", "worktime", "worked_hour", "worked", "working"},
            "points": {"bonus", "points", "point", "awarded"},
            "available_days": {"balance", "leave", "days", "available", "time off", "leaves"},
            "days": {"balance", "leave", "days", "available", "time off", "leaves"},
            "rating": {"score", "grade", "review", "satisfaction"},
            "overtime": {"overtime", "ot", "extra hours", "overtime_second"},
        }
        synonym_matches: List[Tuple[str, str]] = []
        for alias, c_name, tbl, col in numeric_candidates:
            c_low = c_name.lower()
            c_words = set(c_low.split("_"))
            for target_col_name, trigger_synonyms in SYNONYM_MAP.items():
                if target_col_name in c_words or c_low == target_col_name or any(target_col_name in w for w in c_words):
                    if any(syn in q_tokens or syn in user_query.lower() for syn in trigger_synonyms):
                        synonym_matches.append((alias, c_name))
                        break

        # Combine candidates from explicit match and synonyms
        all_matches = list({(m[0], m[1]): m for m in (explicit_matches + synonym_matches)}.values())

        if len(all_matches) == 1:
            return all_matches[0]
        elif len(all_matches) > 1:
            # 1. Prefer core column over prefix/qualifier variants (e.g. "wage" over "initial_wage", "worked_hour" over "minimum_hour")
            core_matches = [
                m for m in all_matches
                if not any(m[1].lower().startswith(pfx) for pfx in ("initial_", "previous_", "old_", "deduction_", "temp_", "min_", "minimum_"))
            ]
            candidates_to_rank = core_matches if core_matches else all_matches
            if len(candidates_to_rank) == 1:
                return candidates_to_rank[0]

            # 2. Check if exactly one match belongs to a table explicitly named in query tokens
            named_table_matches = []
            for alias, col_name in candidates_to_rank:
                tbl = alias_to_table[alias]
                t_low = tbl.table_name.lower()
                if t_low in q_tokens or (t_low.endswith("s") and t_low[:-1] in q_tokens):
                    named_table_matches.append((alias, col_name))
            if len(named_table_matches) == 1:
                return named_table_matches[0]

            # 3. Score candidates by token overlap with query
            sup_match = re.search(r"\b(?:most|highest|least|lowest|maximum|minimum)\s+([a-zA-Z0-9_]+)\b", user_query.lower())
            target_metric_word = sup_match.group(1) if sup_match else None

            def _candidate_score(cand: Tuple[str, str]) -> float:
                alias, c_name = cand
                tbl = alias_to_table[alias]
                c_clean = c_name.lower()
                c_parts = set(c_clean.split("_"))
                score = 0.0
                for part in c_parts:
                    if part in q_tokens:
                        score += 2.0
                    elif any(part in tok or tok in part for tok in q_tokens if len(tok) > 3):
                        score += 1.0
                if c_clean in user_query.lower() or c_clean.replace("_", " ") in user_query.lower():
                    score += 5.0
                # Direct match with metric following superlative (e.g. "overtime")
                if target_metric_word and (target_metric_word in c_parts or target_metric_word in c_clean):
                    score += 10.0
                # Give bonus if table name contains query tokens (e.g. "attendanceovertime" matches "overtime")
                t_low = tbl.table_name.lower()
                for tok in q_tokens:
                    if len(tok) > 3 and tok in t_low and tok not in {"base", "employee", "public", "app", "tbl"}:
                        score += 3.0
                return score

            sorted_candidates = sorted(candidates_to_rank, key=_candidate_score, reverse=True)
            if sorted_candidates and _candidate_score(sorted_candidates[0]) > 0.0:
                if len(sorted_candidates) == 1 or _candidate_score(sorted_candidates[0]) > _candidate_score(sorted_candidates[1]):
                    return sorted_candidates[0]
                # Tie-breaker: prefer candidate whose table has additional column matches with query tokens
                best_cand = sorted_candidates[0]
                best_extra = -1
                for cand in sorted_candidates:
                    if _candidate_score(cand) == _candidate_score(sorted_candidates[0]):
                        cand_tbl = alias_to_table[cand[0]]
                        extra_cols = sum(1 for c in cand_tbl.columns.keys() if c.lower() in q_tokens and c.lower() not in {"id"})
                        if extra_cols > best_extra:
                            best_extra = extra_cols
                            best_cand = cand
                return best_cand

            # Ambiguous: multiple matching columns -> fail closed to LLM
            return None

        # Priority 3: Unambiguous numeric candidate (only if primary table has exactly one numeric column)
        prim_candidates = [m for m in numeric_candidates if m[0] == primary_alias]
        if len(prim_candidates) == 1:
            return prim_candidates[0][0], prim_candidates[0][1]

        # Priority 4: If query mentions an entity or counting concept and no numeric candidates matched, fall back to entity PK count
        for alias, tbl in alias_to_table.items():
            t_lower = tbl.table_name.lower()
            if any(tok in q_tokens for tok in t_lower.split("_") if len(tok) > 3):
                pk = next((c for c, col in tbl.columns.items() if col.is_primary_key or c == "id"), None)
                if pk:
                    return alias, pk

        # Priority 5: Ambiguous / No match -> fail closed
        return None

    @classmethod
    def plan(
        cls,
        user_query: str,
        database_knowledgebase_id: uuid.UUID,
        canonical_schema: DatabaseSchema,
        retrieval_result: SchemaRetrievalResult,
        default_limit: Optional[int] = None,
        semantic_context: Optional[Any] = None,
    ) -> QueryPlanIR:
        """
        Create a machine-validated QueryPlanIR from user query and retrieved sub-schema.
        """
        analysis = QueryIntentAnalyzer.analyze(user_query)

        GENERIC_COLUMN_STOPWORDS = {
            "year", "month", "day", "days", "date", "time", "status", "name", "type",
            "description", "title", "id", "start", "end", "reason", "comment", "total",
            "amount", "stage", "order", "state", "hours", "hour", "period", "value",
            "code", "file", "image", "report", "user", "active", "is_active", "candidate",
            "employee", "details", "record", "request", "view", "count", "score", "note",
            "level", "number", "text", "sequence", "role", "action", "duration", "frequency",
        }

        # 1. Map Retrieved Tables into TablePlan objects with unique aliases
        all_table_plans: List[TablePlan] = []
        table_to_alias: Dict[str, str] = {}  # "public.customers" -> "c"
        alias_to_table: Dict[str, TableSchema] = {}
        used_aliases: Set[str] = set()

        for idx, tbl in enumerate(retrieval_result.retrieved_tables):
            table_key = f"{tbl.schema_name}.{tbl.table_name}"
            alias = cls._generate_alias(tbl.table_name, used_aliases)
            used_aliases.add(alias)
            table_to_alias[table_key] = alias
            alias_to_table[alias] = tbl

            role = "PRIMARY" if idx == 0 else "JOIN_TARGET"
            all_table_plans.append(
                TablePlan(
                    schema_name=tbl.schema_name,
                    table_name=tbl.table_name,
                    alias=alias,
                    role=role,
                )
            )

        q_lower = user_query.lower()
        q_tokens = set(re.findall(r"\b[a-zA-Z0-9_]+\b", q_lower))

        # 1.1 Enterprise Semantic Entity to Table Resolution (Phase 6.5 & Schema-Grounded)
        matched_entity_tables: Dict[str, str] = {}
        used_for_entity: Set[str] = set()
        graph = SchemaGraph.from_database_schema(canonical_schema)
        allowed_retrieved_tables = {t.table_name.lower() for t in retrieval_result.retrieved_tables}

        from app.core.config import get_settings
        settings = get_settings()
        resolved_entities: List[Any] = []

        if getattr(settings, "entity_resolution_mode", "schema_grounded") == "schema_grounded" and getattr(analysis, "candidates", None):
            from .schema_entity_resolver import SchemaEntityResolver, EntityConfidence
            try:
                resolved_entities = SchemaEntityResolver.resolve_candidates_sync(
                    candidates=analysis.candidates,
                    canonical_schema=canonical_schema,
                    candidate_tables=list(alias_to_table.values()),
                )
                for r in resolved_entities:
                    # Strict precision criteria for primary entity tables:
                    # 1. Must be HIGH confidence (>= 0.70)
                    # 2. Must be entity_type == "TABLE" (columns are not entity tables)
                    # 3. Must NOT be an n-gram (bigrams are concept binding, not primary tables)
                    # 4. Must NOT be a likely verb (verbs are action/filter concepts)
                    is_exact_table_ngram = False
                    if getattr(r, "metadata", {}).get("is_ngram") and r.resolved_to:
                        r_tbl_norm = r.resolved_to.lower().split(".")[-1].replace("_", "")
                        tok_norm = r.token.lower().replace(" ", "").replace("_", "").rstrip("s")
                        if r_tbl_norm == tok_norm or tok_norm in r_tbl_norm:
                            is_exact_table_ngram = True

                    if (
                        r.confidence == EntityConfidence.HIGH
                        and r.entity_type == "TABLE"
                        and (not getattr(r, "metadata", {}).get("is_ngram") or is_exact_table_ngram)
                        and not getattr(r, "metadata", {}).get("likely_verb")
                        and r.resolved_to
                    ):
                        r_tbl = r.resolved_to.lower().split(".")[-1]
                        for a, tbl in alias_to_table.items():
                            if tbl.table_name.lower() == r_tbl:
                                if a not in used_for_entity:
                                    # Disqualify disconnected tables: if an entity table is already matched,
                                    # any candidate table for another entity MUST have a valid join path in SchemaGraph
                                    # to at least one already matched entity table!
                                    if matched_entity_tables:
                                        has_path = any(
                                            alias_to_table[prev_a].table_name.lower() == tbl.table_name.lower()
                                            or graph.find_shortest_path(
                                                alias_to_table[prev_a].table_name,
                                                tbl.table_name,
                                                max_hops=3,
                                                allowed_tables=allowed_retrieved_tables,
                                            ) is not None
                                            for prev_a in matched_entity_tables.values()
                                        )
                                        if not has_path:
                                            continue
                                    matched_entity_tables[r.token] = a
                                    used_for_entity.add(a)
                                break
            except Exception:
                resolved_entities = []

        for ent in analysis.detected_entities:
            best_score = -1.0
            best_alias = None
            ent_stem = ent.lower()
            if ent_stem.endswith("s") and len(ent_stem) > 3:
                ent_stem = ent_stem[:-1]
            ent_parts = [p for p in ent_stem.split("_") if p]
            ent_clean = ent_stem.replace("_", "")

            for alias, tbl in alias_to_table.items():
                t_raw = tbl.table_name.lower()
                t_clean = t_raw.replace("_", "")
                t_tokens = cls._decompose_table_name(t_raw)
                score = 0.0

                raw_parts = [p for p in t_raw.split("_") if p]
                has_duplicate_tokens = len(raw_parts) == 2 and raw_parts[0] == raw_parts[1] and (
                    raw_parts[0] == ent or raw_parts[0] == ent_stem
                )
                stripped_prefix_match = False
                for pfx in ("base_", "tbl_", "dim_", "fact_", "ref_", "core_", "app_"):
                    if t_raw.startswith(pfx):
                        remainder = t_raw[len(pfx):]
                        if remainder == ent or remainder == ent_stem or remainder == f"{ent_stem}s" or remainder.replace("_", "") == ent_clean:
                            stripped_prefix_match = True
                            break

                if t_raw == ent or t_raw == f"{ent}s" or t_raw == ent_stem:
                    score = 1.0
                elif has_duplicate_tokens:
                    score = 0.95
                elif stripped_prefix_match:
                    score = 0.90
                elif len(ent_parts) > 1 and all(any(p == tok or p in tok for tok in t_tokens) for p in ent_parts):
                    # Compound match (e.g. leave_request matching leave_leaverequest)
                    score = 0.92 - (0.02 * len(t_tokens))
                elif ent_clean in t_clean or t_clean in ent_clean:
                    score = 0.85 - (0.02 * len(t_tokens))
                elif ent in t_tokens or ent_stem in t_tokens:
                    score = 0.80 - (0.04 * len(t_tokens))
                elif ent in t_raw or ent_stem in t_raw:
                    score = 0.50

                # Also match attribute-based entities via table columns (e.g. reporting_manager_id_id for manager)
                if score == 0.0 and ent_clean not in GENERIC_COLUMN_STOPWORDS:
                    for c_name in tbl.columns:
                        c_low = c_name.lower()
                        if c_low.endswith(("_id", "_id_id")):
                            continue
                        if ent == c_low or ent_stem == c_low:
                            score = 0.65 - (0.02 * len(t_tokens))
                            break

                # Disqualify disconnected tables: if a primary entity table is already matched,
                # any candidate table for another entity MUST have a valid join path in SchemaGraph!
                if matched_entity_tables and score > 0.0:
                    first_alias = next(iter(matched_entity_tables.values()))
                    first_tbl = alias_to_table[first_alias].table_name
                    if graph.find_shortest_path(first_tbl, tbl.table_name, max_hops=3, allowed_tables=allowed_retrieved_tables) is None:
                        score = 0.0
                    else:
                        # Prefer tables sharing domain prefix with the primary entity (e.g. employee_*)
                        first_domain = first_tbl.split("_")[0]
                        if tbl.table_name.startswith(f"{first_domain}_"):
                            score += 0.15

                # Penalize historical or log tables unless explicitly requested
                if "historical" in t_raw and "historical" not in ent_stem:
                    score -= 0.35
                if "override" in t_raw and "override" not in ent_stem:
                    score -= 0.25

                if score > best_score and score > 0.40:
                    best_score = score
                    best_alias = alias

            if best_alias and best_alias not in used_for_entity:
                matched_entity_tables[ent] = best_alias
                used_for_entity.add(best_alias)

        named_aliases: Set[str] = set(matched_entity_tables.values())

        # Collect candidate tables in retrieval whose decomposed tokens, clean names, domain concepts, or columns appear in query
        DOMAIN_CONCEPTS = {
            "payroll_contract": {"earn", "earns", "earning", "compensation", "salary", "wage", "pay"},
            "payroll_deduction": {"deduction", "deductions", "deduct", "payroll deduction", "payroll deductions"},
            "payroll_payslip": {"payslip", "payslips", "pay slip", "pay slips"},
            "asset_asset": {"asset", "assets", "laptop", "device", "hardware", "equipment", "status", "purchase", "cost", "warranty", "expire", "expiring", "expired"},
            "asset_assetassignment": {"assigned", "assignment", "device", "devices", "hardware", "equipment", "asset", "assets", "laptop", "hold"},
            "base_rotatingshiftassign": {"schedule", "shift", "roster", "rotating", "work schedule"},
            "pms_employeeobjective": {"okr", "okrs", "objective", "objectives", "goal", "goals", "quarterly goals"},
            "employee_employeebankdetails": {"bank", "banking", "account", "bank details", "ifsc", "routing", "iban", "swift"},
            "employee_bonuspoint": {"bonus", "bonus point", "bonus points", "points", "award", "awarded"},
            "base_worktype": {"work type", "worktype", "hybrid", "remote"},
            "employee_employeeworkinformation": {"work type", "worktype", "employee type", "employeetype", "work info", "work information", "designation", "job", "hybrid", "remote"},
            "payroll_loanaccount": {"loan", "loans", "installment", "installments", "borrow", "settled"},
            "helpdesk_ticket": {"ticket", "tickets", "helpdesk", "issue", "issues"},
            "project_project": {"project", "projects"},
            "project_task": {"task", "tasks"},
            "project_timesheet": {"timesheet", "timesheets", "time spent"},
            "attendance_attendance": {"attendance", "check in", "clock in", "check out", "clock out", "punch", "worked", "work", "working", "checkin", "checkout", "clockin", "clockout", "overtime"},
            "attendance_attendancelatecomeearlyout": {"late", "early", "early out", "late come", "leave early", "late arrivals", "arrival", "arrivals"},
            "leave_leaverequest": {"leave", "vacation", "absence", "absent", "absenteeism", "time off", "requested", "leaves"},
        }
        for alias, tbl in alias_to_table.items():
            t_low = tbl.table_name.lower()
            if t_low.startswith(("auth_", "django_")) or t_low in {"base_company"}:
                continue
            t_tokens = cls._decompose_table_name(t_low)
            clean_tokens = [tok for tok in t_tokens if tok not in {"base", "employee", "public", "app", "tbl"}]
            if any(tok in q_tokens for tok in clean_tokens):
                named_aliases.add(alias)
                continue

            # Domain concept triggers
            if t_low in DOMAIN_CONCEPTS:
                if any(syn in q_tokens if " " not in syn else syn in user_query.lower() for syn in DOMAIN_CONCEPTS[t_low]):
                    named_aliases.add(alias)
                    continue

            # Non-administrative column name or space-separated form in query
            for c_name in tbl.columns.keys():
                c_clean = c_name.lower()
                if (
                    len(c_clean) > 3
                    and c_clean not in GENERIC_COLUMN_STOPWORDS
                    and not c_clean.startswith(("created_", "modified_"))
                    and not c_clean.endswith(("_id_id", "_id"))
                ):
                    if c_clean in q_tokens or c_clean.replace("_", " ") in user_query.lower():
                        named_aliases.add(alias)
                        break

        # Check if query contains an entity literal mention (e.g. "details of Kannan", "What is Girinath phone number?")
        from .entity_value_resolver import EntityValueResolver
        literals = EntityValueResolver.extract_literal_candidates(user_query, canonical_schema=canonical_schema)
        anchor_alias = None
        if literals:
            best_alias = None
            best_score = -1.0
            ADMIN_TABLES = {"auth_user", "auth_group", "django_content_type", "base_company", "django_migrations", "django_session"}
            for a, tbl in alias_to_table.items():
                if tbl.table_name.lower() in ADMIN_TABLES or tbl.table_name.lower().startswith(("auth_", "django_")):
                    continue
                tbl_cols = {c.lower() for c in tbl.columns.keys()}
                score = 0.0
                if "onboarding" in user_query.lower() and "onboarding_candidatetask" in tbl.table_name.lower():
                    score += 85.0
                elif "candidate" in user_query.lower() and "candidate" in tbl.table_name.lower():
                    score += 65.0
                elif any("first_name" in c or "full_name" in c for c in tbl_cols):
                    score += 50.0
                elif any("last_name" in c for c in tbl_cols):
                    score += 40.0
                elif any(c.endswith("name") or "name" in c for c in tbl_cols if not c.endswith(("_id", "_id_id"))):
                    score += 20.0
                elif any("title" in c for c in tbl_cols):
                    score += 15.0

                if any("email" in c for c in tbl_cols):
                    score += 10.0

                # Prefer tables with fewer foreign keys (independent core entities over bridge/child tables)
                fk_count = len(tbl.foreign_keys) if tbl.foreign_keys else 0
                score -= fk_count * 2.0

                if score > best_score and score > 0.0:
                    best_score = score
                    best_alias = a

            # If no employee/person table with first_name was found in retrieved tables,
            # resolve the canonical employee anchor table directly from canonical_schema!
            if (not best_alias or best_score < 40.0) and canonical_schema:
                for s_name, s_val in canonical_schema.schemas.items():
                    for t_name, t_obj in s_val.tables.items():
                        if t_name.lower() in ADMIN_TABLES or t_name.lower().startswith(("auth_", "django_")):
                            continue
                        tbl_cols = {c.lower() for c in t_obj.columns.keys()}
                        if (
                            "employee_first_name" in tbl_cols
                            or t_name.lower() == "employee_employee"
                            or ("employee" in t_name.lower() and any("first_name" in c or "full_name" in c for c in tbl_cols))
                        ) and not any(h in t_name.lower() for h in ("historical", "backup", "audit", "note", "tag", "detail")):
                            cand_alias = None
                            for a, tbl in alias_to_table.items():
                                if tbl.table_name.lower() == t_name.lower():
                                    cand_alias = a
                                    break
                            if not cand_alias:
                                cand_alias = cls._generate_alias(t_name, used_aliases)
                                used_aliases.add(cand_alias)
                                alias_to_table[cand_alias] = t_obj
                                all_table_plans.append(TablePlan(schema_name=t_obj.schema_name, table_name=t_obj.table_name, alias=cand_alias, role="PRIMARY"))
                            best_alias = cand_alias
                            best_score = 100.0
                            break
                    if best_alias and best_score >= 100.0:
                        break

            if best_alias:
                anchor_alias = best_alias
                named_aliases.add(best_alias)

        def _get_or_create_table_alias(target_table_name: str, role: str = "PRIMARY") -> Optional[str]:
            for a, tbl in alias_to_table.items():
                if tbl.table_name.lower() == target_table_name.lower():
                    return a
            if canonical_schema:
                for s_name, s_val in canonical_schema.schemas.items():
                    for t_name, t_obj in s_val.tables.items():
                        if t_name.lower() == target_table_name.lower():
                            new_a = cls._generate_alias(t_name, used_aliases)
                            used_aliases.add(new_a)
                            alias_to_table[new_a] = t_obj
                            all_table_plans.append(TablePlan(schema_name=t_obj.schema_name, table_name=t_obj.table_name, alias=new_a, role=role))
                            return new_a
            return None

        # Check explicit domain keywords first to avoid random token collisions from all_table_plans
        explicit_target_table = None
        if any(w in q_lower for w in ("deduction", "deductions")):
            explicit_target_table = "payroll_deduction"
        elif any(w in q_lower for w in ("payslip", "pay slip", "salary slip")):
            explicit_target_table = "payroll_payslip"
        elif any(w in q_lower for w in ("salary", "wage", "contract")):
            explicit_target_table = "payroll_contract"
        elif any(w in q_lower for w in ("early out", "leave early", "late come", "late arrival", "late arrivals")) or ("late" in q_tokens and "latest" not in q_tokens) or ("early" in q_tokens):
            explicit_target_table = "attendance_attendancelatecomeearlyout"
        elif any(w in q_lower for w in ("attendance", "check in", "clock in", "check out", "clock out", "punch", "worked", "working", "work", "hours", "checkin", "checkout", "clockin", "clockout", "overtime")):
            explicit_target_table = "attendance_attendance"
        elif any(w in q_lower for w in ("vacation", "absence", "absent", "absenteeism", "time off", "on leave", "leave request", "leave balance", "sick leave", "casual leave")) or ("leave" in q_tokens and not any(w in q_lower for w in ("leave early", "early leave", "left early"))):
            if any(w in q_lower for w in ("balance", "available", "remaining")):
                explicit_target_table = "leave_availableleave"
            else:
                explicit_target_table = "leave_leaverequest"
        elif any(w in q_lower for w in ("asset", "assets", "laptop", "device", "hardware", "equipment", "warranty", "expiring", "expired", "purchased", "purchase", "cost")):
            explicit_target_table = "asset_asset"
        elif any(w in q_lower for w in ("department", "departments")):
            explicit_target_table = "base_department"
        elif any(w in q_lower for w in ("employee", "employees", "staff", "person", "people", "member", "members", "who", "highest-paid", "lowest-paid")):
            explicit_target_table = "employee_employee"

        # Anchor table takes highest precedence as primary table
        if anchor_alias:
            primary_alias = anchor_alias
        elif explicit_target_table and not any(w in q_lower for w in ("all employees in", "list all employees", "list employees")):
            target_alias = _get_or_create_table_alias(explicit_target_table, role="PRIMARY")
            if target_alias:
                primary_alias = target_alias
            else:
                primary_alias = all_table_plans[0].alias if all_table_plans else "t"
        else:
            specific_alias = None
            for tp in all_table_plans:
                if tp.alias in named_aliases and tp.table_name.lower() not in ("auth_user", "django_content_type"):
                    if tp.table_name.lower() != "employee_employee":
                        specific_alias = tp.alias
                        break
            if specific_alias and not any(w in q_lower for w in ("all employees in", "list all employees", "list employees")):
                primary_alias = specific_alias
            elif explicit_target_table:
                target_alias = _get_or_create_table_alias(explicit_target_table, role="PRIMARY")
                if target_alias:
                    primary_alias = target_alias
                else:
                    primary_alias = all_table_plans[0].alias if all_table_plans else "t"
            else:
                primary_alias = all_table_plans[0].alias if all_table_plans else "t"
                for tp in all_table_plans:
                    if tp.alias in named_aliases:
                        primary_alias = tp.alias
                        break

        # Primary entities that must be joined
        primary_entity_aliases = list(matched_entity_tables.values()) if matched_entity_tables else ([anchor_alias] if anchor_alias else [primary_alias])

        needed_aliases: Set[str] = {a for a in ({primary_alias} | set(primary_entity_aliases) | named_aliases) if a in alias_to_table}

        # Add host tables of resolved COLUMN entities to needed_aliases
        if resolved_entities:
            from .schema_entity_resolver import EntityConfidence
            for r in resolved_entities:
                if (
                    r.entity_type == "COLUMN"
                    and r.resolved_to
                    and r.confidence == EntityConfidence.HIGH
                    and not getattr(r, "metadata", {}).get("is_ngram")
                    and r.token.lower() not in GENERIC_COLUMN_STOPWORDS
                ):
                    r_clean = r.resolved_to.lower()
                    r_parts = r_clean.split(".")
                    r_tbl = r_parts[-2] if len(r_parts) >= 2 else ""
                    if r_tbl:
                        col_alias = None
                        for a, tbl in alias_to_table.items():
                            if tbl.table_name.lower() == r_tbl:
                                col_alias = a
                                break
                        if not col_alias and canonical_schema:
                            # Register table from canonical schema if not already present
                            for s_name, s_val in canonical_schema.schemas.items():
                                if r_tbl in s_val.tables:
                                    t_obj = s_val.tables[r_tbl]
                                    col_alias = cls._generate_alias(r_tbl, used_aliases)
                                    used_aliases.add(col_alias)
                                    alias_to_table[col_alias] = t_obj
                                    all_table_plans.append(TablePlan(schema_name=t_obj.schema_name, table_name=t_obj.table_name, alias=col_alias, role="JOIN_TARGET"))
                                    break
                        if col_alias:
                            needed_aliases.add(col_alias)

        # Semantic Table Disambiguation (Cardinality & Relationship Semantics Guard)
        # 1. Leave Balance vs Leave Request History
        if any(w in q_lower for w in ("balance", "available", "remaining")):
            has_balance_tbl = any("availableleave" in alias_to_table[a].table_name.lower().replace("_", "") for a in needed_aliases if a in alias_to_table)
            if has_balance_tbl:
                needed_aliases = {
                    a for a in needed_aliases
                    if not any(h in alias_to_table[a].table_name.lower().replace("_", "") for h in ("leaverequest", "allocation", "compensatory", "penalty", "restrict", "comment", "file"))
                }
        elif any(w in q_lower for w in ("request", "applied", "history", "taken")):
            has_request_tbl = any("leaverequest" in alias_to_table[a].table_name.lower().replace("_", "") for a in needed_aliases if a in alias_to_table)
            if has_request_tbl:
                needed_aliases = {
                    a for a in needed_aliases
                    if not any(h in alias_to_table[a].table_name.lower().replace("_", "") for h in ("availableleave", "allocation", "compensatory", "penalty", "restrict", "comment", "file"))
                }

        # 2. Contract vs Revision Disambiguation
        if "revision" not in q_lower:
            has_contract_tbl = any(alias_to_table[a].table_name.lower() == "payroll_contract" for a in needed_aliases if a in alias_to_table)
            if has_contract_tbl:
                needed_aliases = {
                    a for a in needed_aliases
                    if not any(h in alias_to_table[a].table_name.lower() for h in ("salaryrevision", "historicalcontract"))
                }

        # 3. Employee & Domain Focus & Anti-Join Explosion Guard
        primary_tbl_name = alias_to_table[primary_alias].table_name.lower()
        q_words = set(re.findall(r"\b\w+\b", q_lower))
        has_payslip_intent = any(w in q_lower for w in ("payslip", "pay slip", "salary slip", "pay stub", "paystub", "last paid", "net pay", "gross pay", "basic pay"))
        has_leave_intent = (
            any(w in q_lower for w in ("vacation", "time off", "absence", "absent", "absenteeism", "on leave", "leave request", "leave balance", "leave days", "sick leave", "casual leave", "parental leave", "maternity leave"))
            or ("leave" in q_words and not any(w in q_lower for w in ("leave early", "early leave", "left early")))
        )
        has_shift_intent = any(w in q_lower for w in ("shift", "shifts", "rotatingshift", "schedule", "roster"))
        has_dept_intent = any(w in q_lower for w in ("department", "dept"))
        has_pos_intent = any(w in q_lower for w in ("position", "designation", "role", "job", "work type", "hybrid", "remote", "permanent", "contractual", "intern", "probation"))
        has_manager_intent = any(w in q_lower for w in ("manager", "report", "head", "lead"))
        has_att_intent = (
            any(w in q_lower for w in ("attendance", "check in", "clock in", "check out", "clock out", "punch", "worked", "working", "checkin", "checkout", "clockin", "clockout", "overtime", "early out", "early arrivals", "late arrivals", "late come", "leave early"))
            or ("work" in q_words and "work type" not in q_lower and "work information" not in q_lower)
            or ("late" in q_words and "latest" not in q_words)
            or ("early" in q_words)
        ) and not has_shift_intent and not has_payslip_intent and not has_leave_intent
        has_salary_intent = (
            any(w in q_lower for w in ("salary", "wage", "compensation", "earnings", "contract", "earn"))
            or ("pay" in q_words and not has_payslip_intent)
            or "highest-paid" in q_lower
            or "lowest-paid" in q_lower
        ) and not has_payslip_intent
        has_asset_intent = any(w in q_lower for w in ("asset", "assets", "device", "laptop", "hardware", "equipment", "warranty", "expiring", "expired")) or "owns asset" in q_lower or "linked to asset" in q_lower
        has_ticket_intent = any(w in q_lower for w in ("ticket", "helpdesk", "issue"))
        has_onboarding_intent = any(w in q_lower for w in ("onboarding", "candidate task"))
        has_project_intent = (
            (
                any(w in q_lower for w in ("project", "projects", "task", "tasks", "timesheet", "timesheets"))
                or ("hours" in q_lower and any(w in q_lower for w in ("spend", "spent", "work on", "worked on")))
                or ("time" in q_lower and any(w in q_lower for w in ("spend", "spent")))
            )
            and not has_onboarding_intent
        )
        has_recruitment_intent = any(w in q_lower for w in ("candidate", "applicant", "recruitment", "interview"))
        has_pms_intent = any(w in q_lower for w in ("pms", "objective", "key result", "okr", "appraisal", "performance", "rating", "review", "feedback", "goal", "target"))
        has_disciplinary_intent = any(w in q_lower for w in ("disciplinary", "violation", "warning", "action"))
        has_allowance_intent = any(w in q_lower for w in ("allowance", "benefit", "stipend"))
        has_deduction_intent = any(w in q_lower for w in ("deduction", "tax", "pf", "esi")) and not has_payslip_intent
        has_loan_intent = any(w in q_lower for w in ("loan", "installment", "settled", "installments"))
        has_policy_intent = any(w in q_lower for w in ("policy", "policies"))
        has_bonus_intent = any(w in q_lower for w in ("bonus", "incentive"))
        has_holiday_intent = any(w in q_lower for w in ("holiday", "holidays"))
        has_badge_intent = any(w in q_lower for w in ("badge", "award"))

        DISALLOWED_AUX_SUFFIXES = (
            "_exclude_employees",
            "_specific_employees",
            "_filtered_employees",
            "_answer_employees",
            "_accessibility_employees",
            "_company_id",
            "_open_positions",
            "_job_position_ids",
            "_job_position",
            "_reject_reason_id",
            "_also_sent_to",
            "_colleague_id",
            "_others_id",
            "_subordinate_id",
            "_employee_id",
            "_attendance_id",
            "_candidate_id",
            "_key_result_id",
            "_key_results_id",
            "_template_id",
            "_question_template_id",
            "_allowance_exclude_employees",
            "_allowance_specific_employees",
            "_deduction_exclude_employees",
            "_deduction_specific_employees",
            "_announcement_department",
            "_announcement_employees",
            "_announcementcomment",
            "_installment_ids",
            "overtime",
            "allowedip",
        )
        needed_aliases = {
            a for a in needed_aliases
            if not any(alias_to_table[a].table_name.lower().endswith(sfx) for sfx in DISALLOWED_AUX_SUFFIXES)
            and alias_to_table[a].table_name.lower() not in (
                "leave_overrideleaverequests",
                "leave_leaverequestconditionapproval",
                "attendance_attendanceovertime",
                "base_attendanceallowedip",
                "payroll_payslip_installment_ids",
            )
        }

        if not has_recruitment_intent:
            needed_aliases = {
                a for a in needed_aliases
                if not alias_to_table[a].table_name.lower().startswith("recruitment_")
            }

        def _ensure_canonical_table(target_table_name: str, role: str = "JOIN_TARGET") -> Optional[str]:
            for a, t in alias_to_table.items():
                if t.table_name.lower() == target_table_name.lower():
                    return a
            if canonical_schema:
                for s_name, s_val in canonical_schema.schemas.items():
                    for t_name, t_obj in s_val.tables.items():
                        if t_name.lower() == target_table_name.lower():
                            new_alias = cls._generate_alias(t_name, used_aliases)
                            used_aliases.add(new_alias)
                            alias_to_table[new_alias] = t_obj
                            all_table_plans.append(TablePlan(schema_name=t_obj.schema_name, table_name=t_obj.table_name, alias=new_alias, role=role))
                            return new_alias
            return None

        active_target_aliases: Set[str] = {primary_alias}
        if anchor_alias:
            active_target_aliases.add(anchor_alias)

        for a in needed_aliases:
            t_name = alias_to_table[a].table_name.lower()
            if t_name == primary_tbl_name:
                active_target_aliases.add(a)
            elif "employee_employee" in t_name:
                active_target_aliases.add(a)
            elif has_dept_intent and t_name in ("base_department", "employee_employeeworkinformation", "employee_employee"):
                active_target_aliases.add(a)
            elif has_pos_intent and t_name in ("base_jobposition", "base_jobrole", "base_worktype", "employee_employeeworkinformation", "employee_employee"):
                active_target_aliases.add(a)
            elif (has_dept_intent or has_pos_intent or has_manager_intent) and "workinformation" in t_name:
                active_target_aliases.add(a)
            elif has_shift_intent and ("shift" in t_name or "workinformation" in t_name or "employee_employee" in t_name):
                active_target_aliases.add(a)
            elif has_att_intent:
                if t_name in ("attendance_attendance", "employee_employee"):
                    active_target_aliases.add(a)
                elif "late" in q_lower and "latecome" in t_name:
                    active_target_aliases.add(a)
                elif "overtime" in q_lower and "overtime" in t_name:
                    active_target_aliases.add(a)
                elif "activity" in q_lower and "activity" in t_name:
                    active_target_aliases.add(a)
            elif has_leave_intent:
                is_leave_balance = any(w in q_lower for w in ("balance", "available", "remaining", "have", "sick", "annual", "carry", "compensatory", "types"))
                if is_leave_balance and t_name in ("leave_availableleave", "leave_leavetype", "employee_employee"):
                    active_target_aliases.add(a)
                elif not is_leave_balance and t_name in ("leave_leaverequest", "leave_leavetype", "employee_employee"):
                    active_target_aliases.add(a)
            elif has_payslip_intent and t_name in ("payroll_payslip", "employee_employee"):
                active_target_aliases.add(a)
            elif has_loan_intent and t_name in ("payroll_loan", "payroll_loaninstallment", "employee_employee"):
                active_target_aliases.add(a)
            elif has_deduction_intent and t_name in ("payroll_deduction", "employee_employee"):
                active_target_aliases.add(a)
            elif has_salary_intent and t_name in ("payroll_contract", "employee_employeeworkinformation", "employee_employee"):
                active_target_aliases.add(a)
            elif has_asset_intent and t_name in ("asset_asset", "asset_assetassignment", "employee_employee", "employee_employeeworkinformation", "base_department"):
                active_target_aliases.add(a)
            elif has_asset_intent and t_name == "asset_assetcategory" and any(w in q_lower for w in ("category", "asset category")):
                active_target_aliases.add(a)
            elif has_ticket_intent and "ticket" in t_name:
                active_target_aliases.add(a)
            elif has_project_intent:
                is_ts = any(w in q_lower for w in ("timesheet", "hour", "hours", "spend", "spent", "time"))
                is_task = any(w in q_lower for w in ("task", "tasks"))
                if is_ts and t_name in ("project_timesheet", "project_project", "employee_employee"):
                    active_target_aliases.add(a)
                elif is_task and t_name in ("project_task", "project_task_task_members", "project_project", "employee_employee"):
                    active_target_aliases.add(a)
                elif not is_ts and not is_task and t_name in ("project_project", "project_project_members", "project_project_managers", "employee_employee"):
                    active_target_aliases.add(a)
            elif has_pms_intent and any(d in t_name for d in ("pms_", "objective", "keyresult")):
                active_target_aliases.add(a)
            elif has_disciplinary_intent and "disciplinary" in t_name:
                active_target_aliases.add(a)
            elif has_allowance_intent and "allowance" in t_name:
                active_target_aliases.add(a)
            elif has_policy_intent and "policy" in t_name:
                active_target_aliases.add(a)
            elif has_bonus_intent and "bonus" in t_name:
                active_target_aliases.add(a)
            elif has_holiday_intent and "holiday" in t_name:
                active_target_aliases.add(a)
            elif has_badge_intent and "badge" in t_name:
                active_target_aliases.add(a)

        # Ensure essential domain tables and bridge relations are present in active_target_aliases
        if has_asset_intent:
            asset_a = _ensure_canonical_table("asset_asset")
            if asset_a:
                active_target_aliases.add(asset_a)
            if any(w in q_lower for w in ("owner", "owns", "owned", "ownership")):
                emp_a = _ensure_canonical_table("employee_employee")
                if emp_a:
                    active_target_aliases.add(emp_a)
                active_target_aliases = {a for a in active_target_aliases if alias_to_table[a].table_name.lower() in ("asset_asset", "employee_employee")}
            elif any(w in q_lower for w in ("assigned", "assign", "assignment", "laptop", "engineering", "department", "staff")) or anchor_alias or literals:
                assign_a = _ensure_canonical_table("asset_assetassignment")
                if assign_a:
                    active_target_aliases.add(assign_a)
                emp_a = _ensure_canonical_table("employee_employee")
                if emp_a:
                    active_target_aliases.add(emp_a)
            else:
                # Standalone asset query
                active_target_aliases = {a for a in active_target_aliases if alias_to_table[a].table_name.lower() == "asset_asset"}
            if any(w in q_lower for w in ("category", "asset category")):
                cat_a = _ensure_canonical_table("asset_assetcategory")
                if cat_a:
                    active_target_aliases.add(cat_a)
            if has_dept_intent or any(alias_to_table[a].table_name.lower() == "base_department" for a in active_target_aliases):
                emp_a = _ensure_canonical_table("employee_employee")
                if emp_a:
                    active_target_aliases.add(emp_a)
                work_a = _ensure_canonical_table("employee_employeeworkinformation")
                if work_a:
                    active_target_aliases.add(work_a)
                dept_a = _ensure_canonical_table("base_department")
                if dept_a:
                    active_target_aliases.add(dept_a)
        elif has_project_intent:
            is_ts = any(w in q_lower for w in ("timesheet", "hour", "hours", "spend", "spent", "time"))
            is_task = any(w in q_lower for w in ("task", "tasks"))
            if is_ts:
                ts_a = _ensure_canonical_table("project_timesheet")
                if ts_a:
                    active_target_aliases.add(ts_a)
                if "project" in q_lower:
                    proj_a = _ensure_canonical_table("project_project")
                    if proj_a:
                        active_target_aliases.add(proj_a)
            elif is_task:
                task_a = _ensure_canonical_table("project_task")
                if task_a:
                    active_target_aliases.add(task_a)
                tm_a = _ensure_canonical_table("project_task_task_members")
                if tm_a:
                    active_target_aliases.add(tm_a)
                if "project" in q_lower:
                    proj_a = _ensure_canonical_table("project_project")
                    if proj_a:
                        active_target_aliases.add(proj_a)
            else:
                proj_a = _ensure_canonical_table("project_project")
                if proj_a:
                    active_target_aliases.add(proj_a)
                pm_a = _ensure_canonical_table("project_project_members")
                if pm_a:
                    active_target_aliases.add(pm_a)
                if "manager" in q_lower:
                    mgr_a = _ensure_canonical_table("project_project_managers")
                    if mgr_a:
                        active_target_aliases.add(mgr_a)
        else:
            if "absenteeism" in q_lower or (any(w in q_lower for w in ("absent", "absence")) and "department" in q_lower):
                dept_a = _ensure_canonical_table("base_department")
                if dept_a:
                    active_target_aliases.add(dept_a)
                work_a = _ensure_canonical_table("employee_employeeworkinformation")
                if work_a:
                    active_target_aliases.add(work_a)
                emp_a = _ensure_canonical_table("employee_employee")
                if emp_a:
                    active_target_aliases.add(emp_a)
                lea_a = _ensure_canonical_table("leave_leaverequest")
                if lea_a:
                    active_target_aliases.add(lea_a)
            elif has_dept_intent or any(alias_to_table[a].table_name.lower() == "base_department" for a in active_target_aliases):
                dept_a = _ensure_canonical_table("base_department")
                if dept_a:
                    active_target_aliases.add(dept_a)
                work_a = _ensure_canonical_table("employee_employeeworkinformation")
                if work_a:
                    active_target_aliases.add(work_a)
            elif has_pos_intent or any(alias_to_table[a].table_name.lower() in ("base_jobposition", "base_jobrole", "base_worktype") for a in active_target_aliases):
                if any(w in q_lower for w in ("job role", "role")):
                    pos_a = _ensure_canonical_table("base_jobrole")
                elif any(w in q_lower for w in ("work type", "hybrid", "remote")):
                    pos_a = _ensure_canonical_table("base_worktype")
                else:
                    pos_a = _ensure_canonical_table("base_jobposition")
                if pos_a:
                    active_target_aliases.add(pos_a)
                work_a = _ensure_canonical_table("employee_employeeworkinformation")
                if work_a:
                    active_target_aliases.add(work_a)
            elif has_shift_intent:
                shift_a = _ensure_canonical_table("base_employeeshift")
                if shift_a:
                    active_target_aliases.add(shift_a)
                if "rotating" in q_lower:
                    rot_a = _ensure_canonical_table("base_rotatingshiftassign")
                    if rot_a:
                        active_target_aliases.add(rot_a)
                work_a = _ensure_canonical_table("employee_employeeworkinformation")
                if work_a:
                    active_target_aliases.add(work_a)
            elif has_att_intent:
                if any(w in q_lower for w in ("late", "early out", "leave early", "late come", "late arrival", "late arrivals")):
                    late_a = _ensure_canonical_table("attendance_attendancelatecomeearlyout")
                    if late_a:
                        active_target_aliases.add(late_a)
                else:
                    att_a = _ensure_canonical_table("attendance_attendance")
                    if att_a:
                        active_target_aliases.add(att_a)
                if anchor_alias or literals or any(w in q_lower for w in ("who", "which employee", "employees")):
                    emp_a = _ensure_canonical_table("employee_employee")
                    if emp_a:
                        active_target_aliases.add(emp_a)
            elif has_leave_intent:
                is_leave_balance = any(w in q_lower for w in ("balance", "available", "remaining", "have", "sick", "annual", "carry", "compensatory", "types"))
                if is_leave_balance:
                    leave_a = _ensure_canonical_table("leave_availableleave")
                else:
                    leave_a = _ensure_canonical_table("leave_leaverequest")
                if leave_a:
                    active_target_aliases.add(leave_a)
                type_a = _ensure_canonical_table("leave_leavetype")
                if type_a:
                    active_target_aliases.add(type_a)
            elif has_payslip_intent:
                pay_a = _ensure_canonical_table("payroll_payslip")
                if pay_a:
                    active_target_aliases.add(pay_a)
            elif has_loan_intent:
                loan_a = _ensure_canonical_table("payroll_loan")
                if loan_a:
                    active_target_aliases.add(loan_a)
                inst_a = _ensure_canonical_table("payroll_loaninstallment")
                if inst_a:
                    active_target_aliases.add(inst_a)
            elif has_deduction_intent:
                ded_a = _ensure_canonical_table("payroll_deduction")
                if ded_a:
                    active_target_aliases.add(ded_a)
                if any(w in q_lower for w in ("contract", "salary")):
                    con_a = _ensure_canonical_table("payroll_contract")
                    if con_a:
                        active_target_aliases.add(con_a)
            elif has_salary_intent:
                contract_a = _ensure_canonical_table("payroll_contract")
                if contract_a:
                    active_target_aliases.add(contract_a)

        # Enforce strict domain boundaries on active_target_aliases
        ALLOWED_ASSET_TABLES = {"asset_asset", "asset_assetassignment", "employee_employee", "employee_employeeworkinformation", "base_department"}
        if any(w in q_lower for w in ("category", "asset category")):
            ALLOWED_ASSET_TABLES.add("asset_assetcategory")
        ALLOWED_ATTENDANCE_TABLES = {
            "attendance_attendance",
            "attendance_attendancelatecomeearlyout",
            "employee_employee",
            "employee_employeeworkinformation",
            "base_department",
            "leave_leaverequest",
            "leave_leavetype",
        }
        ALLOWED_PROJECT_TABLES = {"project_project", "project_project_members", "project_project_managers", "project_task", "project_task_task_members", "project_timesheet", "employee_employee"}
        ALLOWED_LEAVE_TABLES = {"leave_availableleave", "leave_leaverequest", "leave_leavetype", "employee_employee", "employee_employeeworkinformation", "base_department"}
        ALLOWED_LOAN_TABLES = {"payroll_loan", "payroll_loaninstallment", "employee_employee"}
        ALLOWED_DED_TABLES = {"payroll_deduction", "payroll_contract", "employee_employee"}

        if has_asset_intent:
            active_target_aliases = {a for a in active_target_aliases if alias_to_table[a].table_name.lower() in ALLOWED_ASSET_TABLES}
            primary_entity_aliases = [a for a in primary_entity_aliases if alias_to_table[a].table_name.lower() in ALLOWED_ASSET_TABLES]
        elif has_att_intent:
            active_target_aliases = {a for a in active_target_aliases if alias_to_table[a].table_name.lower() in ALLOWED_ATTENDANCE_TABLES}
            primary_entity_aliases = [a for a in primary_entity_aliases if alias_to_table[a].table_name.lower() in ALLOWED_ATTENDANCE_TABLES]
        elif has_project_intent:
            active_target_aliases = {a for a in active_target_aliases if alias_to_table[a].table_name.lower() in ALLOWED_PROJECT_TABLES}
            primary_entity_aliases = [a for a in primary_entity_aliases if alias_to_table[a].table_name.lower() in ALLOWED_PROJECT_TABLES]
        elif has_leave_intent:
            active_target_aliases = {a for a in active_target_aliases if alias_to_table[a].table_name.lower() in ALLOWED_LEAVE_TABLES}
            primary_entity_aliases = [a for a in primary_entity_aliases if alias_to_table[a].table_name.lower() in ALLOWED_LEAVE_TABLES]
        elif has_loan_intent:
            active_target_aliases = {a for a in active_target_aliases if alias_to_table[a].table_name.lower() in ALLOWED_LOAN_TABLES}
            primary_entity_aliases = [a for a in primary_entity_aliases if alias_to_table[a].table_name.lower() in ALLOWED_LOAN_TABLES]
        elif has_deduction_intent:
            active_target_aliases = {a for a in active_target_aliases if alias_to_table[a].table_name.lower() in ALLOWED_DED_TABLES}
            primary_entity_aliases = [a for a in primary_entity_aliases if alias_to_table[a].table_name.lower() in ALLOWED_DED_TABLES]

        needed_aliases = active_target_aliases
        if primary_alias not in needed_aliases and needed_aliases:
            primary_alias = next(iter(needed_aliases))

        # 2. Map Active Relationships to all_join_plans
        all_join_plans: List[JoinPlan] = []
        for rel in retrieval_result.join_paths:
            src_key = f"{rel.source_schema}.{rel.source_table}"
            tgt_key = f"{rel.target_schema}.{rel.target_table}"

            if src_key in table_to_alias and tgt_key in table_to_alias:
                src_alias = table_to_alias[src_key]
                tgt_alias = table_to_alias[tgt_key]
                src_col = rel.source_columns[0] if rel.source_columns else "id"
                tgt_col = rel.target_columns[0] if rel.target_columns else "id"

                if has_asset_intent:
                    if src_col == "assigned_by_employee_id_id" or tgt_col == "assigned_by_employee_id_id":
                        continue
                    if (src_col == "owner_id" or tgt_col == "owner_id") and not any(w in q_lower for w in ("owner", "owns", "owned", "ownership")):
                        continue

                all_join_plans.append(
                    JoinPlan(
                        source_table_alias=src_alias,
                        source_column=src_col,
                        target_table_alias=tgt_alias,
                        target_column=tgt_col,
                        join_type=JoinType.INNER,
                        relationship_name=rel.relationship_type.value,
                    )
                )

        # 2.1 Minimal Relationship Subgraph Connection (Phase 6.5)
        # If multiple primary entities are requested, ensure they are connected via approved join paths
        if len(primary_entity_aliases) >= 2:
            graph = SchemaGraph.from_database_schema(canonical_schema)
            if has_asset_intent:
                allowed_retrieved_tables = ALLOWED_ASSET_TABLES
            elif has_att_intent:
                allowed_retrieved_tables = ALLOWED_ATTENDANCE_TABLES
            elif has_project_intent:
                allowed_retrieved_tables = ALLOWED_PROJECT_TABLES
            elif has_leave_intent:
                allowed_retrieved_tables = ALLOWED_LEAVE_TABLES
            elif has_loan_intent:
                allowed_retrieved_tables = ALLOWED_LOAN_TABLES
            elif has_deduction_intent:
                allowed_retrieved_tables = ALLOWED_DED_TABLES
            else:
                allowed_retrieved_tables = {t.table_name.lower() for t in retrieval_result.retrieved_tables}

            forbidden_hops = set()
            if has_asset_intent and not any(w in q_lower for w in ("owner", "owns", "owned", "ownership")):
                forbidden_hops.add(("asset_asset", "employee_employee"))
                forbidden_hops.add(("employee_employee", "asset_asset"))

            primary_list = sorted(list(primary_entity_aliases))
            for i in range(len(primary_list)):
                for j in range(i + 1, len(primary_list)):
                    a1, a2 = primary_list[i], primary_list[j]
                    t1_name = alias_to_table[a1].table_name
                    t2_name = alias_to_table[a2].table_name

                    path = graph.find_shortest_path(
                        t1_name,
                        t2_name,
                        max_hops=4,
                        allowed_tables=allowed_retrieved_tables,
                        forbidden_hops=forbidden_hops,
                    )
                    if path and len(path) > 1:
                        for step_idx in range(len(path) - 1):
                            u_name = path[step_idx]
                            v_name = path[step_idx + 1]

                            # Resolve or register alias for u
                            u_alias = None
                            for a, t in alias_to_table.items():
                                if t.table_name.lower() == u_name.lower() or f"{t.schema_name}.{t.table_name}".lower() == u_name.lower():
                                    u_alias = a
                                    break
                            if not u_alias:
                                u_clean = u_name.split(".")[-1]
                                if u_clean.lower() in allowed_retrieved_tables:
                                    for s_name, s_val in canonical_schema.schemas.items():
                                        if u_clean in s_val.tables:
                                            t_obj = s_val.tables[u_clean]
                                            u_alias = cls._generate_alias(u_clean, used_aliases)
                                            used_aliases.add(u_alias)
                                            alias_to_table[u_alias] = t_obj
                                            all_table_plans.append(TablePlan(schema_name=t_obj.schema_name, table_name=t_obj.table_name, alias=u_alias, role="BRIDGE"))
                                            break

                            # Resolve or register alias for v
                            v_alias = None
                            for a, t in alias_to_table.items():
                                if t.table_name.lower() == v_name.lower() or f"{t.schema_name}.{t.table_name}".lower() == v_name.lower():
                                    v_alias = a
                                    break
                            if not v_alias:
                                v_clean = v_name.split(".")[-1]
                                if v_clean.lower() in allowed_retrieved_tables:
                                    for s_name, s_val in canonical_schema.schemas.items():
                                        if v_clean in s_val.tables:
                                            t_obj = s_val.tables[v_clean]
                                            v_alias = cls._generate_alias(v_clean, used_aliases)
                                            used_aliases.add(v_alias)
                                            alias_to_table[v_alias] = t_obj
                                            all_table_plans.append(TablePlan(schema_name=t_obj.schema_name, table_name=t_obj.table_name, alias=v_alias, role="BRIDGE"))
                                            break

                            if u_alias and v_alias:
                                needed_aliases.add(u_alias)
                                needed_aliases.add(v_alias)

                                candidate_matches = []
                                for neighbor, rel in graph.get_neighbors(u_name):
                                    if neighbor == v_name or neighbor.split(".")[-1] == v_name.split(".")[-1]:
                                        src_tbl = rel.source_table.lower()
                                        tgt_tbl = rel.target_table.lower()
                                        u_clean = u_name.split(".")[-1].lower()

                                        if u_clean == src_tbl:
                                            u_col = rel.source_columns[0] if rel.source_columns else "id"
                                            v_col = rel.target_columns[0] if rel.target_columns else "id"
                                            fk_col = u_col
                                        else:
                                            u_col = rel.target_columns[0] if rel.target_columns else "id"
                                            v_col = rel.source_columns[0] if rel.source_columns else "id"
                                            fk_col = v_col

                                        score = 0
                                        if any(w in q_lower for w in ("owner", "owns", "owned", "ownership")) and fk_col.lower() == "owner_id":
                                            score += 150
                                        elif fk_col.lower() in ("employee_id_id", "candidate_id", "department_id", "leave_type_id_id", "stage_id_id"):
                                            score += 100
                                        elif "employee" in fk_col.lower() and not any(ign in fk_col.lower() for ign in ("created", "modified", "managed", "reported", "assigned")):
                                            score += 80
                                        elif any(ign in fk_col.lower() for ign in ("created", "modified", "reported", "assigned", "canceled", "rejected", "approved", "history")):
                                            score -= 50
                                        candidate_matches.append((score, u_col, v_col, rel))

                                if candidate_matches:
                                    candidate_matches.sort(key=lambda x: x[0], reverse=True)
                                    best_score, u_col, v_col, rel = candidate_matches[0]
                                    if not any((jp.source_table_alias == u_alias and jp.target_table_alias == v_alias) or (jp.source_table_alias == v_alias and jp.target_table_alias == u_alias) for jp in all_join_plans):
                                        all_join_plans.append(
                                            JoinPlan(
                                                source_table_alias=u_alias,
                                                source_column=u_col,
                                                target_table_alias=v_alias,
                                                target_column=v_col,
                                                join_type=JoinType.INNER,
                                                relationship_name=rel.relationship_type.value if hasattr(rel.relationship_type, "value") else str(rel.relationship_type),
                                            )
                                        )

        # If semantic context specifies approved joins, filter candidate joins strictly to approved paths
        if semantic_context and getattr(semantic_context, "approved_joins", None):
            approved_pairs = set()
            for aj in semantic_context.approved_joins:
                approved_pairs.add((aj.source_table.lower(), aj.target_table.lower()))
                approved_pairs.add((aj.target_table.lower(), aj.source_table.lower()))
            all_join_plans = [
                jp for jp in all_join_plans
                if (alias_to_table[jp.source_table_alias].table_name.lower(), alias_to_table[jp.target_table_alias].table_name.lower()) in approved_pairs
            ]

        # 3. Formulate Column Projections & Grouping
        projections: List[ColumnProjectionPlan] = []
        group_by: List[str] = []

        BRIDGE_TABLES = {
            "employee_employeeworkinformation",
            # NOTE: asset_assetassignment is intentionally NOT a bridge here so that
            # assigned_date / return_date / return_status can be projected for asset queries.
            "project_project_members", "project_task_task_members",
            "base_rotatingshiftassign", "payroll_payslip_installment_ids",
            "attendance_attendancerequestcomment_files", "leave_leaverequestcomment",
        }
        bridge_aliases = {
            tp.alias for tp in all_table_plans
            if tp.role == "BRIDGE" or tp.table_name.lower() in BRIDGE_TABLES
        }

        SENSITIVE_FINANCIAL = {"basic_salary", "salary", "wage", "gross_pay", "net_pay", "basic_pay", "deduction", "allowance", "bonus", "hourly_rate", "payment_rate", "salary_hour", "revised_salary"}
        SENSITIVE_BANKING = {"bank_name", "account_number", "routing_number", "iban", "swift", "branch", "ifsc"}
        SENSITIVE_CONTACT = {"phone", "mobile", "telephone", "emergency_contact", "contact_number"}
        SENSITIVE_PII = {"dob", "date_of_birth", "age", "marital_status", "children", "passport_number", "ssn", "national_id"}
        SENSITIVE_LOCATION = {"address", "address_line", "postal_code", "zip_code"}
        SENSITIVE_CREDENTIALS = {"password", "secret", "token", "hash", "salt"}

        is_fin_auth = (
            has_salary_intent or has_payslip_intent or has_deduction_intent or has_allowance_intent
            or any(w in q_lower for w in (
                "salary", "wage", "earn", "earning", "make", "compensation",
                "payslip", "deduction", "allowance", "bonus", "gross pay",
                "net pay", "basic pay", "pay", "income", "basic_salary"
            ))
        )
        if is_fin_auth and any(w in q_lower for w in ("show employees", "list employees", "which employees", "who are the employees", "employees in", "all employees")):
            if any(kw in q_lower for kw in ("whose salary", "with salary", "salary >", "salary above", "salary <", "salary less", "salary greater")):
                if not any(ask in q_lower for ask in ("and their salary", "with their salary", "show salary", "what is their salary")):
                    is_fin_auth = False

        is_phone_auth = any(w in q_lower for w in ("phone", "mobile", "cell", "telephone", "call", "contact number"))
        if is_phone_auth and "whose phone" in q_lower and "available" in q_lower and not any(ask in q_lower for ask in ("show phone", "what is", "and their phone")):
            is_phone_auth = False

        is_email_auth = any(w in q_lower for w in ("email", "mail address", "send email", "email address", "where can i email"))
        is_dob_auth = any(w in q_lower for w in ("dob", "birth", "birthday", "born", "age", "how old"))
        is_exp_auth = any(w in q_lower for w in ("experience", "how many years of experience", "exp"))
        is_gender_auth = any(w in q_lower for w in ("gender", "sex"))
        is_marital_auth = any(w in q_lower for w in ("marital", "married", "single", "spouse", "marriage"))
        is_children_auth = any(w in q_lower for w in ("children", "kids", "child", "dependents"))
        is_qual_auth = any(w in q_lower for w in ("qualification", "degree", "education", "graduat"))
        is_loc_auth = any(w in q_lower for w in ("address", "where does", "where is", "live", "residence", "city", "state", "country", "postal"))
        is_bank_auth = any(w in q_lower for w in ("bank", "account number", "iban", "routing", "swift", "ifsc"))

        # If semantic context has a resolved canonical metric, use its definition as authoritative projection
        if semantic_context and getattr(semantic_context, "resolved_metric", None):
            metric = semantic_context.resolved_metric
            m_target_alias = None
            m_target_col = metric.source_column
            for alias, tbl in alias_to_table.items():
                if tbl.table_name.lower() == metric.source_entity.lower() or tbl.table_name.lower() == (metric.source_entity.lower() + "s"):
                    m_target_alias = alias
                    break
                if m_target_col.lower() in {c.lower() for c in tbl.columns.keys()}:
                    m_target_alias = alias
                    break
            if not m_target_alias:
                m_target_alias = primary_alias

            needed_aliases.add(m_target_alias)
            agg_val = metric.aggregation.value if hasattr(metric.aggregation, "value") else str(metric.aggregation)
            agg_enum = getattr(AggregateFunction, agg_val.upper(), AggregateFunction.COUNT)
            projections.append(
                ColumnProjectionPlan(
                    table_alias=m_target_alias,
                    column_name=m_target_col,
                    output_alias=metric.name,
                    aggregation=agg_enum,
                )
            )

        elif analysis.aggregations:
            resolved_aggs = []
            for agg in analysis.aggregations:
                col_res = cls._resolve_aggregation_column(
                    agg_func=agg.function,
                    user_query=user_query,
                    alias_to_table=alias_to_table,
                    primary_alias=primary_alias,
                )
                if col_res:
                    resolved_aggs.append((agg, col_res[0], col_res[1]))
                else:
                    break

            if len(resolved_aggs) < len(analysis.aggregations):
                # Ambiguous or unresolvable aggregate column: decline deterministic path, fall back to LLM
                return QueryPlanIR(
                    database_knowledgebase_id=database_knowledgebase_id,
                    schema_version=canonical_schema.fingerprint or "unknown",
                    user_query=user_query,
                    intent=analysis.intent,
                    tables=all_table_plans,
                    projections=[],
                    joins=all_join_plans,
                    predicates=[],
                    group_by=[],
                    order_by=[],
                    limit=None,
                    confidence=0.0,
                    reasoning="Ambiguous or unresolvable aggregate target column; declining deterministic compilation",
                )

            # Add aggregate projection(s)
            for agg, tgt_alias, tgt_col in resolved_aggs:
                needed_aliases.add(tgt_alias)
                projections.append(
                    ColumnProjectionPlan(
                        table_alias=tgt_alias,
                        column_name=tgt_col,
                        output_alias=f"{agg.function.value.lower()}_{tgt_col}",
                        aggregation=agg.function,
                    )
                )

            if analysis.grouping_required:
                # Grouped aggregate: find grouping column matching concept
                grp_alias = None
                grp_col = None
                if analysis.grouping_concept:
                    g_low = analysis.grouping_concept.lower()
                    # Candidate aliases to search: prioritize aliases already in needed_aliases
                    cand_search_aliases = [a for a in needed_aliases if a in alias_to_table] + [a for a in alias_to_table if a not in needed_aliases]
                    for alias in cand_search_aliases:
                        tbl = alias_to_table[alias]
                        t_low = tbl.table_name.lower()
                        # Prefer employee_employee for employee concept
                        if g_low in ("employee", "person", "staff", "who"):
                            if t_low != "employee_employee":
                                continue
                            grp_alias = alias
                            grp_col = "id"
                            break
                        # Prefer base_department for department concept
                        if g_low in ("department", "dept"):
                            if t_low != "base_department":
                                continue
                            grp_alias = alias
                            grp_col = next((c for c in tbl.columns.keys() if c.lower() in ("department", "name", "title")), "id")
                            break
                        if g_low in t_low or (t_low.endswith("s") and t_low[:-1] == g_low):
                            for c_name in tbl.columns.keys():
                                if c_name.lower() in ("name", "title", "department_name", "category"):
                                    grp_alias = alias
                                    grp_col = c_name
                                    break
                            if not grp_col:
                                grp_alias = alias
                                grp_col = next((c for c, col in tbl.columns.items() if col.is_primary_key or c == "id"), None)
                            if grp_col:
                                break
                    # 2. Check column matching concept (e.g. "category" -> products.category)
                    if not grp_col:
                        for alias in cand_search_aliases:
                            tbl = alias_to_table[alias]
                            for c_name in tbl.columns.keys():
                                c_low = c_name.lower()
                                if g_low in c_low or c_low.startswith(g_low) or c_low.endswith(g_low):
                                    grp_alias = alias
                                    grp_col = c_name
                                    break
                            if grp_col:
                                break

                # 3. Fallback to secondary joined table descriptive column strictly from needed_aliases
                if not grp_col and len(all_table_plans) > 1:
                    cand_aliases = [tp.alias for tp in all_table_plans if tp.alias in needed_aliases and tp.alias != primary_alias]
                    for sec_alias in cand_aliases:
                        sec_tbl = alias_to_table.get(sec_alias)
                        if not sec_tbl:
                            continue
                        for c_name in sec_tbl.columns.keys():
                            if c_name.lower() in ("name", "title", "category"):
                                grp_alias = sec_alias
                                grp_col = c_name
                                break
                        if grp_col:
                            break
                        id_col = next((c for c, col in sec_tbl.columns.items() if col.is_primary_key or c == "id"), None)
                        if id_col:
                            grp_alias = sec_alias
                            grp_col = id_col
                            break

                if grp_alias and grp_col:
                    needed_aliases.add(grp_alias)
                    projections.append(
                        ColumnProjectionPlan(
                            table_alias=grp_alias,
                            column_name=grp_col,
                            aggregation=AggregateFunction.NONE,
                        )
                    )
                    group_by.append(f"{grp_alias}.{grp_col}")
            # Note: For pure scalar aggregates (not grouping_required), NO descriptive columns are added!

        else:
            # Non-aggregate query: project descriptive columns for entity listings / filters ONLY from needed tables
            # Strict Data Minimization & Projection Security Invariant:
            # 1. Intermediate bridge tables project ZERO columns unless explicitly requested.
            # 2. Sensitive attributes (financial, banking, personal PII, contact, location) require explicit semantic intent.
            # 3. Predicate-only usage of an attribute (e.g. "whose salary > 100000") does NOT authorize projection.
            # 4. Identified entities project minimal human identifiers (e.g. employee names, department name, asset name).

            projected_cols_per_alias: Dict[str, Set[str]] = {a: set() for a in needed_aliases}

            for alias in list(needed_aliases):
                if alias not in alias_to_table:
                    continue
                tbl = alias_to_table[alias]
                t_low = tbl.table_name.lower()
                is_bridge = (alias in bridge_aliases)

                for c_name, col in tbl.columns.items():
                    c_low = c_name.lower()

                    # Never project password / secret / hash credentials
                    if any(k in c_low for k in ("password", "secret", "token", "hash", "salt")):
                        continue

                    should_project = False

                    if is_bridge:
                        # Bridge tables project ZERO columns unless specifically asked for
                        if c_low in ("basic_salary", "wage") and is_fin_auth and not any(tp.table_name.lower() == "payroll_contract" for tp in all_table_plans if tp.alias in needed_aliases):
                            should_project = True
                        elif c_low == "department" and "base_department" not in [alias_to_table[a].table_name.lower() for a in needed_aliases]:
                            should_project = True
                    else:
                        # Non-bridge tables: Minimal Human & Domain Identifiers
                        if t_low == "employee_employee":
                            if c_low in ("employee_first_name", "employee_last_name"):
                                should_project = True
                            elif c_low == "badge_id" and any(k in q_lower for k in ("badge", "id", "badge id", "employee id")):
                                should_project = True
                            elif c_low in ("phone", "mobile") and is_phone_auth:
                                should_project = True
                            elif c_low == "email" and is_email_auth:
                                should_project = True
                            elif c_low in ("dob", "date_of_birth") and is_dob_auth:
                                should_project = True
                            elif c_low == "experience" and is_exp_auth and not any(
                                w in q_lower for w in ("expired", "expiring", "expiry", "warranty", "asset")
                            ):
                                should_project = True
                            elif c_low == "gender" and is_gender_auth:
                                should_project = True
                            elif c_low == "marital_status" and is_marital_auth:
                                should_project = True
                            elif c_low == "children" and is_children_auth:
                                should_project = True
                            elif c_low == "qualification" and is_qual_auth:
                                should_project = True
                            elif c_low in ("address", "city", "state", "country") and is_loc_auth:
                                should_project = True
                            elif c_low == "is_active" and "active" in q_lower:
                                should_project = True

                        elif t_low == "base_department":
                            if c_low in ("department", "department_name", "name"):
                                should_project = True

                        elif t_low == "asset_asset":
                            if c_low in ("asset_name", "name"):
                                # Always project asset name when asset intent is present;
                                # also covers "laptop", "device", "computer" queries
                                should_project = True
                            elif c_low == "asset_tracking_id":
                                # Project tracking ID when ID is mentioned OR as a key
                                # identifier for ownership / listing queries
                                if any(k in q_lower for k in (
                                    "id", "asset id", "tracking", "number",
                                    "which asset", "what asset", "asset number"
                                )):
                                    should_project = True
                            elif c_low == "asset_status":
                                if any(k in q_lower for k in (
                                    "status", "state", "condition", "active",
                                    "available", "in use", "assigned"
                                )):
                                    should_project = True
                            elif c_low == "asset_purchase_cost":
                                if any(k in q_lower for k in (
                                    "cost", "price", "how much", "amount",
                                    "worth", "value", "purchase cost", "paid"
                                )):
                                    should_project = True
                            elif c_low == "asset_purchase_date":
                                if any(k in q_lower for k in (
                                    "purchased", "bought", "when was", "purchase date",
                                    "date of purchase", "acquisition"
                                )):
                                    should_project = True
                            elif c_low == "expiry_date":
                                # Project expiry_date for expire/expiring/expired queries
                                if any(k in q_lower for k in (
                                    "expire", "expired", "expiring", "expiry",
                                    "expiration", "soon", "warranty"
                                )):
                                    should_project = True
                            elif c_low == "warranty_date":
                                # Project warranty_date for warranty-related queries
                                if any(k in q_lower for k in (
                                    "warranty", "warrant", "expiry", "expire",
                                    "expired", "expiring"
                                )):
                                    should_project = True
                            elif c_low == "notify_before":
                                if any(k in q_lower for k in (
                                    "expiring", "notify", "soon", "alert", "reminder"
                                )):
                                    should_project = True
                            elif c_low == "owner_id":
                                # Project owner FK when ownership is explicitly asked
                                if any(k in q_lower for k in (
                                    "owner", "owns", "who has", "who holds",
                                    "who currently", "assigned to"
                                )):
                                    should_project = True
                            elif c_low == "vendor_name":
                                if any(k in q_lower for k in (
                                    "vendor", "supplier", "manufacturer", "brand"
                                )):
                                    should_project = True

                        elif t_low == "asset_assetassignment":
                            # Projection for the assignment bridge between assets and employees.
                            # Only expose date / status columns – never the raw FK _id fields.
                            if c_low == "assigned_date":
                                should_project = True
                            elif c_low == "return_date" and any(
                                k in q_lower for k in (
                                    "return", "returned", "return date",
                                    "when returned", "handed back"
                                )
                            ):
                                should_project = True
                            elif c_low == "return_status" and any(
                                k in q_lower for k in (
                                    "return", "returned", "status", "condition"
                                )
                            ):
                                should_project = True
                            elif c_low == "requested_date" and any(
                                k in q_lower for k in (
                                    "requested", "request date", "when requested"
                                )
                            ):
                                should_project = True

                        elif t_low == "payroll_contract":
                            if c_low in ("basic_salary", "wage") and is_fin_auth:
                                should_project = True
                            elif c_low in ("contract_name", "name", "contract_start_date", "start_date"):
                                should_project = True
                            elif c_low == "is_active" and "active" in q_lower:
                                should_project = True

                        elif t_low == "payroll_payslip":
                            if c_low in ("gross_pay", "net_pay", "basic_pay") and is_fin_auth:
                                should_project = True
                            elif c_low == "status" and any(k in q_lower for k in ("status", "paid", "draft", "sent")):
                                should_project = True
                            elif c_low in ("start_date", "end_date", "pay_date"):
                                should_project = True

                        elif t_low == "leave_availableleave":
                            if c_low in ("available_days", "total_days", "assigned_days"):
                                should_project = True
                            elif c_low in ("carryforward_days", "carry_forward_days") and any(k in q_lower for k in ("carry", "forward")):
                                should_project = True

                        elif t_low == "leave_leaverequest":
                            if c_low in ("start_date", "end_date", "status", "requested_days"):
                                should_project = True
                            elif c_low in ("reason", "reject_reason", "description") and any(k in q_lower for k in ("why", "reason")):
                                should_project = True

                        elif t_low == "leave_leavetype":
                            if c_low in ("name", "leave_type"):
                                should_project = True

                        elif t_low == "attendance_attendance":
                            is_in_ask = any(k in q_lower for k in ("check in", "clock in", "checkin", "clockin"))
                            is_out_ask = any(k in q_lower for k in ("check out", "clock out", "checkout", "clockout"))
                            if is_in_ask and not is_out_ask:
                                if c_low in ("attendance_date", "attendance_clock_in"):
                                    should_project = True
                            elif is_out_ask and not is_in_ask:
                                if c_low in ("attendance_date", "attendance_clock_out"):
                                    should_project = True
                            elif c_low in ("attendance_date", "attendance_clock_in", "attendance_clock_out"):
                                should_project = True
                            elif c_low == "attendance_day" and "day" in q_lower:
                                should_project = True
                            elif c_low in ("at_work_second", "attendance_worked_hour") and any(k in q_lower for k in ("hour", "hours", "work", "worked", "working")):
                                should_project = True
                            elif c_low in ("overtime_second", "attendance_overtime") and "overtime" in q_lower:
                                should_project = True

                        elif t_low == "attendance_attendancelatecomeearlyout":
                            if c_low in ("type", "created_at", "modified_time"):
                                should_project = True

                        elif t_low == "project_project":
                            if c_low in ("project_name", "title", "name"):
                                should_project = True

                        elif t_low == "project_task":
                            if c_low in ("task_name", "title", "name"):
                                should_project = True
                            elif c_low == "status" and any(k in q_lower for k in ("status", "state", "progress")):
                                should_project = True

                        elif t_low == "project_timesheet":
                            if c_low in ("timesheet_hours", "hours", "duration"):
                                should_project = True
                            elif c_low in ("timesheet_date", "start_time", "end_time"):
                                should_project = True

                        elif t_low == "payroll_loan":
                            if c_low in ("loan_amount", "amount") and (is_fin_auth or has_loan_intent):
                                should_project = True
                            elif c_low in ("monthly_installment", "installment") and any(k in q_lower for k in ("installment", "monthly")):
                                should_project = True
                            elif c_low == "settled" and any(k in q_lower for k in ("settle", "settled", "paid")):
                                should_project = True

                        elif t_low == "payroll_deduction":
                            if c_low in ("deduction_name", "name", "title"):
                                should_project = True
                            elif c_low in ("amount", "rate") and is_fin_auth:
                                should_project = True

                        elif t_low in ("base_jobposition", "base_jobrole", "base_worktype"):
                            if c_low in ("job_position", "job_role", "work_type", "name", "title"):
                                should_project = True

                        else:
                            # Generic business entity fallback: minimal name/title or primary key
                            if c_low in ("name", "title", "label"):
                                should_project = True
                            elif col.is_primary_key and len(projected_cols_per_alias[alias]) == 0:
                                should_project = True

                    if should_project and c_name not in projected_cols_per_alias[alias]:
                        projections.append(
                            ColumnProjectionPlan(
                                table_alias=alias,
                                column_name=c_name,
                                aggregation=AggregateFunction.NONE,
                            )
                        )
                        projected_cols_per_alias[alias].add(c_name)

            if resolved_entities:
                from .schema_entity_resolver import EntityConfidence
                for r in resolved_entities:
                    if r.entity_type == "COLUMN" and r.resolved_to and r.confidence in (EntityConfidence.HIGH, EntityConfidence.MEDIUM):
                        r_clean = r.resolved_to.lower()
                        r_parts = r_clean.split(".")
                        r_tbl = r_parts[-2] if len(r_parts) >= 2 else ""
                        r_col = r_parts[-1]
                        if r_col in ("password", "secret", "token", "hash", "salt"):
                            continue
                        if (r_col in ("basic_salary", "salary", "wage", "gross_pay", "net_pay", "basic_pay") or "salary" in r_col or "wage" in r_col) and not is_fin_auth:
                            continue

                        # Universal media/binary attachment guard (Blocker 6)
                        MEDIA_KEYWORDS = ("image", "photo", "picture", "avatar", "attachment", "document", "file", "blob")
                        has_media_intent = any(w in q_lower for w in ("image", "photo", "picture", "avatar", "attachment", "document", "file", "download", "view image", "show picture"))
                        if any(m in r_col for m in MEDIA_KEYWORDS) and not has_media_intent:
                            continue

                        # Asset cost authorization guard (Blocker 6)
                        has_cost_intent = any(w in q_lower for w in ("cost", "price", "how much", "amount", "worth", "value", "expensive", "cheap"))
                        if (r_col in ("asset_purchase_cost", "purchase_cost", "cost", "price") or "cost" in r_col or "price" in r_col) and not has_cost_intent:
                            continue

                        # Warranty expiry vs start date guard (Blocker 6)
                        if r_col in ("warranty_date", "warranty_start_date") and any(w in q_lower for w in ("expire", "expired", "expiring", "expiry")):
                            continue

                        if r_col in ("phone", "mobile") and not is_phone_auth:
                            continue
                        if r_col == "email" and not is_email_auth:
                            continue
                        if r_col in ("dob", "date_of_birth") and not is_dob_auth:
                            continue
                        # Q08 fix: 'experience' must not be projected when the intent is about asset
                        # expiry/expiring — the entity resolver false-positively matches 'exp' inside 'expired'.
                        if r_col == "experience" and not is_exp_auth:
                            continue
                        if r_col == "experience" and is_exp_auth and any(
                            w in q_lower for w in ("expired", "expiring", "expiry", "warranty", "asset")
                        ):
                            continue
                        for a in needed_aliases:
                            if a in bridge_aliases:
                                continue
                            if r_col.endswith("_id_id") or (r_col.endswith("_id") and r_col not in ("badge_id", "asset_id")):
                                continue
                            tbl = alias_to_table[a]
                            if tbl.table_name.lower() == r_tbl:
                                for c_name in tbl.columns.keys():
                                    if c_name.lower() == r_col and c_name not in projected_cols_per_alias[a]:
                                        projections.append(
                                            ColumnProjectionPlan(
                                                table_alias=a,
                                                column_name=c_name,
                                                aggregation=AggregateFunction.NONE,
                                            )
                                        )
                                        projected_cols_per_alias[a].add(c_name)

            # Ensure every requested non-bridge entity table has at least one projected column
            for alias in named_aliases:
                if alias in needed_aliases and alias not in bridge_aliases and not projected_cols_per_alias.get(alias):
                    tbl = alias_to_table[alias]
                    pk_col = next((c for c, col in tbl.columns.items() if col.is_primary_key or c == "id"), next(iter(tbl.columns.keys()), "id"))
                    projections.append(
                        ColumnProjectionPlan(
                            table_alias=alias,
                            column_name=pk_col,
                            aggregation=AggregateFunction.NONE,
                        )
                    )
                    projected_cols_per_alias[alias].add(pk_col)

            if not projections and all_table_plans:
                first_alias = primary_alias
                first_tbl = alias_to_table[first_alias]
                disp_col = next((c for c in first_tbl.columns.keys() if c.lower() in ("name", "title", "department", "employee_first_name")), "id")
                projections.append(
                    ColumnProjectionPlan(
                        table_alias=first_alias,
                        column_name=disp_col,
                        aggregation=AggregateFunction.NONE,
                    )
                )

        # 4. Formulate Predicates
        predicates: List[PredicatePlan] = []
        for p in analysis.predicates:
            matched_alias = None
            matched_col = None

            # Schema-Grounded candidate column binding
            if resolved_entities and p.target_concept in ("amount/price", "predicate", "comparison"):
                from .schema_entity_resolver import EntityConfidence
                best_score = -1.0
                for r in resolved_entities:
                    if r.entity_type == "COLUMN" and r.resolved_to and r.confidence != EntityConfidence.UNRESOLVED:
                        r_clean = r.resolved_to.lower()
                        r_parts = r_clean.split(".")
                        r_tbl = r_parts[-2] if len(r_parts) >= 2 else ""
                        r_col = r_parts[-1]

                        # Exclude primary keys and foreign key IDs from amount/price comparisons
                        if p.target_concept == "amount/price":
                            if r_col == "id" or r_col.endswith("_id") or r_col.endswith("_id_id"):
                                continue

                        for a, tbl in alias_to_table.items():
                            if tbl.table_name.lower() == r_tbl:
                                for c_name, col_obj in tbl.columns.items():
                                    if c_name.lower() == r_col:
                                        if p.target_concept == "amount/price":
                                            if c_name.lower() == "id" or c_name.lower().endswith("_id") or c_name.lower().endswith("_id_id"):
                                                continue
                                            is_amount_col = (
                                                col_obj.data_type in (ColumnDataType.DECIMAL, ColumnDataType.FLOAT, ColumnDataType.INTEGER)
                                                and any(m in c_name.lower() for m in ("salary", "wage", "pay", "amount", "price", "budget", "cost", "total", "rate", "fee"))
                                            )
                                            if is_amount_col and r.combined_score > best_score:
                                                best_score = r.combined_score
                                                matched_alias = a
                                                matched_col = c_name
                                        else:
                                            is_num_or_date = (
                                                col_obj.data_type in (ColumnDataType.INTEGER, ColumnDataType.DECIMAL, ColumnDataType.FLOAT, ColumnDataType.DATE, ColumnDataType.TIMESTAMP)
                                                or (col_obj.raw_data_type and any(k in col_obj.raw_data_type.lower() for k in ("int", "num", "dec", "float", "double", "money", "date", "time")))
                                            )
                                            if is_num_or_date and r.combined_score > best_score:
                                                best_score = r.combined_score
                                                matched_alias = a
                                                matched_col = c_name

            if not matched_col:
                if p.target_concept == "time_of_day":
                    best_time_alias = None
                    best_time_col = None
                    best_time_score = -1.0
                    is_exit = any(w in q_lower for w in ("out", "left", "leave", "depart", "exit", "departure"))
                    is_entry = any(w in q_lower for w in ("in", "enter", "entered", "arrival", "arrived", "punch", "clock in", "swipe in", "swiped in"))
                    for a, tbl in alias_to_table.items():
                        for c_name, col in tbl.columns.items():
                            c_lower = c_name.lower()
                            score = 0.0
                            if col.data_type == ColumnDataType.TIME:
                                score += 50.0
                            elif col.data_type in (ColumnDataType.TIMESTAMP, ColumnDataType.TIMESTAMPTZ):
                                score += 30.0
                            elif col.data_type == ColumnDataType.DATE:
                                score -= 50.0

                            if is_exit:
                                if any(kw in c_lower for kw in ("clock_out", "out_time", "exit_time", "departure")):
                                    score += 60.0
                                elif "out" in c_lower and "timeout" not in c_lower:
                                    score += 40.0
                            elif is_entry:
                                if any(kw in c_lower for kw in ("clock_in", "in_time", "entry_time", "arrival_time", "entered_time")):
                                    score += 60.0
                                elif "in" in c_lower and "shift" not in c_lower:
                                    score += 40.0
                            else:
                                if any(kw in c_lower for kw in ("clock_in", "clock_out", "start_time", "end_time", "time")):
                                    score += 30.0

                            if any(ev in tbl.table_name.lower() for ev in ("attendance", "visit", "event", "punch", "log", "access", "entry", "shift")):
                                score += 20.0

                            if score > best_time_score and score > 20.0:
                                best_time_score = score
                                best_time_alias = a
                                best_time_col = c_name
                    if best_time_alias and best_time_col:
                        matched_alias = best_time_alias
                        matched_col = best_time_col
                elif p.target_concept in ("date", "relative_date"):
                    best_date_score = 0.0
                    best_date_alias = None
                    best_date_col = None
                    for a, tbl in alias_to_table.items():
                        for c_name, col in tbl.columns.items():
                            c_lower = c_name.lower()
                            is_date_col = col.data_type in (
                                ColumnDataType.DATE,
                                ColumnDataType.TIMESTAMP,
                                ColumnDataType.TIMESTAMPTZ,
                            )
                            if c_lower == "dob" or "birth" in c_lower:
                                continue
                            if is_date_col and not c_lower.endswith(("_id", "_id_id")):
                                score = 10.0
                                if a in needed_aliases:
                                    score += 60.0
                                if "attendance_date" in c_lower:
                                    score += 55.0
                                elif c_lower == "date":
                                    score += 45.0
                                elif "clock_in_date" in c_lower or "clock_out_date" in c_lower:
                                    score += 45.0
                                elif "start_date" in c_lower or "end_date" in c_lower:
                                    score += 40.0
                                elif "created" in c_lower or "updated" in c_lower:
                                    score -= 5.0
                                if any(ev in tbl.table_name.lower() for ev in ("attendance", "leave", "shift", "event", "punch", "work")):
                                    score += 30.0
                                if score > best_date_score:
                                    best_date_score = score
                                    best_date_alias = a
                                    best_date_col = c_name
                    if best_date_alias and best_date_col:
                        matched_alias = best_date_alias
                        matched_col = best_date_col
                        if p.target_concept == "relative_date":
                            if p.value in ("today", "this morning"):
                                p.value = "CURRENT_DATE"
                                p.operator = "="
                            elif p.value == "yesterday":
                                p.value = "CURRENT_DATE - INTERVAL '1 day'"
                                p.operator = "="
                            elif p.value == "this_week":
                                p.value = "DATE_TRUNC('week', CURRENT_DATE)"
                                p.operator = ">="
                            elif p.value == "last_week":
                                p.value = "DATE_TRUNC('week', CURRENT_DATE - INTERVAL '1 week')"
                                p.operator = ">="
                            elif p.value == "this_month":
                                p.value = "DATE_TRUNC('month', CURRENT_DATE)"
                                p.operator = ">="
                            elif p.value == "friday":
                                p.value = 5
                                p.operator = "EXTRACT_DOW"
                elif p.target_concept in ("date_range_start", "date_range_end"):
                    best_date_score = 0.0
                    best_date_alias = None
                    best_date_col = None
                    for a, tbl in alias_to_table.items():
                        for c_name, col in tbl.columns.items():
                            c_lower = c_name.lower()
                            is_date_col = col.data_type in (ColumnDataType.DATE, ColumnDataType.TIMESTAMP, ColumnDataType.TIMESTAMPTZ)
                            if c_lower == "dob" or "birth" in c_lower:
                                continue
                            if is_date_col and not c_lower.endswith(("_id", "_id_id")):
                                score = 10.0
                                if a in needed_aliases:
                                    score += 60.0
                                if "attendance_date" in c_lower:
                                    score += 55.0
                                elif c_lower == "date":
                                    score += 45.0
                                elif "start_date" in c_lower or "end_date" in c_lower:
                                    score += 40.0
                                elif "created" in c_lower or "updated" in c_lower:
                                    score -= 5.0
                                if score > best_date_score:
                                    best_date_score = score
                                    best_date_alias = a
                                    best_date_col = c_name
                    if best_date_alias and best_date_col:
                        matched_alias = best_date_alias
                        matched_col = best_date_col
                else:
                    for alias, tbl in alias_to_table.items():
                        for c_name, col in tbl.columns.items():
                            c_lower = c_name.lower()
                            if p.target_concept == "amount/price" and (
                                c_lower in {"salary", "budget", "price", "amount", "total_amount", "unit_price", "basic_salary", "wage", "gross_pay", "net_pay"}
                                or "salary" in c_lower
                                or "wage" in c_lower
                                or c_lower.endswith("_pay")
                                or c_lower.endswith("_amount")
                            ):
                                matched_alias = alias
                                matched_col = c_name
                                break
                            elif p.target_concept == "status" and c_lower in {"status", "payment_status"}:
                                matched_alias = alias
                                matched_col = c_name
                                break
                            elif p.target_concept == "order_id" and (c_lower == "id" and tbl.table_name == "orders" or c_lower == "order_id"):
                                matched_alias = alias
                                matched_col = c_name
                                break
                            elif p.target_concept in ("product_name", "name", "entity_name") and c_lower in ("name", "full_name", "title", "product_name"):
                                matched_alias = alias
                                matched_col = c_name
                                break
                            elif p.target_concept == "existence" and col.is_primary_key:
                                matched_alias = alias
                                matched_col = c_name
                                break
                            elif p.target_concept == "late_status":
                                if "latecome" in tbl.table_name.lower() and c_lower == "type":
                                    matched_alias = alias
                                    matched_col = c_name
                                    p.value = "late_come"
                                    break
                            elif p.target_concept == "early_status":
                                if "latecome" in tbl.table_name.lower() and c_lower == "type":
                                    matched_alias = alias
                                    matched_col = c_name
                                    p.value = "early_out"
                                    break
                            elif p.target_concept == "expiring_soon":
                                if "asset" in tbl.table_name.lower() and c_lower == "expiry_date":
                                    matched_alias = alias
                                    matched_col = c_name
                                    p.operator = "<="
                                    p.value = f"CURRENT_DATE + (COALESCE({alias}.notify_before, 30) * INTERVAL '1 day')"
                                    predicates.append(
                                        PredicatePlan(
                                            table_alias=alias,
                                            column_name=c_name,
                                            operator=">=",
                                            value="CURRENT_DATE",
                                            logical_operator="AND",
                                        )
                                    )
                                    break
                            elif p.target_concept == "expired_asset":
                                if "asset" in tbl.table_name.lower() and c_lower == "expiry_date":
                                    matched_alias = alias
                                    matched_col = c_name
                                    p.operator = "<"
                                    p.value = "CURRENT_DATE"
                                    break
                            elif p.target_concept == "asset_id":
                                if "asset" in tbl.table_name.lower() and c_lower in ("id", "asset_tracking_id"):
                                    matched_alias = alias
                                    matched_col = c_name
                                    break
                            elif p.target_concept == "asset_name":
                                if "asset" in tbl.table_name.lower() and c_lower == "asset_name":
                                    matched_alias = alias
                                    matched_col = c_name
                                    break
                            elif p.target_concept == "absent_today":
                                if "leave" in tbl.table_name.lower() and c_lower == "start_date":
                                    matched_alias = alias
                                    matched_col = c_name
                                    p.operator = "<="
                                    p.value = "CURRENT_DATE"
                                    end_col = next((c for c in tbl.columns if c.lower() == "end_date"), "end_date")
                                    predicates.append(
                                        PredicatePlan(
                                            table_alias=alias,
                                            column_name=end_col,
                                            operator=">=",
                                            value="CURRENT_DATE",
                                            logical_operator="AND",
                                        )
                                    )
                                    break
                            elif p.target_concept == "overtime":
                                if "attendance" in tbl.table_name.lower() and c_lower in ("overtime_second", "attendance_overtime"):
                                    matched_alias = alias
                                    matched_col = c_name
                                    if c_lower == "overtime_second":
                                        p.operator = ">"
                                        p.value = 0
                                    else:
                                        p.operator = "!="
                                        p.value = "00:00"
                                    break
                            elif p.target_concept == "leave_status":
                                if "leave" in tbl.table_name.lower() and c_lower == "status":
                                    matched_alias = alias
                                    matched_col = c_name
                                    p.value = "approved"
                                    break
                            elif p.target_concept == "shift_early":
                                if "shift" in tbl.table_name.lower() and c_lower == "start_time":
                                    matched_alias = alias
                                    matched_col = c_name
                                    p.operator = "IS NOT NULL"
                                    p.value = None
                                    break
                            elif p.target_concept == "department":
                                if "department" in tbl.table_name.lower() and c_lower in ("department", "department_name", "name"):
                                    matched_alias = alias
                                    matched_col = c_name
                                    break
                            elif p.target_concept == "job_position":
                                if ("jobposition" in tbl.table_name.lower() or "position" in tbl.table_name.lower()) and c_lower in ("job_position", "position", "title", "name"):
                                    matched_alias = alias
                                    matched_col = c_name
                                    break
                            elif p.target_concept == "rating":
                                if any(m in tbl.table_name.lower() for m in ("performance", "review", "feedback", "rating")) and c_lower in ("rating", "score", "performance_rating"):
                                    matched_alias = alias
                                    matched_col = c_name
                                    break
                        if matched_col:
                            break

            if not matched_col and p.target_concept == "department" and canonical_schema:
                for s_name, s_val in canonical_schema.schemas.items():
                    for t_name, t_obj in s_val.tables.items():
                        if t_name.lower() in ("base_department", "department", "departments"):
                            dept_alias = None
                            for a, tbl in alias_to_table.items():
                                if tbl.table_name.lower() == t_name.lower():
                                    dept_alias = a
                                    break
                            if not dept_alias:
                                dept_alias = cls._generate_alias(t_name, used_aliases)
                                used_aliases.add(dept_alias)
                                alias_to_table[dept_alias] = t_obj
                                all_table_plans.append(TablePlan(schema_name=t_obj.schema_name, table_name=t_obj.table_name, alias=dept_alias, role="JOIN_TARGET"))
                            matched_alias = dept_alias
                            matched_col = "department" if "department" in t_obj.columns else next((c for c in t_obj.columns if "name" in c), "name")
                            break
                    if matched_alias:
                        break

            if not matched_col and p.target_concept == "job_position" and canonical_schema:
                for s_name, s_val in canonical_schema.schemas.items():
                    for t_name, t_obj in s_val.tables.items():
                        if t_name.lower() in ("base_jobposition", "jobposition", "job_position"):
                            pos_alias = None
                            for a, tbl in alias_to_table.items():
                                if tbl.table_name.lower() == t_name.lower():
                                    pos_alias = a
                                    break
                            if not pos_alias:
                                pos_alias = cls._generate_alias(t_name, used_aliases)
                                used_aliases.add(pos_alias)
                                alias_to_table[pos_alias] = t_obj
                                all_table_plans.append(TablePlan(schema_name=t_obj.schema_name, table_name=t_obj.table_name, alias=pos_alias, role="JOIN_TARGET"))
                            matched_alias = pos_alias
                            matched_col = "job_position" if "job_position" in t_obj.columns else next((c for c in t_obj.columns if "position" in c or "title" in c), "title")
                            break
                    if matched_alias:
                        break

            if matched_alias and matched_col:
                needed_aliases.add(matched_alias)
                predicates.append(
                    PredicatePlan(
                        table_alias=matched_alias,
                        column_name=matched_col,
                        operator=p.operator,
                        value=p.value,
                        logical_operator="AND",
                    )
                )
                if not (analysis.aggregations and not analysis.grouping_required):
                    c_low = matched_col.lower()
                    is_sensitive_pred = (
                        ((c_low in SENSITIVE_FINANCIAL or any(s in c_low for s in ("salary", "wage"))) and not is_fin_auth)
                        or (c_low in SENSITIVE_CONTACT and not is_phone_auth)
                        or (c_low in SENSITIVE_PII and not (is_dob_auth if c_low in ("dob", "date_of_birth", "age") else is_pii_auth))
                        or (c_low in SENSITIVE_LOCATION and not is_loc_auth)
                        or (c_low in SENSITIVE_BANKING and not is_bank_auth)
                        or any(k in c_low for k in SENSITIVE_CREDENTIALS)
                        or matched_alias in bridge_aliases
                    )
                    if not is_sensitive_pred:
                        if not any(proj.table_alias == matched_alias and proj.column_name == matched_col for proj in projections):
                            projections.append(
                                ColumnProjectionPlan(
                                    table_alias=matched_alias,
                                    column_name=matched_col,
                                    aggregation=AggregateFunction.NONE,
                                )
                            )

        # Inject mandatory metric filter condition if present (e.g. status = 'active')
        if semantic_context and getattr(semantic_context, "resolved_metric", None):
            metric = semantic_context.resolved_metric
            if metric.filter_condition and "=" in metric.filter_condition:
                m_parts = metric.filter_condition.split("=")
                m_col = m_parts[0].strip()
                m_val = m_parts[1].strip().strip("'\"")
                for alias, tbl in alias_to_table.items():
                    if m_col.lower() in {c.lower() for c in tbl.columns.keys()}:
                        if not any(pred.table_alias == alias and pred.column_name.lower() == m_col.lower() for pred in predicates):
                            needed_aliases.add(alias)
                            predicates.append(
                                PredicatePlan(
                                    table_alias=alias,
                                    column_name=m_col,
                                    operator="=",
                                    value=m_val,
                                    logical_operator="AND",
                                )
                            )
                        break

        # Inject applicable business rule conditions
        if semantic_context and getattr(semantic_context, "applicable_rules", None):
            for rule in semantic_context.applicable_rules:
                if rule.condition_expression and "=" in rule.condition_expression:
                    r_parts = rule.condition_expression.split("=")
                    r_col = r_parts[0].strip()
                    r_val = r_parts[1].strip().strip("'\"")
                    for alias, tbl in alias_to_table.items():
                        if r_col.lower() in {c.lower() for c in tbl.columns.keys()}:
                            if not any(pred.table_alias == alias and pred.column_name.lower() == r_col.lower() for pred in predicates):
                                needed_aliases.add(alias)
                                predicates.append(
                                    PredicatePlan(
                                        table_alias=alias,
                                        column_name=r_col,
                                        operator="=",
                                        value=r_val,
                                        logical_operator="AND",
                                    )
                                )
                            break

        # Inject entity value resolution: check for literal value mentions (e.g. employee names like "Kannan")
        if user_query:
            from .entity_value_resolver import EntityValueResolver
            literals = EntityValueResolver.extract_literal_candidates(user_query, canonical_schema=canonical_schema)
            if literals:
                for lit in literals:
                    # Check if already bound to an existing predicate
                    if any(pred.value == lit or pred.value == f"%{lit}%" for pred in predicates):
                        continue
                    # Skip department or job position terms from being bound as employee first name
                    DEPT_OR_POSITION_TERMS = {
                        "engineering", "sales", "marketing", "finance", "development", "operations",
                        "support", "management", "hr", "software engineer", "manager", "team lead", "lead"
                    }
                    if lit.lower() in DEPT_OR_POSITION_TERMS or any(term in lit.lower() for term in ("engineer", "developer", "manager", "director", "department", "position")):
                        continue
                    # Search across candidate tables for name columns (preferring tables with employee_first_name or first_name)
                    best_lit_alias = None
                    best_lit_col = None
                    best_lit_score = -1.0
                    ADMIN_TABLES = {"auth_user", "auth_group", "django_content_type", "base_company", "django_migrations", "django_session"}
                    for a, tbl in alias_to_table.items():
                        t_name_low = tbl.table_name.lower()
                        if t_name_low in ADMIN_TABLES or t_name_low.startswith(("auth_", "django_")):
                            continue
                        if has_asset_intent and t_name_low not in ALLOWED_ASSET_TABLES:
                            continue
                        if has_project_intent and t_name_low not in ALLOWED_PROJECT_TABLES:
                            continue
                        if has_leave_intent and t_name_low not in ALLOWED_LEAVE_TABLES:
                            continue
                        if has_loan_intent and t_name_low not in ALLOWED_LOAN_TABLES:
                            continue
                        if has_deduction_intent and t_name_low not in ALLOWED_DED_TABLES:
                            continue
                        for c_name, c_obj in tbl.columns.items():
                            c_low = c_name.lower()
                            if c_low.endswith(("_id", "_id_id")):
                                continue
                            score = 0.0
                            if "first_name" in c_low:
                                score += 50.0
                            elif "last_name" in c_low:
                                score += 40.0
                            elif c_low.endswith("name") or "name" in c_low:
                                score += 30.0
                            elif "title" in c_low:
                                score += 15.0

                            if a == primary_alias:
                                score += 20.0

                            if score > best_lit_score and score > 0.0:
                                best_lit_score = score
                                best_lit_alias = a
                                best_lit_col = c_name

                    if best_lit_alias and best_lit_col:
                        needed_aliases.add(best_lit_alias)
                        predicates.append(
                            PredicatePlan(
                                table_alias=best_lit_alias,
                                column_name=best_lit_col,
                                operator="ILIKE",
                                value=f"%{lit}%",
                                logical_operator="AND",
                            )
                        )
                        if not (analysis.aggregations and not analysis.grouping_required):
                            c_low = best_lit_col.lower()
                            is_sensitive_lit = (
                                ((c_low in SENSITIVE_FINANCIAL or any(s in c_low for s in ("salary", "wage"))) and not is_fin_auth)
                                or (c_low in SENSITIVE_CONTACT and not is_phone_auth)
                                or (c_low in SENSITIVE_PII and not (is_dob_auth if c_low in ("dob", "date_of_birth", "age") else is_pii_auth))
                                or (c_low in SENSITIVE_LOCATION and not is_loc_auth)
                                or (c_low in SENSITIVE_BANKING and not is_bank_auth)
                                or any(k in c_low for k in SENSITIVE_CREDENTIALS)
                                or best_lit_alias in bridge_aliases
                            )
                            if not is_sensitive_lit:
                                if not any(
                                    proj.table_alias == best_lit_alias and proj.column_name == best_lit_col
                                    for proj in projections
                                ):
                                    projections.append(
                                        ColumnProjectionPlan(
                                            table_alias=best_lit_alias,
                                            column_name=best_lit_col,
                                            aggregation=AggregateFunction.NONE,
                                        )
                                    )

        # Enforce strict domain boundaries on needed_aliases before graph path resolution
        if has_asset_intent:
            if any(w in q_lower for w in ("owner", "owns", "owned", "ownership")):
                needed_aliases = {a for a in needed_aliases if alias_to_table[a].table_name.lower() in ("asset_asset", "employee_employee")}
            elif not any(w in q_lower for w in ("assigned", "assign", "assignment", "laptop", "engineering", "department", "staff")) and not anchor_alias and not literals:
                needed_aliases = {a for a in needed_aliases if alias_to_table[a].table_name.lower() == "asset_asset"}
            else:
                needed_aliases = {a for a in needed_aliases if alias_to_table[a].table_name.lower() in ALLOWED_ASSET_TABLES}
        elif has_att_intent:
            needed_aliases = {a for a in needed_aliases if alias_to_table[a].table_name.lower() in ALLOWED_ATTENDANCE_TABLES}
            if any(w in q_lower for w in ("early out", "leave early", "early leave", "late come", "late arrival", "late arrivals")) or ("late" in q_tokens and "latest" not in q_tokens) or ("early" in q_tokens):
                if any(alias_to_table[a].table_name.lower() == "attendance_attendancelatecomeearlyout" for a in needed_aliases):
                    needed_aliases = {a for a in needed_aliases if alias_to_table[a].table_name.lower() in ("attendance_attendancelatecomeearlyout", "employee_employee")}
            elif any(w in q_lower for w in ("absent", "absenteeism")):
                needed_aliases = {a for a in needed_aliases if alias_to_table[a].table_name.lower() in ("leave_leaverequest", "leave_leavetype", "employee_employee", "base_department", "employee_employeeworkinformation")}

        # Ensure all tables in needed_aliases are connected to primary_alias via SchemaGraph
        if len(needed_aliases) > 1:
            graph = SchemaGraph.from_database_schema(canonical_schema)
            primary_tbl_name = alias_to_table[primary_alias].table_name

            forbidden_hops = set()
            if has_asset_intent and not any(w in q_lower for w in ("owner", "owns", "owned", "ownership")):
                forbidden_hops.add(("asset_asset", "employee_employee"))
                forbidden_hops.add(("employee_employee", "asset_asset"))

            allowed_for_path = {alias_to_table[a].table_name.lower() for a in needed_aliases}
            for alias in list(needed_aliases):
                if alias == primary_alias:
                    continue
                tgt_tbl_name = alias_to_table[alias].table_name
                path = graph.find_shortest_path(
                    primary_tbl_name,
                    tgt_tbl_name,
                    max_hops=4,
                    allowed_tables=allowed_for_path,
                    forbidden_hops=forbidden_hops,
                )
                if not path:
                    fallback_allowed = (
                        ALLOWED_ASSET_TABLES if has_asset_intent
                        else (ALLOWED_ATTENDANCE_TABLES if has_att_intent
                        else (ALLOWED_PROJECT_TABLES if has_project_intent
                        else (ALLOWED_LEAVE_TABLES if has_leave_intent
                        else (ALLOWED_LOAN_TABLES if has_loan_intent
                        else (ALLOWED_DED_TABLES if has_deduction_intent else None)))))
                    )
                    path = graph.find_shortest_path(
                        primary_tbl_name,
                        tgt_tbl_name,
                        max_hops=4,
                        allowed_tables=fallback_allowed,
                        forbidden_hops=forbidden_hops,
                    )
                if path and len(path) > 1:
                    for step_idx in range(len(path) - 1):
                        u_name = path[step_idx]
                        v_name = path[step_idx + 1]

                        u_alias = None
                        for a, t in alias_to_table.items():
                            if t.table_name.lower() == u_name.lower() or f"{t.schema_name}.{t.table_name}".lower() == u_name.lower():
                                u_alias = a
                                break
                        if not u_alias and canonical_schema:
                            u_clean = u_name.split(".")[-1]
                            for s_name, s_val in canonical_schema.schemas.items():
                                if u_clean in s_val.tables:
                                    t_obj = s_val.tables[u_clean]
                                    u_alias = cls._generate_alias(u_clean, used_aliases)
                                    used_aliases.add(u_alias)
                                    alias_to_table[u_alias] = t_obj
                                    all_table_plans.append(TablePlan(schema_name=t_obj.schema_name, table_name=t_obj.table_name, alias=u_alias, role="BRIDGE"))
                                    break

                        v_alias = None
                        for a, t in alias_to_table.items():
                            if t.table_name.lower() == v_name.lower() or f"{t.schema_name}.{t.table_name}".lower() == v_name.lower():
                                v_alias = a
                                break
                        if not v_alias and canonical_schema:
                            v_clean = v_name.split(".")[-1]
                            for s_name, s_val in canonical_schema.schemas.items():
                                if v_clean in s_val.tables:
                                    t_obj = s_val.tables[v_clean]
                                    v_alias = cls._generate_alias(v_clean, used_aliases)
                                    used_aliases.add(v_alias)
                                    alias_to_table[v_alias] = t_obj
                                    all_table_plans.append(TablePlan(schema_name=t_obj.schema_name, table_name=t_obj.table_name, alias=v_alias, role="BRIDGE"))
                                    break

                        if u_alias and v_alias:
                            needed_aliases.add(u_alias)
                            needed_aliases.add(v_alias)
                            candidate_matches = []
                            for neighbor, rel in graph.get_neighbors(u_name):
                                if neighbor == v_name or neighbor.split(".")[-1] == v_name.split(".")[-1]:
                                    src_tbl = rel.source_table.lower()
                                    tgt_tbl = rel.target_table.lower()
                                    u_clean = u_name.split(".")[-1].lower()

                                    if u_clean == src_tbl:
                                        u_col = rel.source_columns[0] if rel.source_columns else "id"
                                        v_col = rel.target_columns[0] if rel.target_columns else "id"
                                        fk_col = u_col
                                        ref_tbl = tgt_tbl
                                    else:
                                        u_col = rel.target_columns[0] if rel.target_columns else "id"
                                        v_col = rel.source_columns[0] if rel.source_columns else "id"
                                        fk_col = v_col
                                        ref_tbl = src_tbl

                                    score = 10.0
                                    if fk_col == "assigned_to_employee_id_id" and "employee" in ref_tbl:
                                        score += 150.0
                                    elif fk_col in ("employee_id_id", "employee_id") and "employee" in ref_tbl:
                                        score += 100.0
                                    elif fk_col == "assigned_by_employee_id_id":
                                        # In asset queries we always want the RECIPIENT of the asset,
                                        # not who assigned it.  Give a very strong penalty so this
                                        # FK is never selected when assigned_to_employee_id_id is available.
                                        score -= 999.0 if has_asset_intent else 50.0
                                    elif fk_col == "owner_id" and has_asset_intent and "owner" not in q_lower:
                                        score -= 100.0
                                    elif fk_col in ("asset_id_id", "asset_id") and "asset" in ref_tbl:
                                        score += 100.0
                                    elif fk_col in ("project_id", "project_id_id") and "project" in ref_tbl:
                                        score += 100.0
                                    elif fk_col in ("task_id", "task_id_id") and "task" in ref_tbl:
                                        score += 100.0
                                    elif fk_col in ("leave_type_id_id", "leave_type_id") and "leave" in ref_tbl:
                                        score += 100.0
                                    elif fk_col.startswith("candidate_id") and "candidate" in ref_tbl:
                                        score += 90.0
                                    elif fk_col.startswith("department_id") and "department" in ref_tbl:
                                        score += 100.0
                                    elif fk_col.startswith("job_position_id") and "position" in ref_tbl:
                                        score += 90.0
                                    elif fk_col.startswith("user_id") and "user" in ref_tbl:
                                        score += 80.0
                                    elif fk_col in ("created_by_id", "modified_by_id", "updated_by_id", "deleted_by_id"):
                                        if any(w in q_lower for w in ("created by", "creator", "modified by", "modifier")):
                                            score += 70.0
                                        else:
                                            score -= 50.0  # Strong penalty against audit author
                                    elif fk_col in ("manager_id_id", "manager_id", "approved_by_id"):
                                        if any(w in q_lower for w in ("manager", "report", "head", "lead", "approv")):
                                            score += 80.0
                                        else:
                                            score += 5.0

                                    candidate_matches.append((score, u_col, v_col, rel))

                            if candidate_matches:
                                candidate_matches.sort(key=lambda x: x[0], reverse=True)
                                _, best_u_col, best_v_col, best_rel = candidate_matches[0]
                                existing_jp = None
                                for jp in all_join_plans:
                                    if (jp.source_table_alias == u_alias and jp.target_table_alias == v_alias) or (jp.source_table_alias == v_alias and jp.target_table_alias == u_alias):
                                        existing_jp = jp
                                        break
                                if existing_jp:
                                    existing_jp.source_table_alias = u_alias
                                    existing_jp.source_column = best_u_col
                                    existing_jp.target_table_alias = v_alias
                                    existing_jp.target_column = best_v_col
                                    existing_jp.relationship_name = best_rel.relationship_type.value if hasattr(best_rel.relationship_type, "value") else str(best_rel.relationship_type)
                                else:
                                    all_join_plans.append(
                                        JoinPlan(
                                            source_table_alias=u_alias,
                                            source_column=best_u_col,
                                            target_table_alias=v_alias,
                                            target_column=best_v_col,
                                            join_type=JoinType.INNER,
                                            relationship_name=best_rel.relationship_type.value if hasattr(best_rel.relationship_type, "value") else str(best_rel.relationship_type),
                                        )
                                    )

        # Re-enforce domain boundary on needed_aliases after path resolution
        if has_asset_intent:
            if any(w in q_lower for w in ("owner", "owns", "owned", "ownership")):
                needed_aliases = {a for a in needed_aliases if alias_to_table[a].table_name.lower() in ("asset_asset", "employee_employee")}
            elif not any(w in q_lower for w in ("assigned", "assign", "assignment", "laptop", "engineering", "department", "staff")) and not anchor_alias and not literals:
                needed_aliases = {a for a in needed_aliases if alias_to_table[a].table_name.lower() == "asset_asset"}
            else:
                needed_aliases = {a for a in needed_aliases if alias_to_table[a].table_name.lower() in ALLOWED_ASSET_TABLES}
        elif has_att_intent:
            needed_aliases = {a for a in needed_aliases if alias_to_table[a].table_name.lower() in ALLOWED_ATTENDANCE_TABLES}
            if any(w in q_lower for w in ("early out", "leave early", "early leave", "late come", "late arrival", "late arrivals")) or ("late" in q_tokens and "latest" not in q_tokens) or ("early" in q_tokens):
                if any(alias_to_table[a].table_name.lower() == "attendance_attendancelatecomeearlyout" for a in needed_aliases):
                    needed_aliases = {a for a in needed_aliases if alias_to_table[a].table_name.lower() in ("attendance_attendancelatecomeearlyout", "employee_employee")}
            elif any(w in q_lower for w in ("absent", "absenteeism")):
                needed_aliases = {a for a in needed_aliases if alias_to_table[a].table_name.lower() in ("leave_leaverequest", "leave_leavetype", "employee_employee", "base_department", "employee_employeeworkinformation")}

        # Construct final minimal table_plans with primary table first
        table_plans = [tp for tp in all_table_plans if tp.alias in needed_aliases]
        table_plans.sort(key=lambda tp: 0 if tp.alias == primary_alias else 1)
        for idx, tp in enumerate(table_plans):
            tp.role = "PRIMARY" if idx == 0 else "JOIN_TARGET"
        join_plans = [
            jp for jp in all_join_plans
            if jp.source_table_alias in needed_aliases and jp.target_table_alias in needed_aliases
        ]

        # ── Asset join correction pass ────────────────────────────────────────
        # In any asset-intent query we always want to join employee_employee via
        # assigned_to_employee_id_id (who HAS the asset), never via
        # assigned_by_employee_id_id (who ASSIGNED the asset).
        # This pass runs after all join-building phases so it is the final word.
        if has_asset_intent:
            for jp in join_plans:
                src_tbl = alias_to_table.get(jp.source_table_alias)
                tgt_tbl = alias_to_table.get(jp.target_table_alias)
                if src_tbl and tgt_tbl:
                    # Case A: source=asset_assetassignment, target=employee_employee
                    if (src_tbl.table_name.lower() == "asset_assetassignment"
                            and tgt_tbl.table_name.lower() == "employee_employee"):
                        if jp.source_column == "assigned_by_employee_id_id":
                            jp.source_column = "assigned_to_employee_id_id"
                    # Case B: source=employee_employee, target=asset_assetassignment
                    elif (src_tbl.table_name.lower() == "employee_employee"
                            and tgt_tbl.table_name.lower() == "asset_assetassignment"):
                        if jp.target_column == "assigned_by_employee_id_id":
                            jp.target_column = "assigned_to_employee_id_id"

        # Cartesian product defense: prune any table that is not connected to primary_alias via join_plans
        if len(table_plans) > 1:
            connected_aliases = {primary_alias}
            changed = True
            while changed:
                changed = False
                for jp in join_plans:
                    if jp.source_table_alias in connected_aliases and jp.target_table_alias not in connected_aliases:
                        connected_aliases.add(jp.target_table_alias)
                        changed = True
                    elif jp.target_table_alias in connected_aliases and jp.source_table_alias not in connected_aliases:
                        connected_aliases.add(jp.source_table_alias)
                        changed = True

            table_plans = [tp for tp in table_plans if tp.alias in connected_aliases]
            join_plans = [
                jp for jp in join_plans
                if jp.source_table_alias in connected_aliases and jp.target_table_alias in connected_aliases
            ]
            projections = [p for p in projections if p.table_alias in connected_aliases]
            predicates = [p for p in predicates if p.table_alias in connected_aliases]

        # 5. Formulate Order By
        order_by: List[OrderByPlan] = []

        if analysis.ranking:
            # Rank by aggregated column if present, otherwise metric column
            rank_target = None
            for proj in projections:
                if proj.aggregation != AggregateFunction.NONE:
                    rank_target = proj.output_alias or f"{proj.table_alias}.{proj.column_name}"
                    break
            if not rank_target:
                for proj in projections:
                    if proj.column_name in {"salary", "budget", "total_amount", "amount", "price", "unit_price", "created_at"}:
                        rank_target = f"{proj.table_alias}.{proj.column_name}"
                        break
            if not rank_target and projections:
                rank_target = f"{projections[0].table_alias}.{projections[0].column_name}"

            if rank_target:
                order_by.append(
                    OrderByPlan(
                        expression=rank_target,
                        direction=analysis.ranking.direction,
                    )
                )

        # 6. Formulate Limit
        limit = analysis.ranking.limit if (analysis.ranking and analysis.ranking.limit) else default_limit
        if limit is not None and limit > 1000:
            limit = 1000

        # Cardinality, Relationship Semantics & Fail-Closed Security Guard (Phase 6.5)
        active_table_aliases = {tp.alias for tp in table_plans}
        predicates, order_by, limit, projections = cls._apply_cardinality_and_relationship_guard(
            primary_alias=primary_alias,
            alias_to_table=alias_to_table,
            needed_aliases=active_table_aliases,
            user_query=user_query,
            analysis=analysis,
            predicates=predicates,
            order_by=order_by,
            limit=limit,
            projections=projections,
            semantic_context=semantic_context,
        )
        active_table_aliases = {tp.alias for tp in table_plans}
        predicates = [p for p in predicates if p.table_alias in active_table_aliases]
        projections = [p for p in projections if p.table_alias in active_table_aliases]
        group_by = [g for g in group_by if g.split(".")[0] in active_table_aliases]
        order_by = [o for o in order_by if getattr(o, "table_alias", None) in (None, "") or o.table_alias in active_table_aliases]

        # Deduplicate predicates while preserving order
        seen_pred = set()
        dedup_predicates = []
        for p in predicates:
            key = (p.table_alias, p.column_name, p.operator, str(p.value))
            if key not in seen_pred:
                seen_pred.add(key)
                dedup_predicates.append(p)
        predicates = dedup_predicates

        # Deduplicate group_by while preserving order
        seen_gb = set()
        dedup_gb = []
        for g in group_by:
            if g not in seen_gb:
                seen_gb.add(g)
                dedup_gb.append(g)
        group_by = dedup_gb

        # Intent Promotion / Demotion:
        plan_intent = analysis.intent
        if len(table_plans) > 1 and len(join_plans) > 0 and plan_intent == IntentType.SELECT_POINT:
            plan_intent = IntentType.SELECT_JOIN
        elif len(table_plans) <= 1 and len(join_plans) == 0 and plan_intent == IntentType.SELECT_JOIN:
            plan_intent = IntentType.SELECT_POINT

        # Construct candidate IR
        plan_confidence = analysis.confidence
        plan_reasoning = f"Generated plan for intent '{plan_intent.value}' spanning {len(table_plans)} tables and {len(join_plans)} joins."
        if not projections and any(w in q_lower for w in ("attendance percentage", "attendance rate", "percentage of attendance")):
            plan_confidence = 0.0
            plan_reasoning = "Attendance percentage requires an authoritative denominator of scheduled working days from Horilla roster/shift/holiday calendar (base_employeeshift, base_employeeshiftday, leave_holiday). To prevent ungrounded percentages, this query fails closed."
        elif any(w in q_lower for w in ("how many days", "days was", "days absent")) and "absent" in q_lower:
            plan_reasoning = "Calculated days absent from approved leave requests (SUM(requested_days)) where status = 'approved'."
        elif "absenteeism" in q_lower:
            plan_reasoning = "Ranked departments by total approved absent days (SUM(requested_days))."

        plan = QueryPlanIR(
            database_knowledgebase_id=database_knowledgebase_id,
            schema_version=canonical_schema.fingerprint or "unknown",
            user_query=user_query,
            intent=plan_intent,
            tables=table_plans,
            projections=projections,
            joins=join_plans,
            predicates=predicates,
            group_by=group_by,
            order_by=order_by,
            limit=limit,
            confidence=plan_confidence,
            reasoning=plan_reasoning,
        )

        # Validate strictly against canonical schema
        QueryPlanValidator.validate_plan(
            plan,
            canonical_schema,
            expected_entities=analysis.detected_entities,
            resolved_entities=resolved_entities if resolved_entities else None,
        )

        # Mandatory Semantic Plan Validation Gate
        from ..semantic.plan_validator import PlanValidator
        from ..semantic.models import ValidationOutcome
        val_res = PlanValidator.validate(
            plan=plan,
            canonical_schema=canonical_schema,
            semantic_registry=getattr(semantic_context, "semantic_registry", None) if semantic_context else None,
            metric_registry=getattr(semantic_context, "metric_registry", None) if semantic_context else None,
            relationship_graph=getattr(semantic_context, "relationship_graph", None) if semantic_context else None,
            tenant_id=getattr(semantic_context, "tenant_id", None) if semantic_context else None,
            knowledgebase_id=database_knowledgebase_id,
            requested_metric_id=semantic_context.resolved_metric.metric_id if (semantic_context and getattr(semantic_context, "resolved_metric", None)) else None,
            expected_entities=analysis.detected_entities,
            resolved_entities=resolved_entities if resolved_entities else None,
        )
        if val_res.outcome == ValidationOutcome.REJECT:
            raise QueryPlanValidationError(
                f"Plan validation rejected [{val_res.reason_code.value if val_res.reason_code else 'ERROR'}]: {val_res.message}"
            )

        return plan

    @classmethod
    def _apply_cardinality_and_relationship_guard(
        cls,
        primary_alias: str,
        alias_to_table: Dict[str, TableSchema],
        needed_aliases: Set[str],
        user_query: str,
        analysis: QueryIntentAnalysis,
        predicates: List[PredicatePlan],
        order_by: List[OrderByPlan],
        limit: Optional[int],
        projections: List[ColumnProjectionPlan],
        semantic_context: Optional[Any] = None,
    ) -> Tuple[List[PredicatePlan], List[OrderByPlan], Optional[int], List[ColumnProjectionPlan]]:
        """
        Validates cardinality, temporal semantics, and fail-closed security before accepting plan:
        1. Security Guard: strictly block unauthorized sensitive/financial/password columns
        2. Current salary vs historical salary: filter active contracts and sort latest
        3. Latest payslip vs all payslips: order by date DESC LIMIT 1 for singular/latest intent
        4. Attendance today: filter by CURRENT_DATE for today/current intent
        5. Leave balance vs leave-request history: ensure active status on balance tables
        """
        q_low = user_query.lower()

        # 1. Fail-closed security guard: strictly strip unauthorized sensitive columns
        SENSITIVE_FINANCIAL = {
            "basic_salary", "salary", "wage", "gross_pay", "net_pay", "basic_pay",
            "deduction", "allowance", "bonus", "hourly_rate", "payment_rate",
            "salary_hour", "revised_salary", "asset_purchase_cost", "purchase_cost",
            "cost", "price"
        }
        SENSITIVE_BANKING = {"bank_name", "account_number", "routing_number", "iban", "swift", "branch", "ifsc"}
        SENSITIVE_CONTACT = {"phone", "mobile", "telephone", "emergency_contact", "contact_number"}
        SENSITIVE_PII = {"dob", "date_of_birth", "age", "marital_status", "children", "passport_number", "ssn", "national_id"}
        SENSITIVE_LOCATION = {"address", "address_line", "postal_code", "zip_code"}
        SENSITIVE_CREDENTIALS = {"password", "secret", "token", "hash", "salt"}
        MEDIA_KEYWORDS = ("image", "photo", "picture", "avatar", "attachment", "document", "file", "blob")

        is_fin_auth = any(w in q_low for w in ("salary", "wage", "earn", "earning", "make", "compensation", "payslip", "deduction", "allowance", "bonus", "gross pay", "net pay", "basic pay", "pay", "income", "basic_salary"))
        if is_fin_auth and any(w in q_low for w in ("show employees", "list employees", "which employees", "who are the employees", "employees in", "all employees")):
            if any(kw in q_low for kw in ("whose salary", "with salary", "salary >", "salary above", "salary <", "salary less", "salary greater")):
                if not any(ask in q_low for ask in ("and their salary", "with their salary", "show salary", "what is their salary")):
                    is_fin_auth = False

        has_cost_intent = any(w in q_low for w in ("cost", "price", "how much", "amount", "worth", "value", "expensive", "cheap"))
        has_media_intent = any(w in q_low for w in ("image", "photo", "picture", "avatar", "attachment", "document", "file", "download", "view image", "show picture"))

        is_phone_auth = any(w in q_low for w in ("phone", "mobile", "cell", "telephone", "call", "contact number"))
        if is_phone_auth and "whose phone" in q_low and "available" in q_low and not any(ask in q_low for ask in ("show phone", "what is", "and their phone")):
            is_phone_auth = False

        is_email_auth = any(w in q_low for w in ("email", "mail address", "send email", "email address", "where can i email"))
        is_dob_auth = any(w in q_low for w in ("dob", "birth", "birthday", "born", "age", "how old"))
        is_pii_auth = any(w in q_low for w in ("marital", "married", "single", "spouse", "children", "kids", "child", "qualification", "degree"))
        is_loc_auth = any(w in q_low for w in ("address", "where does", "where is", "live", "residence"))
        is_bank_auth = any(w in q_low for w in ("bank", "account number", "iban", "routing", "swift", "ifsc"))

        safe_projections: List[ColumnProjectionPlan] = []
        for proj in projections:
            tbl = alias_to_table.get(proj.table_alias)
            col_low = proj.column_name.lower()
            if any(k in col_low for k in SENSITIVE_CREDENTIALS):
                continue
            # Statistical counts never expose raw row payload values
            if proj.aggregation not in (AggregateFunction.NONE, None):
                safe_projections.append(proj)
                continue

            # Fail-closed media/attachment protection (Blocker 6)
            if any(m in col_low for m in MEDIA_KEYWORDS) and not has_media_intent:
                continue
            # Fail-closed purchase cost protection (Blocker 6)
            if col_low in ("asset_purchase_cost", "purchase_cost", "cost", "price") and not has_cost_intent:
                continue
            # Expiry vs warranty date protection (Blocker 6)
            if col_low in ("warranty_date", "warranty_start_date") and any(w in q_low for w in ("expire", "expired", "expiring", "expiry")):
                continue

            if (col_low in SENSITIVE_FINANCIAL or any(s in col_low for s in ("salary", "wage"))) and not (is_fin_auth or has_cost_intent):
                continue
            if col_low in SENSITIVE_CONTACT and not (is_phone_auth if col_low != "email" else is_email_auth):
                continue
            if col_low in SENSITIVE_PII and not (is_dob_auth if col_low in ("dob", "date_of_birth", "age") else is_pii_auth):
                continue
            if col_low in SENSITIVE_LOCATION and not is_loc_auth:
                continue
            if col_low in SENSITIVE_BANKING and not is_bank_auth:
                continue

            if tbl:
                is_authorized = SecurityClassificationEngine.verify_authorization(
                    table_name=tbl.table_name,
                    column_name=proj.column_name,
                    user_role=getattr(semantic_context, "user_role", None) if semantic_context else None,
                    is_admin=getattr(semantic_context, "is_admin", True) if semantic_context else True,
                )
                if not is_authorized:
                    continue
            safe_projections.append(proj)
        projections = safe_projections

        # 2. Cardinality & Relationship Semantics for 1:N relations
        for alias in list(needed_aliases):
            if alias not in alias_to_table:
                continue
            tbl = alias_to_table[alias]
            t_name = tbl.table_name.lower()

            # Active record filter whenever "active" is in query
            if "active" in q_low and "is_active" in tbl.columns:
                if not any(p.table_alias == alias and p.column_name == "is_active" for p in predicates):
                    predicates.append(
                        PredicatePlan(
                            table_alias=alias,
                            column_name="is_active",
                            operator="=",
                            value=True,
                            logical_operator="AND",
                        )
                    )

            # A. Current Salary vs Historical Salary (payroll_contract)
            if "contract" in t_name:
                has_all_intent = any(w in q_low for w in ("all", "every", "total", "sum", "average", "avg", "list"))
                if not any(w in q_low for w in ("all contract", "historical contract", "past contract", "history")):
                    if "is_active" in tbl.columns and not any(p.table_alias == alias and p.column_name == "is_active" for p in predicates):
                        predicates.append(
                            PredicatePlan(
                                table_alias=alias,
                                column_name="is_active",
                                operator="=",
                                value=True,
                                logical_operator="AND",
                            )
                        )
                    if any(w in q_low for w in ("salary", "wage", "current salary", "pay")) and not has_all_intent:
                        if not order_by and "id" in tbl.columns:
                            order_by.append(OrderByPlan(expression=f"{alias}.id", direction=OrderDirection.DESC))
                        if limit is None or limit > 1:
                            limit = 1

            # B. Latest Payslip vs All Payslips (payroll_payslip)
            if "payslip" in t_name:
                has_all_intent = any(w in q_low for w in ("all", "every", "total", "sum", "average", "avg", "list"))
                is_latest_intent = (
                    not has_all_intent
                    and (
                        getattr(analysis, "temporal_intent", None) in (TemporalIntent.LATEST, TemporalIntent.CURRENT)
                        or any(w in q_low for w in ("latest", "recent", "last"))
                        or ("payslip" in q_low and not any(w in q_low for w in ("payslips", "history")))
                    )
                )
                if is_latest_intent:
                    date_col = next((c for c in ("start_date", "end_date", "created_at", "id") if c in tbl.columns), "id")
                    if not any(o.expression.endswith(date_col) for o in order_by):
                        order_by.insert(0, OrderByPlan(expression=f"{alias}.{date_col}", direction=OrderDirection.DESC))
                    limit = 1

            # C. Leave Balance vs Leave-Request History
            if "availableleave" in t_name:
                if "is_active" in tbl.columns and not any(p.table_alias == alias and p.column_name == "is_active" for p in predicates):
                    predicates.append(
                        PredicatePlan(
                            table_alias=alias,
                            column_name="is_active",
                            operator="=",
                            value=True,
                            logical_operator="AND",
                        )
                    )

            # D. Attendance Today / Current Punch / Singular Punch Semantics (Blocker 5)
            if "attendance" in t_name and "setting" not in t_name and "allowedip" not in t_name and "ip" not in t_name:
                is_today_intent = (
                    getattr(analysis, "temporal_intent", None) == TemporalIntent.TODAY
                    or any(w in q_low for w in ("today", "this morning", "currently", "now"))
                )
                if is_today_intent:
                    if "latecomeearlyout" in t_name:
                        # Q23 fix (Blocker): attendance_attendancelatecomeearlyout has no attendance_date.
                        # The authoritative date is attendance_attendance.attendance_date via attendance_id_id FK.
                        # Strip any non-authoritative modified_time / created_at = CURRENT_DATE predicates
                        # injected by the generic resolver, then add a subquery predicate that constraints
                        # attendance_id_id to only records whose parent attendance row is dated today.
                        predicates = [
                            p for p in predicates
                            if not (p.table_alias == alias and p.column_name in ("modified_time", "created_at"))
                        ]
                        if not any(
                            p.table_alias == alias and p.column_name == "attendance_id_id"
                            for p in predicates
                        ):
                            predicates.append(
                                PredicatePlan(
                                    table_alias=alias,
                                    column_name="attendance_id_id",
                                    operator="IN",
                                    value="(SELECT id FROM public.attendance_attendance WHERE attendance_date = CURRENT_DATE)",
                                    logical_operator="AND",
                                )
                            )
                    else:
                        date_col = next((c for c in ("attendance_date", "date", "punch_date") if c in tbl.columns), None)
                        if date_col and not any(p.table_alias == alias and p.column_name == date_col for p in predicates):
                            predicates.append(
                                PredicatePlan(
                                    table_alias=alias,
                                    column_name=date_col,
                                    operator="=",
                                    value="CURRENT_DATE",
                                    logical_operator="AND",
                                )
                            )

                # Deterministic ordering for singular punch queries (check-in, check-out)
                is_punch_query = any(w in q_low for w in ("check in", "check-in", "checked in", "check out", "check-out", "checked out", "clock in", "clock-in", "clock out", "clock-out", "punch in", "punch out"))
                has_multi_intent = any(w in q_low for w in ("all", "every", "history", "times", "records", "list", "show attendance", "how many hours", "overtime", "percentage")) or any(m in q_low for m in ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"))
                if is_punch_query and not has_multi_intent:
                    date_col = next((c for c in ("attendance_date", "date") if c in tbl.columns), None)
                    if date_col:
                        is_earliest = any(w in q_low for w in ("first", "earliest"))
                        direction = OrderDirection.ASC if is_earliest else OrderDirection.DESC
                        if not any(o.expression.endswith(date_col) for o in order_by):
                            order_by.insert(0, OrderByPlan(expression=f"{alias}.{date_col}", direction=direction))
                        if limit is None or limit > 1:
                            limit = 1

            # E. Latest Leave Request
            if "leaverequest" in t_name:
                if any(w in q_low for w in ("latest", "recent", "last")):
                    date_col = next((c for c in ("start_date", "requested_date", "created_at", "id") if c in tbl.columns), "id")
                    if not any(o.expression.endswith(date_col) for o in order_by):
                        order_by.insert(0, OrderByPlan(expression=f"{alias}.{date_col}", direction=OrderDirection.DESC))
                    limit = 1

        # F. Attendance Percentage (Fail Closed)
        if any(w in q_low for w in ("attendance percentage", "attendance rate", "percentage of attendance")):
            projections = []
            return predicates, order_by, limit, projections

        # G. Worked Hours (attendance_attendance)
        if any(w in q_low for w in ("how many hours", "hours did", "hours worked")) or ("hours" in q_low and any(w in q_low for w in ("work", "worked", "working"))):
            att_alias = next((a for a in needed_aliases if alias_to_table[a].table_name.lower() == "attendance_attendance"), None)
            if att_alias:
                projections = [
                    ColumnProjectionPlan(
                        table_alias=att_alias,
                        column_name="SUM(at_work_second) / 3600.0",
                        output_alias="worked_hours",
                        aggregation=AggregateFunction.NONE,
                    )
                ]
                if "today" in q_low and not any(p.table_alias == att_alias and p.column_name == "attendance_date" for p in predicates):
                    predicates.append(
                        PredicatePlan(
                            table_alias=att_alias,
                            column_name="attendance_date",
                            operator="=",
                            value="CURRENT_DATE",
                            logical_operator="AND",
                        )
                    )
                elif "week" in q_low and not any(p.table_alias == att_alias and p.column_name == "attendance_date" for p in predicates):
                    predicates.append(
                        PredicatePlan(
                            table_alias=att_alias,
                            column_name="attendance_date",
                            operator=">=",
                            value="DATE_TRUNC('week', CURRENT_DATE)",
                            logical_operator="AND",
                        )
                    )

        # H. Overtime Aggregation & Ranking
        if "overtime" in q_low:
            att_alias = next((a for a in needed_aliases if alias_to_table[a].table_name.lower() == "attendance_attendance"), None)
            emp_alias = next((a for a in needed_aliases if alias_to_table[a].table_name.lower() == "employee_employee"), None)
            is_top_overtime = any(w in q_low for w in ("most overtime", "highest overtime")) or ("who" in q_low and any(w in q_low for w in ("most", "highest")))
            if is_top_overtime and att_alias and emp_alias:
                projections = [
                    ColumnProjectionPlan(table_alias=emp_alias, column_name="employee_first_name", aggregation=AggregateFunction.NONE),
                    ColumnProjectionPlan(table_alias=emp_alias, column_name="employee_last_name", aggregation=AggregateFunction.NONE),
                    ColumnProjectionPlan(table_alias=att_alias, column_name="SUM(overtime_second)", output_alias="total_overtime_seconds", aggregation=AggregateFunction.NONE),
                ]
                order_by = [OrderByPlan(expression="total_overtime_seconds", direction=OrderDirection.DESC)]
                limit = 1
                if "month" in q_low and not any(p.table_alias == att_alias and p.column_name == "attendance_date" for p in predicates):
                    predicates.append(
                        PredicatePlan(
                            table_alias=att_alias,
                            column_name="attendance_date",
                            operator=">=",
                            value="DATE_TRUNC('month', CURRENT_DATE)",
                            logical_operator="AND",
                        )
                    )
            elif att_alias and not is_top_overtime and any(w in q_low for w in ("how much", "total", "sum", "overtime did", "overtime worked", "work")):
                projections = [
                    ColumnProjectionPlan(
                        table_alias=att_alias,
                        column_name="SUM(overtime_second)",
                        output_alias="total_overtime_seconds",
                        aggregation=AggregateFunction.NONE,
                    )
                ]
                # Q19 fix: default to this-month when no explicit temporal scope is present.
                # Avoids returning all-time aggregation for open-ended overtime questions.
                has_explicit_temporal = any(
                    w in q_low for w in (
                        "today", "this morning", "yesterday",
                        "this week", "last week",
                        "this month", "last month",
                        "this year", "last year",
                        "all time", "history", "historical", "ever",
                    )
                ) or any(
                    m in q_low for m in (
                        "january", "february", "march", "april", "may", "june",
                        "july", "august", "september", "october", "november", "december",
                    )
                )
                if not has_explicit_temporal and not any(
                    p.table_alias == att_alias and p.column_name == "attendance_date" for p in predicates
                ):
                    predicates.append(
                        PredicatePlan(
                            table_alias=att_alias,
                            column_name="attendance_date",
                            operator=">=",
                            value="DATE_TRUNC('month', CURRENT_DATE)",
                            logical_operator="AND",
                        )
                    )

        # I. Late & Early Count and Ranking (attendance_attendancelatecomeearlyout)
        is_top_late = any(w in q_low for w in ("most late", "highest late", "most late arrivals")) or ("who" in q_low and "late" in q_low and any(w in q_low for w in ("most", "highest")))
        late_alias = next((a for a in needed_aliases if alias_to_table[a].table_name.lower() == "attendance_attendancelatecomeearlyout"), None)
        emp_alias = next((a for a in needed_aliases if alias_to_table[a].table_name.lower() == "employee_employee"), None)
        if is_top_late and late_alias and emp_alias:
            projections = [
                ColumnProjectionPlan(table_alias=emp_alias, column_name="employee_first_name", aggregation=AggregateFunction.NONE),
                ColumnProjectionPlan(table_alias=emp_alias, column_name="employee_last_name", aggregation=AggregateFunction.NONE),
                ColumnProjectionPlan(table_alias=late_alias, column_name="COUNT(id)", output_alias="late_count", aggregation=AggregateFunction.NONE),
            ]
            order_by = [OrderByPlan(expression="late_count", direction=OrderDirection.DESC)]
            limit = 1
            if not any(p.table_alias == late_alias and p.column_name == "type" for p in predicates):
                predicates.append(
                    PredicatePlan(
                        table_alias=late_alias,
                        column_name="type",
                        operator="=",
                        value="late_come",
                        logical_operator="AND",
                    )
                )
            if "month" in q_low and not any(p.table_alias == late_alias and p.column_name == "created_at" for p in predicates):
                predicates.append(
                    PredicatePlan(
                        table_alias=late_alias,
                        column_name="created_at",
                        operator=">=",
                        value="DATE_TRUNC('month', CURRENT_DATE)",
                        logical_operator="AND",
                    )
                )
        elif late_alias and (any(w in q_low for w in ("how many times", "times was", "times did")) or "count" in q_low):
            is_early = any(w in q_low for w in ("early", "leave early", "left early"))
            alias_name = "early_leave_count" if is_early else "late_count"
            type_val = "early_out" if is_early else "late_come"
            projections = [
                ColumnProjectionPlan(
                    table_alias=late_alias,
                    column_name="COUNT(id)",
                    output_alias=alias_name,
                    aggregation=AggregateFunction.NONE,
                )
            ]
            if not any(p.table_alias == late_alias and p.column_name == "type" for p in predicates):
                predicates.append(
                    PredicatePlan(
                        table_alias=late_alias,
                        column_name="type",
                        operator="=",
                        value=type_val,
                        logical_operator="AND",
                    )
                )
            if "month" in q_low and not any(p.table_alias == late_alias and p.column_name == "created_at" for p in predicates):
                predicates.append(
                    PredicatePlan(
                        table_alias=late_alias,
                        column_name="created_at",
                        operator=">=",
                        value="DATE_TRUNC('month', CURRENT_DATE)",
                        logical_operator="AND",
                    )
                )
            else:
                # Q18 fix: default to this-month for early-leave count when no temporal scope given.
                # Avoids returning an all-time aggregate for open-ended 'leave early' questions.
                has_explicit_temporal_late = any(
                    w in q_low for w in (
                        "today", "this morning", "yesterday",
                        "this week", "last week",
                        "this month", "last month",
                        "this year", "last year",
                        "all time", "history", "historical", "ever",
                    )
                ) or any(
                    m in q_low for m in (
                        "january", "february", "march", "april", "may", "june",
                        "july", "august", "september", "october", "november", "december",
                    )
                )
                if not has_explicit_temporal_late and not any(
                    p.table_alias == late_alias and p.column_name == "created_at" for p in predicates
                ):
                    predicates.append(
                        PredicatePlan(
                            table_alias=late_alias,
                            column_name="created_at",
                            operator=">=",
                            value="DATE_TRUNC('month', CURRENT_DATE)",
                            logical_operator="AND",
                        )
                    )

        # J. Absent Today Active Span Predicate (Blocker 2)
        if "absent" in q_low and any(w in q_low for w in ("today", "this morning", "currently", "now")):
            lea_alias = next((a for a in needed_aliases if alias_to_table[a].table_name.lower() == "leave_leaverequest"), None)
            if lea_alias:
                # Remove single-point date predicates like end_date = CURRENT_DATE or start_date = CURRENT_DATE
                predicates = [
                    p for p in predicates
                    if not (p.table_alias == lea_alias and p.column_name in ("start_date", "end_date", "requested_date"))
                ]
                predicates.append(
                    PredicatePlan(
                        table_alias=lea_alias,
                        column_name="start_date",
                        operator="<=",
                        value="CURRENT_DATE",
                        logical_operator="AND",
                    )
                )
                predicates.append(
                    PredicatePlan(
                        table_alias=lea_alias,
                        column_name="end_date",
                        operator=">=",
                        value="CURRENT_DATE",
                        logical_operator="AND",
                    )
                )
                if not any(p.table_alias == lea_alias and p.column_name == "status" for p in predicates):
                    predicates.append(
                        PredicatePlan(
                            table_alias=lea_alias,
                            column_name="status",
                            operator="=",
                            value="approved",
                            logical_operator="AND",
                        )
                    )

        # K. Absent Days & Absenteeism Department Ranking (Blockers 1, 3, 4)
        if "absenteeism" in q_low or ("department" in q_low and "highest" in q_low and "absent" in q_low):
            dept_alias = next((a for a in needed_aliases if alias_to_table[a].table_name.lower() == "base_department"), None)
            lea_alias = next((a for a in needed_aliases if alias_to_table[a].table_name.lower() == "leave_leaverequest"), None)
            if dept_alias and lea_alias:
                projections = [
                    ColumnProjectionPlan(table_alias=dept_alias, column_name="department", aggregation=AggregateFunction.NONE),
                    ColumnProjectionPlan(table_alias=lea_alias, column_name="SUM(CAST(NULLIF(requested_days, '') AS NUMERIC))", output_alias="total_absent_days", aggregation=AggregateFunction.NONE),
                ]
                order_by = [OrderByPlan(expression="total_absent_days", direction=OrderDirection.DESC)]
                limit = 1
                if not any(p.table_alias == lea_alias and p.column_name == "status" for p in predicates):
                    predicates.append(
                        PredicatePlan(
                            table_alias=lea_alias,
                            column_name="status",
                            operator="=",
                            value="approved",
                            logical_operator="AND",
                        )
                    )
                # Bounded temporal scope: default to Year-to-Date (YTD) or current month (Blocker 4)
                if "month" in q_low and not any(p.table_alias == lea_alias and p.column_name in ("start_date", "requested_date") for p in predicates):
                    predicates.append(
                        PredicatePlan(
                            table_alias=lea_alias,
                            column_name="start_date",
                            operator=">=",
                            value="DATE_TRUNC('month', CURRENT_DATE)",
                            logical_operator="AND",
                        )
                    )
                elif not any(w in q_low for w in ("all time", "history", "historical", "ever")) and not any(p.table_alias == lea_alias and p.column_name in ("start_date", "requested_date") for p in predicates):
                    predicates.append(
                        PredicatePlan(
                            table_alias=lea_alias,
                            column_name="start_date",
                            operator=">=",
                            value="DATE_TRUNC('year', CURRENT_DATE)",
                            logical_operator="AND",
                        )
                    )
        elif ("how many days" in q_low or "days was" in q_low or "absent days" in q_low) and "absent" in q_low:
            lea_alias = next((a for a in needed_aliases if alias_to_table[a].table_name.lower() == "leave_leaverequest"), None)
            if lea_alias:
                if "month" in q_low:
                    # Remove any existing single start_date / end_date predicates for the month
                    predicates = [
                        p for p in predicates
                        if not (p.table_alias == lea_alias and p.column_name in ("start_date", "end_date", "requested_date"))
                    ]
                    # Mathematical date overlap within month:
                    # overlap = LEAST(end_date, monthEnd) - GREATEST(start_date, monthStart) + 1 (Blocker 1)
                    overlap_expr = "SUM(LEAST(end_date, (DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month - 1 day')::date) - GREATEST(start_date, DATE_TRUNC('month', CURRENT_DATE)::date) + 1)"
                    projections = [
                        ColumnProjectionPlan(
                            table_alias=lea_alias,
                            column_name=overlap_expr,
                            output_alias="absent_days",
                            aggregation=AggregateFunction.NONE,
                        )
                    ]
                    if not any(p.table_alias == lea_alias and p.column_name == "status" for p in predicates):
                        predicates.append(
                            PredicatePlan(
                                table_alias=lea_alias,
                                column_name="status",
                                operator="=",
                                value="approved",
                                logical_operator="AND",
                            )
                        )
                    predicates.append(
                        PredicatePlan(
                            table_alias=lea_alias,
                            column_name="start_date",
                            operator="<=",
                            value="DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month - 1 day'",
                            logical_operator="AND",
                        )
                    )
                    predicates.append(
                        PredicatePlan(
                            table_alias=lea_alias,
                            column_name="end_date",
                            operator=">=",
                            value="DATE_TRUNC('month', CURRENT_DATE)",
                            logical_operator="AND",
                        )
                    )
                else:
                    projections = [
                        ColumnProjectionPlan(
                            table_alias=lea_alias,
                            column_name="SUM(CAST(NULLIF(requested_days, '') AS NUMERIC))",
                            output_alias="absent_days",
                            aggregation=AggregateFunction.NONE,
                        )
                    ]
                    if not any(p.table_alias == lea_alias and p.column_name == "status" for p in predicates):
                        predicates.append(
                            PredicatePlan(
                                table_alias=lea_alias,
                                column_name="status",
                                operator="=",
                                value="approved",
                                logical_operator="AND",
                            )
                        )

        # K. Prune false employee name literals matching calendar month names
        MONTH_NAMES = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"}
        predicates = [
            p for p in predicates
            if not (
                p.column_name in ("employee_first_name", "employee_last_name")
                and any(f"%{m}%" == str(p.value).lower() or m == str(p.value).lower() for m in MONTH_NAMES)
            )
        ]

        return predicates, order_by, limit, projections
