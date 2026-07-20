import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from .query_analyzer import AnalysisResult, QueryIntent, QueryMetadata
from app.modules.rag.engines.registry import CapabilityRegistry

logger = logging.getLogger(__name__)

class RetrievalTask(BaseModel):
    engine_name: str # e.g., 'table', 'financial', 'vector', 'graph'
    query: str
    metadata_filters: QueryMetadata
    task_id: str
    target_section: Optional[str] = None
    priority: float = 1.0
    required: bool = False
    reason: str = ""

class RetrievalPlan(BaseModel):
    tasks: List[RetrievalTask]
    aggregator_strategy: str # e.g., 'merge', 'calculate', 'compare'
    coverage_goals: List[str] = []

class AdaptivePlanner:
    """
    Orchestrates the retrieval strategy based on query intent.
    Creates a multi-hop plan that dispatches to various specialized engines.
    """
    
    def __init__(self, neo4j_repo, tenant_id: str):
        self.neo4j_repo = neo4j_repo
        self.tenant_id = tenant_id
        
    async def _expand_ontology(self, primary_topic: str) -> List[str]:
        """Queries Neo4j for child nodes of the primary topic."""
        if not primary_topic:
            return []
            
        cypher = """
        MATCH (d:OntologyDomain {name: $topic})
        WHERE d.tenant_id = $tenant_id OR $tenant_id = $tenant_id
        MATCH (d)-[:HAS_CHILD]->(c)
        RETURN c.name as child_name
        """
        try:
            results = await self.neo4j_repo.execute_read(cypher, {"topic": primary_topic, "tenant_id": self.tenant_id})
            if results:
                return [r["child_name"] for r in results]
        except Exception as e:
            logger.error(f"Ontology expansion failed: {e}")
        return []
        
    async def _create_domain_tasks(self, analysis: AnalysisResult, original_query: str, base_id: str, intent: QueryIntent) -> List[RetrievalTask]:
        """Helper to create multiple tasks based on graph ontology expansion and registry capabilities"""
        tasks = []
        coverage_goals = []
        
        primary_topic = analysis.metadata.primary_topic
        
        # Select the best engine for this intent and domain
        best_engine = CapabilityRegistry.get_best_engine(intent, primary_topic)
        
        if primary_topic:
            related_sections = await self._expand_ontology(primary_topic)
            
            # If graph expanded, fan out
            if related_sections:
                for idx, section in enumerate(related_sections):
                    tasks.append(RetrievalTask(
                        engine_name=best_engine,
                        query=original_query,
                        metadata_filters=analysis.metadata,
                        task_id=f"{base_id}_expanded_{idx}",
                        target_section=section,
                        priority=0.9,
                        required=True,
                        reason=f"Coverage Expansion for {primary_topic}"
                    ))
                    coverage_goals.append(section)
            else:
                # Use primary topic directly if no children found
                tasks.append(RetrievalTask(
                    engine_name=best_engine,
                    query=original_query,
                    metadata_filters=analysis.metadata,
                    task_id=f"{base_id}_primary",
                    target_section=primary_topic,
                    priority=1.0,
                    required=True,
                    reason=f"Primary Topic Search"
                ))
                coverage_goals.append(primary_topic)
        else:
            # Fallback if no topic at all
            tasks.append(RetrievalTask(
                engine_name=best_engine,
                query=original_query,
                metadata_filters=analysis.metadata,
                task_id=f"{base_id}_fallback"
            ))
            
        return tasks, coverage_goals
        
    async def create_plan(self, analysis: AnalysisResult, original_query: str) -> RetrievalPlan:
        """
        Creates a RetrievalPlan containing multiple RetrievalTasks based on the intent.
        """
        intent = analysis.intent
        tasks = []
        coverage_goals = []
        strategy = "merge"
        
        logger.info(f"Creating retrieval plan for intent: {intent.name}")
        
        if intent == QueryIntent.COMPARISON:
            best_engine = CapabilityRegistry.get_best_engine(intent, analysis.metadata.primary_topic)
            f_tasks, goals = await self._create_domain_tasks(analysis, original_query, "compare_1", intent)
            tasks.extend(f_tasks)
            coverage_goals.extend(goals)
            strategy = "compare"
            
        elif intent == QueryIntent.CALCULATION:
            best_engine = CapabilityRegistry.get_best_engine(intent, analysis.metadata.primary_topic)
            f_tasks, goals = await self._create_domain_tasks(analysis, original_query, "calc_1", intent)
            tasks.extend(f_tasks)
            coverage_goals.extend(goals)
            strategy = "calculate"
            
        elif intent == QueryIntent.TABLE:
            best_engine = CapabilityRegistry.get_best_engine(intent, analysis.metadata.primary_topic)
            tasks.append(RetrievalTask(
                engine_name=best_engine,
                query=original_query,
                metadata_filters=analysis.metadata,
                task_id="table_1"
            ))
            
        elif intent == QueryIntent.STRUCTURAL:
            best_engine = CapabilityRegistry.get_best_engine(intent, analysis.metadata.primary_topic)
            tasks.append(RetrievalTask(
                engine_name=best_engine,
                query=original_query,
                metadata_filters=analysis.metadata,
                task_id="graph_1"
            ))
            
        elif intent == QueryIntent.FACT:
            f_tasks, goals = await self._create_domain_tasks(analysis, original_query, "fact_1", intent)
            tasks.extend(f_tasks)
            coverage_goals.extend(goals)
                
        else:
            best_engine = CapabilityRegistry.get_best_engine(intent, analysis.metadata.primary_topic)
            tasks.append(RetrievalTask(
                engine_name=best_engine,
                query=original_query,
                metadata_filters=analysis.metadata,
                task_id="vec_fallback"
            ))
            
        return RetrievalPlan(tasks=tasks, aggregator_strategy=strategy, coverage_goals=coverage_goals)
