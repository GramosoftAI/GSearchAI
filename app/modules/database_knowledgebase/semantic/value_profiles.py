"""Universal Value Profiles

Provides bounded, safe value profiling for categorical, status, and low-cardinality
columns across any client database.
Strictly prohibits profiling of passwords, credentials, tokens, secrets, or sensitive PII.
"""

from typing import Any, Dict, List, Optional, Set
import uuid

from .database_knowledge_profile import (
    ColumnSemanticProfile,
    ColumnSemanticRole,
    ColumnSemanticSubtype,
)
from .models import SensitivityLevel, ValueProfileSample
from .profiling import ValueProfiler, SensitiveColumnProfilingBlockedError


class UniversalValueProfiler:
    """
    Orchestrates controlled profiling of low-cardinality columns.
    Enforces privacy boundaries and hard limits on distinct values fetched.
    """

    def __init__(self, profiler: Optional[ValueProfiler] = None):
        self.profiler = profiler or ValueProfiler()

    def identify_profileable_columns(
        self,
        columns: Dict[str, ColumnSemanticProfile],
    ) -> List[ColumnSemanticProfile]:
        """
        Identifies columns that are safe and valuable to profile.
        Includes STATUS, CATEGORY, and low-cardinality reference codes.
        Excludes sensitive, primary keys, and large descriptive text fields.
        """
        candidates: List[ColumnSemanticProfile] = []

        for c in columns.values():
            if c.is_sensitive:
                continue

            if self.profiler.is_column_sensitive(c.column_name):
                continue

            if c.role in (ColumnSemanticRole.STATUS, ColumnSemanticRole.CATEGORY):
                candidates.append(c)
            elif c.subtype in (
                ColumnSemanticSubtype.STATUS_CODE,
                ColumnSemanticSubtype.BOOLEAN_FLAG,
                ColumnSemanticSubtype.CATEGORY_TAG,
            ):
                candidates.append(c)

        return candidates

    async def profile_database(
        self,
        connection_pool,
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
        profileable_columns: List[ColumnSemanticProfile],
        max_sample_limit: int = 50,
        timeout_seconds: float = 3.0,
    ) -> List[ValueProfileSample]:
        """
        Safely profiles the specified columns against the live database pool.
        Fails closed on errors or sensitive flags.
        """
        samples: List[ValueProfileSample] = []

        for col in profileable_columns:
            try:
                sample = await self.profiler.profile_column_safe(
                    connection_pool=connection_pool,
                    table_name=col.table_name,
                    column_name=col.column_name,
                    tenant_id=tenant_id,
                    knowledgebase_id=knowledgebase_id,
                    entity_name=col.table_name,
                    schema_name=col.schema_name,
                    max_samples=max_sample_limit,
                    timeout_seconds=timeout_seconds,
                )
                samples.append(sample)
            except SensitiveColumnProfilingBlockedError:
                continue
            except Exception:
                # Controlled profiling failure never breaks the pipeline
                continue

        return samples
