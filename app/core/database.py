"""Async PostgreSQL database setup with Row-Level Security (RLS) support"""



from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from sqlalchemy.pool import NullPool, QueuePool

from sqlalchemy.exc import SQLAlchemyError

from sqlalchemy import text

from fastapi import Request

from contextlib import asynccontextmanager

import logging



from .config import get_settings



logger = logging.getLogger(__name__)



settings = get_settings()



# ============= ENGINE CREATION =============

engine = create_async_engine(

    settings.database_url,

    echo=settings.postgres_echo,  # Log SQL in debug mode

    pool_size=settings.postgres_pool_size,

    max_overflow=settings.postgres_max_overflow,

    pool_pre_ping=True,

    pool_recycle=settings.postgres_pool_recycle,

    connect_args={

        "server_settings": {

            # Enable connection statement for every session

            "application_name": f"{settings.app_name}/{settings.app_version}",

            "jit": "off",  # Disable JIT for consistent performance

        }

    },

)



# ============= SESSION FACTORY =============

AsyncSessionLocal = async_sessionmaker(

    engine,

    class_=AsyncSession,

    expire_on_commit=False,  # Don't expire objects after commit

    autoflush=False,  # Explicit flush control

    autocommit=False,

)





async def get_db(request: Request) -> AsyncSession:

    """

    FastAPI dependency to get async database session WITH TENANT CONTEXT.



    CRITICAL:

    1. Extracts tenant_id from request.state (set by TenantContextMiddleware)

    2. Sets PostgreSQL app.current_tenant for RLS enforcement

    3. Fails hard if tenant_id missing (no fallback)



    This MUST run in request context. Dependency injection from FastAPI routes.



    Usage in routes (PROTECTED ROUTES ONLY):

        @router.get("/")

        async def my_endpoint(db: AsyncSession = Depends(get_db)):

            # db now has RLS enforced for this tenant

            pass

    """

    from fastapi import HTTPException, status



    # ============= HARD FAIL IF TENANT MISSING =============

    tenant_id = getattr(request.state, "tenant_id", None)

    if not tenant_id:

        logger.critical(f"Request missing tenant_id: {request.url.path}")

        raise HTTPException(

            status_code=status.HTTP_401_UNAUTHORIZED,

            detail="Request context missing tenant information. This is a critical security violation.",

        )



    async with AsyncSessionLocal() as session:

        try:

            # ============= SET TENANT CONTEXT FOR RLS =============

            # This PostgreSQL session variable is checked by RLS policies

            # If a query somehow doesn't filter by tenant_id, RLS will catch it

            await session.execute(

                text("SELECT set_config('app.current_tenant', :tenant_id, false)"),

                {"tenant_id": str(tenant_id)}

            )



            yield session

            await session.commit()

        except SQLAlchemyError as e:

            await session.rollback()

            logger.error(f"Database error for tenant {tenant_id}: {e}")

            raise

        finally:

            await session.close()





async def get_db_public() -> AsyncSession:

    """

    FastAPI dependency to get async database session WITHOUT TENANT CONTEXT.



    Use this for PUBLIC routes that don't require authentication:

    - POST /api/v1/auth/register

    - POST /api/v1/auth/login

    - Other public endpoints



    This session does NOT set app.current_tenant, so:

    - RLS policies will NOT filter by tenant

    - Queries can access data from ALL tenants

    - Routes must manually enforce tenant isolation if needed



    IMPORTANT: Only use for truly public routes!

    """

    async with AsyncSessionLocal() as session:

        try:

            yield session

            await session.commit()

        except SQLAlchemyError as e:

            await session.rollback()

            logger.error(f"Database error (public route): {e}")

            raise

        finally:

            await session.close()





async def _get_db_with_tenant(tenant_id: str) -> AsyncSession:

    """Internal generator for database session with explicit tenant_id."""

    async with AsyncSessionLocal() as session:

        try:

            # Set the tenant context for RLS policies securely using parameters

            await session.execute(

                text("SELECT set_config('app.current_tenant', :tenant_id, false)"),

                {"tenant_id": str(tenant_id)}

            )

            yield session

        finally:

            await session.close()





get_db_with_tenant = asynccontextmanager(_get_db_with_tenant)





