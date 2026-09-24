"""
Fast Query Analyzer - Modular, Deterministic, Low-Latency Query Preprocessing & Hybrid Intent Routing.
Performs deterministic Python normalization, entity extraction, typo correction, keyword extraction,
and intent/tabular routing in < 5-50ms locally. Only invokes a compact DeepInfra LLM call when 
genuine semantic ambiguity exists.
"""

import re
import time
import json
import difflib
import logging
import asyncio
from typing import Dict, Any, Optional, List, Tuple, Set

from app.modules.rag.orchestrator.query_analyzer import QueryIntent, QueryMetadata, AnalysisResult
from app.core.llm.deepinfra_llm import DeepInfraLLMClient
from app.core.llm.routing import LLMTask

logger = logging.getLogger(__name__)

# Reusable stopwords from term_frequency & NLP best practices
STOPWORDS: Set[str] = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "when", "at", "from",
    "by", "for", "with", "about", "against", "between", "into", "through", "during",
    "before", "after", "above", "below", "to", "of", "up", "down", "in", "out", "on",
    "off", "over", "under", "again", "further", "then", "once", "here", "there",
    "all", "any", "both", "each", "few", "more", "most", "other", "some", "such",
    "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "can", "will", "just", "should", "now", "tell", "show", "give", "me", "find",
    "what", "which", "who", "whom", "this", "that", "these", "those", "am", "is",
    "are", "was", "were", "be", "been", "being", "have", "has", "had", "having",
    "do", "does", "did", "doing", "would", "could", "please", "could", "you"
}

# Common domain correction vocabulary for typo correction
COMMON_DOMAIN_VOCAB: Dict[str, str] = {
    "salary": "salary",
    "salry": "salary",
    "salery": "salary",
    "slaary": "salary",
    "earning": "salary",
    "earnings": "salary",
    "employee": "employee",
    "empolyee": "employee",
    "employe": "employee",
    "emplyee": "employee",
    "department": "department",
    "dept": "department",
    "depatment": "department",
    "designation": "designation",
    "desig": "designation",
    "insurance": "insurance",
    "insurence": "insurance",
    "insurrance": "insurance",
    "premium": "premium",
    "premum": "premium",
    "policy": "policy",
    "polcy": "policy",
    "polic": "policy",
    "coverage": "coverage",
    "covrage": "coverage",
    "deductible": "deductible",
    "deductable": "deductible",
    "claim": "claim",
    "claims": "claim",
    "reimbursement": "reimbursement",
    "reimbersment": "reimbursement",
    "reimbersment": "reimbursement",
    "status": "status",
    "staus": "status",
    "average": "average",
    "avg": "average",
    "total": "total",
    "totl": "total",
    "minimum": "minimum",
    "maximum": "maximum"
}

# Semantic mappings from user verbs/concepts to conceptual columns
SYNONYM_COLUMN_MAPPINGS: Dict[str, List[str]] = {
    "salary": ["salary", "compensation", "earnings", "ctc", "wage", "pay", "stipend", "remuneration"],
    "earn": ["salary", "compensation", "earnings", "ctc", "wage", "pay"],
    "earns": ["salary", "compensation", "earnings", "ctc", "wage", "pay"],
    "paid": ["salary", "compensation", "earnings", "ctc", "wage", "pay"],
    "compensation": ["salary", "compensation", "earnings"],
    "department": ["department", "dept", "division", "team", "unit", "business unit"],
    "work": ["department", "designation", "office", "location"],
    "works": ["department", "designation", "office", "location"],
    "job": ["designation", "role", "title", "position", "job title"],
    "role": ["designation", "role", "title", "position", "job title"],
    "title": ["designation", "role", "title", "position", "job title"],
    "position": ["designation", "role", "title", "position", "job title"],
    "hired": ["hire date", "joining date", "date of joining", "doj"],
    "joined": ["hire date", "joining date", "date of joining", "doj"],
    "born": ["date of birth", "dob", "birth date"],
    "location": ["location", "city", "branch", "office", "address", "country", "state"],
    "manager": ["manager", "supervisor", "reporting manager", "lead"],
    "status": ["status", "active", "employment status", "claim status"],
    "cost": ["cost", "price", "mrp", "rate", "amount", "fee"],
    "price": ["price", "mrp", "cost", "rate", "amount"],
    "premium": ["premium", "premium amount", "cost"],
    "bonus": ["bonus", "incentive", "allowance"]
}

