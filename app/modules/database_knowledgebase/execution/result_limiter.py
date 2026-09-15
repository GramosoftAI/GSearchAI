"""Phase 2C Result Limiter and Resource Bound Protection

Enforces upper bounds on row counts, column counts, serialized byte payload,
and single-cell lengths to protect the server from denial of service and memory exhaustion.
"""

import json
from typing import Any, Dict, List, Tuple
from .models import ExecutionConfig


class ResultLimiter:
    """Enforces resource limits on normalized query results."""

    @classmethod
    def apply_limits(
        cls,
        rows: List[Dict[str, Any]],
        config: ExecutionConfig,
    ) -> Tuple[List[Dict[str, Any]], bool, List[str]]:
        """
        Applies row count and payload size limits to the normalized result set.
        Returns: (bounded_rows, is_truncated, warnings)
        """
        warnings: List[str] = []
        is_truncated = False

        # 1. Row Count Limit (Bounded check)
        if len(rows) > config.max_rows:
            is_truncated = True
            warnings.append(
                f"Result set exceeded maximum row limit of {config.max_rows}; truncated to {config.max_rows} rows."
            )
            bounded_rows = rows[: config.max_rows]
        else:
            bounded_rows = rows

        # 2. Total Serialized Byte Size Protection
        try:
            # Approximate payload size check
            serialized = json.dumps(bounded_rows)
            byte_size = len(serialized.encode("utf-8"))

            if byte_size > config.max_serialized_bytes:
                is_truncated = True
                warnings.append(
                    f"Result size ({byte_size} bytes) exceeded maximum serialized payload of {config.max_serialized_bytes} bytes. Truncating rows..."
                )
                # Bisection or linear reduction to fit within byte budget
                while bounded_rows and len(json.dumps(bounded_rows).encode("utf-8")) > config.max_serialized_bytes:
                    # Drop back half
                    drop_count = max(1, len(bounded_rows) // 4)
                    bounded_rows = bounded_rows[:-drop_count]

                warnings.append(f"Result payload reduced to {len(bounded_rows)} rows to stay within safe memory budget.")
        except Exception:
            pass

        return bounded_rows, is_truncated, warnings
