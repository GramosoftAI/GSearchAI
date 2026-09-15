"""Connector Factory

Instantiates appropriate DatabaseConnector implementation according to DatabaseType.
"""

from ..schemas.connection import DatabaseConnectionConfig, DatabaseType
from .base import DatabaseConnector
from .postgresql import PostgreSQLConnector
from ..exceptions.errors import UnsupportedDatabaseError


class ConnectorFactory:
    """Factory to create database connector instances."""

    @staticmethod
    def create_connector(config: DatabaseConnectionConfig) -> DatabaseConnector:
        """
        Instantiate connector based on configured database type.
        """
        if config.db_type == DatabaseType.POSTGRESQL:
            return PostgreSQLConnector(config)
        else:
            raise UnsupportedDatabaseError(
                database_type=config.db_type.value if hasattr(config.db_type, "value") else str(config.db_type)
            )
