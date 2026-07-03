"""
Verification Script - End-to-End Excel/CSV Ontology-Based Ingestion & RAG Traversal Test

This script:
1. Dynamically discovers an active Tenant, User, and Agent.
2. Creates a fresh test Knowledge Base.
3. Seeds ontology classes, relationships, and allowed rules in Neo4j.
4. Generates two complex relational datasets in Excel/CSV format (HRMS & Logistics).
5. Triggers the ExcelIngestionService to parse the sheets, discover mappings,
   ground types against the active ontology, and ingest the rows.
6. Directly queries Neo4j to inspect the formed Entity nodes & typed relationships (REPORTS_TO, BELONGS_TO, IMPORTED_FROM).
7. Runs a Hybrid RAG query using the RAGPipeline and LLM to answer relational questions.
"""

import sys
import json
import asyncio
import os
import pandas as pd
import io
import uuid
from datetime import datetime
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.types import TypeDecorator, Text
from sqlalchemy.ext.asyncio import create_async_engine

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from app.core.config import get_settings
settings = get_settings()

class MockVector(TypeDecorator):
    impl = Text
    cache_ok = True

    def __init__(self, dim=None):
        super().__init__()
        self.dim = dim

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, list):
            return "[" + ",".join(map(str, value)) + "]"
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        cleaned = value.strip("[]")
        if not cleaned:
            return []
        return [float(x) for x in cleaned.split(",")]

# Auto-detect PostgreSQL system vector capability
async def check_vector_capability():
    temp_engine = create_async_engine(settings.database_url)
    has_vector = False
    try:
        async with temp_engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        has_vector = True
    except Exception:
        has_vector = False
    finally:
        await temp_engine.dispose()
    return has_vector

# Detect vector support synchronously before model imports
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

has_vector_extension = loop.run_until_complete(check_vector_capability())

if not has_vector_extension:
    print("[SETUP] System pgvector PostgreSQL extension is not available. Activating standard text fallback.")
    import pgvector.sqlalchemy
    pgvector.sqlalchemy.Vector = MockVector
else:
    print("[SETUP] System pgvector PostgreSQL extension is active. Using native vector storage.")

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.neo4j_repository import Neo4jRepository
from app.modules.knowledge_bases.models import KnowledgeBase
from app.modules.agents.models import Agent
from app.modules.tenants.models import Tenant
from app.modules.auth.models import User
from app.modules.knowledge_bases.services.excel_ingestion_service import ExcelIngestionService
from app.modules.rag.service import RAGService
from app.modules.ontology.service import OntologyService
from app.modules.ontology.schemas import OntologyClassCreate, OntologyRelationCreate, OntologyRuleCreate


