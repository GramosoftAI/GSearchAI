"""Phase 3 Step 3.3 QuestionAnalyzer (No LLM)

Parses a natural language question into a structured QuestionFrame:
- normalized text & filtered query tokens (English & Tanglish stop words removed)
- time range: relative & absolute intervals mapped to [start_date, end_date]
- numbers with units: e.g. "8 hours" -> 28800 seconds, "10 percent" -> 0.10, "15 minutes" -> 900 seconds
- comparison operators: (<, <=, >, >=, =, between)
- aggregation cues: total, sum, count, average, per, top N, highest, lowest
- entity span candidates: capitalized spans, quoted terms
- literal values: emails, phones, numbers kept separate as literals (never searched in value index)
"""

import re
import json
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from pydantic import BaseModel, Field

# Load stop words from config
_STOPWORDS_FILE = Path(__file__).resolve().parent / "stopwords.json"
_STOPWORDS_SET = set()
if _STOPWORDS_FILE.exists():
    try:
        with open(_STOPWORDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            _STOPWORDS_SET.update(data.get("english_stopwords", []))
            _STOPWORDS_SET.update(data.get("tanglish_function_words", []))
    except Exception:
        pass


class TimeRange(BaseModel):
    start_date: Optional[str] = None  # YYYY-MM-DD
    end_date: Optional[str] = None    # YYYY-MM-DD
    expression: str = ""


class UnitValue(BaseModel):
    raw_text: str
    numeric_value: float
    unit: str  # seconds, minutes, hours, percent, count, currency, plain
    canonical_seconds: Optional[float] = None


class ComparisonFilter(BaseModel):
    operator: str  # <, <=, >, >=, =, between
    raw_cue: str
    target_value: Optional[float] = None
    target_unit: Optional[str] = None


class QuestionFrame(BaseModel):
    original_question: str
    normalized_text: str
    tokens: List[str] = Field(default_factory=list)
    time_range: Optional[TimeRange] = None
    unit_values: List[UnitValue] = Field(default_factory=list)
    comparison: Optional[ComparisonFilter] = None
    aggregation_cues: List[str] = Field(default_factory=list)
    entity_candidates: List[str] = Field(default_factory=list)
    literal_values: List[str] = Field(default_factory=list)


# Regex patterns
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_PATTERN = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3,4}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_DATE_ISO_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_DATE_PATTERN = re.compile(r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})\b")


def extract_literals(text: str) -> Tuple[List[str], str]:
    """Extract literals (emails, phones, numbers) and return remaining clean text."""
    literals = []
    cleaned = text

    # Extract emails
    for m in _EMAIL_PATTERN.finditer(text):
        em = m.group(0)
        literals.append(em)
        cleaned = cleaned.replace(em, " ")

    # Extract phones
    for m in _PHONE_PATTERN.finditer(cleaned):
        ph = m.group(0)
        # Avoid matching small numbers as phones
        if len(re.sub(r"\D", "", ph)) >= 7:
            literals.append(ph)
            cleaned = cleaned.replace(ph, " ")

    return literals, cleaned


