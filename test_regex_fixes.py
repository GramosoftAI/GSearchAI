import re

def _is_task_query_heuristic(query: str) -> bool:
    query_lower = query.lower().strip()
    task_verbs_pattern = r"^(list|show|find|calculate|filter|get|display|compare|count|sum|sort|export|generate|retrieve)\b"
    comparison_pattern = r"(>|<|%|greater than|less than|above|below|at least|at most)"
    
    is_task_verb = bool(re.search(task_verbs_pattern, query_lower))
    has_comparison = bool(re.search(comparison_pattern, query_lower))
    
    parts = re.split(r'\band\b|\bwhere\b|\bor\b|,', query_lower)
    parts = [p.strip() for p in parts if p.strip()]
    has_multi_clause = len(parts) > 1
    
    if is_task_verb or (has_comparison and has_multi_clause):
        return True
    return False

_PREFERENCE_PATTERNS = re.compile(
    r"\b(remember|please remember|note (that|down)|"
    r"always (respond|answer|reply|format|use|show)|"
    r"from now on|i prefer|my preferred|please (always|remember)|"
    r"don'?t (use|do)|stop (using|doing)|never (use|do)|"
    r"not\s+.+\s+it'?s|upgrade\s+my|update\s+my|change\s+my|my\s+.*is|upgrad|upgrade|change|update)\b",
    re.IGNORECASE,
)

_DYNAMIC_FACT_PATTERN = re.compile(
    r".*?\b(?:my\s+)?"
    r"(?P<key>(?:(?:(?!and\b|where\b|or\b|,)[a-zA-Z0-9_\-']+)\s*){1,4}?)\s+"
    r"(?:is|are|=|:|was|not\s+.*?\s+(?:it'?s|into|to)|to|into|changed?\s+to|upgraded?\s+to|upgrad\s+into)\s+"
    r"(?P<value>(?:(?:(?!is\b|are\b|was\b|and\b|where\b|or\b|,)[a-zA-Z0-9%\s_\-'\.])\s*)+)",
    re.IGNORECASE,
)

_QUESTION_INDICATOR = re.compile(
    r"^\s*(what|how|when|where|why|who|which|is|are|do|does|did|can|could|would|will)\b|\?\s*$",
    re.IGNORECASE,
)

def _is_deterministic_preference_statement(query: str) -> bool:
    if _is_task_query_heuristic(query):
        return False
    if _QUESTION_INDICATOR.search(query):
        return False
    if _PREFERENCE_PATTERNS.search(query):
        return True
    if _DYNAMIC_FACT_PATTERN.search(query):
        return True
    return False

queries = [
    "List all transactions where the discount was greater than 25% and the sales amount was above ?5,000.",
    "My theme is dark mode",
    "The invoice status was updated to paid",
    "Show me orders where status is pending and amount is over 1000",
    "Always show currency in ?, not $"
]

for q in queries:
    print(f"Query: '{q}' -> {_is_deterministic_preference_statement(q)}")
