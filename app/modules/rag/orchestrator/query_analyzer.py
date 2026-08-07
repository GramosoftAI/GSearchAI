import re
import json
import logging
from enum import Enum
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field

from app.core.llm.deepinfra_llm import DeepInfraLLMClient

logger = logging.getLogger(__name__)

class QueryIntent(Enum):
    FACT = "FACT"
    CALCULATION = "CALCULATION"
    COMPARISON = "COMPARISON"
    TEMPORAL = "TEMPORAL"
    STRUCTURAL = "STRUCTURAL"
    TABLE = "TABLE"
    GRAPH = "GRAPH"
    SUMMARY = "SUMMARY"
    WHY = "WHY"
    UNKNOWN = "UNKNOWN"

class QueryMetadata(BaseModel):
    quarter: Optional[str] = Field(None, description="E.g., Q1, Q2, Q3, Q4")
    year: Optional[str] = Field(None, description="E.g., 2023, 2024, FY23")
    company: Optional[str] = Field(None, description="Company name mentioned in query")
    document_type: Optional[str] = Field(None, description="E.g., 10-Q, 10-K, Earnings Call")
    primary_topic: Optional[str] = Field(None, description="Primary domain topic (e.g., Accounting, Revenue, Tax)")
    keywords: List[str] = Field(default_factory=list, description="Extracted keywords for search")
    corrected_query: Optional[str] = Field(None, description="The query with spelling or typo corrections applied")
    tabular_subquery: Optional[str] = Field(None, description="Extracted sub-query meant for structured tabular/spreadsheet data with pronouns resolved.")
    vector_subquery: Optional[str] = Field(None, description="Extracted sub-query meant for unstructured document/text data with pronouns resolved.")


class AnalysisResult(BaseModel):
    intent: QueryIntent
    metadata: QueryMetadata
    is_tabular: bool = Field(False, description="Set to true if query asks for data likely stored in structured tabular format/spreadsheet. Set to false for text/PDF lookup or conversational greetings.")
    confidence: float
    reasoning: str

