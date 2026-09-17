from langgraph.graph import StateGraph, END
from app.modules.rag.graph.state import GraphState

from app.modules.rag.graph.nodes.init_node import init_node
from app.modules.rag.graph.nodes.memory_node import memory_node
from app.modules.rag.graph.nodes.kb_resolution_node import kb_resolution_node
from app.modules.rag.graph.nodes.tabular_node import tabular_node
from app.modules.rag.graph.nodes.retrieval_node import retrieval_node
from app.modules.rag.graph.nodes.rerank_node import rerank_node
from app.modules.rag.graph.nodes.generation_node import generation_node
from app.modules.rag.graph.nodes.join_node import join_node
from app.modules.rag.graph.nodes.cleanup_node import cleanup_node

def route_kb(state: GraphState) -> str:
    """Conditional routing from KB Resolution."""
    if state.get("requires_clarification"):
        return END # Pause or return error payload
    # In Phase 2, if tabular KB is chosen, we still let both branches go to the join?
    # No, we only route to what's needed. But the join expects edges.
    # To use BSP properly with conditional edges that might not fire, it's safest
    # if we just let the nodes gracefully no-op if they don't apply.
    # We already made tabular_node and retrieval_node no-op if they don't match intent.
    # So we can just unconditionally route to both, and they will execute or no-op fast.
    return "parallel"

def build_rag_graph() -> StateGraph:
    """
    Builds the LangGraph state machine for the RAG pipeline using BSP fan-in.
    """
    workflow = StateGraph(GraphState)
    
    # 1. Add Nodes
    workflow.add_node("init_node", init_node)
    workflow.add_node("memory_node", memory_node)
    workflow.add_node("kb_resolution_node", kb_resolution_node)
    workflow.add_node("tabular_node", tabular_node)
    workflow.add_node("retrieval_node", retrieval_node)
    workflow.add_node("rerank_node", rerank_node)
    workflow.add_node("join_node", join_node)
    workflow.add_node("generation_node", generation_node)
    workflow.add_node("cleanup_node", cleanup_node)
    
    # 2. Add Edges
    workflow.set_entry_point("init_node")
    
    # Init goes straight to KB Resolution
    workflow.add_edge("init_node", "kb_resolution_node")
    
    # Since nodes no-op if not applicable based on state, we can unconditionally branch
    # from kb_resolution to memory, tabular, and retrieval to keep graph topology simple.
    # By starting memory_node here, it shares the same superstep as retrieval_node, truly parallelizing them.
    workflow.add_edge("kb_resolution_node", "memory_node")
    workflow.add_edge("kb_resolution_node", "tabular_node")
    workflow.add_edge("kb_resolution_node", "retrieval_node")
    
    # Retrieval always goes to Rerank
    workflow.add_edge("retrieval_node", "rerank_node")
    
    # Fan-in Join Point
    # Memory, Rerank, and Tabular all point to the join_node.
    # LangGraph waits for all incoming supersteps to complete before running join_node.
    workflow.add_edge(["memory_node", "rerank_node", "tabular_node"], "join_node")
    
    workflow.add_edge("join_node", "generation_node")
    
    # Cleanup runs last before checkpointing
    workflow.add_edge("generation_node", "cleanup_node")
    workflow.add_edge("cleanup_node", END)
    
    return workflow
