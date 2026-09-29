import re

with open('scripts/performance_and_correctness_benchmark.py', 'r') as f:
    code = f.read()

pg_setup = """
    # =========================================================================
    # 2. GROUND-TRUTH POSTGRESQL DATABASE EXECUTION SETUP
    # =========================================================================
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    from app.modules.knowledge_bases.models import DocumentChunk
    from app.modules.models.database_knowledgebase import DatabaseKnowledgebase, DatabaseSchemaSnapshot
    from app.core.embeddings import EmbeddingGenerator

    pg_url = "postgresql+asyncpg://postgres:postgres@localhost:5433/gsearch"
    engine = create_async_engine(pg_url)
    async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session_maker() as session:
        # Create schema and tables
        await session.execute(text("DROP SCHEMA IF EXISTS phase6_benchmark CASCADE;"))
        await session.execute(text("CREATE SCHEMA phase6_benchmark;"))
        
        await session.execute(text("CREATE TABLE phase6_benchmark.employees (id INT, department_id INT, job_id INT, manager_id INT, name TEXT, salary NUMERIC); "))
        await session.execute(text("CREATE TABLE phase6_benchmark.departments (id INT, name TEXT, office_id INT);"))
        await session.execute(text("CREATE TABLE phase6_benchmark.projects (id INT, name TEXT, budget NUMERIC);"))
        await session.execute(text("CREATE TABLE phase6_benchmark.employee_projects (employee_id INT, project_id INT, assigned_date TEXT);"))
        await session.execute(text("CREATE TABLE phase6_benchmark.suppliers (id INT, name TEXT);"))
        await session.execute(text("CREATE TABLE phase6_benchmark.benefits (id INT, name TEXT);"))
        await session.execute(text("CREATE TABLE phase6_benchmark.jobs (id INT, name TEXT);"))
        
        await session.execute(text("INSERT INTO phase6_benchmark.employees VALUES (1, 10, 100, NULL, 'Girinath', 120000), (2, 10, 101, 1, 'Alice', 95000), (3, 20, 102, 1, 'Bob', 110000), (4, 20, 102, 3, 'Charlie', 80000);"))
        await session.execute(text("INSERT INTO phase6_benchmark.departments VALUES (10, 'Sales', 1), (20, 'Engineering', 1);"))
        await session.execute(text("INSERT INTO phase6_benchmark.projects VALUES (501, 'Apollo', 500000), (502, 'Zeus', 750000);"))
        await session.execute(text("INSERT INTO phase6_benchmark.employee_projects VALUES (1, 501, '2026-01-01'), (2, 501, '2026-01-15'), (3, 502, '2026-02-01');"))
        await session.execute(text("INSERT INTO phase6_benchmark.jobs VALUES (100, 'Engineer'), (101, 'Manager'), (102, 'Analyst');"))
        
        # Setup KB and Chunks
        await session.execute(text("DELETE FROM knowledge_bases WHERE id = :kid"), {'kid': kb_id})
        await session.execute(text("DELETE FROM document_chunks WHERE kb_id = :kid"), {'kid': kb_id})
        await session.execute(text("DELETE FROM database_schema_snapshots WHERE db_knowledgebase_id = :kid"), {'kid': kb_id})
        
        kb = DatabaseKnowledgebase(id=kb_id, tenant_id=tenant_id, agent_id=uuid.uuid4(), user_id=uuid.uuid4(), name="Phase6Benchmark")
        session.add(kb)
        
        # Insert Schema Snapshot
        snap = DatabaseSchemaSnapshot(
            tenant_id=tenant_id,
            db_knowledgebase_id=kb_id,
            schema_version=schema_hash,
            schema_data=canonical_schema.model_dump(mode='json')
        )
        session.add(snap)
        
        # Add chunks with embeddings
        idx = 0
        for t_name, t_obj in tables_dict.items():
            col_strs = [f"{c.name} ({c.data_type.value.upper()})" for c in t_obj.columns.values()]
            text_content = f"Table {t_name} with columns: {', '.join(col_strs)}"
            embedding = await EmbeddingGenerator.generate_embedding(text_content)
            if embedding:
                chunk = DocumentChunk(
                    tenant_id=tenant_id,
                    kb_id=kb_id,
                    text=text_content,
                    chunk_index=idx,
                    embedding_bge=embedding,
                    section="SCHEMA_INDEX"
                )
                session.add(chunk)
                idx += 1
            
        await session.commit()
    
    async def pg_exec(sql: str) -> List[Dict[str, Any]]:
        clean_sql = sql.replace("public.", "phase6_benchmark.").replace("PUBLIC.", "phase6_benchmark.")
        async with async_session_maker() as session:
            try:
                res = await session.execute(text(clean_sql))
                rows = res.fetchall()
                cols = list(res.keys())
                return [dict(zip(cols, row)) for row in rows]
            except Exception as e:
                # If it's a DDL or non-returning statement, fetchall will fail
                return []
"""

code = re.sub(
    r'# 2\. GROUND-TRUTH DATABASE EXECUTION SETUP.*?# 3\. 50-QUERY BENCHMARK CORPUS', 
    pg_setup + '\n    # =========================================================================\n    # 3. 50-QUERY BENCHMARK CORPUS', 
    code, flags=re.DOTALL
)

code = code.replace('sqlite_exec', 'pg_exec')
code = code.replace('use_llm=False,', 'use_llm=True,\n            db_session=session,')
code = code.replace('res = await Phase5ShadowPipelineService.run_shadow_pipeline(', 'async with async_session_maker() as session:\n            res = await Phase5ShadowPipelineService.run_shadow_pipeline(')
code = code.replace('def run_phase5b_benchmark', 'def run_phase6_shadow')
code = code.replace('run_phase5b_benchmark()', 'run_phase6_shadow()')

with open('scripts/phase6_e2e_shadow.py', 'w') as f:
    f.write(code)

print("Done generating phase6_e2e_shadow.py")
