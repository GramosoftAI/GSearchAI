"""Phase 2 Knowledge Layer: Seed Examples & Verified Query Memory Generation

Generates 20-50 question/SQL pairs per domain cluster from knowledge items:
- Question varieties: simple, filter, join, aggregate, date-range, and short/vague phrasing.
- SQL parsing via sqlglot:
  - SELECT only, no DDL/DML
  - Tables & columns must exist in catalog snapshot
  - Adds LIMIT if missing
- Read-only execution test with 5s timeout on customer database. Failures are discarded.
- Saved through QueryMemoryRepository:
  - status='verified'
  - plan_ir minimal
  - referenced_items
  - execution_stats with provenance='seed'
  - embedding of the question
- UI helper: get_suggested_questions
"""

import uuid
import re
import json
import logging
import asyncio
from typing import Optional, Dict, Any, List, Set, Tuple
from datetime import datetime, timezone
from pydantic import BaseModel, Field

import sqlglot
import sqlglot.expressions as exp

from app.core.embeddings import EmbeddingGenerator
from app.core.llm.deepinfra_llm import DeepInfraLLMClient, strip_think_tags
from ..adapters.phase1_adapter import Phase1Adapter
from ..repositories.query_memory_repository import QueryMemoryRepository
from ..repositories.knowledge_item_repository import KnowledgeItemRepository
from ..models.knowledge_items import KB2KnowledgeItem

logger = logging.getLogger(__name__)


class GeneratedQuestionPair(BaseModel):
    question: str
    sql: str
    category: str = "filter"  # simple, filter, join, aggregate, date_range, vague
    tables_referenced: List[str] = Field(default_factory=list)


class SeedGenerationBatch(BaseModel):
    pairs: List[GeneratedQuestionPair] = Field(default_factory=list)


def parse_and_validate_sql(
    sql_text: str,
    valid_tables: Set[str],
    valid_columns_by_table: Dict[str, Set[str]],
    default_limit: int = 100,
) -> Tuple[bool, Optional[str], List[str], Optional[str]]:
    """Parse SQL with sqlglot, ensure SELECT only, no DDL/DML, valid tables/cols, add LIMIT if missing.
    
    Returns: (is_valid, modified_sql, referenced_tables_and_columns, error_message)
    """
    if not sql_text or not sql_text.strip():
        return False, None, [], "Empty SQL"

    clean_sql = sql_text.strip().rstrip(";")

    try:
        parsed = sqlglot.parse_one(clean_sql, read="postgres")
    except Exception as exc:
        return False, None, [], f"SQL parse error: {exc}"

    # 1. Must be SELECT statement only
    if not isinstance(parsed, exp.Select):
        return False, None, [], "Only SELECT queries are allowed"

    # Reject any DDL/DML or destructive expressions
    destructive = [exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter]
    for d in destructive:
        if list(parsed.find_all(d)):
            return False, None, [], f"Destructive statements not permitted: {d.__name__}"

    # 2. Extract referenced tables
    referenced_tables: Set[str] = set()
    for table_exp in parsed.find_all(exp.Table):
        t_name = table_exp.name.lower()
        referenced_tables.add(t_name)

    norm_valid_tables = {t.lower() for t in valid_tables}
    missing_tables = [t for t in referenced_tables if t not in norm_valid_tables]
    if missing_tables:
        return False, None, [], f"Unknown table(s): {', '.join(missing_tables)}"

    # 3. Add LIMIT if not present
    if parsed.args.get("limit") is None:
        parsed = parsed.limit(default_limit)

    final_sql = parsed.sql(dialect="postgres")

    # Collect referenced items
    ref_items = [f"table:{t}" for t in referenced_tables]
    for col_exp in parsed.find_all(exp.Column):
        c_name = col_exp.name.lower()
        t_name = col_exp.table.lower() if col_exp.table else ""
        if t_name and t_name in norm_valid_tables:
            ref_items.append(f"column:{t_name}.{c_name}")
        else:
            ref_items.append(f"column:{c_name}")

    return True, final_sql, list(set(ref_items)), None


