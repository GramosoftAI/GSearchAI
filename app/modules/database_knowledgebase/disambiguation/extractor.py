import logging
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class EntityExtractor:
    """
    Extracts potential entity names from the raw user query.
    Rerouted to the unified local-only resolve_entities function.
    """

    @classmethod
    async def extract_person_names(
        cls,
        query: str,
        canonical_schema: Optional[Any] = None,
        aliases: Optional[Any] = None,
        glossary_terms: Optional[Any] = None,
        session: Optional[AsyncSession] = None,
        tenant_id: Optional[Any] = None,
        kb_id: Optional[Any] = None,
    ) -> list[str]:
        """
        Extract likely person names from a natural language query via unified resolve_entities.
        """
        if not session or not kb_id:
            return []

        from ..knowledge.retrieval.entity_resolver import resolve_entities

        try:
            res = await resolve_entities(
                question=query,
                kb_id=kb_id,
                session=session,
                canonical_schema=canonical_schema,
                tenant_id=tenant_id,
            )
            return list(dict.fromkeys([e.matched_value for e in res.resolved_entities]))
        except Exception as exc:
            logger.warning(f"[EntityExtractor] resolve_entities failed: {exc}")
            return []
