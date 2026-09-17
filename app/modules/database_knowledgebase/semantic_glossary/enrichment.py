"""Offline Semantic Glossary LLM Enrichment Service

Batches column metadata at the table level to enrich business descriptions,
domain synonyms, and semantic concepts offline without blocking query paths.
Enforces Invariant 8/9: strictly excludes quarantined columns and never sends raw rows.
"""

import asyncio
import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm.deepinfra_llm import DeepInfraLLMClient, strip_think_tags
from app.core.embeddings import EmbeddingGenerator
from ..models.concept_glossary import ConceptGlossary
from ..schemas.canonical import ColumnSchema, DatabaseSchema, TableSchema
from .canonicality import is_canonical_table

logger = logging.getLogger(__name__)

# Security invariant: Sensitive/quarantined columns that must NEVER be sent to the LLM
SENSITIVE_PATTERNS: Set[str] = {
    "password", "secret", "token", "hash", "salt", "api_key", "credential",
    "auth_token", "private_key", "passphrase", "access_token", "refresh_token",
}

# Extensible allow-list seeded with fine-grained business concept roles across enterprise domains:
# HRMS, CRM, Finance, Hospital/Healthcare, and Supply Chain.
SEEDED_SEMANTIC_ROLES: Set[str] = {
    # Coarse structural fallback roles
    "IDENTITY", "TEMPORAL", "STATUS", "METRIC", "NUMERIC", "CATEGORICAL", "DESCRIPTIVE", "REFERENCE", "UNKNOWN",
    
    # Temporal fine-grained business concepts
    "ARRIVAL_TIME", "DEPARTURE_TIME", "CHECK_IN_TIME", "CHECK_OUT_TIME",
    "START_TIME", "END_TIME", "START_DATE", "END_DATE",
    "HIRE_DATE", "TERMINATION_DATE", "BIRTH_DATE", "EXPIRY_DATE", "DUE_DATE",
    "ADMISSION_DATE", "DISCHARGE_DATE", "ORDER_DATE", "INVOICE_DATE", "PAYMENT_DATE",
    "TRANSACTION_TIME", "CREATED_AT", "UPDATED_AT", "SCHEDULE_TIME",
    
    # Financial & Metric fine-grained concepts
    "AMOUNT_PAID", "AMOUNT_DUE", "TOTAL_AMOUNT", "UNIT_PRICE", "UNIT_COST", "TOTAL_COST",
    "SALARY_RATE", "BASE_PAY", "BONUS_AMOUNT", "DISCOUNT_AMOUNT", "TAX_AMOUNT",
    "QUANTITY", "HOURS_WORKED", "OVERTIME_HOURS", "LEAVE_BALANCE", "BALANCE",
    "BUDGET", "REVENUE", "EXPENSE",
    
    # Identity & Entity concepts
    "EMPLOYEE_ID", "PATIENT_ID", "CUSTOMER_ID", "USER_ID", "VENDOR_ID",
    "ORDER_ID", "INVOICE_ID", "ACCOUNT_ID", "TRANSACTION_ID", "DOCUMENT_ID",
    
    # Status & Workflow concepts
    "APPROVAL_STATUS", "PAYMENT_STATUS", "EMPLOYMENT_STATUS", "ORDER_STATUS",
    "ATTENDANCE_STATUS", "LEAVE_STATUS", "TICKET_STATUS", "ACTIVE_FLAG",
    
    # Descriptive & Contact concepts
    "FULL_NAME", "FIRST_NAME", "LAST_NAME", "EMAIL_ADDRESS", "PHONE_NUMBER",
    "DEPARTMENT_NAME", "JOB_TITLE", "ROLE_NAME", "ADDRESS", "DESCRIPTION_TEXT",
}

VALID_SEMANTIC_ROLES: Set[str] = set(SEEDED_SEMANTIC_ROLES)

MAX_SYNONYMS_PER_CONCEPT = 15
MAX_COLUMNS_PER_PROMPT = 12


