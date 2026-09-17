"""Dynamic Entity Registry

Derives and manages first-class semantic business entities from classified tables
and columns without domain hardcoding. Automatically converts discovered catalog
tables and semantic classifications into canonical DiscoveredEntity and SemanticEntity
instances.
"""

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from ..discovery.database_discovery import DiscoveredCatalog, DiscoveredTable
from ..schemas.canonical import DatabaseSchema, TableSchema
from .database_knowledge_profile import (
    ColumnSemanticProfile,
    ColumnSemanticRole,
    ColumnSemanticSubtype,
    DiscoveredEntity,
    TableCategory,
    TableClassification,
)
from .models import (
    SemanticAttribute,
    SemanticEntity,
    SemanticOperation,
    SensitivityLevel,
)
from .table_classifier import TableClassifier


class DynamicEntityRegistry:
    """
    Constructs, catalogs, and resolves business entities directly from
    database topology and column semantic profiles.
    """

    # Common technical or ORM prefixes to strip when creating clean business names
    _PREFIX_STRIP_PATTERNS = [
        re.compile(r"^tbl_", re.IGNORECASE),
        re.compile(r"^dim_", re.IGNORECASE),
        re.compile(r"^fact_", re.IGNORECASE),
        re.compile(r"^ref_", re.IGNORECASE),
        re.compile(r"^base_", re.IGNORECASE),
        re.compile(r"^core_", re.IGNORECASE),
        re.compile(r"^app_", re.IGNORECASE),
    ]

    def __init__(self):
        self._entities: Dict[str, DiscoveredEntity] = {}          # Key: entity_id
        self._table_to_entity: Dict[str, str] = {}                 # Key: f"{schema}.{table}" -> entity_id
        self._name_to_entity: Dict[str, str] = {}                  # Key: clean_name.lower() -> entity_id

    @classmethod
    def clean_table_name(cls, table_name: str) -> Tuple[str, str, List[str]]:
        """
        Derives canonical entity name, display name, and synonyms from a physical table name.
        Handles duplicate Django patterns (e.g. employee_employee -> employee),
        snake_case, and common database prefixes.
        
        Returns:
            (canonical_name, display_name, synonyms)
        """
        raw = table_name.strip().lower()

        # Check for duplicated model names like employee_employee -> employee
        parts = [p for p in raw.split("_") if p]
        if len(parts) == 2 and parts[0] == parts[1]:
            raw = parts[0]
        else:
            # Strip prefixes like tbl_ or base_
            for pat in cls._PREFIX_STRIP_PATTERNS:
                raw = pat.sub("", raw)

        clean_parts = [p for p in raw.split("_") if p]
        if not clean_parts:
            clean_parts = [table_name.strip()]

        # Generate singular/plural forms
        singular_parts = []
        for i, part in enumerate(clean_parts):
            if i == len(clean_parts) - 1:
                # Singularize last token
                sing = cls.singularize(part)
                singular_parts.append(sing)
            else:
                singular_parts.append(part)

        canonical_name = "".join(p.capitalize() for p in singular_parts)
        display_name = " ".join(p.capitalize() for p in clean_parts)
        singular_display = " ".join(p.capitalize() for p in singular_parts)

        # Collect synonyms
        synonyms: Set[str] = set()
        synonyms.add(" ".join(clean_parts).lower())
        synonyms.add(" ".join(singular_parts).lower())
        synonyms.add("".join(clean_parts).lower())
        synonyms.add("".join(singular_parts).lower())
        synonyms.add(table_name.lower())
        synonyms.add(table_name.replace("_", " ").lower())
        synonyms.add(canonical_name.lower())

        return canonical_name, singular_display if singular_display else display_name, sorted(list(synonyms))

    @staticmethod
    def singularize(word: str) -> str:
        """Lightweight, rule-based singularization for common English suffixes."""
        w = word.lower()
        if w.endswith("ies") and len(w) > 3:
            return w[:-3] + "y"
        if w.endswith("sses") or w.endswith("shes") or w.endswith("ches") or w.endswith("xes"):
            return w[:-2]
        if w.endswith("es") and len(w) > 3 and not w.endswith("ees"):
            return w[:-1]
        if w.endswith("s") and not w.endswith("ss") and len(w) > 2:
            return w[:-1]
        return w

    @staticmethod
    def pluralize(word: str) -> str:
        """Lightweight, rule-based pluralization for common English nouns."""
        w = word.lower()
        if w.endswith("y") and len(w) > 1 and w[-2] not in "aeiou":
            return w[:-1] + "ies"
        if w.endswith(("s", "sh", "ch", "x", "z")):
            return w + "es"
        return w + "s"

    def build_entities_from_profile(
        self,
        tables: Dict[str, TableClassification],
        columns: Dict[str, ColumnSemanticProfile],
    ) -> Dict[str, DiscoveredEntity]:
        """
        Builds DiscoveredEntity instances for all eligible tables in the profile.
        Tables classified as SYSTEM, SECURITY, AUDIT, or HISTORY are skipped.
        """
        discovered: Dict[str, DiscoveredEntity] = {}

        for key, tbl in tables.items():
            if tbl.category in (
                TableCategory.SYSTEM,
                TableCategory.SECURITY,
                TableCategory.AUDIT,
                TableCategory.HISTORY,
                TableCategory.CONFIGURATION,
            ):
                continue

            canonical_name, display_name, synonyms = self.clean_table_name(tbl.table_name)
            entity_id = f"entity_{tbl.schema_name}_{tbl.table_name}".lower()

            # Find all columns for this table
            tbl_columns: Dict[str, ColumnSemanticProfile] = {}
            for col_key, col_prof in columns.items():
                if col_prof.schema_name == tbl.schema_name and col_prof.table_name == tbl.table_name:
                    tbl_columns[col_prof.column_name] = col_prof

            # Identify primary keys, identity columns, and name columns
            pk_cols = list(tbl.primary_key_columns)
            identity_cols: List[str] = []
            name_cols: List[str] = []
            attributes: Dict[str, str] = {}

            for c_name, c_prof in tbl_columns.items():
                attributes[c_name] = c_name
                if c_prof.is_primary_key and c_name not in pk_cols:
                    pk_cols.append(c_name)

                if c_prof.subtype in (
                    ColumnSemanticSubtype.PERSON_FIRST_NAME,
                    ColumnSemanticSubtype.PERSON_LAST_NAME,
                    ColumnSemanticSubtype.PERSON_FULL_NAME,
                    ColumnSemanticSubtype.ORGANIZATION_NAME,
                    ColumnSemanticSubtype.USERNAME,
                ):
                    name_cols.append(c_name)
                    identity_cols.append(c_name)
                elif c_prof.subtype in (
                    ColumnSemanticSubtype.EMAIL,
                    ColumnSemanticSubtype.PHONE,
                    ColumnSemanticSubtype.BUSINESS_CODE,
                ):
                    identity_cols.append(c_name)

            # If no identity columns found, fall back to PK columns
            if not identity_cols and pk_cols:
                identity_cols.extend(pk_cols)

            evidence = [
                f"Classified as {tbl.category.value} with confidence {tbl.confidence:.2f}",
                f"{len(tbl_columns)} columns mapped to entity attributes",
            ]
            if pk_cols:
                evidence.append(f"Primary key(s): {', '.join(pk_cols)}")
            if name_cols:
                evidence.append(f"Name column(s): {', '.join(name_cols)}")

            ent = DiscoveredEntity(
                entity_id=entity_id,
                semantic_name=canonical_name,
                display_name=display_name,
                physical_schema=tbl.schema_name,
                physical_table=tbl.table_name,
                category=tbl.category,
                primary_key_columns=pk_cols,
                identity_columns=identity_cols,
                name_columns=name_cols,
                attributes=attributes,
                synonyms=synonyms,
                confidence=tbl.confidence,
                evidence=evidence,
            )

            discovered[entity_id] = ent
            self._entities[entity_id] = ent
            self._table_to_entity[f"{tbl.schema_name}.{tbl.table_name}".lower()] = entity_id
            self._table_to_entity[tbl.table_name.lower()] = entity_id
            self._name_to_entity[canonical_name.lower()] = entity_id
            self._name_to_entity[display_name.lower()] = entity_id
            for syn in synonyms:
                self._name_to_entity[syn.lower()] = entity_id

        return discovered

    def to_semantic_entities(
        self,
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
        columns: Dict[str, ColumnSemanticProfile],
        schema_version: Optional[str] = None,
    ) -> List[SemanticEntity]:
        """
        Converts all discovered entities into Phase 6 SemanticEntity models,
        ready for injection into SemanticModelRegistry.
        """
        semantic_entities: List[SemanticEntity] = []

        for entity_id, disc in self._entities.items():
            attrs: Dict[str, SemanticAttribute] = {}
            for col_name in disc.attributes.keys():
                col_key = f"{disc.physical_schema}.{disc.physical_table}.{col_name}".lower()
                c_prof = columns.get(col_key)

                # Derive semantic properties
                is_dim = True
                is_meas = False
                is_ident = False
                sens = SensitivityLevel.INTERNAL

                if c_prof:
                    if c_prof.is_primary_key or c_prof.subtype in (
                        ColumnSemanticSubtype.PRIMARY_KEY,
                        ColumnSemanticSubtype.BUSINESS_CODE,
                        ColumnSemanticSubtype.FOREIGN_KEY,
                    ):
                        is_ident = True

                    if c_prof.role == ColumnSemanticRole.NUMERIC and c_prof.subtype in (
                        ColumnSemanticSubtype.CURRENCY,
                        ColumnSemanticSubtype.AMOUNT,
                        ColumnSemanticSubtype.QUANTITY,
                        ColumnSemanticSubtype.PERCENTAGE,
                        ColumnSemanticSubtype.COUNTABLE,
                        ColumnSemanticSubtype.SCORE,
                    ):
                        is_meas = True
                        is_dim = False

                    if c_prof.is_sensitive:
                        sens = SensitivityLevel.CONFIDENTIAL

                # Clean display name for column
                col_clean = col_name.replace("_", " ").title()

                attr = SemanticAttribute(
                    attribute_id=col_name,
                    display_name=col_clean,
                    physical_column=col_name,
                    synonyms=[col_name.lower(), col_name.replace("_", " ").lower()],
                    is_dimension=is_dim,
                    is_measure=is_meas,
                    is_identifier=is_ident,
                    sensitivity=sens,
                    allowed_operations=[
                        SemanticOperation.SELECT,
                        SemanticOperation.FILTER,
                        SemanticOperation.AGGREGATE,
                        SemanticOperation.GROUP_BY,
                        SemanticOperation.ORDER_BY,
                        SemanticOperation.JOIN,
                    ],
                )
                attrs[col_name] = attr

            pk_attr = disc.primary_key_columns[0] if disc.primary_key_columns else (
                list(attrs.keys())[0] if attrs else None
            )

            sem_ent = SemanticEntity(
                entity_id=disc.entity_id,
                name=disc.semantic_name,
                display_name=disc.display_name,
                description=f"Auto-discovered business entity for {disc.physical_table}",
                physical_schema=disc.physical_schema,
                physical_table=disc.physical_table,
                synonyms=disc.synonyms,
                attributes=attrs,
                primary_key_attribute=pk_attr,
                tenant_id=tenant_id,
                knowledgebase_id=knowledgebase_id,
                schema_version=schema_version,
            )
            semantic_entities.append(sem_ent)

        return semantic_entities

    def get_entity(self, name_or_table: str) -> Optional[DiscoveredEntity]:
        """Finds an entity by table name or canonical name."""
        clean = name_or_table.strip().lower()
        if clean in self._name_to_entity:
            return self._entities.get(self._name_to_entity[clean])
        if clean in self._table_to_entity:
            return self._entities.get(self._table_to_entity[clean])
        return None

    def list_entities(self) -> List[DiscoveredEntity]:
        """Returns all registered discovered entities."""
        return list(self._entities.values())
