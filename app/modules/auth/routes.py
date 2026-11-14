"""Authentication routes: register, login, refresh, API keys"""

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from ...core.database import get_db, get_db_public
from ...utils.formatters import format_success, format_error, format_paginated
from . import services, schemas

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/send-registration-otp", status_code=status.HTTP_200_OK)
async def send_registration_otp(
    request: schemas.SendRegistrationOTPRequest, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_public)
):
    """
    Send OTP for registration email verification.
    """
    result = await services.send_registration_otp(request, background_tasks, db)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=result.get("error")
        )
    return format_success(meta={"message": result.get("message")})


@router.post("/register", status_code=status.HTTP_200_OK)
async def register(
    request: schemas.RegisterRequest, db: AsyncSession = Depends(get_db_public)
):
    """
    Register a new user and create/join tenant.

    Returns access + refresh tokens on success.
    """
    result = await services.register_user(request, db)

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=result.get("error")
        )

    # Convert models to schemas
    user_response = schemas.UserResponse.from_orm(result["user"])
    tenant_response = schemas.TenantResponse.from_orm(result["tenant"])

    login_response = schemas.LoginResponse(
        user=user_response,
        tenant=tenant_response,
        tokens=schemas.TokenResponse(**result["tokens"]),
    )

    return format_success(data=login_response, meta={"action": "registered","message":"User registered successfully"})


@router.post("/login")
async def login(
    request: schemas.LoginRequest, db: AsyncSession = Depends(get_db_public)
):
    """
    Login with email and password.

    Returns user info, tenant info, and tokens.
    """
    result = await services.login_user(request, db)

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=result.get("error")
        )

    # Convert models to schemas
    user_response = schemas.UserResponse.from_orm(result["user"])
    tenant_response = schemas.TenantResponse.from_orm(result["tenant"])

    login_response = schemas.LoginResponse(
        user=user_response,
        tenant=tenant_response,
        tokens=schemas.TokenResponse(**result["tokens"]),
    )

    return format_success(data=login_response, meta={"action": "authenticated","message":"User logged in successfully"})


@router.post("/refresh")
async def refresh_token(
    request: schemas.RefreshTokenRequest, db: AsyncSession = Depends(get_db_public)
):
    """
    Refresh access token using refresh token.

    Returns new access token (refresh token remains same).
    """
    result = await services.refresh_access_token(request.refresh_token, db)

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=result.get("error")
        )

    return format_success(
        data=schemas.TokenResponse(**result["tokens"]),
        meta={"action": "token_refreshed"},
    )


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(
    request: schemas.ForgotPasswordRequest, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_public)
):
    """
    Request a password reset link.
    Generates a secure token, hashes it for storage, and sends it via email.
    """
    result = await services.request_password_reset(request.email, background_tasks, db)
    return format_success(meta={"message": result.get("message")})


@router.post("/reset-password")
async def reset_password(
    request: schemas.ResetPasswordRequest, db: AsyncSession = Depends(get_db_public)
):
    """
    Reset password using a valid token.
    
    Validates the hashed token, updates the password, and invalidates sessions.
    """
    result = await services.reset_password(request, db)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=result.get("error")
        )
    return format_success(meta={"message": result.get("message")})


@router.post("/google")
async def google_auth(
    request: schemas.GoogleAuthRequest, db: AsyncSession = Depends(get_db_public)
):
    """
    Authenticate or register with Google OAuth ID token.

    Returns user info, tenant info, and JWT tokens.
    """
    result = await services.authenticate_google_user(request, db)

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=result.get("error")
        )

    user_response = schemas.UserResponse.from_orm(result["user"])
    tenant_response = schemas.TenantResponse.from_orm(result["tenant"])

    login_response = schemas.LoginResponse(
        user=user_response,
        tenant=tenant_response,
        tokens=schemas.TokenResponse(**result["tokens"]),
    )

    return format_success(
        data=login_response,
        meta={"action": "authenticated", "message": "Google authentication successful"}
    )