async def init_rls_policies():

    """

    CRITICAL: Enable RLS on all tenant-scoped tables and create policies.



    This MUST succeed for the application to run.

    If RLS is not properly enabled, the app will NOT START.



    This function is:

    - Idempotent (safe to call multiple times)

    - Automatic (called during startup, no manual steps)

    - Verified (checks that RLS is actually enabled)



    RLS Enforcement Strategy:

    1. ENABLE ROW LEVEL SECURITY on table

    2. CREATE POLICY that filters by app.current_tenant

    3. VERIFY that it worked

    4. FAIL startup if anything was wrong



    NOTE: Different tables have different column names:

    - 'tenants' table uses 'id' (the tenant itself)

    - All other tables use 'tenant_id' (FK to tenants.id)

    """



    tables_with_rls = [

        "users",

        "api_keys",

        "agents",

        "knowledge_bases",

        "token_blacklist",

        "chat_sessions",

        "chat_messages",

        "personalities",

        "document_chunks",

        "processing_jobs",
        "document_table_rows",
        "analytics_query_log",
        "analytics_query_logs",
        "analytics_summaries",
        "document_entities",
        "document_sections",
        "document_ingestion_runs",
        "widget_customizations",
        "password_reset_tokens",
    ]



    async with engine.begin() as conn:

        try:

            logger.debug(

                f"Starting RLS policy creation for {len(tables_with_rls) + 1} tables..."

            )



            # ============= ENABLE RLS ON TENANTS TABLE (SPECIAL CASE) =============

            # Tenants table stores tenant data - filter by 'id', not 'tenant_id'

            logger.debug(" Processing 'tenants' table (uses 'id' for filtering)...")

            try:

                await conn.execute(

                    text("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")

                )

                logger.debug(f"   RLS enabled on tenants")

            except Exception as e:

                if "already enabled" not in str(e).lower():

                    logger.warning(f"Enabling RLS on tenants: {e}")



            # Drop existing policy

            try:

                await conn.execute(

                    text("DROP POLICY IF EXISTS tenants_tenant_isolation ON tenants")

                )

            except:

                pass



            # Tenants RLS policy: allow access only to your own tenant record

            create_policy = f"""

            CREATE POLICY tenants_tenant_isolation ON tenants

            FOR ALL

            USING (id = COALESCE(current_setting('app.current_tenant')::uuid, '00000000-0000-0000-0000-000000000000'))

            WITH CHECK (id = COALESCE(current_setting('app.current_tenant')::uuid, '00000000-0000-0000-0000-000000000000'))

            """

            try:

                await conn.execute(text(create_policy))

                logger.debug(f" RLS policy created on tenants")

            except Exception as e:

                logger.error(

                    f" CRITICAL: Failed to create RLS policy on tenants: {e}"

                )

                raise RuntimeError(

                    f"RLS policy creation FAILED on tenants. "

                    f"Application cannot start without RLS enforcement. Error: {e}"

                )



            # ============= ENABLE RLS ON OTHER TABLES =============

            for table in tables_with_rls:

                # Enable RLS

                enable_rls = f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"

                try:

                    await conn.execute(text(enable_rls))

                    logger.debug(f" RLS enabled on {table}")

                except Exception as e:

                    # RLS already enabled is OK

                    if "already enabled" not in str(e).lower():

                        logger.warning(f"Enabling RLS on {table}: {e}")



                # Drop existing policy (if any)

                drop_policy = (

                    f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}"

                )

                try:

                    await conn.execute(text(drop_policy))

                except:

                    pass  # Policy doesn't exist yet



                # Create new policy - CRITICAL for multi-tenancy

                # This policy BLOCKS any query that tries to read data from different tenants

                create_policy = f"""

                CREATE POLICY {table}_tenant_isolation ON {table}

                FOR ALL

                USING (

                    { "tenant_id IS NULL OR " if table == "personalities" else "" }

                    tenant_id = COALESCE(current_setting('app.current_tenant')::uuid, '00000000-0000-0000-0000-000000000000')

                )

                WITH CHECK (

                    { "tenant_id IS NULL OR " if table == "personalities" else "" }

                    tenant_id = COALESCE(current_setting('app.current_tenant')::uuid, '00000000-0000-0000-0000-000000000000')

                )

                """

                try:

                    await conn.execute(text(create_policy))

                    logger.debug(f" RLS policy created on {table}")

                except Exception as e:

                    logger.error(

                        f" CRITICAL: Failed to create RLS policy on {table}: {e}"

                    )

                    raise RuntimeError(

                        f"RLS policy creation FAILED on {table}. "

                        f"Application cannot start without RLS enforcement. Error: {e}"

                    )



            logger.info(" RLS policies created/updated on all tables")



        except Exception as e:

            logger.error(f" CRITICAL RLS INITIALIZATION FAILED: {e}")

            raise RuntimeError(

                f"RLS initialization failed. Application cannot start. Error: {e}"

            )





