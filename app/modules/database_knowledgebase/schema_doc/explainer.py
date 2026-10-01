"""LLM Schema Explainer & Pydantic Validation

Takes factual table & column metadata, masked samples, and relationships,
and asks the LLM for:
- Table purpose, business context, synonyms, caveats
- Per-column meaning, search synonyms, coded-value mappings (e.g. 'A' = active)

CRITICAL INVARIANTS:
1. Exact name guarantee: The LLM output is keyed strictly by internal table/column IDs
   (or exact column names). Code maps everything back to the exact introspected schema.
   Table and column names are NEVER typed, renamed, or changed by the LLM.
2. Tables with over ~20 columns are batched.
3. Validated with Pydantic; if a column is missing from the output, retry once, then mark the table "failed".
4. Every LLM call passes tenant_id and task name for token usage tracking.
"""

import json
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.core.llm.deepinfra_llm import DeepInfraLLMClient, strip_think_tags
from .mapper import TableRelationshipMap
from .profiler import TableFacts
from .sensitivity import SensitivityGuard

logger = logging.getLogger(__name__)

MAX_COLUMNS_PER_BATCH = 15  # Batch if columns > 15-20


class ColumnDocOutput(BaseModel):
    """Pydantic model for LLM column documentation."""
    column_id: str = Field(..., description="The exact column ID/name provided in the prompt")
    meaning: str = Field(..., description="Clear explanation of the business meaning of this column")
    synonyms: List[str] = Field(default_factory=list, description="2-4 user search synonyms")
    coded_values: Optional[Dict[str, str]] = Field(default=None, description="Decoded meanings of codes/enums if any")


class TableExplanationOutput(BaseModel):
    """Pydantic model for LLM table documentation."""
    table_purpose: str = Field(..., description="High-level business purpose of the table")
    synonyms: List[str] = Field(default_factory=list, description="Common user terms or synonyms for this table")
    caveats: Optional[str] = Field(default=None, description="Important quirks, caveats, or filtering rules")
    columns: List[ColumnDocOutput] = Field(default_factory=list, description="Documentation for each column")


