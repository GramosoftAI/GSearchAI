"""Automatic Golden Query Corpus Generator

Generates 15 categories of database-specific golden test queries directly from
the discovered DatabaseKnowledgeProfile without hardcoded domain knowledge.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from ..planning.models import IntentType
from ..semantic.database_knowledge_profile import (
    ColumnSemanticRole,
    ColumnSemanticSubtype,
    DatabaseKnowledgeProfile,
    DiscoveredEntity,
    DiscoveredMetric,
    DiscoveredRelationship,
)


class GoldenQueryCategory(str, Enum):
    ENTITY_LISTING = "ENTITY_LISTING"
    ENTITY_COUNTING = "ENTITY_COUNTING"
    SCALAR_METRIC_SUM = "SCALAR_METRIC_SUM"
    SCALAR_METRIC_AVG = "SCALAR_METRIC_AVG"
    METRIC_RANKING_TOP = "METRIC_RANKING_TOP"
    METRIC_RANKING_BOTTOM = "METRIC_RANKING_BOTTOM"
    ENTITY_DETAIL_LOOKUP = "ENTITY_DETAIL_LOOKUP"
    CATEGORICAL_FILTER = "CATEGORICAL_FILTER"
    TEMPORAL_FILTER_YEAR = "TEMPORAL_FILTER_YEAR"
    RELATIVE_TEMPORAL_FILTER = "RELATIVE_TEMPORAL_FILTER"
    RELATIONAL_1HOP_JOIN = "RELATIONAL_1HOP_JOIN"
    RELATIONAL_AGGREGATION_GROUP_BY = "RELATIONAL_AGGREGATION_GROUP_BY"
    EXISTENCE_QUERY = "EXISTENCE_QUERY"
    MULTI_ENTITY_JOIN = "MULTI_ENTITY_JOIN"
    EXTREME_VALUE_LOOKUP = "EXTREME_VALUE_LOOKUP"


class GeneratedGoldenQuery(BaseModel):
    """A generated golden query benchmark item."""
    model_config = ConfigDict(extra="forbid")

    category: GoldenQueryCategory
    query_text: str
    expected_primary_table: str
    expected_intent: IntentType
    expected_join_tables: List[str] = Field(default_factory=list)
    expected_metrics: List[str] = Field(default_factory=list)
    description: str


class GoldenCorpusGenerator:
    """
    Generates a full evaluation corpus from a DatabaseKnowledgeProfile.
    Zero hardcoded domain assumptions.
    """

    @classmethod
    def generate_corpus(cls, profile: DatabaseKnowledgeProfile) -> List[GeneratedGoldenQuery]:
        """
        Generates up to 15 diverse query categories based on profile characteristics.
        """
        queries: List[GeneratedGoldenQuery] = []

        entities = list(profile.entities.values())
        if not entities:
            return queries

        primary_ent = entities[0]
        secondary_ent = entities[1] if len(entities) > 1 else None
        tertiary_ent = entities[2] if len(entities) > 2 else None

        # 1. Entity Listing
        queries.append(
            GeneratedGoldenQuery(
                category=GoldenQueryCategory.ENTITY_LISTING,
                query_text=f"Show all {primary_ent.semantic_name}s",
                expected_primary_table=primary_ent.physical_table,
                expected_intent=IntentType.SELECT_POINT,
                description=f"List records for primary entity {primary_ent.semantic_name}",
            )
        )

        # 2. Entity Counting
        queries.append(
            GeneratedGoldenQuery(
                category=GoldenQueryCategory.ENTITY_COUNTING,
                query_text=f"How many {primary_ent.semantic_name}s are there?",
                expected_primary_table=primary_ent.physical_table,
                expected_intent=IntentType.SELECT_AGGREGATE,
                description=f"Count total records for {primary_ent.semantic_name}",
            )
        )

        # Find available metrics
        metrics = list(profile.metrics.values())
        sum_metrics = [m for m in metrics if m.default_aggregation == "SUM"]
        avg_metrics = [m for m in metrics if m.default_aggregation == "AVG"]

        # 3. Scalar Metric SUM
        if sum_metrics:
            m = sum_metrics[0]
            clean_m = m.source_column.replace("_", " ")
            queries.append(
                GeneratedGoldenQuery(
                    category=GoldenQueryCategory.SCALAR_METRIC_SUM,
                    query_text=f"What is the total {clean_m} of {primary_ent.semantic_name}s?",
                    expected_primary_table=m.source_table,
                    expected_intent=IntentType.SELECT_AGGREGATE,
                    expected_metrics=[m.metric_id],
                    description=f"Aggregate SUM for {m.source_column}",
                )
            )

        # 4. Scalar Metric AVG
        if avg_metrics:
            m = avg_metrics[0]
            clean_m = m.source_column.replace("_", " ")
            queries.append(
                GeneratedGoldenQuery(
                    category=GoldenQueryCategory.SCALAR_METRIC_AVG,
                    query_text=f"What is the average {clean_m}?",
                    expected_primary_table=m.source_table,
                    expected_intent=IntentType.SELECT_AGGREGATE,
                    expected_metrics=[m.metric_id],
                    description=f"Aggregate AVG for {m.source_column}",
                )
            )

        # 5. Metric Ranking Top
        if sum_metrics:
            m = sum_metrics[0]
            clean_m = m.source_column.replace("_", " ")
            queries.append(
                GeneratedGoldenQuery(
                    category=GoldenQueryCategory.METRIC_RANKING_TOP,
                    query_text=f"Top 5 {primary_ent.semantic_name}s by {clean_m}",
                    expected_primary_table=primary_ent.physical_table,
                    expected_intent=IntentType.SELECT_RANKING,
                    description=f"Ranking top 5 by {clean_m}",
                )
            )

        # 6. Metric Ranking Bottom
        if sum_metrics:
            m = sum_metrics[0]
            clean_m = m.source_column.replace("_", " ")
            queries.append(
                GeneratedGoldenQuery(
                    category=GoldenQueryCategory.METRIC_RANKING_BOTTOM,
                    query_text=f"Lowest 5 {primary_ent.semantic_name}s by {clean_m}",
                    expected_primary_table=primary_ent.physical_table,
                    expected_intent=IntentType.SELECT_RANKING,
                    description=f"Ranking lowest 5 by {clean_m}",
                )
            )

        # 7. Entity Detail Lookup
        if primary_ent.identity_columns:
            queries.append(
                GeneratedGoldenQuery(
                    category=GoldenQueryCategory.ENTITY_DETAIL_LOOKUP,
                    query_text=f"Give me details of {primary_ent.semantic_name} sample_record",
                    expected_primary_table=primary_ent.physical_table,
                    expected_intent=IntentType.SELECT_POINT,
                    description=f"Parameterized literal entity lookup for {primary_ent.semantic_name}",
                )
            )

        # 8. Categorical Filter
        status_cols = [
            c for c in profile.columns.values()
            if c.table_name == primary_ent.physical_table and c.role == ColumnSemanticRole.STATUS
        ]
        if status_cols:
            sc = status_cols[0]
            queries.append(
                GeneratedGoldenQuery(
                    category=GoldenQueryCategory.CATEGORICAL_FILTER,
                    query_text=f"Show {primary_ent.semantic_name}s with status active",
                    expected_primary_table=primary_ent.physical_table,
                    expected_intent=IntentType.SELECT_FILTER_MULTI,
                    description=f"Filter {primary_ent.semantic_name} by {sc.column_name}",
                )
            )

        # 9. Temporal Filter Year
        date_cols = [
            c for c in profile.columns.values()
            if c.table_name == primary_ent.physical_table and c.role == ColumnSemanticRole.TEMPORAL
        ]
        if date_cols:
            queries.append(
                GeneratedGoldenQuery(
                    category=GoldenQueryCategory.TEMPORAL_FILTER_YEAR,
                    query_text=f"Show {primary_ent.semantic_name}s in 2024",
                    expected_primary_table=primary_ent.physical_table,
                    expected_intent=IntentType.SELECT_FILTER_MULTI,
                    description="Temporal year constraint filter",
                )
            )

        # 10. Relative Temporal Filter
        if date_cols:
            queries.append(
                GeneratedGoldenQuery(
                    category=GoldenQueryCategory.RELATIVE_TEMPORAL_FILTER,
                    query_text=f"Show {primary_ent.semantic_name}s from last month",
                    expected_primary_table=primary_ent.physical_table,
                    expected_intent=IntentType.SELECT_TIME_SERIES,
                    description="Relative temporal month constraint filter",
                )
            )

        # 11. Relational 1-Hop Join
        if profile.relationships and secondary_ent:
            rel = profile.relationships[0]
            queries.append(
                GeneratedGoldenQuery(
                    category=GoldenQueryCategory.RELATIONAL_1HOP_JOIN,
                    query_text=f"Show {primary_ent.semantic_name}s and their {secondary_ent.semantic_name}",
                    expected_primary_table=primary_ent.physical_table,
                    expected_intent=IntentType.SELECT_JOIN,
                    expected_join_tables=[secondary_ent.physical_table],
                    description="1-Hop FK relational join",
                )
            )

        # 12. Relational Aggregation Group By
        if sum_metrics and secondary_ent:
            m = sum_metrics[0]
            clean_m = m.source_column.replace("_", " ")
            queries.append(
                GeneratedGoldenQuery(
                    category=GoldenQueryCategory.RELATIONAL_AGGREGATION_GROUP_BY,
                    query_text=f"Total {clean_m} by {secondary_ent.semantic_name}",
                    expected_primary_table=primary_ent.physical_table,
                    expected_intent=IntentType.SELECT_AGGREGATE,
                    expected_join_tables=[secondary_ent.physical_table],
                    description=f"Group by aggregation across {secondary_ent.semantic_name}",
                )
            )

        # 13. Existence Query
        if secondary_ent:
            queries.append(
                GeneratedGoldenQuery(
                    category=GoldenQueryCategory.EXISTENCE_QUERY,
                    query_text=f"List {primary_ent.semantic_name}s with {secondary_ent.semantic_name}",
                    expected_primary_table=primary_ent.physical_table,
                    expected_intent=IntentType.SELECT_JOIN,
                    expected_join_tables=[secondary_ent.physical_table],
                    description="Existence / relational presence query",
                )
            )

        # 14. Multi-Entity Join
        if tertiary_ent and len(profile.relationships) >= 2:
            queries.append(
                GeneratedGoldenQuery(
                    category=GoldenQueryCategory.MULTI_ENTITY_JOIN,
                    query_text=f"Show {primary_ent.semantic_name}s with {secondary_ent.semantic_name} and {tertiary_ent.semantic_name}",
                    expected_primary_table=primary_ent.physical_table,
                    expected_intent=IntentType.SELECT_JOIN,
                    expected_join_tables=[secondary_ent.physical_table, tertiary_ent.physical_table],
                    description="Multi-hop 3-table join",
                )
            )

        # 15. Extreme Value Lookup
        if sum_metrics:
            m = sum_metrics[0]
            clean_m = m.source_column.replace("_", " ")
            queries.append(
                GeneratedGoldenQuery(
                    category=GoldenQueryCategory.EXTREME_VALUE_LOOKUP,
                    query_text=f"Who has the highest {clean_m}?",
                    expected_primary_table=primary_ent.physical_table,
                    expected_intent=IntentType.SELECT_RANKING,
                    description=f"Extreme max value lookup for {clean_m}",
                )
            )

        return queries

    _verified_feedback_cases: List["FeedbackVerifiedCase"] = []

    @classmethod
    def append_verified_feedback_case(
        cls,
        question: str,
        sql: str,
        mappings: Optional[Dict[str, Any]] = None,
        is_correction: bool = False,
        confidence_tier: str = "HUMAN_VERIFIED",
    ) -> "FeedbackVerifiedCase":
        """Appends a verified mapping/query pair to the regression corpus."""
        from datetime import datetime, timezone
        case = FeedbackVerifiedCase(
            question=question,
            sql=sql,
            mappings=mappings or {},
            is_correction=is_correction,
            confidence_tier=confidence_tier,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        cls._verified_feedback_cases.append(case)
        return case

    @classmethod
    def get_verified_feedback_cases(cls) -> List["FeedbackVerifiedCase"]:
        """Returns all recorded feedback cases."""
        return list(cls._verified_feedback_cases)


class FeedbackVerifiedCase(BaseModel):
    """A regression test case recorded from human or system verified feedback."""
    model_config = ConfigDict(extra="forbid")

    question: str
    sql: str
    mappings: Dict[str, Any] = Field(default_factory=dict)
    is_correction: bool = False
    confidence_tier: str = "HUMAN_VERIFIED"
    recorded_at: str = ""
