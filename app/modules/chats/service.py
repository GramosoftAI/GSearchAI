"""Chat Service - Business logic for chat history and memory injection

ARCHITECTURE:
    ChatService wraps around the existing RAGService WITHOUT modifying it.
    Memory injection is done by augmenting the query string with conversation
    history BEFORE passing it to RAGService.generate_answer().

NON-BREAKING DESIGN:
    - RAGService.generate_answer() signature is UNCHANGED
    - Memory context is prepended to the query string
    - If memory injection fails, the original query is used (graceful fallback)
    - ChatService is a NEW layer on top, not a modification

MEMORY INJECTION STRATEGY:
    1. Load last N messages from session (default: 10 messages = 5 turns)
    2. Format as "CONVERSATION HISTORY:" block
    3. Append "CURRENT QUESTION:" with the user's new message
    4. Pass the augmented string as the query to RAGService

    The LLM sees both KB context (from RAG pipeline) AND conversation context
    (from memory injection), enabling coherent multi-turn conversations.

MEMORY WINDOW:
    - Default: 10 messages (5 user + 5 assistant = 5 turns)
    - Configurable per request (memory_window param)
    - Only recent messages loaded (not entire history)
    - Token-efficient: ~200-400 tokens for 5 turns
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from .repository import ChatRepository
from .models import ChatSession, ChatMessage
from ..rag.service import RAGService
from ..knowledge_bases.repository import KnowledgeBaseRepository
from ...core.memory.consolidation import MemoryConsolidator
from ...core.memory.personalization import PersonalMemoryService

logger = logging.getLogger(__name__)

# Default memory window: 10 messages = 5 conversation turns
DEFAULT_MEMORY_WINDOW = 10
# Max memory window to prevent token overflow
MAX_MEMORY_WINDOW = 20


class ChatService:
    """
    Chat service - orchestrates conversation persistence and memory injection.

    RESPONSIBILITIES:
    1. Session lifecycle (create, list, delete)
    2. Message persistence (save user + assistant messages)
    3. Memory injection (augment RAG query with conversation history)
    4. RAG orchestration (call existing RAGService with augmented query)

    MULTI-TENANCY:
    - tenant_id passed at init (from middleware)
    - All operations scoped to tenant
    - RAGService inherits tenant context
    """

    def __init__(self, db: AsyncSession, tenant_id: str):
        """
        Initialize Chat service for tenant.

        Args:
            db: Database session
            tenant_id: Tenant UUID (from middleware, never from request)
        """
        self.db = db
        self.tenant_id = tenant_id
        self.chat_repo = ChatRepository(db, tenant_id)
        self.rag_service = RAGService(db=db, tenant_id=tenant_id)
        self.kb_repo = KnowledgeBaseRepository(db, tenant_id)

    # ========================================================================
    # SESSION MANAGEMENT
    # ========================================================================

    async def create_session(
        self,
        agent_id: str,
        user_id: str,
        title: Optional[str] = None,
    ) -> ChatSession:
        """
        Create a new chat session.

        Args:
            agent_id: Agent UUID
            user_id: User UUID
            title: Optional title (auto-generated if omitted)

        Returns:
            Created ChatSession
        """
        session = await self.chat_repo.create_session(
            agent_id=agent_id,
            user_id=user_id,
            title=title or "New Conversation",
        )
        await self.db.commit()

        logger.info(f" New chat session created: {session.id}")
        return session

    async def list_sessions(
        self,
        agent_id: str,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        include_messages: bool = True,
    ) -> tuple:
        """
        List chat sessions for a user+agent pair.

        Args:
            agent_id: Agent UUID
            user_id: User UUID
            limit: Max results
            offset: Pagination offset
            include_messages: Whether to load and attach messages to sessions

        Returns:
            Tuple of (sessions, total_count)
        """
        sessions, total = await self.chat_repo.list_sessions_by_agent(
            agent_id=agent_id,
            user_id=user_id,
            limit=limit,
            offset=offset,
        )

        if not sessions:
            return [], total

        if include_messages:
            session_ids = [s.id for s in sessions]
            messages = await self.chat_repo.get_messages_for_sessions(session_ids)

            # Group messages by session_id
            from collections import defaultdict
            messages_by_session = defaultdict(list)
            for msg in messages:
                messages_by_session[msg.session_id].append(msg)

            # Attach messages to session models
            for session in sessions:
                session.messages = messages_by_session.get(session.id, [])

        return sessions, total

    async def get_session_with_messages(
        self,
        session_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get a session with all its messages.

        Args:
            session_id: Session UUID

        Returns:
            Dict with session metadata and messages, or None
        """
        session = await self.chat_repo.get_session_by_id(session_id)
        if not session:
            return None

        messages = await self.chat_repo.get_messages(session_id)

        return {
            "session": session,
            "messages": messages,
        }

    async def update_session(
        self,
        session_id: str,
        title: Optional[str] = None,
    ) -> Optional[ChatSession]:
        """
        Update session metadata (e.g., rename).

        Args:
            session_id: Session UUID
            title: New title

        Returns:
            Updated session or None
        """
        session = await self.chat_repo.update_session(
            session_id=session_id,
            title=title,
        )
        if session:
            await self.db.commit()
        return session

    async def delete_session(self, session_id: str) -> bool:
        """
        Soft-delete a chat session.

        Args:
            session_id: Session UUID

        Returns:
            True if deleted, False if not found
        """
        deleted = await self.chat_repo.soft_delete_session(session_id)
        if deleted:
            await self.db.commit()
            logger.info(f" Chat session deleted: {session_id}")
        return deleted

    # ========================================================================
    # SEND MESSAGE (Core Feature)
    # ========================================================================

    async def send_message(
        self,
        agent_id: str,
        user_id: str,
        message: str,
        session_id: Optional[str] = None,
        top_k: int = 10,
        max_depth: int = 2,
        memory_window: int = DEFAULT_MEMORY_WINDOW,
    ) -> Dict[str, Any]:
        """
        Send a message to an agent and get a response.

        CRITICAL FLOW:
        1. Create or retrieve session
        2. Save user message
        3. Load conversation history (memory)
        4. Augment query with memory context
        5. Call RAGService.generate_answer() (EXISTING - UNTOUCHED)
        6. Save assistant response
        7. Return response with session ID

        NON-BREAKING:
        - RAGService is called with augmented query string
        - No changes to RAGService signature or logic
        - Memory injection is purely additive

        Args:
            agent_id: Agent UUID
            user_id: User UUID
            message: User's message text
            session_id: Existing session ID (creates new if None)
            top_k: RAG seed chunks
            max_depth: RAG graph expansion depth
            memory_window: Number of recent messages for context

        Returns:
            Dict with answer, sources, session_id, memory metadata
        """
        logger.info(
            f" ChatService: message for agent={agent_id}, "
            f"session={session_id or 'NEW'}, len={len(message)}"
        )

        # ============= STEP 1: GET OR CREATE SESSION =============
        if session_id:
            session = await self.chat_repo.get_session_by_id(session_id)
            if not session:
                logger.warning(f"Session {session_id} not found, creating new")
                session = await self.chat_repo.create_session(
                    agent_id=agent_id,
                    user_id=user_id,
                )
        else:
            session = await self.chat_repo.create_session(
                agent_id=agent_id,
                user_id=user_id,
            )

        session_id = str(session.id)
        logger.debug(f"Using session: {session_id}")

        # ============= STEP 2: SAVE USER MESSAGE =============
        user_msg = await self.chat_repo.add_message(
            session_id=session_id,
            role="user",
            content=message,
        )
        logger.debug(f"Saved user message at position {user_msg.position}")

        # ============= STEP 3: LOAD MEMORY (CONVERSATION HISTORY & USER PREFERENCES) =============
        memory_used = False
        augmented_query = message
        conversation_turns = 0

        # 3a. Load long-term persistent user preferences and episodic memory from memory-api
        episodic_guidance = ""
        try:
            import httpx
            import os
            memory_api_base = os.getenv("MEMORY_API_BASE_URL", "http://memory-api:8001").rstrip("/")
            candidate_urls = [
                f"{memory_api_base}/api/v1/memory/process-turn",
                "http://localhost:8003/api/v1/memory/process-turn",
                "http://127.0.0.1:8003/api/v1/memory/process-turn",
                "http://localhost:8002/api/v1/memory/process-turn",
                "http://memory-api:8001/api/v1/memory/process-turn"
            ]
            urls = list(dict.fromkeys(candidate_urls))
            async with httpx.AsyncClient() as client:
                for url in urls:
                    try:
                        resp = await client.post(
                            url,
                            json={
                                "query": message,
                                "session_id": session_id,
                                "agent_id": agent_id,
                                "user_id": user_id,
                                "tenant_id": self.tenant_id
                            },
                            timeout=5.0
                        )
                        if resp.status_code == 200:
                            mem_data = resp.json()
                            episodic_guidance = mem_data.get("guidance_context") or ""
                            break
                    except Exception as e:
                        logger.debug(f"Memory API process-turn attempt {url} failed: {e}")
        except Exception as pe:
            logger.warning(f"Memory API process-turn failed: {pe}")

        # 3b. Load in-session recent conversation turns
        if session.message_count > 1:  # >1 because we just added the user message
            try:
                memory_messages = await self.chat_repo.get_recent_messages(
                    session_id=session_id,
                    count=min(memory_window, MAX_MEMORY_WINDOW),
                )

                # Exclude the message we just added (it's the current question)
                history_messages = [
                    m for m in memory_messages if str(m.id) != str(user_msg.id)
                ]

                if history_messages:
                    augmented_query = self._format_memory_context(
                        history=history_messages,
                        current_query=message,
                    )
                    memory_used = True
                    conversation_turns = sum(
                        1 for m in history_messages if m.role == "user"
                    )

                    logger.info(
                        f" Memory injected: {len(history_messages)} messages, "
                        f"{conversation_turns} turns"
                    )

            except Exception as e:
                # GRACEFUL FALLBACK: If memory fails, use original query
                logger.warning(
                    f" Memory injection failed: {e}. Using original query."
                )
                augmented_query = message
                memory_used = False

        # 3c. Prepend persistent user profile & preference context if available
        if episodic_guidance:
            guidance_block = (
                "### MANDATORY USER PREFERENCES & MEMORY DIRECTIVES\n"
                f"{episodic_guidance}\n\n"
            )
            augmented_query = guidance_block + augmented_query
            memory_used = True

        # ============= STEP 4: RESOLVE KBs (Agent can own multiple KBs) =============
        kbs, _ = await self.kb_repo.list_by_agent(agent_id, limit=10)
        if not kbs:
            # Save error as assistant message
            error_msg = "No knowledge base found for this agent. Please add a knowledge base first."
            await self.chat_repo.add_message(
                session_id=session_id,
                role="assistant",
                content=error_msg,
                metadata={"error": True},
            )
            await self.db.commit()

            return {
                "session_id": session_id,
                "answer": error_msg,
                "sources": [],
                "context": None,
                "message_position": user_msg.position + 1,
                "memory_used": memory_used,
                "conversation_turns": conversation_turns,
            }

        kb_ids = [str(kb.id) for kb in kbs]

        # ============= STEP 5: CALL RAG SERVICE (EXISTING - UNTOUCHED) =============
        logger.debug("Calling RAGService.generate_answer() with augmented query...")
        try:
            rag_response = await self.rag_service.generate_answer(
                query=augmented_query,
                agent_id=agent_id,
                kb_id=kb_ids,
                user_id=user_id,
                top_k=top_k,
                max_depth=max_depth,
            )
        except Exception as e:
            logger.error(f" RAG generation failed: {e}")
            # Save error as assistant message
            error_answer = (
                "I'm sorry, I encountered an error while processing your question. "
                "Please try again."
            )
            await self.chat_repo.add_message(
                session_id=session_id,
                role="assistant",
                content=error_answer,
                metadata={"error": True, "error_detail": str(e)},
            )
            await self.db.commit()

            return {
                "session_id": session_id,
                "answer": error_answer,
                "sources": [],
                "context": None,
                "message_position": user_msg.position + 1,
                "memory_used": memory_used,
                "conversation_turns": conversation_turns,
            }

        # ============= STEP 6: EXTRACT ANSWER =============
        # RAG service returns error dict or success dict
        if "error" in rag_response and rag_response.get("answer") is None:
            answer = rag_response.get(
                "error",
                "I couldn't find relevant information to answer your question.",
            )
            sources = []
            context_info = None
        else:
            answer = rag_response.get("answer", "No answer generated.")
            sources = rag_response.get("sources", [])
            context_info = rag_response.get("context")

        # ============= STEP 7: SAVE ASSISTANT RESPONSE =============
        assistant_metadata = {
            "sources": sources,
            "memory_used": memory_used,
            "conversation_turns": conversation_turns,
        }

        # Add RAG stats if available
        if "stats" in rag_response:
            assistant_metadata["stats"] = rag_response["stats"]
        if "confidence" in rag_response:
            assistant_metadata["confidence"] = rag_response["confidence"]

        assistant_msg = await self.chat_repo.add_message(
            session_id=session_id,
            role="assistant",
            content=answer,
            metadata=assistant_metadata,
        )

        # ============= STEP 8: COMMIT ALL CHANGES =============
        await self.db.commit()
        logger.info(
            f" Chat complete: session={session_id}, "
            f"answer_len={len(answer)}, sources={len(sources)}, "
            f"memory={'ON' if memory_used else 'OFF'}"
        )

        # Trigger Standalone Memory API Save-Turn
        try:
            import httpx
            import os
            memory_api_base = os.getenv("MEMORY_API_BASE_URL", "http://memory-api:8001").rstrip("/")
            candidate_urls = [
                f"{memory_api_base}/api/v1/memory/save-turn",
                "http://localhost:8003/api/v1/memory/save-turn",
                "http://127.0.0.1:8003/api/v1/memory/save-turn",
                "http://localhost:8002/api/v1/memory/save-turn",
                "http://127.0.0.1:8002/api/v1/memory/save-turn",
                "http://memory-api:8001/api/v1/memory/save-turn"
            ]
            urls = list(dict.fromkeys(candidate_urls))
            payload = {
                "query": message,
                "ai_response": answer,
                "session_id": session_id,
                "agent_id": agent_id,
                "user_id": user_id,
                "tenant_id": self.tenant_id,
                "metadata": {"source_doc_count": len(sources)}
            }
            async with httpx.AsyncClient() as client:
                for url in urls:
                    try:
                        resp = await client.post(url, json=payload, timeout=3.0)
                        if resp.status_code == 200:
                            break
                    except Exception as e:
                        logger.debug(f"Memory API save-turn attempt {url} failed: {e}")
        except Exception as me:
            logger.warning(f"Failed to push turn to memory-api save-turn: {me}")

        # ============= STEP 9: MEMORY CONSOLIDATION (Pattern #11) =============
        # Trigger background consolidation to update Knowledge Graph with new facts
        # Feature-flagged: Only runs if triplet extraction is enabled
        from ...core.config import get_settings
        settings = get_settings()

        if settings.use_triplet_extraction:
            try:
                import asyncio
                consolidator = MemoryConsolidator(self.tenant_id)
                # Run as fire-and-forget background task
                asyncio.create_task(
                    consolidator.consolidate_interaction(
                        user_message=message,
                        assistant_message=answer,
                        session_id=session_id
                    )
                )
                logger.debug(f" Consolidation task triggered for session {session_id}")

                # --- ADDED: Personal Memory (Mem0 Pattern) ---
                if settings.use_personal_memory:
                    personal_memory = PersonalMemoryService(self.tenant_id)
                    asyncio.create_task(
                        personal_memory.add_memory(
                            user_id=user_id,
                            message=message
                        )
                    )
                    logger.debug(f" Personal memory task triggered for user {user_id[:8]}")
            except Exception as e:
                logger.warning(f" Failed to trigger memory consolidation: {e}")
        else:
            logger.debug(" Memory consolidation skipped (feature disabled in config)")

        return {
            "session_id": session_id,
            "answer": answer,
            "sources": sources,
            "context": context_info,
            "message_position": assistant_msg.position,
            "memory_used": memory_used,
            "conversation_turns": conversation_turns,
        }

    # ========================================================================
    # MEMORY FORMATTING
    # ========================================================================

    def _format_memory_context(
        self,
        history: List[ChatMessage],
        current_query: str,
    ) -> str:
        """
        Format conversation history into a memory context block
        that is prepended to the user's query.

        OUTPUT FORMAT:
            CONVERSATION HISTORY (for context):
            User: What is GraphRAG?
            Assistant: GraphRAG combines graph databases with RAG...
            User: How does it compare?
            Assistant: Compared to traditional RAG...
            ---
            CURRENT QUESTION: Tell me more about the entity extraction part

        DESIGN DECISIONS:
        - Clear separator between history and current question
        - Role labels (User/Assistant) for LLM comprehension
        - Truncation on long messages to stay within token budget
        - "CONVERSATION HISTORY" label signals the LLM this is context, not instruction

        Args:
            history: List of previous messages (chronological order)
            current_query: The current user message

        Returns:
            Augmented query string with conversation history prepended
        """
        if not history:
            return current_query

        # Build conversation history block
        history_lines = []
        for msg in history:
            role_label = "User" if msg.role == "user" else "Assistant"
            # Truncate long messages to save tokens (max 300 chars per message)
            content = msg.content
            if len(content) > 300:
                content = content[:297] + "..."
            history_lines.append(f"{role_label}: {content}")

        history_block = "\n".join(history_lines)

        # Format augmented query
        augmented = (
            f"CONVERSATION HISTORY (for context):\n"
            f"{history_block}\n"
            f"---\n"
            f"CURRENT QUESTION: {current_query}"
        )

        logger.debug(
            f"Memory context: {len(history)} messages, "
            f"{len(augmented)} chars total"
        )

        return augmented

    async def save_message_feedback(
        self,
        message_id: str,
        feedback_type: str,
        feedback_reason: Optional[str] = None,
        feedback_score: Optional[int] = None,
    ) -> ChatMessage:
        """
        Save feedback for a message.
        """
        # Validate feedback_type
        if feedback_type not in ["thumbs_up", "thumbs_down"]:
            raise ValueError("feedback_type must be either 'thumbs_up' or 'thumbs_down'")

        # Fetch message
        message = await self.chat_repo.get_message_by_id(message_id)
        if not message:
            raise KeyError("Message not found")

        # Ensure message role is assistant
        if message.role != "assistant":
            raise ValueError("Feedback can only be submitted for assistant messages")

        # Save and commit
        updated_message = await self.chat_repo.save_message_feedback(
            message=message,
            feedback_type=feedback_type,
            feedback_reason=feedback_reason,
            feedback_score=feedback_score,
        )
        await self.db.commit()
        return updated_message
