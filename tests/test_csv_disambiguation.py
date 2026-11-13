import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.modules.rag.service import (
    CSVSessionPinStore,
    is_csv_kb,
    is_cross_file_query,
    _get_kb_row_count,
    _build_csv_disambiguation_payload,
    RAGService,
)
from app.modules.rag.schemas import (
    CSVDisambiguationCandidate,
    ClarificationNeededResponse,
)


class MockKB:
    def __init__(self, id_val, name, description="excel_parquet", dataset_schema=None, categorical_values=None, agent_id="agent_1", metadata_json=None):
        self.id = id_val
        self.name = name
        self.description = description
        self.dataset_schema = dataset_schema or {}
        self.categorical_values = categorical_values or {}
        self.agent_id = agent_id
        self.parsed_path = f"/data/{name}.parquet"
        self.s3_path = f"s3://bucket/{name}"
        self.metadata_json = metadata_json or {}
        self.total_chunks = 100


class TestCSVHelpers:
    """Unit tests for CSV helper functions and contracts."""

    def test_is_csv_kb(self):
        csv_kb1 = MockKB(uuid4(), "employees_q1.csv")
        assert is_csv_kb(csv_kb1) is True

        csv_kb2 = MockKB(uuid4(), "employees_q2", metadata_json={"source_type": "csv"})
        assert is_csv_kb(csv_kb2) is True

        csv_kb3 = MockKB(uuid4(), "employees_q3", metadata_json={"original_filename": "data.CSV"})
        assert is_csv_kb(csv_kb3) is True

        excel_kb = MockKB(uuid4(), "financials.xlsx")
        assert is_csv_kb(excel_kb) is False

        doc_kb = MockKB(uuid4(), "handbook.pdf", description="document")
        doc_kb.parsed_path = "/data/handbook.pdf"
        assert is_csv_kb(doc_kb) is False

    def test_is_cross_file_query(self):
        assert is_cross_file_query("compare salaries across both files") is True
        assert is_cross_file_query("what is the difference between file1 and file2") is True
        assert is_cross_file_query("show total sales across all datasets") is True
        assert is_cross_file_query("Alice vs Bob performance") is True
        assert is_cross_file_query("What is the average salary in marketing?") is False
        assert is_cross_file_query("List all employees hired in 2025") is False

    def test_build_csv_disambiguation_payload_format(self):
        kb1 = MockKB(
            "kb-111", "employees_2025.csv",
            dataset_schema={"Employee ID": "string", "Salary": "integer"},
            metadata_json={"row_count": 1200}
        )
        kb2 = MockKB(
            "kb-222", "employees_2026.csv",
            dataset_schema={"Employee ID": "string", "Salary": "integer", "Bonus": "integer"},
            metadata_json={"row_count": 1450}
        )

        candidates = [{"kb": kb1}, {"kb": kb2}]
        payload = _build_csv_disambiguation_payload(candidates, reason="score_gap_ambiguity")

        assert payload["type"] == "clarification_needed"
        assert payload["reason"] == "score_gap_ambiguity"
        assert "Multiple relevant CSV files" in payload["message"]
        assert len(payload["candidates"]) == 2

        c1 = payload["candidates"][0]
        assert c1["kb_id"] == "kb-111"
        assert c1["filename"] == "employees_2025.csv"
        assert c1["row_count"] == 1200
        assert "Employee ID" in c1["columns"]
        # Score must be stripped from candidate payload
        assert "score" not in c1
        assert "total_score" not in c1

        # Check pydantic schema validation
        validated = ClarificationNeededResponse(**payload)
        assert len(validated.candidates) == 2
        assert validated.candidates[0].filename == "employees_2025.csv"
        assert "employees_2025.csv" in validated.plain_text_fallback


