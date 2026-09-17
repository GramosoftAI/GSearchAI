"""Identity Registry

Catalogs identity, name, code, and key fields per entity and table.
Provides structured metadata for entity value resolution, entity lookup,
and natural language disambiguation.
"""

from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, ConfigDict, Field

from ..discovery.database_discovery import DiscoveredCatalog
from .database_knowledge_profile import (
    ColumnSemanticProfile,
    ColumnSemanticRole,
    ColumnSemanticSubtype,
    DiscoveredEntity,
    IdentityField,
)


class EntityIdentitySummary(BaseModel):
    """Identity configuration summary for an entity."""
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    schema_name: str
    table_name: str
    primary_key_fields: List[str] = Field(default_factory=list)
    name_fields: List[str] = Field(default_factory=list)
    code_fields: List[str] = Field(default_factory=list)
    email_fields: List[str] = Field(default_factory=list)
    all_identity_fields: List[IdentityField] = Field(default_factory=list)


class IdentityRegistry:
    """
    Manages identity and key fields for database entities to power
    secure, parameterized entity value resolution.
    """

    def __init__(self):
        self._entity_identities: Dict[str, EntityIdentitySummary] = {}
        self._table_identities: Dict[str, EntityIdentitySummary] = {}

    def register_from_profile(
        self,
        entities: Dict[str, DiscoveredEntity],
        columns: Dict[str, ColumnSemanticProfile],
    ) -> Dict[str, List[IdentityField]]:
        """
        Builds the identity registry from discovered entities and semantic column profiles.
        Returns a mapping of entity_id -> List[IdentityField].
        """
        result: Dict[str, List[IdentityField]] = {}

        for ent_id, ent in entities.items():
            pk_fields: List[str] = list(ent.primary_key_columns)
            name_fields: List[str] = []
            code_fields: List[str] = []
            email_fields: List[str] = []
            all_fields: List[IdentityField] = []

            for col_name in ent.attributes.keys():
                col_key = f"{ent.physical_schema}.{ent.physical_table}.{col_name}".lower()
                c_prof = columns.get(col_key)

                if not c_prof:
                    continue

                if c_prof.role == ColumnSemanticRole.IDENTITY or c_prof.is_primary_key:
                    ident = IdentityField(
                        schema_name=ent.physical_schema,
                        table_name=ent.physical_table,
                        column_name=col_name,
                        identity_subtype=c_prof.subtype,
                        confidence=c_prof.confidence,
                        is_primary_key=c_prof.is_primary_key,
                        evidence=list(c_prof.evidence),
                    )
                    all_fields.append(ident)

                    if c_prof.subtype in (
                        ColumnSemanticSubtype.PERSON_FIRST_NAME,
                        ColumnSemanticSubtype.PERSON_LAST_NAME,
                        ColumnSemanticSubtype.PERSON_FULL_NAME,
                        ColumnSemanticSubtype.ORGANIZATION_NAME,
                    ):
                        name_fields.append(col_name)
                    elif c_prof.subtype in (
                        ColumnSemanticSubtype.BUSINESS_CODE,
                        ColumnSemanticSubtype.USERNAME,
                    ):
                        code_fields.append(col_name)
                    elif c_prof.subtype == ColumnSemanticSubtype.EMAIL:
                        email_fields.append(col_name)

            # Sort identity fields: Name fields first, then code, email, and PKs
            def identity_priority(field: IdentityField) -> int:
                if field.identity_subtype in (
                    ColumnSemanticSubtype.PERSON_FULL_NAME,
                    ColumnSemanticSubtype.PERSON_FIRST_NAME,
                    ColumnSemanticSubtype.ORGANIZATION_NAME,
                ):
                    return 1
                if field.identity_subtype in (
                    ColumnSemanticSubtype.PERSON_LAST_NAME,
                    ColumnSemanticSubtype.USERNAME,
                ):
                    return 2
                if field.identity_subtype in (
                    ColumnSemanticSubtype.BUSINESS_CODE,
                    ColumnSemanticSubtype.EMAIL,
                ):
                    return 3
                if field.is_primary_key:
                    return 4
                return 5

            all_fields.sort(key=identity_priority)

            summary = EntityIdentitySummary(
                entity_id=ent_id,
                schema_name=ent.physical_schema,
                table_name=ent.physical_table,
                primary_key_fields=pk_fields,
                name_fields=name_fields,
                code_fields=code_fields,
                email_fields=email_fields,
                all_identity_fields=all_fields,
            )

            self._entity_identities[ent_id] = summary
            tbl_key = f"{ent.physical_schema}.{ent.physical_table}".lower()
            self._table_identities[tbl_key] = summary
            self._table_identities[ent.physical_table.lower()] = summary
            result[ent_id] = all_fields

        return result

    def get_summary_for_entity(self, entity_id: str) -> Optional[EntityIdentitySummary]:
        """Get identity summary for entity ID."""
        return self._entity_identities.get(entity_id)

    def get_summary_for_table(self, table_name: str, schema_name: str = "public") -> Optional[EntityIdentitySummary]:
        """Get identity summary for table name."""
        key = f"{schema_name}.{table_name}".lower()
        if key in self._table_identities:
            return self._table_identities[key]
        return self._table_identities.get(table_name.lower())

    def get_candidate_lookup_columns(self, table_name: str, schema_name: str = "public") -> List[str]:
        """
        Returns an ordered list of columns to check when resolving an entity literal value
        (e.g., 'Kannan', 'Sales', 'Acme Corp').
        """
        summary = self.get_summary_for_table(table_name, schema_name)
        if not summary:
            return []

        cols: List[str] = []
        # 1. Names
        cols.extend(summary.name_fields)
        # 2. Codes / Usernames
        cols.extend(summary.code_fields)
        # 3. Emails
        cols.extend(summary.email_fields)
        # 4. Primary Keys
        cols.extend(summary.primary_key_fields)

        return list(dict.fromkeys(cols))
