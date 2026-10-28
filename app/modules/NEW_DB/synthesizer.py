"""Grounded Answer Synthesizer for NEW_DB

Converts raw database query results into clear, detailed, executive natural-language
passages and structured bullet points, highlighting accomplishments and task progress.
Directly implements the design proven in D:\\DB\\main.
"""

import json
import logging
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class AnswerSynthesizer:
    """Synthesizes rich, grounded natural language answers from query execution results."""

    @classmethod
    def _get_client(cls) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=settings.deepinfra_api_key or "anonymous",
            base_url=settings.deepinfra_api_url or "https://api.deepinfra.com/v1/openai",
            timeout=60.0,
        )

    @classmethod
    async def synthesize(
        cls,
        question: str,
        sql: str,
        rows: List[Dict[str, Any]],
        columns: List[str],
        row_count: int,
        truncated: bool = False,
        model: Optional[str] = None,
    ) -> str:
        """
        Convert database rows into clear, detailed natural language passages.
        """
        if row_count == 0:
            return f"No records were found in the database matching your question: '{question}'."

        # Fast-path for single scalar count
        if row_count == 1 and len(columns) == 1 and rows:
            val = next(iter(rows[0].values()))
            col_name = columns[0].lower()
            if "count" in col_name or any(w in question.lower() for w in ("how many", "total", "count")):
                return f"There are **{val}** records in total matching your query."

        # Clean sample records to prevent prompt bloating (cap at 15 rows, truncate long text fields)
        sample_records = []
        for r in rows[:15]:
            if isinstance(r, dict):
                r_clean = {}
                for k, v in r.items():
                    if isinstance(v, str) and len(v) > 250:
                        r_clean[k] = v[:250] + "..."
                    else:
                        r_clean[k] = v
                sample_records.append(r_clean)
            elif isinstance(r, (list, tuple)):
                sample_records.append([
                    (v[:250] + "...") if isinstance(v, str) and len(v) > 250 else v
                    for v in r
                ])
            else:
                sample_records.append(r)

        system_prompt = """You are an intelligent database assistant.
The user asked a database question. SQL was generated and executed against the live database.
Your job is to provide a concise, clear, and comprehensive natural language summary with bullet points.

Guidelines:
1. Do NOT output raw JSON.
2. Directly answer the question with bullet points.
3. Highlight specific details like names, dates, statuses, numbers, and progress indicators.
4. Keep the answer concise, fast to read, and professional.
"""

        user_prompt = f"""Question: {question}

Executed SQL:
{sql}

Database Result ({row_count} total rows{' (truncated to first 200)' if truncated else ''}):
{json.dumps(sample_records, default=str, ensure_ascii=False)}

Please provide a clear and concise answer in natural language:"""

        chosen_model = model or getattr(settings, "model_answer", "deepseek-ai/DeepSeek-V3")
        client = cls._get_client()

        try:
            response = await client.chat.completions.create(
                model=chosen_model,
                temperature=0.2,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            logger.error(f"[NEW_DB] LLM answer generation failed: {exc}")
            return f"Query executed successfully and returned {row_count} records: {json.dumps(sample_records[:3], default=str)}"
