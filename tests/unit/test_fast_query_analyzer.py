"""
Comprehensive Unit Tests for FastQueryAnalyzer & QueryAnalyzer Compatibility Wrapper.
Tests all 22 target cases:
1. Normal factual query
2. Typo
3. Multiple typos
4. Partial employee ID
5. Exact employee ID
6. Salary query
7. Calculation query
8. Comparison query
9. Summary query
10. Why query
11. Vector query
12. Tabular query
13. Composite query
14. Pronoun resolution
15. Ambiguous query
16. Empty query
17. Greeting
18. Unknown query
19. Identifier preservation
20. LLM fallback
21. LLM timeout
22. Invalid LLM JSON
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

# Ensure root is in path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))
sys.path.insert(0, PROJECT_ROOT)

from app.modules.rag.orchestrator.fast_query_analyzer import FastQueryAnalyzer
from app.modules.rag.orchestrator.query_analyzer import QueryAnalyzer, QueryIntent, AnalysisResult


class TestFastQueryAnalyzer(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.analyzer = FastQueryAnalyzer()
        self.wrapper = QueryAnalyzer()

    # 1. Normal factual query
    async def test_01_normal_factual_query(self):
        res = await self.analyzer.analyze_query("What is the capital of France?")
        self.assertEqual(res.intent, QueryIntent.FACT)
        self.assertFalse(res.is_tabular)
        self.assertIn("capital", res.metadata.keywords)
        self.assertEqual(res.metadata.structured_queries, [])

    # 2. Single Typo
    async def test_02_single_typo(self):
        res = await self.analyzer.analyze_query("what is emp1009 salry")
        self.assertEqual(res.intent, QueryIntent.FACT)
        self.assertTrue(res.is_tabular)
        self.assertEqual(res.metadata.corrected_query, "what is EMP1009 salary")
        self.assertIn("salary", res.metadata.keywords)

    # 3. Multiple typos
    async def test_03_multiple_typos(self):
        res = await self.analyzer.analyze_query("empolyee salery staus")
        self.assertIn("employee", res.metadata.corrected_query)
        self.assertIn("salary", res.metadata.corrected_query)
        self.assertIn("status", res.metadata.corrected_query)

    # 4. Partial employee ID
    async def test_04_partial_employee_id(self):
        kb_context = "Schema: EMP1001, EMP1004, EMP1009, Employee Name, Salary"
        res = await self.analyzer.analyze_query("salary of employee 9", kb_context=kb_context)
        self.assertEqual(res.intent, QueryIntent.FACT)
        self.assertTrue(res.is_tabular)
        self.assertIn("EMP1009", res.metadata.keywords)

    # 5. Exact employee ID
    async def test_05_exact_employee_id(self):
        res = await self.analyzer.analyze_query("EMP 1009 salary")
        self.assertEqual(res.intent, QueryIntent.FACT)
        self.assertTrue(res.is_tabular)
        self.assertIn("EMP1009", res.metadata.keywords)
        self.assertIn("salary", res.metadata.keywords)

    # 6. Salary query
    async def test_06_salary_query(self):
        kb_context = "Columns: Employee ID, Employee Name, Salary, Department"
        res = await self.analyzer.analyze_query("how much does Arun earn?", kb_context=kb_context)
        self.assertEqual(res.intent, QueryIntent.FACT)
        self.assertTrue(res.is_tabular)
        self.assertIn("Salary", res.metadata.implied_columns)

    # 7. Calculation query
    async def test_07_calculation_query(self):
        res = await self.analyzer.analyze_query("What is the average salary of employees?")
        self.assertEqual(res.intent, QueryIntent.CALCULATION)
        self.assertTrue(res.is_tabular)

    # 8. Comparison query
    async def test_08_comparison_query(self):
        res = await self.analyzer.analyze_query("Compare Arun and Ravi salary")
        self.assertEqual(res.intent, QueryIntent.COMPARISON)
        self.assertTrue(res.is_tabular)

    # 9. Summary query
    async def test_09_summary_query(self):
        res = await self.analyzer.analyze_query("Summarize this policy")
        self.assertEqual(res.intent, QueryIntent.SUMMARY)
        self.assertFalse(res.is_tabular)

    # 10. Why query
    async def test_10_why_query(self):
        res = await self.analyzer.analyze_query("Why was this claim rejected?")
        self.assertEqual(res.intent, QueryIntent.WHY)
        self.assertFalse(res.is_tabular)

    # 11. Vector query
    async def test_11_vector_query(self):
        res = await self.analyzer.analyze_query("What does this policy cover in the document?")
        self.assertEqual(res.intent, QueryIntent.FACT)
        self.assertFalse(res.is_tabular)

    # 12. Tabular query
    async def test_12_tabular_query(self):
        res = await self.analyzer.analyze_query("How many employees are in the sales department?")
        self.assertEqual(res.intent, QueryIntent.TABLE)
        self.assertTrue(res.is_tabular)

    # 13. Composite query
    async def test_13_composite_query(self):
        res = await self.analyzer.analyze_query("Tell me about Arun and what is his salary from the first CSV.")
        self.assertIsNotNone(res.metadata.tabular_subquery)
        self.assertIsNotNone(res.metadata.vector_subquery)
        self.assertIn("salary", res.metadata.tabular_subquery.lower())
        self.assertIn("Arun", res.metadata.vector_subquery)

    # 14. Pronoun resolution in composite
    async def test_14_pronoun_resolution(self):
        res = await self.analyzer.analyze_query("Tell me about Arun and how much does he earn?")
        self.assertIn("Arun", res.metadata.tabular_subquery)

    # 15. Ambiguous query triggers compact LLM fallback
    @patch.object(FastQueryAnalyzer, "call_compact_llm_fallback")
    async def test_15_ambiguous_query_fallback(self, mock_llm):
        mock_llm.return_value = {
            "intent": "COMPARISON",
            "is_tabular": True,
            "confidence": 0.90
        }
        # A query with low local confidence (< 0.65)
        res = await self.analyzer.analyze_query("Is Arun better off than Ravi?")
        mock_llm.assert_awaited_once()
        self.assertEqual(res.intent, QueryIntent.COMPARISON)

    # 16. Empty query
    async def test_16_empty_query(self):
        res = await self.analyzer.analyze_query("   ")
        self.assertEqual(res.intent, QueryIntent.UNKNOWN)
        self.assertEqual(res.confidence, 0.0)

    # 17. Greeting query (0 LLM calls, < 1ms)
    async def test_17_greeting_query(self):
        res = await self.analyzer.analyze_query("Hello there!")
        self.assertEqual(res.intent, QueryIntent.FACT)
        self.assertEqual(res.confidence, 1.0)
        self.assertFalse(res.is_tabular)

    # 18. Unknown query with zero signals
    async def test_18_unknown_or_generic_query(self):
        res = await self.analyzer.analyze_query("xyzabc qwerty foo")
        self.assertIn(res.intent, [QueryIntent.FACT, QueryIntent.UNKNOWN])

    # 19. Identifier preservation (do not corrupt structured codes)
    async def test_19_identifier_preservation(self):
        query = "Show details for POL12345, EMP1004, INV-2025-009, and RM8000"
        res = await self.analyzer.analyze_query(query)
        for code in ["POL12345", "EMP1004", "INV-2025-009", "RM8000"]:
            self.assertIn(code, res.metadata.keywords)

    # 20. LLM fallback graceful success
    @patch.object(FastQueryAnalyzer, "call_compact_llm_fallback")
    async def test_20_llm_fallback_success(self, mock_llm):
        mock_llm.return_value = {
            "intent": "GRAPH",
            "is_tabular": False,
            "implied_columns": ["Hierarchy"],
            "confidence": 0.88
        }
        # Low confidence query triggers fallback
        res = await self.analyzer.analyze_query("somewhat ambiguous line", kb_context="None")
        self.assertIsNotNone(res)

    # 21. LLM timeout handled safely without crashing
    @patch.object(FastQueryAnalyzer, "call_compact_llm_fallback")
    async def test_21_llm_timeout_handled(self, mock_llm):
        mock_llm.side_effect = asyncio.TimeoutError()
        res = await self.analyzer.analyze_query("ambiguous query line")
        self.assertIsInstance(res, AnalysisResult)
        self.assertFalse(res.heuristic_fallback_used)

    # 22. Invalid LLM JSON handled gracefully
    @patch.object(FastQueryAnalyzer, "call_compact_llm_fallback")
    async def test_22_invalid_llm_json_handled(self, mock_llm):
        mock_llm.return_value = None  # JSON parsing failure in fallback returns None
        res = await self.analyzer.analyze_query("ambiguous statement here")
        self.assertIsInstance(res, AnalysisResult)
        self.assertIsNotNone(res.intent)

    # 23. Backward compatibility via QueryAnalyzer wrapper
    async def test_23_backward_compatibility_wrapper(self):
        res = await self.wrapper.analyze_query("what is emp1009 salary")
        self.assertIsInstance(res, AnalysisResult)
        self.assertEqual(res.intent, QueryIntent.FACT)
        self.assertTrue(res.is_tabular)
        self.assertIn("EMP1009", res.metadata.keywords)


if __name__ == "__main__":
    unittest.main()
