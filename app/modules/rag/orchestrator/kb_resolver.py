import logging
from typing import List, Optional
from app.modules.knowledge_bases.models import KnowledgeBase

logger = logging.getLogger(__name__)

class KBResolver:
    """
    Resolves an explicit user query to a specific Knowledge Base by performing
    exact or substring matches against KB aliases and canonical names.
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = str(tenant_id)

    def resolve(self, query: str, kbs: List[KnowledgeBase]) -> Optional[str]:
        """
        Returns the ID of the resolved KB, or None if no high-confidence match is found.
        """
        query_lower = query.lower()

        # First pass: look for exact occurrences of canonical names or aliases in the query
        for kb in kbs:
            kb_id = str(kb.id)
            
            # Check canonical name
            canonical_name = getattr(kb, "canonical_name", None)
            if canonical_name and canonical_name.strip().lower() in query_lower:
                logger.info(f"[KB_RESOLVER] Resolved '{canonical_name}' -> KB {kb_id} (match_type=canonical_name)")
                return kb_id
            
            # Check aliases
            aliases = getattr(kb, "aliases", []) or []
            if isinstance(aliases, list):
                for alias in aliases:
                    if alias and alias.strip().lower() in query_lower:
                        logger.info(f"[KB_RESOLVER] Resolved alias '{alias}' -> KB {kb_id} (match_type=alias)")
                        return kb_id
                        
            # Check name (fallback to existing behavior/filename match)
            kb_name = getattr(kb, "name", None)
            if kb_name:
                clean_name = kb_name.lower().replace(".pdf", "").replace(".csv", "").replace(".docx", "")
                if len(clean_name) > 4 and clean_name in query_lower:
                    logger.info(f"[KB_RESOLVER] Resolved KB name '{clean_name}' -> KB {kb_id} (match_type=kb_name)")
                    return kb_id

        logger.info("[KB_RESOLVER] No direct alias match found. Returning None.")
        return None