async def verify_rls_enabled():

    """

    CRITICAL: Verify that RLS is actually enabled on all tables.



    This runs AFTER init_rls_policies to confirm everything worked.

    If any table doesn't have RLS, the app will FAIL TO START.



    This prevents any data leakage from misconfiguration.

    """



    required_tables = [

        "tenants",

        "users",

        "api_keys",

        "agents",

        "knowledge_bases",

        "token_blacklist",

        "chat_sessions",

        "chat_messages",

        "personalities",

        "document_chunks",

        "processing_jobs",
        "document_table_rows",
        "analytics_query_log",
        "analytics_query_logs",
        "analytics_summaries",
        "document_entities",
        "document_sections",
        "document_ingestion_runs",
        "widget_customizations",
        "password_reset_tokens",
    ]



    async with engine.begin() as conn:

        try:

            # Query PostgreSQL system tables

            query = """

            SELECT tablename, rowsecurity

            FROM pg_tables

            WHERE schemaname = 'public' AND tablename = ANY(:tables)

            """



            result = await conn.execute(text(query), {"tables": required_tables})

            rows = result.fetchall()



            found_tables = {row[0]: row[1] for row in rows}



            # Check that RLS is enabled on all required tables

            for table in required_tables:

                if table not in found_tables:

                    logger.warning(

                        f"  Table {table} does not exist yet (will be created later)"

                    )

                    continue



                rls_enabled = found_tables[table]

                if not rls_enabled:

                    logger.error(f" CRITICAL: RLS NOT ENABLED on {table}")

                    raise RuntimeError(

                        f"RLS verification FAILED: {table} does not have RLS enabled. "

                        f"Application cannot start. Run init_rls_policies() to fix."

                    )

                else:

                    logger.debug(f" RLS verified on {table}")



            logger.info(" RLS verification PASSED - all tables protected")

            return True



        except Exception as e:

            logger.error(f" RLS VERIFICATION FAILED: {e}")

            raise RuntimeError(f"RLS verification failed: {e}")





