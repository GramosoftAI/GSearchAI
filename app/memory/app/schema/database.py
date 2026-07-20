import os
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Index, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from pgvector.sqlalchemy import VECTOR

DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql+asyncpg://graphmind:graphmind_password@db:5432/graphmind"
)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
Base = declarative_base()

class EpisodicMemory(Base):
    __tablename__ = "episodic_memories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(100), nullable=False, index=True)
    session_id = Column(String(100), nullable=False, index=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    agent_id = Column(String(100), nullable=False, index=True)
    
    user_query = Column(String, nullable=False)
    ai_response = Column(String, nullable=True)
    summarization = Column(String, nullable=True)
    
    # Dual Vectorization Arrays (BGE-M3 Native: 1024 dimensions)
    raw_vector = Column(VECTOR(1024), nullable=True)
    summary_vector = Column(VECTOR(1024), nullable=True)
    
    metadata_json = Column(JSONB, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

Index(
    "idx_memory_scoping_v2", 
    EpisodicMemory.tenant_id, 
    EpisodicMemory.user_id, 
    EpisodicMemory.session_id
)

async def init_db():
    async with engine.begin() as conn:
        # 1. Ensure pgvector extension is active in the database
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        
        # 2. Let SQLAlchemy create the table framework if it's completely missing
        await conn.run_sync(Base.metadata.create_all)
        
        # 3. Add raw_vector column safely with 1024 dimensions if it doesn't exist
        await conn.execute(text("""
            ALTER TABLE episodic_memories 
            ADD COLUMN IF NOT EXISTS raw_vector vector(1024);
        """))
        
        # 4. Add summary_vector column safely with 1024 dimensions if it doesn't exist
        await conn.execute(text("""
            ALTER TABLE episodic_memories 
            ADD COLUMN IF NOT EXISTS summary_vector vector(1024);
        """))