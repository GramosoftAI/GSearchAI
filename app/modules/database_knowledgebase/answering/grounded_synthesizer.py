"""Grounded Answer Synthesizer for Database Knowledge Base

Transforms database query results into clear, detailed natural language passages,
highlighting task notes, progress, and accomplishments.
Directly implements the design from D:\\DB\\main\\app\\pipeline\\answer_synthesizer.py.
"""

import json
import logging
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class GroundedAnswerSynthesizer:
    """Synthesizes rich, detailed natural language answers from query execution results."""

    @classmethod
    def _get_client(cls) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=settings.deepinfra_api_key or "anonymous",
            base_url=settings.deepinfra_api_url or "https://api.deepinfra.com/v1/openai",
            timeout=60.0,
        )

    @classmethod
    async def synthesize_answer(
        cls,
        question: str,
        sql: str,
        result: Dict[str, Any],
        model: Optional[str] = None,
    ) -> str:
        """
        Convert database query results into clear, detailed natural language passages.
        """
        if not result or "rows" not in result:
            return "No database results were obtained."

        rows = result.get("rows", [])
        row_count = result.get("row_count", len(rows))
        truncated = result.get("truncated", False)

        if row_count == 0:
            return f"No records were found in the database matching your question: '{question}'."

        # Fast-path for single scalar count if query is pure count
        cols = result.get("columns", [])
        if row_count == 1 and len(cols) == 1 and isinstance(rows[0], (list, tuple, dict)):
            val = rows[0][0] if isinstance(rows[0], (list, tuple)) else next(iter(rows[0].values()))
            col_name = cols[0].lower() if cols else "count"
            if "count" in col_name or any(w in question.lower() for w in ("how many", "total", "count")):
                return f"There are {val} records in total matching your query."

        # Send up to 35 representative rows to fit within context while keeping high detail
        sample_records = rows[:35]

        system_prompt = """You are an intelligent PostgreSQL database assistant.
The user asked a database question. SQL was generated and executed against the database.
Your job is to provide a clear, comprehensive, and well-written natural language answer (passages/paragraphs).

Guidelines:
1. Do NOT output raw JSON.
2. Directly answer the question with clear passages, paragraphs, and well-organized bullet points.
3. Highlight specific details like names, dates, statuses, numbers, and progress indicators.
4. When a `description` field is present (containing task notes, daily updates, or bullet points), thoroughly explain and summarize the specific work items, accomplishments, and activities listed in the description!
5. If certain numeric fields (like estimated hours or done ratio) are null or empty, note that they are unset, but focus heavily on the actual narrative work details in `description`.
6. Keep the tone professional, direct, and easy to read.
"""

        user_prompt = f"""Question: {question}

Executed SQL:
{sql}

Database Result ({row_count} total rows{' (truncated to first 200)' if truncated else ''}):
{json.dumps(sample_records, default=str, ensure_ascii=False)}

Please provide a clear and detailed answer in natural language:"""

        chosen_model = model or getattr(settings, "chat_model", "deepseek-ai/DeepSeek-V4-Flash-0731")
        client = cls._get_client()

        try:
            response = await client.chat.completions.create(
                model=chosen_model,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            logger.error(f"[GroundedAnswerSynthesizer] LLM answer generation failed: {exc}")
            # Fallback summary
            return f"Query returned {row_count} rows: {json.dumps(sample_records[:5], default=str)}"
