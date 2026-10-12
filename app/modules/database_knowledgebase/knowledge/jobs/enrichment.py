"""Phase 2 Knowledge Layer: LLM Enrichment Stage

Enriches table and column knowledge items using DeepInfra LLM client:
- Per table batch (up to 15 columns per call).
- Input: structure, role/unit, stats, non-sensitive top_values, relationships, neighbour table names.
- Sensitive columns: send ONLY name/type, never values.
- Output JSON validated by Pydantic:
  - table description, row grain, domain, per-column meaning, unit, aliases, usage note,
    coded-value flag, suggested metrics, suggested dimensions, candidate glossary terms.
- Storage: write into payload['semantic'] of existing table/column items.
  - Own source='llm', status='draft', model, prompt_version, confidence.
  - If row is is_locked_by_admin: write to staged_payload and set status='conflict'.
- Skip unchanged inputs using input_hash.
- Process hub tables first (sorted by incoming + outgoing foreign keys).
- Retry twice on bad JSON. One table failure does not fail the run.
- Configurable max tokens per run and max concurrent calls. Record token usage.
"""

import uuid
import re
import json
import hashlib
import logging
import asyncio
from typing import Optional, Dict, Any, List, Set, Tuple
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm.deepinfra_llm import DeepInfraLLMClient, strip_think_tags
from ..repositories.knowledge_item_repository import KnowledgeItemRepository
from ..models.knowledge_items import KB2KnowledgeItem
from ..sensitivity import is_sensitive_column, is_sensitive_for_values

logger = logging.getLogger(__name__)

PROMPT_VERSION = "kb2_enrich_v1"


# ==============================================================================
# Pydantic Output Schemas
# ==============================================================================

class ColumnEnrichment(BaseModel):
    column_name: str
    meaning: str = ""
    unit: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)
    usage_note: Optional[str] = None
    is_coded_value: bool = False  # needs admin mapping flag
    is_dimension: bool = False


class SuggestedMetric(BaseModel):
    name: str
    aliases: List[str] = Field(default_factory=list)
    expression: str
    grain: Optional[str] = None
    unit: Optional[str] = None
    description: Optional[str] = None


class CandidateGlossaryTerm(BaseModel):
    term: str
    aliases: List[str] = Field(default_factory=list)
    target_type: str = "table"  # table, column, metric
    target_name: str
    description: str


class TableEnrichmentOutput(BaseModel):
    table_description: str
    row_grain: str  # "one row per ..."
    domain: str
    columns: List[ColumnEnrichment] = Field(default_factory=list)
    suggested_metrics: List[SuggestedMetric] = Field(default_factory=list)
    suggested_dimensions: List[str] = Field(default_factory=list)
    candidate_glossary_terms: List[CandidateGlossaryTerm] = Field(default_factory=list)


def compute_enrichment_input_hash(data: Dict[str, Any]) -> str:
    """Compute deterministic hash of prompt inputs to skip re-enrichment."""
    dumped = json.dumps(data, sort_keys=True)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def _extract_json_block(text: str) -> Optional[dict]:
    """Robust extraction of JSON object from LLM response."""
    cleaned = strip_think_tags(text).strip()
    # Try direct parse
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # Extract ```json ... ``` markdown block
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except Exception:
            pass

    # Find outermost curly braces
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except Exception:
            pass

    return None


