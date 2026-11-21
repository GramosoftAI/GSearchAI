"""Profile Management business logic & complete account deletion service"""

import uuid
from uuid import UUID
from datetime import datetime
from typing import Optional, Dict, Any, Union
import logging

from fastapi import HTTPException, status
from sqlalchemy import select, delete, func, text, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User, APIKey, TokenBlacklist, PasswordResetToken
from app.modules.profile.models import UserProfile
from app.modules.profile import schemas
from app.core.security import verify_password

logger = logging.getLogger("app.modules.profile.services")


def _coerce_uuid(val: Any) -> Optional[UUID]:
    if not val:
        return None
    if isinstance(val, UUID):
        return val
    try:
        return UUID(str(val))
    except (ValueError, TypeError):
        return None


async def get_or_create_profile(user: User, db: AsyncSession) -> UserProfile:
    """
    Retrieve profile for user, or automatically provision one matching user's registered login credentials.
    Ensures seamless login integration and accurate user info reflection.
    """
    user_uuid = user.id if isinstance(user.id, UUID) else _coerce_uuid(user.id)
    stmt = select(UserProfile).where(UserProfile.user_id == user_uuid)
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile:
        # Keep registered email and names synchronized with User account
        updated = False
        if profile.email != user.email:
            profile.email = user.email
            updated = True
        if user.first_name and not profile.first_name:
            profile.first_name = user.first_name
            updated = True
        if user.last_name and not profile.last_name:
            profile.last_name = user.last_name
            updated = True
        if updated:
            db.add(profile)
            await db.commit()
            await db.refresh(profile)
        return profile

    # Auto-provision profile with unique username
    base_username = (user.email.split("@")[0] or "user").lower().replace("+", "_").replace(".", "_")
    candidate_username = base_username
    counter = 1

    while True:
        check_stmt = select(UserProfile).where(UserProfile.username == candidate_username)
        res = await db.execute(check_stmt)
        if not res.scalar_one_or_none():
            break
        candidate_username = f"{base_username}_{counter}"
        counter += 1

    display_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or candidate_username

    profile = UserProfile(
        id=uuid.uuid4(),
        user_id=user_uuid,
        tenant_id=user.tenant_id,
        username=candidate_username,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        display_name=display_name,
        timezone="UTC",
        language="en",
        theme="system",
        notification_preferences={"email_notifications": True, "chat_sound": True},
        custom_metadata={},
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    logger.info(f"✅ Auto-provisioned user profile for {user.email} (username: {candidate_username})")
    return profile


async def get_user_resource_summary(user: User, db: AsyncSession) -> schemas.UserResourceSummary:
    """Calculates all resources currently owned by the user across the platform"""
    user_uuid = user.id if isinstance(user.id, UUID) else _coerce_uuid(user.id)
    user_id_str = str(user_uuid)

    from app.modules.agents.models import Agent
    from app.modules.knowledge_bases.models import KnowledgeBase
    from app.modules.chats.models import ChatSession, ChatMessage

    # 1. Agents count
    agents_res = await db.execute(
        select(func.count(Agent.id)).where(Agent.user_id == user_uuid, Agent.tenant_id == user.tenant_id)
    )
    agents_count = agents_res.scalar() or 0

    # 2. Knowledge Bases count
    kbs_res = await db.execute(
        select(func.count(KnowledgeBase.id)).where(KnowledgeBase.user_id == user_uuid)
    )
    kbs_count = kbs_res.scalar() or 0

    # 3. Database Knowledgebases count
    try:
        from app.modules.database_knowledgebase.models import DatabaseKnowledgebase
        db_kbs_res = await db.execute(
            select(func.count(DatabaseKnowledgebase.id)).where(DatabaseKnowledgebase.user_id == user_uuid)
        )
        db_kbs_count = db_kbs_res.scalar() or 0
    except Exception:
        db_kbs_count = 0

    # 4. Chat Sessions and Messages count
    sessions_res = await db.execute(
        select(func.count(ChatSession.id)).where(ChatSession.user_id == user_uuid)
    )
    sessions_count = sessions_res.scalar() or 0

    messages_res = await db.execute(
        select(func.count(ChatMessage.id))
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.user_id == user_uuid)
    )
    messages_count = messages_res.scalar() or 0

    # 5. Episodic memories count
    try:
        mem_res = await db.execute(
            text("SELECT COUNT(*) FROM episodic_memories WHERE user_id = :uid"),
            {"uid": user_id_str}
        )
        memories_count = mem_res.scalar() or 0
    except Exception:
        memories_count = 0

    # 6. User preferences count
    try:
        pref_res = await db.execute(
            text("SELECT COUNT(*) FROM user_preferences WHERE user_id = :uid"),
            {"uid": user_id_str}
        )
        preferences_count = pref_res.scalar() or 0
    except Exception:
        preferences_count = 0

    # 7. API Keys count
    keys_res = await db.execute(
        select(func.count(APIKey.id)).where(APIKey.user_id == user_uuid)
    )
    api_keys_count = keys_res.scalar() or 0

    total_resources = (
        agents_count
        + kbs_count
        + db_kbs_count
        + sessions_count
        + messages_count
        + memories_count
        + preferences_count
        + api_keys_count
    )

    return schemas.UserResourceSummary(
        agents_count=agents_count,
        knowledge_bases_count=kbs_count,
        database_knowledgebases_count=db_kbs_count,
        chat_sessions_count=sessions_count,
        chat_messages_count=messages_count,
        episodic_memories_count=memories_count,
        user_preferences_count=preferences_count,
        api_keys_count=api_keys_count,
        files_count=kbs_count,
        total_resources=total_resources,
    )