class QueryAnalyzer:
    """
    Analyzes queries to determine strict enterprise intents and extracts deterministic metadata.
    Replaces simplistic query routing with deep query understanding.
    """
    
    def __init__(self):
        self.llm_client = DeepInfraLLMClient()
        
    async def analyze_query(self, query: str) -> AnalysisResult:
        """
        Uses LLM to extract intent and metadata in a single pass.
        """
        q_strip = query.strip()
        # Fast-Path 1: Simple greetings & casual chat (0 ms overhead, no LLM call needed!)
        if re.match(r'^(hello|hi|hey|good\s+morning|good\s+afternoon|good\s+evening|howdy|greetings|thanks|thank\s+you|how\s+are\s+you)[!.,?]*$', q_strip, re.IGNORECASE):
            return AnalysisResult(
                intent=QueryIntent.FACT,
                metadata=QueryMetadata(keywords=[q_strip], corrected_query=q_strip),
                is_tabular=False,
                confidence=1.0,
                reasoning="Fast-path greeting regex match"
            )

        prompt = f"""
You are an Expert Knowledge Retrieval Query Analyzer.
Your task is to classify the user's query into one of the exact intents below and extract structured metadata.

CRITICAL TASK: SPELL CHECK & QUERY EXPANSION
You must output a `corrected_query` field. 
- Fix any obvious typos in named entities or concepts (e.g. "Jon Sno" -> "Jon Snow", "justce" -> "justice").
- If the query is already perfect, `corrected_query` should just be the original query.

CRITICAL TASK: TABULAR VS VECTOR CLASSIFICATION
You must output an `is_tabular` boolean field in the JSON root.
- Set `is_tabular` to true if the query is seeking structured data, lists of entities, counts, aggregates, sums, averages, or specific database records (e.g. "how many rows", "what is David's email", "list of companies in Chennai", "what is the total salary", "how many columns").
- Set `is_tabular` to false if the query is purely conversational, seeking unstructured text, biography, background info, or asking about a topic not stored in spreadsheet columns (e.g. "who is vijay", "tell me about Smackcoders", "what did we discuss", "explain quantum computing").

CRITICAL TASK: COMPOSITE QUERY DECOMPOSITION & CO-REFERENCE RESOLUTION
If the query is composite (asking multiple distinct questions where some apply to spreadsheets/tables and others to documents/resumes/text), you must decompose it:
- `tabular_subquery`: Extract the portion meant for structured tabular/spreadsheet data (like salary, age, count, sums, employee rosters). RESOLVE pronouns (like "he", "she", "his", "her") to the actual subject name (e.g., "Arun's salary" instead of "his salary").
- `vector_subquery`: Extract the portion meant for unstructured text/document data (like job descriptions, work history, resume summaries, textual facts). RESOLVE pronouns to the actual subject name.
- If the query is simple and not composite, set both `tabular_subquery` and `vector_subquery` to null (or omit them).

INTENTS:
- FACT: Direct lookup of a single fact or entity.
- CALCULATION: Requires math.
- COMPARISON: Comparing two or more things.
- TEMPORAL: Requires time-aware filtering.
- STRUCTURAL: Asking about document structure.
- TABLE: Explicitly asking about a table or cell.
- SUMMARY: Needs an overview or tl;dr.
- WHY: Needs reasoning or explanation.
- UNKNOWN: Fallback if nothing matches.

Return ONLY valid JSON:
{{
  "intent": "FACT",
  "is_tabular": false,
  "metadata": {{
    "quarter": null,
    "year": null,
    "company": null,
    "document_type": null,
    "primary_topic": "Character",
    "keywords": ["Jon Snow"],
    "corrected_query": "Who is Jon Snow?",
    "tabular_subquery": null,
    "vector_subquery": null
  }},
  "confidence": 0.95,
  "reasoning": "Query asks for a specific character fact. The typo 'Jon Sno' was corrected."
}}

Example of Composite Query Decomposition:
QUERY: "tell me about arun and what is his salary from the 1st CSV file"
JSON:
{{
  "intent": "COMPARISON",
  "is_tabular": true,
  "metadata": {{
    "quarter": null,
    "year": null,
    "company": null,
    "document_type": "Resume",
    "primary_topic": "Employee Details",
    "keywords": ["Arun", "salary"],
    "corrected_query": "tell me about arun and what is his salary from the 1st CSV file",
    "tabular_subquery": "What is Arun's salary from the 1st CSV file?",
    "vector_subquery": "Tell me about Arun."
  }},
  "confidence": 0.98,
  "reasoning": "Query is composite. Split into tabular salary query with resolved pronoun, and vector document query."
}}

QUERY:
{query}
"""
        try:
            response = await self.llm_client.generate_cloud(
                prompt=prompt,
                system_prompt="You are an expert financial query analyzer. Return only JSON.",
                temperature=0.0,
                max_tokens=1024,
                enable_thinking=False,
                timeout=8.0
            )
            
            # Extract JSON block
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', response, re.DOTALL)
            if json_match:
                cleaned = json_match.group(1)
            else:
                start_idx = response.find('{')
                end_idx = response.rfind('}')
                if start_idx != -1 and end_idx != -1:
                    cleaned = response[start_idx:end_idx+1]
                else:
                    cleaned = response.strip()
                    
            data = json.loads(cleaned)
            
            intent_str = data.get("intent", "UNKNOWN").upper()
            try:
                intent = QueryIntent(intent_str)
            except ValueError:
                intent = QueryIntent.UNKNOWN
                
            metadata_dict = data.get("metadata", {})
            metadata = QueryMetadata(
                quarter=metadata_dict.get("quarter"),
                year=metadata_dict.get("year"),
                company=metadata_dict.get("company"),
                document_type=metadata_dict.get("document_type"),
                primary_topic=metadata_dict.get("primary_topic"),
                keywords=metadata_dict.get("keywords", []),
                corrected_query=metadata_dict.get("corrected_query"),
                tabular_subquery=metadata_dict.get("tabular_subquery"),
                vector_subquery=metadata_dict.get("vector_subquery")
            )

            is_tabular = bool(data.get("is_tabular", False))

            return AnalysisResult(
                intent=intent,
                metadata=metadata,
                is_tabular=is_tabular,
                confidence=float(data.get("confidence", 0.5)),
                reasoning=data.get("reasoning", "LLM determined")
            )
            
        except Exception as e:
            logger.error(f"QueryAnalyzer failed: {e}")
            return AnalysisResult(
                intent=QueryIntent.UNKNOWN,
                metadata=QueryMetadata(keywords=[]),
                is_tabular=False,
                confidence=0.0,
                reasoning=f"Failed to parse: {e}"
            )
