"""Dedicated Security, Crypto, TOTP, and Token handling for SuperAdmin.

CRITICAL:
SuperAdmin tokens are distinct from tenant-user tokens.
They carry is_superadmin=True, explicit roles, and platform permissions,
with no tenant_id confinement.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Tuple
import secrets
import bcrypt
import hmac
import hashlib
import struct
import base64
import time
import ipaddress
import logging
from jose import jwt, JWTError

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

SUPERADMIN_ACCESS_TOKEN_TYPE = "superadmin_access"
SUPERADMIN_REFRESH_TOKEN_TYPE = "superadmin_refresh"
SUPERADMIN_MFA_PENDING_TYPE = "superadmin_mfa_pending"


# ============================================================================
# 1. SECURE PASSWORD & TOKEN HASHING
# ============================================================================

def hash_password(password: str) -> str:
    """Hash plaintext password with bcrypt."""
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plaintext password against bcrypt hash."""
    pwd_bytes = plain_password.encode("utf-8")
    hash_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(pwd_bytes, hash_bytes)


def hash_token(token: str) -> str:
    """SHA-256 hash for secure storage of refresh tokens, session tokens, and reset tokens."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ============================================================================
# 2. TOTP MULTI-FACTOR AUTHENTICATION (RFC 6238 / RFC 4226)
# ============================================================================

def generate_totp_secret() -> str:
    """Generate a 160-bit random base32-encoded secret for TOTP."""
    raw_bytes = secrets.token_bytes(20)
    return base64.b32encode(raw_bytes).decode("utf-8").replace("=", "")


def generate_totp_uri(secret: str, email: str, issuer: str = "GSearchAI") -> str:
    """Generate standard otpauth:// URI for QR code integration."""
    clean_secret = secret.replace(" ", "").upper()
    return f"otpauth://totp/{issuer}:{email}?secret={clean_secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"


def generate_totp_code(secret: str, for_time: Optional[float] = None) -> str:
    """
    Generate standard 6-digit TOTP code according to RFC 6238.
    Pure Python standard library implementation with zero third-party dependencies.
    """
    if for_time is None:
        for_time = time.time()

    counter = int(for_time / 30)
    
    # Pad secret to base32 boundary
    padded_secret = secret.upper()
    missing_padding = len(padded_secret) % 8
    if missing_padding:
        padded_secret += "=" * (8 - missing_padding)

    key = base64.b32decode(padded_secret, casefold=True)
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()

    offset = h[-1] & 0x0F
    code_int = struct.unpack(">I", h[offset : offset + 4])[0] & 0x7FFFFFFF
    code = code_int % 1000000
    return f"{code:06d}"


def verify_totp_code(secret: str, user_code: str, window: int = 1) -> bool:
    """
    Verify user-supplied 6-digit TOTP code against secret.
    Allows clock drift tolerance window of +/- 30 seconds (window=1).
    """
    if not secret or not user_code:
        return False

    clean_code = user_code.strip().replace(" ", "")
    if len(clean_code) != 6 or not clean_code.isdigit():
        return False

    current_time = time.time()
    for step in range(-window, window + 1):
        expected_code = generate_totp_code(secret, for_time=current_time + (step * 30))
        if hmac.compare_digest(expected_code, clean_code):
            return True

    return False


def generate_backup_codes(count: int = 8) -> Tuple[List[str], List[str]]:
    """
    Generate one-time recovery backup codes.
    Returns: (plain_codes, hashed_codes)
    """
    plain_codes: List[str] = []
    hashed_codes: List[str] = []
    for _ in range(count):
        code = f"{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"
        plain_codes.append(code)
        hashed_codes.append(hash_token(code))
    return plain_codes, hashed_codes


# ============================================================================
# 3. IP ALLOWLIST CHECKING
# ============================================================================

def is_ip_allowed(client_ip: Optional[str], allowed_ips: Optional[List[str]]) -> bool:
    """
    Check if incoming client IP address satisfies configured allowlist.
    Supports exact IPs and CIDR subnets (e.g., 10.0.0.0/8, 192.168.1.0/24).
    """
    if not allowed_ips or len(allowed_ips) == 0:
        return True  # No restriction configured

    if not client_ip:
        return False

    try:
        incoming_ip = ipaddress.ip_address(client_ip.strip())
    except ValueError:
        logger.warning(f"Invalid client IP format: {client_ip}")
        return False

    for rule in allowed_ips:
        clean_rule = rule.strip()
        if not clean_rule:
            continue
        try:
            if "/" in clean_rule:
                # CIDR block
                network = ipaddress.ip_network(clean_rule, strict=False)
                if incoming_ip in network:
                    return True
            else:
                # Exact IP
                target_ip = ipaddress.ip_address(clean_rule)
                if incoming_ip == target_ip:
                    return True
        except ValueError:
            logger.warning(f"Malformed IP allowlist rule: {clean_rule}")
            continue

    return False


# ============================================================================
# 4. SUPERADMIN JWT TOKEN ISSUANCE & VERIFICATION
# ============================================================================

def create_superadmin_access_token(
    admin_id: str,
    email: str,
    role: str,
    permissions: Optional[List[str]] = None,
    session_id: Optional[str] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT access token for SuperAdmin authentication."""
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        # Default 8 hours for administrative sessions
        expire = datetime.now(timezone.utc) + timedelta(hours=8)

    jti = secrets.token_urlsafe(32)

    payload: Dict[str, Any] = {
        "sub": str(admin_id),
        "admin_id": str(admin_id),
        "email": email,
        "role": role,
        "permissions": permissions or ["*"],
        "session_id": str(session_id) if session_id else None,
        "is_superadmin": True,
        "type": SUPERADMIN_ACCESS_TOKEN_TYPE,
        "jti": jti,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }

    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_superadmin_refresh_token(
    admin_id: str,
    session_id: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create longer-lived refresh token (e.g., 7 days) tied to a SuperAdmin session."""
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=7)

    jti = secrets.token_urlsafe(32)

    payload: Dict[str, Any] = {
        "sub": str(admin_id),
        "admin_id": str(admin_id),
        "session_id": str(session_id),
        "is_superadmin": True,
        "type": SUPERADMIN_REFRESH_TOKEN_TYPE,
        "jti": jti,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }

    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_mfa_pending_token(
    admin_id: str,
    email: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create short-lived (5 min) token when password passes but second factor is required."""
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=5))
    payload: Dict[str, Any] = {
        "sub": str(admin_id),
        "admin_id": str(admin_id),
        "email": email,
        "is_superadmin": True,
        "type": SUPERADMIN_MFA_PENDING_TYPE,
        "jti": secrets.token_urlsafe(32),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_superadmin_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify a SuperAdmin JWT access token."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )

        if not payload.get("is_superadmin"):
            return None

        if payload.get("type") != SUPERADMIN_ACCESS_TOKEN_TYPE:
            return None

        if not payload.get("admin_id") or not payload.get("email"):
            return None

        return payload
    except JWTError as e:
        logger.warning(f"SuperAdmin access token decode failed: {e}")
        return None


def verify_superadmin_refresh_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify a SuperAdmin refresh token."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        if not payload.get("is_superadmin") or payload.get("type") != SUPERADMIN_REFRESH_TOKEN_TYPE:
            return None
        return payload
    except JWTError:
        return None


def verify_mfa_pending_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify an MFA challenge pending token."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        if not payload.get("is_superadmin") or payload.get("type") != SUPERADMIN_MFA_PENDING_TYPE:
            return None
        return payload
    except JWTError:
        return None
