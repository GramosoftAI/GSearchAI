import os
import json
import logging
from typing import AsyncGenerator, Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from .service import RAGService
from ..chats.service import ChatService
from ...core.query_rewriter import QueryRewriter
from .services.memory_manager import MemoryManager
from .stream.response_chunk import ChunkType, ResponseChunk, StatusChunk, DoneChunk, ContentChunk, ErrorChunk, MetadataChunk, MetadataPayload
from ...core.config import settings

logger = logging.getLogger(__name__)

class ChatPipeline:
    """
    Centralized orchestration pipeline for all chat interactions (Website, Embed, API).
    """

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.rag_service = RAGService(db=db, tenant_id=tenant_id)
        self.chat_service = ChatService(db=db, tenant_id=tenant_id)
        self.query_rewriter = QueryRewriter()
        self.memory_manager = MemoryManager()

    async def stream_response(
        self,
        query: str,
        session_id: str,
        agent_id: str,
        user_id: str,
        kb_ids: List[str],
        enhance_prompt: bool = False,
        top_k: int = 10,
        max_depth: int = 2,
    ) -> AsyncGenerator[ResponseChunk, None]:
        
        # 1. MEMORY-API TRIAGE + RECALL
        mem_result = await self.memory_manager.process_turn(
            query=query,
            session_id=session_id,
            agent_id=agent_id,
            user_id=user_id,
            tenant_id=self.tenant_id
        )
        
        episodic_guidance = mem_result["episodic_guidance"]
        is_feedback_only = mem_result["is_feedback_only"]
        is_history_query = mem_result["is_history_query"]
        router_category = mem_result["router_category"]

        # 2. SAVE USER MESSAGE
        user_msg = await self.chat_service.chat_repo.add_message(
            session_id=session_id, role="user", content=query
        )
        await self.db.commit()

        # Handle feedback-only turns
        if is_feedback_only:
            acknowledgment = "Understood! I've updated your preferences and saved them to my long-term memory."
            await self.memory_manager.save_turn(
                query=query,
                ai_response=acknowledgment,
                session_id=session_id,
                agent_id=agent_id,
                user_id=user_id,
                tenant_id=self.tenant_id,
                is_feedback_only=True,
                metadata={"router_category": router_category},
            )
            
            await self.chat_service.chat_repo.add_message(
                session_id=session_id,
                role="assistant",
                content=acknowledgment,
                metadata={"feedback_turn": True},
            )
            await self.db.commit()
            
            yield StatusChunk(text="Preferences recorded successfully.")
            yield DoneChunk()
            return

        # 3. META-HISTORY SHORT-CIRCUIT (COGNEE STRUCTURAL RECALL)
        if is_history_query:
            history_prompt = (
                "You are a helpful assistant. The user is asking about past chat history.\n"
                "Answer their question using ONLY the provided conversation context and graph facts below.\n\n"
                f"{episodic_guidance if episodic_guidance else 'No previous chat history found for this user.'}\n\n"
                f"User Question: {query}\n\n"
                "Provide a clear, concise summary of what was discussed:"
            )

            full_response_text = ""
            history_stream_error = None
            try:
                full_response_text = await self.rag_service.llm_client.generate_cloud(prompt=history_prompt)
                yield ContentChunk(text=full_response_text)
            except Exception as direct_err:
                logger.error(
                    f"Direct memory streaming failed: {direct_err}",
                    exc_info=True,
                )
                history_stream_error = str(direct_err)
                full_response_text = "I attempted to review our past chats, but ran into an error processing the summaries."
                yield ErrorChunk(text=full_response_text)
            
            await self.chat_service.chat_repo.add_message(
                session_id=session_id,
                role="assistant",
                content=full_response_text,
                metadata={
                    "memory_used": True,
                    "direct_history_recall": True,
                    "error": history_stream_error,
                },
            )
            await self.db.commit()

            await self.memory_manager.save_turn(
                query=query,
                ai_response=full_response_text,
                session_id=session_id,
                agent_id=agent_id,
                user_id=user_id,
                tenant_id=self.tenant_id,
                metadata={"router_category": router_category}
            )

            yield DoneChunk()
            return

        # 4. FETCH RECENT HISTORY
        history_messages = []
        conversation_turns = 0
        session = await self.chat_service.chat_repo.get_session_by_id(session_id)
        if session and session.message_count > 1:
            try:
                memory_messages = await self.chat_service.chat_repo.get_recent_messages(
                    session_id=session_id, count=10
                )
                history_messages = [
                    m for m in memory_messages if str(m.id) != str(user_msg.id)
                ]
                conversation_turns = sum(
                    1 for m in history_messages if m.role == "user"
                )
            except Exception as me:
                logger.warning(f"Failed to fetch recent memory messages: {me}")

        # 5. PROMPT ENHANCER / QUERY REWRITING
        enhanced_query = query
        is_enhanced = False
        if enhance_prompt or history_messages:
            try:
                rewritten = await self.query_rewriter.rewrite_query(
                    query, history=history_messages
                )
                if rewritten and rewritten != query:
                    enhanced_query = rewritten
                    is_enhanced = True
            except Exception as e:
                logger.error(f"Prompt enhancement failed: {e}", exc_info=True)

        # 6. PREPARE CONTEXT FOR FINAL LLM GENERATION
        chat_history_str = None
        memory_used = False
        if history_messages:
            chat_history_str = self.chat_service._format_memory_context(
                history=history_messages, current_query=enhanced_query
            )
            memory_used = True

        if episodic_guidance:
            guidance_block = (
                "### MANDATORY USER PREFERENCES & MEMORY DIRECTIVES\n"
                f"{episodic_guidance}\n"
            )
            chat_history_str = guidance_block + (
                "\n" + chat_history_str if chat_history_str else ""
            )
            memory_used = True

        skip_search = False
        if enhanced_query.startswith("[HISTORY_FILTER]"):
            skip_search = True
            enhanced_query = enhanced_query.replace("[HISTORY_FILTER]", "").strip()

        # 7. STREAM RAG ANSWER FROM KNOWLEDGE BASE
        full_response_text = ""
        sources = []
        has_error = False
        token_usage = {}

        def capture_usage(usage_dict):
            token_usage.update(usage_dict)

        from .stream.pipeline_context import PipelineContext
        pipeline_context = PipelineContext(
            query=enhanced_query,
            session_id=session_id,
            agent_id=agent_id,
            user_id=user_id,
            tenant_id=self.tenant_id,
            kb_ids=kb_ids,
            rewritten_query=enhanced_query if is_enhanced else None,
            memory_context=chat_history_str,
            router_category=router_category,
            is_feedback_only=is_feedback_only,
            is_history_query=is_history_query
        )

        async for chunk in self.rag_service.stream_rag_answer(
            context=pipeline_context,
            on_usage_callback=capture_usage,
            skip_search=skip_search,
            top_k=top_k,
            max_depth=max_depth
        ):
            try:
                parsed = json.loads(chunk)
                if isinstance(parsed, dict):
                    if parsed.get("type") == "metadata":
                        parsed["session_id"] = session_id
                        if is_enhanced:
                            parsed["is_enhanced"] = True
                            parsed["enhanced_query"] = enhanced_query
                        sources = parsed.get("sources", [])
                        
                        yield MetadataChunk(data=MetadataPayload(**parsed))
                        continue

                    elif "error" in parsed:
                        yield ErrorChunk(text=parsed["error"])
                        full_response_text = parsed["error"]
                        has_error = True
                        break
            except (json.JSONDecodeError, TypeError):
                pass

            yield ContentChunk(text=chunk)
            full_response_text += chunk

        # 8. PERSIST ASSISTANT MESSAGE
        assistant_metadata = {
            "sources": sources,
            "memory_used": memory_used,
            "conversation_turns": conversation_turns,
        }
        if has_error:
            assistant_metadata["error"] = True

        if token_usage:
            assistant_metadata["stats"] = {
                "llm_input_tokens": token_usage.get("prompt_tokens", 0),
                "llm_output_tokens": token_usage.get("completion_tokens", 0),
                "total_tokens": token_usage.get("total_tokens", 0),
                "model": os.environ.get("MODEL_ANSWER", getattr(settings, "model_answer", "deepseek-ai/DeepSeek-V3-2")),
            }
            
        await self.chat_service.chat_repo.add_message(
            session_id=session_id,
            role="assistant",
            content=full_response_text,
            metadata=assistant_metadata,
        )
        await self.db.commit()

        # 9. SAVE TURN TO MEMORY API
        if not has_error and full_response_text:
            await self.memory_manager.save_turn(
                query=query,
                ai_response=full_response_text,
                session_id=session_id,
                agent_id=agent_id,
                user_id=user_id,
                tenant_id=self.tenant_id,
                metadata={
                    "source_doc_count": len(sources),
                    "router_category": router_category,
                }
            )

        # 10. SIGNAL COMPLETION
        if not has_error:
            yield DoneChunk()