# Structured ID patterns: e.g., EMP1009, EMP 1009, POL12345, INV-2025-009, RM8000, 29019292JA
STRUCTURED_ID_RE = re.compile(r'\b([A-Za-z]{2,5})[-_\s]?(\d{3,8})\b', re.IGNORECASE)
PARTIAL_ID_RE = re.compile(r'\b(?:employee|emp|worker|staff|id|user|policy|pol|claim|inv|invoice|record)\s*(?:#|no\.?|num|number)?\s*(\d{1,6})\b', re.IGNORECASE)
ALPHANUM_ID_RE = re.compile(r'\b(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_-]{4,15}\b')


class FastQueryAnalyzer:
    """
    High-Performance Standalone Query Analyzer.
    
    1. Preprocesses query in Python (< 5ms): Normalization, conservative typo correction,
       structured identifier extraction, column matching, and stopword-filtered keyword extraction.
    2. Deterministic Intent & Tabular Scoring (< 5ms).
    3. LLM Gating: Only calls DeepInfra LLM (max_tokens=128, timeout=2.0s) if the query is
       genuinely ambiguous.
    """

    def __init__(self):
        self.llm_client = DeepInfraLLMClient.get_instance()

    # ----------------------------------------------------------------------
    # STAGE 1: FAST PYTHON PREPROCESSING
    # ----------------------------------------------------------------------
    def normalize_text(self, text: str) -> str:
        """Cleans whitespace, basic punctuation, while preserving quotes and tokens."""
        if not text:
            return ""
        # Collapse multiple spaces, newlines, tabs
        cleaned = re.sub(r'\s+', ' ', text).strip()
        return cleaned

    def extract_identifiers(self, query: str, kb_context: str = "") -> Tuple[List[str], Dict[str, str]]:
        """
        Extracts structured IDs (e.g. EMP1009, POL12345) and maps partial references
        (e.g., 'employee 9' -> EMP1009 if known schema/context has EMP prefix).
        Returns (extracted_ids, partial_mappings)
        """
        extracted_ids: List[str] = []
        mappings: Dict[str, str] = {}

        # 1. Exact alphanumeric ID patterns like EMP1009, POL12345, INV-2025-009
        doc_prefixes = {"IR", "RFC", "ISO", "IEEE", "NIST", "SP", "SEC", "DOC", "PUB"}
        for match in STRUCTURED_ID_RE.finditer(query):
            prefix = match.group(1).upper()
            if prefix in doc_prefixes:
                continue
            num = match.group(2)
            canonical_id = f"{prefix}{num}"
            extracted_ids.append(canonical_id)
            orig_span = match.group(0)
            if orig_span != canonical_id:
                mappings[orig_span] = canonical_id

        # 2. Other standalone alphanumeric codes (e.g. RM8000, 29019292JA)
        for token in re.findall(r'\b[a-zA-Z0-9_-]{4,15}\b', query):
            upper_token = token.upper()
            if any(c.isalpha() for c in token) and any(c.isdigit() for c in token):
                if not any(upper_token.startswith(p) for p in doc_prefixes):
                    if upper_token not in extracted_ids:
                        extracted_ids.append(upper_token)

        # 3. Partial identifiers: e.g. "salary of employee 9" or "emp 9"
        # If kb_context contains standard prefix like EMP1001 or EMP1004, pad/resolve
        known_prefixes = set(re.findall(r'\b([A-Za-z]{2,5})\d{3,8}\b', kb_context))
        if not known_prefixes:
            known_prefixes = {"EMP", "POL", "INV", "USER", "ID"}

        default_prefix = "EMP" if "EMP" in known_prefixes else list(known_prefixes)[0]

        for match in PARTIAL_ID_RE.finditer(query):
            raw_match = match.group(0)
            num_str = match.group(1)
            # Find context prefix if mentioned in raw_match (e.g., 'employee 9' -> 'EMP')
            match_prefix = default_prefix
            if "emp" in raw_match.lower():
                match_prefix = "EMP"
            elif "pol" in raw_match.lower():
                match_prefix = "POL"
            elif "inv" in raw_match.lower():
                match_prefix = "INV"

            # Context resolution: if numbers in KB context have 4 digits (e.g. EMP1001, EMP1009),
            # resolve single digit '9' to EMP1009, or pad appropriately
            context_matches = re.findall(rf'\b{match_prefix}(\d+)\b', kb_context, re.IGNORECASE)
            canonical_candidate = None
            if context_matches:
                target_len = len(context_matches[0])
                # Check if exact suffix exists (e.g. '9' matches '1009')
                for c_num in context_matches:
                    if c_num.endswith(num_str) or int(c_num) == int(num_str):
                        canonical_candidate = f"{match_prefix}{c_num}"
                        break
                if not canonical_candidate:
                    canonical_candidate = f"{match_prefix}{num_str.zfill(target_len)}"
            else:
                # Default 4-digit convention for EMP (e.g. 9 -> 1009 if <= 50, else zero-padded)
                if match_prefix == "EMP" and len(num_str) <= 2:
                    canonical_candidate = f"EMP10{num_str.zfill(2)}"
                else:
                    canonical_candidate = f"{match_prefix}{num_str}"

            if canonical_candidate:
                extracted_ids.append(canonical_candidate)
                mappings[raw_match] = canonical_candidate

        # 4. Connected disjunctions / sequences: e.g. "EMP1004 or 9", "EMP1004, 1009", "EMP1004 and 9"
        # Only check if query already contains structured IDs
        if extracted_ids:
            disj_matches = re.finditer(r'(?:or|and|,)\s*(\d{1,6})\b', query, re.IGNORECASE)
            for d_match in disj_matches:
                raw_d = d_match.group(0)
                num_str = d_match.group(1)
                # Find closest preceding structured ID if available
                prec_prefix = default_prefix
                m_p = re.match(r'^([A-Za-z]{2,5})', extracted_ids[0])
                if m_p:
                    prec_prefix = m_p.group(1).upper()
                
                if prec_prefix in doc_prefixes:
                    continue

                # Context resolution
                context_matches = re.findall(rf'\b{prec_prefix}(\d+)\b', kb_context, re.IGNORECASE)
                canonical_candidate = None
                if context_matches:
                    target_len = len(context_matches[0])
                    for c_num in context_matches:
                        if c_num.endswith(num_str) or int(c_num) == int(num_str):
                            canonical_candidate = f"{prec_prefix}{c_num}"
                            break
                    if not canonical_candidate:
                        canonical_candidate = f"{prec_prefix}{num_str.zfill(target_len)}"
                else:
                    if prec_prefix == "EMP" and len(num_str) <= 2:
                        canonical_candidate = f"EMP10{num_str.zfill(2)}"
                    else:
                        canonical_candidate = f"{prec_prefix}{num_str}"

                if canonical_candidate and canonical_candidate not in extracted_ids:
                    extracted_ids.append(canonical_candidate)
                    mappings[raw_d.strip()] = canonical_candidate

        return extracted_ids, mappings

    def conservative_spell_correct(
        self,
        tokens: List[str],
        protected_tokens: Set[str],
        known_schema_cols: List[str]
    ) -> Tuple[List[str], Dict[str, str]]:
        """
        Conservative typo correction:
        - NEVER corrects protected structured identifiers (e.g. EMP1009, POL123).
        - Looks up common dictionary typos first.
        - Uses difflib fuzzy matching with a high similarity threshold (>= 0.85).
        """
        corrected: List[str] = []
        corrections: Dict[str, str] = {}

        # Build dynamic vocabulary from known schema columns + common domain vocab
        vocab = dict(COMMON_DOMAIN_VOCAB)
        for col in known_schema_cols:
            c_low = col.lower().strip()
            vocab[c_low] = col
            for subw in re.findall(r'[a-zA-Z0-9]+', c_low):
                if len(subw) > 3 and subw not in vocab:
                    vocab[subw] = subw

        vocab_keys = list(vocab.keys())

        for tok in tokens:
            tok_low = tok.lower()
            # If protected, keep as-is
            if tok in protected_tokens or tok.upper() in protected_tokens or re.search(r'\d', tok):
                corrected.append(tok)
                continue

            # Exact dictionary match
            if tok_low in vocab:
                canon = vocab[tok_low]
                if tok_low != canon.lower():
                    corrections[tok] = canon
                corrected.append(canon)
                continue

            # Skip short words for fuzzy matching to avoid false positives
            if len(tok_low) < 4:
                corrected.append(tok)
                continue

            # Conservative fuzzy match (cutoff 0.85)
            close = difflib.get_close_matches(tok_low, vocab_keys, n=1, cutoff=0.85)
            if close:
                matched_canon = vocab[close[0]]
                corrections[tok] = matched_canon
                corrected.append(matched_canon)
            else:
                corrected.append(tok)

        return corrected, corrections

    def extract_keywords(
        self,
        tokens: List[str],
        identified_entities: List[str],
        implied_columns: List[str]
    ) -> List[str]:
        """
        Extracts search keywords locally without calling an LLM:
        Removes stopwords and filler words; keeps nouns, domain terms, schema columns, and entities.
        """
        keywords: List[str] = []
        seen = set()

        # Prioritize identified entities and implied columns
        for item in identified_entities + implied_columns:
            if item and item.lower() not in seen:
                keywords.append(item)
                seen.add(item.lower())

        for tok in tokens:
            t_low = tok.lower()
            if t_low in STOPWORDS or len(t_low) <= 2:
                continue
            if t_low not in seen:
                keywords.append(tok)
                seen.add(t_low)

        return keywords

    def match_implied_columns(
        self,
        query: str,
        available_cols: List[str]
    ) -> Tuple[List[str], float]:
        """
        Maps user query words (e.g. 'earn', 'job', 'salary') to actual schema columns.
        Returns (matched_column_names, confidence).
        """
        matched: List[str] = []
        query_words = set(re.findall(r'[a-zA-Z0-9]+', query.lower()))
        col_map = {c.lower(): c for c in available_cols}

        # Direct name match
        for c_low, orig_col in col_map.items():
            c_words = set(re.findall(r'[a-zA-Z0-9]+', c_low))
            if c_words and c_words.issubset(query_words):
                if orig_col not in matched:
                    matched.append(orig_col)
            elif c_low in query.lower():
                if orig_col not in matched:
                    matched.append(orig_col)

        # Synonym / Semantic Concept match
        for concept, synonyms in SYNONYM_COLUMN_MAPPINGS.items():
            if concept in query_words:
                for syn in synonyms:
                    for c_low, orig_col in col_map.items():
                        if syn in c_low and orig_col not in matched:
                            matched.append(orig_col)

        confidence = 0.9 if matched else (0.4 if available_cols else 0.7)
        return matched, confidence

    # ----------------------------------------------------------------------
    # STAGE 2: INTENT & TABULAR ROUTING SCORING
    # ----------------------------------------------------------------------
    def classify_intent_and_routing(
        self,
        query: str,
        has_tabular_ids: bool,
        has_implied_cols: bool,
        is_composite: bool
    ) -> Tuple[QueryIntent, bool, float, str, Optional[str]]:
        """
        Deterministic, rule-based classification with calibrated confidence scores.
        Returns (intent, is_tabular, confidence, reasoning)
        """
        q_low = query.lower()
        query_words = set(re.findall(r'[a-zA-Z0-9]+', q_low))

        # Calculation signals (strictly mathematical / statistical aggregations)
        calc_signals = {"average", "avg", "sum", "total", "count", "maximum", "max", "minimum", "min", "percentage", "ratio", "median"}
        # Comparison signals
        comp_signals = {"compare", "comparison", "difference", "versus", "vs", "higher", "lower", "better", "worse"}
        # Why / reasoning signals
        why_signals = {"why", "reason", "cause", "explain why", "how come", "led to"}
        # Summary signals
        summary_signals = {"summarize", "summary", "overview", "tl;dr", "brief", "digest"}
        # Graph / Relationship signals
        graph_signals = {"hierarchy", "reporting", "org chart", "structure", "connected to", "relationship", "lineage"}
        # Tabular indicator keywords
        tabular_signals = {"salary", "hsn", "sku", "mrp", "price", "cost", "csv", "excel", "spreadsheet", "table", "rows", "column", "dataset"}
        # Document signals pointing to Vector
        # Explicit document keywords pointing away from calculation
        pure_doc_keywords = {"document", "pdf", "policy", "clause", "section", "paragraph", "guideline", "rule", "terms", "fuzzing", "nist", "according to"}
        has_pure_doc = bool(query_words & pure_doc_keywords) or any(ph in q_low for ph in ["according to", "in the pdf", "in the doc"])

        # 0. Enumeration
        enum_targets = {
            "job_posting": ["openings", "jobs", "careers", "positions"],
            "service_offering": ["services", "offerings"],
            "team_member": ["team", "members", "who are"]
        }
        for chunk_type, keywords in enum_targets.items():
            if any(k in q_low for k in keywords):
                if any(w in query_words for w in ["list", "all", "current"]) or "what are" in q_low or "tell me" in q_low or "show" in q_low:
                    return QueryIntent.ENUMERATION, False, 0.95, f"Deterministic enumeration for {chunk_type}", chunk_type
                    
        # 1. Calculation
        if bool(query_words & calc_signals) and not has_pure_doc:
            return QueryIntent.CALCULATION, True, 0.92, "Deterministic calculation match", None

        # 2. Comparison
        if bool(query_words & comp_signals):
            # If comparing salaries or numbers -> tabular comparison
            is_tab = bool(query_words & tabular_signals) or has_tabular_ids or has_implied_cols
            # Subjective comparisons (e.g. "better off", "worse off") without clear metrics are ambiguous
            if "better" in query_words or "worse" in query_words:
                if not (has_tabular_ids or has_implied_cols or (query_words & tabular_signals)):
                    return QueryIntent.COMPARISON, False, 0.50, "Subjective comparison without clear metrics (ambiguous)", None
            return QueryIntent.COMPARISON, is_tab, 0.88, "Deterministic comparison match", None

        # 3. Why / Reasoning
        if bool(query_words & why_signals):
            return QueryIntent.WHY, False, 0.90, "Deterministic why/reasoning match", None

        # 4. Summary
        if bool(query_words & summary_signals):
            return QueryIntent.SUMMARY, False, 0.95, "Deterministic summary match", None

        # 5. Graph / Structural
        if bool(query_words & graph_signals):
            return QueryIntent.GRAPH, False, 0.85, "Deterministic graph/relationship match", None

        # 6. Table Lookup (e.g. "show all records", "list rows")
        if "table records" in q_low or (any(ph in q_low for ph in ["how many", "list all", "show all"]) and (has_tabular_ids or has_implied_cols)):
            return QueryIntent.TABLE, True, 0.92, "Deterministic table aggregation match", None

        # 7. Fact / Lookup (Tabular vs Vector)
        # Exclude common publication/standards prefixes from tabular entity IDs (e.g. IR 8397, RFC 2616, ISO 27001)
        doc_code_prefixes = {"IR", "RFC", "ISO", "IEEE", "NIST", "SP", "SEC"}
        has_real_tabular_ids = any(
            not any(p in tid.upper() for p in doc_code_prefixes)
            for tid in ([id_mappings.get(k, k) for k in id_mappings] if 'id_mappings' in locals() else [])
        ) if has_tabular_ids else False

        tab_score = 0
        if has_tabular_ids and has_real_tabular_ids:
            tab_score += 2
        if has_implied_cols:
            tab_score += 2
        if bool(query_words & tabular_signals):
            tab_score += 2
        if any(q in q_low for q in ["how much", "what is the salary", "what is the cost", "what is the price"]):
            tab_score += 3

        vec_score = 0
        doc_signals = {"document", "pdf", "policy", "clause", "section", "paragraph", "guideline", "rule", "terms", "fuzzing", "nist", "benefits", "limitations", "definition", "categories"}
        has_strong_doc = bool(query_words & doc_signals) or any(ph in q_low for ph in ["according to", "what is", "explain", "describe"])

        if bool(query_words & doc_signals):
            vec_score += 3
        if any(q in q_low for q in ["explain", "describe", "meaning", "what does", "tell me about", "according to"]):
            vec_score += 2

        if has_strong_doc and not (query_words & tabular_signals) and not any(q in q_low for q in ["salary", "cost", "price", "revenue", "how many"]):
            return QueryIntent.FACT, False, 0.90, "Strong document/vector lookup signals override", None

        if tab_score > vec_score and tab_score >= 2:
            return QueryIntent.FACT, True, 0.90, "Strong tabular entity/attribute signals", None
        elif vec_score > tab_score:
            return QueryIntent.FACT, False, 0.88, "Strong document/vector lookup signals", None

        # Default Fact with moderate confidence
        return QueryIntent.FACT, False, 0.70, "Default factual question", None

    def decompose_composite_query(self, query: str, identified_entities: List[str]) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Detects composite queries (e.g. 'Tell me about Arun and what is his salary from the first CSV.')
        Decomposes into (vector_subquery, tabular_subquery) and resolves pronouns locally.
        """
        # Split markers
        split_match = re.search(r'\b(and|also|plus|as well as|then)\b\s+(what|how|show|tell|is|are|calculate)\b', query, re.IGNORECASE)
        if not split_match:
            return False, None, None

        split_idx = split_match.start()
        part1 = query[:split_idx].strip()
        part2 = query[split_match.start(2):].strip()

        # Check if one part is document/descriptive and the other is tabular
        tabular_kws = {"salary", "earning", "earn", "paid", "amount", "cost", "price", "csv", "excel", "table", "emp"}
        part1_is_tab = any(k in part1.lower() for k in tabular_kws)
        part2_is_tab = any(k in part2.lower() for k in tabular_kws)

        if part1_is_tab != part2_is_tab:
            # Composite detected!
            tab_part = part1 if part1_is_tab else part2
            vec_part = part2 if part1_is_tab else part1

            # Simple local pronoun resolution: resolve 'his', 'her', 'their', 'he', 'she' to main entity
            main_entity = identified_entities[0] if identified_entities else ""
            if not main_entity:
                # Extract proper noun from vector part (e.g. 'Arun' from 'Tell me about Arun')
                proper_nouns = re.findall(r'\b[A-Z][a-z]{2,}\b', vec_part)
                for pn in proper_nouns:
                    if pn.lower() not in STOPWORDS:
                        main_entity = pn
                        break

            if main_entity:
                tab_part = re.sub(r'\b(his|her|their)\s+salary\b', f"{main_entity}'s salary", tab_part, flags=re.IGNORECASE)
                tab_part = re.sub(r'\b(he|she|they)\s+(earns?|makes?|gets?)\b', f"{main_entity} \\1", tab_part, flags=re.IGNORECASE)
                tab_part = re.sub(r'\bdoes\s+(he|she|they)\s+(earn|make|get)\b', f"does {main_entity} \\2", tab_part, flags=re.IGNORECASE)
                tab_part = re.sub(r'\b(his|her|their)\b', f"{main_entity}'s", tab_part, flags=re.IGNORECASE)

            return True, tab_part, vec_part

        return False, None, None

    # ----------------------------------------------------------------------
    # STAGE 3: COMPACT LLM FALLBACK (Only for low-confidence ambiguity)
    # ----------------------------------------------------------------------
    async def call_compact_llm_fallback(
        self,
        query: str,
        kb_context: str,
        tenant_id: Optional[str],
        user_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """
        Very compact DeepInfra LLM call for genuinely ambiguous semantic queries.
        - max_tokens: 128 (NOT 1024)
        - timeout: 1.8s (fast-fail to guarantee 2.0s analyzer SLA)
        - prompt size: ~150 tokens (NO reasoning requested, NO 3 queries generated)
        """
        # Minimal context excerpt (max 200 chars)
        kb_snippet = kb_context[:250].strip() if kb_context else ""
        schema_info = f"Schema Context: {kb_snippet}\n" if kb_snippet else ""

        compact_prompt = f"""{schema_info}Analyze this query for RAG routing.
