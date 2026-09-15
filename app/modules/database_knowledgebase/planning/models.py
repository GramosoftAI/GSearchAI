"""Query Plan Intermediate Representation (IR) Models

Strongly typed Pydantic V2 models representing structured, machine-validatable query plans.
Strictly configured with extra="forbid" for security-sensitive planning.
"""

import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class IntentType(str, Enum):
    """Semantic intent classification of the user query."""
    SELECT_POINT = "SELECT_POINT"
    SELECT_JOIN = "SELECT_JOIN"
    SELECT_AGGREGATE = "SELECT_AGGREGATE"
    SELECT_RANKING = "SELECT_RANKING"
    SELECT_COMPARISON = "SELECT_COMPARISON"
    SELECT_FILTER_MULTI = "SELECT_FILTER_MULTI"
    SELECT_TIME_SERIES = "SELECT_TIME_SERIES"


class AggregateFunction(str, Enum):
    """Supported SQL aggregation functions."""
    NONE = "NONE"
    COUNT = "COUNT"
    COUNT_DISTINCT = "COUNT_DISTINCT"
    SUM = "SUM"
    AVG = "AVG"
    MIN = "MIN"
    MAX = "MAX"


class JoinType(str, Enum):
    """Relational join types."""
    INNER = "INNER"
    LEFT = "LEFT"


class OrderDirection(str, Enum):
    """Sorting directions."""
    ASC = "ASC"
    DESC = "DESC"


class TablePlan(BaseModel):
    """Table node in the query plan."""
    model_config = ConfigDict(extra="forbid")

    schema_name: str = Field(default="public", description="Schema namespace")
    table_name: str = Field(..., min_length=1, description="Table name")
    alias: str = Field(..., min_length=1, description="Unique table alias in the plan (e.g. 'c', 'o')")
    role: str = Field(default="PRIMARY", description="Role in query: PRIMARY, JOIN_TARGET, BRIDGE")


class ColumnProjectionPlan(BaseModel):
    """Column projection in the SELECT clause."""
    model_config = ConfigDict(extra="forbid")

    table_alias: str = Field(..., min_length=1, description="Alias of the parent table")
    column_name: str = Field(..., min_length=1, description="Column name in the schema")
    output_alias: Optional[str] = Field(default=None, description="Optional SQL AS alias")
    aggregation: AggregateFunction = Field(default=AggregateFunction.NONE, description="Applied aggregation")


class JoinPlan(BaseModel):
    """Relational join edge between two tables."""
    model_config = ConfigDict(extra="forbid")

    source_table_alias: str = Field(..., min_length=1, description="Alias of left table")
    source_column: str = Field(..., min_length=1, description="Join column on left table")
    target_table_alias: str = Field(..., min_length=1, description="Alias of right table")
    target_column: str = Field(..., min_length=1, description="Join column on right table")
    join_type: JoinType = Field(default=JoinType.INNER, description="INNER or LEFT join")
    relationship_name: Optional[str] = Field(default=None, description="Optional name of backing foreign key")


class PredicatePlan(BaseModel):
    """WHERE clause filtering predicate."""
    model_config = ConfigDict(extra="forbid")

    table_alias: str = Field(..., min_length=1, description="Alias of table containing column")
    column_name: str = Field(..., min_length=1, description="Filtered column name")
    operator: str = Field(..., description="Operator: =, !=, >, <, >=, <=, LIKE, ILIKE, IN, BETWEEN, IS NULL, IS NOT NULL")
    value: Any = Field(default=None, description="Literal filter value or parameter")
    logical_operator: str = Field(default="AND", description="AND or OR connecting this predicate")


class OrderByPlan(BaseModel):
    """ORDER BY clause item."""
    model_config = ConfigDict(extra="forbid")

    expression: str = Field(..., min_length=1, description="Column or alias or aggregate expression")
    direction: OrderDirection = Field(default=OrderDirection.ASC, description="ASC or DESC")


class QueryPlanIR(BaseModel):
    """
    Complete Query Plan Intermediate Representation (IR).
    
    Machine-validatable, strongly typed, and decoupled from raw SQL strings.
    """
    model_config = ConfigDict(extra="forbid")

    database_knowledgebase_id: uuid.UUID = Field(..., description="Target database knowledgebase ID")
    schema_version: str = Field(..., min_length=1, description="Pinned SHA-256 schema fingerprint")
    user_query: str = Field(..., min_length=1, description="Original natural-language user query")
    intent: IntentType = Field(..., description="Classified query intent")
    tables: List[TablePlan] = Field(..., min_length=1, description="List of tables in the query")
    projections: List[ColumnProjectionPlan] = Field(default_factory=list, description="Projected SELECT items")
    joins: List[JoinPlan] = Field(default_factory=list, description="Approved relational joins")
    predicates: List[PredicatePlan] = Field(default_factory=list, description="Filtering conditions")
    group_by: List[str] = Field(default_factory=list, description="GROUP BY column aliases or expressions")
    order_by: List[OrderByPlan] = Field(default_factory=list, description="ORDER BY sorting items")
    limit: Optional[int] = Field(default=None, ge=1, le=1000, description="Safety row limit")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Planner confidence score")
    reasoning: str = Field(default="", description="Planner explanation of approach")
