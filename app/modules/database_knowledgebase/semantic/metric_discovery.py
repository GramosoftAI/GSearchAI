"""Universal Metric Discovery

Automatically discovers and formulates aggregatable business metrics from
database numeric columns and primary keys without hardcoded domain lists.
Converts discovered numeric measures into Canonical MetricDefinitions.
"""

from typing import Dict, List, Optional, Set, Tuple
import uuid

from .database_knowledge_profile import (
    ColumnSemanticProfile,
    ColumnSemanticRole,
    ColumnSemanticSubtype,
    DiscoveredEntity,
    DiscoveredMetric,
)
from .models import MetricDefinition, MetricType


class UniversalMetricDiscovery:
    """
    Discovers canonical business metrics from numeric and key columns.
    Enforces that all discovered metrics use approved aggregations (COUNT, SUM, AVG, MIN, MAX).
    """

    @classmethod
    def discover_metrics(
        cls,
        entities: Dict[str, DiscoveredEntity],
        columns: Dict[str, ColumnSemanticProfile],
    ) -> Dict[str, DiscoveredMetric]:
        """
        Discovers metrics across all non-system tables.
        Returns a mapping of metric_id -> DiscoveredMetric.
        """
        discovered: Dict[str, DiscoveredMetric] = {}

        # 1. Entity count metrics (e.g., total_employees, count_patients, total_invoices)
        for ent_id, ent in entities.items():
            pk_col = ent.primary_key_columns[0] if ent.primary_key_columns else "id"
            metric_id = f"count_{ent.semantic_name.lower()}s"
            disp_name = f"Total {ent.display_name}s"

            expr = f'COUNT("{pk_col}")'
            synonyms = [
                f"total {ent.semantic_name.lower()}s",
                f"number of {ent.semantic_name.lower()}s",
                f"count of {ent.semantic_name.lower()}s",
                f"how many {ent.semantic_name.lower()}s",
            ]
            for syn in ent.synonyms:
                synonyms.append(f"total {syn}")
                synonyms.append(f"number of {syn}")

            m = DiscoveredMetric(
                metric_id=metric_id,
                name=metric_id,
                display_name=disp_name,
                source_schema=ent.physical_schema,
                source_table=ent.physical_table,
                source_column=pk_col,
                metric_subtype=ColumnSemanticSubtype.COUNTABLE,
                default_aggregation="COUNT",
                expression=expr,
                unit="count",
                synonyms=sorted(list(set(synonyms))),
                confidence=0.95,
                evidence=[f"Auto-generated count metric for entity {ent.semantic_name}"],
            )
            discovered[metric_id] = m

        # 2. Measures from numeric columns (e.g., salary, amount, price, fee, balance)
        for col_key, c_prof in columns.items():
            if c_prof.is_primary_key or c_prof.is_foreign_key or c_prof.is_sensitive:
                continue

            if c_prof.role == ColumnSemanticRole.NUMERIC and c_prof.subtype in (
                ColumnSemanticSubtype.CURRENCY,
                ColumnSemanticSubtype.AMOUNT,
                ColumnSemanticSubtype.QUANTITY,
                ColumnSemanticSubtype.PERCENTAGE,
                ColumnSemanticSubtype.SCORE,
            ):
                c_clean = c_prof.column_name.replace("_", " ")
                t_clean = c_prof.table_name.replace("_", " ")

                # Standard unit
                unit = "USD" if c_prof.subtype == ColumnSemanticSubtype.CURRENCY else None

                # SUM metric
                sum_id = f"total_{c_prof.table_name}_{c_prof.column_name}".lower()
                sum_disp = f"Total {c_clean.title()}"
                sum_synonyms = [
                    f"total {c_clean}",
                    f"sum of {c_clean}",
                    f"total {c_prof.column_name}",
                    c_clean,
                ]
                discovered[sum_id] = DiscoveredMetric(
                    metric_id=sum_id,
                    name=sum_id,
                    display_name=sum_disp,
                    source_schema=c_prof.schema_name,
                    source_table=c_prof.table_name,
                    source_column=c_prof.column_name,
                    metric_subtype=c_prof.subtype,
                    default_aggregation="SUM",
                    expression=f'SUM("{c_prof.column_name}")',
                    unit=unit,
                    synonyms=sorted(list(set(sum_synonyms))),
                    confidence=c_prof.confidence,
                    evidence=[f"Aggregatable measure discovered from {col_key} ({c_prof.subtype.value})"],
                )

                # AVG metric
                avg_id = f"avg_{c_prof.table_name}_{c_prof.column_name}".lower()
                avg_disp = f"Average {c_clean.title()}"
                avg_synonyms = [
                    f"average {c_clean}",
                    f"mean {c_clean}",
                    f"avg {c_clean}",
                ]
                discovered[avg_id] = DiscoveredMetric(
                    metric_id=avg_id,
                    name=avg_id,
                    display_name=avg_disp,
                    source_schema=c_prof.schema_name,
                    source_table=c_prof.table_name,
                    source_column=c_prof.column_name,
                    metric_subtype=c_prof.subtype,
                    default_aggregation="AVG",
                    expression=f'AVG("{c_prof.column_name}")',
                    unit=unit,
                    synonyms=sorted(list(set(avg_synonyms))),
                    confidence=c_prof.confidence,
                    evidence=[f"Aggregatable measure discovered from {col_key} ({c_prof.subtype.value})"],
                )

        return discovered

    @classmethod
    def to_metric_definitions(
        cls,
        discovered_metrics: Dict[str, DiscoveredMetric],
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
        entities: Dict[str, DiscoveredEntity],
        schema_version: Optional[str] = None,
    ) -> List[MetricDefinition]:
        """
        Converts discovered metrics into Phase 6 MetricDefinition models for
        CanonicalMetricRegistry.
        """
        # Map physical table to entity semantic name
        tbl_to_ent_name: Dict[str, str] = {}
        for ent in entities.values():
            tbl_to_ent_name[ent.physical_table.lower()] = ent.semantic_name

        agg_map = {
            "SUM": MetricType.SUM,
            "AVG": MetricType.AVG,
            "COUNT": MetricType.COUNT,
            "MIN": MetricType.MIN,
            "MAX": MetricType.MAX,
        }

        definitions: List[MetricDefinition] = []
        for m in discovered_metrics.values():
            ent_name = tbl_to_ent_name.get(m.source_table.lower(), m.source_table)
            agg_type = agg_map.get(m.default_aggregation, MetricType.SUM)

            defn = MetricDefinition(
                metric_id=m.metric_id,
                name=m.name,
                display_name=m.display_name,
                description=f"Authoritative metric: {m.display_name} on {ent_name}.{m.source_column}",
                expression=m.expression,
                aggregation=agg_type,
                source_entity=ent_name,
                source_column=m.source_column,
                synonyms=m.synonyms,
                unit=m.unit,
                tenant_id=tenant_id,
                knowledgebase_id=knowledgebase_id,
                schema_version=schema_version,
            )
            definitions.append(defn)

        return definitions
