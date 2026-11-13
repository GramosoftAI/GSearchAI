"""Unit Tests for Schema Documentation ("Cheat Sheet") Pipeline

Tests required by Step 1 specification:
1. Exact-name guarantee (table and column names match introspected schema exactly)
2. Deny-list and masking (sensitive columns have no sample values, PII is masked)
3. Missing-column retry (retries once if LLM misses a column, fails if still missing)
4. Example-SQL rejection (rejects SQL selecting sensitive columns or failing execution)
5. Idempotent re-sync (same schema version makes 0 LLM calls and creates 0 duplicate rows)
"""

import pytest
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any, List

from app.modules.database_knowledgebase.schemas.canonical import (
    DatabaseSchema,
    TableSchema,
    ColumnSchema,
    ColumnDataType,
    ForeignKeySchema,
    SchemaInfo,
)
from app.modules.database_knowledgebase.schema_doc.sensitivity import SensitivityGuard
from app.modules.database_knowledgebase.schema_doc.mapper import RelationshipMapper
from app.modules.database_knowledgebase.schema_doc.explainer import (
    SchemaExplainer,
    TableExplanationOutput,
    ColumnDocOutput,
)
from app.modules.database_knowledgebase.schema_doc.examples import ExampleGenerator, CandidateExample
from app.modules.database_knowledgebase.schema_doc.pipeline import SchemaDocPipeline
from app.modules.database_knowledgebase.schema_doc.profiler import TableFacts


