import json
import os
import time
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class TelemetryLogger:
    """
    Logs retrieval metrics for automated regression testing and enterprise auditing.
    """
    
    LOG_FILE = "v:/graphmind/logs/telemetry.jsonl"
    
    @classmethod
    def _ensure_dir(cls):
        os.makedirs(os.path.dirname(cls.LOG_FILE), exist_ok=True)
        
    @classmethod
    def log_query(cls, query: str, intent: str, planner_latency: float, engine_latency: float, 
                  coverage_score: float, conflict_found: bool, token_usage: int, evidence_count: int):
        
        cls._ensure_dir()
        
        entry = {
            "timestamp": time.time(),
            "query": query,
            "intent": intent,
            "metrics": {
                "planner_latency_sec": round(planner_latency, 3),
                "engine_latency_sec": round(engine_latency, 3),
                "coverage_score": round(coverage_score, 2),
                "conflict_found": conflict_found,
                "token_usage": token_usage,
                "evidence_count": evidence_count
            }
        }
        
        try:
            with open(cls.LOG_FILE, 'a') as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.error(f"Failed to write telemetry: {e}")
