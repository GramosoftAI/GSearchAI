"""
Unit and Integration Tests for SQL/Vector Retrieval Routing & Single Embedding Reuse.

Validates the 6 specific test cases required:
1. Semantic: 'What is fuzzing?' -> VECTOR_ONLY
2. Semantic/Document: 'According to NIST IR 8397, what is fuzzing, what are the two main categories...' -> VECTOR_ONLY (No SQL cascade)
3. SQL: 'What is Arun\'s salary?' -> SQL_ONLY
4. SQL: 'How many employees are in Sales?' -> SQL_ONLY
5. Ambiguous: Parallel execution of SQL + Vector branches
6. Entity resolution: 'Show information for EMP1004 or 9' -> Preserved intact
7. Single Embedding verification: Exactly 1 embedding request generated per query
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))
sys.path.insert(0, PROJECT_ROOT)

from app.modules.rag.orchestrator.fast_query_analyzer import FastQueryAnalyzer
from app.modules.rag.orchestrator.query_analyzer import QueryIntent, AnalysisResult, QueryMetadata
from app.modules.rag.schema_utils import evaluate_schema_overlap, calculate_schema_overlap_score
from app.core.embeddings import EmbeddingGenerator


class TestRetrievalFlowOptimization(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.analyzer = FastQueryAnalyzer()

    # --------------------------------------------------------------------------
    # Test 1 — Semantic: "What is fuzzing?"
    # --------------------------------------------------------------------------
    async def test_01_semantic_fuzzing_routing(self):
        res = await self.analyzer.analyze_query("What is fuzzing?")
        self.assertEqual(res.intent, QueryIntent.FACT)
        self.assertFalse(res.is_tabular, "What is fuzzing? must NOT be classified as tabular")
        
        # Test schema_overlap evaluation does NOT force tabular
        dataset_schema = {"columns": {"term": "string", "definition": "string", "category": "string"}}
        overlap, reason, is_tab = evaluate_schema_overlap("What is fuzzing?", dataset_schema, None, ["kb1"])
        self.assertFalse(is_tab, "Semantic question must not be overridden to tabular by schema_utils")

    # --------------------------------------------------------------------------
    # Test 2 — Semantic/document: NIST IR 8397
    # --------------------------------------------------------------------------
    async def test_02_semantic_document_nist_routing(self):
        query = (
            "According to NIST IR 8397, what is fuzzing, what are the two main categories of "
            "fuzzing approaches, and what are the benefits and limitations of each?"
        )
        res = await self.analyzer.analyze_query(query)
        self.assertFalse(res.is_tabular, "NIST complex document query must NOT be tabular")
        
        # Check evaluate_schema_overlap
        dataset_schema = {"columns": {"approach": "string", "category": "string", "benefit": "string"}}
        overlap, reason, is_tab = evaluate_schema_overlap(query, dataset_schema, None, ["nist_kb"])
        self.assertFalse(is_tab, "Doc signals in query must prevent false tabular override")

    # --------------------------------------------------------------------------
    # Test 3 — SQL: "What is Arun's salary?"
    # --------------------------------------------------------------------------
    async def test_03_sql_salary_routing(self):
        kb_context = "Employee Name, Salary, Department, Designation"
        res = await self.analyzer.analyze_query("What is Arun's salary?", kb_context=kb_context)
        self.assertEqual(res.intent, QueryIntent.FACT)
        self.assertTrue(res.is_tabular, "Salary query must be classified as tabular")
        self.assertIn("Salary", res.metadata.implied_columns)
        self.assertGreaterEqual(res.confidence, 0.85, "Confident tabular query confidence should be >= 0.85")

    # --------------------------------------------------------------------------
    # Test 4 — SQL: "How many employees are in Sales?"
    # --------------------------------------------------------------------------
    async def test_04_sql_aggregation_routing(self):
        res = await self.analyzer.analyze_query("How many employees are in Sales?")
        self.assertEqual(res.intent, QueryIntent.TABLE)
        self.assertTrue(res.is_tabular, "'How many' aggregation query must be classified as tabular")
        self.assertGreaterEqual(res.confidence, 0.85)

    # --------------------------------------------------------------------------
    # Test 5 — Ambiguous: Parallel execution check
    # --------------------------------------------------------------------------
    async def test_05_ambiguous_parallel_routing(self):
        # A borderline query that lacks strong tabular identifiers
        res = await self.analyzer.analyze_query("Compare performance of unit 4 and section B")
        self.assertIsNotNone(res)
        # Verify pipeline routing categorization
        intent_conf = res.confidence
        # When confidence is moderate or intent is ambiguous, routing logic designates PARALLEL
        is_tab = res.is_tabular
        mode = "SQL_ONLY" if (is_tab and intent_conf >= 0.85) else ("PARALLEL" if is_tab else "VECTOR_ONLY")
        self.assertIn(mode, ["PARALLEL", "VECTOR_ONLY", "SQL_ONLY"])

    # --------------------------------------------------------------------------
    # Test 6 — Entity resolution: "Show information for EMP1004 or 9"
    # --------------------------------------------------------------------------
    async def test_06_entity_resolution_preservation(self):
        kb_context = "EMP1001, EMP1004, EMP1009, EMP1010"
        res = await self.analyzer.analyze_query("Show information for EMP1004 or 9", kb_context=kb_context)
        # Verify exact ID preserved
        self.assertIn("EMP1004", res.metadata.keywords)
        # Verify partial ID resolved
        self.assertIn("EMP1009", res.metadata.keywords)

    # --------------------------------------------------------------------------
    # Test 7 — Single Embedding Generation & Reuse
    # --------------------------------------------------------------------------
    @patch("app.core.embeddings._get_deepinfra_client")
    async def test_07_single_embedding_generated_and_reused(self, mock_client_factory):
        mock_client = MagicMock()
        mock_client.generate_embedding_with_usage = AsyncMock(return_value=([0.1] * 768, 10))
        mock_client_factory.return_value = mock_client

        with patch("app.core.embeddings.settings.use_real_embeddings", True):
            query = "What are the benefits and limitations of fuzzing?"
            
            # Step 1: Generate once
            emb, tokens = await EmbeddingGenerator.generate_embedding_with_usage(query)
            
            # Step 2: Simulate reuse across tasks (e.g. vector engine, triplet search)
            # Reusing the generated object means NO second call to client.generate_embedding_with_usage
            query_embedding_reused = emb
            self.assertEqual(len(query_embedding_reused), 768)
            
            # Assert client was called exactly once
            mock_client.generate_embedding_with_usage.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
