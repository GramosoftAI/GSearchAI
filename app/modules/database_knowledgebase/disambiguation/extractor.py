import re
import uuid
import logging
from typing import Any, Dict, List, Optional, Set
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class EntityExtractor:
    """
    Extracts potential person names from the raw user query.
    Uses stop-word filtering, domain nouns, schema exclusion, and kb2_entity_values lookup
    to ensure only legitimate person names are treated as candidates.
    """
    
    # Comprehensive stop words: common English + database/business domain terms
    STOP_WORDS = {
        # Common English
        "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "by", "from",
        "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
        "do", "does", "did", "can", "could", "should", "would", "will", "shall",
        "may", "might", "must", "need", "dare",
        "and", "or", "not", "no", "nor", "but", "if", "then", "else", "so", "than",
        "show", "me", "my", "mine", "your", "yours", "his", "her", "hers", "its",
        "our", "ours", "their", "theirs", "this", "that", "these", "those",
        "what", "which", "who", "whom", "whose", "how", "nhow", "where", "when", "why",
        "i", "you", "he", "she", "it", "we", "they",
        "am", "im",
        "get", "got", "find", "list", "give", "tell", "name", "named", "check", "search", "view", "fetch",
        "please", "just", "also", "only", "about", "like", "want", "know",
        "very", "much", "many", "some", "any", "all", "each", "every",
        "more", "most", "less", "least", "few", "several",
        "here", "there", "up", "down", "out", "off", "over", "under",
        "between", "through", "during", "before", "after", "above", "below",
        # Time words
        "yesterday", "today", "tomorrow", "last", "next", "ago", "since",
        "week", "month", "year", "day", "date", "time", "hour", "hours", "minute", "minutes", "second", "seconds",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "january", "february", "march", "april", "may", "june", 
        "july", "august", "september", "october", "november", "december",
        # Database / business domain
        "work", "worked", "working", "package", "packages", "task", "tasks", "project", "projects",
        "user", "users", "author", "assignee", "assigned", "created", "updated",
        "status", "type", "priority", "id", "total", "count", "number", "sum", "average",
        "table", "column", "row", "data", "database", "query", "report", "result",
        "select", "filter", "sort", "group", "order", "limit",
        "first", "second", "third", "new", "old", "recent", "current", "previous",
        "pending", "approved", "rejected", "completed", "cancelled",
        "timesheet", "overtime", "shortage", "balance", "deficit",
        # Generic linguistic modifiers, quantifiers, and aggregation qualifiers
        "overall", "entire", "complete", "general", "combined", "net", "gross",
        "cumulative", "grand", "aggregate", "aggregated", "aggregating", "aggregation",
        "whole", "full", "totaling", "across", "altogether", "comprehensively",
        "universal", "composite", "global", "approximate", "exact", "standard",
        "single", "multiple", "together", "joint", "jointly", "separately", "individually",
    }

    # Small generic set of common domain nouns (and variants)
    GENERIC_DOMAIN_WORDS = {
        "employee", "employees",
        "worker", "workers", "staff",
        "absent", "absentees", "absenteeism",
        "present", "presenteeism",
        "attend", "attended", "attending", "attendance",
        "leave", "leaves",
        "progress",
        "eod",
        "today", "yesterday", "tomorrow",
    }
    
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
        Extract likely person names from a natural language query.
        
        Strict filtering rules:
        1. Excludes STOP_WORDS and GENERIC_DOMAIN_WORDS.
        2. Excludes any token matching a table name, column name, alias, or glossary term
           from the KB's own schema snapshot.
        3. When database session and kb_id are provided, ONLY treats a token as a candidate
           if it matches a record in kb2_entity_values.
        """
        excluded_tokens: Set[str] = set(cls.STOP_WORDS)
        excluded_tokens.update(cls.GENERIC_DOMAIN_WORDS)

        # 1. Schema tables and columns from canonical_schema
        if canonical_schema:
            if hasattr(canonical_schema, "schemas") and isinstance(canonical_schema.schemas, dict):
                for s in canonical_schema.schemas.values():
                    if hasattr(s, "tables") and isinstance(s.tables, dict):
                        for t_name, t_schema in s.tables.items():
                            excluded_tokens.add(t_name.lower())
                            for part in re.split(r'[_.\s]+', t_name):
                                if len(part) >= 2:
                                    excluded_tokens.add(part.lower())
                            if hasattr(t_schema, "columns") and isinstance(t_schema.columns, dict):
                                for c_name in t_schema.columns.keys():
                                    excluded_tokens.add(c_name.lower())
                                    for part in re.split(r'[_.\s]+', c_name):
                                        if len(part) >= 2:
                                            excluded_tokens.add(part.lower())
            elif hasattr(canonical_schema, "all_tables"):
                for t in canonical_schema.all_tables:
                    t_name = getattr(t, "table_name", "")
                    if t_name:
                        excluded_tokens.add(t_name.lower())
                        for part in re.split(r'[_.\s]+', t_name):
                            if len(part) >= 2:
                                excluded_tokens.add(part.lower())
                    if hasattr(t, "columns") and isinstance(t.columns, dict):
                        for c_name in t.columns.keys():
                            excluded_tokens.add(c_name.lower())
                            for part in re.split(r'[_.\s]+', c_name):
                                if len(part) >= 2:
                                    excluded_tokens.add(part.lower())

        # 2. Aliases
        if aliases:
            if isinstance(aliases, dict):
                for tbl, alias_list in aliases.items():
                    excluded_tokens.add(tbl.lower())
                    if isinstance(alias_list, (list, set, tuple)):
                        for a in alias_list:
                            if isinstance(a, str):
                                excluded_tokens.add(a.lower())
            elif isinstance(aliases, (list, set, tuple)):
                for a in aliases:
                    if isinstance(a, str):
                        excluded_tokens.add(a.lower())

        # 3. Glossary terms
        if glossary_terms:
            if isinstance(glossary_terms, (list, set, tuple)):
                for g in glossary_terms:
                    if isinstance(g, str):
                        excluded_tokens.add(g.lower())

        if session and tenant_id:
            try:
                from ..models.concept_glossary import ConceptGlossary
                t_id_str = str(tenant_id)
                g_stmt = select(
                    ConceptGlossary.table_name,
                    ConceptGlossary.column_name,
                    ConceptGlossary.synonyms,
                    ConceptGlossary.semantic_role,
                ).where(
                    ConceptGlossary.tenant_id == t_id_str,
                    ConceptGlossary.is_published == True,
                )
                g_res = await session.execute(g_stmt)
                for g_row in g_res.fetchall():
                    if g_row[0]:
                        excluded_tokens.add(g_row[0].lower())
                    if g_row[1]:
                        excluded_tokens.add(g_row[1].lower())
                    if g_row[2] and isinstance(g_row[2], list):
                        for syn in g_row[2]:
                            if isinstance(syn, str):
                                excluded_tokens.add(syn.lower())
                    if g_row[3]:
                        excluded_tokens.add(g_row[3].lower())
            except Exception as g_err:
                logger.debug(f"[EntityExtractor] Could not fetch glossary terms: {g_err}")

        # Extract tokens from query
        words = re.findall(r'\b[a-zA-Z]+\b', query)
        raw_candidates = []
        for w in words:
            if w.lower() in excluded_tokens:
                continue
            if len(w) < 2:
                continue
            raw_candidates.append(w)

        if not raw_candidates or not session or not kb_id:
            return raw_candidates

        # 4. Only treat token as candidate if it matches a value in kb2_entity_values
        try:
            from ..knowledge.models.knowledge_items import KB2EntityValue
            
            tenant_uuid = uuid.UUID(str(tenant_id)) if tenant_id else None
            kb_uuid = uuid.UUID(str(kb_id)) if kb_id else None

            # Discovered person table / columns if available
            person_table = None
            person_cols = None
            if canonical_schema:
                try:
                    from .collision_detector import CollisionDetector
                    disc = CollisionDetector.discover_person_table_and_columns(canonical_schema)
                    if disc:
                        person_table, _, person_cols, _ = disc
                except Exception:
                    pass

            verified_candidates = []
            for cand in raw_candidates:
                clean_cand = cand.strip().lower()
                conds = [
                    KB2EntityValue.db_knowledgebase_id == kb_uuid,
                    or_(
                        KB2EntityValue.normalized_value == clean_cand,
                        KB2EntityValue.normalized_value.ilike(f"%{clean_cand}%"),
                    ),
                ]
                if tenant_uuid:
                    conds.append(KB2EntityValue.tenant_id == tenant_uuid)
                if person_table:
                    tbl_names = [person_table]
                    if "." in person_table:
                        tbl_names.append(person_table.split(".")[-1])
                    conds.append(KB2EntityValue.table_name.in_(tbl_names))
                if person_cols:
                    conds.append(KB2EntityValue.column_name.in_(person_cols))

                stmt = select(KB2EntityValue.id).where(*conds).limit(1)
                res = await session.execute(stmt)
                if res.scalar_one_or_none() is not None:
                    verified_candidates.append(cand)
                else:
                    # Fallback check on person_table without column restriction if person_cols was restricted
                    if person_table and person_cols:
                        tbl_names = [person_table]
                        if "." in person_table:
                            tbl_names.append(person_table.split(".")[-1])
                        fb_stmt = select(KB2EntityValue.id).where(
                            KB2EntityValue.db_knowledgebase_id == kb_uuid,
                            KB2EntityValue.table_name.in_(tbl_names),
                            or_(
                                KB2EntityValue.normalized_value == clean_cand,
                                KB2EntityValue.normalized_value.ilike(f"%{clean_cand}%"),
                            ),
                        ).limit(1)
                        if tenant_uuid:
                            fb_stmt = fb_stmt.where(KB2EntityValue.tenant_id == tenant_uuid)
                        res_fb = await session.execute(fb_stmt)
                        if res_fb.scalar_one_or_none() is not None:
                            verified_candidates.append(cand)
                            continue

                    logger.info(f"[EntityExtractor] Candidate '{cand}' dropped: not found in local kb2_entity_values")

            return verified_candidates
        except Exception as exc:
            logger.warning(f"[EntityExtractor] Verification against kb2_entity_values failed: {exc}")
            return []
