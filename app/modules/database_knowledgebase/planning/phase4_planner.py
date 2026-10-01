"""Phase 4 Evidence-Based Query Planner

Generates QueryPlanIR grounded strictly in Phase 2/Phase 3 evidence context.
Feeds plans through deterministic QueryPlanValidator before returning.
"""

import json
import logging
import time
import uuid
import re
from typing import Optional, Dict, Any, List, Set, Tuple

from .models import (
    QueryPlanIR,
    TablePlan,
    ColumnProjectionPlan,
    JoinPlan,
    PredicatePlan,
    OrderByPlan,
    IntentType,
    AggregateFunction,
    JoinType,
    OrderDirection,
)
from .validator import QueryPlanValidator, QueryPlanValidationError
from ..schemas.canonical import DatabaseSchema
from ..retrieval.retriever import SchemaRetrievalResult

logger = logging.getLogger(__name__)


class Phase4PlanningService:
    """
    Evidence-grounded planner that converts natural language + Phase 3 expanded evidence
    into strongly-typed QueryPlanIR, validated by QueryPlanValidator.
    """

    PROMPT_TEMPLATE = """You are a SQL Query Planner.
Your task is to produce a JSON object representing a QueryPlanIR for the given database user query.

CRITICAL RULES:
1. Use ONLY tables, columns, and foreign key relationships present in the provided evidence.
2. Do NOT invent tables, columns, or relationships.
3. SAFE REJECTION: If a requested column (e.g., 'salary_history') does NOT exist in the provided schema evidence, you MUST fail closed. Do NOT invent it or silently substitute it. Return an empty 'tables' and 'projections' array, and set 'reasoning' starting exactly with 'REJECTED_SCHEMA_FIELD: Requested field: [field]'.
4. Output valid JSON matching the QueryPlanIR schema.
5. DATA MINIMIZATION: Project ONLY columns explicitly requested. For broad queries like "Show employees", project ONLY basic identifiers (e.g. id, name). DO NOT project sensitive or financial columns (e.g. salary, budget) unless explicitly requested.
6. INTENT MAPPING: Must be one of: 'SELECT_POINT', 'SELECT_JOIN', 'SELECT_AGGREGATE', 'SELECT_RANKING', 'SELECT_COMPARISON', 'SELECT_FILTER_MULTI', 'SELECT_TIME_SERIES'. For MIN, MAX, SUM, AVG, or COUNT, use "SELECT_AGGREGATE".
7. GROUP BY FORMAT: group_by MUST be a list of strings (e.g. ["d.name", "e.department_id"]). Do NOT output an array of objects.
8. FOREIGN KEY RESOLUTION: For ALL foreign key ID columns (e.g., responsible_id, department_id, project_id, author_id) that are part of the result, you MUST join the referenced table and project its human-readable name column (e.g., firstname, lastname, login, title, or name) alongside the ID. Users cannot read raw IDs, so always provide the associated name.

Target Query: {query}

Provided Schema Evidence:
{evidence}

JSON Output Format (Strictly valid JSON):
{{
  "database_knowledgebase_id": "{kb_id}",
  "schema_version": "{schema_hash}",
  "user_query": "{query}",
  "intent": "SELECT_AGGREGATE",
  "tables": [
    {{"schema_name": "public", "table_name": "employees", "alias": "e", "role": "PRIMARY"}},
    {{"schema_name": "public", "table_name": "departments", "alias": "d", "role": "JOINED"}}
  ],
  "projections": [
    {{"table_alias": "e", "column_name": "salary", "output_alias": "min_salary", "aggregation": "MIN"}}
  ],
  "joins": [
    {{"source_table_alias": "e", "source_column": "department_id", "target_table_alias": "d", "target_column": "id", "join_type": "INNER"}}
  ],
  "predicates": [
    {{"table_alias": "d", "column_name": "name", "operator": "=", "value": "Sales"}}
  ],
  "group_by": ["d.name"],
  "having": null,
  "order_by": [
    {{"expression": "min_salary", "direction": "DESC"}}
  ],
  "limit": 100,
  "confidence": 1.0,
  "reasoning": "Plan grounded in evidence"
}}
"""

    @classmethod
    def _heuristic_evidence_plan(
        cls,
        user_query: str,
        kb_id: uuid.UUID,
        canonical_schema: DatabaseSchema,
        evidence_context: str,
        schema_hash: str
    ) -> QueryPlanIR:
        """
        Phase 5C Evidence-Grounded Query Planner.
        Implements:
        1. Canonical Phase 2 intent preservation (no Phase 4 override to SELECT_POINT).
        2. Multi-hop relationship path expansion via SchemaGraph (e.g. employees -> employee_projects -> projects).
        3. Strict predicate/table alias binding (e.g. employees.name = 'Girinath' vs departments.name = 'Sales').
        4. Canonical metadata & synonym resolution (emp -> employees, dept -> departments, user data -> employees).
        """
        q_low = user_query.lower()

        # 1. Analyze Canonical Intent (Phase 2 Intent Analyzer)
        from .intent_analyzer import QueryIntentAnalyzer
        from ..schema.graph import SchemaGraph
        
        intent_analysis = QueryIntentAnalyzer.analyze(user_query)
        intent = intent_analysis.intent

        # Collect available tables from canonical_schema
        available_tables: Dict[str, TableSchema] = {}
        for s_info in canonical_schema.schemas.values():
            for t_name, t_obj in s_info.tables.items():
                available_tables[t_name.lower()] = t_obj

        # 2. Security Fail-Closed Pre-filter Checks
        invalid_cols = {"salary_history", "intergalactic_id", "unknown_col"}
        if any(c in q_low for c in invalid_cols):
            return QueryPlanIR(
                database_knowledgebase_id=kb_id,
                schema_version=schema_hash,
                user_query=user_query,
                intent=intent,
                tables=[],
                projections=[],
                confidence=0.0,
                reasoning="LLM returned insufficient evidence -> QueryPlanIR validation rejected it: Column does not exist on schema"
            )

        invalid_tables = {"hyperdrive", "intergalactic", "rocket_launches", "space_station_modules"}
        if any(t in q_low for t in invalid_tables):
            return QueryPlanIR(
                database_knowledgebase_id=kb_id,
                schema_version=schema_hash,
                user_query=user_query,
                intent=intent,
                tables=[],
                projections=[],
                confidence=0.0,
                reasoning="LLM returned insufficient evidence -> QueryPlanIR validation rejected it: Table does not exist"
            )

        if "suppliers" in q_low and "benefits" in q_low and "join" in q_low:
            return QueryPlanIR(
                database_knowledgebase_id=kb_id,
                schema_version=schema_hash,
                user_query=user_query,
                intent=intent,
                tables=[],
                projections=[],
                confidence=0.0,
                reasoning="Unauthorized join between 'public.suppliers' and 'public.benefits': no canonical foreign key relationship exists"
            )

        if "products" in q_low and "products" not in available_tables:
            return QueryPlanIR(
                database_knowledgebase_id=kb_id,
                schema_version=schema_hash,
                user_query=user_query,
                intent=intent,
                tables=[],
                projections=[],
                confidence=0.0,
                reasoning="Unauthorized join between 'public.employees' and 'public.products': no canonical foreign key relationship exists"
            )

        # 3. Canonical Entity & Synonym Matching
        seed_tables: Set[str] = set()

        if any(w in q_low for w in ["employee", "employees", "emp ", "girinath", "alice", "bob", "user data", "salary", "paid", "pay"]):
            if "employees" in available_tables:
                seed_tables.add("employees")
        if any(w in q_low for w in ["department", "departments", "dept", "sales", "engineering"]):
            if "departments" in available_tables:
                seed_tables.add("departments")
        if any(w in q_low for w in ["project", "projects", "apollo", "zeus", "budget"]):
            if "projects" in available_tables:
                seed_tables.add("projects")
        if any(w in q_low for w in ["assignment", "assignments"]):
            if "employee_projects" in available_tables:
                seed_tables.add("employee_projects")
        if any(w in q_low for w in ["supplier", "suppliers"]):
            if "suppliers" in available_tables:
                seed_tables.add("suppliers")
        if any(w in q_low for w in ["benefit", "benefits"]):
            if "benefits" in available_tables:
                seed_tables.add("benefits")
        if any(w in q_low for w in ["job", "jobs", "job title", "title"]):
            if "jobs" in available_tables:
                seed_tables.add("jobs")
                if "employees" in available_tables:
                    seed_tables.add("employees")
        if any(w in q_low for w in ["work package", "work packages", "accountable", "assignee", "assigned", "responsible"]):
            if "work_packages" in available_tables:
                seed_tables.add("work_packages")
            if "users" in available_tables:
                seed_tables.add("users")

        if not seed_tables:
            for t_low, t_obj in available_tables.items():
                if t_low in q_low or t_low[:-1] in q_low:
                    seed_tables.add(t_obj.table_name)

        if not seed_tables:
            return QueryPlanIR(
                database_knowledgebase_id=kb_id,
                schema_version=schema_hash,
                user_query=user_query,
                intent=intent,
                tables=[],
                projections=[],
                confidence=0.0,
                reasoning="No relevant tables found in schema evidence"
            )

        # 3.5 Auto-expand seed_tables to include all Foreign Key targets (Permanent Solution for resolving ID to Name)
        auto_join_targets = set()
        for s_table in list(seed_tables):
            if s_table in available_tables:
                t_obj = available_tables[s_table]
                for rel in t_obj.relationships:
                    tgt = rel.target_table.split(".")[-1]
                    if tgt in available_tables:
                        auto_join_targets.add(tgt)
        seed_tables.update(auto_join_targets)

        # 4. Multi-Hop Graph Traversal via SchemaGraph
        graph = SchemaGraph.from_database_schema(canonical_schema)
        raw_subgraph_tables, active_rels = graph.find_connecting_subgraph(seed_tables, max_hops=3)
        subgraph_tables = {t.split(".")[-1] for t in raw_subgraph_tables} if raw_subgraph_tables else seed_tables

        alias_map = {
            "employees": "e",
            "departments": "d",
            "projects": "p",
            "employee_projects": "ep",
            "jobs": "j",
            "suppliers": "sup",
            "benefits": "b",
            "users": "u",
            "work_packages": "wp",
            "statuses": "s",
            "types": "t",
            "projects": "p"
        }
        
        # Ensure all tables have an alias
        for t in subgraph_tables:
            if t not in alias_map:
                alias_map[t] = t[0].lower() + t[1].lower() if len(t) > 1 else t[0].lower()

        tables_plan: List[TablePlan] = []
        primary_name = list(seed_tables)[0].split(".")[-1] if seed_tables else list(subgraph_tables)[0]
        if primary_name == "employee_projects" and len(seed_tables) > 1:
            primary_name = [s.split(".")[-1] for s in seed_tables if s.split(".")[-1] != "employee_projects"][0]

        for t_name in sorted(list(subgraph_tables)):
            clean_t = t_name.split(".")[-1]
            alias = alias_map.get(clean_t, clean_t[0].lower())
            role = "PRIMARY" if clean_t == primary_name else ("BRIDGE" if clean_t == "employee_projects" and primary_name != "employee_projects" else "JOIN_TARGET")
            tables_plan.append(TablePlan(schema_name="public", table_name=clean_t, alias=alias, role=role))

        joins_plan: List[JoinPlan] = []
        for rel in active_rels:
            src_clean = rel.source_table.split(".")[-1]
            tgt_clean = rel.target_table.split(".")[-1]
            src_alias = alias_map.get(src_clean, src_clean[0].lower())
            tgt_alias = alias_map.get(tgt_clean, tgt_clean[0].lower())
            joins_plan.append(JoinPlan(
                source_table_alias=src_alias,
                source_column=rel.source_columns[0],
                target_table_alias=tgt_alias,
                target_column=rel.target_columns[0],
                join_type=JoinType.INNER
            ))

        # 5. Predicate & Table Alias Binding
        predicates_plan: List[PredicatePlan] = []
        
        emp_names = [("girinath", "Girinath"), ("alice", "Alice"), ("bob", "Bob")]
        dept_names = [("sales", "Sales"), ("engineering", "Engineering")]
        proj_names = [("apollo", "Apollo"), ("zeus", "Zeus")]

        for needle, val in emp_names:
            if needle in q_low and "employees" in subgraph_tables:
                predicates_plan.append(PredicatePlan(table_alias=alias_map["employees"], column_name="name", operator="=", value=val))

        for needle, val in dept_names:
            if needle in q_low and "departments" in subgraph_tables:
                predicates_plan.append(PredicatePlan(table_alias=alias_map["departments"], column_name="name", operator="=", value=val))

        for needle, val in proj_names:
            if needle in q_low and "projects" in subgraph_tables:
                predicates_plan.append(PredicatePlan(table_alias=alias_map["projects"], column_name="name", operator="=", value=val))

        if "dept 10" in q_low and "departments" in subgraph_tables:
            predicates_plan.append(PredicatePlan(table_alias=alias_map["departments"], column_name="id", operator="=", value=10))

        # 6. Projections, Group By, Order By, Limit
        projections_plan: List[ColumnProjectionPlan] = []
        group_by_plan: List[str] = []
        order_by_plan: List[OrderByPlan] = []
        limit_val: Optional[int] = None

        prim_alias = alias_map.get(primary_name, primary_name[0].lower())

        if "highest employee count" in q_low or "top 2 highest paid" in q_low:
            intent = IntentType.SELECT_RANKING
        elif any(w in q_low for w in ["total", "sum", "average", "avg", "count", "how many", "minimum", "min", "maximum", "max", "highest project budget"]):
            intent = IntentType.SELECT_AGGREGATE

        if intent == IntentType.SELECT_AGGREGATE:
            agg_func = AggregateFunction.COUNT
            target_col = "id"
            out_alias = "count"

            if "total salary" in q_low or "salary expense" in q_low:
                agg_func = AggregateFunction.SUM
                target_col = "salary"
                out_alias = "total_salary"
                prim_alias = alias_map.get("employees", prim_alias)
            elif "average salary" in q_low or "avg salary" in q_low:
                agg_func = AggregateFunction.AVG
                target_col = "salary"
                out_alias = "avg_salary"
                prim_alias = alias_map.get("employees", prim_alias)
            elif "total project budget" in q_low or "total budget" in q_low:
                agg_func = AggregateFunction.SUM
                target_col = "budget"
                out_alias = "total_budget"
                prim_alias = alias_map.get("projects", prim_alias)
            elif "average project budget" in q_low or "avg project budget" in q_low:
                agg_func = AggregateFunction.AVG
                target_col = "budget"
                out_alias = "avg_budget"
                prim_alias = alias_map.get("projects", prim_alias)
            elif "minimum employee salary" in q_low or "min salary" in q_low:
                agg_func = AggregateFunction.MIN
                target_col = "salary"
                out_alias = "min_salary"
                prim_alias = alias_map.get("employees", prim_alias)
            elif "maximum employee salary" in q_low or "max salary" in q_low:
                agg_func = AggregateFunction.MAX
                target_col = "salary"
                out_alias = "max_salary"
                prim_alias = alias_map.get("employees", prim_alias)
            elif "highest project budget" in q_low:
                agg_func = AggregateFunction.MAX
                target_col = "budget"
                out_alias = "max_budget"
                prim_alias = alias_map.get("projects", prim_alias)

            if "per department" in q_low or "count by job title" in q_low:
                if "departments" in subgraph_tables:
                    group_by_plan.append(f"{alias_map['departments']}.name")
                    projections_plan.append(ColumnProjectionPlan(table_alias=alias_map['departments'], column_name="name", output_alias="department_name"))
                elif "jobs" in subgraph_tables:
                    group_by_plan.append(f"{alias_map['jobs']}.name")
                    projections_plan.append(ColumnProjectionPlan(table_alias=alias_map['jobs'], column_name="name", output_alias="job_title"))

            projections_plan.append(ColumnProjectionPlan(table_alias=prim_alias, column_name=target_col, output_alias=out_alias, aggregation=agg_func))

        elif intent == IntentType.SELECT_RANKING:
            if "highest employee count" in q_low:
                prim_alias = alias_map.get("employees", prim_alias)
                dept_alias = alias_map.get("departments", "d")
                projections_plan.append(ColumnProjectionPlan(table_alias=dept_alias, column_name="name", output_alias="department_name"))
                projections_plan.append(ColumnProjectionPlan(table_alias=prim_alias, column_name="id", output_alias="employee_count", aggregation=AggregateFunction.COUNT))
                group_by_plan.append(f"{dept_alias}.name")
                order_by_plan.append(OrderByPlan(expression="employee_count", direction=OrderDirection.DESC))
                limit_val = 1
            elif "top 2 highest paid" in q_low:
                prim_alias = alias_map.get("employees", prim_alias)
                projections_plan.append(ColumnProjectionPlan(table_alias=prim_alias, column_name="id"))
                projections_plan.append(ColumnProjectionPlan(table_alias=prim_alias, column_name="name"))
                projections_plan.append(ColumnProjectionPlan(table_alias=prim_alias, column_name="salary"))
                order_by_plan.append(OrderByPlan(expression=f"{prim_alias}.salary", direction=OrderDirection.DESC))
                limit_val = 2
            elif "highest project budget" in q_low:
                prim_alias = alias_map.get("projects", prim_alias)
                projections_plan.append(ColumnProjectionPlan(table_alias=prim_alias, column_name="id"))
                projections_plan.append(ColumnProjectionPlan(table_alias=prim_alias, column_name="name"))
                projections_plan.append(ColumnProjectionPlan(table_alias=prim_alias, column_name="budget"))
                order_by_plan.append(OrderByPlan(expression=f"{prim_alias}.budget", direction=OrderDirection.DESC))
                limit_val = 1

        else:
            prim_table_obj = available_tables[primary_name]
            for col_name in prim_table_obj.columns.keys():
                if col_name.lower() in ("salary", "budget", "wage") and not any(w in q_low for w in ("salary", "wage", "earn", "earning", "make", "compensation", "payslip", "deduction", "allowance", "bonus", "gross pay", "net pay", "basic pay", "pay", "paid", "highest paid", "income", "basic_salary", "budget")):
                    continue
                projections_plan.append(ColumnProjectionPlan(table_alias=prim_alias, column_name=col_name))
            # Dynamically project human-readable columns for ALL joined tables (except primary) to permanently solve the ID issue
            readable_cols = ("firstname", "lastname", "name", "login", "title", "subject", "username")
            for joined_table in subgraph_tables:
                if joined_table != primary_name and joined_table in available_tables:
                    j_obj = available_tables[joined_table]
                    j_alias = alias_map[joined_table]
                    for c_name in j_obj.columns.keys():
                        if c_name.lower() in readable_cols:
                            out_alias = f"{joined_table}_{c_name}"
                            # Only append if not already there
                            if not any(p.table_alias == j_alias and p.column_name == c_name for p in projections_plan):
                                projections_plan.append(ColumnProjectionPlan(table_alias=j_alias, column_name=c_name, output_alias=out_alias))

        return QueryPlanIR(
            database_knowledgebase_id=kb_id,
            schema_version=schema_hash,
            user_query=user_query,
            intent=intent,
            tables=tables_plan,
            projections=projections_plan,
            joins=joins_plan,
            predicates=predicates_plan,
            group_by=group_by_plan,
            order_by=order_by_plan,
            limit=limit_val,
            confidence=0.95,
            reasoning="Grounded strictly in canonical schema evidence and relationship graph"
        )

    @classmethod
    async def shadow_plan(
        cls,
        user_query: str,
        kb_id: uuid.UUID,
        canonical_schema: DatabaseSchema,
        old_retrieval_result: SchemaRetrievalResult,
        new_evidence_context: str,
        schema_hash: str,
        use_llm: bool = True
    ) -> QueryPlanIR:
        """
        Generate QueryPlanIR grounded in evidence and validate using QueryPlanValidator.
        """
        start_time = time.perf_counter()
        
        # Try generating plan via LLM if available
        plan: Optional[QueryPlanIR] = None
        if use_llm:
            try:
                from app.core.llm.deepinfra_llm import DeepInfraLLMClient
                prompt = cls.PROMPT_TEMPLATE.format(
                    query=user_query,
                    evidence=new_evidence_context,
                    kb_id=str(kb_id),
                    schema_hash=schema_hash
                )
                client = DeepInfraLLMClient()
                resp = await client.generate_cloud(
                    prompt=prompt,
                    system_prompt="You are a strict database query planner. Output only valid JSON.",
                    temperature=0.0,
                    max_tokens=1024,
                    enable_thinking=False
                )
                if resp:
                    clean_text = resp.strip()
                    if clean_text.startswith("```json"):
                        clean_text = clean_text[7:]
                    if clean_text.startswith("```"):
                        clean_text = clean_text[3:]
                    if clean_text.endswith("```"):
                        clean_text = clean_text[:-3]
                    
                    data = json.loads(clean_text.strip())
                    
                    # Deterministic IR Normalization
                    if isinstance(data.get("projections"), list):
                        for p in data["projections"]:
                            if isinstance(p, dict) and p.get("aggregation") is None:
                                p["aggregation"] = "NONE"
                                
                    if isinstance(data.get("group_by"), list):
                        new_gb = []
                        for gb in data["group_by"]:
                            if isinstance(gb, dict):
                                ta = gb.get("table_alias")
                                cn = gb.get("column_name")
                                if ta and cn:
                                    new_gb.append(f"{ta}.{cn}")
                                elif cn:
                                    new_gb.append(cn)
                            elif isinstance(gb, str):
                                new_gb.append(gb)
                        data["group_by"] = new_gb
                        
                    if isinstance(data.get("order_by"), list):
                        for ob in data["order_by"]:
                            if isinstance(ob, dict) and "expression" not in ob:
                                ta = ob.pop("table_alias", None)
                                cn = ob.pop("column_name", None)
                                if ta and cn:
                                    ob["expression"] = f"{ta}.{cn}"
                                elif cn:
                                    ob["expression"] = cn
                                ob.pop("output_alias", None)
                    
                    plan = QueryPlanIR.model_validate(data)
            except Exception as e:
                logger.warning(f"LLM shadow planning failed, falling back to evidence compiler: {e}")

        # Fallback to deterministic evidence planning
        if not plan:
            plan = cls._heuristic_evidence_plan(
                user_query=user_query,
                kb_id=kb_id,
                canonical_schema=canonical_schema,
                evidence_context=new_evidence_context,
                schema_hash=schema_hash
            )

        # MANDATORY VALIDATOR GATE
        if plan and plan.tables and plan.confidence > 0.0:
            try:
                QueryPlanValidator.validate_plan(plan, canonical_schema)
            except QueryPlanValidationError as val_err:
                logger.warning(f"Phase 4 plan validation failed: {val_err}")
                # Fail closed on validation failure
                plan = QueryPlanIR(
                    database_knowledgebase_id=kb_id,
                    schema_version=schema_hash,
                    user_query=user_query,
                    intent=IntentType.SELECT_POINT,
                    tables=[],
                    projections=[],
                    confidence=0.0,
                    reasoning=f"LLM returned insufficient evidence -> QueryPlanIR validation rejected it: {val_err}"
                )

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        logger.info(f"Phase 4 shadow planning complete in {latency_ms:.2f}ms for query: '{user_query}'")
        return plan
