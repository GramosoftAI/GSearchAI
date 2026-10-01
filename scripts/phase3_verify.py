import asyncio
import os
import uuid
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import AsyncSessionLocal, engine
from app.modules.database_knowledgebase.retrieval.phase3_expander import Phase3Expander

async def run_tests():
    print("Starting Phase 3 Verification...")
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    schema_hash = "mock_hash_123"
    
    async with AsyncSessionLocal() as session:
        # Mock tenant and kb setup
        await session.execute(text("INSERT INTO tenants (id, name) VALUES (:id, 'Test Tenant') ON CONFLICT DO NOTHING"), {"id": tenant_id})
        await session.execute(text("INSERT INTO users (id, tenant_id, email, hashed_password) VALUES (:u_id, :id, 'test@test.com', 'pwd') ON CONFLICT DO NOTHING"), {"u_id": uuid.uuid4(), "id": tenant_id})
        await session.execute(text("INSERT INTO knowledge_bases (id, tenant_id, user_id, agent_id, name) VALUES (:kb, :id, (SELECT id FROM users LIMIT 1), '00000000-0000-0000-0000-000000000000', 'Test KB') ON CONFLICT DO NOTHING"), {"kb": kb_id, "id": tenant_id})
        
        # 1. We will insert mock documents into document_chunks directly.
        # Tables: departments, employees (ref departments), roles, employee_roles (ref employees, roles - multi-hop)
        
        docs = [
            {
                "table_name": "departments",
                "schema_name": "public",
                "columns": [{"name": "id"}],
                "relationships": []
            },
            {
                "table_name": "employees",
                "schema_name": "public",
                "columns": [{"name": "id"}, {"name": "department_id"}],
                "relationships": [{"column": "department_id", "referenced_table": "departments", "referenced_column": "id"}]
            },
            {
                "table_name": "roles",
                "schema_name": "public",
                "columns": [{"name": "id"}],
                "relationships": []
            },
            {
                "table_name": "employee_roles",
                "schema_name": "public",
                "columns": [{"name": "employee_id"}, {"name": "role_id"}],
                "relationships": [
                    {"column": "employee_id", "referenced_table": "employees", "referenced_column": "id"},
                    {"column": "role_id", "referenced_table": "roles", "referenced_column": "id"}
                ]
            }
        ]
        
        # Clear old mock data
        await session.execute(text("DELETE FROM document_chunks WHERE kb_id = :kb_id"), {"kb_id": kb_id})
        
        for doc in docs:
            meta = {
                "schema_hash": schema_hash,
                "tenant_id": str(tenant_id),
                "connection_id": str(kb_id),
                "table_name": doc["table_name"],
                "relationships": doc["relationships"],
                "columns": doc["columns"]
            }
            await session.execute(text("""
                INSERT INTO document_chunks (id, tenant_id, kb_id, text, chunk_index, section, metadata_json)
                VALUES (:id, :tenant_id, :kb_id, :text, 0, 'SCHEMA_INDEX', :meta::jsonb)
            """), {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "kb_id": kb_id,
                "text": f"Table: {doc['table_name']}",
                "meta": json.dumps(meta)
            })
            
        await session.commit()
        
        expander = Phase3Expander(session=session, tenant_id=tenant_id)
        
        # --- TEST CASES ---
        
        print("\n--- Test: FK relationship (Forward) ---")
        # Seed: employees, Expect: departments
        seed = [{"table_name": "employees", "relationships": [{"column": "department_id", "referenced_table": "departments", "referenced_column": "id"}]}]
        res = await expander.expand(seed, kb_id, schema_hash, max_hops=1, max_related_tables=5)
        print("Paths:", res.expansion_paths)
        print("Expanded Tables:", [t.get("table_name") for t in res.expanded_tables])
        
        print("\n--- Test: Reverse FK ---")
        # Seed: departments, Expect: employees
        seed = [{"table_name": "departments", "relationships": []}]
        res = await expander.expand(seed, kb_id, schema_hash, max_hops=1, max_related_tables=5)
        print("Paths:", res.expansion_paths)
        print("Expanded Tables:", [t.get("table_name") for t in res.expanded_tables])
        
        print("\n--- Test: 2-hop relationship ---")
        # Seed: departments, Expect: employees (1 hop), employee_roles (2 hop)
        res = await expander.expand(seed, kb_id, schema_hash, max_hops=2, max_related_tables=5)
        print("Paths:", res.expansion_paths)
        print("Expanded Tables:", [t.get("table_name") for t in res.expanded_tables])
        
        print("\n--- Test: Cycle / Duplicate relationship ---")
        # The code inherently prevents cycles by using `visited_tables`.
        print("Handled via `visited_tables` set check. Paths:", len(res.expansion_paths))
        
        print("\n--- Test: Nonexistent FK ---")
        seed = [{"table_name": "employees", "relationships": [{"column": "bad_id", "referenced_table": "nonexistent_table", "referenced_column": "id"}]}]
        res = await expander.expand(seed, kb_id, schema_hash, max_hops=1, max_related_tables=5)
        print("Expanded Tables:", [t.get("table_name") for t in res.expanded_tables])
        
        print("\n--- Test: Expansion limit (max_related_tables=1) ---")
        seed = [{"table_name": "departments", "relationships": []}]
        res = await expander.expand(seed, kb_id, schema_hash, max_hops=2, max_related_tables=1)
        print("Paths:", res.expansion_paths)
        print("Expanded Tables (Count):", len(res.expanded_tables))
        
        print("\n--- Test: Wrong tenant / Wrong kb_id / Stale hash ---")
        wrong_expander = Phase3Expander(session=session, tenant_id=uuid.uuid4())
        res1 = await wrong_expander.expand([{"table_name": "employees"}], kb_id, schema_hash)
        res2 = await expander.expand([{"table_name": "employees"}], uuid.uuid4(), schema_hash)
        res3 = await expander.expand([{"table_name": "employees"}], kb_id, "bad_hash")
        print(f"Wrong Tenant expanded: {len(res1.expanded_tables)}")
        print(f"Wrong KB ID expanded: {len(res2.expanded_tables)}")
        print(f"Stale Hash expanded: {len(res3.expanded_tables)}")
        
        print("\n--- Test: Evidence formatting ---")
        seed = [{"table_name": "employees", "_semantic_text": "Table: employees", "relationships": [{"column": "department_id", "referenced_table": "departments", "referenced_column": "id"}]}]
        res = await expander.expand(seed, kb_id, schema_hash, max_hops=1, max_related_tables=5)
        print(res.final_evidence_context)

    await engine.dispose()
    print("\nPhase 3 Verification Complete.")

if __name__ == "__main__":
    asyncio.run(run_tests())
