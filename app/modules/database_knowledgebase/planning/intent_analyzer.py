"""Query Intent Analyzer

Deterministic extraction and semantic classification of natural language queries
into structural query intent requirements.
"""

from enum import Enum
import datetime
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, ConfigDict, Field

from .models import AggregateFunction, IntentType, OrderDirection


class TemporalIntent(str, Enum):
    """Classification of temporal and currency scope for HR queries."""
    CURRENT = "CURRENT"          # Active / current record (e.g. current salary, active contract)
    TODAY = "TODAY"              # Current day (e.g. present today, punch today)
    THIS_WEEK = "THIS_WEEK"      # Current week
    THIS_MONTH = "THIS_MONTH"    # Current month
    LATEST = "LATEST"            # Most recent / latest record
    DATE_EXACT = "DATE_EXACT"    # Specific date
    DATE_RANGE = "DATE_RANGE"    # Range between dates
    HISTORICAL = "HISTORICAL"    # Historical / past records
    ALL = "ALL"                  # Unbounded


class ExtractedTemporalConstraint(BaseModel):
    """Temporal constraint extracted from query."""
    model_config = ConfigDict(extra="forbid")
    
    constraint_type: str  # EXACT_YEAR, RELATIVE_DAYS, RELATIVE_MONTHS
    value: Any
    raw_match: str


class ExtractedAggregation(BaseModel):
    """Aggregation requirement extracted from query."""
    model_config = ConfigDict(extra="forbid")

    function: AggregateFunction
    target_concept: Optional[str] = None
    raw_match: str


class ExtractedRanking(BaseModel):
    """Ranking or limit requirement extracted from query."""
    model_config = ConfigDict(extra="forbid")

    direction: OrderDirection = OrderDirection.DESC
    limit: Optional[int] = None
    target_metric: Optional[str] = None
    raw_match: str


class ExtractedPredicate(BaseModel):
    """Filter constraint extracted from query."""
    model_config = ConfigDict(extra="forbid")

    target_concept: str
    operator: str
    value: Any
    raw_match: str


class QueryIntentAnalysis(BaseModel):
    """Complete analysis output from QueryIntentAnalyzer."""
    model_config = ConfigDict(extra="forbid")

    user_query: str
    intent: IntentType
    aggregations: List[ExtractedAggregation] = Field(default_factory=list)
    ranking: Optional[ExtractedRanking] = None
    temporal_constraints: List[ExtractedTemporalConstraint] = Field(default_factory=list)
    temporal_intent: TemporalIntent = TemporalIntent.CURRENT
    predicates: List[ExtractedPredicate] = Field(default_factory=list)
    grouping_required: bool = False
    grouping_concept: Optional[str] = None
    requires_joins: bool = False
    confidence: float = 1.0
    detected_entities: List[str] = Field(default_factory=list)
    candidates: List[Any] = Field(default_factory=list)


