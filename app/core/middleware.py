"""Middleware: Tenant context, error handling, logging"""

from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import logging
import uuid
from typing import Optional

from .security import verify_access_token
from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class TenantContextMiddleware(BaseHTTPMiddleware):
    """
    CRITICAL MIDDLEWARE: Extracts JWT token and injects tenant context.

    This MUST run on every request to enforce multi-tenancy.
    Failure = cross-tenant data leakage.

    Extracts:
        - Authorization: Bearer <JWT>
        - Decodes JWT
        - Validates tenant_id and user_id
        - Stores in request.state
        - Sets PostgreSQL app.current_tenant for RLS

    PUBLIC ROUTES (no auth required):
    - POST /auth/signup
    - POST /auth/login
    - GET /docs, /openapi.json, /redoc (Swagger/OpenAPI)
    - GET /health (health check)
    """

    # Routes that don't require authentication
    PUBLIC_ROUTES = {
        ("/api/v1/auth/register", "POST"),
        ("/api/v1/auth/login", "POST"),
        ("/api/v1/auth/refresh", "POST"),
        ("/api/v1/auth/send-registration-otp", "POST"),
        ("/api/v1/auth/forgot-password", "POST"),
        ("/api/v1/auth/reset-password", "POST"),
        ("/docs", "GET"),
        ("/openapi.json", "GET"),
        ("/redoc", "GET"),
        ("/health", "GET"),
        ("/", "GET"),
    }

    async def dispatch(self, request: Request, call_next):
        # ============= CHECK IF ROUTE IS PUBLIC =============
        route_key = (request.url.path, request.method)
        if (
            route_key in self.PUBLIC_ROUTES 
            or request.url.path.startswith("/api/v1/embed")
            or "/sharepoint/login" in request.url.path
            or "/sharepoint/callback" in request.url.path
        ):
            logger.debug(f"Public/Embed/Auth route: {request.method} {request.url.path}")
            return await call_next(request)

        # ============= EXTRACT JWT =============
        auth_header = request.headers.get("Authorization")

        if not auth_header:
            logger.warning(f"No Authorization header: {request.url.path}")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "success": False,
                    "data": None,
                    "error": "Missing Authorization header",
                    "meta": {},
                },
            )

        # ============= PARSE BEARER TOKEN =============
        try:
            scheme, token = auth_header.split()
            if scheme.lower() != "bearer":
                logger.warning(f"Invalid auth scheme: {scheme}")
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={
                        "success": False,
                        "data": None,
                        "error": "Invalid authentication scheme",
                        "meta": {},
                    },
                )
        except ValueError:
            logger.warning("Malformed Authorization header")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "success": False,
                    "data": None,
                    "error": "Malformed Authorization header",
                    "meta": {},
                },
            )

        # ============= VERIFY JWT (with blacklist check) =============
        # Import here to avoid circular imports
        from .database import AsyncSessionLocal

        # Create temporary session for blacklist check
        async with AsyncSessionLocal() as temp_db:
            payload = await verify_access_token(token, db=temp_db)

        if not payload:
            logger.warning("Invalid, expired, or revoked token")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "success": False,
                    "data": None,
                    "error": "Invalid, expired, or revoked token",
                    "meta": {},
                },
            )

        # ============= INJECT INTO REQUEST STATE =============
        request.state.user_id = payload.user_id
        request.state.tenant_id = payload.tenant_id
        request.state.request_id = str(uuid.uuid4())

        logger.info(
            f"Request {request.state.request_id}: {request.method} {request.url.path} "
            f"(tenant: {payload.tenant_id}, user: {payload.user_id})"
        )

        # ============= CONTINUE TO ROUTE =============
        response = await call_next(request)

        # Add request ID to response headers for tracing
        response.headers["X-Request-ID"] = request.state.request_id

        return response


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """
    Catches unhandled exceptions and returns standardized response.

    Format:
        {
            "success": false,
            "data": null,
            "error": "Error message",
            "meta": {"request_id": "..."}
        }
    """

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            request_id = getattr(request.state, "request_id", "unknown")
            logger.error(
                f"Unhandled exception in {request.method} {request.url.path}: {exc}",
                exc_info=True,
                extra={"request_id": request_id},
            )

            try:
                import traceback
                import asyncio
                from app.core.error_logger import log_error_to_db
                
                tenant_id = getattr(request.state, "tenant_id", None)
                user_id = getattr(request.state, "user_id", None)
                stack_trace = traceback.format_exc()
                
                asyncio.create_task(
                    log_error_to_db(
                        module="API",
                        message=str(exc),
                        error_type=type(exc).__name__,
                        stack_trace=stack_trace,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        endpoint=request.url.path,
                        request_metadata={
                            "method": request.method,
                            "request_id": request_id
                        }
                    )
                )
            except Exception as log_err:
                logger.error(f"Failed to dispatch error logger background task: {log_err}")

            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "success": False,
                    "data": None,
                    "error": (
                        "Internal server error" if not settings.debug else str(exc)
                    ),
                    "meta": {"request_id": request_id},
                },
            )


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs HTTP request details for debugging and monitoring.
    """

    async def dispatch(self, request: Request, call_next):
        # Extract tenant for logging
        tenant_id = getattr(request.state, "tenant_id", "unknown")

        # Log request
        logger.debug(
            f"{request.method} {request.url.path}",
            extra={
                "method": request.method,
                "path": request.url.path,
                "tenant_id": tenant_id,
            },
        )

        # Get response
        response = await call_next(request)

        # Log response
        logger.debug(
            f"Response {response.status_code} for {request.method} {request.url.path}",
            extra={
                "status_code": response.status_code,
                "path": request.url.path,
                "tenant_id": tenant_id,
            },
        )

        return response
