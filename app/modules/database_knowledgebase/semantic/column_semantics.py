"""Universal Column Semantic Resolver

Classifies physical columns into semantic roles and subtypes based on
data types, constraint metadata, naming signals, and parent table context.
Eliminates static global lists like SALARY_COLUMNS = [...] in favor of
structured, database-derived semantic inference.
"""

import re
from typing import Dict, List, Optional
from .database_knowledge_profile import (
    ColumnSemanticProfile,
    ColumnSemanticRole,
    ColumnSemanticSubtype,
)
from ..discovery.database_discovery import DiscoveredCatalog, DiscoveredColumn, DiscoveredTable
from ..schemas.canonical import ColumnDataType


class ColumnSemanticResolver:
    """
    Infers semantic roles and fine-grained subtypes for database columns.
    """

    # Email patterns
    _EMAIL_PATTERN = re.compile(r"(email|e_mail|mail_address)", re.IGNORECASE)
    # Phone patterns
    _PHONE_PATTERN = re.compile(r"(phone|mobile|cell|telephone|fax)", re.IGNORECASE)
    # Username patterns
    _USERNAME_PATTERN = re.compile(r"(username|user_name|login_id|screen_name)", re.IGNORECASE)
    # Name patterns
    _FIRST_NAME_PATTERN = re.compile(r"(first_?name|fname|given_?name)", re.IGNORECASE)
    _LAST_NAME_PATTERN = re.compile(r"(last_?name|lname|surname|family_?name)", re.IGNORECASE)
    _FULL_NAME_PATTERN = re.compile(r"(full_?name|display_?name)", re.IGNORECASE)

    # Business Identifier patterns
    _BUSINESS_CODE_PATTERN = re.compile(
        r"(code|_code$|sku|account_num|record_num|order_num|mrn|ssn|ein|pan|tax_id|license_num)",
        re.IGNORECASE,
    )

    # Temporal patterns
    _CREATED_AT_PATTERN = re.compile(r"(created_?at|create_?date|inserted_?at|registration_?date)", re.IGNORECASE)
    _UPDATED_AT_PATTERN = re.compile(r"(updated_?at|modified_?at|last_?update|last_?login)", re.IGNORECASE)
    _START_TIME_PATTERN = re.compile(r"(start_?time|begin_?time|clock_?in|check_?in|entry_?time)", re.IGNORECASE)
    _END_TIME_PATTERN = re.compile(r"(end_?time|finish_?time|clock_?out|check_?out|exit_?time)", re.IGNORECASE)
    _DURATION_PATTERN = re.compile(r"(duration|worked_?hours|total_?hours|elapsed|latency)", re.IGNORECASE)

    # Numeric & Financial patterns
    _CURRENCY_PATTERN = re.compile(
        r"(salary|wage|price|cost|amount|total|revenue|spend|budget|fee|charge|balance|payment|invoice|tax|deduction|bonus|allowance)",
        re.IGNORECASE,
    )
    _QUANTITY_PATTERN = re.compile(r"(quantity|qty|stock|units?|items?_count|inventory)", re.IGNORECASE)
    _PERCENTAGE_PATTERN = re.compile(r"(percent|percentage|pct|rate|ratio|discount)", re.IGNORECASE)
    _SCORE_PATTERN = re.compile(r"(score|rating|rank|weight|points)", re.IGNORECASE)

    # Status & Flag patterns
    _STATUS_PATTERN = re.compile(r"(status|state|stage|phase|condition)", re.IGNORECASE)
    _FLAG_PATTERN = re.compile(r"^(is_|has_|can_|should_|active$|enabled$|verified$|deleted$)", re.IGNORECASE)
    _CATEGORY_PATTERN = re.compile(r"(type|category|kind|genre|tier|level|group|class)", re.IGNORECASE)

    # Sensitive patterns
    _SENSITIVE_PATTERN = re.compile(
        r"(password|passwd|pwd|secret|token|jwt|api_key|hash|salt|credit_card|card_num|cvv|pin)",
        re.IGNORECASE,
    )

    @classmethod
    def resolve_table_columns(cls, table: DiscoveredTable) -> Dict[str, ColumnSemanticProfile]:
        """Resolve semantic profiles for all columns in a table."""
        profiles: Dict[str, ColumnSemanticProfile] = {}
        for c_name, col in table.columns.items():
            key = f"{table.schema_name}.{table.table_name}.{c_name}"
            profiles[key] = cls.resolve_column(col, table)
        return profiles

    @classmethod
    def resolve_all_columns(cls, catalog: DiscoveredCatalog) -> Dict[str, ColumnSemanticProfile]:
        """Resolve semantic profiles for all columns across all tables in a catalog."""
        profiles: Dict[str, ColumnSemanticProfile] = {}
        for table in catalog.tables.values():
            profiles.update(cls.resolve_table_columns(table))
        return profiles

    @classmethod
    def resolve_column(cls, col: DiscoveredColumn, table: DiscoveredTable) -> ColumnSemanticProfile:
        """
        Classify an individual column into role, subtype, and sensitivity.
        """
        c_raw = col.name.lower()
        t_raw = table.table_name.lower()
        dtype = col.data_type
        evidence: List[str] = []

        # 0. Check Sensitive Columns
        is_sensitive = bool(cls._SENSITIVE_PATTERN.search(c_raw))
        if is_sensitive:
            evidence.append("Matches sensitive / credential keyword pattern")

        # 1. Primary Key
        if col.is_primary_key or c_raw in table.primary_key_columns:
            evidence.append("Declared primary key constraint")
            return ColumnSemanticProfile(
                schema_name=table.schema_name,
                table_name=table.table_name,
                column_name=col.name,
                data_type=dtype,
                role=ColumnSemanticRole.IDENTITY,
                subtype=ColumnSemanticSubtype.PRIMARY_KEY,
                confidence=1.0,
                evidence=evidence,
                is_primary_key=True,
                is_foreign_key=col.is_foreign_key,
                is_unique=True,
                is_nullable=col.is_nullable,
                is_sensitive=is_sensitive,
            )

        # 2. Foreign Key
        if col.is_foreign_key or c_raw.endswith("_id") or c_raw.endswith("_id_id"):
            evidence.append("Declared or structural foreign key")
            return ColumnSemanticProfile(
                schema_name=table.schema_name,
                table_name=table.table_name,
                column_name=col.name,
                data_type=dtype,
                role=ColumnSemanticRole.REFERENCE,
                subtype=ColumnSemanticSubtype.FOREIGN_KEY,
                confidence=0.95 if col.is_foreign_key else 0.85,
                evidence=evidence,
                is_primary_key=False,
                is_foreign_key=True,
                is_unique=col.is_unique,
                is_nullable=col.is_nullable,
                is_sensitive=is_sensitive,
            )

        # 3. Identity Subtypes (Email, Phone, Username, Names, Codes)
        if cls._EMAIL_PATTERN.search(c_raw):
            evidence.append(f"Name '{c_raw}' matches email pattern")
            return cls._make_profile(table, col, ColumnSemanticRole.IDENTITY, ColumnSemanticSubtype.EMAIL, 0.95, evidence, is_sensitive)

        if cls._PHONE_PATTERN.search(c_raw):
            evidence.append(f"Name '{c_raw}' matches phone pattern")
            return cls._make_profile(table, col, ColumnSemanticRole.IDENTITY, ColumnSemanticSubtype.PHONE, 0.95, evidence, is_sensitive)

        if cls._USERNAME_PATTERN.search(c_raw):
            evidence.append(f"Name '{c_raw}' matches username pattern")
            return cls._make_profile(table, col, ColumnSemanticRole.IDENTITY, ColumnSemanticSubtype.USERNAME, 0.95, evidence, is_sensitive)

        if cls._FIRST_NAME_PATTERN.search(c_raw):
            evidence.append(f"Name '{c_raw}' matches person first name")
            return cls._make_profile(table, col, ColumnSemanticRole.IDENTITY, ColumnSemanticSubtype.PERSON_FIRST_NAME, 0.95, evidence, is_sensitive)

        if cls._LAST_NAME_PATTERN.search(c_raw):
            evidence.append(f"Name '{c_raw}' matches person last name")
            return cls._make_profile(table, col, ColumnSemanticRole.IDENTITY, ColumnSemanticSubtype.PERSON_LAST_NAME, 0.95, evidence, is_sensitive)

        if cls._FULL_NAME_PATTERN.search(c_raw) or (c_raw == "name" and dtype in (ColumnDataType.VARCHAR, ColumnDataType.TEXT)):
            evidence.append(f"Name '{c_raw}' matches name/label descriptor")
            return cls._make_profile(table, col, ColumnSemanticRole.IDENTITY, ColumnSemanticSubtype.PERSON_FULL_NAME, 0.90, evidence, is_sensitive)

        if cls._BUSINESS_CODE_PATTERN.search(c_raw):
            evidence.append(f"Name '{c_raw}' matches business code / external identifier")
            return cls._make_profile(table, col, ColumnSemanticRole.IDENTITY, ColumnSemanticSubtype.BUSINESS_CODE, 0.90, evidence, is_sensitive)

        # 4. Temporal Subtypes (Date, Time, Timestamps, Duration)
        if dtype in (ColumnDataType.TIMESTAMP, ColumnDataType.TIMESTAMPTZ, ColumnDataType.DATE, ColumnDataType.TIME):
            if cls._CREATED_AT_PATTERN.search(c_raw):
                evidence.append("Timestamp matching creation date pattern")
                return cls._make_profile(table, col, ColumnSemanticRole.TEMPORAL, ColumnSemanticSubtype.CREATED_AT, 0.95, evidence, is_sensitive)
            if cls._UPDATED_AT_PATTERN.search(c_raw):
                evidence.append("Timestamp matching modification date pattern")
                return cls._make_profile(table, col, ColumnSemanticRole.TEMPORAL, ColumnSemanticSubtype.UPDATED_AT, 0.95, evidence, is_sensitive)
            if cls._START_TIME_PATTERN.search(c_raw):
                evidence.append("Time/Date matching start event pattern")
                return cls._make_profile(table, col, ColumnSemanticRole.TEMPORAL, ColumnSemanticSubtype.TIME_OF_DAY if dtype == ColumnDataType.TIME else ColumnSemanticSubtype.DATETIME, 0.90, evidence, is_sensitive)
            if cls._END_TIME_PATTERN.search(c_raw):
                evidence.append("Time/Date matching end event pattern")
                return cls._make_profile(table, col, ColumnSemanticRole.TEMPORAL, ColumnSemanticSubtype.TIME_OF_DAY if dtype == ColumnDataType.TIME else ColumnSemanticSubtype.DATETIME, 0.90, evidence, is_sensitive)

            subtype = ColumnSemanticSubtype.TIME_OF_DAY if dtype == ColumnDataType.TIME else (
                ColumnSemanticSubtype.DATE if dtype == ColumnDataType.DATE else ColumnSemanticSubtype.DATETIME
            )
            evidence.append(f"Native temporal data type: {dtype.value}")
            return cls._make_profile(table, col, ColumnSemanticRole.TEMPORAL, subtype, 0.90, evidence, is_sensitive)

        if cls._DURATION_PATTERN.search(c_raw):
            evidence.append(f"Name '{c_raw}' matches duration pattern")
            return cls._make_profile(table, col, ColumnSemanticRole.TEMPORAL, ColumnSemanticSubtype.DURATION, 0.85, evidence, is_sensitive)

        # 5. Numeric Subtypes (Currency, Amount, Quantity, Percentage, Score)
        if dtype in (ColumnDataType.DECIMAL, ColumnDataType.NUMERIC, ColumnDataType.FLOAT, ColumnDataType.DOUBLE, ColumnDataType.INTEGER, ColumnDataType.BIGINT):
            if cls._PERCENTAGE_PATTERN.search(c_raw):
                evidence.append("Numeric matching percentage pattern")
                return cls._make_profile(table, col, ColumnSemanticRole.NUMERIC, ColumnSemanticSubtype.PERCENTAGE, 0.90, evidence, is_sensitive)
            if cls._CURRENCY_PATTERN.search(c_raw):
                evidence.append(f"Numeric column with financial keyword: '{c_raw}'")
                return cls._make_profile(table, col, ColumnSemanticRole.NUMERIC, ColumnSemanticSubtype.CURRENCY, 0.92, evidence, is_sensitive)
            if cls._QUANTITY_PATTERN.search(c_raw):
                evidence.append("Numeric column matching count / inventory quantity")
                return cls._make_profile(table, col, ColumnSemanticRole.NUMERIC, ColumnSemanticSubtype.QUANTITY, 0.90, evidence, is_sensitive)
            if cls._SCORE_PATTERN.search(c_raw):
                evidence.append("Numeric column matching rating / score")
                return cls._make_profile(table, col, ColumnSemanticRole.NUMERIC, ColumnSemanticSubtype.SCORE, 0.85, evidence, is_sensitive)

            # Default numeric role
            evidence.append(f"General numeric data type: {dtype.value}")
            return cls._make_profile(table, col, ColumnSemanticRole.NUMERIC, ColumnSemanticSubtype.COUNTABLE, 0.70, evidence, is_sensitive)

        # 6. Status, Boolean, and Categories
        if dtype == ColumnDataType.BOOLEAN or cls._FLAG_PATTERN.search(c_raw):
            evidence.append("Boolean data type or flag naming pattern")
            return cls._make_profile(table, col, ColumnSemanticRole.STATUS, ColumnSemanticSubtype.BOOLEAN_FLAG, 0.95, evidence, is_sensitive)

        if cls._STATUS_PATTERN.search(c_raw):
            evidence.append("Column matching lifecycle status code")
            return cls._make_profile(table, col, ColumnSemanticRole.STATUS, ColumnSemanticSubtype.STATUS_CODE, 0.90, evidence, is_sensitive)

        if cls._CATEGORY_PATTERN.search(c_raw):
            evidence.append("Column matching categorical classification tag")
            return cls._make_profile(table, col, ColumnSemanticRole.CATEGORY, ColumnSemanticSubtype.CATEGORY_TAG, 0.85, evidence, is_sensitive)

        # 7. Descriptive Text
        if dtype in (ColumnDataType.TEXT, ColumnDataType.VARCHAR):
            evidence.append("Textual string attribute")
            return cls._make_profile(table, col, ColumnSemanticRole.DESCRIPTIVE, ColumnSemanticSubtype.GENERIC, 0.60, evidence, is_sensitive)

        # 8. Fallback Unknown
        evidence.append(f"Fallback classification for type: {dtype.value}")
        return cls._make_profile(table, col, ColumnSemanticRole.UNKNOWN, ColumnSemanticSubtype.GENERIC, 0.50, evidence, is_sensitive)

    @classmethod
    def _make_profile(
        cls,
        table: DiscoveredTable,
        col: DiscoveredColumn,
        role: ColumnSemanticRole,
        subtype: ColumnSemanticSubtype,
        confidence: float,
        evidence: List[str],
        is_sensitive: bool,
    ) -> ColumnSemanticProfile:
        return ColumnSemanticProfile(
            schema_name=table.schema_name,
            table_name=table.table_name,
            column_name=col.name,
            data_type=col.data_type,
            role=role,
            subtype=subtype,
            confidence=confidence,
            evidence=evidence,
            is_primary_key=col.is_primary_key,
            is_foreign_key=col.is_foreign_key,
            is_unique=col.is_unique,
            is_nullable=col.is_nullable,
            is_sensitive=is_sensitive,
        )
