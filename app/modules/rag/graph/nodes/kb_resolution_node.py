import re
import json
import os
import time
import duckdb
import logging
from app.modules.rag.graph.state import GraphState
from app.core.parquet_ingester import ParquetIngester
from app.modules.rag.schema_utils import get_schema_columns, calculate_schema_overlap_score

logger = logging.getLogger(__name__)
# Simple cache for ID index equivalent to self._id_index_cache in service.py
_id_index_cache = {}

async def kb_resolution_node(state: GraphState) -> GraphState:
    """
    Handles Access Control & KB Resolution.
    - Evaluates schema-overlap scoring.
    - Triggers Entity-Presence-Probe fallback.
    - Handles multi-KB disambiguation logic (Phase 7 stub).
    """
    query = state["query"]
    tenant_id = state["tenant_id"]
    agent_id = state["agent_id"]
    kb_ids = state.get("kb_ids", [])
    effective_target_kb_id = state.get("target_kb_id")

    excel_kbs = []
    doc_kbs = []

    if kb_ids:
        from app.core.database import get_db_with_tenant
        from app.modules.knowledge_bases.repository import KnowledgeBaseRepository
        async with get_db_with_tenant(tenant_id) as session:
            repo = KnowledgeBaseRepository(session, tenant_id)
            for kid in kb_ids:
                kb = await repo.get_by_id(kid)
                if kb:
                    session.expunge(kb)
                    if str(kb.agent_id) == str(agent_id):
                        if getattr(kb, "description", "") == "excel_parquet":
                            excel_kbs.append(kb)
                        else:
                            doc_kbs.append(kb)

    updates = {}
    if effective_target_kb_id:
        selected_kb = next((k for k in excel_kbs if str(k.id) == effective_target_kb_id), None)
        if selected_kb:
            excel_kbs = [selected_kb]
            updates["target_kb_id"] = str(selected_kb.id)

    updates["excel_kbs"] = excel_kbs
    updates["doc_kbs"] = doc_kbs

    if not excel_kbs:
        return updates

    kb_scores = []
    for kb in excel_kbs:
        ds = getattr(kb, "dataset_schema", None)
        cv = getattr(kb, "categorical_values", None)
        name = getattr(kb, "parsed_path", None) or getattr(kb, "name", None)
        
        cat_score, gen_score = calculate_schema_overlap_score(query, ds, cv, name)
        total_score = cat_score * 2 + gen_score
        kb_scores.append({"kb": kb, "name": name, "cat_score": cat_score, "gen_score": gen_score, "total_score": total_score})


    if kb_scores:
        max_total = max(s["total_score"] for s in kb_scores)
        tied = [s for s in kb_scores if s["total_score"] == max_total]

        # Tiebreaker: exact membership check on ID index
        if len(tied) > 1 and all(s["cat_score"] == 0 for s in tied):
            from app.modules.rag.schema_utils import ID_REGEX_PATTERN
            extracted_id_match = re.search(ID_REGEX_PATTERN, query)
            extracted_id = extracted_id_match.group(0) if extracted_id_match else None
            
            if extracted_id:
                token = extracted_id.upper().strip()
                matches = []
                for s in tied:
                    index = _get_id_index(s["kb"])
                    if any(token in vals for vals in index.values()):
                        matches.append(s)
                        
                if len(matches) == 1:
                    matches[0]["total_score"] += 100
                    logger.info(f"Resolved ambiguous routing via ID-index: {token} found only in {matches[0]['name']}")

        # Re-eval max after tiebreaker
        max_total = max(s["total_score"] for s in kb_scores)

        # --- ENTITY PRESENCE PROBE FALLBACK ---
        MIN_BASELINE = 4
        probe_hits = []
        if max_total < MIN_BASELINE:
            entity_candidates = re.findall(r'"([^"]+)"|\'([^\']+)\'|\b([A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)+)\b', query)
            entity_to_probe = None
            for cand in entity_candidates:
                extracted = cand[0] or cand[1] or cand[2]
                if extracted and len(extracted) > 3:
                    entity_to_probe = extracted.strip()
                    break
            
            if entity_to_probe:
                for s in kb_scores:
                    path = getattr(s["kb"], "parsed_path", None)
                    if not path: continue
                    active_path = ParquetIngester.get_active_dataset(path)
                    if not active_path: continue
                    text_cols = get_schema_columns(getattr(s["kb"], "dataset_schema", None), getattr(s["kb"], "categorical_values", None))
                    if not text_cols: continue
                        
                    concat_expr = "CONCAT_WS(' ', " + ", ".join([f'"{c}"' for c in text_cols]) + ")"
                    probe_sql = f"SELECT 1 FROM read_parquet(?) WHERE {concat_expr} ILIKE ? LIMIT 1"
                    try:
                        with duckdb.connect() as con:
                            res = con.execute(probe_sql, [active_path, f"%{entity_to_probe}%"]).fetchall()
                        if res:
                            probe_hits.append(s)
                    except Exception as e:
                        logger.warning(f"Probe failed on {s['name']}: {e}")
                        
                if len(probe_hits) == 1:
                    probe_hits[0]["total_score"] += 100
                    max_total = max(s_kb["total_score"] for s_kb in kb_scores)

        # Final Routing Selection
        close_scorers = [s for s in kb_scores if max_total - s["total_score"] <= 1 and s["total_score"] > 0]
        top_scorers = [s for s in kb_scores if s["total_score"] == max_total]
        
        if max_total == 0 and not probe_hits:
            updates["clarification_payload"] = {"error": "No matching schema found"}
            updates["requires_clarification"] = False
        elif len(close_scorers) > 1:
            # Phase 7: Dispatch Clarification for ambiguous top matches
            updates["requires_clarification"] = True
            updates["clarification_payload"] = {
                "type": "clarification_needed",
                "message": "Multiple datasets seem highly relevant. Please select one to proceed:",
                "candidates": [{"kb_id": str(s["kb"].id), "filename": s["name"]} for s in close_scorers]
            }
        else:
            updates["target_kb_id"] = str(top_scorers[0]["kb"].id)
            updates["excel_kbs"] = [top_scorers[0]["kb"]]

    return updates

def _get_id_index(kb):
    path = getattr(kb, "parsed_path", None)
    if not path: return {}
    base = os.path.splitext(os.path.basename(path))[0]
    version = base.split("_")[-1] if "_" in base else "unknown"
    kb_id_str = str(kb.id)
    cached = _id_index_cache.get(kb_id_str)
    if cached and cached[0] == version: return cached[1]
    index_path = os.path.join(os.path.dirname(path), f"{base}_idindex.json")
    if os.path.exists(index_path):
        with open(index_path, 'r') as f:
            index = json.load(f)
        for col in index: index[col] = set(index[col])
        _id_index_cache[kb_id_str] = (version, index)
        return index
    return {}
