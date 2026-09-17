"""Universal Table Classifier

Automatically classifies any database table into canonical structural categories:
ENTITY, TRANSACTION, EVENT, REFERENCE, RELATIONSHIP, HISTORY, AUDIT, SYSTEM,
SECURITY, CONFIGURATION, UNKNOWN.

Derives classifications strictly from topology, constraints, datatypes, and patterns.
Zero hardcoded domain rules.
"""

import re
from typing import Dict, List, Set, Tuple
from .database_knowledge_profile import TableCategory, TableClassification
from ..discovery.database_discovery import DiscoveredCatalog, DiscoveredTable
from ..schemas.canonical import ColumnDataType


class TableClassifier:
    """
    Classifies tables based on structural evidence:
    - PK and FK counts and topologies
    - Column composition (temporal, financial, identity)
    - Catalog types and naming conventions
    """

    # System and framework patterns
    _SYSTEM_SCHEMAS = {"information_schema", "pg_catalog", "pg_toast"}
    _SYSTEM_TABLE_PATTERNS = re.compile(
        r"^(alembic_|django_migrations|spatial_ref_sys|celery_|django_content_type|"
        r"auth_permission|django_session)",
        re.IGNORECASE,
    )
    _SECURITY_PATTERNS = re.compile(
        r"(password|credential|token|jwt|oauth|secret|auth_user|user_session)",
        re.IGNORECASE,
    )
    _HISTORY_PATTERNS = re.compile(
        r"(historical|history|_hist$|_log$|_archive$|revisions?)",
        re.IGNORECASE,
    )
    _AUDIT_PATTERNS = re.compile(
        r"(audit|_audit$|changelog|activity_log)",
        re.IGNORECASE,
    )
    _CONFIG_PATTERNS = re.compile(
        r"(config|setting|preference|feature_flag)",
        re.IGNORECASE,
    )

    @classmethod
    def classify_catalog(cls, catalog: DiscoveredCatalog) -> Dict[str, TableClassification]:
        """
        Classify all tables in a DiscoveredCatalog.
        First calculates topological degree (incoming FK counts), then classifies each table.
        """
        # 1. Compute incoming FK degree map: table_key -> count
        incoming_fk_counts: Dict[str, int] = {k: 0 for k in catalog.tables.keys()}
        for t_key, table in catalog.tables.items():
            for fk in table.foreign_keys:
                target_key = f"{fk.target_schema}.{fk.target_table}"
                if target_key in incoming_fk_counts:
                    incoming_fk_counts[target_key] += 1
                else:
                    # Target table might not have schema prefix in key
                    for k in incoming_fk_counts:
                        if k.endswith(f".{fk.target_table}"):
                            incoming_fk_counts[k] += 1

        results: Dict[str, TableClassification] = {}
        for t_key, table in catalog.tables.items():
            in_fks = incoming_fk_counts.get(t_key, 0)
            classification = cls.classify_table(table, incoming_fk_count=in_fks)
            results[t_key] = classification

        return results

    @classmethod
    def classify_table(cls, table: DiscoveredTable, incoming_fk_count: int = 0) -> TableClassification:
        """
        Classify an individual DiscoveredTable using multi-factor evidence scoring.
        """
        t_raw = table.table_name.lower()
        s_raw = table.schema_name.lower()
        cols = table.columns
        fks = table.foreign_keys
        pks = table.primary_key_columns
        evidence: List[str] = []

        # Category 1: SYSTEM & SECURITY catalogs
        if s_raw in cls._SYSTEM_SCHEMAS or cls._SYSTEM_TABLE_PATTERNS.search(t_raw):
            evidence.append(f"Matches system catalog or migration pattern: schema='{s_raw}', name='{t_raw}'")
            return TableClassification(
                schema_name=table.schema_name,
                table_name=table.table_name,
                category=TableCategory.SYSTEM,
                confidence=1.0,
                evidence=evidence,
                primary_key_columns=pks,
                outgoing_fk_count=len(fks),
                incoming_fk_count=incoming_fk_count,
                is_system_or_security=True,
            )

        if cls._SECURITY_PATTERNS.search(t_raw):
            evidence.append(f"Contains security/credential keyword in table name: '{t_raw}'")
            return TableClassification(
                schema_name=table.schema_name,
                table_name=table.table_name,
                category=TableCategory.SECURITY,
                confidence=0.95,
                evidence=evidence,
                primary_key_columns=pks,
                outgoing_fk_count=len(fks),
                incoming_fk_count=incoming_fk_count,
                is_system_or_security=True,
            )

        # Category 2: HISTORY / AUDIT
        if cls._HISTORY_PATTERNS.search(t_raw):
            evidence.append(f"Name matches history/archive convention: '{t_raw}'")
            return TableClassification(
                schema_name=table.schema_name,
                table_name=table.table_name,
                category=TableCategory.HISTORY,
                confidence=0.90,
                evidence=evidence,
                primary_key_columns=pks,
                outgoing_fk_count=len(fks),
                incoming_fk_count=incoming_fk_count,
            )

        if cls._AUDIT_PATTERNS.search(t_raw):
            evidence.append(f"Name matches audit pattern: '{t_raw}'")
            return TableClassification(
                schema_name=table.schema_name,
                table_name=table.table_name,
                category=TableCategory.AUDIT,
                confidence=0.90,
                evidence=evidence,
                primary_key_columns=pks,
                outgoing_fk_count=len(fks),
                incoming_fk_count=incoming_fk_count,
            )

        # Category 3: CONFIGURATION
        if cls._CONFIG_PATTERNS.search(t_raw):
            evidence.append(f"Name matches system configuration: '{t_raw}'")
            return TableClassification(
                schema_name=table.schema_name,
                table_name=table.table_name,
                category=TableCategory.CONFIGURATION,
                confidence=0.85,
                evidence=evidence,
                primary_key_columns=pks,
                outgoing_fk_count=len(fks),
                incoming_fk_count=incoming_fk_count,
            )

        # Check Column Characteristics
        col_names = [c.lower() for c in cols.keys()]
        temporal_cols = [
            c for c in cols.values()
            if c.data_type in (ColumnDataType.DATE, ColumnDataType.TIMESTAMP, ColumnDataType.TIMESTAMPTZ, ColumnDataType.TIME)
        ]
        numeric_cols = [
            c for c in cols.values()
            if c.data_type in (ColumnDataType.DECIMAL, ColumnDataType.NUMERIC, ColumnDataType.FLOAT, ColumnDataType.DOUBLE)
            or (c.data_type == ColumnDataType.INTEGER and not c.is_primary_key and not c.is_foreign_key)
        ]
        financial_col_names = [
            c for c in col_names
            if any(k in c for k in ("price", "amount", "total", "cost", "salary", "wage", "balance", "fee", "tax", "charge"))
        ]

        # Category 4: RELATIONSHIP / JUNCTION (Bridge Table)
        # Distinct target tables referenced by outgoing FKs
        target_tables = {f"{fk.target_schema}.{fk.target_table}" for fk in fks}
        non_fk_cols = [c for c in cols.values() if not c.is_primary_key and not c.is_foreign_key]

        if len(target_tables) >= 2 and len(non_fk_cols) <= 3:
            evidence.append(
                f"Junction topology: references {len(target_tables)} tables with only {len(non_fk_cols)} payload columns"
            )
            return TableClassification(
                schema_name=table.schema_name,
                table_name=table.table_name,
                category=TableCategory.RELATIONSHIP,
                confidence=0.92,
                evidence=evidence,
                primary_key_columns=pks,
                outgoing_fk_count=len(fks),
                incoming_fk_count=incoming_fk_count,
                is_bridge=True,
            )

        # Category 5: EVENT
        # Multiple temporal columns or event timestamps combined with entity reference
        has_time_pairs = len(temporal_cols) >= 2 or any(
            k in t_raw for k in ("attendance", "session", "visit", "log", "activity", "track", "clock", "checkin", "checkout", "entry")
        )
        if has_time_pairs and len(fks) >= 1:
            evidence.append(
                f"Event topology: {len(temporal_cols)} temporal columns and {len(fks)} outgoing FKs"
            )
            return TableClassification(
                schema_name=table.schema_name,
                table_name=table.table_name,
                category=TableCategory.EVENT,
                confidence=0.88,
                evidence=evidence,
                primary_key_columns=pks,
                outgoing_fk_count=len(fks),
                incoming_fk_count=incoming_fk_count,
            )

        # Category 6: TRANSACTION
        # Financial or numerical payload with status and entity foreign key
        has_entity_identity = any(
            k in col_names for k in ("first_name", "last_name", "full_name", "username", "email", "date_of_birth")
        )
        is_entity_candidate = has_entity_identity or incoming_fk_count >= 2

        if not is_entity_candidate and (
            financial_col_names or (len(numeric_cols) >= 1 and any(k in col_names for k in ("status", "state", "order_date", "invoice_date", "payment_date")))
        ):
            evidence.append(
                f"Transaction characteristics: financial/metric columns ({', '.join(financial_col_names or [c.name for c in numeric_cols[:2]])}) with {len(fks)} FKs"
            )
            return TableClassification(
                schema_name=table.schema_name,
                table_name=table.table_name,
                category=TableCategory.TRANSACTION,
                confidence=0.85,
                evidence=evidence,
                primary_key_columns=pks,
                outgoing_fk_count=len(fks),
                incoming_fk_count=incoming_fk_count,
            )

        # Category 7: REFERENCE (Lookup Table)
        # Small table with primary key, name/code, no or few outgoing FKs, referenced by other tables
        has_code_or_name = any(k in col_names for k in ("name", "code", "title", "label", "description", "slug"))
        if len(cols) <= 6 and len(fks) == 0 and has_code_or_name:
            evidence.append(
                f"Lookup/Reference characteristics: {len(cols)} columns, 0 outgoing FKs, contains descriptor column"
            )
            return TableClassification(
                schema_name=table.schema_name,
                table_name=table.table_name,
                category=TableCategory.REFERENCE,
                confidence=0.85,
                evidence=evidence,
                primary_key_columns=pks,
                outgoing_fk_count=len(fks),
                incoming_fk_count=incoming_fk_count,
            )

        # Category 8: PRIMARY ENTITY
        # High incoming FK count, primary key, descriptive columns
        evidence.append(
            f"Primary entity characteristics: PK={pks}, incoming FKs={incoming_fk_count}, columns={len(cols)}"
        )
        confidence = 0.80 if incoming_fk_count > 0 else 0.70
        return TableClassification(
            schema_name=table.schema_name,
            table_name=table.table_name,
            category=TableCategory.ENTITY,
            confidence=confidence,
            evidence=evidence,
            primary_key_columns=pks,
            outgoing_fk_count=len(fks),
            incoming_fk_count=incoming_fk_count,
        )
