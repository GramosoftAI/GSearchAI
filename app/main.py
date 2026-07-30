"""GraphMind FastAPI Application - Main Entry Point



CORE ARCHITECTURE:

    1. Middleware: TenantContextMiddleware (JWT validation)  CRITICAL

    2. Middleware: ErrorHandlingMiddleware (exception handling)

    3. Middleware: LoggingMiddleware (request/response logging)

    4. Routes: Dynamically loaded from app/modules/*/routes.py

    5. Dependencies: Tenant context injected via request.state



REQUEST FLOW:

    Request  TenantContextMiddleware (extract JWT, validate tenant)

            ErrorHandlingMiddleware (catch exceptions)

            LoggingMiddleware (log request)

            Route Handler (use request.state.tenant_id)

            Response



CRITICAL: Never trust client-provided tenant_id. Always extract from JWT.

"""



from fastapi import FastAPI, Request, status

from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import JSONResponse

from contextlib import asynccontextmanager

import importlib

import pkgutil

import logging

import asyncio



from app.core.config import get_settings

from app.core.database import init_db, close_db


from app.core.neo4j import init_neo4j, close_neo4j

from app.core.middleware import (

    TenantContextMiddleware,

    ErrorHandlingMiddleware,

    LoggingMiddleware,

)

from app.core import logging as logging_module  # Import logging module to initialize it



logger = logging.getLogger(__name__)

settings = get_settings()





# ============================================================================

# LIFECYCLE MANAGEMENT

# ============================================================================





@asynccontextmanager

async def lifespan(app: FastAPI):

    """

    Application lifespan: startup and shutdown events.



    Startup:

        - Initialize database (create tables)

        - Load Neo4j driver

        - Load plugins/routers



    Shutdown:

        - Close database connections

        - Close Neo4j driver

    """

    # ============= STARTUP =============

    logger.info("=" * 80)

    logger.info("=" * 80)

    logger.info(f"[STARTUP] Starting {settings.app_name} v{settings.app_version}")

    logger.info(f"[STARTUP] Environment: {settings.app_env.upper()}")

    logger.info(f"[STARTUP] Debug mode: {settings.debug}")

    logger.info(f"[STARTUP] Log level: {settings.log_level}")

    logger.info(

        f"[STARTUP] Database: {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"

    )

    logger.info(f"[STARTUP] Multi-tenancy: ENABLED (RLS ENFORCED)")

    logger.info("=" * 80)



    try:

        # Initialize PostgreSQL

        logger.info("[STARTUP] Initializing PostgreSQL...")

        await init_db()

        logger.info("[STARTUP] PostgreSQL initialized successfully (RLS ENFORCED)")



        # Initialize Neo4j graph database

        logger.info("[STARTUP] Checking Neo4j availability...")

        try:

            await asyncio.wait_for(init_neo4j(), timeout=10.0)

            logger.info("[STARTUP] Neo4j initialized")

        except asyncio.TimeoutError:

            logger.warning(

                f"[STARTUP] Neo4j initialization timed out (>10s). Continuing without graph DB."

            )

        except Exception as e:

            logger.warning(

                f"[STARTUP] Neo4j initialization failed: {e}. Continuing without graph DB."

            )



        logger.info("=" * 80)

        logger.info("[STARTUP] Application startup COMPLETE")

        logger.info(f"[STARTUP] API available at: http://{settings.host}:{settings.port}")

        logger.info(f"[STARTUP] Swagger docs at: http://{settings.host}:{settings.port}/docs")

        logger.info("[STARTUP] MULTI-TENANCY ENFORCED - RLS POLICIES ACTIVE")

        logger.info("=" * 80)



    except Exception as e:

        logger.error("=" * 80)

        logger.error(f"[STARTUP] STARTUP FAILED: {e}")

        logger.error(f"[STARTUP] APPLICATION CANNOT START - RLS enforcement is CRITICAL")

        logger.error("=" * 80)

        raise



    yield  # Application is running



    # ============= SHUTDOWN =============

    logger.info("Shutting down application...")

    try:

        await close_db()

        logger.info(" Database connections closed")



        await close_neo4j()

        logger.info(" Neo4j driver closed")

    except Exception as e:

        logger.error(f"Error during shutdown: {e}")





