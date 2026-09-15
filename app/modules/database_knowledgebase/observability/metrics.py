"""Production Metrics Collector for Phase 3A: Database Knowledgebase Pipeline

Provides thread-safe, low-overhead, in-memory aggregation of operational metrics:
- Success, failure, and security rejection rates
- Grounding and fallback rates
- LLM usage and repair frequencies
- p50, p95, and p99 latency percentiles via bounded reservoir sampling
- Strictly bounded memory usage (fixed-capacity ring buffer)
- Tenant isolation and Prometheus-compatible exposition
"""

from collections import deque
import math
from threading import Lock
from typing import Any, Deque, Dict, List, Optional, Union
import uuid


class BoundedLatencyReservoir:
    """Thread-safe, fixed-size ring buffer for calculating latency percentiles without unbounded memory."""

    def __init__(self, capacity: int = 1000):
        self.capacity = capacity
        self.samples: Deque[float] = deque(maxlen=capacity)
        self.total_sum: float = 0.0
        self.total_count: int = 0

    def add(self, value_ms: float) -> None:
        self.samples.append(value_ms)
        self.total_sum += value_ms
        self.total_count += 1

    def calculate_percentiles(self) -> Dict[str, float]:
        if not self.samples:
            return {"avg": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0}

        sorted_samples = sorted(self.samples)
        n = len(sorted_samples)

        def _pct(p: float) -> float:
            idx = int(math.ceil((p / 100.0) * n)) - 1
            idx = max(0, min(idx, n - 1))
            return round(sorted_samples[idx], 2)

        avg = round(self.total_sum / self.total_count, 2) if self.total_count > 0 else 0.0
        return {
            "avg": avg,
            "p50": _pct(50.0),
            "p95": _pct(95.0),
            "p99": _pct(99.0),
        }


class TenantMetrics:
    """Counters and latency reservoirs for a single tenant."""

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.total_queries: int = 0
        self.successful_queries: int = 0
        self.failed_queries: int = 0
        self.security_rejections: int = 0
        self.execution_failures: int = 0
        self.timeouts: int = 0
        self.grounding_failures: int = 0
        self.fallback_count: int = 0
        self.llm_usage: int = 0
        self.llm_repairs: int = 0
        self.result_truncations: int = 0

        self.total_latency_reservoir = BoundedLatencyReservoir()
        self.db_latency_reservoir = BoundedLatencyReservoir()
        self.llm_latency_reservoir = BoundedLatencyReservoir()

    def snapshot(self) -> Dict[str, Any]:
        total_lat = self.total_latency_reservoir.calculate_percentiles()
        db_lat = self.db_latency_reservoir.calculate_percentiles()
        llm_lat = self.llm_latency_reservoir.calculate_percentiles()

        q_total = max(1, self.total_queries)
        return {
            "tenant_id": self.tenant_id,
            "counts": {
                "total_queries": self.total_queries,
                "successful_queries": self.successful_queries,
                "failed_queries": self.failed_queries,
                "security_rejections": self.security_rejections,
                "execution_failures": self.execution_failures,
                "timeouts": self.timeouts,
                "grounding_failures": self.grounding_failures,
                "fallback_count": self.fallback_count,
                "llm_usage": self.llm_usage,
                "llm_repairs": self.llm_repairs,
                "result_truncations": self.result_truncations,
            },
            "rates": {
                "query_success_rate": round(self.successful_queries / q_total, 4),
                "query_failure_rate": round(self.failed_queries / q_total, 4),
                "security_rejection_rate": round(self.security_rejections / q_total, 4),
                "execution_success_rate": round(
                    max(0, self.total_queries - self.execution_failures) / q_total, 4
                ),
                "grounding_success_rate": round(
                    max(0, self.total_queries - self.grounding_failures) / q_total, 4
                ),
                "fallback_rate": round(self.fallback_count / q_total, 4),
                "llm_usage_rate": round(self.llm_usage / q_total, 4),
                "llm_repair_rate": round(self.llm_repairs / max(1, self.llm_usage), 4),
                "result_truncation_rate": round(self.result_truncations / q_total, 4),
                "timeout_rate": round(self.timeouts / q_total, 4),
            },
            "latencies_ms": {
                "total": total_lat,
                "database_execution": db_lat,
                "llm": llm_lat,
            },
        }


