import asyncio
import os
import uuid
import json
import logging

logging.basicConfig(level=logging.INFO)

from app.modules.database_knowledgebase.planning.phase4_planner import Phase4PlanningService
from app.modules.database_knowledgebase.planning.models import QueryPlanIR
from app.modules.database_knowledgebase.schemas.canonical import DatabaseSchema, SchemaInfo, TableSchema, ColumnSchema, ColumnDataType
from app.modules.database_knowledgebase.retrieval.retriever import SchemaRetrievalResult

async def run_benchmark():
    print("Starting Phase 4 Benchmark (Shadow Planning)...")
    kb_id = uuid.uuid4()
    schema_hash = "mock_hash_123"
    
    # Mock Canonical Schema
    col1 = ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True)
    col2 = ColumnSchema(name="department_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer")
    col3 = ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar")
    
    employees_table = TableSchema(
        schema_name="public",
        table_name="employees",
        columns={"id": col1, "department_id": col2, "name": col3}
    )
    
    departments_table = TableSchema(
        schema_name="public",
        table_name="departments",
        columns={"id": col1, "name": col3}
    )
    
    schema_info = SchemaInfo(schema_name="public", tables={"employees": employees_table, "departments": departments_table})
    db_schema = DatabaseSchema(
        database_name="test_db",
        schemas={"public": schema_info},
        fingerprint=schema_hash
    )
    
    # Mock Old Retrieval Result
    old_retrieval_result = SchemaRetrievalResult(
        database_name="test_db",
        database_type="postgres",
        schema_version=schema_hash,
        retrieved_tables=[employees_table, departments_table],
        retrieval_scores={},
        join_paths=[],
        overall_confidence=0.9,
        untrusted_boundary_text="mock xml"
    )
    
    # Mock New Evidence Context (From Phase 3)
    new_evidence_context = """
PRIMARY RETRIEVAL
--- Table: employees ---
Columns: id (INT), department_id (INT), name (VARCHAR)

RELATIONSHIP EXPANSION
employees.department_id -> departments.id

--- Table: departments (Expanded) ---
Columns: id (INT), name (VARCHAR)
"""
    
    test_queries = [
        "Show me all employees.",                         # Simple lookup
        "What department does Girinath work in?",         # Multi-table join
        "How many employees are there?",                  # Aggregation
        "Show employees in the Sales department.",        # Filtering
        "Show me user data.",                             # Ambiguous
        "Show me the intergalactic hyperdrive status."    # Irrelevant
    ]
    
    for q in test_queries:
        print(f"\n--- Benchmark Query: '{q}' ---")
        try:
            # We skip the DB dependencies here by mocking the retrieval output
            plan = await Phase4PlanningService.shadow_plan(
                user_query=q,
                kb_id=kb_id,
                canonical_schema=db_schema,
                old_retrieval_result=old_retrieval_result,
                new_evidence_context=new_evidence_context,
                schema_hash=schema_hash
            )
            print(f"Authoritative (Old) Plan Intent: {plan.intent.name}")
        except Exception as e:
            print(f"Benchmark failed for query '{q}': {e}")
            
    print("\nPhase 4 Benchmark Complete.")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
