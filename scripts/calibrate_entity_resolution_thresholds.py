"""Threshold & Weight Calibration Script for Schema-Grounded Entity Resolution

Sweeps embedding/fuzzy weights and confidence thresholds against enterprise
golden corpus schema queries to evaluate precision/recall and calibrate defaults.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Dict, List, Tuple
from app.modules.database_knowledgebase.planning.pos_extractor import Candidate, POSCandidateExtractor
from app.modules.database_knowledgebase.planning.schema_entity_resolver import (
    EntityConfidence,
    ResolvedEntity,
    SchemaEntityResolver,
)
from app.modules.database_knowledgebase.schemas.canonical import (
    ColumnDataType,
    ColumnSchema,
    DatabaseSchema,
    RelationshipSchema,
    RelationshipType,
    SchemaInfo,
    TableSchema,
)


def build_calibration_schema() -> DatabaseSchema:
    """Enterprise canonical schema with HR, Finance, and Project domains."""
    emp_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="int", is_primary_key=True),
        "first_name": ColumnSchema(name="first_name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        "email": ColumnSchema(name="email", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
    }
    work_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="int", is_primary_key=True),
        "employee_id_id": ColumnSchema(name="employee_id_id", data_type=ColumnDataType.INTEGER, raw_data_type="int"),
        "department_id_id": ColumnSchema(name="department_id_id", data_type=ColumnDataType.INTEGER, raw_data_type="int"),
        "basic_salary": ColumnSchema(name="basic_salary", data_type=ColumnDataType.DECIMAL, raw_data_type="numeric"),
    }
    dept_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="int", is_primary_key=True),
        "department": ColumnSchema(name="department", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
    }
    proj_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="int", is_primary_key=True),
        "project_name": ColumnSchema(name="project_name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        "budget": ColumnSchema(name="budget", data_type=ColumnDataType.DECIMAL, raw_data_type="numeric"),
    }

    tables = {
        "employee_employee": TableSchema(schema_name="public", table_name="employee_employee", columns=emp_cols),
        "employee_employeeworkinformation": TableSchema(schema_name="public", table_name="employee_employeeworkinformation", columns=work_cols),
        "base_department": TableSchema(schema_name="public", table_name="base_department", columns=dept_cols),
        "project_project": TableSchema(schema_name="public", table_name="project_project", columns=proj_cols),
    }

    return DatabaseSchema(database_name="test_db", schemas={"public": SchemaInfo(schema_name="public", tables=tables)})


BENCHMARK_CASES = [
    # (query, expected_entities, expected_pred_cols, non_entities)
    ("Show employees earning more than 80000 and their departments.", ["employee", "department"], ["basic_salary"], ["earning", "more"]),
    ("Show employees with basic salary above 50000.", ["employee"], ["basic_salary"], ["above"]),
    ("Show all departments and projects.", ["department", "project"], [], ["all", "and"]),
    ("Show projects with budget greater than 100000.", ["project"], ["budget"], ["greater"]),
    ("Which employees belong to each department?", ["employee", "department"], [], ["belong", "which"]),
]


async def run_calibration() -> None:
    schema = build_calibration_schema()
    all_candidate_tables = list(schema.schemas["public"].tables.values())

    weight_candidates = [
        (0.60, 0.40),
        (0.70, 0.30),
        (0.75, 0.25),
        (0.80, 0.20),
        (0.85, 0.15),
    ]
    threshold_candidates = [
        (0.70, 0.45, 0.25),
        (0.75, 0.50, 0.30),
        (0.80, 0.55, 0.35),
    ]

    best_score = -1.0
    best_config = None
    shared_token_emb: Dict[str, List[float]] = {}
    shared_target_emb: Dict[str, List[float]] = {}

    print("=" * 70)
    print("CALIBRATING SCHEMA-GROUNDED RESOLUTION WEIGHTS & THRESHOLDS")
    print("=" * 70)

    for ew, fw in weight_candidates:
        for ht, mt, lt in threshold_candidates:
            tp, fp, fn = 0, 0, 0

            for query, expected_ents, expected_cols, non_ents in BENCHMARK_CASES:
                candidates = POSCandidateExtractor.extract(query)
                resolved = await SchemaEntityResolver.resolve_candidates(
                    candidates=candidates,
                    canonical_schema=schema,
                    candidate_tables=all_candidate_tables,
                    embedding_weight=ew,
                    fuzzy_weight=fw,
                    high_threshold=ht,
                    medium_threshold=mt,
                    low_threshold=lt,
                    token_embeddings=shared_token_emb,
                    target_embeddings=shared_target_emb,
                )

                resolved_names = {
                    r.resolved_to.split(".")[-1].lower()
                    for r in resolved
                    if r.resolved_to and r.confidence in (EntityConfidence.HIGH, EntityConfidence.MEDIUM)
                }

                # Evaluate true positives and false negatives on expected entities
                for exp in expected_ents:
                    if any(exp in r_name for r_name in resolved_names):
                        tp += 1
                    else:
                        fn += 1

                # Evaluate non-entities: must not be resolved with HIGH/MEDIUM confidence
                for ne in non_ents:
                    ne_res = next((r for r in resolved if r.token == ne), None)
                    if ne_res and ne_res.confidence in (EntityConfidence.HIGH, EntityConfidence.MEDIUM):
                        fp += 1

            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
            f05 = (1.25 * precision * recall) / (0.25 * precision + recall) if (0.25 * precision + recall) > 0 else 0.0

            if f05 > best_score:
                best_score = f05
                best_config = (ew, fw, ht, mt, lt, precision, recall, f1, f05)

    ew, fw, ht, mt, lt, prec, rec, f1, f05 = best_config
    print(f"\nOPTIMAL CALIBRATED CONFIGURATION (F0.5 Precision-Optimized):")
    print(f"  Embedding Weight:    {ew:.2f}")
    print(f"  Fuzzy Weight:        {fw:.2f}")
    print(f"  HIGH Threshold:      {ht:.2f}")
    print(f"  MEDIUM Threshold:    {mt:.2f}")
    print(f"  LOW Threshold:       {lt:.2f}")
    print(f"  Benchmark Precision: {prec:.4f}")
    print(f"  Benchmark Recall:    {rec:.4f}")
    print(f"  Benchmark F1 Score:  {f1:.4f}")
    print(f"  Benchmark F0.5 Score:{f05:.4f}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_calibration())
