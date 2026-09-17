import re
import logging
from typing import Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)

ID_REGEX_PATTERN = r'(?=.*\d)[a-zA-Z0-9-]{5,}'

def get_schema_columns(dataset_schema: Optional[Dict[str, Any]], categorical_values: Optional[Dict[str, list]]) -> list[str]:
    cols = []
    if dataset_schema and "columns" in dataset_schema:
        # If columns dict has type information as values (e.g., 'object', 'string', 'int64')
        for col_name, col_info in dataset_schema["columns"].items():
            col_type = str(col_info).lower()
            # Include text, string, object, category types. Exclude purely numeric types (int, float, double)
            if any(t in col_type for t in ["str", "obj", "char", "text", "cat"]) or not any(n in col_type for n in ["int", "float", "double", "num"]):
                cols.append(col_name)
        if not cols:
            cols = list(dataset_schema["columns"].keys())
    elif isinstance(dataset_schema, dict) and dataset_schema:
        cols = list(dataset_schema.keys())
    elif categorical_values:
        cols = list(categorical_values.keys())
    return cols

def calculate_schema_overlap_score(query: str, dataset_schema: Optional[Dict[str, Any]], categorical_values: Optional[Dict[str, list]], name: Optional[str]) -> Tuple[int, int]:
    query_lower = query.lower()
    query_terms = set(re.findall(r'[a-zA-Z0-9]+', query_lower))
    
    schema_col_terms = set()
    cols = get_schema_columns(dataset_schema, categorical_values)
        
    for c in cols:
        col_str = str(c).lower()
        terms = re.findall(r'[a-zA-Z0-9]+', col_str)
        schema_col_terms.update(terms)
        
        # Domain synonym expansions
        if "mrp" in col_str or "price" in col_str:
            schema_col_terms.update(["mrp", "price", "pricing", "cost", "rate", "dlp"])
        if "part" in col_str or "description" in col_str or "item" in col_str:
            schema_col_terms.update(["part", "item", "sku", "code", "repair", "kit", "product"])
        
    schema_name_terms = set()
    if name:
        name_str = str(name).lower()
        schema_name_terms.update(re.findall(r'[a-zA-Z0-9]+', name_str))
        if "mrp" in name_str or "price" in name_str or "pricelist" in name_str:
            schema_name_terms.update(["mrp", "price", "pricing", "cost", "rate", "list", "edition"])
        
    categorical_match_count = 0
    if categorical_values:
        for vals in categorical_values.values():
            for v in vals:
                if isinstance(v, str):
                    v_lower = v.lower().strip()
                    if not v_lower:
                        continue
                        
                    # Prevent short numbers (like "5") from matching dozens of numeric columns
                    if v_lower.isdigit() and len(v_lower) < 4:
                        continue
                        
                    v_terms = set(re.findall(r'[a-zA-Z0-9]+', v_lower))
                    # Exact subset match of words
                    if v_terms and v_terms.issubset(query_terms):
                        categorical_match_count += len(v_terms)
                    # Substring match for longer strings
                    elif len(v_lower) > 3 and v_lower in query_lower:
                        categorical_match_count += 1
                        
    all_schema_terms = schema_col_terms | schema_name_terms
    generic_match_count = 0
    for qt in query_terms:
        if qt in all_schema_terms:
            generic_match_count += 1
        elif len(qt) > 3 and qt.endswith('ies') and qt[:-3] + 'y' in all_schema_terms:
            generic_match_count += 1
        elif len(qt) > 2 and qt.endswith('es') and qt[:-2] in all_schema_terms:
            generic_match_count += 1
        elif len(qt) > 2 and qt.endswith('s') and qt[:-1] in all_schema_terms:
            generic_match_count += 1
            
    return (categorical_match_count, generic_match_count)

