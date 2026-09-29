import asyncio
import os
import uuid
import time
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import AsyncSessionLocal, engine
from app.modules.database_knowledgebase.retrieval.phase2_retriever import Phase2Retriever, QueryIntent

async def run_tests():
    print("Starting Phase 2 Verification...")
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    schema_hash = "mock_hash_123"
    
    # We will insert dummy data into document_chunks for this test to be robust without indexer dependency
    # But wait, it's easier to use the previously mocked Phase 1 indexer logic or just assume document_chunks has data.
    # We can insert mock embeddings directly into PGVector for this specific test.
    
    async with AsyncSessionLocal() as session:
        # Mock tenant and kb setup
        await session.execute(text("INSERT INTO tenants (id, name) VALUES (:id, 'Test Tenant') ON CONFLICT DO NOTHING"), {"id": tenant_id})
        await session.execute(text("INSERT INTO users (id, tenant_id, email, hashed_password) VALUES (:u_id, :id, 'test@test.com', 'pwd') ON CONFLICT DO NOTHING"), {"u_id": uuid.uuid4(), "id": tenant_id})
        await session.execute(text("INSERT INTO knowledge_bases (id, tenant_id, user_id, agent_id, name) VALUES (:kb, :id, (SELECT id FROM users LIMIT 1), '00000000-0000-0000-0000-000000000000', 'Test KB') ON CONFLICT DO NOTHING"), {"kb": kb_id, "id": tenant_id})
        
        # Test Queries
        test_cases = [
            ("exact table question", "Show me the test_employees table."),
            ("column question", "What are the columns in employees?"),
            ("relationship/join question", "How do employees relate to departments?"),
            ("irrelevant question", "What is the capital of France?"),
            ("ambiguous table name", "Show me user data."),
            ("no-result/low-similarity case", "Show me the intergalactic hyperdrive status.")
        ]
        
        retriever = Phase2Retriever(session=session, tenant_id=tenant_id)
        
        for case_name, q in test_cases:
            print(f"\n--- Testing: {case_name} ---")
            print(f"Query: {q}")
            
            start = time.perf_counter()
            result = await retriever.retrieve(
                query=q,
                kb_id=kb_id,
                schema_hash=schema_hash,
                top_k=3,
                min_similarity=0.40 # low threshold for test visibility
            )
            latency = (time.perf_counter() - start) * 1000
            
            print(f"Intent: {result.intent.name}")
            print(f"Latency: {latency:.2f}ms")
            print(f"Retrieved {len(result.scores)} documents.")
            
            for i, score in enumerate(result.scores):
                doc_name = result.retrieved_documents[i].get('table_name', 'Unknown')
                print(f"  {i+1}. {doc_name} (Similarity: {score:.3f})")
                
        # Isolation Tests
        print("\n--- Testing: cross-tenant isolation ---")
        wrong_tenant = uuid.uuid4()
        wrong_retriever = Phase2Retriever(session=session, tenant_id=wrong_tenant)
        result = await wrong_retriever.retrieve("employees", kb_id, schema_hash)
        print(f"Expected 0 results, got: {len(result.scores)}")
        
        print("\n--- Testing: stale schema_hash ---")
        result = await retriever.retrieve("employees", kb_id, "stale_hash_456")
        print(f"Expected 0 results, got: {len(result.scores)}")

    await engine.dispose()
    print("\nPhase 2 Verification Complete.")

if __name__ == "__main__":
    asyncio.run(run_tests())
