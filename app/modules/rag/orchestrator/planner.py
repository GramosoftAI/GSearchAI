import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from .query_analyzer import AnalysisResult, QueryIntent, QueryMetadata

logger = logging.getLogger(__name__)

class RetrievalTask(BaseModel):
    engine_name: str # e.g., 'table', 'financial', 'vector', 'graph'
    query: str
    metadata_filters: QueryMetadata
    task_id: str

class RetrievalPlan(BaseModel):
    tasks: List[RetrievalTask]
    aggregator_strategy: str # e.g., 'merge', 'calculate', 'compare'

class AdaptivePlanner:
    """
    Orchestrates the retrieval strategy based on query intent.
    Creates a multi-hop plan that dispatches to various specialized engines.
    """
    
    def __init__(self):
        pass
        
    def create_plan(self, analysis: AnalysisResult, original_query: str) -> RetrievalPlan:
        """
        Creates a RetrievalPlan containing multiple RetrievalTasks based on the intent.
        """
        intent = analysis.intent
        tasks = []
        strategy = "merge"
        
        logger.info(f"Creating retrieval plan for intent: {intent.name}")
        
        if intent == QueryIntent.COMPARISON:
            # Example: Compare FY23 and FY24 revenue
            # Split into two tasks (this is a simplified heuristic, an LLM could split it more intelligently)
            # We'll just issue two vector tasks with different hypothetical filters for demonstration,
            # or rely on the aggregator to handle the complex merge.
            # Real enterprise systems use an LLM here to rewrite the query into sub-queries.
            tasks.append(RetrievalTask(
                engine_name="vector",
                query=original_query,
                metadata_filters=analysis.metadata,
                task_id="compare_1"
            ))
            strategy = "compare"
            
        elif intent == QueryIntent.CALCULATION:
            # Example: proportion of revenue
            # In a fully realized system, this would split into "find X" and "find Y".
            tasks.append(RetrievalTask(
                engine_name="vector",
                query=original_query,
                metadata_filters=analysis.metadata,
                task_id="calc_1"
            ))
            strategy = "calculate"
            
        elif intent == QueryIntent.TABLE:
            tasks.append(RetrievalTask(
                engine_name="table",
                query=original_query,
                metadata_filters=analysis.metadata,
                task_id="table_1"
            ))
            
        elif intent == QueryIntent.STRUCTURAL:
            tasks.append(RetrievalTask(
                engine_name="graph",
                query=original_query,
                metadata_filters=analysis.metadata,
                task_id="graph_1"
            ))
            
        elif intent == QueryIntent.FACT:
            # Check if it looks like a financial fact
            if any(k in original_query.lower() for k in ["revenue", "margin", "eps", "income", "expense"]):
                tasks.append(RetrievalTask(
                    engine_name="financial",
                    query=original_query,
                    metadata_filters=analysis.metadata,
                    task_id="fin_1"
                ))
            else:
                tasks.append(RetrievalTask(
                    engine_name="vector",
                    query=original_query,
                    metadata_filters=analysis.metadata,
                    task_id="vec_1"
                ))
                
        else:
            # Default fallback to Vector + Graph hybrid (the old way)
            tasks.append(RetrievalTask(
                engine_name="vector",
                query=original_query,
                metadata_filters=analysis.metadata,
                task_id="vec_fallback"
            ))
            
        return RetrievalPlan(tasks=tasks, aggregator_strategy=strategy)
