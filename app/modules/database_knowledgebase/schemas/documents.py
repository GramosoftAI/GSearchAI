"""Schema Semantic Document Models for Phase 2A

Represents 5 distinct document tiers for semantic schema indexing and retrieval:
1. DatabaseDocument
2. SchemaDocument
3. TableDocument
4. ColumnDocument
5. RelationshipDocument

CRITICAL DESIGN PRINCIPLE:
Every document strictly separates:
- TECHNICAL FACTS (deterministically derived from Phase 1 database catalog)
- BUSINESS / SEMANTIC INFORMATION (database comments & descriptions - never fabricated)
"""

from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ConfigDict

from .canonical import ColumnDataType, RelationshipType


class SchemaDocumentType(str, Enum):
    DATABASE = "database"
    SCHEMA = "schema"
    TABLE = "table"
    COLUMN = "column"
    RELATIONSHIP = "relationship"


class BaseSchemaDocument(BaseModel):
    """Base schema document model."""
    model_config = ConfigDict(extra="forbid")

    document_type: SchemaDocumentType
    entity_key: str = Field(..., description="Unique deterministic identifier for the schema entity")
    embedding_text: str = Field(..., description="Compact, dense text representation used for vector embedding")


# ==============================================================================
# 1. DATABASE DOCUMENT
# ==============================================================================
class DatabaseTechnicalFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database_name: str
    database_type: str
    schema_names: List[str]
    table_count: int
    relationship_count: int


class DatabaseBusinessSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: Optional[str] = None
    comment: Optional[str] = None


class DatabaseDocument(BaseSchemaDocument):
    document_type: SchemaDocumentType = SchemaDocumentType.DATABASE
    technical_facts: DatabaseTechnicalFacts
    business_semantics: DatabaseBusinessSemantics = Field(default_factory=DatabaseBusinessSemantics)


# ==============================================================================
# 2. SCHEMA DOCUMENT
# ==============================================================================
class SchemaTechnicalFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_name: str
    tables: List[str]
    table_count: int


class SchemaBusinessSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: Optional[str] = None
    comment: Optional[str] = None


class SchemaDocument(BaseSchemaDocument):
    document_type: SchemaDocumentType = SchemaDocumentType.SCHEMA
    technical_facts: SchemaTechnicalFacts
    business_semantics: SchemaBusinessSemantics = Field(default_factory=SchemaBusinessSemantics)


# ==============================================================================
# 3. TABLE DOCUMENT
# ==============================================================================
class TableTechnicalFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_name: str
    table_name: str
    table_type: str = "TABLE"
    primary_key_columns: List[str] = Field(default_factory=list)
    foreign_key_references: List[str] = Field(default_factory=list)  # e.g., ["customer_id -> public.customers.id"]
    column_names: List[str] = Field(default_factory=list)
    indexed_columns: List[str] = Field(default_factory=list)


class TableBusinessSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comment: Optional[str] = None
    synonyms: List[str] = Field(default_factory=list)


class TableDocument(BaseSchemaDocument):
    document_type: SchemaDocumentType = SchemaDocumentType.TABLE
    technical_facts: TableTechnicalFacts
    business_semantics: TableBusinessSemantics = Field(default_factory=TableBusinessSemantics)


# ==============================================================================
# 4. COLUMN DOCUMENT
# ==============================================================================
class ColumnTechnicalFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_name: str
    table_name: str
    column_name: str
    data_type: ColumnDataType
    raw_data_type: str
    is_primary_key: bool = False
    is_foreign_key: bool = False
    is_nullable: bool = True
    foreign_key_target: Optional[str] = None  # e.g. "public.customers.id"


class ColumnBusinessSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comment: Optional[str] = None
    synonyms: List[str] = Field(default_factory=list)


class ColumnDocument(BaseSchemaDocument):
    document_type: SchemaDocumentType = SchemaDocumentType.COLUMN
    technical_facts: ColumnTechnicalFacts
    business_semantics: ColumnBusinessSemantics = Field(default_factory=ColumnBusinessSemantics)


# ==============================================================================
# 5. RELATIONSHIP DOCUMENT
# ==============================================================================
class RelationshipTechnicalFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relationship_type: RelationshipType
    source_schema: str
    source_table: str
    source_columns: List[str]
    target_schema: str
    target_table: str
    target_columns: List[str]
    foreign_key_name: Optional[str] = None


class RelationshipBusinessSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: Optional[str] = None


class RelationshipDocument(BaseSchemaDocument):
    document_type: SchemaDocumentType = SchemaDocumentType.RELATIONSHIP
    technical_facts: RelationshipTechnicalFacts
    business_semantics: RelationshipBusinessSemantics = Field(default_factory=RelationshipBusinessSemantics)
