"""Phase 2 Knowledge Layer: Profiler Inference Rules

Deterministic role and unit hint inference based on column name tokens,
data types, and value distributions.
Zero LLM dependencies.

Roles:
id | name | date | timestamp | amount | quantity | boolean | enum | duration | text | code | unknown

Unit hints:
seconds | minutes | hours | ms | currency | percent | none
"""

import re
from typing import Optional, List, Dict, Any

_TOKEN_SPLIT_REGEX = re.compile(
    r"[_\-.\s]+|(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
)


def get_column_tokens(column_name: str) -> List[str]:
    """Tokenize column name by underscore, hyphen, space, and camelCase transitions."""
    if not column_name:
        return []
    return [t.lower() for t in _TOKEN_SPLIT_REGEX.split(str(column_name).strip()) if t]


def infer_role_and_unit(
    column_name: str,
    data_type: str,
    is_primary_key: bool = False,
    is_foreign_key: bool = False,
    distinct_count: Optional[int] = None,
    min_val: Optional[Any] = None,
    max_val: Optional[Any] = None,
) -> tuple[str, Optional[str]]:
    """Deterministically infer (role, unit_hint) from column metadata and tokens."""
    tokens = get_column_tokens(column_name)
    raw_col = column_name.lower()
    dtype = (data_type or "").lower()

    # 1. Primary or foreign key -> 'id'
    if is_primary_key or is_foreign_key:
        return "id", None

    if tokens and tokens[-1] == "id":
        return "id", None
    if tokens and tokens[0] == "id" and len(tokens) == 1:
        return "id", None
    if raw_col.endswith("_id") or raw_col.endswith("_uuid") or raw_col.endswith("_guid"):
        return "id", None
    if raw_col in ("uuid", "guid"):
        return "id", None

    # 2. Boolean
    if "bool" in dtype:
        return "boolean", None
    if tokens and tokens[0] in ("is", "has", "can", "should", "was"):
        return "boolean", None
    if raw_col.startswith("is_") or raw_col.startswith("has_") or raw_col.startswith("can_"):
        return "boolean", None

    # 3. Timestamp / Date
    if "timestamp" in dtype or "datetime" in dtype:
        return "timestamp", None
    if "date" in dtype and "time" not in dtype:
        return "date", None
    if tokens and any(t in ("timestamp", "datetime") for t in tokens):
        return "timestamp", None
    if raw_col.endswith("_at") or raw_col.endswith("_time") or raw_col.endswith("timestamp"):
        return "timestamp", None
    if raw_col.endswith("_date") or raw_col.startswith("date_") or "date" in tokens:
        return "date", None

    # 4. Duration and time units
    # e.g. at_work_second, duration_ms, latency_sec, elapsed_minutes, duration_hours, flight_minutes, shift_hours, billing_hr
    duration_unit_map = {
        "ms": "ms",
        "millisecond": "ms",
        "milliseconds": "ms",
        "sec": "seconds",
        "second": "seconds",
        "seconds": "seconds",
        "min": "minutes",
        "minute": "minutes",
        "minutes": "minutes",
        "hr": "hours",
        "hour": "hours",
        "hours": "hours",
    }
    for tok in tokens:
        if tok in duration_unit_map:
            if any(t in ("duration", "elapsed", "latency", "work", "time", "delay", "wait", "spent", "length", "flight", "shift", "billing", "run", "sleep") for t in tokens) or tok in ("sec", "second", "seconds", "ms", "millisecond", "milliseconds", "minutes", "hours", "minute", "hour"):
                return "duration", duration_unit_map[tok]

    if "duration" in tokens or "latency" in tokens or "elapsed" in tokens:
        return "duration", "seconds"

    # 5. Percent / Percentage
    if any(t in ("pct", "percent", "percentage", "rate", "ratio") for t in tokens):
        # If float or numeric, unit is percent
        if any(num_t in dtype for num_t in ("int", "float", "numeric", "decimal", "real", "double")):
            return "quantity", "percent"

    # 6. Currency / Amount
    currency_tokens = ("amount", "amt", "price", "cost", "fee", "balance", "revenue", "salary", "wage", "total", "subtotal", "tax")
    if any(t in currency_tokens for t in tokens):
        if any(num_t in dtype for num_t in ("int", "float", "numeric", "decimal", "real", "double", "money")):
            return "amount", "currency"

    # 7. Quantity / Count
    quantity_tokens = ("quantity", "qty", "count", "num", "number", "items", "units", "score", "points", "size", "length", "weight", "volume", "height", "width", "depth")
    if any(t in quantity_tokens for t in tokens):
        if any(num_t in dtype for num_t in ("int", "float", "numeric", "decimal", "real", "double")):
            return "quantity", None

    # 8. Name
    name_tokens = ("name", "title", "firstname", "lastname", "fullname", "label")
    if any(t in name_tokens for t in tokens):
        return "name", None

    # 9. Code / Slug
    code_tokens = ("code", "slug", "sku", "key", "zip", "postal", "postalcode", "zipcode", "hash", "iso")
    if any(t in code_tokens for t in tokens):
        return "code", None

    # 10. Enum (low cardinality or explicit enum type)
    if "enum" in dtype:
        return "enum", None
    if distinct_count is not None and 1 <= distinct_count <= 25:
        if any(str_t in dtype for str_t in ("char", "text", "varchar")):
            return "enum", None

    if any(t in ("status", "state", "type", "category", "kind", "priority", "level", "tier", "grade", "mode") for t in tokens):
        return "enum", None

    # 11. Text / Long String
    if "text" in dtype or "lob" in dtype or "character varying" in dtype or "varchar" in dtype:
        if any(t in ("description", "comment", "note", "notes", "body", "content", "summary", "detail", "details", "message", "bio", "prompt") for t in tokens):
            return "text", None
        return "text", None

    # 12. Fallback numbers
    if any(num_t in dtype for num_t in ("int", "float", "numeric", "decimal", "real", "double")):
        return "quantity", None

    return "unknown", None
