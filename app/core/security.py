"""Security utilities: password hashing, JWT tokens, token validation"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from jose import JWTError, jwt
import hashlib
import bcrypt
from pydantic import BaseModel
import logging
import secrets
import time

from .config import get_settings

logger = logging.getLogger(__name__)

# Simple TTL cache to prevent N+1 DB queries on every API request
_blacklist_cache = {}
_BLACKLIST_CACHE_TTL = 300 # 5 minutes
_MAX_CACHE_SIZE = 10000

# ... (Previous imports)

def hash_reset_token(token: str) -> str:
    """
    Hash a plaintext reset token (SHA-256) for secure DB storage.
    
    Args:
        token: Plaintext token generated via secrets.token_urlsafe()
        
    Returns:
        Hexadecimal hash of the token
    """
    return hashlib.sha256(token.encode()).hexdigest()

# ============= STARTUP VALIDATION =============
# This runs when module is imported
import warnings

settings = get_settings()
try:
    settings.validate_jwt_secret()
    settings.validate_cors()
except ValueError as e:
    raise RuntimeError(f"SECURITY VALIDATION FAILED: {e}") from e

def hash_password(password: str) -> str:
    """
    Hash a plaintext password using bcrypt.

    Args:
        password: Plaintext password string

    Returns:
        Hashed password suitable for database storage
    """
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against its hash.

    Args:
        plain_password: User-provided plaintext password
        hashed_password: Hash stored in database

    Returns:
        True if password matches, False otherwise
    """
    pwd_bytes = plain_password.encode('utf-8')
    hash_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(pwd_bytes, hash_bytes)


# ============= JWT TOKEN UTILITIES =============
class TokenPayload(BaseModel):
    """JWT token payload structure"""

    user_id: str
    tenant_id: str
    type: str = "access"  # 'access' or 'refresh'
    exp: datetime
    jti: str  # JWT ID - unique identifier for THIS token (enables revocation/logout)


def create_access_token(
    user_id: str, tenant_id: str, expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token.

    CRITICAL: Always includes tenant_id to prevent cross-tenant attacks.
    CRITICAL: Includes jti (JWT ID) to enable token revocation (logout).

    Args:
        user_id: UUID of the user
        tenant_id: UUID of the tenant
        expires_delta: Custom expiration (defaults to config)

    Returns:
        Encoded JWT token
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.access_token_expire_minutes
        )

    # Generate unique jti for this token (enables revocation)
    jti = secrets.token_urlsafe(32)

    to_encode = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "type": "access",
        "jti": jti,  # CRITICAL: Enables revocation tracking
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }

    encoded_jwt = jwt.encode(
        to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    return encoded_jwt


def create_refresh_token(
    user_id: str, tenant_id: str, expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT refresh token (longer-lived).

    CRITICAL: Includes jti to enable token revocation.

    Args:
        user_id: UUID of the user
        tenant_id: UUID of the tenant
        expires_delta: Custom expiration (defaults to config)

    Returns:
        Encoded JWT refresh token
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            days=settings.refresh_token_expire_days
        )

    # Generate unique jti for this token (enables revocation)
    jti = secrets.token_urlsafe(32)

    to_encode = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "type": "refresh",
        "jti": jti,  # CRITICAL: Enables revocation tracking
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }

    encoded_jwt = jwt.encode(
        to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    return encoded_jwt


async def verify_access_token(
    token: str, db: "AsyncSession" = None
) -> Optional[TokenPayload]:
    """
    Decode and verify a JWT access token.

    CRITICAL:
    1. Verifies token signature and expiry
    2. Checks if token is in blacklist (revoked)
    3. Returns None if ANY check fails

    Args:
        token: JWT token string
        db: Database session (for blacklist check)

    Returns:
        TokenPayload if valid, None if invalid/expired/revoked
    """
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )

        # Validate required fields
        user_id = payload.get("user_id")
        tenant_id = payload.get("tenant_id")
        token_type = payload.get("type", "access")
        jti = payload.get("jti", "")

        if not user_id or not tenant_id:
            logger.warning("Token missing user_id or tenant_id")
            return None

        if token_type != "access":
            logger.warning(f"Expected access token, got {token_type}")
            return None

        # CRITICAL: Check if token is blacklisted (revoked)
        if jti:
            cache_key = f"{tenant_id}:{jti}"
            now = time.time()
            
            # 1. Check in-memory cache first to avoid DB query latency
            if cache_key in _blacklist_cache:
                is_blacklisted, timestamp = _blacklist_cache[cache_key]
                if now - timestamp < _BLACKLIST_CACHE_TTL:
                    if is_blacklisted:
                        logger.warning(f"Token blacklisted (cached): {jti[:20]}...")
                        return None
                    else:
                        # Proceed! It's cached as valid.
                        pass
                else:
                    # Expired, clean it up before DB check
                    del _blacklist_cache[cache_key]

            # 2. Cache miss: Check Database
            if cache_key not in _blacklist_cache:
                from sqlalchemy import select
                from ..modules.auth.models import TokenBlacklist
                
                async def fetch_blacklist(session):
                    result = await session.execute(
                        select(TokenBlacklist).where(
                            (TokenBlacklist.jti == jti)
                            & (TokenBlacklist.tenant_id == tenant_id)
                        )
                    )
                    return result.scalar_one_or_none()

                blacklisted = None
                if db:
                    blacklisted = await fetch_blacklist(db)
                else:
                    from .database import AsyncSessionLocal
                    async with AsyncSessionLocal() as temp_db:
                        blacklisted = await fetch_blacklist(temp_db)
                
                # Update Cache
                if len(_blacklist_cache) > _MAX_CACHE_SIZE:
                    _blacklist_cache.clear()
                
                _blacklist_cache[cache_key] = (blacklisted is not None, now)

                if blacklisted:
                    logger.warning(
                        f"Token blacklisted (revoked): {jti[:20]}... "
                        f"Reason: {blacklisted.reason}"
                    )
                    return None

        return TokenPayload(
            user_id=user_id,
            tenant_id=tenant_id,
            type=token_type,
            jti=jti,
            exp=datetime.fromtimestamp(payload.get("exp"), tz=timezone.utc),
        )
    except JWTError as e:
        logger.warning(f"Invalid JWT token: {e}")
        return None


