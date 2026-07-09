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
    section: Optional[str] = Field(None, description="Specific document section, e.g., Note 1, MD&A, Risk Factors")
    keywords: List[str] = Field(default_factory=list, description="Extracted keywords for search")

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
You are an Enterprise Financial Query Analyzer.
Your task is to classify the user's query into one of the exact intents below and extract structured metadata.

INTENTS:
- FACT: Direct lookup of a single fact or entity (e.g., "Who is the CEO?", "What is the address?").
- CALCULATION: Requires math (e.g., "What proportion of revenue...", "Margin percentage").
- COMPARISON: Comparing two or more things (e.g., "Compare FY23 and FY24 revenue").
- TEMPORAL: Requires time-aware filtering (e.g., "Q3 stock repurchases").
- STRUCTURAL: Asking about document structure (e.g., "What does Note 1 say?").
- TABLE: Explicitly asking about a financial table or cell (e.g., "Gaming Revenue in Q3").
- SUMMARY: Needs an overview or tl;dr.
- WHY: Needs reasoning or explanation for a phenomenon.
- UNKNOWN: Fallback if nothing matches.

Extract metadata if explicitly mentioned or strongly implied. 
If not present, use null.

Return ONLY valid JSON:
{{
  "intent": "CALCULATION",
  "metadata": {{
    "quarter": "Q3",
    "year": "2023",
    "company": "NVIDIA",
    "document_type": "10-Q",
    "section": "Note 1",
    "keywords": ["revenue", "data center"]
  }},
  "confidence": 0.95,
  "reasoning": "User is asking for a proportion which requires calculating Data Center Revenue / Total Revenue"
}}

QUERY:
{query}
"""
        try:
            response = await self.llm_client.generate(
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
                section=metadata_dict.get("section"),
                keywords=metadata_dict.get("keywords", [])
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
