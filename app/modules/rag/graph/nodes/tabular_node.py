import logging
import time
from app.modules.rag.graph.state import GraphState
from app.modules.rag.pandas_engine import PandasQueryEngine
from app.core.config import get_settings

logger = logging.getLogger(__name__)

async def tabular_node(state: GraphState) -> GraphState:
    """
    Executes Pandas/SQL extraction for structured data.
    Separates fast-path ILIKE template from full SQL generation.
    """
    query = state["query"]
    excel_kbs = state.get("excel_kbs", [])
    csv_kbs = state.get("csv_kbs", [])
    tabular_kbs = excel_kbs + csv_kbs
    
    intent = state.get("intent")
    is_tabular_intent = intent in ["TABULAR_SQL", "DATA_AGGREGATION", "CALCULATION"]
    
    if not tabular_kbs and not is_tabular_intent:
        return {}
        
    from app.core.parquet_ingester import ParquetIngester
    active_paths = []
    active_kbs = []
    for kb in tabular_kbs:
        path = getattr(kb, "parsed_path", None) or getattr(kb, "s3_path", None)
        if path:
            p = ParquetIngester.get_active_dataset(path)
            if p: 
                active_paths.append(p)
                active_kbs.append(kb)

    if tabular_kbs and not active_paths:
        return {
            "tabular_results": "No active dataset found for analysis."
        }

    # If multiple spreadsheets, try to filter by query mention to avoid massive UNIONs
    if len(active_paths) > 1:
        matched_paths = []
        for p, kb in zip(active_paths, active_kbs):
            title = (getattr(kb, "name", "") or "").lower().replace(".csv", "").replace(".xlsx", "").strip()
            if title and title in query.lower():
                matched_paths.append(p)
                
        if len(matched_paths) == 1:
            active_paths = matched_paths
        else:
            candidates = [{"kb_id": str(kb.id), "filename": getattr(kb, "name", "Dataset")} for kb in active_kbs]
            return {
                "requires_clarification": True,
                "clarification_payload": {
                    "type": "clarification_needed",
                    "message": "Multiple datasets matched your query. Please select one to proceed:",
                    "candidates": candidates
                },
                "tabular_results": "Waiting for user clarification on which file to search.",
                "used_sql_fallback": False
            }

    t0 = time.perf_counter()
    try:
        from app.modules.rag.pandas_engine import PandasQueryEngine
        
        # Initialize pandas engine with the active dataset paths (or None to auto-discover)
        engine = PandasQueryEngine(all_dataset_paths=active_paths if active_paths else None)
        t_init = time.perf_counter() - t0
        logger.info(f"[TIMING] PandasQueryEngine initialization took {t_init:.3f}s")
        
        # Execute table analytics
        t1 = time.perf_counter()
        res = await engine.execute_query(query)
        t_exec = time.perf_counter() - t1
        logger.info(f"[TIMING] PandasQueryEngine.execute_query took {t_exec:.3f}s")
        
        return {
            "tabular_results": str(res),
            "tabular_sources": [getattr(kb, "name", "Spreadsheet") for kb in active_kbs],
            "used_sql_fallback": True
        }
    except Exception as e:
        logger.error(f"Tabular node failed: {e}")
        return {
            "tabular_results": f"Error during tabular extraction: {str(e)}",
            "used_sql_fallback": False
        }