class QueryIntentAnalyzer:
    """
    Performs deterministic parsing and semantic classification of query requirements.
    """

    # Aggregation keywords mapping
    AGG_PATTERNS = [
        (r"\b(total|sum of|sum|revenue)\b", AggregateFunction.SUM),
        (r"\b(average|mean|avg)\b", AggregateFunction.AVG),
        (r"\b(how many|count of|count|number of|item counts|total count|headcount)\b", AggregateFunction.COUNT),
        (r"\b(highest|maximum|max|most|top)\b", AggregateFunction.MAX),
        (r"\b(lowest|minimum|min|least|bottom)\b", AggregateFunction.MIN),
    ]

    # Year regex & Exact ISO Date regex
    YEAR_PATTERN = re.compile(r"\b(19\d\d|20\d\d)\b")
    DATE_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

    WORD_TO_NUM = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12
    }

    @classmethod
    def _parse_time_string(cls, time_str: str) -> Optional[str]:
        t_clean = time_str.strip().lower()
        # 1. Colloquial phrases: "half past ten at night", "quarter past 9", "half past 10"
        colloquial = re.match(
            r"(half|quarter)\s+(past|to)\s+([a-zA-Z0-9]+)(?:\s+(?:at\s+night|in\s+the\s+(?:night|evening|pm)|pm|am))?",
            t_clean
        )
        if colloquial:
            rel = colloquial.group(1)
            direction = colloquial.group(2)
            hour_str = colloquial.group(3)
            hour = cls.WORD_TO_NUM.get(hour_str, int(hour_str) if hour_str.isdigit() else None)
            if hour is not None:
                is_pm = any(kw in t_clean for kw in ("night", "evening", "pm"))
                if rel == "half":
                    minute = 30
                elif rel == "quarter" and direction == "past":
                    minute = 15
                elif rel == "quarter" and direction == "to":
                    minute = 45
                    hour = hour - 1 if hour > 1 else 12
                else:
                    minute = 0

                if is_pm and hour < 12:
                    hour += 12
                elif not is_pm and hour == 12 and "am" in t_clean:
                    hour = 0
                return f"{hour:02d}:{minute:02d}:00"

        # 2. Standard numeric format: "10:30 PM", "9 AM", "22:30"
        m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t_clean)
        if not m:
            return None
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        meridiem = m.group(3)
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}:00"

    # Relative time expressions
    RELATIVE_TIME_PATTERNS = [
        (r"\blast month\b", "RELATIVE_MONTHS", 1),
        (r"\bthis month\b", "RELATIVE_MONTHS", 0),
        (r"\blast week\b", "RELATIVE_WEEKS", 1),
        (r"\bthis week\b", "RELATIVE_WEEKS", 0),
        (r"\blast (\d+)\s+days\b", "RELATIVE_DAYS", lambda m: int(m.group(1))),
        (r"\bpast (\d+)\s+days\b", "RELATIVE_DAYS", lambda m: int(m.group(1))),
        (r"\byesterday\b", "RELATIVE_DAYS", 1),
        (r"\btoday\b", "RELATIVE_DAYS", 0),
        (r"\bthis morning\b", "RELATIVE_DAYS", 0),
        (r"\bon friday\b", "DAY_OF_WEEK", 5),
        (r"\bfriday\b", "DAY_OF_WEEK", 5),
        (r"\bthis year\b", "RELATIVE_YEARS", 0),
        (r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b", "CALENDAR_MONTH", lambda m: m.group(1).lower()),
    ]

    # Ranking patterns (e.g. "top 5", "first 10", "highest spending", "most frequently")
    TOP_N_PATTERN = re.compile(r"\btop\s+(\d+)\b", re.IGNORECASE)
    FIRST_N_PATTERN = re.compile(r"\bfirst\s+(\d+)\b", re.IGNORECASE)
    LIMIT_N_PATTERN = re.compile(r"\blimit\s+(\d+)\b", re.IGNORECASE)

    # Comparison / predicate patterns
    PRICE_GT_PATTERN = re.compile(r"\b(above|greater than|more than|>)\s*\$?(\d+(?:\.\d+)?)\b", re.IGNORECASE)
    PRICE_LT_PATTERN = re.compile(r"\b(below|less than|under|<)\s*\$?(\d+(?:\.\d+)?)\b", re.IGNORECASE)
    STATUS_PATTERN = re.compile(r"\bstatus\s*(?:is|=|:)\s*['\"]?(\w+)['\"]?\b", re.IGNORECASE)

    @classmethod
    def analyze(cls, query: str) -> QueryIntentAnalysis:
        """
        Analyze the natural-language query and return a structured QueryIntentAnalysis.
        """
        q_lower = query.lower()

        # 1. Extract Temporal Constraints
        temporals: List[ExtractedTemporalConstraint] = []
        predicates: List[ExtractedPredicate] = []

        for match in cls.DATE_PATTERN.finditer(query):
            date_str = match.group(1)
            temporals.append(
                ExtractedTemporalConstraint(
                    constraint_type="EXACT_DATE",
                    value=date_str,
                    raw_match=match.group(0),
                )
            )
            predicates.append(
                ExtractedPredicate(
                    target_concept="date",
                    operator="=",
                    value=date_str,
                    raw_match=match.group(0),
                )
            )

        for match in cls.YEAR_PATTERN.finditer(query):
            # Avoid matching year inside YYYY-MM-DD
            if re.search(r"\d{4}-\d{2}-\d{2}", query[max(0, match.start() - 1):min(len(query), match.end() + 7)]):
                continue
            year_val = int(match.group(1))
            temporals.append(
                ExtractedTemporalConstraint(
                    constraint_type="EXACT_YEAR",
                    value=year_val,
                    raw_match=match.group(0),
                )
            )

        for pat, c_type, val_fn in cls.RELATIVE_TIME_PATTERNS:
            for match in re.finditer(pat, q_lower):
                val = val_fn(match) if callable(val_fn) else val_fn
                temporals.append(
                    ExtractedTemporalConstraint(
                        constraint_type=c_type,
                        value=val,
                        raw_match=match.group(0),
                    )
                )

        # 2. Extract Ranking & Limits (before aggregations to disambiguate 'top N' from MAX)
        ranking: Optional[ExtractedRanking] = None
        top_match = cls.TOP_N_PATTERN.search(q_lower)
        first_match = cls.FIRST_N_PATTERN.search(q_lower)
        limit_match = cls.LIMIT_N_PATTERN.search(q_lower)

        if top_match:
            ranking = ExtractedRanking(
                direction=OrderDirection.DESC,
                limit=int(top_match.group(1)),
                raw_match=top_match.group(0),
            )
        elif first_match:
            ranking = ExtractedRanking(
                direction=OrderDirection.ASC,
                limit=int(first_match.group(1)),
                raw_match=first_match.group(0),
            )
        elif limit_match:
            ranking = ExtractedRanking(
                direction=OrderDirection.ASC,
                limit=int(limit_match.group(1)),
                raw_match=limit_match.group(0),
            )
        elif "highest" in q_lower or "most frequently" in q_lower or "spent the most" in q_lower or "selling the most" in q_lower:
            ranking = ExtractedRanking(
                direction=OrderDirection.DESC,
                limit=1 if "highest" in q_lower or "the most" in q_lower else None,
                raw_match="highest/most",
            )
        elif "lowest" in q_lower or "least" in q_lower or "earliest" in q_lower:
            ranking = ExtractedRanking(
                direction=OrderDirection.ASC,
                limit=1 if "lowest" in q_lower or "least" in q_lower or "earliest" in q_lower else None,
                raw_match="lowest/least/earliest",
            )

        # 3. Extract Aggregations
        aggregations: List[ExtractedAggregation] = []
        # If query has an explicit top-N ranking limit (e.g. "top 5 highest paid employees"),
        # words like "top" and "highest" are ranking/ordering criteria, not aggregate projections!
        if not (ranking and ranking.limit and ranking.limit > 1):
            for pat, agg_func in cls.AGG_PATTERNS:
                for match in re.finditer(pat, q_lower):
                    # Do not treat "top" as MAX if it was part of "top <N>"
                    if agg_func == AggregateFunction.MAX and match.group(0).lower() == "top" and top_match:
                        continue
                    # Do not treat "most" as MAX if it is part of "most recent" (temporal intent)
                    if agg_func == AggregateFunction.MAX and match.group(0).lower() == "most" and "most recent" in q_lower:
                        continue
                    aggregations.append(
                        ExtractedAggregation(
                            function=agg_func,
                            raw_match=match.group(0),
                        )
                    )

            # Disambiguate "how many total" / "total count" / "total number of" -> COUNT, not SUM
            has_count = any(a.function == AggregateFunction.COUNT for a in aggregations)
            if has_count:
                aggregations = [
                    a for a in aggregations
                    if not (a.function == AggregateFunction.SUM and a.raw_match.lower() == "total")
                ]
            elif any(a.function == AggregateFunction.SUM and a.raw_match.lower() == "total" for a in aggregations):
                # If query mentions "total" but no financial/monetary/numeric terms, it is counting entities (e.g. "total candidates")
                has_numeric_metric = any(m in q_lower for m in ("expenditure", "spending", "payroll", "salary", "wage", "amount", "budget", "revenue", "cost", "price", "point", "points", "hour", "hours", "balance", "days"))
                if not has_numeric_metric:
                    aggregations = [
                        ExtractedAggregation(function=AggregateFunction.COUNT, raw_match="total") if (a.function == AggregateFunction.SUM and a.raw_match.lower() == "total") else a
                        for a in aggregations
                    ]

            # Disambiguate "how many years of experience" / "how many children" -> Scalar attribute lookup, not COUNT
            if any(a.function == AggregateFunction.COUNT and a.raw_match.lower() == "how many" for a in aggregations):
                if re.search(r"\bhow many\s+(?:years\s+(?:of\s+)?)?experience\b", q_lower) or re.search(r"\bhow many\s+children\b", q_lower):
                    aggregations = [a for a in aggregations if not (a.function == AggregateFunction.COUNT and a.raw_match.lower() == "how many")]
                elif re.search(r"\bhow many\s+hours\b", q_lower):
                    # "how many hours" is a SUM of worked duration, not record COUNT
                    aggregations = [a for a in aggregations if not (a.function == AggregateFunction.COUNT and a.raw_match.lower() == "how many")]
                    aggregations.append(ExtractedAggregation(function=AggregateFunction.SUM, target_concept="hours", raw_match="how many hours"))

            # Overtime queries: "how much overtime", "total overtime", or "most overtime" -> SUM
            if any(w in q_lower for w in ("how much overtime", "total overtime", "overtime worked", "most overtime")) and not any(a.function == AggregateFunction.SUM and a.target_concept == "overtime" for a in aggregations):
                aggregations.append(ExtractedAggregation(function=AggregateFunction.SUM, target_concept="overtime", raw_match="overtime"))

            # Absenteeism queries: "highest absenteeism" or "days was ... absent" -> SUM of days absent
            if any(w in q_lower for w in ("absenteeism", "days was", "days absent")) and not any(a.target_concept == "absenteeism" for a in aggregations):
                aggregations.append(ExtractedAggregation(function=AggregateFunction.SUM, target_concept="absenteeism", raw_match="absenteeism"))

            # Late arrivals queries: "most late arrivals" or "how many times was ... late" -> COUNT
            if any(w in q_lower for w in ("late arrivals", "most late", "leave early", "early out")) or (any(w in q_lower for w in ("how many times", "times was")) and any(w in q_lower for w in ("late", "early"))):
                if not any(a.target_concept == "late" for a in aggregations):
                    aggregations.append(ExtractedAggregation(function=AggregateFunction.COUNT, target_concept="late", raw_match="late"))

        # 4. Extract Predicates (predicates initialized earlier to preserve exact date predicates)
        gt_match = cls.PRICE_GT_PATTERN.search(q_lower)
        if gt_match:
            predicates.append(
                ExtractedPredicate(
                    target_concept="amount/price",
                    operator=">",
                    value=float(gt_match.group(2)),
                    raw_match=gt_match.group(0),
                )
            )

        lt_match = cls.PRICE_LT_PATTERN.search(q_lower)
        if lt_match:
            predicates.append(
                ExtractedPredicate(
                    target_concept="amount/price",
                    operator="<",
                    value=float(lt_match.group(2)),
                    raw_match=lt_match.group(0),
                )
            )

        status_match = cls.STATUS_PATTERN.search(q_lower)
        if status_match and status_match.group(1).lower() not in {"the", "a", "an", "this", "that", "each", "all", "our", "their", "its"}:
            predicates.append(
                ExtractedPredicate(
                    target_concept="status",
                    operator="=",
                    value=status_match.group(1),
                    raw_match=status_match.group(0),
                )
            )
        elif re.search(r"\bpending\b", q_lower):
            predicates.append(
                ExtractedPredicate(
                    target_concept="status",
                    operator="=",
                    value="pending",
                    raw_match="pending",
                )
            )
        elif re.search(r"\bfailed\b", q_lower):
            predicates.append(
                ExtractedPredicate(
                    target_concept="status",
                    operator="=",
                    value="failed",
                    raw_match="failed",
                )
            )
        elif re.search(r"\bcompleted\b", q_lower):
            predicates.append(
                ExtractedPredicate(
                    target_concept="status",
                    operator="=",
                    value="completed",
                    raw_match="completed",
                )
            )
        elif "never placed" in q_lower or "without" in q_lower:
            predicates.append(
                ExtractedPredicate(
                    target_concept="existence",
                    operator="IS NULL",
                    value=None,
                    raw_match="never placed",
                )
            )

        # Specific order/item ID matching: e.g. "order #500" or "order 1042"
        id_match = re.search(r"\border\s*#?(\d+)\b", q_lower)
        if id_match:
            predicates.append(
                ExtractedPredicate(
                    target_concept="order_id",
                    operator="=",
                    value=int(id_match.group(1)),
                    raw_match=id_match.group(0),
                )
            )

        # Time-of-day matching: e.g. "after 10:30 PM", "before 9:00 AM", "after half past ten at night"
        time_match = re.search(
            r"\b(after|before|since|until|past)\s+((?:(?:half|quarter)\s+(?:past|to)\s+[a-zA-Z0-9]+(?:\s+(?:at\s+night|in\s+the\s+(?:night|evening|pm)|pm|am))?)|\d{1,2}(?::\d{2})?(?:\s*(?:am|pm))?)\b",
            q_lower
        )
        if time_match:
            prep = time_match.group(1).lower()
            time_val = cls._parse_time_string(time_match.group(2))
            if time_val:
                op = ">" if prep in ("after", "since", "past") else "<"
                predicates.append(
                    ExtractedPredicate(
                        target_concept="time_of_day",
                        operator=op,
                        value=time_val,
                        raw_match=time_match.group(0),
                    )
                )

        # Product name matching: e.g. "product X"
        prod_match = re.search(r"\bproduct\s+([a-zA-Z0-9_-]+)\b", query, re.IGNORECASE)
        if prod_match and prod_match.group(1).lower() not in {"name", "category", "price", "catalog"}:
            predicates.append(
                ExtractedPredicate(
                    target_concept="product_name",
                    operator="ILIKE",
                    value=f"%{prod_match.group(1)}%",
                    raw_match=prod_match.group(0),
                )
            )

        # HRMS Domain Predicates
        if re.search(r"\b(?:came|come|arrived?|showed?\s+up)\s+(?:in\s+)?late\b|\blate\b", q_lower):
            predicates.append(
                ExtractedPredicate(
                    target_concept="late_status",
                    operator="=",
                    value="late_come",
                    raw_match="late",
                )
            )
        if re.search(r"\b(?:left|leave|depart(?:ed)?)\s+early\b|\bearly\s+out\b", q_lower):
            predicates.append(
                ExtractedPredicate(
                    target_concept="early_status",
                    operator="=",
                    value="early_out",
                    raw_match="early out",
                )
            )
        if re.search(r"\b(?:worked\s+)?overtime\b", q_lower):
            predicates.append(
                ExtractedPredicate(
                    target_concept="overtime",
                    operator=">",
                    value=0,
                    raw_match="overtime",
                )
            )
        if re.search(r"\b(?:currently\s+)?on\s+leave\b|\babsent\b|\babsence\b", q_lower):
            predicates.append(
                ExtractedPredicate(
                    target_concept="leave_status",
                    operator="=",
                    value="approved",
                    raw_match="on leave",
                )
            )
        if re.search(r"\bshift\s+starts?\s+early\b|\bearly\s+shift\b", q_lower):
            predicates.append(
                ExtractedPredicate(
                    target_concept="shift_early",
                    operator="<",
                    value="09:30:00",
                    raw_match="shift starts early",
                )
            )

        # Department Predicates: e.g. "in the Engineering department", "department is Sales", "in Engineering"
        dept_match = re.search(r"\b(?:in\s+(?:the\s+)?|department\s+(?:is\s+|of\s+)?)([a-zA-Z0-9_\s\-]+?)\s+department\b", query, re.IGNORECASE)
        if not dept_match:
            dept_match = re.search(r"\bdepartment\s*(?:is|=|:)\s*['\"]?([a-zA-Z0-9_\s\-]+?)['\"]?(?:\b|$)", query, re.IGNORECASE)
        if not dept_match:
            dept_match = re.search(r"\b(?:in|of)\s+(Engineering|Sales|Marketing|Finance|HR|Human Resources|Development|Operations|Support|Management|Accounts|Legal|Design)\b", query, re.IGNORECASE)

        if dept_match:
            dept_name = dept_match.group(1).strip(" '\"")
            if dept_name.lower() not in {"the", "a", "an", "each", "all", "our", "their", "its", "which", "what"}:
                predicates.append(
                    ExtractedPredicate(
                        target_concept="department",
                        operator="ILIKE",
                        value=f"%{dept_name}%",
                        raw_match=dept_match.group(0),
                    )
                )

        # Job Position / Role Predicates: e.g. 'job position "Software Engineer"', 'job position Software Engineer'
        pos_match = re.search(r"\bjob\s+position\s*(?:is|=|:)?\s*['\"]([^'\"]+)['\"]", query, re.IGNORECASE)
        if not pos_match:
            pos_match = re.search(r"\bposition\s+['\"]([^'\"]+)['\"]", query, re.IGNORECASE)
        if not pos_match:
            pos_match = re.search(r"\brole\s+['\"]([^'\"]+)['\"]", query, re.IGNORECASE)
        if not pos_match:
            pos_match = re.search(r"\b(?:job\s+position|designation)\s+(?:is|=|of)?\s*([a-zA-Z0-9_\s\-]+?)(?:\?|$)", query, re.IGNORECASE)
        if pos_match:
            pos_name = pos_match.group(1).strip(" '\"")
            if pos_name.lower() not in {"the", "a", "an", "each", "all", "our", "their", "its", "which", "what"}:
                predicates.append(
                    ExtractedPredicate(
                        target_concept="job_position",
                        operator="ILIKE",
                        value=f"%{pos_name}%",
                        raw_match=pos_match.group(0),
                    )
                )

        # Performance Rating Predicates: e.g. 'performance rating of 5', 'rating of 5'
        rating_match = re.search(r"\b(?:performance\s+)?rating\s+(?:of\s+|is\s+|=)?\s*(\d+(?:\.\d+)?)\b", q_lower)
        if rating_match:
            r_val = float(rating_match.group(1)) if "." in rating_match.group(1) else int(rating_match.group(1))
            predicates.append(
                ExtractedPredicate(
                    target_concept="rating",
                    operator="=",
                    value=r_val,
                    raw_match=rating_match.group(0),
                )
            )

        # Relative Date Predicates
        if re.search(r"\btoday\b|\bthis morning\b", q_lower):
            predicates.append(
                ExtractedPredicate(
                    target_concept="relative_date",
                    operator="=",
                    value="today",
                    raw_match="today",
                )
            )
        elif re.search(r"\byesterday\b", q_lower):
            predicates.append(
                ExtractedPredicate(
                    target_concept="relative_date",
                    operator="=",
                    value="yesterday",
                    raw_match="yesterday",
                )
            )
        elif re.search(r"\bthis week\b", q_lower):
            predicates.append(
                ExtractedPredicate(
                    target_concept="relative_date",
                    operator=">=",
                    value="this_week",
                    raw_match="this week",
                )
            )
        elif re.search(r"\blast week\b", q_lower):
            predicates.append(
                ExtractedPredicate(
                    target_concept="relative_date",
                    operator="=",
                    value="last_week",
                    raw_match="last week",
                )
            )
        elif re.search(r"\bthis month\b", q_lower):
            predicates.append(
                ExtractedPredicate(
                    target_concept="relative_date",
                    operator=">=",
                    value="this_month",
                    raw_match="this month",
                )
            )
        elif re.search(r"\bon friday\b|\bfriday\b", q_lower):
            predicates.append(
                ExtractedPredicate(
                    target_concept="relative_date",
                    operator="=",
                    value="friday",
                    raw_match="friday",
                )
            )

        # Calendar Month Predicates: e.g. "for August", "in August"
        month_match = re.search(r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b", q_lower)
        if month_match:
            m_name = month_match.group(1).lower()
            month_numbers = {
                "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
                "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
            }
            m_num = month_numbers[m_name]
            import calendar
            curr_year = datetime.datetime.now().year
            last_day = calendar.monthrange(curr_year, m_num)[1]
            start_str = f"{curr_year}-{m_num:02d}-01"
            end_str = f"{curr_year}-{m_num:02d}-{last_day:02d}"
            predicates.append(
                ExtractedPredicate(
                    target_concept="date_range_start",
                    operator=">=",
                    value=start_str,
                    raw_match=m_name,
                )
            )
            predicates.append(
                ExtractedPredicate(
                    target_concept="date_range_end",
                    operator="<=",
                    value=end_str,
                    raw_match=m_name,
                )
            )

        # Late and Early Status Predicates
        if any(w in q_lower for w in ("late", "late arrivals", "late arrival", "late come")):
            predicates.append(
                ExtractedPredicate(
                    target_concept="late_status",
                    operator="=",
                    value="late_come",
                    raw_match="late",
                )
            )
        elif any(w in q_lower for w in ("leave early", "left early", "early out", "early departure")):
            predicates.append(
                ExtractedPredicate(
                    target_concept="early_status",
                    operator="=",
                    value="early_out",
                    raw_match="early",
                )
            )

        # Asset Predicates
        if any(w in q_lower for w in ("expiring soon", "expire soon", "expiring")):
            predicates.append(
                ExtractedPredicate(
                    target_concept="expiring_soon",
                    operator="=",
                    value="soon",
                    raw_match="expiring soon",
                )
            )
        elif any(w in q_lower for w in ("are expired", "is expired", "which assets assigned to .* are expired")):
            predicates.append(
                ExtractedPredicate(
                    target_concept="expired_asset",
                    operator="<",
                    value="CURRENT_DATE",
                    raw_match="expired",
                )
            )

        laptop_m = re.search(r"\b(laptop|desktop|monitor|tablet|vehicle)\b", q_lower)
        if laptop_m and not any(p.target_concept == "asset_name" for p in predicates):
            predicates.append(
                ExtractedPredicate(
                    target_concept="asset_name",
                    operator="ILIKE",
                    value=f"%{laptop_m.group(1)}%",
                    raw_match=laptop_m.group(0),
                )
            )

        asset_id_m = re.search(r"\b(?:asset\s+(?:id\s+)?|owns\s+asset\s+)(\d+)\b", q_lower)
        if asset_id_m:
            predicates.append(
                ExtractedPredicate(
                    target_concept="asset_id",
                    operator="=",
                    value=int(asset_id_m.group(1)),
                    raw_match=asset_id_m.group(0),
                )
            )

        # Absenteeism / Leave Predicates
        if "absent" in q_lower:
            predicates.append(
                ExtractedPredicate(
                    target_concept="leave_status",
                    operator="=",
                    value="approved",
                    raw_match="absent",
                )
            )
            if "today" in q_lower:
                predicates.append(
                    ExtractedPredicate(
                        target_concept="absent_today",
                        operator="=",
                        value="today",
                        raw_match="absent today",
                    )
                )

        # 5. Grouping Detection (e.g. "per customer", "by category", "in each department", "for each customer")
        grouping_required = False
        grouping_concept: Optional[str] = None

        group_match = re.search(r"\b(?:by|per|for each|in each|grouped by)\s+([a-zA-Z0-9_]+)\b", q_lower)
        which_group_match = re.search(r"\bwhich\s+([a-zA-Z0-9_]+)\s+has\s+(?:the\s+)?(most|highest|lowest|least|maximum|minimum)\b", q_lower)
        who_group_match = re.search(r"\b(?:who|which employee)\s+(?:has\s+|had\s+|took\s+|taken\s+|worked\s+)?(?:the\s+)?(most|highest|lowest|least|maximum|minimum)\b", q_lower)

        if group_match:
            candidate_concept = group_match.group(1).strip()
            # Exclude grammatical stopwords and metric words
            if candidate_concept not in {
                "the", "a", "an", "all", "order", "asc", "desc",
                "salary", "budget", "amount", "price", "count", "sum", "avg", "min", "max",
                "total", "highest", "lowest", "least", "most", "average"
            }:
                grouping_required = True
                grouping_concept = candidate_concept
        elif which_group_match:
            candidate_concept = which_group_match.group(1).strip()
            if candidate_concept not in {"the", "a", "an", "all", "one"}:
                grouping_required = True
                grouping_concept = candidate_concept
                superlative = which_group_match.group(2).lower()
                direction = OrderDirection.DESC if superlative in ("most", "highest", "maximum") else OrderDirection.ASC
                ranking = ExtractedRanking(direction=direction, limit=1, raw_match=superlative)
        elif who_group_match:
            grouping_required = True
            grouping_concept = "employee"
            superlative = who_group_match.group(1).lower()
            direction = OrderDirection.DESC if superlative in ("most", "highest", "maximum") else OrderDirection.ASC
            ranking = ExtractedRanking(direction=direction, limit=1, raw_match=superlative)
        elif aggregations and ("each" in q_lower or "per" in q_lower or "frequently" in q_lower):
            each_match = re.search(r"\beach\s+([a-zA-Z0-9_]+)\b", q_lower)
            if each_match:
                candidate_concept = each_match.group(1).strip()
                if candidate_concept not in {"the", "a", "an", "all", "order", "asc", "desc"}:
                    grouping_required = True
                    grouping_concept = candidate_concept
            else:
                grouping_required = True

        # 6. Intent Classification
        if ranking is not None and (ranking.limit or ranking.direction):
            intent = IntentType.SELECT_RANKING
        elif temporals and grouping_required:
            intent = IntentType.SELECT_TIME_SERIES
        elif grouping_required or (aggregations and not ranking):
            intent = IntentType.SELECT_AGGREGATE
        elif len(predicates) >= 2 or ("never" in q_lower or "without" in q_lower):
            intent = IntentType.SELECT_FILTER_MULTI
        elif "compare" in q_lower or "difference" in q_lower:
            intent = IntentType.SELECT_COMPARISON
        elif predicates:
            intent = IntentType.SELECT_FILTER_MULTI
        else:
            intent = IntentType.SELECT_POINT

        # 7. Generalized Enterprise Semantic Entity Extraction
        STOPWORDS = {
            "show", "list", "tell", "find", "give", "display", "get", "fetch", "all",
            "each", "every", "the", "a", "an", "and", "or", "with", "their", "its",
            "them", "in", "on", "at", "to", "for", "from", "by", "of", "is", "are",
            "was", "were", "belong", "belongs", "does", "do", "did", "have", "has",
            "had", "which", "what", "where", "who", "whom", "how", "many", "much",
            "total", "sum", "average", "avg", "min", "max", "maximum", "minimum", "highest", "lowest",
            "count", "top", "first", "last", "limit", "status", "price", "amount",
            "salary", "budget", "cost", "date", "year", "month", "day", "working",
            "assigned", "there", "about", "detail", "details", "info", "information",
            "active", "inactive", "pending", "approved", "rejected", "completed",
            "cancelled", "open", "closed", "enabled", "disabled", "new", "old",
            "current", "previous", "historical", "latest", "highest", "lowest",
            # SQL keywords that must never be treated as entities
            "select", "insert", "update", "delete", "drop", "alter", "create", "truncate",
            "grant", "revoke", "table", "database", "schema", "view", "index", "column",
            "into", "values", "where", "join", "inner", "left", "right", "outer", "full",
            "group", "having", "offset", "union", "null", "not", "true", "false",
            # Structural, metadata, time, and verbal qualifiers
            "record", "records", "row", "rows", "entry", "entries", "item", "items",
            "number", "numbers", "hire", "hired", "hiring", "join", "joined", "joining",
            "come", "came", "coming", "go", "went", "going", "arrive", "arrived", "arriving",
            "paid", "pay", "paying", "earn", "earns", "earned", "earning", "earnings",
            "make", "makes", "making", "made", "receive", "receives", "received", "receiving",
            "spend", "spends", "spent", "spending", "basic", "main", "valid", "invalid", "code", "codes",
            "level", "value", "values", "recently", "recent", "between", "after", "before",
            "over", "under", "greater", "less", "more", "than", "equal", "above", "below",
            "building", "office", "name", "title",
            "company", "firm", "organization", "corp", "corporation", "business", "team", "system",
            # Prepositions and auxiliary verbs
            "along", "across", "through", "upon", "within", "without", "amid", "among",
            "doe", "does", "did", "done", "doing",
            "each", "every", "other", "another", "this", "that", "these", "those",
            "year", "years", "month", "months", "week", "weeks", "day", "days", "time", "times",
            # Months
            "january", "february", "march", "april", "may", "june", "july", "august",
            "september", "october", "november", "december", "jan", "feb", "mar", "apr",
            "jun", "jul", "aug", "sep", "oct", "nov", "dec",
            # Ranking and superlatives
            "largest", "smallest", "highest", "lowest", "bottom", "top", "least", "most", "best", "worst",
            # Common column attribute concepts (not domain tables)
            "email", "emails", "phone", "phones", "address", "addresses", "city", "state", "country",
            "salary", "salaries", "wage", "wages", "compensation", "income", "budget", "budgets", "amount", "amounts", "price", "prices", "cost", "costs",
        }

        def _singularize(word: str) -> str:
            w = word.lower()
            if w in STOPWORDS:
                return w
            if w.endswith("ees"):
                return w[:-1]
            elif w.endswith("ies") and len(w) > 4:
                return w[:-3] + "y"
            elif (w.endswith("xes") or w.endswith("shes") or w.endswith("ches") or w.endswith("sses") or w.endswith("zes")) and len(w) > 4:
                return w[:-2]
            elif w.endswith("s") and len(w) > 3 and not w.endswith("ss"):
                return w[:-1]
            return w

        # 1. Normalize compound business entities in query
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
            # Attendance & HRMS concepts
            (r"\bentered?\s+(?:the\s+)?office\b", "attendance"),
            (r"\b(?:clock|punch|check)[ed]*[\s-]in\b", "attendance"),
            (r"\b(?:clock|punch|check)[ed]*[\s-]out\b", "attendance"),
            (r"\b(?:swipe|swiped|scan|scanned)[\s-]in\b", "attendance"),
            (r"\b(?:swipe|swiped|scan|scanned)[\s-]out\b", "attendance"),
            (r"\b(?:left|leave)\s+(?:the\s+)?office\b", "attendance"),
            (r"\boffice\s+(?:entry|arrival|departure|time)\b", "attendance"),
            (r"\barrived?\s+(?:at\s+)?(?:the\s+)?office\b", "attendance"),
            (r"\b(?:work(?:ing)?|office)\s+attendance\b", "attendance"),
            (r"\b(?:came|come|arrived?|showed?\s+up)\s+(?:in\s+)?late\b", "late_come attendance"),
            (r"\blate\s+(?:to\s+)?(?:work|office|come|arrival|arriv)\b", "late_come attendance"),
            (r"\btardy\b", "late_come attendance"),
            (r"\b(?:left|leave|depart(?:ed)?)\s+early\b", "early_out attendance"),
            (r"\b(?:check(?:ed)?|clock(?:ed)?|punch(?:ed)?)\s+out\s+early\b", "early_out attendance"),
            (r"\b(?:currently\s+)?on\s+leave\b", "leave_request"),
            (r"\btak(?:e|ing)\s+leave\b", "leave_request"),
            (r"\babsent\b", "leave_request attendance"),
            (r"\babsence\b", "leave_request attendance"),
            (r"\b(?:worked\s+)?overtime\b", "overtime attendance"),
            (r"\bextra\s+hours?\b", "overtime attendance"),
            (r"\b(?:work\s+)?shift\s+starts?\s+(?:early|late)?\b", "shift shift_schedule"),
            (r"\bearly\s+shift\b", "shift shift_schedule"),
            (r"\bnight\s+shift\b", "shift shift_schedule"),
            (r"\bshift\s+schedule\b", "shift_schedule"),
        ]
        norm_q = q_lower
        for pat, canonical_ent in compound_patterns:
            norm_q = re.sub(pat, canonical_ent, norm_q)

        candidate_entities: List[str] = []

        def _is_valid_entity(raw_term: str, singular_term: str) -> bool:
            return (
                bool(singular_term)
                and len(singular_term) >= 3
                and not singular_term.isdigit()
                and any(c.isalpha() for c in singular_term)
                and raw_term not in STOPWORDS
                and singular_term not in STOPWORDS
                and singular_term not in candidate_entities
            )

        # 2. Multi-entity relation phrasing patterns:
        # e.g. "show employees and their departments", "employees with leave_request"
        rel_pairs = re.findall(r"\b([a-zA-Z_]{3,})\s+(?:and|with|along\s+with)\s+(?:their|its)?\s*([a-zA-Z_]{3,})\b", norm_q)
        for e1, e2 in rel_pairs:
            s1, s2 = _singularize(e1), _singularize(e2)
            if _is_valid_entity(e1, s1):
                candidate_entities.append(s1)
            if _is_valid_entity(e2, s2):
                candidate_entities.append(s2)

        # "which employees belong to each department", "which department does each employee belong to"
        belong_pairs = re.findall(r"\bwhich\s+([a-zA-Z_]{3,})\s+(?:belong\s+to\s+(?:each|the)?\s*([a-zA-Z_]{3,})|does\s+(?:each)?\s*([a-zA-Z_]{3,})\s+belong\s+to)\b", norm_q)
        for m in belong_pairs:
            e1 = m[0] if m[0] else ""
            e2 = m[1] if m[1] else (m[2] if m[2] else "")
            s1 = _singularize(e1) if e1 else ""
            s2 = _singularize(e2) if e2 else ""
            if e1 and _is_valid_entity(e1, s1):
                candidate_entities.append(s1)
            if e2 and _is_valid_entity(e2, s2):
                candidate_entities.append(s2)

        # "employees working on projects", "departments and the employees in them"
        in_work_pairs = re.findall(r"\b([a-zA-Z_]{3,})\s+(?:working\s+on|assigned\s+to|in|of)\s+(?:each|the)?\s*([a-zA-Z_]{3,})\b", norm_q)
        for e1, e2 in in_work_pairs:
            s1, s2 = _singularize(e1), _singularize(e2)
            if _is_valid_entity(e1, s1):
                candidate_entities.append(s1)
            if _is_valid_entity(e2, s2):
                candidate_entities.append(s2)

        # 3. Fallback keyword scanning for domain nouns
        from app.core.config import settings
        is_schema_grounded = getattr(settings, "entity_resolution_mode", "legacy") == "schema_grounded"
        extracted_candidates = []

        if is_schema_grounded:
            from .pos_extractor import POSCandidateExtractor
            extracted_candidates = POSCandidateExtractor.extract(norm_q)
            for cand in extracted_candidates:
                if cand.is_ngram:
                    continue  # Bigrams are passed in candidates list for Phase 2/3 concept binding
                # Do not treat likely verbs as required domain entity tables by default
                if cand.likely_verb:
                    continue
                s = _singularize(cand.text)
                if _is_valid_entity(cand.text, s):
                    candidate_entities.append(s)
        else:
            for token in re.findall(r"\b[a-zA-Z_]{3,}\b", norm_q):
                if token in STOPWORDS:
                    continue
                s = _singularize(token)
                if _is_valid_entity(token, s):
                    candidate_entities.append(s)

        # If multiple distinct entities are requested and intent was SELECT_POINT, promote to SELECT_JOIN
        has_multiple_entities = len(candidate_entities) >= 2
        requires_joins = has_multiple_entities
        if has_multiple_entities and intent == IntentType.SELECT_POINT:
            intent = IntentType.SELECT_JOIN

        # Determine Temporal Intent
        if "today" in q_lower or "this morning" in q_lower:
            temporal_intent = TemporalIntent.TODAY
        elif "this week" in q_lower:
            temporal_intent = TemporalIntent.THIS_WEEK
        elif "this month" in q_lower:
            temporal_intent = TemporalIntent.THIS_MONTH
        elif any(w in q_lower for w in ("latest", "most recent", "last punch", "last record", "last payslip", "last salary", "last pay", "last basic", "recent pay stub", "last paid")):
            temporal_intent = TemporalIntent.LATEST
        elif any(w in q_lower for w in ("history", "historical", "previous", "past", "former")):
            temporal_intent = TemporalIntent.HISTORICAL
        elif any(w in q_lower for w in ("all payslips", "all records", "all contracts", "all attendance", "list all", "all salary", "all shift", "all candidates", "all past", "all taken", "all leave", "all bank", "all past okrs", "all onboarding", "all disciplinary", "each department", "breakdown by work type")):
            temporal_intent = TemporalIntent.ALL
        elif temporals:
            if any(t.constraint_type == "EXACT_DATE" for t in temporals):
                temporal_intent = TemporalIntent.DATE_EXACT
            else:
                temporal_intent = TemporalIntent.DATE_RANGE
        else:
            temporal_intent = TemporalIntent.CURRENT

        # Deduplicate predicates while preserving order
        dedup_predicates = []
        seen_pred = set()
        for p in predicates:
            key = (p.target_concept, p.operator, str(p.value))
            if key not in seen_pred:
                seen_pred.add(key)
                dedup_predicates.append(p)
        predicates = dedup_predicates

        return QueryIntentAnalysis(
            user_query=query,
            intent=intent,
            aggregations=aggregations,
            ranking=ranking,
            temporal_constraints=temporals,
            temporal_intent=temporal_intent,
            predicates=predicates,
            grouping_required=grouping_required,
            grouping_concept=grouping_concept,
            requires_joins=requires_joins,
            confidence=0.95,
            detected_entities=candidate_entities,
            candidates=extracted_candidates,
        )
