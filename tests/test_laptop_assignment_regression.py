import asyncio
import sys
import os
import datetime

sys.path.insert(0, os.path.abspath("."))

from app.core.database import AsyncSessionLocal
from app.modules.database_knowledgebase.models.database_knowledgebase import DatabaseKnowledgebase, DatabaseSchemaSnapshot
from app.modules.database_knowledgebase.schemas.canonical import DatabaseSchema
from app.modules.database_knowledgebase.disambiguation.collision_detector import CollisionDetector
from app.modules.database_knowledgebase.planning.planner import QueryPlanner
from app.modules.database_knowledgebase.retrieval.retriever import SchemaRetrievalResult
from app.modules.database_knowledgebase.sql_generator.generator import CandidateSQLGenerator
from app.modules.database_knowledgebase.security.secrets import get_secret_manager
from app.modules.database_knowledgebase.execution.connection_helper import connect_to_database
from sqlalchemy import select

async def test_regression_which_laptop_assigned_to_arun():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(DatabaseKnowledgebase).order_by(DatabaseKnowledgebase.created_at.desc()).limit(1))
        kb = res.scalar_one_or_none()
        assert kb is not None, "KB not found"
        
        snap = await db.execute(select(DatabaseSchemaSnapshot).where(DatabaseSchemaSnapshot.db_knowledgebase_id == kb.id).order_by(DatabaseSchemaSnapshot.created_at.desc()).limit(1))
        s = snap.scalar_one_or_none()
        assert s is not None, "Schema snapshot not found"
        canonical_schema = DatabaseSchema(**s.schema_data)
        
        query = "which laptop assign to arun"
        secrets = get_secret_manager()
        
        # 1. Test Disambiguation resolves employee_employee with IDs
        res_user = await CollisionDetector.check_for_user_collisions("arun", kb, secrets, canonical_schema)
        assert res_user is not None, "Collision detector returned None for 'arun'"
        assert res_user["table"] == "employee_employee", f"Expected employee_employee, got {res_user['table']}"
        assert set(res_user["ids"]) == {88, 110}, f"Expected IDs [88, 110], got {res_user['ids']}"
        
        resolved_entities = [{
            "type": "user",
            "id": res_user["ids"],
            "name": "arun",
            "table": res_user["table"],
            "pk_column": res_user["pk_column"],
        }]
        
        # 2. Test Planner binds disambiguated IDs and hardware category
        retrieval_res = SchemaRetrievalResult(
            database_name=canonical_schema.database_name,
            database_type="postgresql",
            schema_version=s.schema_version,
            retrieved_tables=[],
            selected_relationships=[],
            table_scores={},
            token_count=0,
            retrieval_scores={},
            join_paths=[],
            overall_confidence=1.0,
            untrusted_boundary_text="",
        )
        
        plan = QueryPlanner.plan(
            user_query=query,
            database_knowledgebase_id=kb.id,
            canonical_schema=canonical_schema,
            retrieval_result=retrieval_res,
            resolved_entities=resolved_entities,
        )
        
        table_names = [t.table_name for t in plan.tables]
        assert "asset_asset" in table_names
        assert "asset_assetassignment" in table_names
        assert "employee_employee" in table_names
        assert "asset_assetcategory" in table_names
        
        # 3. Test Join direction uses assigned_to_employee_id_id
        join_cols = [f"{j.source_column}->{j.target_column}" for j in plan.joins]
        assert any("assigned_to_employee_id_id" in jc for jc in join_cols), f"assigned_to join missing in {join_cols}"
        
        # 4. Test SQL compilation handles IN list with integers
        sql = CandidateSQLGenerator.compile_plan_to_sql(plan)
        assert "IN (88, 110)" in sql, f"Expected 'IN (88, 110)' in SQL, got: {sql}"
        assert "asset_category_name" in sql, f"Expected asset_category_name in SQL, got: {sql}"
        
        # 5. Test Live DB Execution returns Arun N's laptop
        config = secrets.decrypt_credentials(kb.encrypted_credentials)
        conn = await connect_to_database(config, timeout_seconds=5.0, read_only=True)
        rows = await conn.fetch(sql)
        await conn.close()
        
        assert len(rows) > 0, f"Expected >0 rows from database, got {len(rows)}"
        row_dict = dict(rows[0])
        assert "HP EliteBook 840 G7 Notebook PC" in row_dict.get("asset_name", ""), f"Unexpected asset: {row_dict}"
        assert row_dict.get("employee_first_name") == "Arun"
        print("SUCCESS: Regression test passed! Found laptop:", row_dict["asset_name"], "assigned to:", row_dict["employee_first_name"], row_dict["employee_last_name"])

if __name__ == "__main__":
    asyncio.run(test_regression_which_laptop_assigned_to_arun())