async def build_profile_response(
    profile: UserProfile,
    user: User,
    db: AsyncSession,
    include_summary: bool = True
) -> schemas.ProfileResponse:
    """Constructs complete ProfileResponse combining User and UserProfile models"""
    summary = await get_user_resource_summary(user, db) if include_summary else None

    return schemas.ProfileResponse(
        id=profile.id,
        user_id=profile.user_id,
        tenant_id=profile.tenant_id,
        username=profile.username,
        email=profile.email,
        first_name=profile.first_name,
        last_name=profile.last_name,
        display_name=profile.display_name,
        phone_number=profile.phone_number,
        avatar_url=profile.avatar_url,
        bio=profile.bio,
        job_title=profile.job_title,
        department=profile.department,
        organization=profile.organization,
        country=profile.country,
        timezone=profile.timezone or "UTC",
        language=profile.language or "en",
        theme=profile.theme or "system",
        notification_preferences=profile.notification_preferences or {},
        custom_metadata=profile.custom_metadata or {},
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        role="admin" if user.is_admin else "user",
        is_admin=user.is_admin,
        is_active=user.is_active,
        last_login_at=getattr(user, "last_login_at", None),
        preferred_llm_model=user.preferred_llm_model,
        resource_summary=summary,
    )


async def get_user_profile(user: User, db: AsyncSession, include_summary: bool = True) -> schemas.ProfileResponse:
    """Retrieve full profile with login integration"""
    profile = await get_or_create_profile(user, db)
    return await build_profile_response(profile, user, db, include_summary=include_summary)