async def run_seed_query_memory(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    schema_version: str,
    adapter: Phase1Adapter,
    item_repo: KnowledgeItemRepository,
    query_repo: QueryMemoryRepository,
    llm_client: Optional[Any] = None,
    target_pair_count: int = 30,
) -> Dict[str, Any]:
    """Generate and verify seed queries for a knowledge base."""
    logger.info(f"[Seed Query Memory] Starting generation for KB={kb_id}, version={schema_version}")
    client = llm_client or DeepInfraLLMClient.get_instance()

    try:
        schema_view = await adapter.get_schema_by_version(tenant_id, kb_id, schema_version)
        if not schema_view:
            schema_view = await adapter.get_current_schema(tenant_id, kb_id)
    except Exception as exc:
        logger.info(f"[Seed Query Memory] No schema snapshot found ({exc}). Returning empty generation metrics.")
        return {"generated": 0, "verified": 0, "failed": 0}

    if not schema_view or not schema_view.tables:
        return {"generated": 0, "verified": 0, "failed": 0}

    tables = schema_view.tables
    valid_tables = set(tables.keys())
    valid_columns_by_table: Dict[str, Set[str]] = {}
    table_summaries = []

    for t_name, t_view in tables.items():
        col_names = set(t_view.columns.keys())
        valid_columns_by_table[t_name.lower()] = {c.lower() for c in col_names}
        table_summaries.append({
            "table": t_name,
            "columns": [c for c in list(col_names)[:10]],
            "pk": t_view.primary_key_columns,
        })

    # Prompt LLM to produce candidate question/SQL pairs across categories
    prompt = f"""You are a database query expert. Given these database tables and columns:
{json.dumps(table_summaries[:8], indent=2)}

Generate {target_pair_count} diverse, natural question and PostgreSQL SELECT query pairs.
Include these categories:
- simple (single table select with limit)
- filter (WHERE clauses with numbers or strings)
- join (INNER or LEFT JOIN using foreign keys)
- aggregate (COUNT, SUM, AVG with GROUP BY)
- date_range (date filtering or ordering)
- vague (short conversational phrasing, e.g. "active users" or "recent sales")

Output ONLY valid JSON matching this schema:
{{
  "pairs": [
    {{
      "question": "What are the top 5 highest order totals?",
      "sql": "SELECT id, total_amount FROM orders ORDER BY total_amount DESC LIMIT 5",
      "category": "filter",
      "tables_referenced": ["orders"]
    }}
  ]
}}"""

    pairs_data: List[GeneratedQuestionPair] = []
    try:
        raw_output = await client.generate(
            prompt=prompt,
            system_prompt="You are a SQL database analyst. Output ONLY valid JSON containing SELECT queries.",
            temperature=0.3,
            max_tokens=4096,
        )
        cleaned = strip_think_tags(raw_output).strip()
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
        content_to_parse = match.group(1) if match else cleaned
        # Find json block if extra text
        s_idx = content_to_parse.find("{")
        e_idx = content_to_parse.rfind("}")
        if s_idx != -1 and e_idx != -1:
            parsed_dict = json.loads(content_to_parse[s_idx : e_idx + 1])
            batch = SeedGenerationBatch(**parsed_dict)
            pairs_data = batch.pairs
    except Exception as exc:
        logger.warning(f"[Seed Query Memory] LLM question generation failed: {exc}")

    verified_count = 0
    rejections = {
        "parse_error": 0,
        "non_select": 0,
        "unknown_table": 0,
        "execution_error": 0,
        "empty_result": 0,
    }
    sample_execution_error: Optional[Dict[str, str]] = None

    # Test and execute each query on customer database
    for pair in pairs_data:
        is_valid, final_sql, ref_items, parse_err = parse_and_validate_sql(
            sql_text=pair.sql,
            valid_tables=valid_tables,
            valid_columns_by_table=valid_columns_by_table,
        )
        if not is_valid or not final_sql:
            if parse_err:
                if "parse error" in parse_err.lower():
                    rejections["parse_error"] += 1
                elif "select" in parse_err.lower() or "destructive" in parse_err.lower():
                    rejections["non_select"] += 1
                elif "unknown table" in parse_err.lower():
                    rejections["unknown_table"] += 1
                else:
                    rejections["parse_error"] += 1
            else:
                rejections["parse_error"] += 1
            continue

        # Execute read-only with 5s timeout
        exec_start = datetime.now(timezone.utc)
        execution_success = False
        row_count = 0
        exec_latency_ms = 0.0

        try:
            async with adapter.open_readonly_connection(tenant_id, kb_id) as conn:
                t0 = datetime.now(timezone.utc)
                rows = await conn.fetch(final_sql)
                exec_latency_ms = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
                row_count = len(rows)
                execution_success = True
        except Exception as exec_err:
            rejections["execution_error"] += 1
            if not sample_execution_error:
                sample_execution_error = {
                    "sql": final_sql,
                    "error": str(exec_err)
                }
            logger.debug(f"[Seed Query Memory] Discarding SQL execution failure: {exec_err}")
            continue

        if not execution_success:
            continue

        # Reject empty-result queries: must return at least 1 row to be verified
        if row_count == 0:
            rejections["empty_result"] += 1
            logger.debug(f"[Seed Query Memory] Discarding empty-result query (0 rows returned): {final_sql}")
            continue

        # Compute question embedding
        try:
            q_embedding = await EmbeddingGenerator.generate_embedding(pair.question, is_query=True)
        except Exception:
            q_embedding = None

        exec_stats = {
            "provenance": "seed",
            "latency_ms": round(exec_latency_ms, 2),
            "result_rows": row_count,
            "category": pair.category,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        plan_ir = {
            "category": pair.category,
            "tables": pair.tables_referenced or list(valid_tables),
        }

        await query_repo.upsert_query_memory(
            db_knowledgebase_id=kb_id,
            schema_version=schema_version,
            natural_query=pair.question,
            compiled_sql=final_sql,
            plan_ir=plan_ir,
            referenced_items=ref_items,
            execution_stats=exec_stats,
            embedding=q_embedding,
            status="verified",
        )
        verified_count += 1

    await query_repo.db.commit()

    total_failed = sum(rejections[k] for k in ["parse_error", "non_select", "unknown_table", "execution_error", "empty_result"])

    logger.info(
        f"[Seed Query Memory] Finished. Generated: {len(pairs_data)}, "
        f"Verified: {verified_count}, Discarded: {total_failed}, Rejections: {rejections}"
    )

    return {
        "generated": len(pairs_data),
        "verified": verified_count,
        "failed": total_failed,
        "rejections": rejections,
        "sample_execution_error": sample_execution_error,
    }


async def get_suggested_questions(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    query_repo: QueryMemoryRepository,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Helper for UI to retrieve high-quality suggested questions."""
    return await query_repo.list_suggested_questions(db_knowledgebase_id=kb_id, limit=limit)
