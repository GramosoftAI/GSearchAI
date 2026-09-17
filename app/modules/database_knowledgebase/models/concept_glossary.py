"""Concept Glossary & Schema Workspace ORM Models

Enables semantic glossary enrichment, canonicality tagging,
multi-tenancy, and domain workspace partitioning.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from app.models.base import Base
from app.core.config import get_settings

settings = get_settings()


class ConceptGlossary(Base):
    """
    Semantic concept glossary entry mapping table/column to business description,
    synonyms, semantic roles, and canonicality status.
    """
    __tablename__ = "concept_glossary"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    table_name = Column(String(255), nullable=False)
    column_name = Column(String(255), nullable=False)
    business_description = Column(Text, nullable=False)
    synonyms = Column(ARRAY(String), nullable=False, server_default="{}")
    semantic_role = Column(String(100), nullable=False)
    is_canonical = Column(Boolean, nullable=False, default=True)
    is_published = Column(Boolean, nullable=False, default=False)
    confidence_source = Column(String(50), nullable=False)  # 'LLM_GENERATED' or 'HUMAN_VERIFIED'
    schema_fingerprint = Column(String(64), nullable=False, index=True)
    embedding = Column(Vector(settings.embedding_dimension), nullable=True)
    orphaned_by_drift = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "table_name", "column_name", "schema_fingerprint", name="uq_concept_glossary_item"),
        Index("idx_concept_glossary_role", "tenant_id", "semantic_role", postgresql_where=(is_canonical == True)),
        Index("idx_concept_glossary_synonyms", "synonyms", postgresql_using="gin"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return (
            f"<ConceptGlossary id={self.id} tenant_id='{self.tenant_id}' "
            f"table='{self.table_name}' col='{self.column_name}' role='{self.semantic_role}' "
            f"canonical={self.is_canonical} source='{self.confidence_source}'>"
        )


class SchemaWorkspace(Base):
    """
    Domain workspace mapping partitioning database tables around hub entities.
    """
    __tablename__ = "schema_workspace"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    workspace_name = Column(String(100), nullable=False)  # e.g. "attendance", "payroll"
    table_name = Column(String(255), nullable=False)
    schema_fingerprint = Column(String(64), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "table_name", "schema_fingerprint", name="uq_schema_workspace_item"),
        Index("ix_schema_workspace_tenant_ws", "tenant_id", "workspace_name"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return (
            f"<SchemaWorkspace id={self.id} tenant_id='{self.tenant_id}' "
            f"workspace='{self.workspace_name}' table='{self.table_name}'>"
        )
