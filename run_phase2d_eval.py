import asyncio
import uuid
import time
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

from app.core.config import get_settings
from app.modules.knowledge_bases.service import KnowledgeBaseService
from app.modules.knowledge_bases.models import KnowledgeBase, DocumentChunk
from app.core.pdf_extractor import PDFExtractor
from app.modules.rag.engines.vector_engine import VectorEngine
from app.modules.rag.schemas import RetrievalTask

async def main():
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    
    async with async_session() as db:
        res = await db.execute(text("SELECT tenant_id, id as agent_id FROM agents LIMIT 1"))
        row = res.fetchone()
        if not row:
            print("No agents found!")
            return
        tenant_id = str(row[0])
        agent_id = str(row[1])
        
        res = await db.execute(text(f"SELECT id FROM users WHERE tenant_id = '{tenant_id}' LIMIT 1"))
        row = res.fetchone()
        user_id = str(row[0]) if row else tenant_id
        
        kb_id = str(uuid.uuid4())
        settings.chunking_v2_kb_ids = kb_id
        files_to_ingest = [
            "tests/data/apple.pdf",
            "tests/data/ntsb.pdf",
            "tests/data/the-four-million-o-henry-1147.pdf"
        ]
        
        # Create KB
        kb = KnowledgeBase(id=uuid.UUID(kb_id), tenant_id=uuid.UUID(tenant_id), user_id=uuid.UUID(user_id), agent_id=uuid.UUID(agent_id), name="Test KB v2")
        db.add(kb)
        await db.commit()
        
        kb_service = KnowledgeBaseService(db=db, tenant_id=tenant_id)
        
        for file_path in files_to_ingest:
            if not Path(file_path).exists():
                print(f"Skipping {file_path} - not found.")
                continue
                
            print(f"Extracting {file_path}...")
            content = Path(file_path).read_bytes()
            try:
                document_text = await PDFExtractor.extract(
                    pdf_bytes=content,
                    filename=Path(file_path).name,
                    tenant_id=tenant_id
                )
                
                print(f"Ingesting {file_path} into KB {kb_id}...")
                await kb_service.ingest_document(
                    kb_id=kb_id,
                    document_text=document_text,
                    source=Path(file_path).name,
                    document_category="general_document"
                )
            except Exception as e:
                print(f"Failed to ingest {file_path}: {e}")
                
        await db.commit()
        
        # Check chunks
        res = await db.execute(text(f"SELECT COUNT(*), SUM(CASE WHEN length(text) > 2048 THEN 1 ELSE 0 END) FROM document_chunks WHERE kb_id = '{kb_id}'"))
        count, large_chunks = res.fetchone()
        print(f"Ingested {count} chunks. Chunks > 512 tokens (~2048 chars): {large_chunks}")
        
    print("Evaluating Retrieval...")
    import json
    with open('golden_set_v1.json', 'r') as f:
        questions = json.load(f)
        
    class MockNeo4jRepo:
        def __init__(self, tenant_id):
            self.tenant_id = tenant_id

    neo4j_repo = MockNeo4jRepo(tenant_id)
    vector_engine = VectorEngine(tenant_id=tenant_id, neo4j_repo=neo4j_repo, session_factory=async_session)
    
    total = 0
    recall_at_5 = 0
    mrr = 0.0
    
    for q in questions:
        expected = q.get('expected_source', '').lower()
        if not expected or expected not in ["apple.pdf", "ntsb pdfs", "the-four-million-o-henry-1147.pdf"]:
            continue # only evaluate what we ingested
            
        total += 1
        
        task = RetrievalTask(
            task_id="test",
            query=q['query'],
            target_section_ids=[],
            metadata_filters={}
        )
        chunks = await vector_engine.retrieve(task, kb_ids=[kb_id])
        
        found_rank = -1
        for r, chunk in enumerate(chunks[:5]):
            if expected.replace(" pdfs", ".pdf") in str(chunk.source).lower():
                found_rank = r + 1
                break
                
        if found_rank > 0:
            recall_at_5 += 1
            mrr += 1.0 / found_rank
            
    final_mrr = mrr / total if total > 0 else 0
    final_recall = (recall_at_5 / total) * 100 if total > 0 else 0
    
    print(f"\n--- EVALUATION RESULTS (V2) ---")
    print(f"Recall@5: {final_recall:.2f}%")
    print(f"MRR: {final_mrr:.4f}")

if __name__ == "__main__":
    asyncio.run(main())