def extract_unit_values(text: str) -> List[UnitValue]:
    """Extract numbers with units (e.g., '8 hours' -> 28800s, '10 percent' -> 10)."""
    units = []
    # Pattern: number + optional space + unit
    pattern = re.compile(
        r"\b(\d+(?:\.\d+)?)\s*(hours?|hrs?|seconds?|secs?|minutes?|mins?|percent|%|k|lakhs?|cr|crores?)\b",
        re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        raw_match = m.group(0)
        val = float(m.group(1))
        u = m.group(2).lower()

        canon_sec = None
        std_unit = u
        if u in ("hours", "hour", "hrs", "hr"):
            std_unit = "hours"
            canon_sec = val * 3600.0
        elif u in ("minutes", "minute", "mins", "min"):
            std_unit = "minutes"
            canon_sec = val * 60.0
        elif u in ("seconds", "second", "secs", "sec"):
            std_unit = "seconds"
            canon_sec = val
        elif u in ("percent", "%"):
            std_unit = "percent"

        units.append(UnitValue(
            raw_text=raw_match,
            numeric_value=val,
            unit=std_unit,
            canonical_seconds=canon_sec,
        ))
    return units


def extract_time_range(text: str, ref_date: date) -> Optional[TimeRange]:
    """Extract time expressions in English and Tanglish into absolute date intervals."""
    lower = text.lower()

    # Dates: ISO (YYYY-MM-DD) or Slash/Hyphen (DD/MM/YYYY, MM/DD/YYYY)
    raw_dates = _DATE_PATTERN.findall(text)
    iso_dates = []
    for rd in raw_dates:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", rd):
            iso_dates.append(rd)
        else:
            parts = [int(p) for p in re.split(r"[-/]", rd)]
            if len(parts) == 3 and parts[2] >= 1900:
                if parts[1] <= 12 and parts[0] <= 31:
                    d_day, d_month, d_year = parts[0], parts[1], parts[2]
                elif parts[0] <= 12 and parts[1] <= 31:
                    d_month, d_day, d_year = parts[0], parts[1], parts[2]
                else:
                    d_day, d_month, d_year = parts[0], parts[1], parts[2]
                iso_dates.append(f"{d_year:04d}-{d_month:02d}-{d_day:02d}")

    if len(iso_dates) >= 2:
        return TimeRange(start_date=iso_dates[0], end_date=iso_dates[1], expression="custom interval")
    elif len(iso_dates) == 1:
        if any(w in lower for w in ("after", "since", "from")):
            return TimeRange(start_date=iso_dates[0], end_date=None, expression=f"after {iso_dates[0]}")
        elif any(w in lower for w in ("before", "until", "to")):
            return TimeRange(start_date=None, end_date=iso_dates[0], expression=f"before {iso_dates[0]}")
        else:
            return TimeRange(start_date=iso_dates[0], end_date=iso_dates[0], expression=f"on {iso_dates[0]}")

    # Today / inniku
    if any(w in lower for w in ("today", "inniku", "iniku")):
        d_str = ref_date.isoformat()
        return TimeRange(start_date=d_str, end_date=d_str, expression="today")

    # Yesterday / nethu
    if any(w in lower for w in ("yesterday", "nethu", "netru")):
        y_str = (ref_date - timedelta(days=1)).isoformat()
        return TimeRange(start_date=y_str, end_date=y_str, expression="yesterday")

    # Last month / kadantha maatham / ponna maasam
    if any(w in lower for w in ("last month", "kadantha maatham", "kadantha maasam", "ponna maasam")):
        first_this_month = ref_date.replace(day=1)
        last_month_end = first_this_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return TimeRange(
            start_date=last_month_start.isoformat(),
            end_date=last_month_end.isoformat(),
            expression="last month",
        )

    # This month / indha maasam
    if any(w in lower for w in ("this month", "indha maasam", "indha maatham")):
        start_m = ref_date.replace(day=1)
        return TimeRange(start_date=start_m.isoformat(), end_date=ref_date.isoformat(), expression="this month")

    # Last week / kadantha vaaram
    if any(w in lower for w in ("last week", "kadantha vaaram", "ponna vaaram")):
        start_w = ref_date - timedelta(days=7)
        return TimeRange(start_date=start_w.isoformat(), end_date=ref_date.isoformat(), expression="last week")

    # Last N days
    m_days = re.search(r"last\s+(\d+)\s+days", lower)
    if m_days:
        n = int(m_days.group(1))
        return TimeRange(
            start_date=(ref_date - timedelta(days=n)).isoformat(),
            end_date=ref_date.isoformat(),
            expression=f"last {n} days",
        )

    return None


def extract_comparison(text: str, unit_values: List[UnitValue]) -> Optional[ComparisonFilter]:
    """Detect comparison operators (less than, more than, kela, keela, above, between)."""
    lower = text.lower()
    
    # Check unit target
    target_val = unit_values[0].canonical_seconds or unit_values[0].numeric_value if unit_values else None
    target_unit = unit_values[0].unit if unit_values else None

    if any(w in lower for w in ("less than", "below", "under", "kela", "keela", "<")):
        return ComparisonFilter(operator="<", raw_cue="less than / kela", target_value=target_val, target_unit=target_unit)
    if any(w in lower for w in ("more than", "greater than", "above", "over", ">")):
        return ComparisonFilter(operator=">", raw_cue="more than / above", target_value=target_val, target_unit=target_unit)
    if "between" in lower:
        return ComparisonFilter(operator="between", raw_cue="between")
    if any(w in lower for w in ("equal to", "equals", "=")):
        return ComparisonFilter(operator="=", raw_cue="equal", target_value=target_val, target_unit=target_unit)

    return None


def extract_aggregation_cues(text: str) -> List[str]:
    """Detect aggregation cues (total, sum, count, average, per, highest, top)."""
    lower = text.lower()
    cues = []
    mapping = {
        "total": ["total", "sum", "totl"],
        "count": ["count", "how many", "number of", "ethana"],
        "average": ["average", "avg", "mean"],
        "per": ["per", "each", "group by"],
        "highest": ["highest", "max", "maximum", "most", "top"],
        "lowest": ["lowest", "min", "minimum", "least"],
    }
    for cue_type, keywords in mapping.items():
        if any(kw in lower for kw in keywords):
            cues.append(cue_type)
    return cues


def extract_entity_candidates(text: str) -> List[str]:
    """Extract candidate entity spans from capitalized words, quotes, or distinct names."""
    candidates = []
    # Quoted text
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", text)
    candidates.extend([q.strip() for q in quoted if len(q.strip()) > 1])

    # Capitalized tokens (excluding beginning of sentence if only title case)
    words = text.split()
    for i, w in enumerate(words):
        clean_w = re.sub(r"[^a-zA-Z]", "", w)
        if clean_w and clean_w[0].isupper() and clean_w.lower() not in _STOPWORDS_SET:
            # Multi-word capitalization merge
            if i > 0 and candidates and words[i - 1].endswith(candidates[-1].split()[-1]):
                candidates[-1] = f"{candidates[-1]} {clean_w}"
            else:
                candidates.append(clean_w)

    return list(dict.fromkeys(candidates))


class QuestionAnalyzer:
    """Parses user question without LLM into QuestionFrame."""

    @staticmethod
    def analyze(question: str, reference_date: Optional[date] = None) -> QuestionFrame:
        if reference_date is None:
            reference_date = date.today()

        raw = (question or "").strip()
        literals, text_no_literals = extract_literals(raw)
        unit_values = extract_unit_values(text_no_literals)
        time_range = extract_time_range(raw, reference_date)
        comparison = extract_comparison(raw, unit_values)
        aggregation = extract_aggregation_cues(raw)
        entity_candidates = extract_entity_candidates(raw)

        # Tokenization & stop-word filtering
        clean_words = re.findall(r"[a-zA-Z0-9_]+", raw.lower())
        filtered_tokens = [w for w in clean_words if w not in _STOPWORDS_SET and len(w) > 1]

        # Normalized clean string
        normalized = " ".join(filtered_tokens)

        return QuestionFrame(
            original_question=raw,
            normalized_text=normalized,
            tokens=filtered_tokens,
            time_range=time_range,
            unit_values=unit_values,
            comparison=comparison,
            aggregation_cues=aggregation,
            entity_candidates=entity_candidates,
            literal_values=literals,
        )
