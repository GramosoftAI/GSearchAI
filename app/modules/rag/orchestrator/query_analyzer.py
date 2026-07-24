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

class AnalysisResult(BaseModel):
    intent: QueryIntent
    metadata: QueryMetadata
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
        prompt = f"""
You are an Expert Knowledge Retrieval Query Analyzer.
Your task is to classify the user's query into one of the exact intents below and extract structured metadata.

CRITICAL TASK: SPELL CHECK & QUERY EXPANSION
You must output a `corrected_query` field. 
- Fix any obvious typos in named entities or concepts (e.g. "Jon Sno" -> "Jon Snow", "justce" -> "justice").
- If the query is already perfect, `corrected_query` should just be the original query.

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
  "metadata": {{
    "quarter": null,
    "year": null,
    "company": null,
    "document_type": null,
    "primary_topic": "Character",
    "keywords": ["Jon Snow"],
    "corrected_query": "Who is Jon Snow?"
  }},
  "confidence": 0.95,
  "reasoning": "Query asks for a specific character fact. The typo 'Jon Sno' was corrected."
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
                enable_thinking=False
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
                corrected_query=metadata_dict.get("corrected_query")
            )
            
            return AnalysisResult(
                intent=intent,
                metadata=metadata,
                confidence=float(data.get("confidence", 0.5)),
                reasoning=data.get("reasoning", "LLM determined")
            )
            
        except Exception as e:
            logger.error(f"QueryAnalyzer failed: {e}")
            return AnalysisResult(
                intent=QueryIntent.UNKNOWN,
                metadata=QueryMetadata(keywords=[]),
                confidence=0.0,
                reasoning=f"Failed to parse: {e}"
            )