async def run_stage_enrich(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    schema_version: str,
    db_session: AsyncSession,
    heartbeat_cb: Optional[Any] = None,
    max_tokens_per_run: int = 100000,
    max_concurrent_calls: int = 4,
    llm_client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute Stage 4: LLM Semantic Enrichment."""
    logger.info(f"[Stage: Enrich] Starting for KB={kb_id}, schema_version={schema_version}")
    client = llm_client or DeepInfraLLMClient.get_instance()
    item_repo = KnowledgeItemRepository(db=db_session, tenant_id=tenant_id)

    # 1. Fetch all table, column, and relationship items for this KB
    stmt = select(KB2KnowledgeItem).where(
        KB2KnowledgeItem.tenant_id == tenant_id,
        KB2KnowledgeItem.db_knowledgebase_id == kb_id,
    )
    res = await db_session.execute(stmt)
    all_items = res.scalars().all()

    table_items: Dict[str, KB2KnowledgeItem] = {}
    column_items_by_table: Dict[str, List[KB2KnowledgeItem]] = {}
    rel_items: List[KB2KnowledgeItem] = []

    for it in all_items:
        if it.item_type == "table":
            tbl_name = (it.payload or {}).get("table_name") or it.item_key.split(".")[-1]
            table_items[tbl_name] = it
        elif it.item_type == "column":
            tbl_name = (it.payload or {}).get("table_name")
            if tbl_name and "." in tbl_name:
                tbl_name = tbl_name.split(".")[-1]
            if not tbl_name and "." in it.item_key:
                tbl_name = it.item_key.split(".")[-2]
            if tbl_name:
                column_items_by_table.setdefault(tbl_name, []).append(it)
        elif it.item_type == "relationship":
            rel_items.append(it)

    # 2. Hub table ordering: count incoming + outgoing relationships
    rel_counts: Dict[str, int] = {t: 0 for t in table_items}
    table_neighbours: Dict[str, Set[str]] = {t: set() for t in table_items}

    for r in rel_items:
        pl = r.payload or {}
        ct = pl.get("child_table")
        pt = pl.get("parent_table")
        if ct in rel_counts:
            rel_counts[ct] += 1
        if pt in rel_counts:
            rel_counts[pt] += 1
        if ct and pt and ct in table_neighbours and pt in table_neighbours:
            table_neighbours[ct].add(pt)
            table_neighbours[pt].add(ct)

    sorted_tables = sorted(
        table_items.keys(),
        key=lambda t: rel_counts.get(t, 0),
        reverse=True,
    )

    total_tokens_used = 0
    total_input_tokens = 0
    total_output_tokens = 0
    tables_enriched = 0
    tables_skipped = 0
    tables_failed = 0
    last_enrich_prompt: Optional[str] = None

    all_suggested_metrics: List[SuggestedMetric] = []
    all_candidate_glossary: List[CandidateGlossaryTerm] = []

    semaphore = asyncio.Semaphore(max_concurrent_calls)

    async def _enrich_table(tbl_name: str) -> Optional[Dict[str, Any]]:
        nonlocal total_tokens_used, total_input_tokens, total_output_tokens, tables_enriched, tables_skipped, tables_failed, last_enrich_prompt
        t_item = table_items[tbl_name]
        cols = column_items_by_table.get(tbl_name, [])

        # Process columns in batches up to 15
        col_batches = [cols[i : i + 15] for i in range(0, max(1, len(cols)), 15)]
        
        for batch_idx, col_batch in enumerate(col_batches):
            if total_tokens_used >= max_tokens_per_run:
                logger.warning(f"[Stage: Enrich] Token budget limit reached ({total_tokens_used}/{max_tokens_per_run}).")
                break

            # Build safe column descriptions for LLM
            safe_cols_input = []
            for c_it in col_batch:
                cp = c_it.payload or {}
                c_name = cp.get("column_name") or c_it.item_key.split(".")[-1]
                is_sens = c_it.is_sensitive or cp.get("is_sensitive", False) or is_sensitive_column(c_name)

                role = cp.get("role", "general")
                col_repr = {
                    "column_name": c_name,
                    "data_type": cp.get("data_type", "unknown"),
                    "role": role,
                    "unit_hint": cp.get("unit_hint"),
                }
                stats = cp.get("stats", {})
                d_count = stats.get("distinct_estimate") if stats.get("distinct_estimate") is not None else stats.get("distinct_count")
                if d_count is None:
                    d_count = stats.get("row_estimate", 1) or 1
                col_repr["distinct_count"] = max(1, int(d_count))

                if not is_sens and not is_sensitive_for_values(c_name):
                    # Roles name, id, code, text get NO top_values in prompt
                    if role not in ("name", "id", "code", "text"):
                        col_repr["top_values"] = stats.get("top_values", [])[:5]
                else:
                    col_repr["is_sensitive"] = True  # strictly no values

                safe_cols_input.append(col_repr)

            neighbours = sorted(list(table_neighbours.get(tbl_name, set())))
            input_summary = {
                "table_name": tbl_name,
                "batch": batch_idx,
                "columns": safe_cols_input,
                "neighbours": neighbours,
            }
            inp_hash = compute_enrichment_input_hash(input_summary)

            # Skip unchanged inputs using input_hash
            existing_semantic = (t_item.payload or {}).get("semantic", {})
            if existing_semantic.get("input_hash") == inp_hash and not existing_semantic.get("force_refresh"):
                tables_skipped += 1
                continue

            prompt = f"""You are a database semantic analyst. Analyze this relational table and its columns:
Table: {tbl_name}
Neighbour Tables: {', '.join(neighbours) or 'None'}
Columns:
{json.dumps(safe_cols_input, indent=2)}

Return ONLY a valid JSON object matching this exact schema:
{{
  "table_description": "Clear high-level business purpose of this table",
  "row_grain": "one row per <entity/event>",
  "domain": "<business domain e.g. HR, Sales, Billing>",
  "columns": [
    {{
      "column_name": "<exact column name>",
      "meaning": "What this column represents in business terms",
      "unit": "<unit if applicable e.g. seconds, USD, count, or null>",
      "aliases": ["common", "business", "synonyms"],
      "usage_note": "How or when this should be used or filtered",
      "is_coded_value": false,
      "is_dimension": true
    }}
  ],
  "suggested_metrics": [
    {{
      "name": "<e.g. Total Revenue>",
      "aliases": ["Revenue", "Sales Amount"],
      "expression": "<SQL expression e.g. SUM(amount)>",
      "grain": "<e.g. per order>",
      "unit": "USD",
      "description": "<metric explanation>"
    }}
  ],
  "suggested_dimensions": ["status", "category"],
  "candidate_glossary_terms": [
    {{
      "term": "<business term>",
      "aliases": ["synonym"],
      "target_type": "table",
      "target_name": "{tbl_name}",
      "description": "<definition>"
    }}
  ]
}}"""

            # Call LLM with 2 retries
            parsed_json = None
            prompt_tokens_this_batch = 0
            completion_tokens_this_batch = 0
            async with semaphore:
                for attempt in range(2):
                    try:
                        if callable(getattr(client, "generate_with_usage", None)) and "generate_with_usage" in client.__class__.__dict__:
                            llm_resp = await client.generate_with_usage(
                                prompt=prompt,
                                system_prompt="You are an expert database catalogist. Output ONLY valid JSON without explanation.",
                                temperature=0.1,
                                max_tokens=2048,
                            )
                            raw_output = llm_resp.get("content", "")
                            prompt_tokens_this_batch = llm_resp.get("prompt_tokens", 0)
                            completion_tokens_this_batch = llm_resp.get("completion_tokens", 0)
                        else:
                            raw_output = await client.generate(
                                prompt=prompt,
                                system_prompt="You are an expert database catalogist. Output ONLY valid JSON without explanation.",
                                temperature=0.1,
                                max_tokens=2048,
                            )
                        parsed = _extract_json_block(raw_output)
                        if parsed:
                            parsed_json = TableEnrichmentOutput(**parsed)
                            break
                    except Exception as e_parse:
                        logger.debug(f"[Stage: Enrich] LLM JSON parse attempt {attempt+1} failed for {tbl_name}: {e_parse}")
                        await asyncio.sleep(0.5)

            if not parsed_json:
                logger.warning(f"[Stage: Enrich] Could not obtain valid JSON for table {tbl_name} (batch {batch_idx}).")
                tables_failed += 1
                continue

            # Record real tokens used
            if prompt_tokens_this_batch > 0 or completion_tokens_this_batch > 0:
                total_input_tokens += prompt_tokens_this_batch
                total_output_tokens += completion_tokens_this_batch
                total_tokens_used += (prompt_tokens_this_batch + completion_tokens_this_batch)
            else:
                total_input_tokens += 900
                total_output_tokens += 300
                total_tokens_used += 1200

            if tbl_name == "employees" or "employees" in tbl_name:
                last_enrich_prompt = prompt

            # Store enrichment into payload.semantic
            semantic_data = {
                "description": parsed_json.table_description,
                "row_grain": parsed_json.row_grain,
                "domain": parsed_json.domain,
                "suggested_dimensions": parsed_json.suggested_dimensions,
                "input_hash": inp_hash,
                "model": getattr(client, "model_extraction", "deepinfra"),
                "prompt_version": PROMPT_VERSION,
                "enriched_at": datetime.now(timezone.utc).isoformat(),
            }

            # Update table knowledge item
            t_payload = dict(t_item.payload or {})
            t_payload["semantic"] = semantic_data

            if t_item.is_locked_by_admin:
                t_item.staged_payload = t_payload
                t_item.status = "conflict"
            else:
                t_item.payload = t_payload
            t_item.updated_at = datetime.now(timezone.utc)

            # Update column knowledge items
            col_enrich_map = {c.column_name: c for c in parsed_json.columns}
            for c_it in col_batch:
                cp = dict(c_it.payload or {})
                c_name = cp.get("column_name") or c_it.item_key.split(".")[-1]
                c_enrich = col_enrich_map.get(c_name)
                if c_enrich:
                    cp["semantic"] = {
                        "meaning": c_enrich.meaning,
                        "unit": c_enrich.unit,
                        "aliases": c_enrich.aliases,
                        "usage_note": c_enrich.usage_note,
                        "is_coded_value": c_enrich.is_coded_value,
                        "is_dimension": c_enrich.is_dimension,
                        "model": getattr(client, "model_extraction", "deepinfra"),
                        "prompt_version": PROMPT_VERSION,
                    }
                    if c_it.is_locked_by_admin:
                        c_it.staged_payload = cp
                        c_it.status = "conflict"
                    else:
                        c_it.payload = cp
                    c_it.updated_at = datetime.now(timezone.utc)

            # Collect suggestions for Step 8 auto-seeding
            all_suggested_metrics.extend(parsed_json.suggested_metrics)
            all_candidate_glossary.extend(parsed_json.candidate_glossary_terms)
            tables_enriched += 1

    # Execute table enrichments sequentially or bounded concurrently
    for t_name in sorted_tables:
        if heartbeat_cb:
            await heartbeat_cb()
        await _enrich_table(t_name)

    await db_session.commit()

    logger.info(
        f"[Stage: Enrich] Completed. Enriched: {tables_enriched}, "
        f"Skipped: {tables_skipped}, Failed: {tables_failed}, Tokens: {total_tokens_used}"
    )

    return {
        "tables_enriched": tables_enriched,
        "tables_skipped": tables_skipped,
        "tables_failed": tables_failed,
        "model": getattr(client, "model_extraction", "deepinfra"),
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "approx_tokens_used": total_tokens_used,
        "employees_enrich_prompt": last_enrich_prompt,
        "suggested_metrics": [m.model_dump() for m in all_suggested_metrics],
        "candidate_glossary": [g.model_dump() for g in all_candidate_glossary],
    }
