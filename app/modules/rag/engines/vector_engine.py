import logging
from typing import List, Dict, Any
from app.core.neo4j_repository import Neo4jRepository
from app.modules.rag.pipeline import RetrievedChunk
from app.modules.rag.orchestrator.query_analyzer import QueryIntent
from app.modules.rag.engines.registry import BaseEngine, CapabilityRegistry

logger = logging.getLogger(__name__)

@CapabilityRegistry.register("vector")
class VectorEngine(BaseEngine):
    """
    Standard semantic vector retrieval engine.
    Used as a fallback for missing coverage goals or unknown domains.
    """
    
    @classmethod
    def supports(cls, intent: QueryIntent) -> bool:
        return True # Supports all intents as fallback
        
    @classmethod
    def priority(cls) -> float:
        return 0.1 # Lowest priority
        
    @classmethod
    def cost(cls) -> float:
        return 50.0 # Vector similarity is more expensive than exact graph traversal
        
    @classmethod
    def domain(cls) -> List[str]:
        return ["*"]
        
    def __init__(self, tenant_id: str, neo4j_repo: Neo4jRepository, db: Any = None):
        self.tenant_id = tenant_id
        self.neo4j_repo = neo4j_repo
        self.db = db
        
    async def get_candidate_sections(self, task: Any, kb_ids: List[str]) -> List[Dict[str, Any]]:
        keywords = task.metadata_filters.keywords if task.metadata_filters else []
        if not keywords:
            keywords = [task.query.split()[0]] if task.query else []
            
        cypher = """
        MATCH (kb:KnowledgeBase)-[:HAS_DOCUMENT]->(doc)-[:HAS_SECTION*0..2]->(sec)-[:HAS_TEXT]->(c:Chunk)
        WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
        AND any(word IN $keywords WHERE toLower(c.text) CONTAINS toLower(word))
        RETURN DISTINCT sec.id as section_id, sec.title as title, doc.type as doc_type
        LIMIT 50
        """
        try:
            results = await self.neo4j_repo.execute_read(
                cypher,
                {"kb_ids": kb_ids, "tenant_id": self.tenant_id, "keywords": keywords}
            )
            sections = []
            if results:
                for r in results:
                    sections.append({
                        "section_id": r.get("section_id"),
                        "title": r.get("title", ""),
                        "doc_type": r.get("doc_type", "unknown"),
                        "task_id": getattr(task, "task_id", "")
                    })
            return sections
        except Exception as e:
            logger.error(f"VectorEngine failed to get candidate sections: {e}")
            return []

    async def retrieve(self, task: Any, kb_ids: List[str]) -> List[RetrievedChunk]:
        """
        Retrieves chunks using PostgreSQL pgvector when db session is available.
        Otherwise, falls back to simulated vector retrieval using Cypher.
        """
        logger.info(f"VectorEngine executing task: {task.task_id}")
        
        target_section_ids = getattr(task, "target_section_ids", [])
        keywords = task.metadata_filters.keywords if task.metadata_filters else []
        if not keywords:
            keywords = [task.query.split()[0]] if task.query else []

        if self.db:
            try:
                from app.core.embeddings import EmbeddingGenerator
                from sqlalchemy import select, and_, case, Float
                from app.modules.knowledge_bases.models import DocumentChunk, KnowledgeBase
                from uuid import UUID

                query_embedding = await EmbeddingGenerator.generate_embedding(task.query)
                
                top_k = getattr(task, "top_k", 15)
                candidate_limit = max(top_k, 15)
                
                vector_score = (1.0 - DocumentChunk.embedding.cosine_distance(query_embedding))
                position_boost = case((DocumentChunk.chunk_index < 3, 1.0), else_=0.0).cast(Float)

                stmt = (
                    select(
                        DocumentChunk.id,
                        DocumentChunk.text,
                        DocumentChunk.chunk_index,
                        DocumentChunk.kb_id,
                        DocumentChunk.metadata_json,
                        KnowledgeBase.name,
                        KnowledgeBase.s3_path,
                        vector_score.label("similarity")
                    )
                    .join(KnowledgeBase, DocumentChunk.kb_id == KnowledgeBase.id)
                    .where(
                        and_(
                            DocumentChunk.tenant_id == UUID(str(self.tenant_id)),
                            DocumentChunk.kb_id.in_([UUID(str(kb_id)) for kb_id in kb_ids])
                        )
                    )
                    .order_by((vector_score + position_boost).desc())
                    .limit(200)  # Fetch more for Python re-ranking
                )
                
                res = await self.db.execute(stmt)
                chunks = []
                
                # Simple keyword extraction (alphanumeric words > 4 chars)
                exact_terms = [w for w in task.query.split() if len(w) > 4 and w.isalnum()]
                
                all_rows = res.fetchall()
                for idx, row in enumerate(all_rows):
                    similarity = float(row.similarity) if row.similarity is not None else 0.8
                    chunk_text = row.text or ""
                    
                    weight = 1.0
                    for term in exact_terms:
                        if term.lower() in chunk_text.lower():
                            weight *= 1.15
                            
                    if row.chunk_index < 3:
                        final_score = similarity + 1.0
                    else:
                        final_score = min(similarity * weight, 1.0)
                    
                    chunks.append(RetrievedChunk(
                        chunk_id=str(row.id),
                        text=chunk_text,
                        kb_id=str(row.kb_id),
                        position=idx,
                        embedding_similarity=similarity,
                        graph_score=0.0,
                        hybrid_score=final_score,
                        reason="VECTOR_SEARCH_HYBRID",
                        source=row.s3_path or row.name or f"DocumentChunk {row.chunk_index}",
                        s3_path=row.s3_path,
                        engine_name="vector",
                        section="Unknown",
                        ontology_node=getattr(task, "target_section", "Unknown")
                    ))
                    
                # Rerank in python
                chunks.sort(key=lambda x: x.hybrid_score, reverse=True)
                return chunks[:candidate_limit]
            except Exception as e:
                logger.error(f"VectorEngine pgvector retrieval failed: {e}. Falling back to Cypher.")

        # Cypher fallback
        cypher = """
        MATCH (kb:KnowledgeBase)-[:HAS_DOCUMENT]->(doc)-[:HAS_SECTION*0..2]->(sec)
        WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
        """
        params = {"kb_ids": kb_ids, "tenant_id": self.tenant_id, "keywords": keywords}
        
        if target_section_ids:
            cypher += " AND sec.id IN $target_section_ids "
            params["target_section_ids"] = target_section_ids
            
        cypher += """
        MATCH (sec)-[:HAS_TEXT]->(c:Chunk)
        WHERE any(word IN $keywords WHERE toLower(c.text) CONTAINS toLower(word))
        RETURN c.id as chunk_id, c.text as text, sec.title as section
        LIMIT 5
        """
        try:
            results = await self.neo4j_repo.execute_read(
                cypher,
                params
            )
            chunks = []
            if results:
                for idx, res in enumerate(results):
                    chunks.append(RetrievedChunk(
                        chunk_id=res.get("chunk_id", f"vec-chunk-{idx}"),
                        text=res.get('text'),
                        kb_id=kb_ids[0],
                        position=idx,
                        embedding_similarity=0.85, 
                        graph_score=0.1,
                        hybrid_score=0.85,
                        reason="VECTOR_FALLBACK",
                        source=f"Section: {res.get('section')}",
                        engine_name="vector",
                        section=res.get('section'),
                        ontology_node=getattr(task, "target_section", "Unknown")
                    ))
            return chunks
        except Exception as e:
            logger.error(f"VectorEngine Cypher fallback failed: {e}")
            return []
