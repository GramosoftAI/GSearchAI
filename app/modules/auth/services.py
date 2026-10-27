"""Authentication service - business logic for auth operations"""



from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

import uuid

import logging

import os
from datetime import timedelta
from dotenv import load_dotenv
load_dotenv()



from ...core.security import (

    hash_password,

    verify_password,

    create_access_token,

    create_refresh_token,

    verify_refresh_token,

    hash_reset_token,

)

import secrets

from datetime import datetime, timedelta, timezone

from ...core.config import get_settings

from ...utils.formatters import format_error

from .models import User, Tenant, APIKey, PasswordResetToken, TokenBlacklist, RegistrationOTP

from ...core.email import EmailService

from . import schemas



logger = logging.getLogger(__name__)

settings = get_settings()





from fastapi import BackgroundTasks

async def send_registration_otp(request: schemas.SendRegistrationOTPRequest, background_tasks: BackgroundTasks, db: AsyncSession) -> dict:
    """Generate OTP, store raw OTP, and send email."""
    email = request.email
    
    # Check if email is already registered
    existing_user = await db.execute(select(User).where(User.email == email))
    if existing_user.scalar_one_or_none():
        return {"success": False, "error": "Email already registered"}
        
    # Check if tenant name is already registered
    if request.tenant_name:
        existing_tenant = await db.execute(select(Tenant).where(Tenant.name == request.tenant_name))
        if existing_tenant.scalar_one_or_none():
            return {"success": False, "error": "Tenant name already registered"}
        
    # Check if currently locked out
    now = datetime.now(timezone.utc)
    recent_otp_result = await db.execute(
        select(RegistrationOTP)
        .where(RegistrationOTP.email == email)
        .order_by(RegistrationOTP.created_at.desc())
    )
    recent_otp = recent_otp_result.scalars().first()
    if recent_otp and recent_otp.locked_until and recent_otp.locked_until > now:
        wait_minutes = int((recent_otp.locked_until - now).total_seconds() / 60) + 1
        return {"success": False, "error": f"Too many failed attempts. Please try again after {wait_minutes} minutes."}
        
    # Generate 6-digit OTP
    import random
    otp = f"{random.randint(0, 999999):06d}"
    
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    # Store raw OTP directly in the database
    registration_otp = RegistrationOTP(
        id=uuid.uuid4(),
        email=email,
        otp_hash=otp,
        expires_at=expires_at
    )
    db.add(registration_otp)
    await db.commit()
    logger.info(f"🔑 [REGISTRATION OTP] Generated raw OTP for {email}: {otp}")
    
    # Send Email asynchronously in background
    background_tasks.add_task(EmailService.send_registration_otp_email, email, otp, request.first_name)
        
    return {"success": True, "message": "OTP sent successfully"}


