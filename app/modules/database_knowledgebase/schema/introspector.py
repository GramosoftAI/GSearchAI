"""Database Introspector: Orchestrates Metadata Discovery, Normalization & Fingerprinting"""

import logging
from typing import Optional, List

from ..schemas.connection import DatabaseConnectionConfig
from ..schemas.canonical import DatabaseSchema
from ..connectors.factory import ConnectorFactory
from .normalizer import SchemaNormalizer
from .fingerprint import SchemaFingerprinter

logger = logging.getLogger(__name__)


class DatabaseIntrospector:
    """
    Orchestrates deterministic database introspection.
    """

    @classmethod
    async def introspect(
        cls,
        config: DatabaseConnectionConfig,
        schemas: Optional[List[str]] = None,
    ) -> DatabaseSchema:
        """
        Connect to database, extract catalog metadata, normalize to canonical models,
        and compute deterministic SHA-256 schema fingerprint.
        """
        connector = ConnectorFactory.create_connector(config)
        try:
            logger.info(f"Starting schema introspection for {config.masked_dsn}")
            raw_metadata = await connector.introspect_raw_metadata(schemas=schemas)
            
            # Normalize raw catalog dictionaries into canonical models
            canonical_schema = SchemaNormalizer.normalize_postgres_raw(raw_metadata)

            # Compute and attach deterministic fingerprint
            fingerprint = SchemaFingerprinter.generate_fingerprint(canonical_schema)
            canonical_schema.fingerprint = fingerprint

            logger.info(
                f"Completed introspection for {config.database_name}: "
                f"{len(canonical_schema.all_tables)} tables discovered, fingerprint={fingerprint[:12]}..."
            )
            return canonical_schema
        finally:
            await connector.close()
