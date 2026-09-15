"""Database Structural Discovery Module"""

from .database_discovery import (
    DatabaseDiscoveryService,
    DiscoveredCatalog,
    DiscoveredTable,
    DiscoveredColumn,
    DiscoveredForeignKey,
    DiscoveredIndex,
    DiscoveredTableType,
)
from .postgres_discovery import PostgresDiscoveryService

__all__ = [
    "DatabaseDiscoveryService",
    "DiscoveredCatalog",
    "DiscoveredTable",
    "DiscoveredColumn",
    "DiscoveredForeignKey",
    "DiscoveredIndex",
    "DiscoveredTableType",
    "PostgresDiscoveryService",
]