async def verify_refresh_token(token: str, db=None) -> Optional[TokenPayload]:
    """
    Decode and verify a JWT refresh token, checking against blacklist if db provided.

    Args:
        token: JWT refresh token string
        db: Optional database session for blacklist check

    Returns:
        TokenPayload if valid, None if invalid/expired or blacklisted
    """
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )

        user_id = payload.get("user_id")
        tenant_id = payload.get("tenant_id")
        token_type = payload.get("type")

        if not user_id or not tenant_id:
            logger.warning("Refresh token missing user_id or tenant_id")
            return None

        if token_type != "refresh":
            logger.warning(f"Expected refresh token, got {token_type}")
            return None

        # Check blacklist
        jti = payload.get("jti", "")
        if jti:
            cache_key = f"{tenant_id}:{jti}"
            now = time.time()
            
            if cache_key in _blacklist_cache:
                is_blacklisted, timestamp = _blacklist_cache[cache_key]
                if now - timestamp < _BLACKLIST_CACHE_TTL:
                    if is_blacklisted:
                        logger.warning(f"Refresh token revoked (cached): {jti[:20]}...")
                        return None
                else:
                    del _blacklist_cache[cache_key]
            
            if cache_key not in _blacklist_cache:
                from ..modules.auth.models import TokenBlacklist
                from sqlalchemy import select

                async def fetch_blacklist_refresh(session):
                    result = await session.execute(
                        select(TokenBlacklist).where(
                            (TokenBlacklist.jti == jti)
                            & (TokenBlacklist.tenant_id == tenant_id)
                        )
                    )
                    return result.scalar_one_or_none()

                blacklisted = None
                if db:
                    blacklisted = await fetch_blacklist_refresh(db)
                else:
                    from .database import AsyncSessionLocal
                    async with AsyncSessionLocal() as temp_db:
                        blacklisted = await fetch_blacklist_refresh(temp_db)
                
                if len(_blacklist_cache) > _MAX_CACHE_SIZE:
                    _blacklist_cache.clear()
                
                _blacklist_cache[cache_key] = (blacklisted is not None, now)

                if blacklisted:
                    logger.warning(f"Refresh token revoked (blacklisted): {jti[:20]}...")
                    return None

        return TokenPayload(
            user_id=user_id,
            tenant_id=tenant_id,
            type=token_type,
            exp=datetime.fromtimestamp(payload.get("exp"), tz=timezone.utc),
        )
    except JWTError as e:
        logger.warning(f"Invalid refresh token: {e}")
        return None

# ============= WIDGET VISITOR TOKENS =============
def issue_signed_visitor_token(tenant_id: str, visitor_id: Optional[str] = None) -> str:
    """
    Issue a signed token for an anonymous widget visitor.
    """
    if not visitor_id:
        import uuid
        visitor_id = str(uuid.uuid4())
    
    payload = {
        "visitor_id": visitor_id,
        "tenant_id": tenant_id,
        "type": "widget_visitor",
        "exp": datetime.now(timezone.utc) + timedelta(days=365) # Long lived for returning visitors
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def verify_visitor_token_signature(token: str, expected_tenant: str) -> Optional[str]:
    """
    Verify signature and return visitor_id if valid.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "widget_visitor":
            return None
        if payload.get("tenant_id") != expected_tenant:
            return None
        return payload.get("visitor_id")
    except JWTError:
        return None