@pytest.mark.asyncio
class TestCSVSessionPinStore:
    """Tests for multi-turn session pinning and eviction."""

    async def test_set_get_and_decrement_pin(self):
        store = CSVSessionPinStore()
        tenant_id = "tenant_123"
        session_id = "session_abc"
        kb_id = "kb-999"

        # Initially empty
        assert await store.get_pin(tenant_id, session_id) is None

        # Set pin
        await store.set_pin(tenant_id, session_id, kb_id, "test.csv", turns=3)
        pin = await store.get_pin(tenant_id, session_id)
        assert pin is not None
        assert pin["kb_id"] == kb_id
        assert pin["filename"] == "test.csv"
        assert pin["turns_left"] == 3

        # Decrement turn 1
        await store.decrement_or_clear_pin(tenant_id, session_id)
        pin = await store.get_pin(tenant_id, session_id)
        assert pin["turns_left"] == 2

        # Decrement turn 2
        await store.decrement_or_clear_pin(tenant_id, session_id)
        pin = await store.get_pin(tenant_id, session_id)
        assert pin["turns_left"] == 1

        # Decrement turn 3 -> expired
        await store.decrement_or_clear_pin(tenant_id, session_id)
        assert await store.get_pin(tenant_id, session_id) is None

    async def test_clear_pin(self):
        store = CSVSessionPinStore()
        await store.set_pin("t1", "s1", "kb-1", "file.csv")
        assert await store.get_pin("t1", "s1") is not None
        await store.clear_pin("t1", "s1")
        assert await store.get_pin("t1", "s1") is None


