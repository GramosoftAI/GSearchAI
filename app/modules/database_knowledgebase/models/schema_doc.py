"""Schema Documentation ("Cheat Sheet") ORM Models

Stores comprehensive schema documentation generated during Schema Sync:
- Status tracking: schema_doc_jobs (queued, mapping, explaining, embedding, done, failed)
- Table-level cheat sheets: schema_doc_tables (draft, approved, stale, failed)
- Column-level documentation: schema_doc_columns (facts, AI explanation, sensitive flag)
- Executable example queries: schema_doc_examples (question, verified SQL, status)
- Dedicated vector embeddings: schema_doc_embeddings (pgvector + tsvector)

Strictly scoped by tenant_id, db_knowledgebase_id, and schema_version.
"""

import uuid
from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    ForeignKey,
    Index,
    Boolean,
    Integer,
    UniqueConstraint,
    Computed,
    UUID as SQLAlchemyUUID,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from app.models.base import Base
from app.core.config import get_settings

settings = get_settings()


class SchemaDocJob(Base):
    """Tracks background schema documentation generation progress."""
    __tablename__ = "schema_doc_jobs"

    id = Column(SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    db_knowledgebase_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("database_knowledgebases.id", ondelete="CASCADE"), nullable=False, index=True)
    schema_version = Column(String(64), nullable=False, index=True)

    status = Column(String(50), nullable=False, default="queued")  # queued, mapping, explaining, embedding, done, failed
    progress_current = Column(Integer, nullable=False, default=0)
    progress_total = Column(Integer, nullable=False, default=0)
    current_step = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    table_errors = Column(JSONB, nullable=False, default=dict)
    tokens_used = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_schema_doc_job_tenant_kb_ver", "tenant_id", "db_knowledgebase_id", "schema_version"),
        {"extend_existing": True},
    )


class SchemaDocTable(Base):
    """Table-level cheat sheet documentation."""
    __tablename__ = "schema_doc_tables"

    id = Column(SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    db_knowledgebase_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("database_knowledgebases.id", ondelete="CASCADE"), nullable=False, index=True)
    schema_version = Column(String(64), nullable=False, index=True)

    table_schema = Column(String(100), nullable=False, default="public")
    table_name = Column(String(255), nullable=False)
    table_hash = Column(String(64), nullable=False, index=True)

    # Status: draft | approved | stale | failed
    status = Column(String(50), nullable=False, default="draft")

    # Facts & Relationships (Computed strictly by code/SQL, never LLM)
    facts_json = Column(JSONB, nullable=False, default=dict)
    relationships_json = Column(JSONB, nullable=False, default=dict)

    # AI Text
    ai_purpose = Column(Text, nullable=True)
    ai_synonyms = Column(JSONB, nullable=False, default=list)
    ai_caveats = Column(Text, nullable=True)
    ai_raw_explanation = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "db_knowledgebase_id", "schema_version", "table_schema", "table_name", name="uq_schema_doc_table"),
        Index("ix_schema_doc_tbl_tenant_kb_ver", "tenant_id", "db_knowledgebase_id", "schema_version"),
        Index("ix_schema_doc_tbl_status", "status"),
        {"extend_existing": True},
    )


class SchemaDocColumn(Base):
    """Column-level cheat sheet documentation."""
    __tablename__ = "schema_doc_columns"

    id = Column(SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    db_knowledgebase_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("database_knowledgebases.id", ondelete="CASCADE"), nullable=False, index=True)
    schema_version = Column(String(64), nullable=False, index=True)
    table_doc_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("schema_doc_tables.id", ondelete="CASCADE"), nullable=False, index=True)

    table_schema = Column(String(100), nullable=False, default="public")
    table_name = Column(String(255), nullable=False)
    column_name = Column(String(255), nullable=False)

    is_sensitive = Column(Boolean, nullable=False, default=False)
    data_type = Column(String(100), nullable=False)
    is_nullable = Column(Boolean, nullable=False, default=True)
    is_primary_key = Column(Boolean, nullable=False, default=False)
    is_foreign_key = Column(Boolean, nullable=False, default=False)

    # Statistical facts (null if is_sensitive=True)
    distinct_count = Column(Integer, nullable=True)
    null_percentage = Column(Integer, nullable=True)
    min_value = Column(String(255), nullable=True)
    max_value = Column(String(255), nullable=True)
    distinct_values = Column(JSONB, nullable=True)  # Low-cardinality text columns only

    # AI Text
    ai_meaning = Column(Text, nullable=True)
    ai_synonyms = Column(JSONB, nullable=False, default=list)
    ai_coded_values = Column(JSONB, nullable=True)  # e.g. {"A": "Active", "I": "Inactive"}

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "db_knowledgebase_id", "schema_version", "table_schema", "table_name", "column_name", name="uq_schema_doc_column"),
        Index("ix_schema_doc_col_tenant_kb_ver", "tenant_id", "db_knowledgebase_id", "schema_version"),
        {"extend_existing": True},
    )


class SchemaDocExample(Base):
    """Verified executable example questions and SQL for a table/schema."""
    __tablename__ = "schema_doc_examples"

    id = Column(SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    db_knowledgebase_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("database_knowledgebases.id", ondelete="CASCADE"), nullable=False, index=True)
    schema_version = Column(String(64), nullable=False, index=True)
    table_doc_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("schema_doc_tables.id", ondelete="CASCADE"), nullable=True, index=True)

    question = Column(Text, nullable=False)
    question_type = Column(String(50), nullable=False)  # short, vague, synonym, typo, multi_table
    sql_query = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default="verified")  # verified, rejected
    execution_row_count = Column(Integer, nullable=False, default=0)
    execution_time_ms = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_schema_doc_ex_tenant_kb_ver", "tenant_id", "db_knowledgebase_id", "schema_version"),
        {"extend_existing": True},
    )


class SchemaDocEmbedding(Base):
    """Dedicated vector embeddings + tsvector for schema documentation elements."""
    __tablename__ = "schema_doc_embeddings"

    id = Column(SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    db_knowledgebase_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("database_knowledgebases.id", ondelete="CASCADE"), nullable=False, index=True)
    schema_version = Column(String(64), nullable=False, index=True)

    item_type = Column(String(50), nullable=False, index=True)  # table_doc, column_doc, example_question
    item_key = Column(String(255), nullable=False, index=True)   # schema.table, schema.table.column, or example ID
    exact_identifier = Column(String(255), nullable=False)       # Exact schema.table or schema.table.column

    document_text = Column(Text, nullable=False)
    tsv_content = Column(TSVECTOR, Computed("to_tsvector('english', document_text)", persisted=True), nullable=True)
    embedding = Column(Vector(settings.embedding_dimension), nullable=False)
    metadata_json = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_schema_doc_emb_tenant_kb_ver", "tenant_id", "db_knowledgebase_id", "schema_version"),
        Index("ix_schema_doc_emb_type_key", "db_knowledgebase_id", "schema_version", "item_type"),
        Index("ix_schema_doc_emb_tsv", "tsv_content", postgresql_using="gin"),
        {"extend_existing": True},
    )
