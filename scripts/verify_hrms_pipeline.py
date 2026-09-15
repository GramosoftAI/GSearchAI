"""End-to-End HRMS Demo Database Verification Script

Validates that the complete database knowledgebase pipeline (Retrieval -> Planning ->
AST Security -> Execution -> Grounded Answer Synthesis -> Observability Trace)
functions seamlessly on the 14-table HRMS database.
"""

import asyncio
import logging
import uuid
import sys

from app.core.database import AsyncSessionLocal
from app.modules.database_knowledgebase.services.service import DatabaseKnowledgebaseService
from app.modules.database_knowledgebase.schemas.connection import DatabaseConnectionConfig
from app.modules.database_knowledgebase.schemas.api import DatabaseKnowledgebaseCreate

TEST_TENANT_ID = "d113ef9e-bcb5-4626-af1d-6c995bbfe4d0"
TEST_USER_ID = uuid.UUID("12690c36-22d1-4aa5-92dd-a17c8d1a3ca0")

HRMS_QUERIES = [
    # 1. Simple lookup
    "Show all employees in the Engineering department.",
    # 2. Filtering
    "Which employees have a salary greater than $150,000?",
    # 3. Aggregation
    "What is the average salary by department?",
    # 4. Ranking
    "Who are the top 5 highest-paid employees?",
    # 5. Join Traversal
    "Show each employee's department and job title.",
    # 6. Multi-hop relationship
    "Which employees are assigned to the project 'Project Titan - NextGen Core'?",
    # 7. Performance reviews
    "Which employees received a performance rating of 5?",
    # 8. Negative / Empty result
    "Which employees have a salary less than $20,000?",
]


async def run_hrms_verification():
    async with AsyncSessionLocal() as session:
        service = DatabaseKnowledgebaseService(db=session, tenant_id=TEST_TENANT_ID)

        # 1. Register or find existing HRMS Demo KB
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
        logger = logging.getLogger(__name__)
        
        existing_kbs = await service.list_database_knowledgebases(limit=10)
        hrms_kb = next((k for k in existing_kbs if "HRMS" in k.name), None)
        
        if not hrms_kb:
            logger.info("Registering HRMS Demo Database in catalog...")
            kb_payload = DatabaseKnowledgebaseCreate(
                name="HRMS Demo Enterprise Database",
                description="14-table HRMS demo database for manual evaluation",
                connection=DatabaseConnectionConfig(
                    db_type="postgresql",
                    host="localhost",
                    port=5433,
                    database_name="gsearch_hrms_demo_db",
                    username="test_ro_user",
                    password="test_ro_password",
                    ssl_mode="disable",
                ),
            )
            kb = await service.create_database_knowledgebase(user_id=TEST_USER_ID, data=kb_payload)
            logger.info(f"Registered KB ID: {kb.id}, status: {kb.status}")

            # 2. Introspect & Snapshot Schema
            logger.info(f"Introspecting HRMS schema for KB '{kb.id}'...")
            schema_res = await service.introspect_and_snapshot_schema(kb_id=kb.id)
            logger.info(
                f"Schema snapshot saved! Version: {schema_res.schema_version[:16]}..., "
                f"Tables: {schema_res.schema_data.summary.get('table_count')}, "
                f"Columns: {schema_res.schema_data.summary.get('column_count')}, "
                f"Relationships: {schema_res.schema_data.summary.get('relationship_count')}"
            )
            target_kb_id = kb.id
        else:
            logger.info(f"Found existing HRMS Demo KB '{hrms_kb.name}' (ID: {hrms_kb.id}, status: {hrms_kb.status})")
            target_kb_id = hrms_kb.id

        # 3. Execute sample queries with pipeline tracing
        logger.info("\n================= EXECUTING HRMS PIPELINE QUERIES =================")
        success_count = 0
        for idx, q in enumerate(HRMS_QUERIES, 1):
            logger.info(f"\n[HRMS-Q{idx:02d}] Query: {q}")
            try:
                answer = await service.query_database(
                    kb_id=target_kb_id,
                    user_query=q,
                    use_llm=True,
                )
                logger.info(f"Answer Type:     {answer.answer_type}")
                logger.info(f"Grounding:       {answer.grounding_status}")
                logger.info(f"Verification:    {answer.verification_status}")
                logger.info(f"Rows Returned:   {answer.row_count}")
                logger.info(f"Answer Text:     {answer.answer_text[:200]}...")

                # Inspect Phase 3A Telemetry
                trace = answer.pipeline_trace
                if trace:
                    logger.info(f"Trace ID:        {trace.query_id}")
                    logger.info(f"Total Latency:   {trace.total_latency_ms} ms")
                    logger.info(f"Retrieved Tables:{trace.retrieval.retrieved_tables}")
                    logger.info(f"Planned Intent:  {trace.planning.intent}")
                    logger.info(f"Candidate SQL:   {trace.sql_generation.candidate_sql}")
                    logger.info(f"AST Valid:       {trace.sql_generation.ast_valid}")
                    logger.info(f"Execution ms:    {trace.execution.execution_time_ms} ms")

                success_count += 1
            except Exception as e:
                logger.error(f"[HRMS-Q{idx:02d}] FAILED with error: {e}", exc_info=True)

        logger.info(f"\n==================================================================")
        logger.info(f"HRMS Queries Completed: {success_count}/{len(HRMS_QUERIES)} PASSED")
        logger.info(f"==================================================================")


if __name__ == "__main__":
    asyncio.run(run_hrms_verification())