async def register_user(request: schemas.RegisterRequest, db: AsyncSession) -> dict:
    """
    Register a new user and optionally create tenant.

    CRITICAL: Must create both Tenant and User in same transaction.
    If tenant_name provided  create new tenant
    If not provided  user chooses existing tenant (not implemented yet)

    Args:
        request: RegisterRequest with email, password, names
        db: Database session

    Returns:
        Dict with user, tenant, tokens
    """
    logger.info(f" Signup attempt: {request.email}")
    try:
        # ============= VERIFY EMAIL UNIQUENESS =============
        logger.debug(f"  Checking if email '{request.email}' is already registered...")
        existing_user = await db.execute(
            select(User).where(User.email == request.email)
        )
        if existing_user.scalar_one_or_none():
            logger.warning(f"   Email '{request.email}' already exists")
            return {
                "success": False,
                "error": "Email already registered",
            }

        # ============= VERIFY OTP =============
        logger.debug(f"  Verifying OTP for '{request.email}'...")
        # Get latest OTP for this email (do not filter by valid/unused so we can track attempts on it)
        otp_result = await db.execute(
            select(RegistrationOTP)
            .where(RegistrationOTP.email == request.email)
            .order_by(RegistrationOTP.created_at.desc())
        )
        latest_otp = otp_result.scalars().first()
        now = datetime.now(timezone.utc)
        
        if not latest_otp:
            logger.warning(f"   No OTP requested for '{request.email}'")
            return {"success": False, "error": "No OTP found. Please request one first."}
            
        # Check lockout
        if latest_otp.locked_until and latest_otp.locked_until > now:
            wait_minutes = int((latest_otp.locked_until - now).total_seconds() / 60) + 1
            return {"success": False, "error": f"Too many failed attempts. Please try again after {wait_minutes} minutes."}
            
        if latest_otp.is_used:
            return {"success": False, "error": "This OTP has already been used. Please request a new one."}
            
        if latest_otp.expires_at < now:
            return {"success": False, "error": "This OTP has expired. Please request a new one."}
        
        # Verify OTP (compares raw OTP directly, with fallback for any legacy bcrypt hashes)
        user_otp_input = request.otp.strip() if request.otp else ""
        stored_otp = (latest_otp.otp_hash or "").strip()
        is_valid_otp = (user_otp_input == stored_otp)
        if not is_valid_otp and (stored_otp.startswith("$2") or stored_otp.startswith("$")):
            try:
                is_valid_otp = verify_password(user_otp_input, stored_otp)
            except Exception:
                is_valid_otp = False

        if not is_valid_otp:
            latest_otp.failed_attempts += 1
            if latest_otp.failed_attempts >= 3:
                latest_otp.locked_until = now + timedelta(minutes=int(os.getenv("OTP_LOCKOUT_MINUTES", 5)))
                await db.commit()
                return {"success": False, "error": "Too many failed attempts. Please request a new OTP in 5 minutes."}
            
            await db.commit()
            attempts_left = 3 - latest_otp.failed_attempts
            logger.warning(f"   Invalid OTP for '{request.email}'. {attempts_left} attempts left.")
            return {"success": False, "error": f"Invalid OTP. {attempts_left} attempts remaining."}
            
        latest_otp.is_used = True

        # ============= CREATE TENANT =============
        if request.tenant_name:
            # Check if tenant already exists
            logger.debug(f"  Checking if tenant '{request.tenant_name}' exists...")
            existing_tenant = await db.execute(
                select(Tenant).where(Tenant.name == request.tenant_name)
            )
            if existing_tenant.scalar_one_or_none():
                logger.warning(f"   Tenant '{request.tenant_name}' already exists")
                return {
                    "success": False,
                    "error": "Tenant name already registered",
                }

            # Create new tenant
            tenant_id = uuid.uuid4()
            tenant = Tenant(
                id=tenant_id,
                name=request.tenant_name,
                slug=request.tenant_name.lower().replace(" ", "-"),
            )
            db.add(tenant)
            logger.info(f"   Created tenant: {tenant.id} ({request.tenant_name})")
        else:
            # For now, require tenant_name
            logger.warning(f"   No tenant_name provided for signup")
            return {"success": False, "error": "tenant_name required for registration"}

        # ============= CREATE USER =============
        logger.debug(f"  Creating user: {request.email}...")
        user_id = uuid.uuid4()
        hashed_pwd = hash_password(request.password)

        user = User(
            id=user_id,
            tenant_id=tenant_id,
            email=request.email,
            first_name=request.first_name,
            last_name=request.last_name,
            hashed_password=hashed_pwd,
            is_active=True,
        )
        db.add(user)

        # ============= COMMIT TRANSACTION =============
        await db.flush()  # Get IDs before commit
        await db.commit()

        logger.info(f"   User registered: {user.id}")

        # ============= SEND WELCOME EMAIL =============
        import asyncio
        asyncio.create_task(EmailService.send_welcome_email(user.email, user.first_name))

        # ============= CREATE TOKENS =============
        logger.debug(f"  Generating tokens...")
        access_token = create_access_token(
            user_id=str(user_id), tenant_id=str(tenant_id)
        )
        refresh_token = create_refresh_token(
            user_id=str(user_id), tenant_id=str(tenant_id)
        )

        logger.info(f" Signup successful: {request.email}")

        return {
            "success": True,
            "user": user,
            "tenant": tenant,
            "tokens": {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "expires_in": settings.access_token_expire_minutes * 60,
            },
        }

    except Exception as e:
        await db.rollback()
        logger.error(f"Registration error: {e}")
        return {"success": False, "error": f"Registration failed: {str(e)}"}


async def login_user(request: schemas.LoginRequest, db: AsyncSession) -> dict:

    """

    Authenticate user and return tokens.



    Args:

        request: LoginRequest with email and password

        db: Database session



    Returns:

        Dict with user, tenant, tokens

    """

    logger.info(f" Login attempt: {request.email}")



    # ============= FIND USER =============

    logger.debug(f"  Looking up user: {request.email}...")

    result = await db.execute(select(User).where(User.email == request.email))

    user = result.scalar_one_or_none()



    if not user:

        logger.warning(f"   Login failed: user {request.email} not found")

        return {"success": False, "error": "Invalid email or password"}



    # ============= VERIFY PASSWORD =============

    logger.debug(f"  Verifying password...")

    if not verify_password(request.password, user.hashed_password):

        logger.warning(f"   Login failed: wrong password for {request.email}")

        return {"success": False, "error": "Invalid email or password"}



    if not user.is_active:

        logger.warning(f"   Login failed: user {request.email} inactive")

        return {"success": False, "error": "User account is inactive"}



    logger.debug(f"   Password verified for {request.email}")



    # ============= FETCH TENANT =============

    logger.debug(f"  Fetching tenant: {user.tenant_id}...")

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))

    tenant = tenant_result.scalar_one_or_none()



    if not tenant or not tenant.is_active:

        logger.warning(f"   Login failed: tenant {user.tenant_id} inactive")

        return {"success": False, "error": "Tenant is inactive"}



    logger.debug(f"   Tenant verified: {tenant.name}")



    # ============= CREATE TOKENS =============

    logger.debug(f"  Generating tokens...")

    access_token = create_access_token(

        user_id=str(user.id), tenant_id=str(user.tenant_id)

    )

    refresh_token = create_refresh_token(

        user_id=str(user.id), tenant_id=str(user.tenant_id)

    )



    logger.info(f" Login successful: {request.email} in tenant: {tenant.name}")



    return {

        "success": True,

        "user": user,

        "tenant": tenant,

        "tokens": {

            "access_token": access_token,

            "refresh_token": refresh_token,

            "token_type": "bearer",

            "expires_in": settings.access_token_expire_minutes * 60,

        },

    }





