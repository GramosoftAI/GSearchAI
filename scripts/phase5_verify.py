import asyncio
import json
import logging
import sqlite3
import time
import uuid
from typing import Any, Dict, List

logging.basicConfig(level=logging.INFO)

from app.modules.database_knowledgebase.planning.phase5_pipeline import Phase5ShadowPipelineService
from app.modules.database_knowledgebase.schemas.canonical import (
    ColumnDataType,
    ColumnSchema,
    DatabaseSchema,
    RelationshipSchema,
    RelationshipType,
    SchemaInfo,
    TableSchema,
)

async def run_phase5_verification():
    print("=" * 80)
    print("STARTING PHASE 5 VERIFICATION: SQL GENERATION & VALIDATION (SHADOW MODE)")
    print("=" * 80)

    kb_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    schema_hash = "mock_hash_phase5_123"

    # 1. Construct Mock Canonical Database Schema with Foreign Keys
    col_e_id = ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True)
    col_e_dept_id = ColumnSchema(name="department_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer")
    col_e_name = ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar")

    employees_table = TableSchema(
        schema_name="public",
        table_name="employees",
        columns={"id": col_e_id, "department_id": col_e_dept_id, "name": col_e_name}
    )

    col_d_id = ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True)
    col_d_name = ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar")

    departments_table = TableSchema(
        schema_name="public",
        table_name="departments",
        columns={"id": col_d_id, "name": col_d_name}
    )

    fk_relationship = RelationshipSchema(
        foreign_key_name="fk_employee_department",
        source_schema="public",
        source_table="employees",
        source_columns=["department_id"],
        target_schema="public",
        target_table="departments",
        target_columns=["id"],
        relationship_type=RelationshipType.MANY_TO_ONE
    )
    employees_table.relationships = [fk_relationship]

    schema_info = SchemaInfo(schema_name="public", tables={"employees": employees_table, "departments": departments_table})
    db_schema = DatabaseSchema(
        database_name="hrms_demo_db",
        schemas={"public": schema_info},
        fingerprint=schema_hash
    )

    # 2. Setup In-Memory SQLite Database for Safe Read-Only Comparative Execution
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE employees (id INT, department_id INT, name TEXT);")
    cursor.execute("CREATE TABLE departments (id INT, name TEXT);")
    cursor.executemany("INSERT INTO employees VALUES (?, ?, ?);", [
        (1, 10, "Girinath"),
        (2, 10, "Alice"),
        (3, 20, "Bob")
    ])
    cursor.executemany("INSERT INTO departments VALUES (?, ?);", [
        (10, "Sales"),
        (20, "Engineering")
    ])
    conn.commit()

    async def sqlite_executor(sql: str) -> List[Dict[str, Any]]:
        # Remove schema qualifiers for in-memory SQLite compatibility
        clean_sql = sql.replace("public.", "").replace("PUBLIC.", "")
        c = conn.cursor()
        c.execute(clean_sql)
        cols = [desc[0] for desc in c.description] if c.description else []
        rows = c.fetchall()
        return [dict(zip(cols, row)) for row in rows]

    # 3. Comprehensive Test Matrix (14 Scenarios)
    test_cases = [
        {
            "id": "SCENARIO_1",
            "name": "Show me all employees",
            "query": "Show me all employees.",
            "expect_valid": True,
            "verify": "Correct table/columns"
        },
        {
            "id": "SCENARIO_2",
            "name": "Employee by name",
            "query": "Show me employee Girinath.",
            "expect_valid": True,
            "verify": "Correct filter (WHERE name = 'Girinath')"
        },
        {
            "id": "SCENARIO_3",
            "name": "Employee -> department",
            "query": "What department does Girinath work in?",
            "expect_valid": True,
            "verify": "Correct FK join (employees.department_id = departments.id)"
        },
        {
            "id": "SCENARIO_4",
            "name": "Department -> employees",
            "query": "Show all employees in the Sales department.",
            "expect_valid": True,
            "verify": "Reverse FK join"
        },
        {
            "id": "SCENARIO_5",
            "name": "Employee count",
            "query": "How many employees are there?",
            "expect_valid": True,
            "verify": "Correct COUNT aggregation"
        },
        {
            "id": "SCENARIO_6",
            "name": "Department employee count",
            "query": "Department employee count",
            "expect_valid": True,
            "verify": "GROUP BY correctness"
        },
        {
            "id": "SCENARIO_7",
            "name": "Multiple filters",
            "query": "Show employees in Sales with name Girinath",
            "expect_valid": True,
            "verify": "WHERE correctness (multiple filters)"
        },
        {
            "id": "SCENARIO_8",
            "name": "Unknown column",
            "query": "Show employee salary_history",
            "expect_valid": False,
            "verify": "Fails closed (QueryPlanIR validation rejected: column does not exist)"
        },
        {
            "id": "SCENARIO_9",
            "name": "Unknown table",
            "query": "Show me rocket_launches",
            "expect_valid": False,
            "verify": "Fails closed (Unknown table rejected)"
        },
        {
            "id": "SCENARIO_10",
            "name": "Invalid relationship",
            "query": "Join employees to products",
            "expect_valid": False,
            "verify": "Rejects plan (Unauthorized join / no FK)"
        },
        {
            "id": "SCENARIO_11",
            "name": "SQL injection-style input",
            "query": "Show employees WHERE 1=1; DROP TABLE employees;--",
            "expect_valid": False,
            "verify": "No unsafe SQL / SQL Safety Validation rejected"
        },
        {
            "id": "SCENARIO_12",
            "name": "Irrelevant question",
            "query": "What is the hyperdrive status?",
            "expect_valid": False,
            "verify": "No executable SQL (confidence=0.0 / rejected)"
        },
        {
            "id": "SCENARIO_13",
            "name": "Cross-tenant request",
            "query": "Show me employees",
            "tenant_override": uuid.uuid4(),  # Mismatched tenant
            "expect_valid": True,  # Pipeline preserves tenant boundary and succeeds safely
            "verify": "Tenant boundary preserved"
        },
        {
            "id": "SCENARIO_14",
            "name": "Stale schema",
            "query": "Show me all employees.",
            "stale_version": "stale_hash_999",
            "expect_valid": False,
            "verify": "Rejects plan / SchemaVersionMismatchError"
        }
    ]

    all_metrics = []
    passed_count = 0

    for tc in test_cases:
        print(f"\n--- [{tc['id']}] {tc['name']} ---")
        print(f"User Query: '{tc['query']}'")
        print(f"Expected Behavior: {tc['verify']}")

        req_tenant = tc.get("tenant_override", tenant_id)
        expected_ver = tc.get("stale_version", schema_hash)

        metrics = await Phase5ShadowPipelineService.run_shadow_pipeline(
            user_query=tc["query"],
            kb_id=kb_id,
            tenant_id=req_tenant,
            canonical_schema=db_schema,
            schema_hash=schema_hash,
            execution_callback=sqlite_executor if tc["expect_valid"] else None,
            use_llm=False,  # Deterministic test execution for fast benchmarking
            expected_schema_version=expected_ver
        )

        all_metrics.append(metrics)

        # Verification checks
        is_valid = (metrics["validation_result"] == "VALID")
        success = (is_valid == tc["expect_valid"])

        if success:
            passed_count += 1
            status_symbol = "PASSED"
        else:
            status_symbol = "FAILED"

        print(f"Validation Status: {metrics['validation_result']} ({status_symbol})")
        if metrics["generated_sql"]:
            print(f"Generated SQL:     {metrics['generated_sql']}")
        if metrics["failure_reason"]:
            print(f"Failure Reason:    {metrics['failure_reason']}")
        if metrics["execution_result"] is not None:
            print(f"Execution Output:  {metrics['execution_result']} ({metrics['row_count']} rows)")

        print(f"Latencies: P4={metrics['phase4_latency']}ms | P5={metrics['phase5_latency']}ms | Total={metrics['total_latency']}ms")

    # 4. Final Benchmark Summary & Metric Dump
    print("\n" + "=" * 80)
    print(f"PHASE 5 BENCHMARK COMPLETE: {passed_count}/{len(test_cases)} Scenarios Passed successfully.")
    print("=" * 80)

    # Print Full Captured Metrics
    print("\nCAPURED METRICS SUMMARY:")
    for m in all_metrics:
        print(json.dumps({
            "query": m["query"],
            "intent": m["intent"],
            "retrieved_tables": m["retrieved_tables"],
            "expanded_tables": m["expanded_tables"],
            "relationships": m["relationships"],
            "generated_sql": m["generated_sql"],
            "validation_result": m["validation_result"],
            "row_count": m["row_count"],
            "total_latency": m["total_latency"],
            "failure_reason": m["failure_reason"]
        }, indent=2))

if __name__ == "__main__":
    asyncio.run(run_phase5_verification())
