import logging
import json
import re
from typing import List, Dict, Any
from app.core.llm.deepinfra_llm import DeepInfraLLMClient
from app.modules.rag.pipeline import RetrievedChunk, RAGContext

logger = logging.getLogger(__name__)

class SemanticComparator:
    """
    Deterministically detects contradictions in retrieved evidence using heuristics.
    """
    
    def __init__(self):
        # Common contradiction pairs in financial contexts
        self.conflict_rules = [
            {
                "positive": r"\b(change(s|d)? in (accounting )?estimate|material change|updated policy)\b",
                "negative": r"\b(no (material )?change(s|d)?|did not change|remained unchanged|no updates)\b",
                "name": "Accounting Changes"
            },
            {
                "positive": r"\b(increase(d)?|grew|higher)\b",
                "negative": r"\b(decrease(d)?|fell|lower|declined)\b",
                "name": "Directional Trends"
            }
        ]
        
        # Regex patterns for lightweight extraction
        self.extraction_patterns = {
            "date": r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4}\b|\b\d{4}-\d{2}-\d{2}\b|\bQ[1-4]\s+\d{4}\b",
            "percentage": r"\b\d+(?:\.\d+)?\s*%",
            "money": r"\$[\d,]+(?:\.\d+)?\s*(?:million|billion|trillion)?\b",
        }

class ConflictDetector:
    """
    Detects contradictions or conflicting information in retrieved evidence before generating a final answer.
    """
    def __init__(self):
        self.comparator = SemanticComparator()
        
    async def detect_conflicts(self, context: RAGContext) -> Dict[str, Any]:
        """
        Analyzes the context for conflicting information.
        Returns a dict: {"conflict_found": bool, "explanation": str}
        """
        if not context.chunks:
            return {"conflict_found": False, "explanation": ""}
            
        evidence_texts = [c.text.lower() for c in context.chunks]
        conflict_warnings = []
        
        # 1. Existing Hardcoded Rules
        for rule in self.comparator.conflict_rules:
            pos_found = False
            neg_found = False
            
            for text in evidence_texts:
                if re.search(rule["positive"], text):
                    pos_found = True
                if re.search(rule["negative"], text):
                    neg_found = True
                    
            if pos_found and neg_found:
                logger.warning(f"Deterministic conflict detected: {rule['name']}")
                conflict_warnings.append(f"Conflicting statements regarding {rule['name']} (e.g. 'changed' vs 'no changes').")
                
        # 2. Generic Regex Extraction for Data Conflicts
        extracted_data = {"date": [], "percentage": [], "money": []}
        
        for i, text in enumerate(context.chunks):
            chunk_txt = text.text
            for category, pattern in self.comparator.extraction_patterns.items():
                matches = set(re.findall(pattern, chunk_txt, flags=re.IGNORECASE))
                for match in matches:
                    extracted_data[category].append((match.lower(), i, chunk_txt))
                    
        # Compare extracted values across chunks
        for category, items in extracted_data.items():
            if len(items) >= 2:
                # We have at least two items extracted for this category.
                # Find distinct values
                distinct_values = set([val for val, idx, txt in items])
                if len(distinct_values) > 1:
                    # We have multiple distinct values for the same category across chunks.
                    # This is a heuristic indication of a potential conflict, e.g. two different dates or numbers.
                    # We group by chunk to report.
                    val_by_chunk = {}
                    for val, idx, txt in items:
                        if idx not in val_by_chunk:
                            val_by_chunk[idx] = set()
                        val_by_chunk[idx].add(val)
                    
                    if len(val_by_chunk) > 1:
                        # Ensure they actually come from different chunks
                        summary = ", ".join([f"chunk {idx} mentions {list(vals)}" for idx, vals in val_by_chunk.items()])
                        warning_msg = f"Potential discrepancy in {category} values: {summary}."
                        logger.warning(f"Generic data conflict detected: {warning_msg}")
                        conflict_warnings.append(warning_msg)
                        
        if conflict_warnings:
            return {
                "conflict_found": True,
                "explanation": " | ".join(conflict_warnings)
            }
                
        return {"conflict_found": False, "explanation": ""}
