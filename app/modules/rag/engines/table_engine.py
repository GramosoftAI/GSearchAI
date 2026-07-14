import logging
from typing import List, Dict, Any
from app.core.neo4j_repository import Neo4jRepository
from app.modules.rag.pipeline import RetrievedChunk

logger = logging.getLogger(__name__)

class TableEngine:
    """
    Deterministic retrieval engine for exact table cells.
    Navigates the graph (HAS_TABLE -> HAS_ROW -> Cell) instead of semantic search.
    """
    def __init__(self, tenant_id: str, neo4j_repo: Neo4jRepository):
        self.tenant_id = tenant_id
        self.neo4j_repo = neo4j_repo
        
    async def retrieve(self, task: Any, kb_ids: List[str]) -> List[RetrievedChunk]:
        """
        Extracts table rows matching the query keywords.
        """
        logger.info(f"TableEngine executing task: {task.task_id}")
        
        # Simplified query: find any Table or Row that contains keywords
        # In a full implementation, we would extract the row header and column header
        keywords = task.metadata_filters.keywords if task.metadata_filters else []
        if not keywords:
            return []
            
        # Example Cypher to find rows matching keywords in tables
        # For this prototype we simulate finding a row node
        cypher = """
        MATCH (kb:KnowledgeBase)-[:HAS_DOCUMENT]->(doc)-[:HAS_SECTION*0..2]->(sec)-[:HAS_TABLE]->(t:Table)-[:HAS_ROW]->(r:Row)
        WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
        AND any(word IN $keywords WHERE toLower(r.text) CONTAINS toLower(word))
        RETURN r.id as chunk_id, r.text as text, t.name as table_name, sec.title as section
        LIMIT 10
        """
        
        try:
            results = await self.neo4j_repo.execute_read(
                cypher,
                {"kb_ids": kb_ids, "tenant_id": self.tenant_id, "keywords": keywords}
            )
            chunks = []
            if results:
                for idx, res in enumerate(results):
                    chunks.append(RetrievedChunk(
                        chunk_id=res.get("chunk_id", f"table-row-{idx}"),
                        text=f"Table: {res.get('table_name')}\nRow: {res.get('text')}",
                        kb_id=kb_ids[0],
                        position=idx,
                        embedding_similarity=1.0, # exact match
                        graph_score=1.0,
                        hybrid_score=1.0,
                        reason="TABLE_EXACT_MATCH",
                        source=f"Table: {res.get('table_name')} in Section: {res.get('section')}"
                    ))
            return chunks
        except Exception as e:
            logger.error(f"TableEngine failed: {e}")
            return []
