import logging
from typing import List, Dict, Any
from app.core.neo4j_repository import Neo4jRepository
from app.modules.rag.pipeline import RetrievedChunk
from app.modules.rag.orchestrator.query_analyzer import QueryIntent
from app.modules.rag.engines.registry import BaseEngine, CapabilityRegistry

logger = logging.getLogger(__name__)

@CapabilityRegistry.register("table")
class TableEngine(BaseEngine):
    """
    Deterministic retrieval engine for exact table cells.
    Navigates the graph (HAS_TABLE -> HAS_ROW -> Cell) instead of semantic search.
    """
    
    @classmethod
    def supports(cls, intent: QueryIntent) -> bool:
        return intent == QueryIntent.TABLE
        
    @classmethod
    def priority(cls) -> float:
        return 1.0 # Highest priority for table intents
        
    @classmethod
    def cost(cls) -> float:
        return 15.0 # slightly more expensive cypher
        
    @classmethod
    def domain(cls) -> List[str]:
        return ["*"] # Supports all domains

    def __init__(self, tenant_id: str, neo4j_repo: Neo4jRepository, session_factory: Any = None):
        self.tenant_id = tenant_id
        self.neo4j_repo = neo4j_repo
        self.session_factory = session_factory
        
    async def get_candidate_sections(self, task: Any, kb_ids: List[str]) -> List[Dict[str, Any]]:
        keywords = task.metadata_filters.get("keywords", []) if isinstance(task.metadata_filters, dict) else (task.metadata_filters.keywords if getattr(task, "metadata_filters", None) else [])
        broad_keywords = []
        stopwords = {"what", "when", "this", "that", "code", "data", "info", "find", "how", "why", "where", "which", "with", "does", "then", "from", "they"}
        for kw in keywords:
            for word in kw.split():
                word = word.strip()
                if len(word) > 3 and word.lower() not in stopwords:
                    broad_keywords.append(word.lower())
                    
        cypher = """
        MATCH (kb:KnowledgeBase)-[:HAS_CHUNK]->(t:Table)
        WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
        WITH DISTINCT sec.id as section_id, sec.title as title, doc.type as doc_type, t.name as table_name
        """
        params = {"kb_ids": kb_ids, "tenant_id": self.tenant_id}
        
        if broad_keywords:
            cypher += """
            WITH section_id, title, doc_type, table_name,
                 REDUCE(s = 0, kw IN $broad_keywords | s + CASE WHEN toLower(title) CONTAINS kw THEN 1 ELSE 0 END) AS score
            ORDER BY score DESC, title ASC
            """
            params["broad_keywords"] = broad_keywords
        else:
            cypher += " ORDER BY title ASC "
            
        cypher += " RETURN section_id, title, doc_type, table_name LIMIT 1000 "
        
        logger.info(f"[TABLE_ENGINE_DEBUG] get_candidate_sections broad_keywords={broad_keywords}")
        
        try:
            results = await self.neo4j_repo.execute_read(cypher, params)
            sections = []
            if results:
                if len(results) >= 1000:
                    logger.warning("Candidate section truncation triggered in table_engine: >= 1000 sections found, truncated to 1000.")
                for r in results:
                    sections.append({
                        "section_id": r.get("section_id"),
                        "title": f"{r.get('title', '')} | Table: {r.get('table_name', '')}",
                        "doc_type": r.get("doc_type", "unknown"),
                        "task_id": getattr(task, "task_id", "")
                    })
            return sections
        except Exception as e:
            logger.error(f"Failed to get table candidate sections: {e}")
            return []

    async def retrieve(self, task: Any, kb_ids: List[str]) -> List[RetrievedChunk]:
        """
        Extracts table rows matching the query keywords.
        """
        logger.info(f"TableEngine executing task: {task.task_id}")
        
        target_section_ids = getattr(task, "target_section_ids", [])
        
        # Simplified query: find any Table or Row that contains keywords
        # In a full implementation, we would extract the row header and column header
        keywords = task.metadata_filters.keywords if task.metadata_filters else []
        if not keywords and not target_section_ids:
            return []
            
        cypher = """
        MATCH (kb:KnowledgeBase)-[:HAS_CHUNK]->(t:Table)-[:HAS_ROW]->(r:Row)
        WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
        """
        params = {"kb_ids": kb_ids, "tenant_id": self.tenant_id, "keywords": keywords}
        
        if target_section_ids:
            cypher += " AND sec.id IN $target_section_ids "
            params["target_section_ids"] = target_section_ids
            
        if keywords:
            cypher += " AND any(word IN $keywords WHERE toLower(r.text) CONTAINS toLower(word)) "
            
        cypher += """
        RETURN r.id as chunk_id, r.text as text, t.name as table_name, sec.title as section
        LIMIT 10
        """
        
        try:
            results = await self.neo4j_repo.execute_read(cypher, params)
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
                        source=f"Table: {res.get('table_name')} in Section: {res.get('section')}",
                        engine_name="table",
                        section=res.get('section'),
                        ontology_node="Table"
                    ))
            return chunks
        except Exception as e:
            logger.error(f"TableEngine failed: {e}")
            return []
