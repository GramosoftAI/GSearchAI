import logging
from typing import List, Any, Dict
from app.core.neo4j_repository import Neo4jRepository
from app.modules.rag.pipeline import RetrievedChunk
from app.modules.rag.orchestrator.query_analyzer import QueryIntent
from app.modules.rag.engines.registry import BaseEngine, CapabilityRegistry

logger = logging.getLogger(__name__)

@CapabilityRegistry.register("financial")
class FinancialEngine(BaseEngine):
    """
    Financial document retrieval engine.
    Navigates via Document -> Section (e.g. MD&A, Notes) before paragraph retrieval.
    """
    
    @classmethod
    def supports(cls, intent: QueryIntent) -> bool:
        return intent in [QueryIntent.FACT, QueryIntent.CALCULATION, QueryIntent.COMPARISON]
        
    @classmethod
    def priority(cls) -> float:
        return 0.8
        
    @classmethod
    def cost(cls) -> float:
        # Graph traversals are fast
        return 10.0
        
    @classmethod
    def domain(cls) -> List[str]:
        return ["Accounting", "Revenue", "Expenses", "Tax"]
        
    def __init__(self, tenant_id: str, neo4j_repo: Neo4jRepository, session_factory: Any = None):
        self.tenant_id = tenant_id
        self.neo4j_repo = neo4j_repo
        self.session_factory = session_factory
        
    async def get_candidate_sections(self, task: Any, kb_ids: List[str]) -> List[Dict[str, Any]]:
        section_filter = getattr(task, "target_section", None)
        if not section_filter and task.metadata_filters and hasattr(task.metadata_filters, 'primary_topic'):
            section_filter = task.metadata_filters.primary_topic
        keywords = task.metadata_filters.get("keywords", []) if isinstance(task.metadata_filters, dict) else (task.metadata_filters.keywords if getattr(task, "metadata_filters", None) else [])
        broad_keywords = []
        stopwords = {"what", "when", "this", "that", "code", "data", "info", "find", "how", "why", "where", "which", "with", "does", "then", "from", "they"}
        for kw in keywords:
            for word in kw.split():
                word = word.strip()
                if len(word) > 3 and word.lower() not in stopwords:
                    broad_keywords.append(word.lower())
                    
        cypher = """
        MATCH (kb:KnowledgeBase)-[:HAS_CHUNK]->(c:Chunk)
        WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
        """
        params = {"kb_ids": kb_ids, "tenant_id": self.tenant_id}
        
        if section_filter:
            cypher += " AND toLower(c.section) CONTAINS toLower($section_filter) "
            params["section_filter"] = section_filter
            
        cypher += " WITH DISTINCT c.section AS title, head(collect(c.source_type)) AS doc_type "
        
        if broad_keywords:
            cypher += """
            WITH title, doc_type,
                 REDUCE(s = 0, kw IN $broad_keywords | s + CASE WHEN toLower(title) CONTAINS kw THEN 1 ELSE 0 END) AS score
            ORDER BY score DESC, title ASC
            """
            params["broad_keywords"] = broad_keywords
        else:
            cypher += " ORDER BY title ASC "
            
        cypher += " RETURN title AS section_id, title, doc_type LIMIT 1000 "
        
        logger.info(f"[FINANCIAL_ENGINE_DEBUG] get_candidate_sections broad_keywords={broad_keywords}")
        
        try:
            results = await self.neo4j_repo.execute_read(cypher, params)
            sections = []
            if results:
                if len(results) >= 1000:
                    logger.warning("Candidate section truncation triggered in financial_engine: >= 1000 sections found, truncated to 1000.")
                for r in results:
                    sections.append({
                        "section_id": r.get("section_id"),
                        "title": r.get("title", ""),
                        "doc_type": r.get("doc_type", "unknown"),
                        "task_id": getattr(task, "task_id", "")
                    })
            return sections
        except Exception as e:
            logger.error(f"Failed to get candidate sections: {e}")
            return []

    async def retrieve(self, task: Any, kb_ids: List[str]) -> List[RetrievedChunk]:
        logger.info(f"FinancialEngine executing task: {task.task_id}")
        
        target_section_ids = getattr(task, "target_section_ids", [])
        section_filter = getattr(task, "target_section", None)
        if not section_filter and task.metadata_filters and hasattr(task.metadata_filters, 'primary_topic'):
            section_filter = task.metadata_filters.primary_topic
            
        keywords = task.metadata_filters.keywords if task.metadata_filters else []
        
        if not keywords and not section_filter and not target_section_ids:
            return []
            
        cypher = """
        MATCH (kb:KnowledgeBase)-[:HAS_CHUNK]->(c:Chunk)
        WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
        """
        
        params = {"kb_ids": kb_ids, "tenant_id": self.tenant_id, "keywords": keywords}
        
        if target_section_ids:
            cypher += " AND c.id IN $target_section_ids "
            params["target_section_ids"] = target_section_ids
        elif section_filter:
            cypher += " AND toLower(c.section) CONTAINS toLower($section_filter) "
            params["section_filter"] = section_filter
            
        cypher += """
        MATCH (sec)-[:HAS_TEXT]->(c:Chunk)
        """
        if keywords:
            cypher += " WHERE any(word IN $keywords WHERE toLower(c.text) CONTAINS toLower(word)) "
            
        cypher += """
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
                        source=f"Section: {res.get('section_title')}",
                        engine_name="financial",
                        section=res.get('section_title'),
                        ontology_node=section_filter
                    ))
            return chunks
        except Exception as e:
            logger.error(f"FinancialEngine failed: {e}")
            return []
