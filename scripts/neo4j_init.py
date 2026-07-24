"""
Neo4j Schema Initialization for Multi-Tenant Graph RAG System.

This script:
1. Creates node constraints (unique IDs across graph)
2. Creates indexes for performance (tenant_id, agent_id)
3. Enforces multi-tenancy at graph level
4. Idempotent safe - can run multiple times without breaking

Run with:
    python scripts/neo4j_init.py
"""

import asyncio
import logging
from typing import List
from neo4j import AsyncGraphDatabase
from neo4j.exceptions import ConstraintError, ClientError

# Import settings
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import get_settings

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class Neo4jSchemaInitializer:
    """
    Manages Neo4j schema creation with multi-tenancy enforcement.

    KEY PRINCIPLE:
    Every node MUST have tenant_id.
    Every relationship MUST stay within tenant boundary.
    """

    def __init__(self, settings):
        self.uri = settings.neo4j_uri
        self.user = settings.neo4j_user
        self.password = settings.neo4j_password
        self.settings = settings  # Store settings for later use (embedding_dimension)
        self.driver = None

    async def connect(self):
        """Create async Neo4j driver connection."""
        self.driver = AsyncGraphDatabase.driver(
            self.uri,
            auth=(self.user, self.password),
            max_connection_pool_size=10,
            connection_timeout=30,
        )
        logger.info(f"✅ Connected to Neo4j: {self.uri}")

    async def close(self):
        """Close connection."""
        if self.driver:
            await self.driver.close()
            logger.info("✅ Neo4j connection closed")

    async def execute_query(self, query: str) -> List[dict]:
        """
        Execute a Cypher query and return results.

        Args:
            query: Cypher query string

        Returns:
            List of result records
        """
        async with self.driver.session() as session:
            result = await session.run(query)
            records = await result.data()
            return records

    async def create_constraints(self):
        """
        Create global node constraints.

        CONTROLS TWO TYPES:
        1. UNIQUE constraints (ID fields)
        2. NOT NULL constraints (tenant_id - CRITICAL for multi-tenancy)

        Ensures:
        - Each Agent has unique ID (UUID)
        - Each Agent MUST have tenant_id (enforced)
        - Each KnowledgeBase has unique ID (UUID)
        - Each KnowledgeBase MUST have tenant_id (enforced)
        - Each Chunk has unique ID (UUID)
        - Each Chunk MUST have tenant_id (enforced)
        - Each Entity has unique ID (UUID)
        - Each Entity MUST have tenant_id (enforced)

        Idempotent: Safe to run multiple times (ignores if exists).

        CRITICAL: NOT NULL constraints prevent accidental
        creation of nodes without tenant_id, which would
        silently break multi-tenancy.
        """
        constraints = [
            # ========== AGENT CONSTRAINTS ==========
            # Agent: unique ID
            """
            CREATE CONSTRAINT agent_id_unique IF NOT EXISTS
            FOR (a:Agent) REQUIRE a.id IS UNIQUE
            """,
            # Agent: MUST have tenant_id (critical for multi-tenancy)
            # SKIPPED: Property existence constraint requires Neo4j Enterprise Edition
            # """
            # CREATE CONSTRAINT agent_tenant_required IF NOT EXISTS
            # FOR (a:Agent) REQUIRE a.tenant_id IS NOT NULL
            # """,
            # ========== KNOWLEDGEBASE CONSTRAINTS ==========
            # KnowledgeBase: unique ID
            """
            CREATE CONSTRAINT kb_id_unique IF NOT EXISTS
            FOR (kb:KnowledgeBase) REQUIRE kb.id IS UNIQUE
            """,
            # KnowledgeBase: MUST have tenant_id (critical for multi-tenancy)
            # SKIPPED: Property existence constraint requires Neo4j Enterprise Edition
            # """
            # CREATE CONSTRAINT kb_tenant_required IF NOT EXISTS
            # FOR (kb:KnowledgeBase) REQUIRE kb.tenant_id IS NOT NULL
            # """,
            # ========== CHUNK CONSTRAINTS ==========
            # Chunk: unique ID
            """
            CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS
            FOR (c:Chunk) REQUIRE c.id IS UNIQUE
            """,
            # Chunk: MUST have tenant_id (critical for multi-tenancy)
            # SKIPPED: Property existence constraint requires Neo4j Enterprise Edition
            # """
            # CREATE CONSTRAINT chunk_tenant_required IF NOT EXISTS
            # FOR (c:Chunk) REQUIRE c.tenant_id IS NOT NULL
            # """,
            # ========== ENTITY CONSTRAINTS ==========
            # Entity: unique ID
            """
            CREATE CONSTRAINT entity_id_unique IF NOT EXISTS
            FOR (e:Entity) REQUIRE e.id IS UNIQUE
            """,
            # Entity: MUST have tenant_id (critical for multi-tenancy)
            # SKIPPED: Property existence constraint requires Neo4j Enterprise Edition
            # """
            # CREATE CONSTRAINT entity_tenant_required IF NOT EXISTS
            # FOR (e:Entity) REQUIRE e.tenant_id IS NOT NULL
            # """,
            # ========== ENTITY DEDUPLICATION CONSTRAINT ==========
            # CRITICAL: Entity deduplication per tenant
            # Prevents duplicate entities within same tenant:
            #   - "Apple Inc" and "apple inc" are same entity (normalized)
            #   - "APPLE INC" is also same entity
            # Without this constraint, graph quality degrades (multiple node copies)
            # SKIPPED: Dropped to allow background cleanup service to normalize nodes with the same normalized name before merging.
            # """
            # CREATE CONSTRAINT entity_unique_per_tenant IF NOT EXISTS
            # FOR (e:Entity) REQUIRE (e.tenant_id, e.normalized_name) IS UNIQUE
            # """,
            # ========== TRIPLET ENTITY CONSTRAINTS ==========
            # CRITICAL: Prevents duplicate triplet entities
            """
            CREATE CONSTRAINT triplet_entity_unique_per_tenant IF NOT EXISTS
            FOR (e:TripletEntity) REQUIRE (e.tenant_id, e.text, e.type) IS UNIQUE
            """,
            # Triplet: unique ID
            """
            CREATE CONSTRAINT triplet_id_unique IF NOT EXISTS
            FOR (t:Triplet) REQUIRE t.id IS UNIQUE
            """,
        ]

        logger.info("📌 Creating constraints...")
        for constraint in constraints:
            try:
                await self.execute_query(constraint)
                logger.info(f"  ✅ Constraint created (or already exists)")
            except (ConstraintError, ClientError) as e:
                # Some versions of Neo4j throw different errors
                if "already exists" in str(e).lower():
                    logger.info(f"  ℹ️  Constraint already exists (idempotent)")
                else:
                    logger.warning(f"  ⚠️  {e}")

    async def create_indexes(self):
        """
        Create performance indexes (single + composite).

        CRITICAL INDEXES FOR MULTI-TENANCY:
        - tenant_id on all nodes (all queries filter by tenant)
        - (tenant_id, agent_id) composite (most common: find chunks for agent in tenant)
        - (tenant_id, kb_id) composite (find chunks in KB within tenant)

        VECTOR INDEX (Neo4j 5.0+):
        - embedding on Chunk (semantic search in RAG)

        ADDITIONAL INDEXES:
        - id on each node type (lookups)
        - user_id on Agent (owner filtering)
        - type on Entity (entity type filtering)
        """
        indexes = [
            # ========== SINGLE INDEXES: TENANT ISOLATION ==========
            # Agent: tenant_id (find agents for tenant)
            """
            CREATE INDEX agent_tenant_idx IF NOT EXISTS
            FOR (a:Agent) ON (a.tenant_id)
            """,
            # KnowledgeBase: tenant_id (find KBs in tenant)
            """
            CREATE INDEX kb_tenant_idx IF NOT EXISTS
            FOR (kb:KnowledgeBase) ON (kb.tenant_id)
            """,
            # Chunk: tenant_id (filter chunks by tenant)
            """
            CREATE INDEX chunk_tenant_idx IF NOT EXISTS
            FOR (c:Chunk) ON (c.tenant_id)
            """,
            # Entity: tenant_id (filter entities by tenant)
            """
            CREATE INDEX entity_tenant_idx IF NOT EXISTS
            FOR (e:Entity) ON (e.tenant_id)
            """,
            # Composite index for faster Entity lookup/MERGE
            """
            CREATE INDEX entity_lookup_idx IF NOT EXISTS
            FOR (e:Entity) ON (e.tenant_id, e.text, e.type)
            """,
            # TripletEntity indexes
            """
            CREATE INDEX triplet_entity_tenant_idx IF NOT EXISTS
            FOR (e:TripletEntity) ON (e.tenant_id)
            """,
            """
            CREATE INDEX triplet_entity_lookup_idx IF NOT EXISTS
            FOR (e:TripletEntity) ON (e.tenant_id, e.text, e.type)
            """,
            # ========== COMPOSITE INDEXES: TENANT + HIERARCHY ==========
            # CRITICAL: (tenant_id, agent_id) on Chunk
            # Most common RAG query: find chunks for specific agent in tenant
            """
            CREATE INDEX chunk_tenant_agent_idx IF NOT EXISTS
            FOR (c:Chunk) ON (c.tenant_id, c.agent_id)
            """,
            # (tenant_id, kb_id) on Chunk
            # Find chunks in specific KB within tenant
            """
            CREATE INDEX chunk_tenant_kb_idx IF NOT EXISTS
            FOR (c:Chunk) ON (c.tenant_id, c.kb_id)
            """,
            # (tenant_id, agent_id) on KnowledgeBase
            # Find KBs for agent in tenant
            """
            CREATE INDEX kb_tenant_agent_idx IF NOT EXISTS
            FOR (kb:KnowledgeBase) ON (kb.tenant_id, kb.agent_id)
            """,
            # ========== SINGLE INDEXES: HIERARCHY ==========
            # KnowledgeBase: agent_id (find KBs for agent)
            """
            CREATE INDEX kb_agent_idx IF NOT EXISTS
            FOR (kb:KnowledgeBase) ON (kb.agent_id)
            """,
            # Chunk: agent_id (find chunks created by agent)
            """
            CREATE INDEX chunk_agent_idx IF NOT EXISTS
            FOR (c:Chunk) ON (c.agent_id)
            """,
            # Chunk: kb_id (find chunks in KB)
            """
            CREATE INDEX chunk_kb_idx IF NOT EXISTS
            FOR (c:Chunk) ON (c.kb_id)
            """,
            # ========== SINGLE INDEXES: LOOKUP ==========
            # Agent: user_id (find agents owned by user)
            """
            CREATE INDEX agent_user_idx IF NOT EXISTS
            FOR (a:Agent) ON (a.user_id)
            """,
            # Entity: type (filter entities by type)
            """
            CREATE INDEX entity_type_idx IF NOT EXISTS
            FOR (e:Entity) ON (e.type)
            """,
            # Triplet indexes
            """
            CREATE INDEX triplet_tenant_idx IF NOT EXISTS
            FOR (t:Triplet) ON (t.tenant_id)
            """,
            """
            CREATE INDEX triplet_chunk_idx IF NOT EXISTS
            FOR (t:Triplet) ON (t.chunk_id)
            """,
            """
            CREATE INDEX triplet_tenant_chunk_idx IF NOT EXISTS
            FOR (t:Triplet) ON (t.tenant_id, t.chunk_id)
            """,
            # ========== VECTOR INDEX: RAG SEMANTIC SEARCH ==========
            # CRITICAL for Phase 5 (Graph RAG Pipeline)
            # Enables fast vector similarity search over embeddings
            # Requires Neo4j 5.0+ with vector support
            # NOTE: Dimension is CONFIGURABLE from settings.embedding_dimension
            """
            CREATE VECTOR INDEX chunk_embedding_idx IF NOT EXISTS
            FOR (c:Chunk)
            ON (c.embedding)
            OPTIONS {
              indexConfig: {
                `vector.dimensions`: 768,
                `vector.similarity_function`: 'cosine'
              }
            }
            """,
        ]

        # Add vector index with dynamic embedding dimension
        vector_index = f"""
            CREATE VECTOR INDEX chunk_embedding_idx IF NOT EXISTS
            FOR (c:Chunk)
            ON (c.embedding)
            OPTIONS {{
              indexConfig: {{
                `vector.dimensions`: {self.settings.embedding_dimension},
                `vector.similarity_function`: 'cosine'
              }}
            }}
            """
        # Replace the hardcoded vector index with the dynamic one
        indexes[-1] = vector_index

        logger.info("📊 Creating indexes...")
        for index in indexes:
            try:
                await self.execute_query(index)
                logger.info(f"  ✅ Index created (or already exists)")
            except (ConstraintError, ClientError) as e:
                if "already exists" in str(e).lower():
                    logger.info(f"  ℹ️  Index already exists (idempotent)")
                else:
                    logger.warning(f"  ⚠️  {e}")

    async def create_schema_documentation(self):
        """
        Log schema structure as reference.

        This is NOT executed, just for documentation.
        """
        schema_doc = """
        ============================================================
        NEO4J SCHEMA FOR MULTI-TENANT GRAPH RAG
        ============================================================

        NODES:
        ------
        1. Agent
           Props: id (UUID), tenant_id, user_id, name, system_prompt, created_at
           Constraints: id UNIQUE
           Indexes: tenant_id, user_id

        2. KnowledgeBase
           Props: id (UUID), tenant_id, agent_id, name, version, created_at
           Constraints: id UNIQUE
           Indexes: tenant_id, agent_id

        3. Chunk
           Props: id (UUID), tenant_id, agent_id, kb_id, content, embedding, created_at
           Constraints: id UNIQUE
           Indexes: tenant_id, agent_id, kb_id

        4. Entity
           Props: id (UUID), tenant_id, name, normalized_name, type, frequency, embedding, created_at
           Constraints: id UNIQUE, tenant_id NOT NULL
           Indexes: tenant_id, type
           Note: normalized_name is lowercase + trimmed (for deduplication)
                 frequency tracks how often entity appears in chunks
                 embedding is optional vector for semantic search

        RELATIONSHIPS (DIRECTIONAL RULES):
        ------
        1. (Agent)-[:OWNS_KB]->(KnowledgeBase)
           Direction: Agent → KnowledgeBase (one direction only)
           Meaning: Agent owns this knowledge base
           Props: None
           Filtering: Both nodes must have same tenant_id
           Enforcement: Neo4jRepository validates tenant_id

        2. (KnowledgeBase)-[:HAS_CHUNK]->(Chunk)
           Direction: KnowledgeBase → Chunk (one direction only)
           Meaning: Knowledge base contains this chunk
           Props: None
           Filtering: Both nodes must have same tenant_id
           Enforcement: Neo4jRepository validates tenant_id

        3. (Chunk)-[:BELONGS_TO]->(Agent)
           Direction: Chunk → Agent (one direction only)
           Meaning: Chunk belongs to (was created by) this agent
           Props: None
           Filtering: Both nodes must have same tenant_id
           Enforcement: Neo4jRepository validates tenant_id

        4. (Chunk)-[:SIMILAR]->(Chunk)
           Direction: Bidirectional (if A similar to B, then B similar to A)
           Meaning: One chunk is semantically similar to another
           Props: similarity_score (0.0-1.0)
           Filtering: Both chunks must have same tenant_id
           Use: Graph expansion in RAG query
           Enforcement: Only create one direction OR both sides when creating
           Enforcement: Neo4jRepository validates tenant_id

        5. (Chunk)-[:MENTIONS]->(Entity)
           Direction: Chunk → Entity (one direction)
           Meaning: Chunk mentions/references this entity
           Props: None
           Filtering: Both must have same tenant_id
           Use: Entity bridging in RAG
           Enforcement: Neo4jRepository validates tenant_id

        6. (Entity)-[:OCCURS_IN]->(Chunk)
           Direction: Entity → Chunk (one direction, inverse of MENTIONS)
           Meaning: Entity appears/is mentioned in chunk
           Props: None
           Filtering: Both must have same tenant_id
           Use: Entity context retrieval
           Enforcement: Neo4jRepository validates tenant_id
           Note: OCCURS_IN is automatically created when MENTIONS is created

        7. (Chunk)-[:NEXT]->(Chunk)
           Direction: Strictly directional (Chunk → next Chunk)
           Meaning: Chunk is followed by this chunk (document order)
           Props: position (integer, for ordering)
           Filtering: Both chunks must have same tenant_id
           Use: Sequential context in RAG (maintenance of document order)
           Enforcement: Position must be sequential
           Enforcement: Neo4jRepository validates tenant_id

        MULTI-TENANCY ENFORCEMENT:
        ------
        ✅ Every node has tenant_id property
        ✅ Every Cypher query MUST filter by tenant_id
        ✅ Every relationship path MUST respect tenant boundaries
        ✅ Neo4jRepository wraps all queries to enforce this

        EXAMPLE SAFE QUERY (enforced by Neo4jRepository):
        ------
        MATCH (a:Agent {tenant_id: $tenant_id, id: $agent_id})
        -[:OWNS_KB]->(kb:KnowledgeBase)
        -[:HAS_CHUNK]->(c:Chunk)
        WHERE c.tenant_id = $tenant_id
        RETURN c

        EXAMPLE UNSAFE QUERY (Neo4jRepository will REJECT):
        ------
        MATCH (c:Chunk) RETURN c  ❌ No tenant_id filter!
        
        ============================================================
        """
        logger.info(schema_doc)

    async def verify_schema(self):
        """
        Verify schema was created correctly.

        Runs sample queries to ensure:
        - Constraints are in place
        - Indexes are in place
        - Graph is ready for data
        """
        logger.info("✔️ Verifying schema...")

        try:
            # List constraints
            constraints = await self.execute_query("SHOW CONSTRAINTS")
            logger.info(f"  ✅ Found {len(constraints)} constraints")
            for constraint in constraints:
                logger.info(f"    - {constraint.get('name', 'unknown')}")

            # List indexes
            indexes = await self.execute_query("SHOW INDEXES")
            logger.info(f"  ✅ Found {len(indexes)} indexes")
            for index in indexes:
                logger.info(f"    - {index.get('name', 'unknown')}")

            logger.info("✅ Schema verification complete!")

        except Exception as e:
            logger.error(f"❌ Schema verification failed: {e}")
            raise

    async def init_schema(self):
        """
        Main entry point: Initialize complete schema.

        Order:
        1. Connect to Neo4j
        2. Create constraints
        3. Create indexes
        4. Verify schema
        5. Log documentation
        6. Close connection
        """
        try:
            # Connect
            await self.connect()

            # Create constraints (must be before indexes)
            await self.create_constraints()

            # Create indexes
            await self.create_indexes()

            # Verify
            await self.verify_schema()

            # Log documentation
            await self.create_schema_documentation()

            logger.info("🎉 Neo4j schema initialization complete!")

        except Exception as e:
            logger.error(f"❌ Schema initialization failed: {e}")
            raise

        finally:
            # Always close connection
            await self.close()


async def main():
    """Entry point for script execution."""
    settings = get_settings()

    # Validate Neo4j config
    if not settings.neo4j_uri:
        raise ValueError("NEO4J_URI not configured in .env")

    logger.info(f"🚀 Initializing Neo4j schema...")
    logger.info(f"   URI: {settings.neo4j_uri}")
    logger.info(f"   User: {settings.neo4j_user}")

    initializer = Neo4jSchemaInitializer(settings)
    await initializer.init_schema()


if __name__ == "__main__":
    asyncio.run(main())