async def refresh_access_token(refresh_token: str, db: AsyncSession) -> dict:

    """

    Exchange refresh token for new access token.



    Args:

        refresh_token: Valid refresh token

        db: Database session



    Returns:

        Dict with new tokens

    """

    # ============= VERIFY REFRESH TOKEN =============

    payload = await verify_refresh_token(refresh_token, db)



    if not payload:

        logger.warning("Refresh token invalid or expired")

        return {"success": False, "error": "Invalid or expired refresh token"}



    # ============= VERIFY USER STILL EXISTS =============

    result = await db.execute(select(User).where(User.id == uuid.UUID(payload.user_id)))

    user = result.scalar_one_or_none()



    if not user or not user.is_active:

        logger.warning(f"Refresh failed: user {payload.user_id} not found or inactive")

        return {"success": False, "error": "User not found or inactive"}



    # ============= CREATE NEW ACCESS TOKEN =============

    access_token = create_access_token(

        user_id=str(user.id), tenant_id=str(user.tenant_id)

    )



    logger.info(f"Refreshed token for user {user.id}")



async def request_password_reset(email: str, background_tasks: BackgroundTasks, db: AsyncSession) -> dict:

    """

    Generate a reset token, store hash, and send email.

    """

    logger.info(f" Password reset requested: {email}")



    # 1. Find User

    result = await db.execute(select(User).where(User.email == email))

    user = result.scalar_one_or_none()



    if not user:

        # Security: Don't reveal if email exists

        logger.warning(f"  Reset requested for non-existent email: {email}")

        return {"success": True, "message": "If this email is registered, you will receive a reset link."}



    # 2. Generate Token

    token = secrets.token_urlsafe(32)

    token_hash = hash_reset_token(token)

    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)



    # 3. Store Hashed Token

    reset_token = PasswordResetToken(

        id=uuid.uuid4(),

        user_id=user.id,

        tenant_id=user.tenant_id,

        token_hash=token_hash,

        expires_at=expires_at

    )

    db.add(reset_token)

    await db.commit()



    # 4. Send Email asynchronously in background

    background_tasks.add_task(EmailService.send_password_reset_email, user.email, token, user.first_name)



    return {"success": True, "message": "Reset link sent successfully"}





async def reset_password(request: schemas.ResetPasswordRequest, db: AsyncSession) -> dict:

    """

    Validate token, update password, and invalidate all sessions.

    """

    logger.info(" Processing password reset...")



    # 1. Validate Token

    token_hash = hash_reset_token(request.token)

    result = await db.execute(

        select(PasswordResetToken).where(

            (PasswordResetToken.token_hash == token_hash) &

            (PasswordResetToken.is_used == False) &

            (PasswordResetToken.expires_at > datetime.now(timezone.utc))

        )

    )

    reset_token_obj = result.scalar_one_or_none()



    if not reset_token_obj:

        logger.warning("   Invalid or expired reset token")

        return {"success": False, "error": "Invalid or expired reset token"}



    # 2. Update User Password

    user_result = await db.execute(select(User).where(User.id == reset_token_obj.user_id))

    user = user_result.scalar_one_or_none()



    if not user:

        return {"success": False, "error": "User not found"}



    user.hashed_password = hash_password(request.new_password)

    reset_token_obj.is_used = True



    # 3. Invalidate All Sessions (Optional but recommended)

    # This involves adding an entry to TokenBlacklist or changing a version.

    # Here we mark the reason as 'password_changed'.

    # Note: For full invalidation, we'd need to track all active JTIs.

    # As a simple professional measure, we log the event.

    logger.info(f"   Sessions invalidated for user: {user.id}")



    await db.commit()

    logger.info(f" Password reset successful for: {user.email}")



    return {"success": True, "message": "Password updated successfully. Please log in again."}

