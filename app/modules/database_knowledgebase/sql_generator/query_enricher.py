"""Dynamic Schema-Aware Query Enricher

Translates conversational, ambiguous, or incomplete user questions into
precise, schema-grounded analytical queries using the actual database tables
and columns. Completely dynamic: zero hardcoded tables or columns.
"""

import logging
import json
import re
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class DynamicQueryEnricher:
    """Enriches natural language user questions dynamically using retrieved schema context and selected tables."""

    @classmethod
    def sanitize_enriched_query(cls, query_text: str, alias_words: Optional[List[str]] = None) -> str:
        """
        Strips hallucinated column filters where a table alias was treated as a column value,
        and repairs hallucinated booleans for status/stage terms and numeric quantities.
        """
        if not query_text:
            return query_text

        # 1. Clean up hallucinated status booleans: 'where the approved is true' -> 'where the stage is 'approved''
        query_text = re.sub(
            r"(?i)\bwhere\s+(?:the\s+)?(approved|pending|rejected|completed|submitted|closed|draft)\s+is\s+(?:true|TRUE)\b",
            r"where the stage is '\1'",
            query_text
        )
        query_text = re.sub(
            r"(?i)\band\s+(?:the\s+)?(approved|pending|rejected|completed|submitted|closed|draft)\s+is\s+(?:true|TRUE)\b",
            r"and the stage is '\1'",
            query_text
        )
        query_text = re.sub(
            r"(?i),\s*(?:the\s+)?(approved|pending|rejected|completed|submitted|closed|draft)\s+is\s+(?:true|TRUE)\b",
            r", the stage is '\1'",
            query_text
        )
        # 2. Clean up numeric zero turned into boolean FALSE: 'budgeted is false' -> 'budgeted is 0'
        query_text = re.sub(
            r"(?i)\b(budgeted|budget|amount|balance)\s+is\s+(?:false|FALSE)\b",
            r"\1 is 0",
            query_text
        )
        # 3. Clean up foreign key ID equated to business code: 'where budget_id is "5010172804"' -> 'where budget code is '5010172804''
        query_text = re.sub(
            r"(?i)\bwhere\s+(?:the\s+)?([a-zA-Z0-9_]+)_id\s+(?:is|=|matches)\s+['\"]?([A-Za-z0-9_-]{4,})['\"]?",
            r"where \1 code is '\2'",
            query_text
        )
        query_text = re.sub(
            r"(?i)\band\s+(?:the\s+)?([a-zA-Z0-9_]+)_id\s+(?:is|=|matches)\s+['\"]?([A-Za-z0-9_-]{4,})['\"]?",
            r"and \1 code is '\2'",
            query_text
        )
        query_text = re.sub(
            r"(?i),\s*(?:the\s+)?([a-zA-Z0-9_]+)_id\s+(?:is|=|matches)\s+['\"]?([A-Za-z0-9_-]{4,})['\"]?",
            r", \1 code is '\2'",
            query_text
        )

        for a in (alias_words or []):
            a_clean = a.strip().lower()
            if not a_clean:
                continue
            escaped_a = re.escape(a_clean)
            pattern1 = rf"(?i)\bwhere\s+(?:the\s+)?`?[a-zA-Z0-9_]+`?(?:\s*\([^)]*\))?\s*(?:is|=|ILIKE|LIKE)\s*['\"`]{escaped_a}['\"`]\s*,\s*"
            query_text = re.sub(pattern1, 'where ', query_text)

            pattern2 = rf"(?i)\bwhere\s+(?:the\s+)?`?[a-zA-Z0-9_]+`?(?:\s*\([^)]*\))?\s*(?:is|=|ILIKE|LIKE)\s*['\"`]{escaped_a}['\"`]\s+and\s+"
            query_text = re.sub(pattern2, 'where ', query_text)

            pattern3 = rf"(?i)\s+and\s+(?:the\s+)?`?[a-zA-Z0-9_]+`?(?:\s*\([^)]*\))?\s*(?:is|=|ILIKE|LIKE)\s*['\"`]{escaped_a}['\"`]"
            query_text = re.sub(pattern3, '', query_text)

            pattern4 = rf"(?i),\s*(?:the\s+)?`?[a-zA-Z0-9_]+`?(?:\s*\([^)]*\))?\s*(?:is|=|ILIKE|LIKE)\s*['\"`]{escaped_a}['\"`]"
            query_text = re.sub(pattern4, '', query_text)

            pattern5 = rf"(?i)\bwhere\s+(?:the\s+)?`?[a-zA-Z0-9_]+`?(?:\s*\([^)]*\))?\s*(?:is|=|ILIKE|LIKE)\s*['\"`]{escaped_a}['\"`]\.?"
            query_text = re.sub(pattern5, '.', query_text)

        return query_text

    @classmethod
    def _get_client(cls, timeout: Optional[float] = None) -> AsyncOpenAI:
        req_timeout = timeout or getattr(settings, "sql_llm_timeout_seconds", 30.0)
        return AsyncOpenAI(
            api_key=settings.deepinfra_api_key or "anonymous",
            base_url=settings.deepinfra_api_url or "https://api.deepinfra.com/v1/openai",
            timeout=req_timeout,
            max_retries=2,
        )

    @classmethod
    async def generate_3_rephrasings(
        cls,
        user_query: str,
        schema_docs: List[Dict[str, Any]],
        selected_tables: Optional[List[str]] = None,
        resolved_entities: Optional[List[Dict[str, Any]]] = None,
        table_alias_mappings: Optional[List[Dict[str, str]]] = None,
        model: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Dynamically generates 3 distinct, schema-grounded rephrased query options:
        1. Grouped / Aggregated Breakdown
        2. Detailed Itemized Listing
        3. Summary Metric / Count
        """
        if not user_query or not user_query.strip():
            return []

        # If specific tables were selected, isolate schema_docs strictly to those tables
        if selected_tables:
            sel_lower = {t.split(".")[-1].lower() for t in selected_tables}
            matched = [d for d in schema_docs if d.get("table_name", "").lower() in sel_lower]
            if matched:
                schema_docs = matched

        # Extract available tables and columns dynamically
        table_summaries = []
        for d in schema_docs:
            tbl = d.get("table_name", "")
            if not tbl:
                continue
            cols = d.get("column_names") or []
            fk_lines = re.findall(r'-\s*FOREIGN KEY\s*\(([^)]+)\)\s*REFERENCES\s*(?:[`"\w]+\.)?`?([a-zA-Z0-9_]+)`?\s*\(([^)]+)\)', d.get("text", ""), re.IGNORECASE)
            rel_str = ""
            if fk_lines:
                rel_str = "\n  Foreign Keys: " + ", ".join(f"`{tbl}.{src.strip('`')}` -> `{tgt_t.strip('`')}.{tgt_c.strip('`')}`" for src, tgt_t, tgt_c in fk_lines)
            if cols:
                col_list = ", ".join(cols[:40])
                table_summaries.append(f"- Table: `{tbl}`\n  Columns: {col_list}{rel_str}")
            else:
                table_summaries.append(f"- Table: `{tbl}`{rel_str}")

        schema_context = "\n".join(table_summaries) if table_summaries else "No schema docs available."
        selected_notice = ""
        if selected_tables:
            sel_str = ", ".join(f"`{t}`" for t in selected_tables)
            selected_notice = (
                f"\nCRITICAL: The user has explicitly selected target table(s): {sel_str}. "
                f"Every option MUST strictly and exclusively target these selected table(s) and their exact columns. "
                f"If the original user question references any other table or old query context, completely ignore that other table and rephrase the query intent specifically for {sel_str}.\n"
            )

        alias_notice = ""
        alias_words: List[str] = []
        if table_alias_mappings:
            alias_lines = []
            for m in table_alias_mappings:
                if isinstance(m, dict):
                    a_name = m.get("alias", "")
                    t_name = m.get("table", "")
                    if a_name and t_name:
                        alias_words.append(a_name)
                        alias_lines.append(f"- '{a_name}' is an alternative name (alias) for table `{t_name}`")
            if alias_lines:
                alias_notice = (
                    "\nCRITICAL TABLE ALIAS INSTRUCTION:\n"
                    "The following words/phrases in the user question are ALTERNATIVE NAMES (aliases) for tables:\n"
                    + "\n".join(alias_lines) + "\n"
                    "Rules for table aliases:\n"
                    "1. These alias tokens refer SOLELY to the database TABLE, NOT to any column value or filter.\n"
                    "2. NEVER interpret or rephrase a table alias token as a column filter (e.g. NEVER write 'where lob is ...', 'where name is ...', etc. for these alias words).\n"
                    "3. The user simply used the alias word to indicate which table to query.\n"
                )

        prompt = f"""You are a dynamic database query architect.
Given an informal user question and relational database schema, generate exactly 3 DISTINCT, practical ways to rephrase and execute the question against the actual database schema:

- Option 1 (Grouped Breakdown): Groups by the key column/entity with occurrence counts or aggregate measures.
- Option 2 (Detailed Records): Retrieves itemized records/columns for all matching entities with sorting.
- Option 3 (Summary Metric): Calculates overall totals, distinct counts, or statistical summary metrics.

Rules:
1. STRICT SCHEMA GROUNDING: You MUST ONLY reference tables and columns that are explicitly listed in 'Available Database Schema' below. Do NOT invent columns or tables.
2. Return ONLY a valid JSON array containing exactly 3 objects with these keys:
   - "id": 1, 2, or 3
   - "title": short title (2-4 words, e.g. "Grouped Duplicate Breakdown")
   - "tag": short badge tag (e.g. "Aggregation", "Detailed List", "Summary Count")
   - "rephrased_query": the complete, clear schema-aligned question to execute
   - "description": 1 short sentence explaining what data this option retrieves

{selected_notice}
{alias_notice}
Available Database Schema:
{schema_context}

Original User Question: "{user_query}"

Respond with ONLY the JSON array (no markdown code blocks, no explanations):"""

        chosen_model = model or getattr(settings, "sql_generation_model", "deepseek-ai/DeepSeek-V3")
        client = cls._get_client()

        try:
            response = await client.chat.completions.create(
                model=chosen_model,
                messages=[
                    {"role": "system", "content": "You are a database query architect. Output ONLY valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=600,
            )
            raw_text = response.choices[0].message.content.strip()
            # Clean markdown code fences if LLM wrapped in ```json
            if "```" in raw_text:
                raw_text = re.sub(r"^```[a-zA-Z]*\n?", "", raw_text)
                raw_text = re.sub(r"\n?```$", "", raw_text)
            raw_text = raw_text.strip()

            parsed = json.loads(raw_text)
            if isinstance(parsed, list) and len(parsed) > 0:
                for opt in parsed:
                    if isinstance(opt, dict):
                        if "rephrased_query" in opt:
                            opt["rephrased_query"] = cls.sanitize_enriched_query(opt["rephrased_query"], alias_words)
                        if "description" in opt:
                            opt["description"] = cls.sanitize_enriched_query(opt["description"], alias_words)
                logger.info(f"[QUERY_ENRICHER] Successfully generated {len(parsed)} rephrasing options for '{user_query}'")
                return parsed[:3]
        except Exception as exc:
            logger.warning(f"[QUERY_ENRICHER] Failed to generate 3 rephrasings via LLM ({exc}). Generating fallback options.")

        # Robust deterministic fallback if LLM or JSON fails
        target_tbl = selected_tables[0] if (selected_tables and len(selected_tables) > 0) else (schema_docs[0].get("table_name", "target_table") if schema_docs else "target_table")
        first_cols = schema_docs[0].get("column_names", ["id", "name"]) if schema_docs else ["id", "name"]
        key_col = next((c for c in first_cols if any(k in c.lower() for k in ("name", "code", "guid", "id", "title"))), first_cols[0] if first_cols else "id")

        return [
            {
                "id": 1,
                "title": "Grouped Breakdown",
                "tag": "Aggregation",
                "rephrased_query": f"List duplicate `{key_col}` values in `{target_tbl}` grouped by `{key_col}` with count greater than 1.",
                "description": f"Groups records by `{key_col}` to inspect frequency and find duplicate occurrences.",
            },
            {
                "id": 2,
                "title": "Detailed Record Listing",
                "tag": "Detailed Records",
                "rephrased_query": f"Retrieve all rows from `{target_tbl}` where `{key_col}` has duplicate entries, ordered by `{key_col}`.",
                "description": f"Selects full record attributes for items with matching `{key_col}` values.",
            },
            {
                "id": 3,
                "title": "Total Metric Summary",
                "tag": "Summary Count",
                "rephrased_query": f"Calculate the total count and distinct count of records in `{target_tbl}` matching '{user_query}'.",
                "description": f"Provides an aggregate summary metric of matching entries in `{target_tbl}`.",
            },
        ]

    @classmethod
    async def enrich_query(
        cls,
        user_query: str,
        schema_docs: List[Dict[str, Any]],
        selected_tables: Optional[List[str]] = None,
        resolved_entities: Optional[List[Dict[str, Any]]] = None,
        table_alias_mappings: Optional[List[Dict[str, str]]] = None,
        model: Optional[str] = None,
    ) -> str:
        """
        Dynamically enrich and clarify the user's natural language question
        based on the actual database schema and user-selected tables.
        """
        if not user_query or not user_query.strip():
            return user_query

        # If specific tables were selected, isolate schema_docs strictly to those tables
        if selected_tables:
            sel_lower = {t.split(".")[-1].lower() for t in selected_tables}
            matched = [d for d in schema_docs if d.get("table_name", "").lower() in sel_lower]
            if matched:
                schema_docs = matched

        # Extract available tables and columns dynamically
        table_summaries = []
        for d in schema_docs:
            tbl = d.get("table_name", "")
            if not tbl:
                continue
            cols = d.get("column_names") or []
            fk_lines = re.findall(r'-\s*FOREIGN KEY\s*\(([^)]+)\)\s*REFERENCES\s*(?:[`"\w]+\.)?`?([a-zA-Z0-9_]+)`?\s*\(([^)]+)\)', d.get("text", ""), re.IGNORECASE)
            rel_str = ""
            if fk_lines:
                rel_str = "\n  Foreign Keys: " + ", ".join(f"`{tbl}.{src.strip('`')}` -> `{tgt_t.strip('`')}.{tgt_c.strip('`')}`" for src, tgt_t, tgt_c in fk_lines)
            if cols:
                col_list = ", ".join(cols[:40])
                table_summaries.append(f"- Table: `{tbl}`\n  Columns: {col_list}{rel_str}")
            else:
                table_summaries.append(f"- Table: `{tbl}`{rel_str}")

        if not table_summaries:
            return user_query

        schema_context = "\n".join(table_summaries)
        selected_notice = ""
        if selected_tables:
            sel_str = ", ".join(f"`{t}`" for t in selected_tables)
            selected_notice = (
                f"\nCRITICAL: The user has explicitly selected target table(s): {sel_str}. "
                f"You MUST rewrite the query specifically targeting these selected table(s) and their exact columns. "
                f"If the question references any other table name, replace it with {sel_str}.\n"
            )

        alias_notice = ""
        alias_words: List[str] = []
        if table_alias_mappings:
            alias_lines = []
            for m in table_alias_mappings:
                if isinstance(m, dict):
                    a_name = m.get("alias", "")
                    t_name = m.get("table", "")
                    if a_name and t_name:
                        alias_words.append(a_name)
                        alias_lines.append(f"- '{a_name}' is an alternative name (alias) for table `{t_name}`")
            if alias_lines:
                alias_notice = (
                    "\nCRITICAL TABLE ALIAS INSTRUCTION:\n"
                    "The following words/phrases in the user question are ALTERNATIVE NAMES (aliases) for tables:\n"
                    + "\n".join(alias_lines) + "\n"
                    "Rules for table aliases:\n"
                    "1. These alias tokens refer SOLELY to the database TABLE, NOT to any column value or filter.\n"
                    "2. NEVER interpret or rephrase a table alias token as a column filter (e.g. NEVER write 'where lob is ...', 'where name is ...', etc. for these alias words).\n"
                    "3. The user simply used the alias word to indicate which table to query.\n"
                )

        prompt = f"""You are a dynamic schema-grounded query enricher for relational databases.
Users often ask vague, informal, or conversational questions (e.g., "list all duplicate name", "show pending items", "best recent customers").
Your task is to enrich and clarify the user's question into an explicit, unambiguous natural language instruction that maps directly to the actual database schema.

Rules:
1. STRICT SCHEMA GROUNDING: You MUST ONLY use tables and columns that are explicitly listed under 'Available Database Schema' below. NEVER mention, invent, or assume any table (such as `add_ons` or `affiliate`) unless that exact table is listed below in 'Available Database Schema'. If a user query refers to a table not in the schema, ground it ONLY in the provided available tables.
2. DISAMBIGUATE TERMS:
   - "duplicate" -> identify the specific column (e.g. name, code, email) and specify grouping by that column with COUNT(*) > 1.
   - "recent / latest" -> order by the relevant date/timestamp or primary key descending.
   - "approved / pending / rejected / submitted / completed / closed / draft" -> filter by the actual status/stage column present in the schema (e.g. `stage`, `status`, `state`, `phase`). NEVER write "where approved is TRUE" or invent boolean columns for workflow status terms! Write "where the `stage` is 'approved'".
   - "budget available in 0 / budget is 0 / count = 0 / zero amount" -> filter using numeric comparison on the amount/budget column (e.g. "where the `budget` is 0" or "where `balance` is 0"). NEVER write "where budgeted is false"!
   - "budgetcode / project code / category name / foreign entity code or name" -> Columns ending in `_id` (e.g. `budget_id`, `project_id`) are foreign keys referencing parent table `id`s, NOT business codes! When the user specifies a code or name for a referenced entity (e.g. "budgetcode 5010172804"), specify joining the child table to the parent table on the foreign key (`cm_budget_requests.budget_id = cm_budgets.id`) and filtering on the parent table's `code` column (`cm_budgets.code` is "5010172804"). NEVER write "where budget_id is '5010172804'"!
   - "list all duplicate name" -> select the name column and count, grouped by the name column having count > 1 (do NOT ask for a single aggregate count if user asked to "list all").
3. PRESERVE INTENT: Do not change what the user wants to know; only make it crystal clear, referencing the exact table and column names.
4. Keep the enriched query concise (1-3 sentences). Return ONLY the enriched question without explanations or code fences.

{selected_notice}
{alias_notice}
Available Database Schema:
{schema_context}

Original User Question: "{user_query}"

Enriched Schema-Grounded Question:"""

        chosen_model = model or getattr(settings, "sql_generation_model", "deepseek-ai/DeepSeek-V3")
        client = cls._get_client()

        try:
            response = await client.chat.completions.create(
                model=chosen_model,
                messages=[
                    {"role": "system", "content": "You enrich and clarify natural language questions against database schemas. Be concise and precise."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=256,
            )
            enriched = response.choices[0].message.content.strip()
            # Clean up quotes if returned
            if enriched.startswith('"') and enriched.endswith('"'):
                enriched = enriched[1:-1].strip()
            if enriched:
                enriched = cls.sanitize_enriched_query(enriched, alias_words)
                logger.info(f"[QUERY_ENRICHER] Original: '{user_query}' -> Enriched: '{enriched}'")
                return enriched
            return user_query
        except Exception as exc:
            logger.warning(f"[QUERY_ENRICHER] Failed to enrich query dynamically ({exc}). Using original query.")
            return user_query
