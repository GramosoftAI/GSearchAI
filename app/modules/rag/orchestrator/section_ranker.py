import logging
import re
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class SectionRanker:
    """
    Ranks candidate sections to determine the most authoritative and relevant sections
    to retrieve evidence from, preventing retrieval from tangential or less detailed sections.
    """
    
    def __init__(self):
        # We can implement lightweight semantic scoring here using rules and keyword overlaps
        self.temporal_keywords = ["q1", "q2", "q3", "q4", "nine months", "six months", "three months", "year", "fy"]
        self.authoritative_docs = ["Notes", "Financial Statements"]
        
    def rank_sections(self, query: str, candidate_sections: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Scores and ranks sections based on temporal constraints, semantic keyword overlap, and doc type.
        """
        import time
        trace_start = time.time()
        logger.info(f"[TRACE_E2E] [ENTRY] SectionRanker.rank_sections - Input: {len(candidate_sections) if candidate_sections else 0} candidates")
        
        if not candidate_sections:
            latency = time.time() - trace_start
            logger.info(f"[TRACE_E2E] [EXIT] SectionRanker.rank_sections - Output: 0 sections - Latency: {latency:.2f}s")
            return []
            
        query_lower = query.lower()
        scored_sections = []
        
        for section in candidate_sections:
            score = 0.0
            title = section.get("title", "").lower()
            doc_type = section.get("doc_type", "unknown").lower()
            
            # 1. Temporal Relevance
            for tk in self.temporal_keywords:
                if tk in query_lower and tk in title:
                    score += 5.0
                    
            # 2. Document Type Authority
            if any(ad.lower() in doc_type for ad in self.authoritative_docs):
                score += 3.0
            elif "md&a" in doc_type:
                score += 1.0
                
            # 3. Keyword Coverage (Basic token overlap)
            query_tokens = set(re.findall(r'\b\w+\b', query_lower))
            title_tokens = set(re.findall(r'\b\w+\b', title))
            overlap = len(query_tokens.intersection(title_tokens))
            score += (overlap * 2.0)
            
            # 4. Exact Ontology Match (if passed down in candidate generator, not used yet)
            
            # Penalty for very generic sections if query is specific
            if "summary" in title and overlap < 2:
                score -= 2.0
                
            section["rank_score"] = score
            scored_sections.append(section)
            
        # Sort descending by score
        scored_sections.sort(key=lambda x: x["rank_score"], reverse=True)
        
        # Deduplicate by section name just in case multiple engines yielded the same section
        seen = set()
        unique_ranked = []
        for s in scored_sections:
            s_name = s.get("title")
            if s_name not in seen and s_name:
                seen.add(s_name)
                unique_ranked.append(s)
                
        final_sections = unique_ranked[:top_k]
        latency = time.time() - trace_start
        logger.info(f"[TRACE_E2E] [EXIT] SectionRanker.rank_sections - Output: {len(final_sections)} sections - Latency: {latency:.2f}s")
        return final_sections
