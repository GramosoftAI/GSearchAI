import logging
from typing import List, Dict, Any
from app.core.neo4j_repository import Neo4jRepository
from app.modules.rag.pipeline import RetrievedChunk

logger = logging.getLogger(__name__)

class FinancialEngine:
    """
    Financial document retrieval engine.
    Navigates via Document -> Section (e.g. MD&A, Notes) before paragraph retrieval.
    """
    def __init__(self, tenant_id: str, neo4j_repo: Neo4jRepository):
        self.tenant_id = tenant_id
        self.neo4j_repo = neo4j_repo
        
    async def retrieve(self, task: Any, kb_ids: List[str]) -> List[RetrievedChunk]:
        logger.info(f"FinancialEngine executing task: {task.task_id}")
        
        section_filter = task.metadata_filters.section if task.metadata_filters else None
        keywords = task.metadata_filters.keywords if task.metadata_filters else []
        
        if not keywords and not section_filter:
            return []
            
        cypher = """
        MATCH (kb:KnowledgeBase)-[:HAS_DOCUMENT]->(doc)-[:HAS_SECTION]->(sec:Section)
        WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
        """
        
        params = {"kb_ids": kb_ids, "tenant_id": self.tenant_id, "keywords": keywords}
        
        if section_filter:
            cypher += " AND toLower(sec.title) CONTAINS toLower($section_filter) "
            params["section_filter"] = section_filter
            
        cypher += """
        MATCH (sec)-[:HAS_TEXT]->(c:Chunk)
        WHERE any(word IN $keywords WHERE toLower(c.text) CONTAINS toLower(word))
        RETURN c.id as chunk_id, c.text as text, sec.title as section_title, c.position as position
        LIMIT 10
        """
        
        try:
            results = await self.neo4j_repo.execute_read(cypher, params)
            chunks = []
            if results:
                for idx, res in enumerate(results):
                    chunks.append(RetrievedChunk(
                        chunk_id=res.get("chunk_id", f"fin-chunk-{idx}"),
                        text=res.get("text", ""),
                        kb_id=kb_ids[0],
                        position=res.get("position", 0),
                        embedding_similarity=0.9, 
                        graph_score=1.0,
                        hybrid_score=0.95,
                        reason="FINANCIAL_SECTION_MATCH",
                        source=f"Section: {res.get('section_title')}"
                    ))
            return chunks
        except Exception as e:
            logger.error(f"FinancialEngine failed: {e}")
            return []
