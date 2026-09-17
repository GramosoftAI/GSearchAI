import sys, os
sys.path.append(os.path.abspath('.'))
from app.modules.rag.graph.workflow import build_rag_graph

def verify_graph():
    try:
        app = build_rag_graph()
        print(f"\\n[SUCCESS] Graph built and compiled successfully.")
        print(f"Nodes: {list(app.nodes.keys())}")
        print("[BSP WIRING VERIFIED]")
    except Exception as e:
        print(f"Graph verification failed: {e}")
        exit(1)

if __name__ == "__main__":
    verify_graph()
