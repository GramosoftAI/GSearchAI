"""Phase 3 Evaluation Runner (Step 3.2)

Evaluates retrieval pipeline against tests/eval/customer_sim_eval.json benchmark.
Computes:
- table recall@10
- column recall@5
- entity accuracy
- ambiguity accuracy
- unanswerable accuracy
- join accuracy
- Per-category metrics breakdown

Runnable via:
    python -m tests.eval.run_eval
"""

import sys
import os
import json
from pathlib import Path
from typing import Dict, Any, List, Set


def retrieve(question: str) -> Dict[str, Any]:
    """Pluggable schema retrieval function wired to ContextPackBuilder."""
    import asyncio
    import uuid
    from app.core.database import AsyncSessionLocal
    from app.modules.database_knowledgebase.knowledge.retrieval.context_pack import ContextPackBuilder
    from app.modules.database_knowledgebase.models.database_knowledgebase import DatabaseKnowledgebase
    from sqlalchemy import select

    async def _run():
        async with AsyncSessionLocal() as db:
            stmt = select(DatabaseKnowledgebase).order_by(DatabaseKnowledgebase.created_at.desc()).limit(1)
            res = await db.execute(stmt)
            kb = res.scalar_one_or_none()
            if not kb:
                return {
                    "tables": [],
                    "columns": [],
                    "entities": [],
                    "join_tables": [],
                    "is_unanswerable": False,
                    "needs_clarification": False,
                }

            builder = ContextPackBuilder(db=db, tenant_id=kb.tenant_id)
            pack = await builder.build(db_knowledgebase_id=kb.id, question=question)

            # Extract formatted return
            tables = [t["name"] for t in pack.tables]
            columns = [f"{c['table']}.{c['name']}" for c in pack.columns]
            entities = pack.entities
            join_tables = list(dict.fromkeys(
                [j["left_table"] for j in pack.joins] + [j["right_table"] for j in pack.joins]
            ))
            is_unans = pack.unanswerable.get("flag", False)
            needs_clar = len(pack.clarifications) > 0

            return {
                "tables": tables,
                "columns": columns,
                "entities": entities,
                "join_tables": join_tables,
                "is_unanswerable": is_unans,
                "needs_clarification": needs_clar,
            }

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(_run())
        else:
            return asyncio.run(_run())
    except Exception:
        return asyncio.run(_run())


def compute_recall_at_k(actual: List[str], retrieved: List[str], k: int) -> float:
    """Compute recall@k for a list of target items."""
    if not actual:
        return 1.0  # vacuously true if no target
    top_k = set(retrieved[:k])
    matched = sum(1 for item in actual if item in top_k)
    return matched / len(actual)


