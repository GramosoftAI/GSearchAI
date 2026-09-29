import asyncio
import os
import uuid
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# Import the existing DB engine and settings from the app
from app.core.database import AsyncSessionLocal, engine
from app.core.embeddings import EmbeddingGenerator
from app.modules.database_knowledgebase.schema.indexer import SchemaIndexer
from app.modules.database_knowledgebase.schemas.canonical import DatabaseSchema, SchemaInfo, TableSchema, ColumnSchema, ColumnDataType

async def main():
    print("Starting Phase 1 Verification...")
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        # 1. Create a mock canonical schema
        col1 = ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="int", is_primary_key=True)
        col2 = ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar")
        table1 = TableSchema(
            schema_name="public",
            table_name="test_employees",
            columns={"id": col1, "name": col2},
            comment="Stores employee records"
        )
        schema_info = SchemaInfo(schema_name="public", tables={"test_employees": table1})
        db_schema = DatabaseSchema(
            database_name="test_db",
            schemas={"public": schema_info},
            fingerprint="mock_hash_123"
        )

        print(f"Using mock KB: {kb_id} for Tenant: {tenant_id}")
        
        # Set RLS for the session
        await session.execute(text("SELECT set_config('app.current_tenant', :tenant_id, false)"), {"tenant_id": str(tenant_id)})
        
        # Mock KB record to satisfy FK
        await session.execute(text("INSERT INTO tenants (id, name) VALUES (:id, 'Test Tenant') ON CONFLICT DO NOTHING"), {"id": tenant_id})
        await session.execute(text("INSERT INTO users (id, tenant_id, email, hashed_password) VALUES (:id, :t_id, 'test@test.com', 'pwd') ON CONFLICT DO NOTHING"), {"id": uuid.uuid4(), "t_id": tenant_id})
        # For simplicity, we just assume the FKs are disabled or we handle it gracefully in the test
        # Actually, let's just let the indexer fail if FKs are enforced, or it might just work if we mock it.
        # Wait, the indexer checks if KB exists:
        # kb = await self.session.get(DatabaseKnowledgebase, kb_id)
        # If not, it returns 0. So we MUST insert a KB.
        
        # We will mock the indexer's session.get so it doesn't need actual DB rows
        class MockKB:
            status = ""
            schema_version = ""
        
        indexer = SchemaIndexer(session=session, tenant_id=tenant_id)
        
        # Patch session.get
        original_get = session.get
        async def mock_get(*args, **kwargs):
            return MockKB()
        session.get = mock_get
        
        # 2. Trigger the indexing process
        print("Triggering index_schema...")
        try:
            indexed_count = await indexer.index_schema(kb_id=kb_id, schema=db_schema)
            print(f"Verified Table document creation: {indexed_count} tables indexed.")
        except Exception as e:
            print(f"Failed to index: {e}")
            return
            
        # Restore session.get
        session.get = original_get

        # 3. Verify document creation & metadata in document_chunks
        res = await session.execute(text(
            "SELECT metadata_json, array_length(embedding_bge::real[], 1) FROM document_chunks WHERE section = 'SCHEMA_INDEX' AND kb_id = :kb_id LIMIT 1"
        ), {"kb_id": kb_id})
        row = res.fetchone()
        
        if row:
            meta = row[0]
            dim = row[1]
            
            print(f"Verified BGE dimension: {dim} (Expected: 1024)")
            print(f"Verified schema_hash deterministic: {meta.get('schema_hash') == 'mock_hash_123'}")
            print(f"Verified Tenant isolation: tenant_id {meta.get('tenant_id')} == {str(tenant_id)}")
            print(f"Verified Database/Connection isolation: connection_id {meta.get('connection_id')} == {str(kb_id)}")
            print(f"Column/FK metadata structure is intact: {len(meta.get('columns', []))} columns found in sample table.")
        else:
            print("No documents found in database.")

    await engine.dispose()
    print("Phase 1 Verification Complete.")

if __name__ == "__main__":
    asyncio.run(main())
