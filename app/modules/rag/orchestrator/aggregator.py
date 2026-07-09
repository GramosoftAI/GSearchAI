import logging
from typing import List
from app.modules.rag.pipeline import RetrievedChunk, RAGContext

logger = logging.getLogger(__name__)

class EvidenceAggregator:
    """
    Aggregates and re-ranks evidence from multiple retrieval engines.
    """
    
    def __init__(self):
        pass
        
    def aggregate(self, all_chunks: List[RetrievedChunk], strategy: str, original_query: str) -> List[RetrievedChunk]:
        """
        Merges chunks and applies simple deterministic re-ranking.
        Exact Table Matches > Exact Graph Matches > High Confidence Financial > Vector
        """
        logger.info(f"Aggregating {len(all_chunks)} chunks with strategy {strategy}")
        
        # Deduplicate chunks by ID
        unique_chunks = {}
        for c in all_chunks:
            if c.chunk_id not in unique_chunks:
                unique_chunks[c.chunk_id] = c
            else:
                # Merge scores or keep highest
                if c.hybrid_score > unique_chunks[c.chunk_id].hybrid_score:
                    unique_chunks[c.chunk_id] = c
                    
        chunks = list(unique_chunks.values())
        
        # Cross-Encoder logic would go here. For now, we apply heuristic scoring boosts.
        for c in chunks:
            if "TABLE_EXACT_MATCH" in c.reason:
                c.hybrid_score += 0.5
            elif "FINANCIAL_SECTION_MATCH" in c.reason:
                c.hybrid_score += 0.3
                
        # Sort by hybrid score
        chunks.sort(key=lambda x: x.hybrid_score, reverse=True)
        
        # Keep top 15
        return chunks[:15]
