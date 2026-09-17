"""Concept Glossary Feedback Loop & Monotonic Guard

Handles recording system-verified and human-verified mappings into ConceptGlossary,
enforcing monotonic state transitions (LLM_GENERATED -> SYSTEM_VERIFIED -> HUMAN_VERIFIED),
synonym-append-only semantics for human-verified rows, and automated cache invalidation.
"""

import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from ..models.concept_glossary import ConceptGlossary
from .enrichment import GlossaryEnrichmentService

logger = logging.getLogger(__name__)

# State machine hierarchy: higher priority states can never be downgraded
TIER_PRIORITIES = {
    "LLM_GENERATED": 1,
    "SYSTEM_VERIFIED": 2,
    "HUMAN_VERIFIED": 3,
}


class GlossaryFeedbackLoop:
    """
    Manages state transitions and feedback integration for ConceptGlossary items.
    Enforces that system verification NEVER downgrades human-verified rows or unpublishes them.
    """

    @classmethod
    async def record_system_verified_mapping(
        cls,
        session: AsyncSession,
        tenant_id: str,
        table_name: str,
        column_name: str,
        schema_fingerprint: str,
        synonyms: Optional[List[str]] = None,
        business_description: Optional[str] = None,
        semantic_role: Optional[str] = None,
        is_canonical: bool = True,
        strict_review: bool = True,
    ) -> ConceptGlossary:
        """
        Record a system-verified mapping (e.g. from AnswerVerifier passing verification).

        MONOTONIC GUARD:
        - If existing row is HUMAN_VERIFIED:
          - NEVER downgrade confidence_source to SYSTEM_VERIFIED.
          - NEVER flip is_published from True to False (even if strict_review=True).
          - Append new synonyms only, preserving existing metadata.
        - If existing row is SYSTEM_VERIFIED:
          - Append new synonyms, update description if provided, preserve confidence_source.
        - If existing row is LLM_GENERATED or does not exist:
          - Upgrade/insert row with confidence_source = 'SYSTEM_VERIFIED'.
          - If strict_review is True, set is_published = False (draft queue).
        """
        t_id_str = str(tenant_id)
        stmt = select(ConceptGlossary).where(
            and_(
                ConceptGlossary.tenant_id == t_id_str,
                ConceptGlossary.table_name == table_name,
                ConceptGlossary.column_name == column_name,
                ConceptGlossary.schema_fingerprint == schema_fingerprint,
            )
        )
        res = await session.execute(stmt)
        existing = res.scalar_one_or_none()

        incoming_synonyms = [s.strip() for s in (synonyms or []) if s.strip()]

        if existing:
            current_tier = existing.confidence_source or "LLM_GENERATED"

            if current_tier == "HUMAN_VERIFIED":
                # LOAD-BEARING MONOTONIC GUARD: Do NOT downgrade or unpublish!
                # Synonym-append-only
                curr_syns = list(existing.synonyms or [])
                changed = False
                for syn in incoming_synonyms:
                    if syn not in curr_syns:
                        curr_syns.append(syn)
                        changed = True
                if changed:
                    existing.synonyms = curr_syns
                    session.add(existing)
                    await session.flush()
                logger.info(
                    f"Preserved HUMAN_VERIFIED row for {table_name}.{column_name} (synonym-append-only)"
                )
                return existing

            elif current_tier == "SYSTEM_VERIFIED":
                # Merge synonyms and optionally update description
                curr_syns = list(existing.synonyms or [])
                for syn in incoming_synonyms:
                    if syn not in curr_syns:
                        curr_syns.append(syn)
                existing.synonyms = curr_syns
                if business_description:
                    existing.business_description = business_description
                if semantic_role:
                    existing.semantic_role = semantic_role
                if not strict_review:
                    existing.is_published = True
                session.add(existing)
                await session.flush()
                return existing

            else:
                # Upgrade LLM_GENERATED -> SYSTEM_VERIFIED
                existing.confidence_source = "SYSTEM_VERIFIED"
                curr_syns = list(existing.synonyms or [])
                for syn in incoming_synonyms:
                    if syn not in curr_syns:
                        curr_syns.append(syn)
                existing.synonyms = curr_syns
                if business_description:
                    existing.business_description = business_description
                if semantic_role:
                    existing.semantic_role = semantic_role
                existing.is_published = False if strict_review else True
                session.add(existing)
                await session.flush()
                logger.info(
                    f"Upgraded {table_name}.{column_name} to SYSTEM_VERIFIED (is_published={existing.is_published})"
                )
                return existing

        # Create new entry under SYSTEM_VERIFIED
        new_entry = ConceptGlossary(
            tenant_id=t_id_str,
            table_name=table_name,
            column_name=column_name,
            business_description=business_description or f"System verified concept for {table_name}.{column_name}",
            synonyms=incoming_synonyms,
            semantic_role=semantic_role or "DESCRIPTIVE",
            is_canonical=is_canonical,
            is_published=False if strict_review else True,
            confidence_source="SYSTEM_VERIFIED",
            schema_fingerprint=schema_fingerprint,
            orphaned_by_drift=False,
        )
        session.add(new_entry)
        await session.flush()
        return new_entry

    @classmethod
    async def record_human_verified_mapping(
        cls,
        session: AsyncSession,
        tenant_id: str,
        table_name: str,
        column_name: str,
        schema_fingerprint: str,
        synonyms: Optional[List[str]] = None,
        business_description: Optional[str] = None,
        semantic_role: Optional[str] = None,
        is_canonical: bool = True,
    ) -> ConceptGlossary:
        """
        Record a human-verified mapping (e.g. from operator confirmation or ambiguity clarification).
        Sets confidence_source = 'HUMAN_VERIFIED', is_published = True, registers semantic role,
        and invalidates tenant retrieval cache.
        """
        t_id_str = str(tenant_id)

        # Register semantic role if provided
        if semantic_role:
            GlossaryEnrichmentService.register_semantic_role(
                semantic_role, confidence_source="HUMAN_VERIFIED"
            )

        stmt = select(ConceptGlossary).where(
            and_(
                ConceptGlossary.tenant_id == t_id_str,
                ConceptGlossary.table_name == table_name,
                ConceptGlossary.column_name == column_name,
                ConceptGlossary.schema_fingerprint == schema_fingerprint,
            )
        )
        res = await session.execute(stmt)
        existing = res.scalar_one_or_none()

        incoming_synonyms = [s.strip() for s in (synonyms or []) if s.strip()]

        if existing:
            existing.confidence_source = "HUMAN_VERIFIED"
            existing.is_published = True
            curr_syns = list(existing.synonyms or [])
            for syn in incoming_synonyms:
                if syn not in curr_syns:
                    curr_syns.append(syn)
            existing.synonyms = curr_syns
            if business_description:
                existing.business_description = business_description
            if semantic_role:
                existing.semantic_role = semantic_role
            session.add(existing)
            target_entry = existing
        else:
            new_entry = ConceptGlossary(
                tenant_id=t_id_str,
                table_name=table_name,
                column_name=column_name,
                business_description=business_description or f"Human verified concept for {table_name}.{column_name}",
                synonyms=incoming_synonyms,
                semantic_role=semantic_role or "DESCRIPTIVE",
                is_canonical=is_canonical,
                is_published=True,
                confidence_source="HUMAN_VERIFIED",
                schema_fingerprint=schema_fingerprint,
                orphaned_by_drift=False,
            )
            session.add(new_entry)
            target_entry = new_entry

        await session.flush()

        # Invalidate retrieval cache for tenant
        try:
            from ..retrieval.cache import SchemaRetrievalCache
            SchemaRetrievalCache.get_instance().invalidate_tenant(t_id_str)
        except Exception as e:
            logger.warning(f"Could not invalidate retrieval cache for tenant {t_id_str}: {e}")

        logger.info(
            f"Successfully recorded HUMAN_VERIFIED mapping for {table_name}.{column_name} (tenant={t_id_str})"
        )
        return target_entry

    @classmethod
    async def confirm_clarification_choice(
        cls,
        session: AsyncSession,
        tenant_id: str,
        table_name: str,
        chosen_column: str,
        user_query: str,
        schema_fingerprint: str,
        semantic_role: Optional[str] = None,
        business_description: Optional[str] = None,
    ) -> ConceptGlossary:
        """
        Confirms a user's clarification choice when resolving an ambiguous query,
        recording it as HUMAN_VERIFIED and appending the query phrase as a synonym.
        """
        clean_q = user_query.strip()
        synonyms = [clean_q] if clean_q else []
        return await cls.record_human_verified_mapping(
            session=session,
            tenant_id=tenant_id,
            table_name=table_name,
            column_name=chosen_column,
            schema_fingerprint=schema_fingerprint,
            synonyms=synonyms,
            business_description=business_description,
            semantic_role=semantic_role,
        )