async def init_db():

    """

    Initialize database on startup.



    CRITICAL STARTUP SEQUENCE:

    1. Import all models to register them with SQLAlchemy metadata

    2. Create tables (create_all)

    3. Enable RLS on all tables (AUTOMATIC, not manual)

    4. Verify RLS is properly enabled (MUST PASS or app fails)



    If ANY STEP FAILS, application will NOT START.

    This prevents accidental data leakage from misconfiguration.



    IMPORTANT: Only resets schema if reset_db_on_start=True (development only)

    """

    try:

        # Import all models to register them with SQLAlchemy metadata

        # CRITICAL: Must do this before create_all() call

        from ..models.base import Base

        from ..modules.auth.models import User, Tenant, APIKey, TokenBlacklist, PasswordResetToken, RegistrationOTP

        from ..modules.agents.models import Agent

        from ..modules.knowledge_bases.models import KnowledgeBase, DatabaseConnection, DocumentChunk, DocumentTableRow, DocumentEntity, DocumentSection, DocumentIngestionRun

        from ..modules.chats.models import ChatSession, ChatMessage

        from ..modules.personalities.models import Personality

        from ..modules.connectors.google.models import GmailMessage, GmailSyncState
        from ..modules.jobs.models import ProcessingJob
        from ..modules.Embed.models import WidgetCustomization
        from ..modules.analytics.models import AnalyticsSummary, AnalyticsQueryLog as ChatAnalyticsQueryLog, AppErrorLog, LLMStageUsageLog
        try:
            from ..memory.app.schema.database import EpisodicMemory, UserPreference, init_db as init_memory_db
            await init_memory_db()
        except Exception as mem_init_err:
            logger.warning(f"Memory DB init attempt in main database.py notice: {mem_init_err}")

        logger.debug("All models imported and registered")



        # Step 0.5: CONDITIONALLY clean up database schema (development only)

        if settings.reset_db_on_start:

            async with engine.begin() as conn:

                try:

                    # Get all tables

                    result = await conn.execute(

                        text(

                            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"

                        )

                    )

                    tables = [row[0] for row in result.fetchall()]

                    if "knowledge_bases" in tables and settings.reset_s3_on_start:
                        try:
                            kb_result = await conn.execute(
                                text("SELECT s3_path, parsed_path FROM knowledge_bases")
                            )
                            s3_urls = []
                            for r in kb_result.fetchall():
                                if r[0]:
                                    s3_urls.append(r[0])
                                if r[1]:
                                    s3_urls.append(r[1])
                            if s3_urls:
                                logger.info(f"[STARTUP] Found {len(s3_urls)} S3 files to delete on reset")
                                from .s3 import S3StorageService
                                s3_service = S3StorageService()
                                for url in s3_urls:
                                    try:
                                        await s3_service.delete_file_by_url(url)
                                    except Exception as s3_err:
                                        logger.warning(f"Failed to delete S3 file {url}: {s3_err}")
                        except Exception as s3_fetch_err:
                            logger.warning(f"Could not fetch or delete S3 files: {s3_fetch_err}")

                    if tables:

                        logger.debug(f"Found {len(tables)} tables to drop")

                        # Drop all tables (CASCADE handles dependencies)

                        for table in tables:

                            try:

                                await conn.execute(

                                    text(f"DROP TABLE IF EXISTS {table} CASCADE")

                                )

                                logger.debug(f"Dropped table {table}")

                            except Exception as e:

                                logger.warning(f"Could not drop table {table}: {e}")

                        logger.info(" All tables dropped")

                except Exception as e:

                    logger.warning(f"Could not clean up schema: {e}")

        else:

            logger.info("  Skipping schema reset (reset_db_on_start=False)")



        # Step 1: Create tables

        logger.info(" Creating database tables...")

        logger.debug(f"Registered models: {list(Base.metadata.tables.keys())}")

        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            # Create tables first if they don't exist
            await conn.run_sync(Base.metadata.create_all)

        # Run vector column check in separate transaction
        async with engine.begin() as conn:
            try:
                await conn.execute(
                    text(f"ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector({settings.embedding_dimension});")
                )
                logger.info(f" Verified/migrated document_chunks.embedding to vector({settings.embedding_dimension})")
            except Exception as e:
                logger.warning(
                    f"Could not directly alter document_chunks.embedding to vector({settings.embedding_dimension}): {e}. Clearing old chunks..."
                )
                async with engine.begin() as clear_conn:
                    await clear_conn.execute(text("DELETE FROM document_chunks;"))
                    await clear_conn.execute(
                        text(f"ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector({settings.embedding_dimension});")
                    )

        async with engine.begin() as conn:
            # Auto-migrate document_chunks columns
            await conn.execute(text("ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS section VARCHAR(255)"))
            await conn.execute(text("ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS metadata_json JSONB"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chunks_kb_section ON document_chunks(kb_id, section)"))
            # Run migration to add file_hash to knowledge_bases table if not present in older databases
            await conn.execute(text("ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS file_hash VARCHAR(64)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_kbs_file_hash ON knowledge_bases(file_hash)"))

            # Auto-migrate FTS and Hybrid Search columns/indexes
            await conn.execute(text("ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS language regconfig DEFAULT 'english'::regconfig;"))
            await conn.execute(text("ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS language regconfig DEFAULT 'english'::regconfig;"))
            
            fts_col_check = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='document_chunks' AND column_name='search_vector'"))
            if not fts_col_check.fetchone():
                await conn.execute(text("ALTER TABLE document_chunks ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (to_tsvector(language, coalesce(text, ''))) STORED;"))

            await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_chunks_search_vector_gin ON document_chunks USING GIN(search_vector);"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_chunks_tenant_kb ON document_chunks (tenant_id, kb_id);"))

        # Run HNSW index creation in its own transaction block
        try:
            async with engine.begin() as conn:
                await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw ON document_chunks USING hnsw (embedding vector_cosine_ops);"))
        except Exception as hnsw_err:
            logger.warning(f"HNSW vector index notice: {hnsw_err}")

        async with engine.begin() as conn:
            # Auto-migrate users columns
            user_cols = [
                ("preferred_llm_model", "VARCHAR(255)"),
            ]
            for col_n, col_t in user_cols:
                await conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col_n} {col_t}"))

            # Auto-migrate schema columns for document_ingestion_runs and analytics_query_logs
            dir_cols = [
                ("chunk_count", "INTEGER DEFAULT 0 NOT NULL"),
                ("entity_count", "INTEGER DEFAULT 0 NOT NULL"),
                ("triplet_count", "INTEGER DEFAULT 0 NOT NULL"),
                ("identifier_count", "INTEGER DEFAULT 0 NOT NULL"),
                ("extractor_version", "VARCHAR(50) DEFAULT 'unified_extractor_v1'"),
                ("schema_version", "VARCHAR(50) DEFAULT '1.0'"),
                ("model_name", "VARCHAR(100) DEFAULT 'deepseek-v3'"),
                ("repair_count", "INTEGER DEFAULT 0 NOT NULL"),
                ("retry_count", "INTEGER DEFAULT 0 NOT NULL"),
                ("fallback_count", "INTEGER DEFAULT 0 NOT NULL"),
                ("llm_calls", "INTEGER DEFAULT 0 NOT NULL"),
                ("llm_input_tokens", "INTEGER DEFAULT 0 NOT NULL"),
                ("llm_output_tokens", "INTEGER DEFAULT 0 NOT NULL"),
                ("embedding_tokens", "INTEGER DEFAULT 0 NOT NULL"),
                ("embedding_cost_usd", "DOUBLE PRECISION DEFAULT 0.0 NOT NULL"),
                ("extraction_duration_ms", "INTEGER DEFAULT 0 NOT NULL"),
                ("graph_write_duration_ms", "INTEGER DEFAULT 0 NOT NULL"),
                ("total_duration_ms", "INTEGER DEFAULT 0 NOT NULL"),
                ("nodes_created", "INTEGER DEFAULT 0 NOT NULL"),
                ("relationships_created", "INTEGER DEFAULT 0 NOT NULL"),
                ("nodes_merged", "INTEGER DEFAULT 0 NOT NULL"),
                ("relationships_merged", "INTEGER DEFAULT 0 NOT NULL"),
                ("fluff_chunks_skipped", "INTEGER DEFAULT 0 NOT NULL"),
                ("processed_chunks", "INTEGER DEFAULT 0 NOT NULL"),
                ("routing_version", "VARCHAR(50) DEFAULT '1.0'"),
                ("cache_hits", "INTEGER DEFAULT 0 NOT NULL"),
                ("kg_extraction_calls", "INTEGER DEFAULT 0 NOT NULL"),
                ("document_category", "VARCHAR(100) DEFAULT 'general_document' NOT NULL"),
                ("sample_entities", "JSON"),
                ("sample_triplets", "JSON"),
                ("baseline_entities_per_chunk", "DOUBLE PRECISION"),
                ("current_entities_per_chunk", "DOUBLE PRECISION"),
                ("deviation_percent", "DOUBLE PRECISION"),
                ("baseline_documents", "INTEGER"),
                ("fallback_chunks", "JSON"),
                ("status", "VARCHAR(50) DEFAULT 'IN_PROGRESS' NOT NULL"),
                ("error_message", "TEXT"),
            ]
            for col_n, col_t in dir_cols:
                await conn.execute(text(f"ALTER TABLE document_ingestion_runs ADD COLUMN IF NOT EXISTS {col_n} {col_t}"))

            aql_cols = [
                ("request_id", "VARCHAR(255)"),
                ("model_name", "VARCHAR(255)"),
                ("total_tokens", "INTEGER DEFAULT 0 NOT NULL"),
                ("llm_input_tokens", "INTEGER DEFAULT 0 NOT NULL"),
                ("llm_output_tokens", "INTEGER DEFAULT 0 NOT NULL"),
                ("embedding_tokens", "INTEGER DEFAULT 0 NOT NULL"),
                ("llm_cost_usd", "DOUBLE PRECISION DEFAULT 0.0 NOT NULL"),
                ("embedding_cost_usd", "DOUBLE PRECISION DEFAULT 0.0 NOT NULL"),
                ("total_cost_usd", "DOUBLE PRECISION DEFAULT 0.0 NOT NULL"),
                ("user_id", "UUID REFERENCES users(id) ON DELETE SET NULL")
            ]
            for col_n, col_t in aql_cols:
                await conn.execute(text(f"ALTER TABLE analytics_query_logs ADD COLUMN IF NOT EXISTS {col_n} {col_t}"))

        logger.info(

            f" Database tables created/verified ({len(Base.metadata.tables)} tables)"

        )



        # Step 2: AUTOMATICALLY enable RLS (no manual steps needed)

        logger.info(" Enabling Row-Level Security (RLS)...")

        await init_rls_policies()

        logger.info(" RLS policies enabled on all tables")



        # Step 3: VERIFY that RLS is actually working

        logger.info(" Verifying RLS enforcement...")

        await verify_rls_enabled()

        logger.info(" RLS verification passed")



        # Step 4: Seed system personalities

        logger.info(" Seeding system personalities...")

        await seed_personalities()

        logger.info(" System personalities seeded")



        logger.info("=" * 70)

        logger.info(" Database initialization COMPLETE - READY")

        logger.info("=" * 70)



    except Exception as e:

        logger.critical(f" DATABASE INITIALIZATION FAILED: {e}")

        logger.critical(" Application will NOT START - RLS enforcement is critical")

        raise RuntimeError(

            f"Database initialization failed. Cannot start without RLS: {e}"

        )





