"""Request-scoped QueryPipelineContext.

Carries stage state for one NL-to-SQL query. Created per request; never stored on
class-level registries or process-global singletons.

Identity fields (question, tenant, knowledgebase, query_id) are set at construction
and are not proof of authorization — callers must still authorize via repository/RLS.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
import uuid

from ..observability.sanitizer import AuditSanitizer
from ..semantic.memory import VerifiedQueryMemory


class QueryPipelineContext:
    """Single request-scoped bag for the production query_database() pipeline.

    Stage outputs remain Optional until that stage runs. Diagnostics never include
    credentials, SQL parameter literals, or result rows.
    """

    __slots__ = (
        "_original_question",
        "_normalized_question",
        "_working_question",
        "_tenant_id",
        "_knowledgebase_id",
        "_query_id",
        "_request_id",
        "_user_id",
        "schema_version",
        "canonical_schema",
        "security_overrides",
        "resolved_entities",
        "disambiguation_notices",
        "retrieval_result",
        "retrieved_table_names",
        "retrieved_column_names",
        "semantic_resolution",
        "plan",
        "planned_table_names",
        "candidate_sql",
        "generated_sql",
        "execution_result",
        "evidence_row_count",
        "evidence_truncated",
        "answer",
        "tracer",
        "current_stage",
        "stage_latency_ms",
        "audit_context",
    )

    def __init__(
        self,
        *,
        original_question: str,
        tenant_id: Union[str, uuid.UUID],
        knowledgebase_id: uuid.UUID,
        query_id: Optional[str] = None,
        request_id: Optional[str] = None,
        user_id: Optional[Any] = None,
    ) -> None:
        question = original_question if isinstance(original_question, str) else str(original_question)
        self._original_question = question
        self._normalized_question = VerifiedQueryMemory.normalize_query(question)
        self._working_question = question
        self._tenant_id = str(tenant_id)
        self._knowledgebase_id = knowledgebase_id if isinstance(knowledgebase_id, uuid.UUID) else uuid.UUID(str(knowledgebase_id))
        self._query_id = str(query_id) if query_id else str(uuid.uuid4())
        self._request_id = str(request_id) if request_id else None
        self._user_id = str(user_id) if user_id is not None else None

        self.schema_version: Optional[str] = None
        self.canonical_schema: Optional[Any] = None
        self.security_overrides: Dict[str, Any] = {}
        self.resolved_entities: List[Any] = []
        self.disambiguation_notices: List[str] = []
        self.retrieval_result: Optional[Any] = None
        self.retrieved_table_names: List[str] = []
        self.retrieved_column_names: Dict[str, List[str]] = {}
        self.semantic_resolution: Optional[Any] = None
        self.plan: Optional[Any] = None
        self.planned_table_names: List[str] = []
        self.candidate_sql: Optional[Any] = None
        self.generated_sql: Optional[str] = None
        self.execution_result: Optional[Any] = None
        self.evidence_row_count: Optional[int] = None
        self.evidence_truncated: Optional[bool] = None
        self.answer: Optional[Any] = None
        self.tracer: Optional[Any] = None
        self.current_stage: str = "INITIALIZATION"
        self.stage_latency_ms: Dict[str, float] = {}
        self.audit_context: Dict[str, Any] = {
            "query_id": self._query_id,
            "tenant_id": self._tenant_id,
            "knowledgebase_id": str(self._knowledgebase_id),
        }

    @classmethod
    def create(
        cls,
        *,
        original_question: str,
        tenant_id: Union[str, uuid.UUID],
        knowledgebase_id: uuid.UUID,
        query_id: Optional[str] = None,
        request_id: Optional[str] = None,
        user_id: Optional[Any] = None,
    ) -> "QueryPipelineContext":
        return cls(
            original_question=original_question,
            tenant_id=tenant_id,
            knowledgebase_id=knowledgebase_id,
            query_id=query_id,
            request_id=request_id,
            user_id=user_id,
        )

    # ----- identity (immutable after construct) -----

    @property
    def original_question(self) -> str:
        return self._original_question

    @property
    def normalized_question(self) -> str:
        return self._normalized_question

    @property
    def working_question(self) -> str:
        return self._working_question

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    @property
    def knowledgebase_id(self) -> uuid.UUID:
        return self._knowledgebase_id

    @property
    def query_id(self) -> str:
        return self._query_id

    @property
    def request_id(self) -> Optional[str]:
        return self._request_id

    @property
    def user_id(self) -> Optional[str]:
        return self._user_id

    def assert_scope(
        self,
        tenant_id: Union[str, uuid.UUID],
        knowledgebase_id: uuid.UUID,
    ) -> None:
        """Context IDs are not authorization. Callers must still authorize the KB.

        This check only prevents accidentally mixing two requests' identifiers
        onto the same context instance.
        """
        if str(tenant_id) != self._tenant_id:
            raise ValueError("QueryPipelineContext tenant_id does not match caller tenant_id")
        kb = knowledgebase_id if isinstance(knowledgebase_id, uuid.UUID) else uuid.UUID(str(knowledgebase_id))
        if kb != self._knowledgebase_id:
            raise ValueError("QueryPipelineContext knowledgebase_id does not match caller knowledgebase_id")

    def set_working_question(self, question: str) -> None:
        """Record a rewritten question used by retrieval/SQL prompts. Original is preserved."""
        if not isinstance(question, str):
            question = str(question)
        self._working_question = question

    def bind_schema(
        self,
        *,
        canonical_schema: Optional[Any] = None,
        schema_version: Optional[str] = None,
        security_overrides: Optional[Dict[str, Any]] = None,
    ) -> None:
        if canonical_schema is not None:
            self.canonical_schema = canonical_schema
        if schema_version:
            self.schema_version = schema_version
        elif canonical_schema is not None:
            self.schema_version = getattr(canonical_schema, "fingerprint", self.schema_version)
        if security_overrides is not None:
            self.security_overrides = dict(security_overrides)

    def record_entities(
        self,
        resolved_entities: Optional[List[Any]] = None,
        notices: Optional[List[str]] = None,
    ) -> None:
        if resolved_entities is not None:
            self.resolved_entities = list(resolved_entities)
        if notices:
            self.disambiguation_notices.extend(notices)

    def record_retrieval(self, retrieval_result: Any, latency_ms: Optional[float] = None) -> None:
        """Store retrieval output and snapshot table names *before* later planner mutation."""
        self.retrieval_result = retrieval_result
        tables = list(getattr(retrieval_result, "retrieved_tables", None) or [])
        names: List[str] = []
        columns: Dict[str, List[str]] = {}
        for tbl in tables:
            name = getattr(tbl, "table_name", None) or str(tbl)
            names.append(name)
            cols = getattr(tbl, "columns", None) or {}
            if isinstance(cols, dict):
                columns[name] = [c if isinstance(c, str) else getattr(c, "name", str(c)) for c in cols.keys()]
            elif isinstance(cols, (list, tuple)):
                columns[name] = [c if isinstance(c, str) else getattr(c, "name", str(c)) for c in cols]
        self.retrieved_table_names = list(names)
        self.retrieved_column_names = columns
        version = getattr(retrieval_result, "schema_version", None)
        if version:
            self.schema_version = version
        if latency_ms is not None:
            self.stage_latency_ms["retrieval"] = float(latency_ms)
        self.current_stage = "RETRIEVAL"

    def record_semantic(self, semantic_resolution: Any) -> None:
        self.semantic_resolution = semantic_resolution
        self.current_stage = "SEMANTIC"

    def record_plan(self, plan: Any, latency_ms: Optional[float] = None) -> None:
        self.plan = plan
        tables = list(getattr(plan, "tables", None) or [])
        names: List[str] = []
        for t in tables:
            names.append(getattr(t, "table_name", None) or str(t))
        self.planned_table_names = names
        if latency_ms is not None:
            self.stage_latency_ms["planning"] = float(latency_ms)
        self.current_stage = "PLANNING"

    def record_sql(self, candidate_sql: Any, latency_ms: Optional[float] = None) -> None:
        self.candidate_sql = candidate_sql
        parameterized = getattr(candidate_sql, "parameterized", None)
        sql_text = None
        if parameterized is not None:
            sql_text = getattr(parameterized, "parameterized_sql", None)
        if not sql_text:
            sql_text = getattr(candidate_sql, "sanitized_sql", None) or getattr(candidate_sql, "raw_sql", None)
        self.generated_sql = sql_text
        if latency_ms is not None:
            self.stage_latency_ms["sql_generation"] = float(latency_ms)
        self.current_stage = "SQL_GENERATION"

    def record_execution(self, execution_result: Any, latency_ms: Optional[float] = None) -> None:
        self.execution_result = execution_result
        self.evidence_row_count = getattr(execution_result, "row_count", None)
        self.evidence_truncated = getattr(execution_result, "truncated", None)
        if latency_ms is not None:
            self.stage_latency_ms["execution"] = float(latency_ms)
        self.current_stage = "EXECUTION"

    def record_answer(self, answer: Any, latency_ms: Optional[float] = None) -> None:
        self.answer = answer
        if latency_ms is not None:
            self.stage_latency_ms["synthesis"] = float(latency_ms)
        self.current_stage = "ANSWER"

    def diagnostics(self) -> Dict[str, Any]:
        """Safe metadata for traces. Omits credentials, parameter literals, and rows."""
        params = {}
        parameterized = getattr(self.candidate_sql, "parameterized", None) if self.candidate_sql is not None else None
        raw_params = getattr(parameterized, "parameters", None) if parameterized is not None else None
        if isinstance(raw_params, dict):
            params = AuditSanitizer.sanitize_parameters(raw_params)

        _, q_hash, q_len = AuditSanitizer.sanitize_user_query(self._original_question)
        return {
            "query_id": self._query_id,
            "request_id": self._request_id,
            "tenant_id": self._tenant_id,
            "knowledgebase_id": str(self._knowledgebase_id),
            "query_length": q_len,
            "query_hash": q_hash,
            "has_working_question": self._working_question != self._original_question,
            "schema_version": self.schema_version,
            "current_stage": self.current_stage,
            "retrieved_table_names": list(self.retrieved_table_names),
            "planned_table_names": list(self.planned_table_names),
            "generated_sql_present": bool(self.generated_sql),
            "sql_parameter_shapes": params,
            "evidence_row_count": self.evidence_row_count,
            "evidence_truncated": self.evidence_truncated,
            "stage_latency_ms": dict(self.stage_latency_ms),
            "resolved_entity_count": len(self.resolved_entities),
        }