@pytest.mark.asyncio
class TestCSVDisambiguationRouting:
    """Core disambiguation tests covering all 8 specified scenarios."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.expunge = MagicMock()
        return db

    @pytest.fixture
    def test_tenant_id(self):
        return str(uuid4())

    @pytest.fixture
    def rag_service(self, mock_db, test_tenant_id):
        service = RAGService(db=mock_db, tenant_id=test_tenant_id)
        service.kb_repo = AsyncMock()
        service.agent_repo = AsyncMock()
        service.llm_client = MagicMock()
        return service

    async def test_case_1_single_clear_winner(self, rag_service):
        """Test 1: Score gap >= 20% -> clear winner, no picker triggered."""
        kb1 = MockKB("kb-1", "employees_engineering.csv", dataset_schema={"Salary": "integer", "Department": "string"})
        kb2 = MockKB("kb-2", "employees_sales.csv", dataset_schema={"Bonus": "integer"})

        rag_service.kb_repo.get_by_id = AsyncMock(side_effect=lambda kid: kb1 if kid == "kb-1" else kb2)
        rag_service.agent_repo.get_by_id = AsyncMock(return_value=MagicMock(name="Agent", system_prompt="", personality="", personality_id=None))

        # Top score 10, runner up 6: gap = (10 - 6) / 10 = 0.40 >= 0.20
        with patch("app.modules.rag.schema_utils.calculate_schema_overlap_score") as mock_score, \
             patch("app.core.parquet_ingester.ParquetIngester.get_active_dataset", return_value="/data/dummy.parquet"), \
             patch("app.modules.rag.pandas_engine.PandasQueryEngine.execute_query", new_callable=AsyncMock, return_value="Engineer salaries: $100k"):
            
            mock_score.side_effect = lambda query, ds, cv, name: (5, 0) if "engineering" in name else (3, 0)
            
            result = await rag_service.generate_answer(
                query="What is the average salary in engineering?",
                agent_id="agent_1",
                kb_id=["kb-1", "kb-2"]
            )

            assert isinstance(result, dict)
            assert result.get("type") != "clarification_needed"
            assert "Engineer salaries" in str(result.get("answer"))

    async def test_case_2_score_gap_tie_triggers_picker(self, rag_service):
        """Test 2: Two CSVs within 20% relative dominance margin -> picker triggered."""
        kb1 = MockKB("kb-1", "employees_q1.csv", dataset_schema={"Salary": "integer", "Name": "string"})
        kb2 = MockKB("kb-2", "employees_q2.csv", dataset_schema={"Salary": "integer", "Name": "string"})

        rag_service.kb_repo.get_by_id = AsyncMock(side_effect=lambda kid: kb1 if kid == "kb-1" else kb2)

        # Top score 10, runner up 9: gap = (10 - 9) / 10 = 0.10 < 0.20 -> AMBIGUOUS
        with patch("app.modules.rag.schema_utils.calculate_schema_overlap_score") as mock_score, \
             patch("app.core.parquet_ingester.ParquetIngester.get_active_dataset", return_value="/data/dummy.parquet"):
            
            mock_score.side_effect = lambda query, ds, cv, name: (4, 2) if "q1" in name else (4, 1)

            result = await rag_service.generate_answer(
                query="Who has the highest salary?",
                agent_id="agent_1",
                kb_id=["kb-1", "kb-2"]
            )

            assert isinstance(result, dict)
            assert result.get("type") == "clarification_needed"
            assert result.get("reason") == "score_gap_ambiguity"
            assert len(result.get("candidates")) == 2
            cand_names = [c["filename"] for c in result["candidates"]]
            assert "employees_q1.csv" in cand_names
            assert "employees_q2.csv" in cand_names

    async def test_case_3_multi_entity_probe_hit(self, rag_service):
        """Test 3: Entity found in 2+ CSVs via DuckDB probe -> picker triggered."""
        kb1 = MockKB("kb-1", "employees_north.csv", dataset_schema={"Name": "string"})
        kb2 = MockKB("kb-2", "employees_south.csv", dataset_schema={"Name": "string"})

        rag_service.kb_repo.get_by_id = AsyncMock(side_effect=lambda kid: kb1 if kid == "kb-1" else kb2)
        rag_service.agent_repo.get_by_id = AsyncMock(return_value=MagicMock(name="Agent", system_prompt="", personality="", personality_id=None))

        # Query has entity "Alice Smith". Both datasets hit probe.
        with patch("app.modules.rag.schema_utils.calculate_schema_overlap_score", return_value=(0, 1)), \
             patch("app.core.parquet_ingester.ParquetIngester.get_active_dataset", return_value="/data/dummy.parquet"), \
             patch("duckdb.connect") as mock_duckdb, \
             patch("app.modules.rag.schema_utils.get_schema_columns", return_value=["Name"]):

            mock_con = MagicMock()
            # Probe returns 1 hit for both
            mock_con.execute.return_value.fetchall.return_value = [(1,)]
            mock_duckdb.return_value.__enter__.return_value = mock_con

            result_chunks = []
            async for chunk in rag_service.stream_rag_answer(
                query='Details for "Alice Smith"',
                agent_id="agent_1",
                kb_id=["kb-1", "kb-2"]
            ):
                result_chunks.append(chunk)

            assert len(result_chunks) == 1
            payload = json.loads(result_chunks[0])
            assert payload.get("type") == "clarification_needed"
            assert payload.get("reason") == "multi_entity_probe_hit"
            assert len(payload.get("candidates")) == 2

    async def test_case_4_cross_file_comparison_query_bypasses_picker(self, rag_service):
        """Test 4: Cross-file comparison query ('compare', 'across') -> picker NOT triggered."""
        kb1 = MockKB("kb-1", "employees_q1.csv", dataset_schema={"Salary": "integer"})
        kb2 = MockKB("kb-2", "employees_q2.csv", dataset_schema={"Salary": "integer"})

        rag_service.kb_repo.get_by_id = AsyncMock(side_effect=lambda kid: kb1 if kid == "kb-1" else kb2)

        # Equal scores, but query is cross-file comparison
        with patch("app.modules.rag.schema_utils.calculate_schema_overlap_score", return_value=(2, 1)), \
             patch("app.core.parquet_ingester.ParquetIngester.get_active_dataset", return_value="/data/dummy.parquet"), \
             patch("app.modules.rag.pandas_engine.PandasQueryEngine.execute_query", new_callable=AsyncMock, return_value="Comparison result"):

            result = await rag_service.generate_answer(
                query="Compare salaries across both CSV files",
                agent_id="agent_1",
                kb_id=["kb-1", "kb-2"]
            )

            assert isinstance(result, dict)
            assert result.get("type") != "clarification_needed"
            assert result.get("answer") == "Comparison result"

    async def test_case_5_idor_security_check(self, rag_service):
        """Test 5: Unauthorized target_kb_id is rejected immediately."""
        authorized_kb = MockKB("kb-authorized", "my_data.csv", agent_id="agent_1")
        rag_service.kb_repo.get_by_id = AsyncMock(return_value=authorized_kb)

        # User passes target_kb_id="attacker-kb" not owned by agent
        result = await rag_service.generate_answer(
            query="Get confidential data",
            agent_id="agent_1",
            kb_id=["kb-authorized"],
            target_kb_id="attacker-kb"
        )

        assert "error" in result
        assert "Unauthorized" in result["error"]

    async def test_case_6_resolution_path_and_zero_row_handling(self, rag_service):
        """Test 6: User selection skips scoring and handles zero rows gracefully."""
        kb1 = MockKB("kb-1", "employees_q1.csv", dataset_schema={"Salary": "integer"})
        kb2 = MockKB("kb-2", "employees_q2.csv", dataset_schema={"Salary": "integer"})

        rag_service.kb_repo.get_by_id = AsyncMock(side_effect=lambda kid: kb1 if kid == "kb-1" else kb2)

        # Case 6A: Direct execution with valid records
        with patch("app.core.parquet_ingester.ParquetIngester.get_active_dataset", return_value="/data/dummy.parquet"), \
             patch("app.modules.rag.pandas_engine.PandasQueryEngine.execute_query", new_callable=AsyncMock, return_value="Alice: $90,000"):

            result = await rag_service.generate_answer(
                query="Salary for Alice",
                agent_id="agent_1",
                kb_id=["kb-1", "kb-2"],
                target_kb_id="kb-2"
            )

            assert result.get("type") != "clarification_needed"
            assert "Alice: $90,000" in result.get("answer")

        # Case 6B: Zero matching records on user-selected file does NOT re-show picker
        with patch("app.core.parquet_ingester.ParquetIngester.get_active_dataset", return_value="/data/dummy.parquet"), \
             patch("app.modules.rag.pandas_engine.PandasQueryEngine.execute_query", new_callable=AsyncMock, return_value="No records matched the criteria."):

            result = await rag_service.generate_answer(
                query="Salary for NonExistentPerson",
                agent_id="agent_1",
                kb_id=["kb-1", "kb-2"],
                target_kb_id="kb-2"
            )

            assert result.get("type") != "clarification_needed"
            assert "No matching records found in employees_q2.csv" in result.get("answer")

    async def test_case_7_regression_entity_probe_isolates_winner(self, rag_service):
        """Test 7: 3 CSVs where entity exists in only 1 -> probe isolates winner, no picker."""
        kb1 = MockKB("kb-1", "employees_dept_a.csv", dataset_schema={"Name": "string"})
        kb2 = MockKB("kb-2", "employees_dept_b.csv", dataset_schema={"Name": "string"})
        kb3 = MockKB("kb-3", "employees_dept_c.csv", dataset_schema={"Name": "string"})

        kbs = {"kb-1": kb1, "kb-2": kb2, "kb-3": kb3}
        rag_service.kb_repo.get_by_id = AsyncMock(side_effect=lambda kid: kbs.get(kid))
        rag_service.agent_repo.get_by_id = AsyncMock(return_value=MagicMock(name="Agent", system_prompt="", personality="", personality_id=None))

        with patch("app.modules.rag.schema_utils.calculate_schema_overlap_score", return_value=(0, 1)), \
             patch("app.core.parquet_ingester.ParquetIngester.get_active_dataset", side_effect=lambda p: p), \
             patch("duckdb.connect") as mock_duckdb, \
             patch("app.modules.rag.schema_utils.get_schema_columns", return_value=["Name"]), \
             patch("app.modules.ontology.service.OntologyService.get_ontology", new_callable=AsyncMock, return_value={"classes": [], "relations": []}), \
             patch("app.modules.rag.orchestrator.query_analyzer.QueryAnalyzer.analyze_query", new_callable=AsyncMock, return_value=MagicMock(intent="TABULAR", is_tabular=True, metadata=MagicMock(tabular_subquery=None, vector_subquery=None))), \
             patch("app.core.embeddings.EmbeddingGenerator.generate_embedding_with_usage", new_callable=AsyncMock, return_value=([0.1]*1536, {"total_tokens": 10})), \
             patch.object(rag_service, "_log_query_analytics_safely", new_callable=AsyncMock), \
             patch.object(rag_service.pipeline, "query", new_callable=AsyncMock) as mock_pipe:

            chunk_mock = MagicMock()
            chunk_mock.chunk_id = "chunk-1"
            chunk_mock.hybrid_score = 0.9
            chunk_mock.text = "Found Charlie Davis"
            chunk_mock.source = "employees_dept_b.csv"
            chunk_mock.s3_path = ""
            chunk_mock.kb_id = "kb-2"
            chunk_mock.content_type = "text/plain"
            chunk_mock.position = 0
            chunk_mock.reason = "ENTITY"
            mock_pipe.return_value = MagicMock(
                chunks=[chunk_mock],
                triplets=[],
                authoritative_entities=[],
                search_type="EXTRACTIVE",
                triplet_context="Found Charlie Davis"
            )

            def mock_execute(sql, params):
                mock_cursor = MagicMock()
                # Only path for kb-2 returns hit
                if "dept_b" in params[0]:
                    mock_cursor.fetchall.return_value = [(1,)]
                else:
                    mock_cursor.fetchall.return_value = []
                return mock_cursor

            mock_con = MagicMock()
            mock_con.execute.side_effect = mock_execute
            mock_duckdb.return_value.__enter__.return_value = mock_con

            chunks = []
            async for chunk in rag_service.stream_rag_answer(
                query='Details for "Charlie Davis"',
                agent_id="agent_1",
                kb_id=["kb-1", "kb-2", "kb-3"]
            ):
                chunks.append(chunk)

            # Clarification should NOT be triggered because probe cleanly isolated kb-2
            has_clarification = any("clarification_needed" in str(c) for c in chunks)
            assert has_clarification is False

    async def test_case_8_session_memory_and_topic_switch(self, rag_service):
        """Test 8: Follow-up query on same topic reuses pin; topic change evicts pin."""
        from app.modules.rag.service import _csv_session_store

        session_id = "session-followup-test"
        tenant_id = rag_service.tenant_id

        kb1 = MockKB("kb-1", "sales_2025.csv", dataset_schema={"Region": "string", "Revenue": "integer"})
        kb2 = MockKB("kb-2", "sales_2026.csv", dataset_schema={"Region": "string", "Revenue": "integer"})

        kbs = {"kb-1": kb1, "kb-2": kb2}
        rag_service.kb_repo.get_by_id = AsyncMock(side_effect=lambda kid: kbs.get(kid))

        # Turn 1: User explicitly selects kb-2 -> sets pin
        with patch("app.core.parquet_ingester.ParquetIngester.get_active_dataset", return_value="/data/dummy.parquet"), \
             patch("app.modules.rag.pandas_engine.PandasQueryEngine.execute_query", new_callable=AsyncMock, return_value="2026 Revenue"):

            await rag_service.generate_answer(
                query="What was the revenue in North region?",
                agent_id="agent_1",
                kb_id=["kb-1", "kb-2"],
                session_id=session_id,
                target_kb_id="kb-2"
            )

        pin = await _csv_session_store.get_pin(tenant_id, session_id)
        assert pin is not None
        assert pin["kb_id"] == "kb-2"

        # Turn 2: Follow-up on same topic ("What about South region?") -> schema overlap score > 0 -> reuses pin!
        with patch("app.core.parquet_ingester.ParquetIngester.get_active_dataset", return_value="/data/dummy.parquet"), \
             patch("app.modules.rag.schema_utils.calculate_schema_overlap_score", return_value=(2, 1)), \
             patch("app.modules.rag.pandas_engine.PandasQueryEngine.execute_query", new_callable=AsyncMock, return_value="South Revenue: $500k"):

            res2 = await rag_service.generate_answer(
                query="What about South region?",
                agent_id="agent_1",
                kb_id=["kb-1", "kb-2"],
                session_id=session_id
            )

            # Reused pin without prompting
            assert res2.get("type") != "clarification_needed"
            assert "South Revenue" in res2.get("answer")

        # Turn 3: Topic switched ("How do I apply for parental leave?") -> schema overlap score == 0 -> evicts pin!
        with patch("app.core.parquet_ingester.ParquetIngester.get_active_dataset", return_value="/data/dummy.parquet"), \
             patch("app.modules.rag.schema_utils.calculate_schema_overlap_score", return_value=(0, 0)):

            res3 = await rag_service.generate_answer(
                query="How do I apply for parental leave?",
                agent_id="agent_1",
                kb_id=["kb-1", "kb-2"],
                session_id=session_id
            )

            # Pin should now be cleared
            pin_after = await _csv_session_store.get_pin(tenant_id, session_id)
            assert pin_after is None