async def create_user_profile(user: User, data: schemas.ProfileCreate, db: AsyncSession) -> schemas.ProfileResponse:
    """Explicitly create or configure user profile"""
    user_uuid = user.id if isinstance(user.id, UUID) else _coerce_uuid(user.id)
    stmt = select(UserProfile).where(UserProfile.user_id == user_uuid)
    res = await db.execute(stmt)
    existing = res.scalar_one_or_none()

    if existing:
        # Profile already exists: update fields
        update_data = schemas.ProfileUpdate(**data.model_dump(exclude_unset=True))
        return await update_user_profile(user, update_data, db)

    # Validate username uniqueness
    username = data.username
    if not username:
        username = (user.email.split("@")[0] or "user").lower().replace("+", "_").replace(".", "_")

    uname_check = await db.execute(select(UserProfile).where(UserProfile.username == username))
    if uname_check.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Username '{username}' is already taken",
        )

    profile = UserProfile(
        id=uuid.uuid4(),
        user_id=user_uuid,
        tenant_id=user.tenant_id,
        username=username,
        email=user.email,
        first_name=data.first_name or user.first_name,
        last_name=data.last_name or user.last_name,
        display_name=data.display_name or f"{data.first_name or user.first_name or ''} {data.last_name or user.last_name or ''}".strip() or username,
        phone_number=data.phone_number,
        avatar_url=data.avatar_url,
        bio=data.bio,
        job_title=data.job_title,
        department=data.department,
        organization=data.organization,
        country=data.country,
        timezone=data.timezone or "UTC",
        language=data.language or "en",
        theme=data.theme or "system",
        notification_preferences=data.notification_preferences or {"email_notifications": True, "chat_sound": True},
        custom_metadata=data.custom_metadata or {},
    )
    db.add(profile)

    # Synchronize names to User record
    if data.first_name:
        user.first_name = data.first_name
    if data.last_name:
        user.last_name = data.last_name
    db.add(user)

    await db.commit()
    await db.refresh(profile)
    await db.refresh(user)

    return await build_profile_response(profile, user, db, include_summary=True)


async def update_user_profile(user: User, data: schemas.ProfileUpdate, db: AsyncSession) -> schemas.ProfileResponse:
    """Update profile attributes and sync essential fields to User table"""
    profile = await get_or_create_profile(user, db)
    update_dict = data.model_dump(exclude_unset=True)

    # 1. Validate username uniqueness if changed
    if "username" in update_dict and update_dict["username"]:
        new_username = update_dict["username"].strip()
        if new_username != profile.username:
            uname_stmt = select(UserProfile).where(
                UserProfile.username == new_username,
                UserProfile.id != profile.id,
            )
            uname_res = await db.execute(uname_stmt)
            if uname_res.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Username '{new_username}' is already taken",
                )
            profile.username = new_username

    # 2. Synchronize names and preferred model
    user_sync_needed = False
    if "first_name" in update_dict:
        profile.first_name = update_dict["first_name"]
        user.first_name = update_dict["first_name"]
        user_sync_needed = True

    if "last_name" in update_dict:
        profile.last_name = update_dict["last_name"]
        user.last_name = update_dict["last_name"]
        user_sync_needed = True

    if "preferred_llm_model" in update_dict:
        user.preferred_llm_model = update_dict["preferred_llm_model"]
        user_sync_needed = True

    # 3. Update remaining profile fields
    for field in [
        "display_name", "phone_number", "avatar_url", "bio",
        "job_title", "department", "organization", "country",
        "timezone", "language", "theme", "notification_preferences",
        "custom_metadata"
    ]:
        if field in update_dict and update_dict[field] is not None:
            setattr(profile, field, update_dict[field])

    profile.updated_at = func.now()
    db.add(profile)
    if user_sync_needed:
        user.updated_at = func.now()
        db.add(user)

    await db.commit()
    await db.refresh(profile)
    await db.refresh(user)

    logger.info(f"✅ Successfully updated profile for user {user.email}")
    return await build_profile_response(profile, user, db, include_summary=True)


