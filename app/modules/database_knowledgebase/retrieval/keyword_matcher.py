"""Deterministic Keyword and Identifier Matching for Database Schema

Matches user query tokens against table names, column names, comments, and identifiers.
Provides an independent, fast keyword score signal for hybrid retrieval.
"""

import re
from typing import Dict, List, Optional, Set, Tuple, Any
from ..schemas.canonical import DatabaseSchema, TableSchema

STOPWORDS = {
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "can", "could", "should", "would", "will", "show", "give", "find",
    "get", "list", "all", "what", "which", "who", "where", "how", "many", "much", "each",
    "every", "me", "my", "our", "us", "please", "tell",
}


class KeywordMatchResult:
    """Represents keyword matching outcome for a specific table."""

    def __init__(
        self,
        table_name: str,
        schema_name: str,
        score: float,
        matched_table_name: bool,
        matched_columns: List[str],
        matched_tokens: List[str],
        retrieval_reason: str,
    ):
        self.table_name = table_name
        self.schema_name = schema_name
        self.score = score
        self.matched_table_name = matched_table_name
        self.matched_columns = matched_columns
        self.matched_tokens = matched_tokens
        self.retrieval_reason = retrieval_reason


class SchemaKeywordMatcher:
    """
    Performs deterministic token and identifier matching against canonical database schema.
    """

    @classmethod
    def tokenize_query(cls, query: str) -> Set[str]:
        """Tokenize and stem query terms into clean identifier tokens."""
    @classmethod
    def tokenize_query(cls, query: str) -> Set[str]:
        """Tokenize and stem query terms into clean identifier tokens, normalizing compound phrases."""
        compound_patterns = [
            (r"\bleave\s+requests?\b", "leave_request"),
            (r"\bpurchase\s+orders?\b", "purchase_order"),
            (r"\bsales\s+orders?\b", "sales_order"),
            (r"\bjob\s+positions?\b", "job_position"),
            (r"\bperformance\s+reviews?\b", "performance_review"),
            (r"\bwork\s+informations?\b", "work_information"),
            (r"\btime\s+offs?\b", "time_off"),
            (r"\btimesheets?\b", "timesheet"),
            (r"\bsupport\s+tickets?\b", "support_ticket"),
            (r"\buser\s+accounts?\b", "user_account"),
            (r"\bbank\s+accounts?\b", "bank_account"),
            (r"\bexpense\s+reports?\b", "expense_report"),
            # Attendance / office-entry concepts
            (r"\bentered?\s+(?:the\s+)?office\b", "attendance"),
            (r"\b(?:clock|punch|check)[ed]*[\s-]in\b", "attendance"),
            (r"\b(?:clock|punch|check)[ed]*[\s-]out\b", "attendance"),
            (r"\b(?:swipe|swiped|scan|scanned)[\s-]in\b", "attendance"),
            (r"\b(?:swipe|swiped|scan|scanned)[\s-]out\b", "attendance"),
            (r"\b(?:left|leave)\s+(?:the\s+)?office\b", "attendance"),
            (r"\boffice\s+(?:entry|arrival|departure|time)\b", "attendance"),
            (r"\barrived?\s+(?:at\s+)?(?:the\s+)?office\b", "attendance"),
            (r"\barrived?\s+(?:after|before|past)\b", "attendance"),
            (r"\boffice\s+hours?\b", "attendance"),
            (r"\b(?:work(?:ing)?|office)\s+attendance\b", "attendance"),
            (r"\blow\s+attendance\b", "attendance"),
            # Late arrivals & early departures (late_come, early_out)
            (r"\b(?:came|come|arrived?|showed?\s+up)\s+(?:in\s+)?late\b", "late_come attendance"),
            (r"\blate\s+(?:to\s+)?(?:work|office|come|arrival|arriv)\b", "late_come attendance"),
            (r"\btardy\b", "late_come attendance"),
            (r"\b(?:left|leave|depart(?:ed)?)\s+early\b", "early_out attendance"),
            (r"\b(?:check(?:ed)?|clock(?:ed)?|punch(?:ed)?)\s+out\s+early\b", "early_out attendance"),
            # Leave & Absences
            (r"\b(?:currently\s+)?on\s+leave\b", "leave_leaverequest employee_employee leave"),
            (r"\btak(?:e|ing)\s+leave\b", "leave_leaverequest employee_employee leave"),
            (r"\babsent\b", "leave_leaverequest attendance employee_employee"),
            (r"\babsence\b", "leave_leaverequest attendance employee_employee"),
            (r"\boff\s+duty\b", "leave_leaverequest"),
            # Overtime
            (r"\b(?:worked\s+)?overtime\b", "overtime attendance"),
            (r"\bextra\s+hours?\b", "overtime attendance"),
            # Shifts
            (r"\b(?:work\s+)?shift\s+starts?\s+(?:early|late)?\b", "shift shift_schedule"),
            (r"\bearly\s+shift\b", "shift shift_schedule"),
            (r"\bnight\s+shift\b", "shift shift_schedule"),
            (r"\bshift\s+schedule\b", "shift_schedule"),
        ]
        norm_q = query.lower()
        for pat, canonical_ent in compound_patterns:
            norm_q = re.sub(pat, canonical_ent, norm_q)

        raw_tokens = re.findall(r"[a-zA-Z0-9_]+", norm_q)
        tokens = set()
        for tok in raw_tokens:
            if tok not in STOPWORDS and len(tok) >= 2:
                tokens.add(tok)
                # Simple lemmatization/singularization
                if tok.endswith("ies") and len(tok) > 3:
                    tokens.add(tok[:-3] + "y")
                elif tok.endswith("es") and len(tok) > 3:
                    tokens.add(tok[:-2])
                elif tok.endswith("s") and len(tok) > 2 and not tok.endswith("ss"):
                    tokens.add(tok[:-1])
        return tokens

    @classmethod
    def match_schema(
        cls,
        query: str,
        schema: DatabaseSchema,
        allowed_tables: Optional[Set[str]] = None,
        glossary_entries: Optional[Dict[Tuple[str, str], Any]] = None,
    ) -> Dict[str, KeywordMatchResult]:
        """
        Evaluate keyword matching across all tables in canonical DatabaseSchema.

        Returns:
            Dictionary of table_key ('public.customers') -> KeywordMatchResult
        """
        tokens = cls.tokenize_query(query)
        results: Dict[str, KeywordMatchResult] = {}

        if not tokens:
            return results

        # Group published glossary entries by table
        glossary_by_table: Dict[str, List[Any]] = {}
        if glossary_entries:
            for (t_name, c_name), entry in glossary_entries.items():
                if getattr(entry, "is_published", False) is True:
                    glossary_by_table.setdefault(t_name, []).append(entry)

        for s_name, s_info in schema.schemas.items():
            for t_name, table in s_info.tables.items():
                if allowed_tables is not None:
                    table_key = f"{table.schema_name}.{table.table_name}"
                    if table_key not in allowed_tables and table.table_name not in allowed_tables:
                        continue

                t_glossary = glossary_by_table.get(table.table_name)
                match = cls._match_table(tokens, table, table_glossary=t_glossary, query_str=query)
                if match.score > 0.0:
                    table_key = f"{table.schema_name}.{table.table_name}"
                    results[table_key] = match

        return results

    @classmethod
    def _match_table(
        cls,
        query_tokens: Set[str],
        table: TableSchema,
        table_glossary: Optional[List[Any]] = None,
        query_str: str = "",
    ) -> KeywordMatchResult:
        t_name = table.table_name.lower()
        t_name_singular = t_name[:-1] if t_name.endswith("s") else t_name
        query_lower = query_str.lower() if query_str else " ".join(query_tokens)

        matched_table = False
        matched_cols: List[str] = []
        matched_tokens: List[str] = []

        # 1. Exact or compound table name matching
        if t_name in query_tokens or t_name_singular in query_tokens:
            matched_table = True
            matched_tokens.append(t_name)
        else:
            for tok in query_tokens:
                tok_parts = [p for p in tok.split("_") if p]
                if len(tok_parts) > 1:
                    # For compound tokens like "leave_request", all constituent parts must appear in table name
                    if all(p in t_name for p in tok_parts):
                        matched_table = True
                        matched_tokens.append(tok)
                        break
                else:
                    if tok in t_name or t_name in tok:
                        matched_table = True
                        matched_tokens.append(tok)
                        break

        # 2. Column identifier matching
        for c_name, col in table.columns.items():
            col_lower = c_name.lower()
            col_singular = col_lower[:-1] if col_lower.endswith("s") else col_lower

            if col_lower in query_tokens or col_singular in query_tokens:
                matched_cols.append(c_name)
                matched_tokens.append(col_lower)
            else:
                for tok in query_tokens:
                    if "_" not in tok and len(tok) >= 3 and (tok in col_lower or col_lower in tok):
                        matched_cols.append(c_name)
                        matched_tokens.append(tok)
                        break

        # 3. Comment matching
        comment_matches = 0
        if table.comment:
            comment_lower = table.comment.lower()
            for tok in query_tokens:
                if tok in comment_lower:
                    comment_matches += 1
                    matched_tokens.append(tok)

        # 4. Published Concept Glossary matching
        # LOAD-BEARING REVIEW GATE: Strictly evaluate entries where is_published is True
        TIER_WEIGHTS = {
            "HUMAN_VERIFIED": 0.35,
            "SYSTEM_VERIFIED": 0.25,
            "LLM_GENERATED": 0.15,
        }
        reasons: List[str] = []
        glossary_matches = 0
        matched_tier_boosts: List[float] = []
        if table_glossary:
            for entry in table_glossary:
                if getattr(entry, "is_published", False) is not True:
                    continue
                c_name = getattr(entry, "column_name", "")
                synonyms = getattr(entry, "synonyms", []) or []
                conf_source = getattr(entry, "confidence_source", "LLM_GENERATED") or "LLM_GENERATED"
                tier_weight = TIER_WEIGHTS.get(conf_source, 0.20)
                matched_syn = None
                for syn in synonyms:
                    syn_clean = syn.lower().strip()
                    if not syn_clean:
                        continue
                    if syn_clean in query_tokens or (len(syn_clean) >= 4 and syn_clean in query_lower):
                        matched_syn = syn_clean
                        break
                    syn_parts = [p for p in syn_clean.split() if p not in STOPWORDS and len(p) >= 3]
                    if syn_parts and all(p in query_tokens for p in syn_parts):
                        matched_syn = syn_clean
                        break

                if matched_syn:
                    glossary_matches += 1
                    matched_tier_boosts.append(tier_weight)
                    matched_cols.append(c_name)
                    matched_tokens.append(matched_syn)
                    reasons.append(f"Glossary concept match for column '{c_name}' (synonym: '{matched_syn}', tier: {conf_source})")

        # 5. Score Calculation
        score = 0.0

        if matched_table:
            score += 0.60
            reasons.append(f"Table name '{table.table_name}' matches query")

        if matched_cols:
            col_score = min(0.40, len(matched_cols) * 0.15)
            score += col_score
            reasons.append(f"Columns matched: {', '.join(matched_cols[:3])}")

        if glossary_matches > 0:
            top_tier_boost = max(matched_tier_boosts) if matched_tier_boosts else 0.25
            glossary_score = min(0.50, top_tier_boost + (glossary_matches - 1) * 0.10)
            score += glossary_score
            reasons.append(f"Glossary concept matches ({glossary_matches}, tier boost: +{top_tier_boost:.2f})")

        if comment_matches > 0:
            score += min(0.20, comment_matches * 0.10)
            reasons.append("Table comment matched query keywords")

        # Boost primary domain entity tables (exact name, duplicate tokens, or common prefixes)
        for tok in query_tokens:
            is_primary_match = (
                t_name == tok
                or t_name == f"{tok}s"
                or (t_name.count("_") == 1 and t_name == f"{tok}_{tok}")
                or any(t_name.startswith(pfx) and t_name[len(pfx):] in (tok, f"{tok}s") for pfx in ("base_", "tbl_", "dim_", "fact_", "ref_", "core_", "app_"))
            )
            if is_primary_match:
                score += 0.25
                break

        # Penalize many-to-many junction tables (e.g. horilla_documents_documentrequest_employee_id)
        if t_name.endswith("_id") and t_name.count("_") >= 3:
            score *= 0.40

        # Penalize historical tables unless user explicitly requested history
        if "historical" in t_name and "historical" not in query_tokens and "history" not in query_tokens:
            score *= 0.50

        score = min(1.0, score)

        return KeywordMatchResult(
            table_name=table.table_name,
            schema_name=table.schema_name,
            score=score,
            matched_table_name=matched_table,
            matched_columns=list(set(matched_cols)),
            matched_tokens=list(set(matched_tokens)),
            retrieval_reason=" | ".join(reasons) if reasons else "No keyword match",
        )
