import json
import os
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class TelemetryOptimizer:
    """
    Parses telemetry logs to compute engine success rates and dynamically
    adjust engine priority.
    """
    LOG_FILE = "v:/graphmind/logs/telemetry.jsonl"
    
    _engine_stats: Dict[str, Dict[str, Any]] = {}
    
    @classmethod
    def load_stats(cls):
        """Reads telemetry.jsonl and calculates success rates per intent/engine."""
        if not os.path.exists(cls.LOG_FILE):
            return
            
        try:
            with open(cls.LOG_FILE, 'r') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                        intent = entry.get("intent", "UNKNOWN")
                        metrics = entry.get("metrics", {})
                        conflict = metrics.get("conflict_found", False)
                        
                        if intent not in cls._engine_stats:
                            cls._engine_stats[intent] = {"total": 0, "conflicts": 0}
                            
                        cls._engine_stats[intent]["total"] += 1
                        if conflict:
                            cls._engine_stats[intent]["conflicts"] += 1
                    except Exception as e:
                        logger.error(f"Error parsing telemetry line: {e}")
        except Exception as e:
            logger.error(f"Failed to read telemetry: {e}")
            
    @classmethod
    def get_penalty_multiplier(cls, intent: str) -> float:
        """Returns a penalty multiplier based on historical conflict rates for an intent."""
        stats = cls._engine_stats.get(intent)
        if not stats or stats["total"] == 0:
            return 1.0
            
        conflict_rate = stats["conflicts"] / stats["total"]
        # If conflict rate is high, we multiply the cost by (1 + conflict_rate * 2)
        return 1.0 + (conflict_rate * 2.0)
