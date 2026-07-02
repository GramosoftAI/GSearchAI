"""Neo4j graph database setup for RAG (retrieval-augmented generation)

Neo4j stores:
- Knowledge graph (entities, relationships, documents)
- Agent reasoning chains
- Entity relationships for context retrieval

PostgreSQL stores:
- User/tenant data (RLS-protected)
- API keys, audit logs
- Billing, analytics

Together they form the complete system.
"""

from neo4j import AsyncDriver, AsyncSession as Neo4jAsyncSession, AsyncGraphDatabase
from neo4j import basic_auth
import logging
from typing import Optional
from contextlib import asynccontextmanager

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ============= DRIVER (SINGLETON) =============
_driver: Optional[AsyncDriver] = None


async def get_neo4j_driver() -> AsyncDriver:
    """
    Get or create Neo4j driver (singleton).

    CRITICAL: Driver should be created once per application.
    Connection pooling handled by driver.
    """
    global _driver

    if _driver is None:
        logger.info(f"Connecting to Neo4j: {settings.neo4j_uri}")

        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=basic_auth(settings.neo4j_user, settings.neo4j_password),
            max_connection_pool_size=settings.neo4j_pool_size,
            connection_timeout=30,
        )

        # Test connection
        try:
            await _driver.verify_connectivity()
            logger.info("Neo4j connection verified")
        except Exception as e:
            logger.error(f"Neo4j connection failed: {e}")
            raise

    return _driver


async def get_neo4j_session() -> Neo4jAsyncSession:
    """
    Get async Neo4j session for queries.

    Usage:
        async with await get_neo4j_session() as session:
            result = await session.run("MATCH (n) RETURN n LIMIT 1")
    """
    driver = await get_neo4j_driver()
    return driver.session()


@asynccontextmanager
async def get_neo4j_context():
    """
    Context manager for Neo4j session.

    Usage:
        async with get_neo4j_context() as session:
            result = await session.run("MATCH (n) RETURN n")
    """
    session = await get_neo4j_session()
    try:
        yield session
    finally:
        await session.close()


async def init_neo4j():
    """
    Initialize Neo4j schema on startup (CRITICAL FOR PHASE 2).

    Uses Neo4jSchemaInitializer to create:
    - UNIQUE constraints on all node IDs
    - NOT NULL constraints on tenant_id (CRITICAL for multi-tenancy)
    - Single indexes for tenant isolation (tenant_id on all nodes)
    - Composite indexes for performance ((tenant_id, agent_id), etc.)
    - Vector index for embeddings (semantic search in RAG)

    CRITICAL CONTROLS:
    1. Every node MUST have tenant_id (enforced by constraint)
    2. Every query MUST filter by tenant_id (enforced by Neo4jRepository)
    3. Cross-tenant data access is IMPOSSIBLE (both layers prevent it)

    Called during application startup.
    Fails if Neo4j is not available or schema cannot be created.
    """
    try:
        # Import here to avoid circular imports
        from pathlib import Path
        import sys
        import importlib.util

        # Load the Neo4jSchemaInitializer from scripts/neo4j_init.py
        script_path = Path(__file__).parent.parent.parent / "scripts" / "neo4j_init.py"

        if not script_path.exists():
            logger.error(f"Neo4j schema script not found: {script_path}")
            raise FileNotFoundError(
                f"scripts/neo4j_init.py required for schema initialization"
            )

        # Load module dynamically
        spec = importlib.util.spec_from_file_location("neo4j_init", script_path)
        neo4j_init_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(neo4j_init_module)

        # Initialize schema
        logger.info(" Initializing Neo4j schema (constraints + indexes)...")
        
        # Check if we need to wipe the DB first
        if settings.reset_graph_db_on_start:
            logger.warning(" DANGER: RESET_GRAPH_DB_ON_START is true! Wiping all data in Neo4j...")
            driver = await get_neo4j_driver()
            async with driver.session() as session:
                await session.run("MATCH (n) DETACH DELETE n")
            logger.info(" Neo4j database wiped clean.")
            
        initializer = neo4j_init_module.Neo4jSchemaInitializer(settings)
        await initializer.init_schema()
        logger.info(" Neo4j schema initialized successfully")
        logger.info("    Unique ID constraints created")
        logger.info("    NOT NULL tenant_id constraints created (CRITICAL)")
        logger.info("    Single indexes created (tenant isolation)")
        logger.info("    Composite indexes created (performance)")
        logger.info("    Vector index created (embeddings)")

    except FileNotFoundError as e:
        logger.error(f" Neo4j schema initialization failed: {e}")
        logger.error(f"   Ensure scripts/neo4j_init.py exists")
        raise

    except Exception as e:
        logger.error(f" Neo4j schema initialization failed: {e}")
        logger.error(f"   Multi-tenancy cannot be guaranteed without schema")
        raise


async def close_neo4j():
    """
    Close Neo4j driver on shutdown.

    Called during application shutdown.
    """
    global _driver

    if _driver:
        await _driver.close()
        _driver = None
        logger.info("Neo4j driver closed")


# ============= QUERY PATTERNS =============
"""
MULTI-TENANCY IN NEO4J:

Every node MUST have tenant_id property for isolation:

    MATCH (e:Entity {tenant_id: $tenant_id})
    RETURN e

If developer forgets tenant_id filter  returns all tenants (BAD)
Database-level enforcement not available (unlike PostgreSQL RLS)

SOLUTION: 
1. Use repository pattern (like we do for PostgreSQL)
2. Repository enforces tenant_id in all queries
3. Code review to catch tenant_id escapes

EXAMPLE - Creating an entity:

    async with await get_neo4j_context() as session:
        result = await session.run(
            '''
            CREATE (e:Entity {{
                tenant_id: $tenant_id,
                id: $id,
                name: $name,
                created_at: timestamp()
            }})
            RETURN e
            ''',
            tenant_id=tenant_id,
            id=str(uuid4()),
            name=name
        )

EXAMPLE - Querying entities:

    async with await get_neo4j_context() as session:
        result = await session.run(
            '''
            MATCH (e:Entity {tenant_id: $tenant_id})
            WHERE e.name CONTAINS $search
            RETURN e
            LIMIT 100
            ''',
            tenant_id=tenant_id,
            search=search_term
        )
        
        return [record['e'] for record in result]
"""