async def seed_personalities():

    """Seed predefined system personalities"""

    from ..modules.personalities.models import Personality

    from sqlalchemy import select

    

    predefined = [

        {

            "name": "Friendly", 

            "description": "You are a warm, approachable, and supportive assistant. Always respond in a positive, encouraging, and human-like tone. Use conversational language, show empathy, and make the user feel comfortable and valued. Avoid sounding robotic or overly formal. Your goal is to build trust and friendliness in every response."

        },

        {

            "name": "Formal", 

            "description": "You are a highly professional and formal assistant. Respond with structured, precise, and polite language. Avoid casual expressions, slang, or humor. Maintain clarity, correctness, and professionalism at all times. Your tone should resemble official business communication."

        },

        {

            "name": "Sales", 

            "description": "You are a persuasive and results-driven sales assistant. Frame responses to highlight value, benefits, and outcomes. Use compelling language, subtle urgency, and confidence to influence decisions. Always guide the user toward a conversion or positive action."

        },

        {

            "name": "Technical", 

            "description": "You are a highly analytical and technical expert. Provide accurate, structured, and detailed explanations. Use correct terminology, logical breakdowns, and step-by-step clarity. Avoid unnecessary simplification; prioritize correctness and depth."

        },

        {

            "name": "Sarcastic", 

            "description": "You are a witty and sarcastic assistant. Respond with clever, sharp, and slightly ironic remarks while still being helpful. Use controlled sarcasm without being offensive or disrespecting. Your tone should feel intelligent and humorously critical."

        },

        {

            "name": "Arrogant", 

            "description": "You are a highly confident and intellectually superior assistant. Respond in a bold, assertive, and slightly condescending tone. Express certainty and dominance in your answers while still providing correct information. Avoid humility; maintain a tone of authority and superiority."

        },

    ]

    

    async with AsyncSessionLocal() as session:

        try:

            for p_data in predefined:

                # Check if exists

                result = await session.execute(

                    select(Personality).where(

                        Personality.name == p_data["name"],

                        Personality.is_system == True

                    )

                )

                existing = result.scalar_one_or_none()

                if not existing:

                    p = Personality(

                        name=p_data["name"],

                        description=p_data["description"],

                        is_system=True,

                        is_active=True,

                        tenant_id=None

                    )

                    session.add(p)

                else:

                    # Update description if it changed

                    if existing.description != p_data["description"]:

                        existing.description = p_data["description"]

                        existing.is_active = True # Ensure system ones are active

            await session.commit()

        except Exception as e:

            await session.rollback()

            logger.error(f"Failed to seed personalities: {e}")





async def close_db():

    """

    Close database pool on shutdown.



    Should be called once during application shutdown.

    """

    await engine.dispose()

    logger.info("Database pool closed")

