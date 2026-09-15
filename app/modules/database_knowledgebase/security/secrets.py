"""Secure Database Credential Vault & Encryption Service

Uses authenticated symmetric encryption (Fernet / AES-128-CBC + HMAC-SHA256)
to store database passwords and connection configurations securely at rest.
"""

import base64
import hashlib
import json
import logging
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from ..schemas.connection import DatabaseConnectionConfig

logger = logging.getLogger(__name__)


class SecretManager:
    """
    Manages authenticated encryption/decryption of database connection secrets.
    """

    def __init__(self, master_key: Optional[str] = None):
        if not master_key:
            settings = get_settings()
            master_key = getattr(settings, "jwt_secret_key", "default-fallback-secret-key-min-32-chars-long")
        
        # Derive a deterministic 32-byte urlsafe base64-encoded key from the master secret
        derived_bytes = hashlib.sha256(master_key.encode("utf-8")).digest()
        self._fernet_key = base64.urlsafe_b64encode(derived_bytes)
        self._cipher = Fernet(self._fernet_key)

    def encrypt_credentials(self, config: DatabaseConnectionConfig) -> str:
        """
        Serialize and encrypt DatabaseConnectionConfig into an opaque ciphertext string.
        """
        try:
            # Construct a dictionary containing all fields including the raw password
            payload = {
                "db_type": config.db_type.value,
                "host": config.host,
                "port": config.port,
                "database_name": config.database_name,
                "username": config.username,
                "password": config.raw_password,
                "ssl_mode": config.ssl_mode.value,
                "connection_timeout": config.connection_timeout,
                "pool_size": config.pool_size,
                "max_overflow": config.max_overflow,
                "schema_filter": config.schema_filter,
                "read_only": config.read_only,
                "extra_params": config.extra_params,
            }
            json_bytes = json.dumps(payload).encode("utf-8")
            ciphertext = self._cipher.encrypt(json_bytes)
            return ciphertext.decode("utf-8")
        except Exception as e:
            from ..exceptions.errors import DatabaseAuthenticationError
            logger.error("Failed to encrypt database credentials safely")
            raise DatabaseAuthenticationError(
                detail="Encryption of database connection configuration failed.",
                error_code="CREDENTIAL_ENCRYPTION_FAILED"
            ) from e

    def decrypt_credentials(self, encrypted_payload: str) -> DatabaseConnectionConfig:
        """
        Decrypt ciphertext back into a strongly typed DatabaseConnectionConfig.
        """
        try:
            decrypted_bytes = self._cipher.decrypt(encrypted_payload.encode("utf-8"))
            data = json.loads(decrypted_bytes.decode("utf-8"))
            return DatabaseConnectionConfig(**data)
        except InvalidToken as e:
            from ..exceptions.errors import DatabaseAuthenticationError
            logger.error("Invalid decryption token or tampered credentials payload")
            raise DatabaseAuthenticationError(
                detail="Failed to decrypt database connection credentials. Key or token is invalid.",
                error_code="INVALID_CREDENTIAL_CIPHERTEXT"
            ) from e
        except Exception as e:
            from ..exceptions.errors import DatabaseAuthenticationError
            logger.error("Unexpected error during credential decryption")
            raise DatabaseAuthenticationError(
                detail="Failed to parse decrypted database connection configuration.",
                error_code="CREDENTIAL_DECRYPTION_FAILED"
            ) from e


# Global singleton instance for easy dependency injection
_secret_manager_instance: Optional[SecretManager] = None


def get_secret_manager() -> SecretManager:
    global _secret_manager_instance
    if _secret_manager_instance is None:
        _secret_manager_instance = SecretManager()
    return _secret_manager_instance