async def setup_test_context(db):
    """Dynamically discover test user/agent and seed ontology schemas."""
    print("[SETUP] Ensuring all PostgreSQL database tables are created...")
    from app.models.base import Base
    from app.core.database import engine
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception:
        print("[SETUP] PostgreSQL system extension 'vector' is not available. Using monkeypatched standard text storage instead.")
        
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    print("[SETUP] Discovering active user and agent from database...")
    
    # 1. Discover a user to inherit tenant_id
    from sqlalchemy import select
    user_res = await db.execute(select(User).limit(1))
    user = user_res.scalar_one_or_none()
    if not user:
        raise RuntimeError("No user found in database. Please run seeds first.")
        
    user_id = str(user.id)
    tenant_id = str(user.tenant_id)
    
    # Set current session context for PostgreSQL RLS bypass
    await db.execute(text("SELECT set_config('app.current_tenant', :tenant_id, false)"), {"tenant_id": tenant_id})
    
    # 2. Discover or create Agent
    agent_res = await db.execute(select(Agent).where(Agent.tenant_id == user.tenant_id).limit(1))
    agent = agent_res.scalar_one_or_none()
    
    if not agent:
        agent = Agent(
            id=uuid.uuid4(),
            tenant_id=user.tenant_id,
            user_id=user.id,
            name="Enterprise Brain Agent",
            system_prompt="You are a brilliant multi-hop retrieval assistant. Always use the provided context to answer query.",
            is_active=True
        )
        db.add(agent)
        await db.flush()
        
    agent_id = str(agent.id)
    
    # 3. Create a fresh test Knowledge Base for our Excel upload
    kb_id = str(uuid.uuid4())
    kb = KnowledgeBase(
        id=uuid.UUID(kb_id),
        tenant_id=agent.tenant_id,
        user_id=user.id,
        agent_id=agent.id,
        name="Enterprise Spreadsheets KB",
        description="Structured HRMS and Cargo logs",
        source="user_upload",
        is_active=True
    )
    db.add(kb)
    
    # Merge Neo4j agent and KB node
    neo4j_repo = Neo4jRepository(tenant_id)
    await neo4j_repo.execute_write(
        """
        MERGE (a:Agent {id: $agent_id, tenant_id: $tenant_id})
        ON CREATE SET a.name = $agent_name
        MERGE (kb:KnowledgeBase {id: $kb_id, tenant_id: $tenant_id})
        ON CREATE SET kb.name = $kb_name
        MERGE (a)-[:OWNS_KB]->(kb)
        """,
        {
            "agent_id": agent_id,
            "agent_name": agent.name,
            "kb_id": kb_id,
            "kb_name": kb.name,
            "tenant_id": tenant_id
        }
    )

    # 4. Seed Ontology Schemas
    ont_service = OntologyService(tenant_id)
    
    # Create Classes
    classes = [
        ("EMPLOYEE", "Company employee member"),
        ("DEPARTMENT", "Corporate team department"),
        ("MANAGER", "Direct supervisor manager"),
        ("SHIPMENT", "Product logistics shipment record"),
        ("LOCATION", "Physical city or country name"),
        ("CARRIER", "Shipping cargo shipping provider")
    ]
    for name, desc in classes:
        try:
            await ont_service.create_class(OntologyClassCreate(name=name, description=desc))
        except Exception:
            pass

    # Create Relations
    relations = [
        ("BELONGS_TO", "Belongs to department"),
        ("REPORTS_TO", "Directly reports to supervisor"),
        ("IMPORTED_FROM", "Originates import country location"),
        ("SHIPPED_TO", "Shipping destination location"),
        ("CARRIED_BY", "Shipping logistics provider carrier")
    ]
    for name, desc in relations:
        try:
            await ont_service.create_relation(OntologyRelationCreate(name=name, description=desc))
        except Exception:
            pass

    # Create Allowed Rules
    rules = [
        ("EMPLOYEE", "BELONGS_TO", "DEPARTMENT"),
        ("EMPLOYEE", "REPORTS_TO", "MANAGER"),
        ("SHIPMENT", "IMPORTED_FROM", "LOCATION"),
        ("SHIPMENT", "SHIPPED_TO", "LOCATION"),
        ("SHIPMENT", "CARRIED_BY", "CARRIER")
    ]
    for src, rel, tgt in rules:
        try:
            await ont_service.create_rule(OntologyRuleCreate(
                source_class=src, relation=rel, target_class=tgt, description=f"{src} links via {rel} to {tgt}"
            ))
        except Exception:
            pass

    await db.commit()
    print(f"[SETUP] Seeding Complete. Tenant ID: {tenant_id}, Agent ID: {agent_id}, KB ID: {kb_id}")
    return tenant_id, agent_id, kb_id


def generate_mock_datasets() -> bytes:
    """Generate in-memory multi-sheet Excel mock spreadsheet (HRMS and Logistics)."""
    print("[DATA] Generating virtual Excel file containing structured relational datasets...")
    
    # 1. HRMS DataFrame
    hrms_data = {
        "Employee ID": ["EMP_Alice", "EMP_Bob", "EMP_Charlie"],
        "Employee Name": ["Alice Vance", "Bob Smith", "Charlie Brown"],
        "Department": ["Operations", "Operations", "Engineering"],
        "Manager": ["Sarah Jenkins", "Sarah Jenkins", "Sarah Jenkins"],
        "Salary Grade": ["Grade 8", "Grade 7", "Grade 9"]
    }
    df_hrms = pd.DataFrame(hrms_data)

    # 2. Cargo Import/Export DataFrame
    logistics_data = {
        "Shipment ID": ["SHIP_888", "SHIP_999"],
        "Product": ["Microchips", "Solar Panels"],
        "Origin Country": ["Taiwan", "Germany"],
        "Destination Country": ["USA", "Japan"],
        "Carrier": ["OceanCargo", "AirLogistics"]
    }
    df_logistics = pd.DataFrame(logistics_data)

    # Save to Excel buffer in memory
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_hrms.to_excel(writer, sheet_name="HRMS_Directory", index=False)
        df_logistics.to_excel(writer, sheet_name="Logistics_Tracker", index=False)

    buffer.seek(0)
    return buffer.read()