class DatabaseKnowledgebaseMetrics:
    """Thread-safe singleton metrics collector for the Database Knowledgebase pipeline."""

    _instance: Optional["DatabaseKnowledgebaseMetrics"] = None
    _lock = Lock()

    def __init__(self):
        self._tenants: Dict[str, TenantMetrics] = {}
        self._global = TenantMetrics(tenant_id="global")
        self._mutex = Lock()

    @classmethod
    def get_instance(cls) -> "DatabaseKnowledgebaseMetrics":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _get_or_create_tenant(self, tenant_id: str) -> TenantMetrics:
        if tenant_id not in self._tenants:
            self._tenants[tenant_id] = TenantMetrics(tenant_id=tenant_id)
        return self._tenants[tenant_id]

    def record_query(
        self,
        tenant_id: Union[str, uuid.UUID],
        success: bool,
        total_latency_ms: float,
        db_latency_ms: float = 0.0,
        llm_latency_ms: float = 0.0,
        security_rejected: bool = False,
        execution_failed: bool = False,
        timed_out: bool = False,
        grounding_failed: bool = False,
        fallback_used: bool = False,
        llm_used: bool = False,
        repair_attempts: int = 0,
        truncated: bool = False,
    ) -> None:
        """Record completed or failed query metrics atomically."""
        t_id = str(tenant_id)
        with self._mutex:
            targets = [self._global, self._get_or_create_tenant(t_id)]
            for m in targets:
                m.total_queries += 1
                if success:
                    m.successful_queries += 1
                else:
                    m.failed_queries += 1

                if security_rejected:
                    m.security_rejections += 1
                if execution_failed:
                    m.execution_failures += 1
                if timed_out:
                    m.timeouts += 1
                if grounding_failed:
                    m.grounding_failures += 1
                if fallback_used:
                    m.fallback_count += 1
                if llm_used:
                    m.llm_usage += 1
                if repair_attempts > 0:
                    m.llm_repairs += repair_attempts
                if truncated:
                    m.result_truncations += 1

                m.total_latency_reservoir.add(total_latency_ms)
                if db_latency_ms > 0:
                    m.db_latency_reservoir.add(db_latency_ms)
                if llm_latency_ms > 0:
                    m.llm_latency_reservoir.add(llm_latency_ms)

    def get_metrics(self, tenant_id: Optional[Union[str, uuid.UUID]] = None) -> Dict[str, Any]:
        """Retrieve metrics snapshot filtered strictly by tenant or globally."""
        with self._mutex:
            if tenant_id:
                t_id = str(tenant_id)
                if t_id in self._tenants:
                    return self._tenants[t_id].snapshot()
                return TenantMetrics(tenant_id=t_id).snapshot()
            return self._global.snapshot()

    def to_prometheus_format(self, tenant_id: Optional[Union[str, uuid.UUID]] = None) -> str:
        """Export metrics in standard Prometheus text-based format."""
        snapshot = self.get_metrics(tenant_id)
        lines = []
        t_label = f'tenant_id="{snapshot["tenant_id"]}"'

        lines.append("# HELP db_kb_queries_total Total queries executed")
        lines.append("# TYPE db_kb_queries_total counter")
        for k, v in snapshot["counts"].items():
            lines.append(f'db_kb_queries_total{{{t_label},status="{k}"}} {v}')

        lines.append("# HELP db_kb_rates Query operational rates")
        lines.append("# TYPE db_kb_rates gauge")
        for k, v in snapshot["rates"].items():
            lines.append(f'db_kb_rates{{{t_label},metric="{k}"}} {v}')

        lines.append("# HELP db_kb_latency_ms Latency percentiles in milliseconds")
        lines.append("# TYPE db_kb_latency_ms gauge")
        for stage, pcts in snapshot["latencies_ms"].items():
            for p_name, val in pcts.items():
                lines.append(f'db_kb_latency_ms{{{t_label},stage="{stage}",percentile="{p_name}"}} {val}')

        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        """Reset all metrics (primarily for unit testing)."""
        with self._mutex:
            self._tenants.clear()
            self._global = TenantMetrics(tenant_id="global")
