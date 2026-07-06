import re
from typing import Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)

def normalize_numeric(value: Any) -> float | None:
    """
    Normalizes string numbers into floats.
    Handles accounting format: $(18,394) -> -18394.0
    Strips currency symbols anywhere in the string before checking for parens.
    """
    if value is None:
        return None
    
    if isinstance(value, (int, float)):
        return float(value)
        
    s = str(value).strip()
    if not s or s.lower() in ("none", "null", "n/a", "-", "—"):
        return None
        
    # Strip currency symbols and whitespace globally
    # E.g. "$", "€", "£", "¥", "₹", " ", ","
    clean_s = re.sub(r'[\$€£¥₹\s,]', '', s)
    
    # Check for accounting negative format: (18394)
    is_negative = False
    if clean_s.startswith('(') and clean_s.endswith(')'):
        is_negative = True
        clean_s = clean_s[1:-1]
    elif clean_s.startswith('-'):
        is_negative = True
        clean_s = clean_s[1:]
        
    try:
        num = float(clean_s)
        return -num if is_negative else num
    except ValueError:
        return None


def detect_label_column_with_confidence(rec: Any) -> Tuple[str, float]:
    """
    Detects the label column dynamically based on heuristics.
    Returns (column_name, confidence).
    """
    if not rec or not hasattr(rec, "values") or not rec.values:
        return ("Row", 0.0)
        
    keys = list(rec.values.keys())
    if not keys:
        return ("Row", 0.0)
        
    # 1. Check for explicit parser hint
    hint = getattr(rec, "label_column_hint", None)
    if hint and hint in keys:
        return (hint, 1.0)
        
    # 2. Check for string column vs numeric majority
    numeric_counts = 0
    string_cols = []
    
    for k, v in rec.values.items():
        if normalize_numeric(v) is not None:
            numeric_counts += 1
        else:
            if str(v).strip() and str(v).strip().lower() not in ("none", "null", "n/a", "-", "—"):
                string_cols.append(k)
                
    total_cols = len(keys)
    if numeric_counts > 0 and numeric_counts >= (total_cols / 2) and string_cols:
        return (string_cols[0], 0.8)
        
    # 3. Fallback to first column
    return (keys[0], 0.5)


def detect_label_column(rec: Any) -> str:
    """Wrapper that just returns the column name."""
    col, conf = detect_label_column_with_confidence(rec)
    if conf < 0.6:
        logger.debug(f"Low confidence ({conf}) for label column detection on row {getattr(rec, 'row_index', 'Unknown')}. Falling back to '{col}'.")
    return col
