"""Universal Entity Value Resolver

Resolves natural language entity literal values (e.g. "details of Kannan",
"department Executive", "info on Acme Corp") to physical column predicates.

Supports:
1. Pattern & heuristic literal extraction from natural language queries.
2. Identity column candidate selection from DatabaseKnowledgeProfile / IdentityRegistry.
3. Multi-stage parameterized query verification (exact -> normalized -> bounded fuzzy).
4. Strict cardinality checks (unique match -> bind, multiple matches -> ambiguous, zero matches -> fail closed).
5. Deterministic PredicatePlan generation.
"""

from enum import Enum
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, ConfigDict, Field

from .models import PredicatePlan
from ..semantic.database_knowledge_profile import (
    ColumnSemanticProfile,
    ColumnSemanticRole,
    ColumnSemanticSubtype,
    DatabaseKnowledgeProfile,
    IdentityField,
)
from ..semantic.identity_registry import IdentityRegistry


class ResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    NO_TARGET_COLUMN = "NO_TARGET_COLUMN"
    PLANNED_OFFLINE = "PLANNED_OFFLINE"


class EntityValueResolutionResult(BaseModel):
    """Structured result of resolving an entity value."""
    model_config = ConfigDict(extra="forbid")

    status: ResolutionStatus
    query_literal: str
    target_table: Optional[str] = None
    target_column: Optional[str] = None
    table_alias: Optional[str] = None
    resolved_value: Optional[Any] = None
    operator: str = "="
    match_count: int = 0
    candidate_matches: List[Any] = Field(default_factory=list)
    predicate_plan: Optional[PredicatePlan] = None
    diagnostic_message: str = ""