async def verify_ontology_graph(tenant_id: str):
    """Query Neo4j and inspect entities and relationships directly."""
    print("\n[GRAPH] INSPECTING NEO4J GRAPH FOR ONTOLOGY STRUCTURE...")
    neo4j_repo = Neo4jRepository(tenant_id)
    
    # Query for typed relationships created by ingestion service
    query = """
    MATCH (s:Entity)-[r]->(o:Entity)
    WHERE s.tenant_id = $tenant_id
    RETURN labels(s) as src_labels, s.text as source, type(r) as relation, o.text as target, labels(o) as tgt_labels
    LIMIT 20
    """
    results = await neo4j_repo.execute_read(query, {"tenant_id": tenant_id})
    
    if not results:
        print("[GRAPH] No relational ontology paths found in Neo4j!")
        return

    print(f"[GRAPH] FOUND {len(results)} STRUCTURED RELATIONSHIPS:")
    print("-" * 100)
    print(f"{'Source (Labels)':<35} {'-[Relationship]->':<20} {'Target (Labels)':<35}")
    print("-" * 100)
    for res in results:
        src_label_list = [l for l in res['src_labels'] if l != 'Entity']
        tgt_label_list = [l for l in res['tgt_labels'] if l != 'Entity']
        src = f"{res['source']} ({','.join(src_label_list)})"
        tgt = f"{res['target']} ({','.join(tgt_label_list)})"
        print(f"{src:<35} {f'-[:{res['relation']}]->':<20} {tgt:<35}")
    print("-" * 100)


async def run_hybrid_rag_queries(tenant_id: str, agent_id: str, kb_id: str):
    """Execute multi-hop RAG queries over the spreadsheet ontology graph."""
    print("\n[RAG] RUNNING HYBRID RAG QUERIES OVER EXCEL-DERIVED KNOWLEDGE...")
    
    async with AsyncSessionLocal() as db:
        rag_service = RAGService(db, tenant_id)
        
        queries = [
            "Who does Alice Vance report to and which department does she belong to?",
            "What is the origin country and carrier of shipment SHIP_888?",
            "Detail the overall directory structure: departments, managers, and employee salary grades from the sheet."
        ]
        
        for q in queries:
            print(f"\n[QUERY] Question: '{q}'")
            print("   Traversing ontology graph & retrieving row context...")
            
            # Fetch answer streamingly
            full_answer = []
            async for chunk in rag_service.stream_rag_answer(
                query=q,
                agent_id=agent_id,
                kb_id=kb_id,
                top_k=5,
                max_depth=2
            ):
                # Filter out metadata JSON structure in output stream
                try:
                    meta = json.loads(chunk)
                    if isinstance(meta, dict) and meta.get("type") == "metadata":
                        print("   [TRAVERSAL] Core Entities Mentioned in Traversal:")
                        for src in meta.get("sources", []):
                            print(f"      - Seed Chunk Reason: {src['reason']}")
                        continue
                except (ValueError, TypeError):
                    pass
                
                full_answer.append(chunk)

            answer = "".join(full_answer).strip()
            print("\n[ANSWER] GROUNDED RESPONSE:")
            print("-" * 80)
            print(answer)
            print("-" * 80)


async def main():
    print("="*100)
    print("STARTING END-TO-END EXCEL ONTOLOGY-INGESTION TEST")
    print("="*100)

    async with AsyncSessionLocal() as db:
        # 1. Setup Tenant and Ontologies
        tenant_id, agent_id, kb_id = await setup_test_context(db)

        # 2. Generate relational dataset
        file_bytes = generate_mock_datasets()

        # 3. Trigger Ingestion
        print("\n[INGEST] Launching ExcelIngestionService...")
        ingestor = ExcelIngestionService(db, tenant_id)
        ingest_result = await ingestor.ingest_file(
            kb_id=kb_id,
            file_bytes=file_bytes,
            filename="enterprise_assets.xlsx"
        )
        
        if not ingest_result.get("success"):
            print(f"[INGEST] INGESTION FAILED: {ingest_result.get('error')}")
            return
        
        data = ingest_result["data"]
        print(f"[INGEST] INGESTION SUCCESSFUL:")
        print(f"   - Row-level Chunks Ingested: {data['chunks_created']}")
        print(f"   - Ontological Entities Formed: {data['entities_created']}")
        print(f"   - Semantic Graph Relationships Created: {data['relationships_created']}")
        
        # Commit PG transaction
        await db.commit()

    # 4. Verify in Neo4j
    await verify_ontology_graph(tenant_id)

    # 5. Run RAG agent reasoning queries
    await run_hybrid_rag_queries(tenant_id, agent_id, kb_id)
    
    print("\nINTEGRATION VERIFICATION COMPLETE!")


if __name__ == "__main__":
    # Ensure event loop runs properly
    asyncio.run(main())