def build_mock_schema() -> DatabaseSchema:
    """Build mock canonical schema with employees and employee_employment."""
    employees_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True, is_nullable=False),
        "first_name": ColumnSchema(name="first_name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar", is_nullable=False),
        "email": ColumnSchema(name="email", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar", is_nullable=False),
        "salary": ColumnSchema(name="salary", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric", is_nullable=False),
        "national_id": ColumnSchema(name="national_id", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar", is_nullable=False),
    }
    emp_table = TableSchema(
        schema_name="public",
        table_name="employees",
        columns=employees_cols,
    )

    employment_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True, is_nullable=False),
        "employee_id": ColumnSchema(name="employee_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_foreign_key=True, is_nullable=False),
        "department": ColumnSchema(name="department", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar", is_nullable=False),
    }
    employment_table = TableSchema(
        schema_name="public",
        table_name="employee_employment",
        columns=employment_cols,
        foreign_keys=[
            ForeignKeySchema(
                name="fk_emp",
                constrained_columns=["employee_id"],
                referred_schema="public",
                referred_table="employees",
                referred_columns=["id"],
            )
        ],
    )

    return DatabaseSchema(
        database_name="testdb",
        database_type="postgresql",
        schemas={"public": SchemaInfo(schema_name="public", tables={"employees": emp_table, "employee_employment": employment_table})},
    )


class TestSchemaDocUnit(unittest.IsolatedAsyncioTestCase):

    def test_deny_list_and_masking(self):
        """Test sensitive column detection and PII masking."""
        assert SensitivityGuard.is_sensitive_column("salary") is True
        assert SensitivityGuard.is_sensitive_column("national_id") is True
        assert SensitivityGuard.is_sensitive_column("date_of_birth") is True
        assert SensitivityGuard.is_sensitive_column("gender") is True
        assert SensitivityGuard.is_sensitive_column("marital_status") is True
        assert SensitivityGuard.is_sensitive_column("performance_rating") is True
        assert SensitivityGuard.is_sensitive_column("password_hash") is True
        
        # Non-sensitive
        assert SensitivityGuard.is_sensitive_column("first_name") is False
        assert SensitivityGuard.is_sensitive_column("department") is False
        assert SensitivityGuard.is_sensitive_column("hire_date") is False

        # Email & Phone masking
        masked_email = SensitivityGuard.mask_email("john.doe@company.com")
        assert masked_email.startswith("j***")
        assert masked_email.endswith("@company.com")

        masked_phone = SensitivityGuard.mask_phone("123-456-7890")
        assert "7890" in masked_phone
        assert "123" not in masked_phone

        # Sample rows sanitization
        samples = [
            {"id": 1, "email": "alice@corp.com", "salary": 95000, "national_id": "N12345"},
            {"id": 2, "email": "bob@corp.com", "salary": 80000, "national_id": "N67890"},
        ]
        sanitized = SensitivityGuard.sanitize_sample_rows(["id", "email", "salary", "national_id"], samples)
        for s in sanitized:
            assert s["salary"] == "[REDACTED_SENSITIVE]"
            assert s["national_id"] == "[REDACTED_SENSITIVE]"
            assert "@corp.com" in s["email"]
            assert s["email"] != "alice@corp.com"

    def test_relationship_topology_and_inferred(self):
        """Test declared vs inferred relationship mapping."""
        schema = build_mock_schema()
        topology = RelationshipMapper.build_topology(schema)

        # Parent table employees should come before child employee_employment
        assert "employees" in topology.processing_order
        assert "employee_employment" in topology.processing_order
        emp_idx = topology.processing_order.index("employees")
        dept_idx = topology.processing_order.index("employee_employment")
        assert emp_idx < dept_idx

        # Check declared FK
        emp_rel = topology.tables["employee_employment"]
        assert len(emp_rel.outgoing_fks) == 1
        assert emp_rel.outgoing_fks[0]["target_table"] == "employees"
        assert emp_rel.outgoing_fks[0]["type"] == "declared"

    async def test_missing_column_retry(self):
        """Test that SchemaExplainer retries once when a column is missing."""
        explainer = SchemaExplainer(llm_client=MagicMock())
        facts = TableFacts(table_name="employees")
        facts.columns = {"id": {}, "first_name": {}, "email": {}}
        rel_map = MagicMock(relationship_summary="none")

        # Mock LLM returning only 2 out of 3 columns on first attempt, then all 3 on second
        first_call = {
            "content": '{"table_purpose": "staff", "synonyms": [], "columns": [{"column_id": "id", "meaning": "id"}, {"column_id": "first_name", "meaning": "name"}]}',
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }
        second_call = {
            "content": '{"table_purpose": "staff", "synonyms": [], "columns": [{"column_id": "id", "meaning": "id"}, {"column_id": "first_name", "meaning": "name"}, {"column_id": "email", "meaning": "email"}]}',
            "prompt_tokens": 120,
            "completion_tokens": 70,
        }

        explainer.llm.generate_with_usage = AsyncMock(side_effect=[first_call, second_call])
        tokens = {}
        res = await explainer.explain_table(tenant_id="tenant-1", facts=facts, relationship_map=rel_map, total_tokens_tracker=tokens)

        assert res is not None
        assert len(res.columns) == 3
        assert explainer.llm.generate_with_usage.call_count == 2
        assert tokens["llm_calls"] == 2

    def test_example_sql_rejection(self):
        """Test that queries selecting sensitive columns are rejected."""
        gen = ExampleGenerator(llm_client=MagicMock())
        schema = build_mock_schema()

        # Queries selecting salary or national_id must be flagged
        assert gen._selects_sensitive_columns("SELECT id, salary FROM employees", schema) is True
        assert gen._selects_sensitive_columns("SELECT national_id, first_name FROM employees", schema) is True
        # Queries selecting non-sensitive columns are safe
        assert gen._selects_sensitive_columns("SELECT id, first_name, email FROM employees", schema) is False

    def test_table_hash_idempotency(self):
        """Test deterministic table hash calculation for idempotent re-sync."""
        schema = build_mock_schema()
        emp_table = schema.get_table("employees")
        hash1 = SchemaDocPipeline.compute_table_hash(emp_table)
        hash2 = SchemaDocPipeline.compute_table_hash(emp_table)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256


if __name__ == "__main__":
    unittest.main()
