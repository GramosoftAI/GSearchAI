"""Knowledge Base model - stored in PostgreSQL with graph nodes in Neo4j"""

from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Text,
    Integer,
    Float,
    JSON,
    UUID as SQLAlchemyUUID,
)
from sqlalchemy.sql import func
from datetime import datetime
import uuid

# Use the shared Base from models package
from ...models.base import Base


class KnowledgeBase(Base):
    """
    Knowledge Base model - stores documents for AI agents.

    CRITICAL:
    - Each KB belongs to one tenant
    - Each KB is owned by one agent
    - KB also represented as (:KnowledgeBase) node in Neo4j
    - Contains documents that are chunked and embedded
    - Deletion cascades to Neo4j (soft-delete via service layer)

    Properties:
    - id: Unique UUID per KB
    - tenant_id: Multi-tenancy scoping (RLS filtered)
    - user_id: User who created KB (for audit)
    - agent_id: Agent this KB belongs to
    - name: Human-readable KB name
    - description: Optional KB description
    - source: Source type (e.g., "user_upload", "api", "database")
    - total_chunks: Metadata - how many chunks in this KB
    - is_active: For soft-deletion
    - deleted_at: Soft delete timestamp
    """

    __tablename__ = "knowledge_bases"

    # ============= PRIMARY KEY =============
    id = Column(
        SQLAlchemyUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    # ============= MULTI-TENANCY =============
    tenant_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ============= OWNERSHIP =============
    user_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ============= AGENT RELATIONSHIP =============
    agent_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ============= KB METADATA =============
    name = Column(String(255), nullable=False)
    description = Column(String(1000), nullable=True)
    source = Column(
        String(50),
        nullable=False,
        default="user_upload",
    )  # user_upload, api, database, etc.

    from sqlalchemy.dialects.postgresql import JSONB
    dataset_schema = Column(JSONB, nullable=True)

    # ============= CONTENT TRACKING =============
    total_chunks = Column(
        Integer,
        nullable=False,
        default=0,
    )  # Number of chunks in this KB (metadata)

    # ============= STATUS =============
    is_active = Column(Boolean, default=True, nullable=False)

    # ============= SOFT DELETE TRACKING =============
    deleted_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    s3_path = Column(String(1024), nullable=True)
    parsed_path = Column(String(1024), nullable=True)



    # ============= AUDIT TRACKING =============
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ============= INDEXES =============
    __table_args__ = (
        # RLS enforcement
        Index("ix_kbs_tenant_id", "tenant_id"),
        # Find by owner
        Index("ix_kbs_user_id", "user_id"),
        # Find KBs by agent
        Index("ix_kbs_agent_id", "agent_id"),
        # Composite: tenant + agent (list KBs for specific agent)
        Index("ix_kbs_tenant_agent", "tenant_id", "agent_id"),
        # Soft-delete filtering
        Index("ix_kbs_is_active", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<KnowledgeBase id={self.id} name={self.name} agent_id={self.agent_id} chunks={self.total_chunks}>"


class DatabaseConnection(Base):
    """
    Natively represents a structured database connection source 
    associated with a parent KnowledgeBase of type 'database'.
    
    CRITICAL:
    - Enforces RLS isolation through tenant_id scope.
    - Linked 1:1 with a parent KnowledgeBase node.
    """
    __tablename__ = "kb_database_connections"

    # ============= PRIMARY KEY =============
    id = Column(
        SQLAlchemyUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    # ============= MULTI-TENANCY =============
    tenant_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ============= KNOWLEDGE BASE RELATIONSHIP =============
    kb_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # ============= DATABASE DETAILS =============
    db_type = Column(String(50), nullable=False)  # 'sqlite' or 'postgresql'
    
    # Store credentials or filepath dynamically in encrypted/raw format
    connection_params = Column(JSON, nullable=False)

    # ============= TEMPORAL TRACKING =============
    last_synced_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_db_conns_tenant_id", "tenant_id"),
        Index("ix_db_conns_kb_id", "kb_id"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return f"<DatabaseConnection id={self.id} type={self.db_type} kb_id={self.kb_id}>"


class DocumentChunk(Base):
    """
    Document Chunk model - stores text chunks and their embeddings in PostgreSQL using pgvector.
    Provides hybrid search capabilities (dense vector search in PG + relationship search in Neo4j).
    """

    __tablename__ = "document_chunks"

    id = Column(
        SQLAlchemyUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )
    
    tenant_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    kb_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )

    text = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    
    # Store the vector. Dimension is 1024 as per EMBEDDING_DIMENSION in .env
    from pgvector.sqlalchemy import Vector
    embedding = Column(Vector(1024), nullable=True)

    from sqlalchemy.dialects.postgresql import JSONB
    metadata_json = Column(JSONB, nullable=True)


    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_chunks_tenant_id", "tenant_id"),
        Index("ix_chunks_kb_id", "kb_id"),
        # We can add an hnsw or ivfflat index later for performance
    )
    
    def __repr__(self) -> str:
        return f"<DocumentChunk id={self.id} kb_id={self.kb_id} index={self.chunk_index}>"


class DocumentTableRow(Base):
    """
    Structured Table Row model - stores extracted tabular data as JSONB in PostgreSQL.
    Provides a SQL engine target for data analytics routing (e.g. "Find products below 5000")
    instead of relying on vector semantic search.
    """

    __tablename__ = "document_table_rows"

    id = Column(
        SQLAlchemyUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )
    
    tenant_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    kb_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )

    page_number = Column(Integer, nullable=False, default=1)
    table_index = Column(Integer, nullable=False, default=0)
    row_index = Column(Integer, nullable=False, default=0)
    
    # Typed columns for deterministic SQL generation and indexing
    from sqlalchemy import Numeric
    part_number = Column(String(255), nullable=True, index=True)
    product_name = Column(String(1000), nullable=True, index=True)
    mrp = Column(Numeric(10, 2), nullable=True, index=True)
    gst = Column(Numeric(5, 2), nullable=True)
    hsn_code = Column(String(100), nullable=True)
    extraction_confidence = Column(Numeric(4, 3), nullable=True, default=0.99)
    
    # Store the row's key-value pairs (Header -> Value) dynamically as a fallback
    from sqlalchemy.dialects.postgresql import JSONB
    row_data = Column(JSONB, nullable=False)

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_tablerows_tenant_id", "tenant_id"),
        Index("ix_tablerows_kb_id", "kb_id"),
        Index("ix_tablerows_page_idx", "page_number"),
        Index("ix_tablerows_row_data_gin", "row_data", postgresql_using="gin"),
    )
    
    def __repr__(self) -> str:
        return f"<DocumentTableRow id={self.id} kb_id={self.kb_id} table={self.table_index} row={self.row_index}>"


class AnalyticsQueryLog(Base):
    """
    Audit trail for deterministic Table Analytics queries.
    Stores the extracted intent, generated SQL, and performance metrics for transparency and debugging.
    """
    __tablename__ = "analytics_query_log"

    id = Column(
        SQLAlchemyUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )
    
    tenant_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    kb_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )

    query_text = Column(Text, nullable=False)
    intent_json = Column(JSON, nullable=False)
    generated_sql = Column(Text, nullable=False)
    rows_returned = Column(Integer, nullable=False, default=0)
    execution_time_ms = Column(Integer, nullable=False, default=0)

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_analyticslog_tenant_id", "tenant_id"),
        Index("ix_analyticslog_kb_id", "kb_id"),
    )
    
    def __repr__(self) -> str:
        return f"<AnalyticsQueryLog id={self.id} kb_id={self.kb_id} rows={self.rows_returned}>"

