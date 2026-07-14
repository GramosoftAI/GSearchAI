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
                return {
                    "conflict_found": True, 
                    "explanation": f"Found conflicting statements regarding {rule['name']} (e.g. 'changed' vs 'no changes')."
                }
                
        return {"conflict_found": False, "explanation": ""}