# ============================================================================

# FASTAPI APPLICATION CREATION

# ============================================================================



app = FastAPI(

    title=settings.app_name,

    version=settings.app_version,

    description="Multi-tenant Graph RAG SaaS Backend",

    lifespan=lifespan,

    docs_url="/docs",

    redoc_url="/redoc",

    openapi_url="/openapi.json",

)





# ============================================================================

# MIDDLEWARE REGISTRATION (ORDER MATTERS!)

# ============================================================================



# IMPORTANT: Middleware is applied in REVERSE order of registration

#

# Do NOT use app.add_middleware() - incorrect order!

# Use app.middleware("http") decorator instead.



# 1. LOGGING MIDDLEWARE (outermost, processes all requests)

app.add_middleware(LoggingMiddleware)



# 2. ERROR HANDLING MIDDLEWARE (catches exceptions)

app.add_middleware(ErrorHandlingMiddleware)



# 3. TENANT CONTEXT MIDDLEWARE (CRITICAL - validates JWT, injects tenant)

app.add_middleware(TenantContextMiddleware)



# 4. CORS MIDDLEWARE (allow cross-origin requests)

app.add_middleware(

    CORSMiddleware,

    allow_origins=settings.cors_origins,

    allow_credentials=settings.cors_credentials,

    allow_methods=settings.cors_methods,

    allow_headers=settings.cors_headers,

)





# ============================================================================

# PUBLIC ENDPOINTS (No auth required)

# ============================================================================





@app.get("/health", tags=["System"])

async def health_check():

    """

    Health check endpoint.



    No authentication required. Used by load balancers.

    """

    return {

        "status": "healthy",

        "app": settings.app_name,

        "version": settings.app_version,

        "environment": settings.app_env,

    }





@app.get("/", tags=["System"])

async def root():

    """Root endpoint - welcome message"""

    return {

        "message": f"Welcome to {settings.app_name}",

        "version": settings.app_version,

        "docs": "/docs",

        "redoc": "/redoc",

    }





# ============================================================================

# DYNAMIC MODULE ROUTER LOADING

# ============================================================================





def load_routers():

    """

    Dynamically discover and load all routers from app/modules/*/routes.py



    Each module must:

        1. Live in app/modules/<module_name>/

        2. Have a routes.py file

        3. Export a 'router' object (FastAPI APIRouter)



    Example module structure:

        app/modules/auth/

         __init__.py

         routes.py       Must export 'router'

         models.py

         schemas.py

         services.py

         dependencies.py



    Usage in routes.py:

        router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])



        @router.post("/login")

        async def login(...):

            ...

    """

    modules_package = "app.modules"

    loaded_count = 0

    failed_count = 0



    try:

        # Import modules package

        modules = importlib.import_module(modules_package)



        # Iterate through subdirectories

        for importer, module_name, ispkg in pkgutil.iter_modules(

            modules.__path__, modules.__name__ + "."

        ):

            if ispkg:  # Only process packages (directories)

                try:

                    # Import routes.py from module

                    router_module_name = f"{module_name}.routes"

                    router_module = importlib.import_module(router_module_name)



                    # Check if router exists

                    if hasattr(router_module, "router"):

                        router = router_module.router

                        app.include_router(router)



                        logger.info(f"[OK] Loaded router from: {module_name}")

                        loaded_count += 1

                    else:

                        logger.warning(f"[WARN] No 'router' found in {router_module_name}")

                        failed_count += 1



                except ImportError as e:

                    logger.error(f"[ERROR] Failed to import {router_module_name}: {e}")

                    failed_count += 1

                except Exception as e:

                    logger.error(

                        f"[ERROR] Error loading module {module_name}: {e}", exc_info=True

                    )

                    failed_count += 1



    except ImportError as e:

        logger.error(f"[ERROR] Failed to import modules package: {e}")

        raise



    logger.info(

        f"Module loading complete: {loaded_count} loaded, {failed_count} failed"

    )



    return loaded_count, failed_count