class DocumentEntity(Base):
    """
    Structured Entity Storage Layer.
    Stores structured business entities during ingestion for precise, extractive queries.
    """
    __tablename__ = "document_entities"

    id = Column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True, nullable=False
    )
    tenant_id = Column(
        SQLAlchemyUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_id = Column(
        SQLAlchemyUUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    
    entity_type = Column(String(50), nullable=False, index=True) # e.g. GSTIN, PAN
    entity_value = Column(String(500), nullable=False)
    page_number = Column(Integer, nullable=True)
    section_name = Column(String(255), nullable=True)
    
    from sqlalchemy import Numeric
    confidence = Column(Numeric(4, 3), nullable=True, default=1.0)
    
    start_offset = Column(Integer, nullable=True)
    end_offset = Column(Integer, nullable=True)
    source_text = Column(Text, nullable=True)
    entity_status = Column(String(50), nullable=False, default="VERIFIED")

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_doc_entities_tenant_id", "tenant_id"),
        Index("ix_doc_entities_doc_id", "document_id"),
        Index("ix_doc_entities_type", "entity_type"),
    )

    def __repr__(self) -> str:
        return f"<DocumentEntity type={self.entity_type} value={self.entity_value}>"


class DocumentSection(Base):
    """
    Structured Section Storage.
    Stores complete extracted sections (e.g. Place of Delivery, Billing Address).
    """
    __tablename__ = "document_sections"

    id = Column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True, nullable=False
    )
    tenant_id = Column(
        SQLAlchemyUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_id = Column(
        SQLAlchemyUUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    
    section_name = Column(String(255), nullable=False, index=True)
    
    from sqlalchemy.dialects.postgresql import JSONB
    section_json = Column(JSONB, nullable=False)
    page_number = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_doc_sections_tenant_id", "tenant_id"),
        Index("ix_doc_sections_doc_id", "document_id"),
        Index("ix_doc_sections_name", "section_name"),
    )

    def __repr__(self) -> str:
        return f"<DocumentSection name={self.section_name}>"


class DocumentIngestionRun(Base):
    """
    Ingestion Audit Trail table.
    Tracks the complete lifecycle of a document ingestion job, providing 
    historical evidence for pipeline behavior, anomalies, and scaling patterns.
    """
    __tablename__ = "document_ingestion_runs"

    id = Column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True, nullable=False
    )
    tenant_id = Column(
        SQLAlchemyUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_id = Column(
        SQLAlchemyUUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    
    # Timing
    started_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Extraction metrics
    chunk_count = Column(Integer, nullable=False, default=0)
    entity_count = Column(Integer, nullable=False, default=0)
    triplet_count = Column(Integer, nullable=False, default=0)
    identifier_count = Column(Integer, nullable=False, default=0)
    
    # Version Tracking
    extractor_version = Column(String(50), nullable=True, default="unified_extractor_v1")
    schema_version = Column(String(50), nullable=True, default="1.0")
    model_name = Column(String(100), nullable=True, default="deepseek-v3")
    
    # Resilience tracking
    repair_count = Column(Integer, nullable=False, default=0)
    retry_count = Column(Integer, nullable=False, default=0)
    fallback_count = Column(Integer, nullable=False, default=0)
    llm_calls = Column(Integer, nullable=False, default=0)
    llm_input_tokens = Column(Integer, nullable=False, default=0)
    llm_output_tokens = Column(Integer, nullable=False, default=0)
    
    # Advanced Telemetry
    extraction_duration_ms = Column(Integer, nullable=False, default=0)
    graph_write_duration_ms = Column(Integer, nullable=False, default=0)
    total_duration_ms = Column(Integer, nullable=False, default=0)
    nodes_created = Column(Integer, nullable=False, default=0)
    relationships_created = Column(Integer, nullable=False, default=0)
    nodes_merged = Column(Integer, nullable=False, default=0)
    relationships_merged = Column(Integer, nullable=False, default=0)
    
    document_category = Column(String(100), nullable=False, default="general_document", index=True)
    sample_entities = Column(JSON, nullable=True)
    sample_triplets = Column(JSON, nullable=True)
    
    # Drift Detection Context
    baseline_entities_per_chunk = Column(Float, nullable=True)
    current_entities_per_chunk = Column(Float, nullable=True)
    deviation_percent = Column(Float, nullable=True)
    baseline_documents = Column(Integer, nullable=True)
    
    fallback_chunks = Column(JSON, nullable=True)
    
    status = Column(String(50), nullable=False, default="IN_PROGRESS") # COMPLETED, FAILED
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_ingestion_runs_tenant_id", "tenant_id"),
        Index("ix_ingestion_runs_doc_id", "document_id"),
        Index("ix_ingestion_runs_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<DocumentIngestionRun id={self.id} doc={self.document_id} status={self.status}>"