async def delete_user_account_completely(
    user: User,
    db: AsyncSession,
    request: Optional[schemas.DeleteAccountRequest] = None,
    is_admin_override: bool = False,
) -> schemas.DeleteAccountResponse:
    """
    CRITICAL: PERMANENT & COMPLETE ACCOUNT DELETION.
    Performs a thorough cleanup of all user-associated resources across the platform:
    1. Neo4j Graph Database: Agent, KB, Chunk, Memory, and Session nodes.
    2. S3 Object Storage: Uploaded document files and parsed text artifacts.
    3. Local Storage: Parquet datasets and cache.
    4. Relational Database:
       - DocumentChunks, DocumentTableRows, DocumentEntities, DocumentSections, DocumentIngestionRuns
       - KnowledgeBases, DatabaseKnowledgebases
       - Agents
       - ChatMessages, ChatSessions
       - EpisodicMemories, UserPreferences
       - APIKeys, PasswordResetTokens, TokenBlacklist
       - ProcessingJobs, WidgetCustomizations, WidgetEmbedConfigs, Personalities
       - Gmail & Slack integration state
       - UserProfile
       - User account
    """
    if request:
        if not request.confirm:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Deletion was not confirmed. 'confirm' must be true to permanently delete account.",
            )
        # If user password is provided and not admin override, verify password
        if request.password and not is_admin_override:
            if not verify_password(request.password, user.hashed_password):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid password provided for account deletion confirmation.",
                )

    user_uuid = user.id if isinstance(user.id, UUID) else _coerce_uuid(user.id)
    tenant_uuid = user.tenant_id if isinstance(user.tenant_id, UUID) else _coerce_uuid(user.tenant_id)
    user_id_str = str(user_uuid)
    tenant_id_str = str(tenant_uuid)
    user_email = user.email

    logger.warning(f"🚨 STARTING COMPLETE ACCOUNT DELETION for user {user_email} (ID: {user_id_str})")

    purged_counts: Dict[str, int] = {}

    try:
        # Import models and services needed for cascade cleanup
        from app.modules.agents.models import Agent
        from app.modules.knowledge_bases.models import (
            KnowledgeBase, DocumentChunk, DocumentTableRow,
            DocumentEntity, DocumentSection, DocumentIngestionRun,
            DatabaseConnection, AnalyticsQueryLog
        )
        from app.modules.chats.models import ChatSession, ChatMessage
        from app.core.s3 import S3StorageService
        from app.core.parquet_ingester import ParquetIngester
        from app.core.neo4j_repository import Neo4jRepository
        from app.core.neo4j_retry import retry_neo4j_operation

        s3_service = S3StorageService()
        neo4j_repo = Neo4jRepository(tenant_id_str)

        # -------------------------------------------------------------
        # 1. PURGE AGENTS & THEIR NEO4J NODES, S3 FILES, PARQUET DATA
        # -------------------------------------------------------------
        agent_stmt = select(Agent).where(Agent.user_id == user_uuid, Agent.tenant_id == tenant_uuid)
        agent_res = await db.execute(agent_stmt)
        user_agents = agent_res.scalars().all()
        agent_ids = [a.id for a in user_agents]
        purged_counts["agents"] = len(agent_ids)

        for agent in user_agents:
            agent_id_str = str(agent.id)
            # Neo4j agent cascade purge
            try:
                chunk_delete_query = """
                MATCH (a:Agent {tenant_id: $tenant_id, id: $agent_id})-[:OWNS_KB]->(kb:KnowledgeBase)-[:HAS_CHUNK]->(c:Chunk)
                DETACH DELETE c
                """
                await retry_neo4j_operation(
                    lambda: neo4j_repo.execute_write(
                        chunk_delete_query,
                        {"agent_id": agent_id_str, "tenant_id": tenant_id_str}
                    )
                )

                agent_delete_query = """
                MATCH (a:Agent {tenant_id: $tenant_id, id: $agent_id})
                OPTIONAL MATCH (a)-[:OWNS_KB]->(kb:KnowledgeBase {tenant_id: $tenant_id})
                OPTIONAL MATCH (s:Session {tenant_id: $tenant_id, agent_id: $agent_id})
                OPTIONAL MATCH (m:MemoryEntity {tenant_id: $tenant_id, agent_id: $agent_id})
                DETACH DELETE a, kb, s, m
                """
                await retry_neo4j_operation(
                    lambda: neo4j_repo.execute_write(
                        agent_delete_query,
                        {"agent_id": agent_id_str, "tenant_id": tenant_id_str}
                    )
                )
            except Exception as neo_err:
                logger.warning(f"Neo4j cleanup warning for agent {agent_id_str}: {neo_err}")

        # Delete any remaining Neo4j nodes tagged with this user
        try:
            user_graph_delete_query = """
            MATCH (n {tenant_id: $tenant_id, user_id: $user_id})
            DETACH DELETE n
            """
            await retry_neo4j_operation(
                lambda: neo4j_repo.execute_write(
                    user_graph_delete_query,
                    {"user_id": user_id_str, "tenant_id": tenant_id_str}
                )
            )
        except Exception as neo_user_err:
            logger.warning(f"Neo4j user graph nodes cleanup warning: {neo_user_err}")

        # -------------------------------------------------------------
        # 2. PURGE KNOWLEDGE BASES & ATTACHED S3 OBJECTS & DOCUMENT CHUNKS
        # -------------------------------------------------------------
        # Gather all KBs owned by user or attached to user's agents
        kb_stmt = select(KnowledgeBase).where(
            or_(
                KnowledgeBase.user_id == user_uuid,
                KnowledgeBase.agent_id.in_(agent_ids) if agent_ids else False
            )
        )
        kb_res = await db.execute(kb_stmt)
        user_kbs = kb_res.scalars().all()
        kb_ids = [kb.id for kb in user_kbs]
        purged_counts["knowledge_bases"] = len(kb_ids)

        # Delete local parquet datasets and S3 files
        for kb in user_kbs:
            if getattr(kb, "description", "") == "excel_parquet" and kb.parsed_path:
                try:
                    ParquetIngester.delete_active_dataset(kb.parsed_path)
                except Exception as p_err:
                    logger.warning(f"Failed deleting parquet dataset for KB {kb.id}: {p_err}")

            if kb.s3_path:
                try:
                    # Only delete from S3 if no other user references this exact file
                    chk_s3 = select(func.count(KnowledgeBase.id)).where(
                        KnowledgeBase.s3_path == kb.s3_path,
                        ~KnowledgeBase.id.in_(kb_ids) if kb_ids else True
                    )
                    s3_use_res = await db.execute(chk_s3)
                    if (s3_use_res.scalar() or 0) == 0:
                        await s3_service.delete_file_by_url(kb.s3_path)
                except Exception as s3_err:
                    logger.warning(f"Failed deleting S3 file for KB {kb.id}: {s3_err}")

        if kb_ids:
            # Purge document chunks and derived data
            chunks_del = await db.execute(delete(DocumentChunk).where(DocumentChunk.kb_id.in_(kb_ids)))
            purged_counts["document_chunks"] = chunks_del.rowcount or len(kb_ids)

            await db.execute(delete(DocumentTableRow).where(DocumentTableRow.kb_id.in_(kb_ids)))
            await db.execute(delete(DocumentEntity).where(DocumentEntity.document_id.in_(kb_ids)))
            await db.execute(delete(DocumentSection).where(DocumentSection.document_id.in_(kb_ids)))
            await db.execute(delete(DocumentIngestionRun).where(DocumentIngestionRun.document_id.in_(kb_ids)))
            await db.execute(delete(DatabaseConnection).where(DatabaseConnection.kb_id.in_(kb_ids)))
            await db.execute(delete(AnalyticsQueryLog).where(AnalyticsQueryLog.kb_id.in_(kb_ids)))
            await db.execute(delete(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids)))

        # -------------------------------------------------------------
        # 3. PURGE DATABASE KNOWLEDGEBASES
        # -------------------------------------------------------------
        try:
            from app.modules.database_knowledgebase.models import DatabaseKnowledgebase
            db_kbs_del = await db.execute(delete(DatabaseKnowledgebase).where(DatabaseKnowledgebase.user_id == user_uuid))
            purged_counts["database_knowledgebases"] = db_kbs_del.rowcount or 0
        except Exception:
            purged_counts["database_knowledgebases"] = 0

        # -------------------------------------------------------------
        # 4. PURGE CHAT SESSIONS & CHAT MESSAGES
        # -------------------------------------------------------------
        session_stmt = select(ChatSession.id).where(
            or_(
                ChatSession.user_id == user_uuid,
                ChatSession.agent_id.in_(agent_ids) if agent_ids else False
            )
        )
        session_res = await db.execute(session_stmt)
        user_session_ids = session_res.scalars().all()
        purged_counts["chat_sessions"] = len(user_session_ids)

        if user_session_ids:
            msg_del = await db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(user_session_ids)))
            purged_counts["chat_messages"] = msg_del.rowcount or 0
            await db.execute(delete(ChatSession).where(ChatSession.id.in_(user_session_ids)))

        # -------------------------------------------------------------
        # 5. PURGE AGENTS FROM POSTGRESQL
        # -------------------------------------------------------------
        if agent_ids:
            await db.execute(delete(Agent).where(Agent.id.in_(agent_ids)))

        # -------------------------------------------------------------
        # 6. PURGE MEMORIES & USER PREFERENCES
        # -------------------------------------------------------------
        mem_del = await db.execute(
            text("DELETE FROM episodic_memories WHERE user_id = :uid OR user_id = :u_uuid"),
            {"uid": user_id_str, "u_uuid": str(user_uuid)}
        )
        purged_counts["episodic_memories"] = mem_del.rowcount or 0

        pref_del = await db.execute(
            text("DELETE FROM user_preferences WHERE user_id = :uid OR user_id = :u_uuid"),
            {"uid": user_id_str, "u_uuid": str(user_uuid)}
        )
        purged_counts["user_preferences"] = pref_del.rowcount or 0

        # -------------------------------------------------------------
        # 7. PURGE API KEYS & TOKENS
        # -------------------------------------------------------------
        keys_del = await db.execute(delete(APIKey).where(APIKey.user_id == user_uuid))
        purged_counts["api_keys"] = keys_del.rowcount or 0

        await db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user_uuid))
        await db.execute(delete(TokenBlacklist).where(TokenBlacklist.user_id == user_uuid))

        # -------------------------------------------------------------
        # 8. PURGE PROCESSING JOBS, WIDGETS, PERSONALITIES, INTEGRATIONS
        # -------------------------------------------------------------
        try:
            await db.execute(text("DELETE FROM processing_jobs WHERE user_id = :uid"), {"uid": str(user_uuid)})
            await db.execute(text("DELETE FROM widget_customizations WHERE user_id = :uid"), {"uid": str(user_uuid)})
            await db.execute(text("DELETE FROM widget_embed_configs WHERE user_id = :uid"), {"uid": str(user_uuid)})
            await db.execute(text("DELETE FROM personalities WHERE user_id = :uid"), {"uid": str(user_uuid)})
            await db.execute(text("DELETE FROM gmail_messages WHERE user_id = :uid"), {"uid": user_id_str})
            await db.execute(text("DELETE FROM gmail_sync_state WHERE user_id = :uid"), {"uid": user_id_str})
            await db.execute(text("DELETE FROM slack_connections WHERE installed_by_user_id = :uid"), {"uid": user_id_str})
        except Exception as aux_err:
            logger.warning(f"Auxiliary tables cleanup notice: {aux_err}")

        # -------------------------------------------------------------
        # 9. PURGE USER PROFILE RECORD
        # -------------------------------------------------------------
        prof_del = await db.execute(delete(UserProfile).where(UserProfile.user_id == user_uuid))
        purged_counts["user_profile"] = prof_del.rowcount or 1

        # -------------------------------------------------------------
        # 10. PURGE USER LOGIN ACCOUNT RECORD
        # -------------------------------------------------------------
        user_del = await db.execute(delete(User).where(User.id == user_uuid))
        purged_counts["user_account"] = user_del.rowcount or 1

        # COMMIT ALL CLEANUP ATOMICALLY
        await db.commit()

        logger.info(
            f"✅ COMPLETE ACCOUNT PURGE SUCCESSFUL for {user_email}. "
            f"Purged: {purged_counts}"
        )

        return schemas.DeleteAccountResponse(
            success=True,
            message="User account, profile, and all associated resources, agents, files, memories, and storage were permanently deleted.",
            user_id=user_id_str,
            email=user_email,
            deleted_at=datetime.utcnow(),
            purged_resources=purged_counts,
        )

    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Failed to completely delete account for user {user_email}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to complete account deletion: {str(e)}",
        )
