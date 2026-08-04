# app/core/llm/cypher_generator.py

import hashlib
import logging
from dataclasses import dataclass
from typing import Optional, Dict
from app.core.llm.deepinfra_llm import DeepInfraLLMClient, strip_think_tags
from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class CypherResult:
    cypher: str
    from_template: bool
    cache_hit: bool


# In-memory Cypher query cache (normalize → Cypher)
_cypher_cache: Dict[str, str] = {}


def _normalize_question(question: str) -> str:
    stopwords = {"the", "a", "an", "is", "are", "was", "were", "what", "which",
                 "who", "where", "when", "how", "of", "in", "on", "at", "to",
                 "for", "with", "by", "from", "and", "or", "that", "this"}
    tokens = [w for w in question.lower().split() if w not in stopwords]
    return " ".join(tokens)


def _match_template(question: str) -> Optional[str]:
    """
    Attempt to match the question to a parameterized Cypher template.
    Returns a Cypher string if matched, None if the LLM must handle it.
    Templates cover 60-80% of routine single-hop queries at zero LLM cost.
    """
    q = question.lower().strip()

    if q.startswith("find") and "related to" in q:
        parts = q.replace("find", "").split("related to")
        if len(parts) == 2:
            subject = parts[0].strip().strip('"')
            target = parts[1].strip().strip('"')
            return (
                f'MATCH (a)-[:RELATED_TO]->(b) '
                f'WHERE toLower(b.name) CONTAINS "{target}" '
                f'AND toLower(a.name) CONTAINS "{subject}" '
                f'RETURN a LIMIT 25'
            )

    if "list all" in q and "of type" in q:
        parts = q.replace("list all", "").split("of type")
        if len(parts) == 2:
            name_filter = parts[0].strip()
            entity_type = parts[1].strip().title()
            return (
                f'MATCH (n:{entity_type}) '
                f'WHERE toLower(n.name) CONTAINS "{name_filter}" '
                f'RETURN n LIMIT 50'
            )

    if q.startswith("who is") or q.startswith("what is"):
        entity = q.replace("who is", "").replace("what is", "").strip().strip("?")
        return (
            f'MATCH (n) '
            f'WHERE toLower(n.name) CONTAINS "{entity}" '
            f'RETURN n LIMIT 10'
        )

    return None  # No template matched — route to LLM


class CypherGenerator:
    def __init__(self, neo4j_driver):
        self.llm = DeepInfraLLMClient()
        self.neo4j = neo4j_driver
        settings = get_settings()
        self.model = settings.active_model("nl_to_cypher")
        self.max_tokens = settings.max_tokens_nl_to_cypher

    async def generate(
        self,
        question: str,
        schema: str,
        few_shot_examples: str,
    ) -> CypherResult:
        normalized = _normalize_question(question)
        cache_key = hashlib.md5(normalized.encode()).hexdigest()

        # 1. Cache lookup
        if cache_key in _cypher_cache:
            return CypherResult(
                cypher=_cypher_cache[cache_key],
                from_template=False,
                cache_hit=True,
            )

        # 2. Template matching — zero LLM cost
        template_cypher = _match_template(question)
        if template_cypher:
            _cypher_cache[cache_key] = template_cypher
            return CypherResult(cypher=template_cypher, from_template=True, cache_hit=False)

        # 3. LLM generation — novel/multi-hop queries only
        system_prompt = (
            "You are a Neo4j Cypher expert. Convert the user's natural language "
            "question into a valid Cypher query.\n\n"
            "Rules:\n"
            "- Return ONLY the Cypher query. No explanation. No markdown. No code fences.\n"
            "- Use LIMIT clauses to prevent runaway queries.\n"
            "- Use toLower() for case-insensitive string matching.\n\n"
            f"Graph Schema:\n{schema}\n\n"
            f"Examples:\n{few_shot_examples}"
        )

        raw = await self.llm.generate(
            prompt=question,
            system_prompt=system_prompt,
        )

        cypher = strip_think_tags(raw).strip()

        # Strip accidental markdown fences
        if cypher.startswith("```"):
            cypher = cypher.split("```")[1]
            if cypher.startswith("cypher"):
                cypher = cypher[6:]
            cypher = cypher.strip()

        # 4. Validate before spending answer-generation tokens
        await self._validate_cypher(cypher)

        _cypher_cache[cache_key] = cypher
        return CypherResult(cypher=cypher, from_template=False, cache_hit=False)

    async def _validate_cypher(self, cypher: str) -> None:
        """
        Syntax-check and EXPLAIN the Cypher against Neo4j.
        Raises ValueError with details if the query is invalid.
        Never invoke the answer model with an unvalidated query.
        """
        try:
            async with self.neo4j.session() as session:
                await session.run(f"EXPLAIN {cypher}")
        except Exception as exc:
            raise ValueError(
                f"Generated Cypher failed validation: {exc}\nQuery: {cypher}"
            ) from exc