class SchemaExplainer:
    """Interacts with LLM to produce structured documentation with exact name guarantees."""

    def __init__(self, llm_client: Optional[DeepInfraLLMClient] = None):
        self.llm = llm_client or DeepInfraLLMClient.get_instance()

    async def explain_table(
        self,
        tenant_id: str,
        facts: TableFacts,
        relationship_map: TableRelationshipMap,
        total_tokens_tracker: Dict[str, Any],
    ) -> Optional[TableExplanationOutput]:
        """
        Explains table and all columns with exact name guarantee and retry on missing columns.
        Batches if columns > MAX_COLUMNS_PER_BATCH.
        """
        all_col_names = list(facts.columns.keys())

        # If columns <= MAX_COLUMNS_PER_BATCH, run in a single prompt
        if len(all_col_names) <= MAX_COLUMNS_PER_BATCH:
            return await self._explain_batch_with_retry(
                tenant_id=tenant_id,
                facts=facts,
                col_subset=all_col_names,
                relationship_map=relationship_map,
                include_table_meta=True,
                total_tokens_tracker=total_tokens_tracker,
            )

        # Batching for tables over ~20 columns
        combined_output: Optional[TableExplanationOutput] = None
        for i in range(0, len(all_col_names), MAX_COLUMNS_PER_BATCH):
            batch_cols = all_col_names[i : i + MAX_COLUMNS_PER_BATCH]
            is_first = (i == 0)
            batch_res = await self._explain_batch_with_retry(
                tenant_id=tenant_id,
                facts=facts,
                col_subset=batch_cols,
                relationship_map=relationship_map,
                include_table_meta=is_first,
                total_tokens_tracker=total_tokens_tracker,
            )
            if not batch_res:
                return None  # Failed retry on a batch -> table failed

            if combined_output is None:
                combined_output = batch_res
            else:
                combined_output.columns.extend(batch_res.columns)

        return combined_output

    async def _explain_batch_with_retry(
        self,
        tenant_id: str,
        facts: TableFacts,
        col_subset: List[str],
        relationship_map: TableRelationshipMap,
        include_table_meta: bool,
        total_tokens_tracker: Dict[str, Any],
    ) -> Optional[TableExplanationOutput]:
        """Attempt explanation, and if columns missing, retry ONCE. Returns None if still failed."""
        # Attempt 1
        res = await self._call_llm_for_batch(
            tenant_id=tenant_id,
            facts=facts,
            col_subset=col_subset,
            relationship_map=relationship_map,
            include_table_meta=include_table_meta,
            total_tokens_tracker=total_tokens_tracker,
        )

        missing = self._get_missing_columns(col_subset, res)
        if not missing:
            return res

        logger.warning(
            f"Missing columns for table {facts.table_name} on attempt 1: {missing}. Retrying once..."
        )

        # Attempt 2 (Retry once with explicit nudge for missing columns)
        res_retry = await self._call_llm_for_batch(
            tenant_id=tenant_id,
            facts=facts,
            col_subset=col_subset,
            relationship_map=relationship_map,
            include_table_meta=include_table_meta,
            missing_nudge=missing,
            total_tokens_tracker=total_tokens_tracker,
        )

        missing_retry = self._get_missing_columns(col_subset, res_retry)
        if missing_retry:
            logger.error(
                f"Validation failed: Table {facts.table_name} still missing columns after retry: {missing_retry}"
            )
            return None

        return res_retry

    def _get_missing_columns(self, expected_cols: List[str], output: Optional[TableExplanationOutput]) -> List[str]:
        if not output or not output.columns:
            return expected_cols
        returned = {c.column_id for c in output.columns}
        return [c for c in expected_cols if c not in returned]

    async def _call_llm_for_batch(
        self,
        tenant_id: str,
        facts: TableFacts,
        col_subset: List[str],
        relationship_map: TableRelationshipMap,
        include_table_meta: bool,
        missing_nudge: Optional[List[str]] = None,
        total_tokens_tracker: Optional[Dict[str, Any]] = None,
    ) -> Optional[TableExplanationOutput]:
        """Format prompt, invoke LLM, parse & validate Pydantic output."""
        prompt = self._build_prompt(
            facts=facts,
            col_subset=col_subset,
            relationship_map=relationship_map,
            include_table_meta=include_table_meta,
            missing_nudge=missing_nudge,
        )

        system_prompt = (
            "You are an expert enterprise database architect and catalog documenter. "
            "Your output must be strictly valid JSON matching the requested schema. "
            "Never invent or rename columns. Maintain exact column IDs."
        )

        try:
            res_dict = await self.llm.generate_with_usage(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=2500,
                temperature=0.0,
            )
            raw_text = res_dict.get("content", "")
            inp_tok = res_dict.get("prompt_tokens", 0)
            out_tok = res_dict.get("completion_tokens", 0)

            # Track tokens
            if total_tokens_tracker is not None:
                total_tokens_tracker["input_tokens"] = total_tokens_tracker.get("input_tokens", 0) + inp_tok
                total_tokens_tracker["output_tokens"] = total_tokens_tracker.get("output_tokens", 0) + out_tok
                total_tokens_tracker["llm_calls"] = total_tokens_tracker.get("llm_calls", 0) + 1

            # Log usage to analytics
            try:
                from app.modules.analytics.repository import AnalyticsRepository
                from app.core.database import AsyncSessionLocal
                async with AsyncSessionLocal() as session:
                    repo = AnalyticsRepository(session)
                    await repo.log_usage(
                        tenant_id=tenant_id,
                        user_id="",
                        model_name=self.llm.model_extraction,
                        query_text=f"Schema cheat sheet explanation: {facts.table_name}",
                        input_tokens=inp_tok,
                        output_tokens=out_tok,
                        task_name="schema_doc_explanation",
                    )
            except Exception as log_err:
                logger.debug(f"Non-fatal analytics log error: {log_err}")

            # Parse JSON
            cleaned_json = strip_think_tags(raw_text).strip()
            if cleaned_json.startswith("```json"):
                cleaned_json = cleaned_json[7:]
            if cleaned_json.startswith("```"):
                cleaned_json = cleaned_json[3:]
            if cleaned_json.endswith("```"):
                cleaned_json = cleaned_json[:-3]
            cleaned_json = cleaned_json.strip()

            parsed = json.loads(cleaned_json)
            # If prompt was for columns only, wrap in dummy table meta
            if not include_table_meta:
                if isinstance(parsed, list):
                    parsed = {"table_purpose": "continuation", "synonyms": [], "columns": parsed}
                elif "columns" not in parsed:
                    parsed = {"table_purpose": "continuation", "synonyms": [], "columns": []}

            # Enforce exact name constraint: map returned column_id to exact column in col_subset
            col_lookup = {c.lower(): c for c in col_subset}
            validated_cols = []
            for c_obj in parsed.get("columns", []):
                raw_cid = str(c_obj.get("column_id", "")).strip()
                if raw_cid.lower() in col_lookup:
                    c_obj["column_id"] = col_lookup[raw_cid.lower()]
                    validated_cols.append(ColumnDocOutput.model_validate(c_obj))

            parsed["columns"] = validated_cols
            return TableExplanationOutput.model_validate(parsed)

        except Exception as e:
            logger.error(f"Failed to generate LLM explanation for {facts.table_name}: {e}")
            return None

    def _build_prompt(
        self,
        facts: TableFacts,
        col_subset: List[str],
        relationship_map: TableRelationshipMap,
        include_table_meta: bool,
        missing_nudge: Optional[List[str]] = None,
    ) -> str:
        """Construct structured prompt with facts, masked samples, and relationships."""
        # 1. Columns facts
        col_lines = []
        for cname in col_subset:
            cinfo = facts.columns.get(cname, {})
            sens = cinfo.get("is_sensitive", False)
            dt = cinfo.get("data_type", "unknown")
            pk = "PK" if cinfo.get("is_primary_key") else ""
            fk = "FK" if cinfo.get("is_foreign_key") else ""
            tags = " ".join([t for t in [pk, fk] if t])
            if tags:
                tags = f" [{tags}]"

            if sens:
                col_lines.append(f"- column_id: '{cname}' | type: {dt}{tags} | [SENSITIVE: NO VALUES AVAILABLE]")
            else:
                dc = cinfo.get("distinct_count")
                np = cinfo.get("null_percentage")
                mn = cinfo.get("min_value")
                mx = cinfo.get("max_value")
                dv = cinfo.get("distinct_values")
                stat_str = f"distinct={dc}, null_pct={np}%"
                if mn is not None and mx is not None:
                    stat_str += f", min='{mn}', max='{mx}'"
                if dv:
                    stat_str += f", distinct_values={dv}"
                col_lines.append(f"- column_id: '{cname}' | type: {dt}{tags} | {stat_str}")

        cols_block = "\n".join(col_lines)

        # 2. Masked Samples (Only safe non-sensitive columns)
        samples_json = "[]"
        if facts.samples:
            # Filter samples down to safe subset
            safe_samples = []
            for s in facts.samples[:5]:
                safe_s = {k: v for k, v in s.items() if k in col_subset and not SensitivityGuard.is_sensitive_column(k)}
                safe_samples.append(safe_s)
            samples_json = json.dumps(safe_samples, indent=2, default=str)

        # 3. Relationships summary
        rel_summary = relationship_map.relationship_summary

        nudge_str = ""
        if missing_nudge:
            nudge_str = f"\nATTENTION: You missed documenting these columns previously: {missing_nudge}. You MUST include an entry for every single one of them.\n"

        prompt = f"""Generate enterprise documentation for the table '{facts.table_name}'.
Table Total Rows: {facts.total_rows}
Relationships: {rel_summary}

Columns to Document:
{cols_block}

Safe Masked Samples (PII masked):
{samples_json}
{nudge_str}
CRITICAL RULES:
1. Output MUST be valid JSON.
2. In 'columns', you MUST include EVERY column_id listed above using its EXACT column_id string.
3. Table purpose: explain what entity or relationship it models.
4. For columns: describe the business meaning, 2-4 search synonyms, and decode coded values if apparent (e.g. status codes).
5. DO NOT hallucinate values or rename columns.

JSON Schema:
{{
  "table_purpose": "1-2 sentences on what this table stores and how it fits into the business",
  "synonyms": ["synonym1", "synonym2"],
  "caveats": "Any notes on soft deletes, nullability, or key joins",
  "columns": [
    {{
      "column_id": "exact_column_name_here",
      "meaning": "Business meaning of this column",
      "synonyms": ["synonym1", "synonym2"],
      "coded_values": {{"code": "meaning"}}
    }}
  ]
}}
"""
        return prompt
