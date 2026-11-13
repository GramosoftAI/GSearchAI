import sys, os, importlib.util
from langgraph.graph import StateGraph

# Load state.py directly to avoid triggering app/__init__.py chains in tests
spec = importlib.util.spec_from_file_location("state", os.path.abspath("app/modules/rag/graph/state.py"))
state_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(state_module)
GraphState = state_module.GraphState

def test_graph_state_compilation():
    '''
    Test that the GraphState TypedDict is compatible with LangGraph.
    '''
    try:
        workflow = StateGraph(GraphState)
        
        # Add a dummy node to allow compilation
        def dummy_node(state: GraphState):
            return state
            
        workflow.add_node("dummy", dummy_node)
        workflow.set_entry_point("dummy")
        
        app = workflow.compile()
        assert app is not None
        print(f"\\n[SUCCESS] StateGraph compiled with GraphState successfully.")
        print(f"[SCHEMA] Schema structure recognized: {GraphState.__annotations__.keys()}")
    except Exception as e:
        print(f"StateGraph compilation failed with GraphState: {e}")
        exit(1)

if __name__ == "__main__":
    test_graph_state_compilation()