class GlossaryEnrichmentService:
    """
    Offline batch enrichment engine generating multi-tenant semantic concept glossary entries.
    """

    def __init__(
        self,
        llm_client: Optional[DeepInfraLLMClient] = None,
        max_concurrency: int = 5,
    ):
        self.llm_client = llm_client or DeepInfraLLMClient()
        self.semaphore = asyncio.Semaphore(max_concurrency)

    @classmethod
    def register_semantic_role(cls, role: str, confidence_source: str = "HUMAN_VERIFIED") -> bool:
        """
        Extends the allow-list with a verified business concept role.
        STRICT GUARD: Only HUMAN_VERIFIED entries can permanently expand the allow-list.
        LLM_GENERATED proposals of novel unseeded roles are rejected / fall back to UNKNOWN.
        """
        if confidence_source != "HUMAN_VERIFIED":
            logger.warning(
                f"Rejected role expansion '{role}': confidence_source must be 'HUMAN_VERIFIED', "
                f"got '{confidence_source}'"
            )
            return False

        clean_role = role.upper().strip().replace(" ", "_").replace("-", "_")
        if re.match(r"^[A-Z][A-Z0-9_]{1,48}$", clean_role):
            VALID_SEMANTIC_ROLES.add(clean_role)
            return True
        return False

    @classmethod
    def is_quarantined_column(cls, col_name: str) -> bool:
        """Determines if a column is sensitive and must be quarantined from LLM prompts."""
        c_clean = col_name.lower().strip()
        return any(pattern in c_clean for pattern in SENSITIVE_PATTERNS)

    @classmethod
    def sanitize_llm_json(cls, raw_text: str) -> List[Dict[str, Any]]:
        """
        Defensively parses JSON response from LLM, stripping markdown code blocks,
        think tags, and trailing commas.
        """
        text = strip_think_tags(raw_text).strip()

        # Remove markdown code block if present
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        # Match outer JSON array
        json_array_match = re.search(r"\[\s*\{.*\}\s*\]", text, re.DOTALL)
        if json_array_match:
            text = json_array_match.group(0)

        # Remove trailing commas before closing braces/brackets
        text = re.sub(r",\s*([\]\}])", r"\1", text)

        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
            elif isinstance(parsed, dict) and "columns" in parsed and isinstance(parsed["columns"], list):
                return parsed["columns"]
            return []
        except Exception as e:
            logger.warning(f"Failed to parse LLM glossary JSON: {e}. Raw text snippet: {text[:200]}")
            return []

    @classmethod
    def build_prompt(cls, table: TableSchema, columns: List[ColumnSchema]) -> str:
        """Constructs table-level batch prompt strictly using metadata; zero raw data rows."""
        col_descriptions = []
        for col in columns:
            fk_info = ""
            if col.is_foreign_key:
                fk_info = " (Foreign Key)"
            elif col.is_primary_key:
                fk_info = " (Primary Key)"
            col_descriptions.append(f"- {col.name}: type={col.raw_data_type}{fk_info}")

        cols_str = "\n".join(col_descriptions)

        return (
            f"You are an enterprise database semantic annotator. Given the table and column definitions below, "
            f"provide a concise business description, 2 to 4 search synonyms that real end-users might query with, "
            f"and a specific fine-grained business semantic role in UPPER_SNAKE_CASE (e.g. ARRIVAL_TIME, DEPARTURE_TIME, "
            f"AMOUNT_PAID, AMOUNT_DUE, UNIT_PRICE, TOTAL_COST, HIRE_DATE, BIRTH_DATE, EMPLOYEE_ID, FULL_NAME, STATUS_FLAG, "
            f"or structural roles like IDENTITY, TEMPORAL, STATUS, METRIC).\n\n"
            f"Table Name: {table.table_name}\n"
            f"Columns:\n{cols_str}\n\n"
            f"Output strictly a valid JSON list of objects matching this exact schema (no markdown, no preamble):\n"
            f"[\n"
            f"  {{\n"
            f'    "column_name": "example_col",\n'
            f'    "business_description": "Concise 1-sentence business meaning",\n'
            f'    "synonyms": ["synonym 1", "synonym 2"],\n'
            f'    "semantic_role": "ARRIVAL_TIME"\n'
            f"  }}\n"
            f"]"
        )

    async def enrich_table_batch(
        self,
        table: TableSchema,
        columns: List[ColumnSchema],
    ) -> List[Dict[str, Any]]:
        """Invokes LLM with concurrency limiting to enrich a batch of columns for a single table."""
        # Enforce quarantine invariant
        safe_columns = [col for col in columns if not self.is_quarantined_column(col.name)]
        if not safe_columns:
            return []

        prompt = self.build_prompt(table, safe_columns)

        async with self.semaphore:
            try:
                raw_response = await self.llm_client.generate_cloud(
                    prompt=prompt,
                    system_prompt="You are a precise database catalog semantic annotator. Return only pure JSON.",
                    temperature=0.0,
                    max_tokens=1500,
                    enable_thinking=False,
                )
                items = self.sanitize_llm_json(raw_response)
                
                # Sanitize and cap each item
                valid_items = []
                col_names = {c.name for c in safe_columns}
                for item in items:
                    cname = item.get("column_name")
                    if not cname or cname not in col_names:
                        continue
                    
                    desc = str(item.get("business_description") or "").strip()
                    raw_synonyms = item.get("synonyms") or []
                    if isinstance(raw_synonyms, list):
                        synonyms = [str(s).lower().strip() for s in raw_synonyms if s and isinstance(s, str)]
                        # Deduplicate while preserving order and cap to MAX_SYNONYMS_PER_CONCEPT
                        seen = set()
                        deduped_synonyms = []
                        for s in synonyms:
                            if s not in seen:
                                seen.add(s)
                                deduped_synonyms.append(s)
                        synonyms = deduped_synonyms[:MAX_SYNONYMS_PER_CONCEPT]
                    else:
                        synonyms = []

                    role = str(item.get("semantic_role") or "UNKNOWN").upper().strip().replace(" ", "_").replace("-", "_")
                    if role not in VALID_SEMANTIC_ROLES:
                        role = "UNKNOWN"

                    valid_items.append({
                        "column_name": cname,
                        "business_description": desc,
                        "synonyms": synonyms,
                        "semantic_role": role,
                    })

                return valid_items

            except Exception as e:
                logger.error(f"Error enriching table {table.table_name}: {e}")
                return []

    async def enrich_schema_async(
        self,
        session: AsyncSession,
        tenant_id: str | uuid.UUID,
        kb_id: uuid.UUID,
        schema: DatabaseSchema,
        fingerprint: Optional[str] = None,
        strict_review: bool = True,
        canonical_overrides: Optional[Dict[str, bool]] = None,
    ) -> List[ConceptGlossary]:
        """
        Executes full offline schema enrichment across all tables.
        Batches columns up to MAX_COLUMNS_PER_PROMPT with bounded concurrency.
        Under strict_review=True, all rows are written with is_published=False (draft).
        """
        t_id_str = str(tenant_id)
        fp_str = fingerprint or schema.fingerprint

        # Filter to canonical tables (or override-whitelisted tables)
        candidate_tables = [
            t for t in schema.all_tables
            if is_canonical_table(t, canonical_overrides=canonical_overrides)
        ]

        # Prepare column batches across all candidate tables
        tasks = []
        batch_metadata = []  # Stores (table, columns)

        for table in candidate_tables:
            business_cols = [
                col for col in table.columns.values()
                if not self.is_quarantined_column(col.name)
            ]
            if not business_cols:
                continue

            for i in range(0, len(business_cols), MAX_COLUMNS_PER_PROMPT):
                batch = business_cols[i : i + MAX_COLUMNS_PER_PROMPT]
                batch_metadata.append((table, batch))
                tasks.append(self.enrich_table_batch(table, batch))

        if not tasks:
            return []

        # Run all batches concurrently with bounded semaphore
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        created_glossary_entries: List[ConceptGlossary] = []
        texts_to_embed = []
        entries_to_persist = []

        for (table, batch_cols), res in zip(batch_metadata, batch_results):
            if isinstance(res, Exception) or not isinstance(res, list):
                continue

            for enriched_item in res:
                cname = enriched_item["column_name"]
                desc = enriched_item["business_description"]
                synonyms = enriched_item["synonyms"]
                role = enriched_item["semantic_role"]

                embed_text = f"{desc} {' '.join(synonyms)}".strip()
                texts_to_embed.append(embed_text)

                # Canonical status of table
                canon = is_canonical_table(table, canonical_overrides=canonical_overrides)

                glossary_entry = ConceptGlossary(
                    tenant_id=t_id_str,
                    table_name=table.table_name,
                    column_name=cname,
                    business_description=desc,
                    synonyms=synonyms,
                    semantic_role=role,
                    is_canonical=canon,
                    is_published=False if strict_review else True,
                    confidence_source="LLM_GENERATED",
                    schema_fingerprint=fp_str,
                    orphaned_by_drift=False,
                )
                entries_to_persist.append(glossary_entry)

        # Batch compute embeddings for all glossary concepts
        if texts_to_embed:
            try:
                embeddings = await asyncio.wait_for(
                    EmbeddingGenerator.generate_embeddings_batch(texts_to_embed),
                    timeout=30.0,
                )
                for entry, emb in zip(entries_to_persist, embeddings):
                    entry.embedding = emb
            except Exception as e:
                logger.warning(f"Could not generate embeddings for glossary entries: {e}")

        # 5. Idempotent persistence: Fetch existing rows to avoid unique constraint violations on retry
        stmt = select(ConceptGlossary).where(
            and_(
                ConceptGlossary.tenant_id == t_id_str,
                ConceptGlossary.schema_fingerprint == fp_str,
            )
        )
        existing_res = await session.execute(stmt)
        existing_map = {
            (row.table_name, row.column_name): row
            for row in existing_res.scalars().all()
        }

        for entry in entries_to_persist:
            key = (entry.table_name, entry.column_name)
            if key in existing_map:
                existing_entry = existing_map[key]
                existing_entry.business_description = entry.business_description
                existing_entry.synonyms = entry.synonyms
                existing_entry.semantic_role = entry.semantic_role
                existing_entry.is_canonical = entry.is_canonical
                existing_entry.is_published = entry.is_published
                existing_entry.confidence_source = entry.confidence_source
                if entry.embedding is not None:
                    existing_entry.embedding = entry.embedding
                created_glossary_entries.append(existing_entry)
            else:
                session.add(entry)
                created_glossary_entries.append(entry)

        await session.flush()
        logger.info(
            f"Successfully enriched {len(created_glossary_entries)} concept glossary items "
            f"for tenant {tenant_id} (strict_review={strict_review}, idempotent=True)"
        )
        return created_glossary_entries