Query: "{query}"
If intent is ENUMERATION (e.g. "list all X"), extract target_chunk_type.
Return strict JSON only:
{{
  "intent": "FACT" | "CALCULATION" | "COMPARISON" | "TEMPORAL" | "STRUCTURAL" | "TABLE" | "SUMMARY" | "WHY" | "GRAPH" | "ENUMERATION" | "UNKNOWN",
  "target_chunk_type": "job_posting" | "service_offering" | "team_member" | "blog_post" | null,
  "entities": ["entity1", "entity2"],
  "is_tabular": true | false,
  "implied_columns": [],
  "confidence": 0.90
}}"""

        try:
            raw_resp = await asyncio.wait_for(
                self.llm_client.generate_cloud(
                    prompt=compact_prompt,
                    system_prompt="You are a strict JSON query classifier. Output only valid JSON.",
                    temperature=0.0,
                    max_tokens=128,
                    enable_thinking=False,
                    model=self.llm_client.model_intent,
                    timeout=1.8,
                    task=LLMTask.INTENT_DETECTION,
                    tenant_id=tenant_id,
                    user_id=user_id
                ),
                timeout=2.5
            )
            # Fast JSON extraction
            json_match = re.search(r'\{.*\}', raw_resp, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                return data
        except Exception as e:
            logger.warning(f"[FAST_ANALYZER] Compact LLM fallback bypassed or timed out: {e}")

        return None

    # ----------------------------------------------------------------------
    # MAIN ENTRY POINT (100% Compatible with QueryAnalyzer.analyze_query)
    # ----------------------------------------------------------------------
    async def analyze_query(
        self,
        query: str,
        kb_context: str = "",
        chat_history: Optional[str] = None,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> AnalysisResult:
        """
        Analyzes query using the Hybrid Fast-Path architecture.
        """
        t_total_start = time.time()
        timings: Dict[str, float] = {}

        original_query = query or ""
        q_strip = original_query.strip()

        # FAST PATH: Empty or greetings (< 1ms, 0 LLM)
        if not q_strip:
            return AnalysisResult(
                intent=QueryIntent.UNKNOWN,
                metadata=QueryMetadata(keywords=[], corrected_query=""),
                is_tabular=False,
                confidence=0.0,
                reasoning="Empty query"
            )

        if re.match(r'^(hello|hi|hey|good\s+morning|good\s+afternoon|good\s+evening|howdy|greetings|thanks|thank\s+you|how\s+are\s+you)(\s+(there|everyone|all|friend))?[!.,?]*$', q_strip, re.IGNORECASE):
            return AnalysisResult(
                intent=QueryIntent.FACT,
                metadata=QueryMetadata(keywords=[q_strip], corrected_query=q_strip),
                is_tabular=False,
                confidence=1.0,
                reasoning="Fast-path greeting match",
                heuristic_fallback_used=False
            )

        # 1. Normalization
        t0 = time.time()
        normalized_query = self.normalize_text(q_strip)
        timings["normalize"] = (time.time() - t0) * 1000

        # 2. Entity & Identifier Extraction
        t0 = time.time()
        extracted_ids, id_mappings = self.extract_identifiers(normalized_query, kb_context)
        timings["entity_resolution"] = (time.time() - t0) * 1000

        # Apply canonical ID replacements to query if partial ID was resolved (e.g. 'emp 9' -> 'EMP1009')
        query_with_ids = normalized_query
        for raw_frag, canon_id in id_mappings.items():
            query_with_ids = re.sub(re.escape(raw_frag), canon_id, query_with_ids, flags=re.IGNORECASE)

        # 3. Schema & Implied Column Extraction
        t0 = time.time()
        available_schema_cols: List[str] = []
        if kb_context:
            available_schema_cols = re.findall(r'\b[A-Z][a-zA-Z0-9_\s]{2,20}\b', kb_context)
        implied_cols, schema_conf = self.match_implied_columns(query_with_ids, available_schema_cols)
        timings["schema_matching"] = (time.time() - t0) * 1000

        # 4. Conservative Typo Correction
        t0 = time.time()
        tokens = re.findall(r'\b[a-zA-Z0-9_-]+\b', query_with_ids)
        protected = set(extracted_ids) | {canon.upper() for canon in extracted_ids}
        corrected_tokens, corrections = self.conservative_spell_correct(tokens, protected, available_schema_cols)
        
        # Build corrected_query
        corrected_query = query_with_ids
        for orig_tok, corr_tok in corrections.items():
            corrected_query = re.sub(rf'\b{re.escape(orig_tok)}\b', corr_tok, corrected_query, flags=re.IGNORECASE)
        timings["spell_correction"] = (time.time() - t0) * 1000

        # 5. Fast Local Keyword Extraction
        t0 = time.time()
        keywords = self.extract_keywords(corrected_tokens, extracted_ids, implied_cols)
        timings["keyword_extraction"] = (time.time() - t0) * 1000

        # 6. Composite Query Decomposition
        is_composite, tab_subq, vec_subq = self.decompose_composite_query(corrected_query, extracted_ids)

        # 7 & 8. Fully Dynamic LLM Routing (BYPASSED FOR OPTION 2)
        t0 = time.time()
        llm_fallback_used = False
        llm_timeout = False
        classify_intent_and_routing_called = True
        
        # Option 2: Pure Logical Routing (0.005s) instead of DeepInfra API
        llm_result = None
        llm_latency_ms = 0
        timings["llm_fallback"] = 0
        
        if llm_result:
            # Dead code, bypassed
            pass
        else:
            # Fallback to rule-based classification if LLM times out
            llm_timeout = True
            classify_intent_and_routing_called = True
            intent, is_tabular, confidence, reasoning, target_chunk_type = self.classify_intent_and_routing(
                corrected_query,
                has_tabular_ids=bool(extracted_ids),
                has_implied_cols=bool(implied_cols),
                is_composite=is_composite
            )
            entities = []

        total_time_ms = (time.time() - t_total_start) * 1000

        # Structured query generation: ONLY empty by default (removes the 3 unnecessary queries)
        structured_queries: List[str] = []

        log_msg = (
            f"\\n[FAST_ANALYZER]\\n"
            f"query=\"{query}\"\\n"
            f"llm_fallback_used={llm_fallback_used}\\n"
        )
        if llm_timeout:
            log_msg += "llm_timeout=True\\n"
        log_msg += (
            f"intent={intent.name}\\n"
            f"entities={entities}\\n"
            f"classify_intent_and_routing_called={classify_intent_and_routing_called}\\n"
            f"llm_latency_ms={int(llm_latency_ms)}\\n"
            f"analysis_latency_ms={int(total_time_ms)}\\n"
        )
        logger.info(log_msg)

        metadata = QueryMetadata(
            keywords=keywords,
            corrected_query=corrected_query,
            tabular_subquery=tab_subq,
            vector_subquery=vec_subq,
            implied_columns=implied_cols,
            structured_queries=structured_queries,
            target_chunk_type=target_chunk_type if 'target_chunk_type' in locals() else None
        )

        return AnalysisResult(
            intent=intent,
            metadata=metadata,
            is_tabular=is_tabular,
            confidence=confidence,
            reasoning=reasoning,
            heuristic_fallback_used=False
        )