# Load all routers on startup

try:

    loaded_count, failed_count = load_routers()

    if failed_count > 0:

        logger.warning(f"[WARN] {failed_count} modules failed to load")

except Exception as e:

    logger.error(f"[ERROR] Critical error loading routers: {e}")

    raise





# ============================================================================

# ERROR HANDLING

# ============================================================================





from fastapi.exceptions import RequestValidationError

from starlette.exceptions import HTTPException as StarletteHTTPException



@app.exception_handler(RequestValidationError)

async def validation_exception_handler(request: Request, exc: RequestValidationError):

    """

    Handle FastAPI Pydantic validation errors globally.

    Formats array of dicts into simple {"success": false, "message": "friendly message"}.

    """

    errors = exc.errors()

    msg = "Validation failed"

    if errors:

        err = errors[0]

        raw_msg = err.get("msg", "")

        loc = err.get("loc", [])

        

        # Clean up standard Pydantic messages for a user-friendly format

        if "Value error, " in raw_msg:

            msg = raw_msg.replace("Value error, ", "")

        elif "String should have at least" in raw_msg and "password" in loc:

            msg = "Password must contain at least 8 characters"

        elif "valid email" in raw_msg.lower():

            msg = "Invalid email address"

        elif "Field required" in raw_msg:

            field = str(loc[-1]) if loc else "Field"

            msg = f"{field.title().replace('_', ' ')} is required"

        else:

            msg = raw_msg



    return JSONResponse(

        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,

        content={

            "success": False,

            "message": msg

        },

    )



@app.exception_handler(StarletteHTTPException)

async def http_exception_handler(request: Request, exc: StarletteHTTPException):

    """

    Handle HTTPExceptions globally.

    Ensures consistent {"success": false, "message": "..."} format.

    """

    # Some Fastapi internal exceptions return a dict for detail, check for that

    if isinstance(exc.detail, dict) and "message" in exc.detail:

        message = exc.detail["message"]

    else:

        message = str(exc.detail)

        

    return JSONResponse(

        status_code=exc.status_code,

        content={

            "success": False,

            "message": message

        },

    )



@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler for unhandled exceptions.

    Returns standardized error response.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    tenant_id = getattr(request.state, "tenant_id", "unknown")

    logger.error(
        f"Unhandled exception: {exc}",
        exc_info=True,
        extra={
            "request_id": request_id,
            "tenant_id": tenant_id,
            "path": request.url.path,
        },
    )

    try:
        import traceback
        import asyncio
        from app.core.error_logger import log_error_to_db
        
        user_id = getattr(request.state, "user_id", None)
        stack_trace = traceback.format_exc()
        
        asyncio.create_task(
            log_error_to_db(
                module="API",
                message=str(exc),
                error_type=type(exc).__name__,
                stack_trace=stack_trace,
                tenant_id=tenant_id if tenant_id != "unknown" else None,
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
            "error": "Internal server error" if not settings.debug else str(exc),
            "meta": {"request_id": request_id},
        },
    )





# ============================================================================

# DEVELOPMENT ONLY: Print routes

# ============================================================================



if settings.debug:



    @app.on_event("startup")

    async def print_routes():

        """Print all registered routes (debug only)"""

        logger.debug("=" * 80)

        logger.debug("REGISTERED ROUTES:")

        logger.debug("=" * 80)



        for route in app.routes:

            if hasattr(route, "methods"):

                methods = ",".join(sorted(route.methods))

                logger.debug(f"{methods:10} {route.path}")



        logger.debug("=" * 80)





# ============================================================================

# ENTRY POINT

# ============================================================================



if __name__ == "__main__":

    import uvicorn



    uvicorn.run(

        "app.main:app",

        host=settings.host,

        port=settings.port,

        reload=settings.debug,

        log_level="debug" if settings.debug else "info",

    )

# Harmless comment to trigger uvicorn reload


