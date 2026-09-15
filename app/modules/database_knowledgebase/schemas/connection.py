"""Database Connection Configuration & Validation Schemas"""

from pydantic import BaseModel, Field, SecretStr, field_validator, ConfigDict
from typing import Optional, List, Dict, Any
from enum import Enum
import urllib.parse


class DatabaseType(str, Enum):
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    SQLSERVER = "sqlserver"
    ORACLE = "oracle"
    SNOWFLAKE = "snowflake"
    CLICKHOUSE = "clickhouse"
    SQLITE = "sqlite"


class SSLMode(str, Enum):
    DISABLE = "disable"
    ALLOW = "allow"
    PREFER = "prefer"
    REQUIRE = "require"
    VERIFY_CA = "verify-ca"
    VERIFY_FULL = "verify-full"


class DatabaseConnectionConfig(BaseModel):
    """
    Strongly-typed, secure database connection configuration.
    
    CRITICAL SECURITY GUARANTEES:
    - Passwords are typed as SecretStr and never dumped in repr or logs.
    - DSN construction encodes credentials safely.
    - Provides masked DSN property for safe observability.
    - Default read_only=True enforces the read-only principle.
    """
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    db_type: DatabaseType = Field(default=DatabaseType.POSTGRESQL, description="Relational database engine type")
    host: str = Field(..., min_length=1, max_length=255, description="Database server hostname or IP address")
    port: int = Field(..., ge=1, le=65535, description="Database port number")
    database_name: str = Field(..., min_length=1, max_length=128, description="Target database name")
    username: str = Field(..., min_length=1, max_length=128, description="Database authentication username")
    password: SecretStr = Field(..., description="Database authentication password (never logged or exposed)")
    
    ssl_mode: SSLMode = Field(default=SSLMode.PREFER, description="TLS / SSL connection mode")
    connection_timeout: int = Field(default=10, ge=1, le=60, description="Connection timeout in seconds")
    pool_size: int = Field(default=5, ge=1, le=50, description="Connection pool size")
    max_overflow: int = Field(default=10, ge=0, le=50, description="Connection pool overflow ceiling")
    
    schema_filter: Optional[List[str]] = Field(default=None, description="Optional list of schema names to restrict introspection to (default: ['public'])")
    read_only: bool = Field(default=True, description="Enforce read-only transactions")
    extra_params: Dict[str, Any] = Field(default_factory=dict, description="Additional safe engine/connector parameters")

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        clean_v = v.strip()
        if not clean_v:
            raise ValueError("Host cannot be blank or whitespace")
        # Prevent injection in host strings
        if any(c in clean_v for c in [";", "\n", "\r", "\t", " "]):
            raise ValueError("Host contains invalid characters")
        return clean_v

    @field_validator("database_name", "username")
    @classmethod
    def validate_safe_identifier(cls, v: str) -> str:
        clean_v = v.strip()
        if not clean_v:
            raise ValueError("Value cannot be blank")
        if any(c in clean_v for c in [";", "\n", "\r", "\0"]):
            raise ValueError("Identifier contains invalid characters")
        return clean_v

    @property
    def raw_password(self) -> str:
        """Helper to retrieve raw password string securely for internal connector drivers."""
        return self.password.get_secret_value()

    @property
    def masked_dsn(self) -> str:
        """Safe DSN representation with masked credentials suitable for logs and audit."""
        encoded_user = urllib.parse.quote_plus(self.username)
        return f"{self.db_type.value}://{encoded_user}:***@{self.host}:{self.port}/{self.database_name}"

    def construct_dsn(self, async_driver: bool = True) -> str:
        """
        Construct SQLAlchemy / driver DSN string with properly encoded credentials.
        """
        encoded_user = urllib.parse.quote_plus(self.username)
        encoded_pw = urllib.parse.quote_plus(self.raw_password)
        
        if self.db_type == DatabaseType.POSTGRESQL:
            prefix = "postgresql+asyncpg" if async_driver else "postgresql+psycopg2"
            dsn = f"{prefix}://{encoded_user}:{encoded_pw}@{self.host}:{self.port}/{self.database_name}"
            # Append SSL mode parameter for PostgreSQL if not disable
            if self.ssl_mode != SSLMode.DISABLE:
                dsn += f"?ssl={self.ssl_mode.value}"
            return dsn
        elif self.db_type == DatabaseType.MYSQL:
            prefix = "mysql+aiomysql" if async_driver else "mysql+pymysql"
            return f"{prefix}://{encoded_user}:{encoded_pw}@{self.host}:{self.port}/{self.database_name}"
        elif self.db_type == DatabaseType.SQLITE:
            prefix = "sqlite+aiosqlite" if async_driver else "sqlite"
            return f"{prefix}:///{self.database_name}"
        else:
            return f"{self.db_type.value}://{encoded_user}:{encoded_pw}@{self.host}:{self.port}/{self.database_name}"

    def to_safe_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with password completely excluded for safe serialization."""
        return {
            "db_type": self.db_type.value,
            "host": self.host,
            "port": self.port,
            "database_name": self.database_name,
            "username": self.username,
            "ssl_mode": self.ssl_mode.value,
            "connection_timeout": self.connection_timeout,
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "schema_filter": self.schema_filter,
            "read_only": self.read_only,
            "masked_dsn": self.masked_dsn,
        }


class ConnectionTestResult(BaseModel):
    """Result of a live database connection verification test."""
    model_config = ConfigDict(extra="forbid")

    success: bool
    latency_ms: Optional[float] = None
    database_version: Optional[str] = None
    database_type: str = "postgresql"
    schemas_found: List[str] = Field(default_factory=list)
    table_count_estimate: Optional[int] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    server_info: Dict[str, Any] = Field(default_factory=dict)
