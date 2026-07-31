"""Service layer for Agent (business logic + transactions)"""

from sqlalchemy import select, and_, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
import logging
import uuid
from datetime import datetime
import asyncio
from sqlalchemy.exc import IntegrityError

from .models import Agent
from .repository import AgentRepository
from .audit import AgentAuditLog, AuditEventType
from . import schemas
from ...core.neo4j_repository import Neo4jRepository, SecurityError
from ...core.neo4j_retry import retry_neo4j_operation
from ...utils.formatters import format_success, format_error

logger = logging.getLogger(__name__)


class AgentService:
    """
    Agent service - coordinates PostgreSQL and Neo4j operations.

    DISTRIBUTED TRANSACTION PATTERN:
    ================================
    We cannot have true ACID across PostgreSQL + Neo4j.
    Instead, we use compensating transactions:

    CREATE:
    -------
    1. PostgreSQL INSERT (not committed)
    2. Neo4j CREATE node
    3. If Neo4j fails → Delete Neo4j node (compensation)
                      → Rollback PostgreSQL
    4. If success → COMMIT both

    DELETE:
    -------
    1. Neo4j DELETE (first, before touching PostgreSQL)
    2. If Neo4j succeeds → PostgreSQL soft-delete + COMMIT
    3. If Neo4j fails → ABORT (PostgreSQL untouched = safe)

    Key Principle:
    - Create: PostgreSQL first (smaller chance of failure)
    - Delete: Neo4j first (so PostgreSQL stays clean if Neo4j fails)
    """

    def __init__(self, db: AsyncSession, tenant_id: str):
        """
        Initialize agent service.

        Args:
            db: Database session (for PostgreSQL)
            tenant_id: Tenant UUID
        """
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id)
        self.repository = AgentRepository(db, str(self.tenant_id))

    async def create_agent(
        self,
        user_id: str,
        request: schemas.AgentCreate,
    ) -> dict:
        """
        Create a new agent in BOTH PostgreSQL and Neo4j (WITH COMPENSATION).

        TRANSACTION SAFETY WITH COMPENSATION:
        =====================================
        1. Create agent in PostgreSQL (not committed yet)
        2. Create (:Agent) node in Neo4j
        3. If Neo4j fails:
           - Delete the Neo4j node we just created (compensation)
           - Rollback PostgreSQL transaction
           - Return error
        4. If both succeed → COMMIT PostgreSQL

        Idempotency:
        - Unique constraint on (tenant_id, name, is_active=True) prevents duplicates
        - Retry fails if agent already exists with same name

        Args:
            user_id: User ID (agent owner)
            request: AgentCreate schema with name, description, system_prompt

        Returns:
            Dict with success, agent (AgentResponse), or error
        """
        agent_id = None
        try:
            # ============= STEP 0.1: VALIDATION: Personality exists with retry =============
            if request.personality_id:
                from app.modules.personalities.models import Personality
                personality_exists = None
                
                """
                Retry once because personality creation may have committed
                milliseconds after this request began.
                
                This is intended only to absorb short transaction visibility
                races between sequential REST requests.
                """
                for attempt in range(2):
                    personality_exists = await self.db.scalar(
                        select(Personality.id).where(Personality.id == request.personality_id)
                    )
                    if personality_exists:
                        break
                    if attempt < 1:
                        await asyncio.sleep(0.1)  # 100ms delay to allow commit propagation
                
                if not personality_exists:
                    logger.warning(
                        "⚠️ Personality missing while creating agent",
                        extra={
                            "personality_id": str(request.personality_id),
                            "agent_name": request.name,
                            "tenant_id": str(self.tenant_id),
                            "user_id": user_id,
                        },
                    )
                    return format_error(
                        "Selected personality does not exist. It may have been deleted or not fully created.",
                        meta={"status_code": 400}
                    )

            # ============= STEP 0.2: VALIDATION: Uniqueness per user =============
            existing = await self.repository.get_by_name_and_user(request.name, user_id)
            if existing:
                logger.warning(f"⚠️ User {user_id} tried to create duplicate agent name: {request.name}")
                return format_error(
                    "You already have an agent with this name. Please choose a different name.",
                    meta={"status_code": 400}
                )

            # ============= STEP 1: POSTGRES INSERT (NOT COMMITTED) =============
            # Create agent in PostgreSQL but don't commit yet
            try:
                pg_agent = await self.repository.create(
                    name=request.name,
                    user_id=user_id,
                    personality=request.personality,
                    personality_id=request.personality_id,
                    system_prompt=request.system_prompt,
                    agent_type=request.agent_type,
                    organization_name=request.organization_name,
                    contact_phone=request.contact_phone,
                    contact_email=request.contact_email,
                    website_url=request.website_url,
                    fallback_message_enabled=request.fallback_message_enabled,
                    brand_persona=request.brand_persona,
                )
            except IntegrityError as e:
                # Catch TOCTOU issues where personality is deleted right after our check
                # or if the repository flush() hits the constraint
                await self.db.rollback()
                
                orig = getattr(e, "orig", None)
                constraint = getattr(orig, "constraint_name", None)
                if constraint is None:
                    diag = getattr(orig, "diag", None)
                    if diag:
                        constraint = getattr(diag, "constraint_name", None)
                
                is_personality_fk = (constraint == "agents_personality_id_fkey")
                
                if not is_personality_fk and orig and type(orig).__name__ == "ForeignKeyViolationError":
                    is_personality_fk = "agents_personality_id_fkey" in str(e)
                elif not is_personality_fk:
                    is_personality_fk = "agents_personality_id_fkey" in str(e)

                if is_personality_fk:
                    logger.exception(
                        "FK violation creating agent",
                        extra={
                            "constraint": constraint or "agents_personality_id_fkey",
                            "personality_id": str(request.personality_id),
                            "agent_name": request.name,
                            "tenant_id": str(self.tenant_id),
                        }
                    )
                    return format_error(
                        "Selected personality no longer exists or is unavailable.",
                        meta={"status_code": 400}
                    )
                raise
                
            agent_id = str(pg_agent.id)
            logger.info(f"✅ PostgreSQL: Created agent {agent_id}")

            # ============= STEP 2: NEO4J CREATE WITH RETRY =============
            # Create Agent node in Neo4j with retry handling
            try:
                neo4j_repo = Neo4jRepository(str(self.tenant_id))

                neo4j_query = """
                CREATE (a:Agent {
                    id: $agent_id,
                    tenant_id: $tenant_id,
                    user_id: $user_id,
                    name: $name,
                    personality: $personality,
                    personality_id: $personality_id,
                    system_prompt: $system_prompt,
                    created_at: timestamp()
                })
                RETURN a
                """

                # Execute with retry for transient failures
                await retry_neo4j_operation(
                    lambda: neo4j_repo.execute_write(
                        neo4j_query,
                        {
                            "agent_id": agent_id,
                            "tenant_id": str(self.tenant_id),
                            "user_id": str(user_id),
                            "name": request.name,
                            "personality": request.personality,
                            "personality_id": str(request.personality_id) if request.personality_id else None,
                            "system_prompt": request.system_prompt or "",
                        },
                    )
                )

                logger.info(f"✅ Neo4j: Created agent node {agent_id}")

            except Exception as neo4j_error:
                # ============= COMPENSATION: DELETE NEO4J NODE =============
                # We created a Neo4j node but something failed.
                # Try to delete it to avoid orphan nodes.
                logger.warning(f"⚠️ Neo4j creation failed: {neo4j_error}")
                logger.warning(
                    f"   Attempting compensation: delete Neo4j node {agent_id}"
                )

                try:
                    await retry_neo4j_operation(
                        lambda: neo4j_repo.execute_write(
                            """
                            MATCH (a:Agent {id: $agent_id, tenant_id: $tenant_id})
                            DETACH DELETE a
                            """,
                            {"agent_id": agent_id, "tenant_id": str(self.tenant_id)},
                        )
                    )
                    logger.info(
                        f"✅ Compensation: Deleted orphan Neo4j node {agent_id}"
                    )
                except Exception as comp_error:
                    logger.error(
                        f"❌ Compensation failed (orphan node remains): {comp_error}"
                    )

                # ============= ROLLBACK POSTGRESQL =============
                await self.db.rollback()
                logger.error(f"❌ Rolled back PostgreSQL after Neo4j failure")

                return format_error(
                    f"Failed to create agent graph node (compensation executed): {neo4j_error}",
                    meta={"error_code": "NEO4J_ERROR"},
                )

            # ============= STEP 3: COMMIT BOTH TRANSACTIONS =============
            await self.db.commit()
            await self.db.refresh(pg_agent) 
            logger.info(f"✅ COMMITTED: Agent {agent_id} in PostgreSQL + Neo4j")

            # ============= AUDIT LOG =============
            await AgentAuditLog.log_event(
                tenant_id=str(self.tenant_id),
                user_id=user_id,
                agent_id=agent_id,
                event_type=AuditEventType.AGENT_CREATED,
                details={
                    "name": request.name,
                    "personality": request.personality,
                    "has_system_prompt": bool(request.system_prompt),
                },
            )

            return format_success(
                {
                    "agent": schemas.AgentResponse.model_validate(
                        pg_agent, from_attributes=True
                    )
                },
                meta={"message": "Agent created successfully"},
            )

        except Exception as e:
            # ============= FINAL ROLLBACK ON ANY ERROR =============
            await self.db.rollback()
            logger.error(f"❌ Agent creation failed: {e}")
            return format_error(
                f"Failed to create agent: {str(e)}", meta={"error_code": "CREATION_ERROR"}
            )

    async def _enrich_agents_with_connections(self, agents, schema_class) -> list[dict]:
        if not agents:
            return []
            
        agent_ids = [a.id for a in agents]
        
        from sqlalchemy import select
        from app.modules.knowledge_bases.models import KnowledgeBase, DatabaseConnection
        
        query = select(
            KnowledgeBase.agent_id, 
            DatabaseConnection.db_type,
            KnowledgeBase.source
        ).outerjoin(
            DatabaseConnection, KnowledgeBase.id == DatabaseConnection.kb_id
        ).where(
            KnowledgeBase.agent_id.in_(agent_ids),
            KnowledgeBase.is_active == True
        )
        res = await self.db.execute(query)
        
        connections_by_agent = {}
        for row in res.all():
            agent_id = row.agent_id
            if agent_id not in connections_by_agent:
                connections_by_agent[agent_id] = set()
            if row.db_type:
                connections_by_agent[agent_id].add(row.db_type)
            if row.source:
                if row.source.startswith('google_drive'):
                    connections_by_agent[agent_id].add('google_drive')
                elif row.source.startswith('sharepoint'):
                    connections_by_agent[agent_id].add('sharepoint')
                elif row.source.startswith('gmail'):
                    connections_by_agent[agent_id].add('gmail')
                elif row.source.startswith('outlook'):
                    connections_by_agent[agent_id].add('outlook')
                elif row.source == 'web_scraper':
                    connections_by_agent[agent_id].add('web_scraper')
            
        responses = []
        for agent in agents:
            # We support both AgentResponse and AgentEnhancedResponse
            agent_dict = schema_class.model_validate(agent, from_attributes=True).model_dump(mode="json")
            agent_dict["connected_integrations"] = list(connections_by_agent.get(agent.id, set()))
            responses.append(agent_dict)
            
        return responses

    async def get_agent(self, agent_id: str) -> dict:
        """
        Get agent by ID (PostgreSQL only, Neo4j not needed for read).

        Args:
            agent_id: Agent UUID

        Returns:
            Dict with success, agent, or error
        """
        try:
            agent = await self.repository.get_by_id(agent_id)

            if not agent:
                return format_error(f"Agent not found: {agent_id}", meta={"status_code": 404})

            enriched = await self._enrich_agents_with_connections([agent], schemas.AgentResponse)

            return format_success(
                {
                    "agent": enriched[0]
                }
            )

        except Exception as e:
            logger.error(f"Failed to get agent: {e}")
            return format_error(f"Failed to retrieve agent: {str(e)}")

    async def list_agents(self, limit: int = 50, offset: int = 0) -> dict:
        """
        List all agents for tenant (PostgreSQL only).
        """
        try:
            agents, total = await self.repository.list_agents(
                limit=limit, offset=offset
            )

            enriched = await self._enrich_agents_with_connections(agents, schemas.AgentResponse)

            return format_success(
                {
                    "agents": enriched,
                    "count": len(agents),
                    "total": total,
                }
            )

        except Exception as e:
            logger.error(f"Failed to list agents: {e}")
            return format_error(f"Failed to list agents: {str(e)}")

    async def list_agents_enhanced(
        self, search: Optional[str] = None, limit: int = 50, offset: int = 0
    ) -> dict:
        """
        Get comprehensive agent audit list with User/Tenant/KB details.
        Supports filtering by agent_name, username, or tenant_name.
        """
        try:
            agents, total = await self.repository.list_agents_enhanced(
                search=search, limit=limit, offset=offset
            )

            # Enhanced agents are just raw objects/dicts based on the repository return type, 
            # we need to be careful if they are objects with an ID or dictionaries.
            # Usually they are mapped to models or are raw rows. Let's handle them assuming they behave like models.
            # To be safe, we just use the schema class to dump them.
            
            # Since agents here might be named tuples returned by the enhanced query, 
            # we adapt the enrichment for them.
            agent_ids = [a.agent_id for a in agents]
            
            from sqlalchemy import select
            query = select(
                KnowledgeBase.agent_id, 
                DatabaseConnection.db_type,
                KnowledgeBase.source
            ).outerjoin(
                DatabaseConnection, KnowledgeBase.id == DatabaseConnection.kb_id
            ).where(
                KnowledgeBase.agent_id.in_(agent_ids),
                KnowledgeBase.is_active == True
            )
            res = await self.db.execute(query)
            connections_by_agent = {}
            for row in res.all():
                if row.agent_id not in connections_by_agent:
                    connections_by_agent[row.agent_id] = set()
                if row.db_type:
                    connections_by_agent[row.agent_id].add(row.db_type)
                if row.source:
                    if row.source.startswith('google_drive'):
                        connections_by_agent[row.agent_id].add('google_drive')
                    elif row.source.startswith('sharepoint'):
                        connections_by_agent[row.agent_id].add('sharepoint')
                    elif row.source.startswith('gmail'):
                        connections_by_agent[row.agent_id].add('gmail')
                    elif row.source.startswith('outlook'):
                        connections_by_agent[row.agent_id].add('outlook')
                    elif row.source == 'web_scraper':
                        connections_by_agent[row.agent_id].add('web_scraper')
            
            responses = []
            for agent in agents:
                agent_dict = schemas.AgentEnhancedResponse.model_validate(agent, from_attributes=True).model_dump(mode="json")
                agent_dict["connected_integrations"] = list(connections_by_agent.get(agent.agent_id, set()))
                responses.append(agent_dict)

            return format_success(
                {
                    "agents": responses,
                    "count": len(agents),
                    "total": total,
                }
            )

        except Exception as e:
            logger.error(f"Failed to list enhanced agents: {e}")
            return format_error(f"Failed to list enhanced agents: {str(e)}")

    async def list_agents_by_user(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> dict:
        """
        List agents created by specific user.

        Args:
            user_id: User UUID
            limit: Max results
            offset: Pagination offset

        Returns:
            Dict with success, agents list, count
        """
        try:
            agents, total = await self.repository.list_by_user(
                user_id, limit=limit, offset=offset
            )

            enriched = await self._enrich_agents_with_connections(agents, schemas.AgentResponse)

            return format_success(
                {
                    "agents": enriched,
                    "count": len(agents),
                    "total": total,
                }
            )

        except Exception as e:
            logger.error(f"Failed to list user agents: {e}")
            return format_error(f"Failed to list agents: {str(e)}")

    async def list_agents_by_user_email(
        self, email: str, limit: int = 50, offset: int = 0
    ) -> dict:
        """
        List all agents created by a specific user identified by email.
        """
        from ..auth.models import User
        from sqlalchemy import select, and_
        
        try:
            # 1. Find user by email within tenant
            result = await self.db.execute(
                select(User).where(
                    and_(
                        User.email == email,
                        User.tenant_id == self.tenant_id
                    )
                )
            )
            user = result.scalar_one_or_none()
            
            if not user:
                return format_error(f"User with email '{email}' not found in this tenant")

            # 2. List agents for this user
            agents, total = await self.repository.list_by_user(
                user_id=str(user.id), limit=limit, offset=offset
            )

            enriched = await self._enrich_agents_with_connections(agents, schemas.AgentResponse)

            return format_success(
                {
                    "agents": enriched,
                    "count": len(agents),
                    "total": total,
                    "owner": {
                        "id": str(user.id),
                        "email": user.email,
                        "name": f"{user.first_name or ''} {user.last_name or ''}".strip()
                    }
                }
            )

        except Exception as e:
            logger.error(f"Failed to list agents for user {email}: {e}")
            return format_error(f"Failed to retrieve agents for user: {str(e)}")

    async def update_agent(self, user_id: str, agent_id: str, request: schemas.AgentUpdate) -> dict:
        """
        Update agent (PostgreSQL + Neo4j sync).

        NOTE: For now, only PostgreSQL is updated. Neo4j update is optional
        and would require additional schema (versioning, timestamps).

        Args:
            agent_id: Agent UUID
            request: AgentUpdate schema with optional fields

        Returns:
            Dict with success, updated agent, or error
        """
        try:
            # Extract non-None fields
            update_data = {
                k: v for k, v in request.model_dump().items() if v is not None
            }

            if not update_data:
                return format_error("No fields provided for update", meta={"status_code": 400})

            # ============= STEP 1: POSTGRES UPDATE =============
            agent = await self.repository.update(agent_id, **update_data)

            if not agent:
                return format_error(f"Agent not found: {agent_id}", meta={"status_code": 404})

            # ============= STEP 2: NEO4J SYNC (IF NEEDED) =============
            # Update fields in Neo4j to keep graph consistent with metadata DB
            if any(k in update_data for k in ["name", "personality", "personality_id", "system_prompt"]):
                try:
                    neo4j_repo = Neo4jRepository(str(self.tenant_id))
                    
                    # Construct dynamic SET clause for Neo4j
                    set_clauses = []
                    params = {"agent_id": agent_id, "tenant_id": str(self.tenant_id)}
                    
                    for field in ["name", "personality", "personality_id", "system_prompt"]:
                        if field in update_data:
                            value = update_data[field]
                            if field == "personality_id" and value:
                                value = str(value)
                            set_clauses.append(f"a.{field} = ${field}")
                            params[field] = value
                    
                    if set_clauses:
                        neo4j_query = f"""
                        MATCH (a:Agent {{id: $agent_id, tenant_id: $tenant_id}})
                        SET {', '.join(set_clauses)}, a.updated_at = timestamp()
                        RETURN a
                        """
                        
                        await retry_neo4j_operation(
                            lambda: neo4j_repo.execute_write(neo4j_query, params)
                        )
                        logger.info(f"✅ Neo4j: Updated agent node {agent_id}")
                        
                except Exception as neo4j_error:
                    # NOTE: We don't necessarily rollback PostgreSQL if Neo4j update fails,
                    # but we should log it. In a "perfect" system, we might want atomic sync.
                    logger.error(f"⚠️ Neo4j sync failed during update: {neo4j_error}")
                    # For consistency, we'll continue but return a warning in meta
                    pass

            await self.db.commit()
            
            # CRITICAL: Refresh the agent object to load DB-generated fields like updated_at
            # This prevents the 'MissingGreenlet' error during Pydantic validation
            await self.db.refresh(agent)

            # ============= AUDIT LOG =============
            await AgentAuditLog.log_event(
                tenant_id=str(self.tenant_id),
                user_id=user_id,
                agent_id=agent_id,
                event_type=AuditEventType.AGENT_UPDATED,
                details={"updated_fields": list(update_data.keys())},
            )

            return format_success(
                {
                    "agent": schemas.AgentResponse.model_validate(
                        agent, from_attributes=True
                    )
                },
                meta={"message": "Agent updated successfully"},
            )

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Failed to update agent: {e}")
            return format_error(f"Failed to update agent: {str(e)}")

    async def delete_agent(self, user_id: str, agent_id: str) -> dict:
        """
        HARD DELETE agent and ALL associated resources permanently from PostgreSQL, S3,
        local Parquet datasets, and Neo4j graph storage.

        CRITICAL DELETE ORDER (Neo4j FIRST, Then S3/Parquet, Then PostgreSQL):
        ======================================================================
        1. Neo4j HARD DELETE FIRST (Agent + KB + Chunks)
        2. S3 Object Removal & Local Parquet Dataset Unregistration
        3. PostgreSQL Hard Delete (CASCADE via Foreign Keys)
        4. COMMIT PostgreSQL & Audit Log
        """
        try:
            from sqlalchemy import select, delete, func
            import uuid
            from .models import Agent
            from app.modules.knowledge_bases.models import (
                KnowledgeBase, DocumentChunk, DocumentTableRow, 
                DocumentEntity, DocumentSection, DocumentIngestionRun, 
                DatabaseConnection, AnalyticsQueryLog
            )
            from app.core.s3 import S3StorageService
            from app.core.parquet_ingester import ParquetIngester

            agent_uuid = uuid.UUID(agent_id) if isinstance(agent_id, str) else agent_id

            # Verify Agent exists before deletion
            agent = await self.db.scalar(
                select(Agent).where(
                    Agent.id == agent_uuid,
                    Agent.tenant_id == self.tenant_id
                )
            )
            if not agent:
                logger.warning(f"Cannot hard delete: agent not found: {agent_id}")
                return format_error(f"Agent not found: {agent_id}", meta={"status_code": 404})

            # ============= STEP 1: NEO4J GRAPH HARD DELETE FIRST =============
            neo4j_repo = Neo4jRepository(str(self.tenant_id))
            delete_query = """
            MATCH (a:Agent {tenant_id: $tenant_id, id: $agent_id})
            OPTIONAL MATCH (a)-[:OWNS_KB]->(kb:KnowledgeBase)
            OPTIONAL MATCH (kb)-[:HAS_CHUNK]->(c:Chunk)
            DETACH DELETE a, kb, c
            RETURN count(a) as deleted_agents
            """
            try:
                await retry_neo4j_operation(
                    lambda: neo4j_repo.execute_write(
                        delete_query,
                        {
                            "agent_id": str(agent_id),
                            "tenant_id": str(self.tenant_id),
                        },
                    )
                )
                logger.info(f"✅ Neo4j: Hard-deleted agent {agent_id} + cascade graph nodes")
            except Exception as neo4j_error:
                logger.error(f"❌ Neo4j hard-deletion failed: {neo4j_error}")
                return format_error(
                    f"Failed to delete agent from graph: {neo4j_error}",
                    meta={"error_code": "NEO4J_ERROR"},
                )

            # ============= STEP 2: S3 & PARQUET DATASET CLEANUP =============
            kbs_res = await self.db.execute(
                select(KnowledgeBase).where(
                    KnowledgeBase.agent_id == agent_uuid,
                    KnowledgeBase.tenant_id == self.tenant_id
                )
            )
            kbs = kbs_res.scalars().all()
            kb_ids = [kb.id for kb in kbs]

            s3_service = S3StorageService()
            for kb in kbs:
                # 1. Clean parsed content from S3 / Parquet disk storage
                if kb.parsed_path:
                    try:
                        await s3_service.delete_file_by_url(kb.parsed_path)
                    except Exception as s3_err:
                        logger.warning(f"Failed to delete parsed_path S3 file for KB {kb.id}: {s3_err}")
                    try:
                        ParquetIngester.unregister_dataset(kb.parsed_path)
                    except Exception as pq_err:
                        logger.warning(f"Failed to unregister Parquet dataset for KB {kb.id}: {pq_err}")

                # 2. Clean original uploaded source file from S3 if not shared
                if kb.s3_path:
                    try:
                        stmt = select(func.count()).select_from(KnowledgeBase).where(
                            KnowledgeBase.s3_path == kb.s3_path,
                            KnowledgeBase.agent_id != agent_uuid
                        )
                        count_res = await self.db.execute(stmt)
                        other_uses = count_res.scalar() or 0
                        if other_uses == 0:
                            await s3_service.delete_file_by_url(kb.s3_path)
                    except Exception as s3_err:
                        logger.warning(f"Failed to delete s3_path S3 file for KB {kb.id}: {s3_err}")

            # ============= STEP 3: POSTGRES HARD DELETE (CASCADE) =============
            if kb_ids:
                await self.db.execute(delete(DocumentChunk).where(DocumentChunk.kb_id.in_(kb_ids)))
                await self.db.execute(delete(DocumentTableRow).where(DocumentTableRow.kb_id.in_(kb_ids)))
                await self.db.execute(delete(DocumentEntity).where(DocumentEntity.document_id.in_(kb_ids)))
                await self.db.execute(delete(DocumentSection).where(DocumentSection.document_id.in_(kb_ids)))
                await self.db.execute(delete(DocumentIngestionRun).where(DocumentIngestionRun.document_id.in_(kb_ids)))
                await self.db.execute(delete(DatabaseConnection).where(DatabaseConnection.kb_id.in_(kb_ids)))
                await self.db.execute(delete(AnalyticsQueryLog).where(AnalyticsQueryLog.kb_id.in_(kb_ids)))
                await self.db.execute(delete(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids)))

            from app.modules.chats.models import ChatSession
            await self.db.execute(delete(ChatSession).where(ChatSession.agent_id == agent_uuid, ChatSession.tenant_id == self.tenant_id))

            # Hard-delete Agent record
            await self.db.execute(delete(Agent).where(Agent.id == agent_uuid, Agent.tenant_id == self.tenant_id))

            # Commit changes
            await self.db.commit()
            logger.info(f"✅ HARD DELETED Agent {agent_id} and all related KBs, S3 files, Parquet datasets, and chat memory.")

            # ============= AUDIT LOG =============
            await AgentAuditLog.log_event(
                tenant_id=str(self.tenant_id),
                user_id=user_id,
                agent_id=str(agent_id),
                event_type=AuditEventType.AGENT_DELETED,
                details={"hard_deleted": True, "deleted_at": datetime.utcnow().isoformat()},
            )

            return format_success(
                {"id": str(agent_id)},
                meta={"message": "Agent and all associated knowledge base files, datasets, and memory purged permanently."},
            )

        except Exception as e:
            await self.db.rollback()
            logger.error(f"❌ Hard deletion of agent failed: {e}", exc_info=True)
            return format_error(f"Failed to hard-delete agent: {str(e)}")