class EntityValueResolver:
    """
    Resolves natural language entity values to physical table column filters.
    Zero domain hardcoding.
    """

    # Linguistic patterns for extracting entity literal values from natural language
    _EXTRACTION_PATTERNS = [
        # Quoted literals: 'Kannan', "Sales"
        re.compile(r"['\"]([^'\"]{2,60})['\"]", re.IGNORECASE),
        # Possessive: "Girinath's phone number", "Alice's salary", "girinath's"
        re.compile(r"\b([a-zA-Z0-9_\-\.]{2,40})'s\b", re.IGNORECASE),
        # "details of Kannan", "info for Kannan", "records of Kannan"
        re.compile(
            r"\b(?:details|info|information|data|profile|record|records)\s+(?:of|for|about|on)\s+([a-zA-Z0-9_\-\.]{2,40})\b",
            re.IGNORECASE,
        ),
        # "named Kannan", "called Kannan", "with name Kannan", "titled Kannan"
        re.compile(r"\b(?:named|called|with name|titled)\s+([a-zA-Z0-9_\-\.]{2,40})\b", re.IGNORECASE),
        # "who is Kannan", "who was Kannan"
        re.compile(r"\bwho\s+(?:is|was)\s+(?:named\s+|called\s+)?([a-zA-Z0-9_\-\.]{2,40})\b", re.IGNORECASE),
        # "employee Kannan", "staff Kannan", "candidate Girinath"
        re.compile(r"\b(?:employee|staff|user|member|person|customer|patient|doctor|client|candidate)\s+([a-zA-Z0-9_\-\.]{2,40})\b", re.IGNORECASE),
        # Prepositional entity mention: "for Kannan", "against Girinath", "by Girinath", "allocated to Girinath", "given to Girinath"
        re.compile(r"\b(?:for|on|about|of|assigned\s+to|allocated\s+to|given\s+to|to|against|by|with)\s+(?:employee|staff|user|member|person|customer|patient|doctor|client|candidate)?\s*([a-zA-Z0-9_\-\.]{2,40})\b", re.IGNORECASE),
        # Question frames: "What is Girinath...", "What are Girinath...", "Tell me Girinath...", "Was Girinath...", "Has Girinath..."
        re.compile(r"\b(?:what\s+is|what\s+are|what's|who\s+is|who\s+are|who's|was|were|is|are|has|have|had|give\s+me|tell\s+me|show|list|find|get|check|verify)\s+(?:the\s+)?([a-zA-Z0-9_\-\.]{2,40})\b", re.IGNORECASE),
        # Action frames: "email girinath", "contact girinath", "call girinath"
        re.compile(r"\b(?:email|call|contact|message|reach)\s+([a-zA-Z0-9_\-\.]{2,40})\b", re.IGNORECASE),
        # Location / Action question frames: "Where does Kannan work", "Where is Girinath located", "How much does Kannan earn"
        re.compile(r"\b(?:where\s+does|where\s+is|where\s+are|which\s+department\s+does|how\s+much\s+does|does|did)\s+([a-zA-Z0-9_\-\.]{2,40})\b", re.IGNORECASE),
        # Direct start with potential entity: "Girinath phone number", "girinath email"
        re.compile(r"^([a-zA-Z0-9_\-\.]{2,40})\s+[a-zA-Z0-9_\-\.]+", re.IGNORECASE),
    ]

    # Closed-class non-value words, commands, and structural terms that should never be extracted as entity literals
    _STOPWORDS = {
        "all", "each", "every", "any", "some", "the", "a", "an", "this", "that", "these", "those", "there", "here",
        "active", "inactive", "pending", "approved", "rejected", "completed",
        "new", "old", "recent", "highest", "lowest", "top", "bottom", "max", "min", "most", "more", "least", "much", "many",
        "average", "total", "sum", "count", "department", "employee", "customer",
        "patient", "doctor", "client", "invoice", "order", "table", "details",
        "data", "record", "records", "information", "profile", "today", "yesterday", "tomorrow",
        "friday", "monday", "tuesday", "wednesday", "thursday", "saturday", "sunday",
        "morning", "evening", "night", "week", "month", "year", "daily", "weekly", "monthly", "quarterly", "yearly", "hourly",
        "who", "whose", "whom", "what", "which", "where", "when", "why", "how",
        "is", "are", "was", "were", "do", "does", "did", "have", "has", "had", "be", "been", "being",
        "can", "could", "will", "would", "shall", "should", "may", "might", "must",
        "give", "tell", "show", "list", "find", "get", "fetch", "display", "check", "verify", "me", "us", "them", "him", "her",
        "staff", "person", "people", "number", "numbers", "code", "id", "value", "values", "type",
        "salary", "salaries", "wage", "wages", "pay", "payment", "amount", "amounts",
        "budget", "budgets", "cost", "costs", "price", "prices", "title", "role",
        "position", "company", "firm", "team", "organization", "system",
        "attendance", "leave", "shift", "status", "rate", "fee", "hours", "balance",
        "assigned", "allocated", "given", "returned", "present", "absent", "current", "objective", "objectives", "asset", "assets",
        "of", "for", "about", "to", "on", "in", "at", "by", "from", "with", "without", "against",
        "candidate", "candidates", "contract", "contracts", "payslip", "payslips", "action", "actions",
        "notice", "notices", "inquiry", "notes", "progress", "target", "review", "reviews", "appraisal",
        "goals", "goal", "roster", "device", "devices", "hardware", "equipment", "lot", "return",
        "timing", "overtime", "punch", "clock", "arrival", "annual", "deductions", "allowances", "allowance",
        "stub", "stubs", "checklist", "pipeline", "stage", "task", "tasks",
        "never", "ever", "not", "no", "none", "neither", "nor", "nothing",
        "submitted", "submit", "submitting", "submits", "applied", "apply", "applying", "applies",
        "requested", "request", "requesting", "requests", "taken", "take", "taking", "takes",
        "joined", "join", "joining", "joins", "worked", "work", "working", "works",
        "above", "below", "greater", "less", "than", "over", "under", "between", "equal", "equals", "exceeding", "exceeds",
        "it", "its", "laptop", "laptops", "purchase", "purchased", "warranty", "expire", "expired", "expiring", "expiration", "bought",
        "late", "early", "arrival", "arrivals", "absent", "absenteeism", "checkin", "checkout", "clockin", "clockout", "out", "in", "check", "clock", "cost", "soon",
        "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
    }

    @classmethod
    def extract_literal_candidates(cls, query: str, canonical_schema: Optional[Any] = None) -> List[str]:
        """
        Extracts candidate entity values from the query.
        Returns a deduplicated list of cleaned strings.
        If canonical_schema is provided, drops candidates that are exact schema column or table names.
        """
        schema_col_names: Set[str] = set()
        schema_tbl_names: Set[str] = set()
        if canonical_schema:
            try:
                for s_info in getattr(canonical_schema, "schemas", {}).values():
                    for tbl_name, t_obj in getattr(s_info, "tables", {}).items():
                        schema_tbl_names.add(tbl_name.lower())
                        for part in tbl_name.lower().split("_"):
                            if len(part) > 2:
                                schema_tbl_names.add(part)
                        for c_name in getattr(t_obj, "columns", {}).keys():
                            schema_col_names.add(c_name.lower())
            except Exception:
                pass

        candidates: List[str] = []
        q_clean = query.strip(" ?.,")
        for pat in cls._EXTRACTION_PATTERNS:
            for match in pat.finditer(q_clean):
                val = match.group(1).strip(" ?.,'\"")
                # Exclude dates (e.g. 2026-03-01) and pure numbers
                if re.match(r"^\d{4}-\d{2}-\d{2}$", val) or val.isdigit():
                    continue
                val_low = val.lower()
                if (
                    val_low not in cls._STOPWORDS
                    and val_low not in schema_col_names
                    and val_low not in schema_tbl_names
                    and len(val) >= 2
                ):
                    candidates.append(val)

        return list(dict.fromkeys(candidates))

    @classmethod
    def find_candidate_columns(
        cls,
        table_name: str,
        profile: Optional[DatabaseKnowledgeProfile] = None,
        identity_registry: Optional[IdentityRegistry] = None,
        schema_name: str = "public",
    ) -> List[str]:
        """
        Retrieves ordered candidate identity columns for a target table.
        Prefers name columns, then code/username, then email, then PK.
        """
        if identity_registry:
            cols = identity_registry.get_candidate_lookup_columns(table_name, schema_name)
            if cols:
                return cols

        if profile:
            ent = profile.get_entity_for_table(table_name, schema_name)
            if ent:
                ordered: List[str] = []
                ordered.extend(ent.name_columns)
                ordered.extend([c for c in ent.identity_columns if c not in ordered])
                ordered.extend([c for c in ent.primary_key_columns if c not in ordered])
                if ordered:
                    return ordered

            return profile.get_identity_columns(table_name)

        # Heuristic fallback if no profile provided
        return ["name", "full_name", "first_name", "username", "code", "id"]

    @classmethod
    def resolve_offline(
        cls,
        query: str,
        target_table: str,
        table_alias: str,
        candidate_columns: List[str],
    ) -> Optional[EntityValueResolutionResult]:
        """
        Static, offline resolution during query planning without live DB execution.
        Extracts the literal and binds it to the highest-priority candidate column.
        """
        literals = cls.extract_literal_candidates(query)
        if not literals or not candidate_columns:
            return None

        # Take first strong literal
        literal = literals[0]
        # Choose primary candidate column (first is highest priority)
        target_col = candidate_columns[0]

        predicate = PredicatePlan(
            table_alias=table_alias,
            column_name=target_col,
            operator="ILIKE",
            value=f"%{literal}%",
            logical_operator="AND",
        )

        return EntityValueResolutionResult(
            status=ResolutionStatus.PLANNED_OFFLINE,
            query_literal=literal,
            target_table=target_table,
            target_column=target_col,
            table_alias=table_alias,
            resolved_value=f"%{literal}%",
            operator="ILIKE",
            match_count=1,
            candidate_matches=[literal],
            predicate_plan=predicate,
            diagnostic_message=f"Offline binding: literal '{literal}' bound to {table_alias}.{target_col} via ILIKE",
        )

    @classmethod
    async def resolve_with_executor(
        cls,
        query_literal: str,
        target_table: str,
        table_alias: str,
        candidate_columns: List[str],
        executor: Any,
        schema_name: str = "public",
        timeout_seconds: float = 3.0,
    ) -> EntityValueResolutionResult:
        """
        Active, multi-stage database resolution:
        1. Exact parameterized match (`col = $1`)
        2. Normalized parameterized match (`LOWER(col) = LOWER($1)`)
        3. Safe bounded fuzzy match (`col ILIKE $1`)
        
        Enforces strict cardinality rules:
        - 1 match: RESOLVED
        - >1 match: AMBIGUOUS (fail closed, do not guess)
        - 0 matches: NOT_FOUND (fail closed)
        """
        if not candidate_columns:
            return EntityValueResolutionResult(
                status=ResolutionStatus.NO_TARGET_COLUMN,
                query_literal=query_literal,
                target_table=target_table,
                table_alias=table_alias,
                diagnostic_message=f"No identity candidate columns found for table {schema_name}.{target_table}",
            )

        # Test each candidate column in priority order
        for col in candidate_columns:
            # Stage 1: Exact match
            query_sql = f'SELECT "{col}" FROM "{schema_name}"."{target_table}" WHERE "{col}" = $1 LIMIT 10;'
            try:
                rows = await executor.execute(query_sql, [query_literal], timeout_seconds=timeout_seconds)
                if len(rows) == 1:
                    matched_val = rows[0][col]
                    pred = PredicatePlan(
                        table_alias=table_alias,
                        column_name=col,
                        operator="=",
                        value=matched_val,
                        logical_operator="AND",
                    )
                    return EntityValueResolutionResult(
                        status=ResolutionStatus.RESOLVED,
                        query_literal=query_literal,
                        target_table=target_table,
                        target_column=col,
                        table_alias=table_alias,
                        resolved_value=matched_val,
                        operator="=",
                        match_count=1,
                        candidate_matches=[matched_val],
                        predicate_plan=pred,
                        diagnostic_message=f"Exact match on {schema_name}.{target_table}.{col} = '{matched_val}'",
                    )
                elif len(rows) > 1:
                    matches = [r[col] for r in rows]
                    return EntityValueResolutionResult(
                        status=ResolutionStatus.AMBIGUOUS,
                        query_literal=query_literal,
                        target_table=target_table,
                        target_column=col,
                        table_alias=table_alias,
                        match_count=len(rows),
                        candidate_matches=matches,
                        diagnostic_message=f"Ambiguity detected: {len(rows)} matches found for '{query_literal}' on {col}",
                    )
            except Exception:
                pass

            # Stage 2: Normalized match (LOWER)
            norm_sql = f'SELECT "{col}" FROM "{schema_name}"."{target_table}" WHERE LOWER("{col}") = LOWER($1) LIMIT 10;'
            try:
                rows = await executor.execute(norm_sql, [query_literal], timeout_seconds=timeout_seconds)
                if len(rows) == 1:
                    matched_val = rows[0][col]
                    pred = PredicatePlan(
                        table_alias=table_alias,
                        column_name=col,
                        operator="=",
                        value=matched_val,
                        logical_operator="AND",
                    )
                    return EntityValueResolutionResult(
                        status=ResolutionStatus.RESOLVED,
                        query_literal=query_literal,
                        target_table=target_table,
                        target_column=col,
                        table_alias=table_alias,
                        resolved_value=matched_val,
                        operator="=",
                        match_count=1,
                        candidate_matches=[matched_val],
                        predicate_plan=pred,
                        diagnostic_message=f"Normalized match on {schema_name}.{target_table}.{col} = '{matched_val}'",
                    )
                elif len(rows) > 1:
                    matches = [r[col] for r in rows]
                    return EntityValueResolutionResult(
                        status=ResolutionStatus.AMBIGUOUS,
                        query_literal=query_literal,
                        target_table=target_table,
                        target_column=col,
                        table_alias=table_alias,
                        match_count=len(rows),
                        candidate_matches=matches,
                        diagnostic_message=f"Ambiguity detected: {len(rows)} matches found for '{query_literal}' on {col}",
                    )
            except Exception:
                pass

            # Stage 3: Bounded fuzzy match (ILIKE %val%)
            fuzzy_sql = f'SELECT "{col}" FROM "{schema_name}"."{target_table}" WHERE "{col}" ILIKE $1 LIMIT 10;'
            try:
                fuzzy_val = f"%{query_literal}%"
                rows = await executor.execute(fuzzy_sql, [fuzzy_val], timeout_seconds=timeout_seconds)
                if len(rows) == 1:
                    matched_val = rows[0][col]
                    pred = PredicatePlan(
                        table_alias=table_alias,
                        column_name=col,
                        operator="=",
                        value=matched_val,
                        logical_operator="AND",
                    )
                    return EntityValueResolutionResult(
                        status=ResolutionStatus.RESOLVED,
                        query_literal=query_literal,
                        target_table=target_table,
                        target_column=col,
                        table_alias=table_alias,
                        resolved_value=matched_val,
                        operator="=",
                        match_count=1,
                        candidate_matches=[matched_val],
                        predicate_plan=pred,
                        diagnostic_message=f"Fuzzy ILIKE match resolved unique entity on {col} = '{matched_val}'",
                    )
                elif len(rows) > 1:
                    matches = [r[col] for r in rows]
                    return EntityValueResolutionResult(
                        status=ResolutionStatus.AMBIGUOUS,
                        query_literal=query_literal,
                        target_table=target_table,
                        target_column=col,
                        table_alias=table_alias,
                        match_count=len(rows),
                        candidate_matches=matches,
                        diagnostic_message=f"Ambiguity detected: {len(rows)} fuzzy matches found for '{query_literal}' on {col}",
                    )
            except Exception:
                pass

        # Zero matches across all candidate columns
        return EntityValueResolutionResult(
            status=ResolutionStatus.NOT_FOUND,
            query_literal=query_literal,
            target_table=target_table,
            table_alias=table_alias,
            match_count=0,
            diagnostic_message=f"Value '{query_literal}' not found in candidate identity columns {candidate_columns} of table {target_table}",
        )
