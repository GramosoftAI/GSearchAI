"""Abstract Database Connector Interface

Defines the contract for engine-specific connectors (PostgreSQL, MySQL, Snowflake, etc.)
Ensures that higher-level services and future SQL agents depend solely on this abstraction,
not on driver/ORM implementation details.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any

from ..schemas.connection import DatabaseConnectionConfig, ConnectionTestResult


class DatabaseConnector(ABC):
    """
    Abstract interface for relational database connectors.
    """

    def __init__(self, config: DatabaseConnectionConfig):
        self.config = config

    @abstractmethod
    async def test_connection(self) -> ConnectionTestResult:
        """
        Safely test connectivity to target database with configured timeout.
        Must never throw unhandled exceptions; errors must be captured in ConnectionTestResult.
        """
        pass

    @abstractmethod
    async def introspect_raw_metadata(self, schemas: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Extract raw metadata dictionaries directly from database system catalogs.
        MUST NOT perform full table scans (SELECT *).
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """
        Gracefully release any connection pools, sockets, and resources.
        """
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