DOC_SIGNALS = [
    "in the document", "in the pdf", "policy", "manual", "according to", "clause", "article",
    "guideline", "section", "paragraph", "doc mentions", "pdf mentions", "what is", "fuzzing",
    "definition", "explain", "describe", "benefits", "limitations", "categories", "approaches"
]

def evaluate_schema_overlap(
    query: str, 
    dataset_schema: Optional[Dict[str, Any]], 
    categorical_values: Optional[Dict[str, list]], 
    active_paths: list
) -> Tuple[bool, str, bool]:
    """
    Evaluates how strongly the natural language query overlaps with the tabular schema and its categorical values.
    
    Returns:
        (strict_schema_overlap: bool, reason: str, is_tabular: bool)
    """
    try:
        query_lower = query.lower()
        query_terms = set(re.findall(r'[a-zA-Z0-9]+', query_lower))

        # Semantic/document queries should NOT be hijacked by coincidental schema column matches
        has_doc_signal = any(sig in query_lower for sig in DOC_SIGNALS)
        
        name = active_paths[0] if active_paths else None
        term_overlap = calculate_schema_overlap_score(query, dataset_schema, categorical_values, name)
        total_term_overlap = term_overlap[0] + term_overlap[1]
        
        # Expanded Part No / Alphanumeric ID Regex (e.g. 29019292JA, EMP1006, APDA-102, MSS013002)
        # Must be within a single token that contains BOTH letters and digits
        all_tokens = re.findall(r'\b[a-zA-Z0-9_-]{4,15}\b', query)
        doc_code_prefixes = ("IR", "RFC", "ISO", "IEEE", "NIST", "SP", "SEC", "DOC", "PUB")
        valid_id_tokens = [
            tok for tok in all_tokens
            if any(c.isalpha() for c in tok) and any(c.isdigit() for c in tok)
            and not any(tok.upper().startswith(p) for p in doc_code_prefixes)
        ]
        has_id_regex = bool(valid_id_tokens)
        
        # Domain keywords indicating spreadsheet/tabular entity queries
        tabular_domain_kws = {"mrp", "part", "price", "hsn", "sku", "item", "kit", "repair", "cost", "details", "list", "edition", "oem", "model", "salary", "employee", "payroll", "wage"}
        has_domain_kw = bool(query_terms & tabular_domain_kws)
        
        # Concrete Analytic verbs for tabular aggregations (avoiding generic "what", "which")
        analytic_verbs = {"average", "avg", "total", "sum", "count", "how many", "max", "min", "highest", "lowest"}
        has_analytic_verb = bool(query_terms & analytic_verbs)

        if has_doc_signal and not (has_id_regex or has_domain_kw or term_overlap[0] > 0):
            return False, "document_semantic_signals_predominate", False
        
        # Final decision logic:
        # Require categorical match OR specific ID OR explicit tabular domain keyword + match OR true analytical aggregation verb
        strict_schema_overlap = (
            term_overlap[0] > 0 or # Explicit categorical match is an instant win
            (term_overlap[1] >= 1 and has_id_regex) or # Looking up specific row by Part No / ID
            (term_overlap[1] >= 1 and has_domain_kw) or # Specific tabular domain inquiry (e.g. MRP, part, price, salary)
            (term_overlap[1] >= 2 and has_analytic_verb and not has_doc_signal) # True analytical aggregation on multiple columns
        )
        
        if strict_schema_overlap:
            reason = f"strict_schema_overlap (cat_score: {term_overlap[0]}, gen_score: {term_overlap[1]}, id: {has_id_regex}, verb: {has_analytic_verb})"
            if term_overlap[0] == 0:
                logger.warning(f"⚠️ FORCING TABULAR OVERRIDE with zero categorical matches! Reason: {reason}")
            return True, reason, True
        else:
            return False, "weak_or_zero_schema_overlap", False
    except Exception as e:
        logger.error(f"Schema overlap evaluation failed: {e}")
        return False, f"schema_check_failed: {e}", False
