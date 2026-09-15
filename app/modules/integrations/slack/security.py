"""Security utilities for Slack Multi-Tenant Integration.

Includes:
- AES-256-GCM authenticated encryption/decryption of Slack bot tokens at rest.
- Cryptographically signed JWT state generation and verification for OAuth CSRF protection.
- HMAC-SHA256 signature verification for Slack webhook event verification with 300-second replay window.
"""

import base64
import os
import hmac
import hashlib
import time
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from jose import jwt, JWTError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

from app.core.config import get_settings


def _get_encryption_key() -> bytes:
    """Derive 32-byte key for AES-GCM from settings."""
    settings = get_settings()
    raw_key = (
        getattr(settings, "slack_token_encryption_key", None)
        or getattr(settings, "secret_key", None)
        or "default-slack-encryption-key-must-be-configured-in-production"
    )
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"graphmind-slack-token-salt",
        info=b"slack-bot-token-aes-gcm",
    )
    return hkdf.derive(raw_key.encode("utf-8"))


def encrypt_token(token: str) -> str:
    """
    Encrypt a Slack bot token using AES-256-GCM.
    Returns URL-safe base64 encoded string containing (12-byte nonce + ciphertext + 16-byte auth tag).
    """
    if not token:
        return ""
    key = _get_encryption_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # Standard 96-bit nonce for GCM
    ciphertext = aesgcm.encrypt(nonce, token.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("utf-8")


def decrypt_token(encrypted_token: str) -> str:
    """
    Decrypt a Slack bot token using AES-256-GCM.
    Validates ciphertext integrity and authentication tag.
    """
    if not encrypted_token:
        return ""
    data = base64.urlsafe_b64decode(encrypted_token.encode("utf-8"))
    if len(data) < 28:  # 12-byte nonce + 16-byte auth tag
        raise ValueError("Invalid encrypted token format or corrupted data")
    nonce = data[:12]
    ciphertext = data[12:]
    key = _get_encryption_key()
    aesgcm = AESGCM(key)
    decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return decrypted_bytes.decode("utf-8")


def create_oauth_state(tenant_id: str, agent_id: str, redirect_uri: Optional[str] = None) -> str:
    """
    Create a tamper-proof signed JWT state parameter with 10-minute TTL.
    Binds tenant_id and agent_id cryptographically to prevent CSRF and cross-tenant injection.
    """
    settings = get_settings()
    secret = getattr(settings, "secret_key", "default-jwt-secret")
    payload = {
        "tenant_id": str(tenant_id),
        "agent_id": str(agent_id),
        "redirect_uri": redirect_uri,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        "iat": datetime.now(timezone.utc),
        "jti": str(uuid4()),
        "purpose": "slack_oauth_state",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_oauth_state(state: str) -> Dict[str, Any]:
    """
    Verify and decode signed JWT state parameter.
    Raises ValueError on expired or forged state.
    """
    settings = get_settings()
    secret = getattr(settings, "secret_key", "default-jwt-secret")
    try:
        payload = jwt.decode(state, secret, algorithms=["HS256"])
        if payload.get("purpose") != "slack_oauth_state":
            raise ValueError("Invalid state purpose")
        if not payload.get("tenant_id") or not payload.get("agent_id"):
            raise ValueError("Missing tenant_id or agent_id in state")
        return payload
    except JWTError as e:
        raise ValueError(f"Invalid or expired OAuth state parameter: {e}") from e


def verify_slack_signature(
    request_body: bytes,
    timestamp: Optional[str],
    signature: Optional[str],
    signing_secret: Optional[str] = None,
) -> bool:
    """
    Verify HMAC-SHA256 signature from Slack webhook events.
    Enforces replay attack window of 300 seconds (5 minutes).
    Constant-time comparison via hmac.compare_digest.
    """
    if not timestamp or not signature:
        return False

    # Check replay attack (timestamp drift > 300 seconds)
    try:
        ts_float = float(timestamp)
        now = time.time()
        if abs(now - ts_float) > 300:
            return False
    except (ValueError, TypeError):
        return False

    if not signing_secret:
        settings = get_settings()
        signing_secret = getattr(settings, "slack_signing_secret", None)
        if not signing_secret:
            return False

    # Construct signature base string: v0:{timestamp}:{body}
    sig_basestring = f"v0:{timestamp}:{request_body.decode('utf-8', errors='replace')}".encode("utf-8")
    computed_hash = hmac.new(
        signing_secret.encode("utf-8"),
        sig_basestring,
        hashlib.sha256,
    ).hexdigest()
    expected_signature = f"v0={computed_hash}"

    return hmac.compare_digest(expected_signature, signature)
