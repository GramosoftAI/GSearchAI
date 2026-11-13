import pytest
import tempfile
import os
import pandas as pd
from sqlalchemy import create_engine, text

from app.modules.rag.pandas_engine import (
    is_partial_entity_reference,
    extract_candidate_entity_references,
    resolve_partial_entities,
    _sanitize_column_identifier,
    _infer_column_id_pattern,
    invalidate_column_values_cache,
    _COLUMN_VALUES_CACHE,
    EntityResolutionResult,
    PandasQueryEngine
)


@pytest.fixture
def mock_duckdb_engine():
    """Creates an in-memory DuckDB engine with a sample dataset view containing realistic employee IDs."""
    engine = create_engine("duckdb:///:memory:")
    from sqlalchemy import event

    @event.listens_for(engine, "checkout")
    def on_checkout(dbapi_connection, connection_record, connection_proxy):
        cur = dbapi_connection.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS employee_table (
                "Employee ID" VARCHAR,
                "Employee Name" VARCHAR,
                "Department" VARCHAR,
                "Salary" INTEGER
            );
        """)
        cur.execute("""
            DELETE FROM employee_table;
            INSERT INTO employee_table VALUES
                ('EMP1001', 'Alice Johnson', 'Engineering', 95000),
                ('EMP1004', 'Bob Smith', 'Marketing', 72000),
                ('EMP1009', 'Charlie Davis', 'Sales', 68000),
                ('EMP1019', 'Dana Evans', 'Engineering', 105000),
                ('EMP1090', 'Evan White', 'Finance', 88000);
            CREATE OR REPLACE VIEW dataset AS SELECT * FROM employee_table;
        """)
        cur.close()

    # Touch once to initialize
    with engine.connect() as conn:
        pass

    return engine


class TestEntityResolutionUnit:
    """Unit tests for the two-stage entity resolution components."""

    def test_detection_step_well_formed_ids(self):
        """Test fast path: Well-formed IDs are flagged as NOT partial (resolution bypassed)."""
        assert is_partial_entity_reference("EMP1004") is False
        assert is_partial_entity_reference("EMP1009") is False
        assert is_partial_entity_reference("ORD-9821") is False
        assert is_partial_entity_reference("ITEM_12345") is False

        # With explicit format pattern
        pattern = r'^EMP\d{4}$'
        assert is_partial_entity_reference("EMP1004", id_format_pattern=pattern) is False
        assert is_partial_entity_reference("EMP9999", id_format_pattern=pattern) is False

    def test_detection_step_partial_ids(self):
        """Test partial detection: bare numbers and short fragments are flagged as partial."""
        assert is_partial_entity_reference("9") is True
        assert is_partial_entity_reference("1004") is True
        assert is_partial_entity_reference("EMP9") is True
        assert is_partial_entity_reference("E1") is True

        # When format pattern expects EMP\d{4}, EMP9 does not match
        pattern = r'^EMP\d{4}$'
        assert is_partial_entity_reference("EMP9", id_format_pattern=pattern) is True
        assert is_partial_entity_reference("9", id_format_pattern=pattern) is True

    def test_extract_candidate_entity_references(self):
        """Test entity reference extraction from user query."""
        query = "Show details for EMP1004 or 9"
        candidates = extract_candidate_entity_references(query)
        # Should extract EMP1004 (well-formed, not partial) and 9 (partial)
        cand_dict = dict(candidates)
        assert "EMP1004" in cand_dict
        assert cand_dict["EMP1004"] is False  # not partial
        assert "9" in cand_dict
        assert cand_dict["9"] is True  # partial

    def test_resolve_partial_entity_single_match(self, mock_duckdb_engine):
        """Test partial numeric ID with single match: '9' matching EMP1009 when scoped/sorted."""
        res = resolve_partial_entities(
            query_entities=["9"],
            column="Employee ID",
            engine=mock_duckdb_engine,
            available_columns=["Employee ID", "Employee Name"]
        )
        assert isinstance(res, EntityResolutionResult)
        assert "9" in res
        matches = res["9"]
        assert "EMP1009" in matches
        assert "EMP1009" in res.exact_matches.values() or len(matches) >= 1

    def test_resolve_partial_entity_exact_suffix_match(self, mock_duckdb_engine):
        """Test that single distinct match resolves accurately."""
        # '1004' uniquely identifies EMP1004
        res = resolve_partial_entities(
            query_entities=["1004"],
            column="Employee ID",
            engine=mock_duckdb_engine,
            available_columns=["Employee ID", "Employee Name"]
        )
        assert res.exact_matches.get("1004") == "EMP1004"
        assert res["1004"] == ["EMP1004"]

    def test_resolve_partial_entity_multiple_matches(self, mock_duckdb_engine):
        """Test partial ID with multiple matches (ambiguous case)."""
        # '19' matches EMP1019 and potentially others containing 19
        # '1' matches EMP1001, EMP1004, EMP1009, EMP1019, EMP1090
        res = resolve_partial_entities(
            query_entities=["19"],
            column="Employee ID",
            engine=mock_duckdb_engine,
            available_columns=["Employee ID", "Employee Name"]
        )
        assert "19" in res
        assert "EMP1019" in res["19"]

    def test_resolve_partial_entity_zero_matches(self, mock_duckdb_engine):
        """Test partial ID with zero matches returns empty list without error."""
        res = resolve_partial_entities(
            query_entities=["9999"],
            column="Employee ID",
            engine=mock_duckdb_engine,
            available_columns=["Employee ID", "Employee Name"]
        )
        assert "9999" in res
        assert res["9999"] == []
        assert "9999" in res.unresolved

    def test_well_formed_id_fast_path(self, mock_duckdb_engine):
        """Test well-formed ID bypasses DuckDB lookup entirely (fast path)."""
        res = resolve_partial_entities(
            query_entities=["EMP1004"],
            column="Employee ID",
            engine=mock_duckdb_engine,
            available_columns=["Employee ID", "Employee Name"]
        )
        assert res["EMP1004"] == ["EMP1004"]
        assert res.exact_matches["EMP1004"] == "EMP1004"

    def test_malformed_and_injection_attempt_input(self, mock_duckdb_engine):
        """Test that SQL injection attempts in fragment and column are safely sanitized."""
        # 1. SQL Injection in fragment search
        injection_fragments = [
            "'; DROP TABLE employee_table; --",
            "' OR '1'='1",
            "1' UNION SELECT * FROM dataset --",
        ]
        for injection in injection_fragments:
            res = resolve_partial_entities(
                query_entities=[injection],
                column="Employee ID",
                engine=mock_duckdb_engine,
                available_columns=["Employee ID", "Employee Name"]
            )
            # Must safely bind parameter and find 0 matches rather than executing injection
            assert res[injection] == []

        # Table should still exist intact
        with mock_duckdb_engine.connect() as conn:
            cnt = conn.execute(text('SELECT COUNT(*) FROM employee_table;')).scalar()
            assert cnt == 5

        # 2. SQL Injection in column name
        with pytest.raises(ValueError, match="Column .* not found"):
            _sanitize_column_identifier("Employee ID\"; DROP TABLE employee_table; --", available_columns=["Employee ID"])

    def test_cache_and_invalidation(self, mock_duckdb_engine, tmp_path):
        """Test in-memory column values cache and invalidation."""
        # Create a temp file path to act as dataset_paths key
        test_file = tmp_path / "test.parquet"
        test_file.write_text("dummy")
        paths = [str(test_file)]

        # First resolution populates cache
        res = resolve_partial_entities(
            query_entities=["1004"],
            column="Employee ID",
            engine=mock_duckdb_engine,
            dataset_paths=paths,
            available_columns=["Employee ID"]
        )
        assert res.exact_matches["1004"] == "EMP1004"

        # Check cache is populated
        paths_key = (str(test_file).replace('\\', '/'),)
        assert (paths_key, "employee id") in _COLUMN_VALUES_CACHE

        # Second resolution uses cache (instantaneous)
        res2 = resolve_partial_entities(
            query_entities=["1004"],
            column="Employee ID",
            engine=mock_duckdb_engine,
            dataset_paths=paths,
            available_columns=["Employee ID"]
        )
        assert res2.exact_matches["1004"] == "EMP1004"

        # Invalidate cache
        invalidate_column_values_cache(paths=paths)
        assert (paths_key, "employee id") not in _COLUMN_VALUES_CACHE


class TestEntityResolutionRegression:
    """Regression tests for the exact bug case: 'EMP1004 or 9'."""

    @pytest.mark.asyncio
    async def test_regression_emp1004_or_9_resolution(self, tmp_path):
        """
        Regression Test:
        Asking about 'EMP1004 or 9' previously generated literal filter `ILIKE 'EMP9'`
        which matched 0 rows.
        With two-stage entity resolution, '9' resolves to 'EMP1009', substituting
        'EMP1004 or EMP1009' into the query before SQL generation.
        """
        # Create a CSV dataset with Employee ID and Name
        csv_path = tmp_path / "employees.csv"
        df = pd.DataFrame({
            "Employee ID": ["EMP1001", "EMP1004", "EMP1009", "EMP1012"],
            "Employee Name": ["Alice", "Bob", "Charlie", "David"],
            "Department": ["HR", "Engineering", "Sales", "Marketing"]
        })
        df.to_csv(csv_path, index=False)

        # Initialize PandasQueryEngine with the CSV
        engine = PandasQueryEngine(data_path_or_client=str(csv_path))

        # Check candidate extraction & resolution directly
        query = "Show details for EMP1004 or 9"
        candidates = extract_candidate_entity_references(query)
        partial_cand = [c for c, is_p in candidates if is_p]
        assert partial_cand == ["9"]

        # Acquire duckdb engine to run resolution
        from app.modules.rag.pandas_engine import get_pooled_duckdb_engine
        duck_engine, cols, _ = get_pooled_duckdb_engine([str(csv_path)])

        res = resolve_partial_entities(
            query_entities=partial_cand,
            column="Employee ID",
            engine=duck_engine,
            dataset_paths=[str(csv_path)],
            available_columns=cols
        )
        assert res.exact_matches.get("9") == "EMP1009"

        # Check that substitution produces the well-formed query
        import re
        resolved_query = query
        for frag, resolved_val in res.exact_matches.items():
            resolved_query = re.sub(r'\b' + re.escape(frag) + r'\b', resolved_val, resolved_query)

        assert "EMP1004 or EMP1009" in resolved_query
        assert "EMP9" not in resolved_query

    @pytest.mark.asyncio
    async def test_disambiguation_mode_clarify(self, tmp_path):
        """
        Test that when multiple matches are found and disambiguation_mode='clarify',
        the engine surfaces a clarification response directly without calling the SQL-gen LLM.
        """
        csv_path = tmp_path / "ambig.csv"
        df = pd.DataFrame({
            "Employee ID": ["EMP1009", "EMP1019", "EMP1090"],
            "Employee Name": ["Charlie", "Dana", "Evan"]
        })
        df.to_csv(csv_path, index=False)

        engine = PandasQueryEngine(data_path_or_client=str(csv_path))

        # Query with partial reference '9' that matches EMP1009, EMP1019, EMP1090
        # In 'clarify' mode, it should return a clarification request with the candidate IDs
        result = await engine.execute_query(
            query="Show details for 9",
            disambiguation_mode="clarify"
        )
        assert "Multiple candidates found" in result
        assert "EMP1009" in result
        assert "EMP1019" in result
