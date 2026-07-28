import logging
from typing import Optional
from app.core.llm.deepinfra_llm import get_llm_client

logger = logging.getLogger(__name__)

import logging
from typing import Optional
from app.core.llm.deepinfra_llm import get_llm_client

logger = logging.getLogger(__name__)

class QueryRewriter:
    """
    Modular Query Rewriter using Qwen2.5-72B-Instruct.
    Optimizes vague, misspelled, or shorthand queries for higher-accuracy RAG retrieval.
    """
    def __init__(self):
        self.system_prompt = (
            """
You are a query rewriting assistant for a Retrieval-Augmented Generation (RAG) system.
Your sole task is to rewrite user queries to maximize retrieval quality in vector databases and knowledge graphs.

STRICT RULES  follow all without exception:
1. Correct all spelling and grammatical errors.
2. Expand abbreviations only when their meaning is unambiguous from context.
3. Rewrite vague, incomplete, or ambiguous queries into precise, keyword-rich, search-optimized queries.
4. If conversation history is provided, resolve any pronouns (he, she, it, they, this, these, above) or contextual references (e.g., 'the first one', 'from above') in the new query to their specific entities from the history.
5. ONLY prefix the rewritten query with '[HISTORY_FILTER] ' if the final answer can be answered using ONLY the text that is ALREADY VISIBLE in the provided CONVERSATION HISTORY (e.g., filtering names, formatting visible fields into a table, counting the listed items).
6. If the query asks for any NEW fields, values, or attributes that are NOT currently written in the history (e.g., "what is their monthly income?", "sum their salary", "give me their emails"), you MUST NOT prefix it with '[HISTORY_FILTER]'. Instead, resolve the pronouns (e.g., replace 'them' with the specific employee numbers) so a database search can retrieve the missing fields.
7. Preserve the user's original intent exactly  do NOT infer, assume, or add meaning beyond what is explicitly stated.
8. Do NOT answer, explain, or comment on the query.
9. Do NOT add examples, suggestions, or elaborations.
10. Keep technical terms, proper nouns, and domain-specific language unchanged.
11. Keep the rewritten query concise, natural, and free of filler words.
12. If the query is already clear, grammatically correct, and search-ready  return it exactly as-is, with zero modifications.
13. Output ONLY the final rewritten query  no preamble, no labels, no punctuation wrappers, no explanation.

BEHAVIOR CONTRACT:
- Input: a raw user query (possibly misspelled, vague, or abbreviated) and optional chat history.
- Output: one rewritten query string, nothing else. Optionally prefixed with '[HISTORY_FILTER] ' ONLY if the answer is fully contained in the history text.
- Any output beyond the rewritten query string is a violation.
"""
        )

    async def rewrite_query(self, query: str, history: Optional[list] = None) -> str:
        """
        Takes a user query, enhances it using Qwen-2.5-72B-Instruct,
        and returns the enhanced query. Falls back to the original query on any failure.
        """
        stripped_query = query.strip()
        # Do not rewrite empty or extremely short queries
        if not stripped_query or len(stripped_query) < 3:
            return query
            
        try:
            llm_client = await get_llm_client()
            logger.debug(f"Rewriting query via Qwen-2.5-72B-Instruct: '{query}'")
            
            dynamic_system_prompt = self.system_prompt
            if history:
                history_str = "\n".join([f"{m.role.capitalize()}: {m.content}" for m in history])
                dynamic_system_prompt += f"\n\n--- CONVERSATION HISTORY ---\n{history_str}\n----------------------------\nUse this history ONLY to resolve contextual references in the query below."

            enhanced_query = await llm_client.generate_cloud(
                prompt=stripped_query,
                system_prompt=dynamic_system_prompt,
                temperature=0.1,  # Low temperature for strict adherence
                max_tokens=256,
            )
            print(f"--------------------Original Query: '{query}' -> Enhanced Query: '{enhanced_query}'-------")
            import re
            cleaned_query = re.sub(r'<think>.*?</think>', '', enhanced_query, flags=re.DOTALL)
            cleaned_query = cleaned_query.strip().strip('"').strip("'")
            if cleaned_query:
                return cleaned_query
            return query
        except Exception as e:
            logger.error(f" Query rewriting failed: {e}. Falling back to original query.")
            return query