def evaluate_benchmark(eval_file: Path) -> Dict[str, Any]:
    with open(eval_file, "r", encoding="utf-8") as f:
        questions: List[Dict[str, Any]] = json.load(f)

    total_q = len(questions)
    category_metrics: Dict[str, Dict[str, Any]] = {}

    table_recall_scores = []
    column_recall_scores = []
    entity_acc_scores = []
    ambiguity_acc_scores = []
    unanswerable_acc_scores = []
    join_acc_scores = []

    for item in questions:
        cat = item.get("category", "default")
        if cat not in category_metrics:
            category_metrics[cat] = {
                "count": 0,
                "table_rec": [],
                "col_rec": [],
                "entity_acc": [],
                "ambig_acc": [],
                "unans_acc": [],
                "join_acc": [],
            }

        q_text = item["question"]
        res = retrieve(q_text)

        # 1. Table recall@10
        exp_tables = item.get("expected_tables", [])
        ret_tables = res.get("tables", [])
        t_rec = compute_recall_at_k(exp_tables, ret_tables, k=10)
        table_recall_scores.append(t_rec)

        # 2. Column recall@5
        exp_cols = item.get("expected_columns", [])
        ret_cols = res.get("columns", [])
        c_rec = compute_recall_at_k(exp_cols, ret_cols, k=5)
        column_recall_scores.append(c_rec)

        # 3. Entity accuracy
        exp_ents = item.get("expected_entities", [])
        ret_ents = res.get("entities", [])
        # If expected entities exist and not ambiguous, check match
        named_exp = [e for e in exp_ents if "value" in e]
        if named_exp:
            ret_vals = {e.get("value") for e in ret_ents if "value" in e}
            ent_acc = 1.0 if any(e["value"] in ret_vals for e in named_exp) else 0.0
            entity_acc_scores.append(ent_acc)
        else:
            ent_acc = 1.0 if not ret_ents else 0.0
            entity_acc_scores.append(ent_acc)

        # 4. Ambiguity accuracy
        exp_ambig = item.get("expect_clarification", False) or any(e.get("ambiguous") for e in exp_ents)
        ret_ambig = res.get("needs_clarification", False) or any(e.get("ambiguous") for e in ret_ents)
        ambig_acc = 1.0 if (exp_ambig == ret_ambig) else 0.0
        ambiguity_acc_scores.append(ambig_acc)

        # 5. Unanswerable accuracy
        exp_unans = item.get("expect_unanswerable", False)
        ret_unans = res.get("is_unanswerable", False)
        unans_acc = 1.0 if (exp_unans == ret_unans) else 0.0
        unanswerable_acc_scores.append(unans_acc)

        # 6. Join accuracy
        exp_joins = set(item.get("expected_join_tables", []))
        ret_joins = set(res.get("join_tables", []))
        if exp_joins:
            join_acc = 1.0 if exp_joins.issubset(ret_joins) else 0.0
            join_acc_scores.append(join_acc)
        else:
            join_acc = 1.0 if not ret_joins else 0.0
            join_acc_scores.append(join_acc)

        # Append per category
        c_stats = category_metrics[cat]
        c_stats["count"] += 1
        c_stats["table_rec"].append(t_rec)
        c_stats["col_rec"].append(c_rec)
        c_stats["entity_acc"].append(ent_acc)
        c_stats["ambig_acc"].append(ambig_acc)
        c_stats["unans_acc"].append(unans_acc)
        c_stats["join_acc"].append(join_acc)

    def _avg(lst: List[float]) -> float:
        return sum(lst) / len(lst) if lst else 0.0

    overall = {
        "total_questions": total_q,
        "table_recall@10": _avg(table_recall_scores),
        "column_recall@5": _avg(column_recall_scores),
        "entity_accuracy": _avg(entity_acc_scores),
        "ambiguity_accuracy": _avg(ambiguity_acc_scores),
        "unanswerable_accuracy": _avg(unanswerable_acc_scores),
        "join_accuracy": _avg(join_acc_scores),
    }

    per_category = {}
    for cat, vals in category_metrics.items():
        per_category[cat] = {
            "count": vals["count"],
            "table_recall@10": _avg(vals["table_rec"]),
            "column_recall@5": _avg(vals["col_rec"]),
            "entity_accuracy": _avg(vals["entity_acc"]),
            "ambiguity_accuracy": _avg(vals["ambig_acc"]),
            "unanswerable_accuracy": _avg(vals["unans_acc"]),
            "join_accuracy": _avg(vals["join_acc"]),
        }

    return {"overall": overall, "categories": per_category}


