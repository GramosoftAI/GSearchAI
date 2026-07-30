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
    
    # Dual Vectorization Arrays (768 dimensions)
    raw_vector = Column(VECTOR(768), nullable=True)
    summary_vector = Column(VECTOR(768), nullable=True)
    
    metadata_json = Column(JSONB, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

Index(
    "idx_memory_scoping_v2", 
    EpisodicMemory.tenant_id, 
    EpisodicMemory.user_id, 
    EpisodicMemory.session_id
)


class UserPreference(Base):
    """
    Dedicated store for user preferences/instructions ("remember that I
    prefer X", "always do Y", "my 10th grade mark is 70%"). Deliberately NOT
    routed through the episodic_memories pgvector pipeline or the entity-triplet
    extractor.

    This table is a direct, deterministic key-value lookup instead:
    always fetched in process-turn, never similarity-ranked, never
    entity-filtered.
    """
    __tablename__ = "user_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String(100), nullable=False, index=True)
    user_id = Column(String(100), nullable=False, index=True)
    agent_id = Column(String(100), nullable=False, index=True)  # Upgraded for agent scoping
    
    preference_key = Column(String(100), nullable=False)   # e.g. "tenth_grade_mark"
    preference_value = Column(String, nullable=False)       # e.g. "70%"
    raw_statement = Column(String, nullable=True)            # Original user statement for context
    updated_at = Column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

# Upgraded Composite Index scoped by Tenant + User + Agent + Key
Index(
    "idx_user_preferences_scoping_v2",
    UserPreference.tenant_id,
    UserPreference.user_id,
    UserPreference.agent_id,
    UserPreference.preference_key,
    unique=True,
)


async def init_db():
    async with engine.begin() as conn:
        # 1. Ensure pgvector extension is active in PostgreSQL
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        
        # 2. Create tables framework if missing
        await conn.run_sync(Base.metadata.create_all)
        
        # 3. Migration safety check for episodic_memories vectors
        await conn.execute(text("""
            ALTER TABLE episodic_memories 
            ADD COLUMN IF NOT EXISTS raw_vector vector(768);
        """))
        
        await conn.execute(text("""
            ALTER TABLE episodic_memories 
            ADD COLUMN IF NOT EXISTS summary_vector vector(768);
        """))

        # Dimension upgrade: This safely clears old vectors and changes type
        await conn.execute(text("""
            ALTER TABLE episodic_memories 
            ALTER COLUMN raw_vector TYPE vector(768) USING NULL;
        """))

        await conn.execute(text("""
            ALTER TABLE episodic_memories 
            ALTER COLUMN summary_vector TYPE vector(768) USING NULL;
        """))

        # 4. Migration safety check for user_preferences agent_id column
        await conn.execute(text("""
            ALTER TABLE user_preferences 
            ADD COLUMN IF NOT EXISTS agent_id VARCHAR(100) NOT NULL DEFAULT 'default_agent';
        """))
        
        # 5. Drop old index for scoping so the new idx_user_preferences_scoping_v2 takes precedence
        await conn.execute(text("""
            DROP INDEX IF EXISTS idx_user_preferences_scoping;
        """))
        
        # 6. If it was created as a constraint instead of an index, drop it too
        await conn.execute(text("""
            ALTER TABLE user_preferences DROP CONSTRAINT IF EXISTS idx_user_preferences_scoping;
        """))