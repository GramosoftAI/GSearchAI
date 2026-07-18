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
        
    def aggregate(self, all_chunks: List[RetrievedChunk], strategy: str, original_query: str, max_tokens: int = 8192) -> List[RetrievedChunk]:
        """
        Merges chunks and applies simple deterministic re-ranking.
        Packs chunks into the context window until the token budget is exhausted.
        Exact Table Matches > Exact Graph Matches > High Confidence Financial > Vector
        """
        logger.info(f"Aggregating {len(all_chunks)} chunks with strategy {strategy}, budget: {max_tokens} tokens")
        
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
        
        # Keep chunks until token budget is hit
        final_chunks = []
        current_tokens = 0
        
        for c in chunks:
            # simple token estimate: words * 1.3
            estimated_tokens = int(len(c.text.split()) * 1.3)
            if current_tokens + estimated_tokens > max_tokens:
                logger.info(f"Token budget ({max_tokens}) reached. Stopping aggregation.")
                break
            
            final_chunks.append(c)
            current_tokens += estimated_tokens
            
        logger.info(f"Aggregated {len(final_chunks)} chunks, totaling ~{current_tokens} tokens.")
        return final_chunks