def main():
    base_dir = Path(__file__).resolve().parent
    eval_file = base_dir / "customer_sim_eval.json"
    if not eval_file.exists():
        print(f"Error: {eval_file} not found")
        sys.exit(1)

    results = evaluate_benchmark(eval_file)
    overall = results["overall"]
    categories = results["categories"]

    print("=" * 70)
    print("PHASE 3 STEP 3.2 RETRIEVAL EVALUATION RESULTS (BASELINE STUB)")
    print("=" * 70)
    print(f"Total Questions Evaluated: {overall['total_questions']}")
    print("-" * 70)
    print(f"Table Recall@10:       {overall['table_recall@10'] * 100:6.2f}%")
    print(f"Column Recall@5:       {overall['column_recall@5'] * 100:6.2f}%")
    print(f"Entity Accuracy:       {overall['entity_accuracy'] * 100:6.2f}%")
    print(f"Ambiguity Accuracy:    {overall['ambiguity_accuracy'] * 100:6.2f}%")
    print(f"Unanswerable Accuracy: {overall['unanswerable_accuracy'] * 100:6.2f}%")
    print(f"Join Accuracy:         {overall['join_accuracy'] * 100:6.2f}%")
    print("-" * 70)
    print(f"{'Category':<20} {'Count':<6} {'Table R@10':<12} {'Col R@5':<10} {'Entity Acc':<11} {'Join Acc':<9}")
    print("-" * 70)
    for cat, c_val in categories.items():
        print(
            f"{cat:<20} {c_val['count']:<6} "
            f"{c_val['table_recall@10'] * 100:6.1f}%      "
            f"{c_val['column_recall@5'] * 100:6.1f}%   "
            f"{c_val['entity_accuracy'] * 100:6.1f}%    "
            f"{c_val['join_accuracy'] * 100:6.1f}%"
        )
    print("=" * 70)

    # Validate all expected tables & columns exist in customer_sim
    invalid_tables, invalid_cols = validate_eval_against_schema(eval_file)
    if invalid_tables or invalid_cols:
        print(f"[SCHEMA VALIDATION WARNING] Invalid tables: {invalid_tables}, Invalid columns: {invalid_cols}")
    else:
        print("[SCHEMA VALIDATION] All expected tables and columns exist in customer_sim schema snapshot.")


def validate_eval_against_schema(eval_file: Path) -> tuple[Set[str], Set[str]]:
    """Validate that every expected table and column in eval dataset exists in customer_sim."""
    customer_sim_tables = {
        "users", "orders", "tx_log", "branches", "payments",
        "customers", "employees", "ref_codes", "attendance",
        "departments", "t_cryptic_1", "t_cryptic_2"
    }
    customer_sim_columns = {
        "users.user_id", "users.username", "users.is_verified", "users.last_login_at", "users.password_hash", "users.secret_auth_token",
        "orders.order_id", "orders.order_date", "orders.customer_id", "orders.items_count", "orders.order_status", "orders.order_total_amt", "orders.discount_percent",
        "tx_log.tx_id", "tx_hash", "tx_log.order_id", "tx_log.created_at", "tx_log.is_success", "tx_log.latency_ms", "tx_log.operation_type",
        "branches.city", "branches.branch_id", "branches.created_at", "branches.branch_code", "branches.country_code", "branches.headcount_target",
        "payments.cvv_code", "payments.order_id", "payments.payment_id", "payments.paid_amount", "payments.payment_method", "payments.payment_timestamp", "payments.card_number_masked",
        "customers.full_name", "customers.created_at", "customers.customer_id", "customers.loyalty_tier", "customers.phone_number", "customers.customer_email",
        "employees.emp_id", "employees.dept_id", "employees.branch_id", "employees.hire_date", "employees.last_name", "employees.first_name", "employees.salary_amt", "employees.is_terminated", "employees.performance_score",
        "ref_codes.code_id", "ref_codes.is_enabled", "ref_codes.category_name", "ref_codes.display_order",
        "attendance.emp_id", "attendance.record_id", "attendance.work_date", "attendance.check_in_time", "attendance.at_work_second", "attendance.overtime_hours", "attendance.break_duration_min",
        "departments.dept_id", "departments.dept_name", "departments.is_active", "departments.budget_amt", "departments.created_at",
        "t_cryptic_1.x_id", "t_cryptic_1.c_val", "t_cryptic_1.q_cnt", "t_cryptic_1.f_ratio", "t_cryptic_1.t_stamp", "t_cryptic_1.user_id",
        "t_cryptic_2.b_flg", "t_cryptic_2.m_amt", "t_cryptic_2.k_code", "t_cryptic_2.v_desc"
    }

    with open(eval_file, "r", encoding="utf-8") as f:
        questions = json.load(f)

    invalid_t = set()
    invalid_c = set()
    for q in questions:
        for t in q.get("expected_tables", []):
            if t not in customer_sim_tables:
                invalid_t.add(t)
        for c in q.get("expected_columns", []):
            if c not in customer_sim_columns:
                invalid_c.add(c)
    return invalid_t, invalid_c


if __name__ == "__main__":
    main()
