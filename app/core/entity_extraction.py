"""Entity extraction for knowledge graphs (names, concepts, topics)"""

import re
import logging
from typing import List, Set, Dict
from dataclasses import dataclass

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class Entity:
    """Extracted entity with type and confidence"""

    text: str
    entity_type: str
    confidence: float = 1.0
    start_char: int = None
    end_char: int = None

    def __hash__(self):
        return hash(f"{self.text}:{self.entity_type}")

    def __eq__(self, other):
        if not isinstance(other, Entity):
            return False
        return (
            self.text.lower() == other.text.lower()
            and self.entity_type == other.entity_type
        )


class EntityExtractor:
    """
    Extract entities from text (names, concepts, topics).

    PHASE 2 (Current): Regex-based extraction
    PHASE 3+: LLM-based extraction for higher quality

    CRITICAL FOR RAG:
    - Entities enable multi-hop reasoning
    - Enable Chunk-[:MENTIONS]->Entity relationships
    - Enable cross-chunk entity linking
    """

    # Track if we've logged the extraction mode (avoid spam)
    _mode_logged = False

    # Common entity patterns (regex-based for Phase 2)
    PATTERNS = {
        "PERSON": [
            r"\b[A-Z][a-z]+ [A-Z][a-z]+\b",  # First Last name
            r"\b(?:Mr|Ms|Dr|Prof|Sir|Lady)\s+[A-Z][a-z]+\b",  # Titles
        ],
        "ORGANIZATION": [
            r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Inc|LLC|Corp|Ltd|Co|Corporation|GmbH|SA|AG)\b",  # Company names
            r"\b[A-Z]{4,10}\b",  # Acronyms (4-10 letters, reduced noise from 3rd letter)
        ],
        "LOCATION": [
            r"\b(?:City|County|State|Province|Country|Mountain|River|Lake|Ocean|Sea|Bay)\s+[A-Z][a-z]+\b",
            r"\b[A-Z][a-z]+,\s+[A-Z]{2}\b",  # City, State format
        ],
        "CONCEPT": [
            r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\s+(?:Model|Algorithm|Framework|Theory|Architecture|System|Protocol|Engine|Service)\b", # Specific concepts
        ],
        "STRUCTURED_IDENTIFIER": [
            r"\b(?:Control|Requirement|Article|Clause|Section|ISO)\s*[\-\:]?\s*[A-Z]?\d+[\.\-]\d+\b",
            r"\bRFC\s*\d+\s+(?:Section|Clause)\s+[\d\.]+\b",
            r"\b[A-Z]?\d+[\.\-]\d+\b",
        ],
    }

    # Stop words to filter (common words that shouldn't be entities)
    STOP_WORDS = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "is",
        "was",
        "are",
        "been",
        "be",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "must",
        "this",
        "that",
        "these",
        "those",
        "for",
        "to",
        "at",
        "in",
        "on",
        "by",
        "with",
        "from",
    }

    @classmethod
    def _normalize_identifier(cls, text: str) -> str:
        """
        Normalize generic identifiers.
        E.g., "ISO 8-11" -> "8.11", "RFC 9110 Section 8.2" -> "RFC9110:8.2"
        """
        text = text.strip()
        
        # 1. RFC 9110 Section 8.2 -> RFC9110:8.2
        rfc_match = re.search(r'(RFC\s*\d+)\s+(?:Section|Clause)\s+([\d\.]+)', text, re.IGNORECASE)
        if rfc_match:
            return f"{rfc_match.group(1).replace(' ', '')}:{rfc_match.group(2)}"
            
        # 2. ISO / Control / Requirement / Article / Clause prefix removal
        prefix_pattern = r'^(?:Control|Requirement|Article|Clause|Section|ISO)\s*[\-\:]?\s*'
        text = re.sub(prefix_pattern, '', text, flags=re.IGNORECASE)
        
        # 3. Replace dashes with dots if it's purely numbers
        if re.match(r'^[A-Z]?\d+[\-\.]\d+$', text, re.IGNORECASE):
            text = text.replace('-', '.')
            
        return text.lower().strip()

    @classmethod
    async def extract_entities(
        cls,
        text: str,
        entity_types: List[str] = None,
    ) -> List[Entity]:
        """
        Extract entities from text using feature flag for Phase switching.

        PHASE 2 (default): Regex-based patterns (fast, 70% accuracy)
        PHASE 3 (enabled via flag): LLM-based extraction (slow, 95% accuracy)

        Feature flag: settings.use_llm_entity_extraction
        - Phase 2: False (regex) - fast, no API calls
        - Phase 3: True (LLM) - accurate, calls DeepInfra

        Args:
            text: Text to extract entities from
            entity_types: Filter to specific types (e.g., ["PERSON", "CONCEPT"])

        Returns:
            List of extracted Entity objects (deduplicated, normalized)
        """
        if not text:
            return []

        # Log entity extraction mode on first call (for debugging + rollout monitoring)
        if not EntityExtractor._mode_logged:
            mode = "LLM (Phase 3)" if settings.use_llm_entity_extraction else "REGEX (Phase 2)"
            logger.info(f"Using entity extraction mode: {mode}")
            EntityExtractor._mode_logged = True

        # FEATURE FLAG: Switch between regex (Phase 2) and LLM (Phase 3)
        if settings.use_llm_entity_extraction:
            # Phase 3: LLM-based extraction (higher accuracy)
            return await cls._extract_entities_llm(text, entity_types)
        else:
            # Phase 2: Regex-based extraction (fast, good enough)
            return cls._extract_entities_regex(text, entity_types)

    @classmethod
    def _extract_entities_regex(
        cls,
        text: str,
        entity_types: List[str] = None,
    ) -> List[Entity]:
        """
        Extract entities using regex patterns (Phase 2).

        Fast, deterministic, no external dependencies.
        Accuracy: ~70% for typical documents.

        Args:
            text: Text to extract entities from
            entity_types: Filter to specific types

        Returns:
            List of extracted Entity objects (deduplicated, normalized)
        """
        entities = set()
        types_to_extract = entity_types or list(cls.PATTERNS.keys())

        for entity_type in types_to_extract:
            if entity_type not in cls.PATTERNS:
                logger.warning(f"Unknown entity type: {entity_type}")
                continue

            patterns = cls.PATTERNS[entity_type]

            for pattern in patterns:
                try:
                    matches = re.finditer(pattern, text, re.IGNORECASE)
                    for match in matches:
                        entity_text = match.group(0).strip()

                        # Filter out stop words
                        if entity_text.lower() in cls.STOP_WORDS:
                            continue

                        # Filter very short matches (likely noise)
                        if len(entity_text) < 2:
                            continue

                        # NORMALIZATION: Prevent "Guido", "guido", "GUIDO" as separate entities
                        # Store original for display, use normalized for deduplication
                        if entity_type == "STRUCTURED_IDENTIFIER":
                            normalized_text = cls._normalize_identifier(entity_text)
                        else:
                            normalized_text = entity_text.lower().strip()

                        # Create entity with confidence
                        # Longer matches typically higher confidence
                        confidence = min(1.0, len(entity_text) / 50.0)

                        entity = Entity(
                            text=normalized_text,  # Use normalized text (lowercase)
                            entity_type=entity_type,
                            confidence=confidence,
                        )
                        entities.add(entity)

                except re.error as e:
                    logger.error(f"Regex error in pattern {pattern}: {e}")

        # Convert set to sorted list (by text length, descending)
        return sorted(entities, key=lambda e: len(e.text), reverse=True)

    @classmethod
    def extract_key_terms(
        cls,
        text: str,
        top_n: int = 10,
    ) -> List[str]:
        """
        Extract key terms from text (simple TF-based ranking).

        Phase 2: Word frequency analysis
        Phase 3+: TF-IDF or LLM-based key term extraction

        Args:
            text: Text to extract from
            top_n: Return top N terms

        Returns:
            List of key terms, ranked by relevance
        """
        # Split into words
        words = re.findall(r"\b\w+\b", text.lower())

        # Filter stop words and short words
        filtered_words = [w for w in words if w not in cls.STOP_WORDS and len(w) > 2]

        # Count frequencies
        word_freq = {}
        for word in filtered_words:
            word_freq[word] = word_freq.get(word, 0) + 1

        # Sort by frequency
        ranked_terms = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)

        # Return top N as unique terms
        return [term for term, count in ranked_terms[:top_n]]

    @classmethod
    def extract_noun_phrases(cls, text: str) -> List[str]:
        """
        Extract noun phrases using simple pattern matching.

        Phase 2: Regex-based patterns
        Phase 3+: Use NLP library (spaCy, NLTK)

        Args:
            text: Text to extract from

        Returns:
            List of noun phrases
        """
        # Pattern: Adj* Noun+ (optional prep Noun+)
        # Very simplified - real version would use NLP
        pattern = r"\b(?:[A-Z][a-z]+\s+)*[A-Z][a-z]+(?:\s+[a-z]+)*\b"

        matches = re.findall(pattern, text)

        # Deduplicate and filter
        phrases = set()
        for match in matches:
            phrase = match.strip()
            if len(phrase) > 2 and phrase.lower() not in cls.STOP_WORDS:
                phrases.add(phrase)

        return sorted(phrases)

    @classmethod
    def deduplicate_entities(
        cls,
        entities: List[Entity],
        similarity_threshold: float = 0.8,
    ) -> List[Entity]:
        """
        Deduplicate entities with similar names.

        Phase 2: String similarity (Levenshtein)
        Phase 3+: Use embedding similarity

        Args:
            entities: List of entities to deduplicate
            similarity_threshold: Threshold for considering entities as duplicates

        Returns:
            Deduplicated list
        """
        if not entities:
            return []

        # For now, simple string-based deduplication
        # Keep track of kept entities
        kept = []
        seen_texts = set()

        for entity in entities:
            if entity.entity_type == "STRUCTURED_IDENTIFIER":
                normalized = cls._normalize_identifier(entity.text)
            else:
                normalized = entity.text.lower().strip()

            # Check if we've seen this exact text
            if normalized in seen_texts:
                continue

            # For now, just do exact string matching
            # TODO: Phase 3 - add fuzzy matching
            seen_texts.add(normalized)
            kept.append(entity)

        return kept

    @classmethod
    async def _extract_entities_llm(
        cls,
        text: str,
        entity_types: List[str] = None,
    ) -> List[Entity]:
        """
        Extract entities using LLM (Phase 3) via DeepInfra.
        """
        try:
            from .llm.deepinfra_llm import DeepInfraLLMClient as DeepInfraClient
            import json

            client = DeepInfraClient()
            
            prompt = f"""
            Extract the most important entities from the following text.
            Focus on PEOPLE, ORGANIZATIONS, LOCATIONS, and key CONCEPTS.
            
            Return exactly in JSON format:
            {{
                "entities": [
                    {{"text": "Entity Name", "type": "PERSON|ORGANIZATION|LOCATION|CONCEPT"}}
                ]
            }}
            
            TEXT: {text}
            """
            
            response_text = await client.generate(prompt)
            
            # Extract JSON from response (handling potential markdown formatting)
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                entities = []
                for e in data.get("entities", []):
                    # Basic validation
                    if "text" in e and "type" in e:
                        entities.append(Entity(
                            text=e["text"].lower().strip(),
                            entity_type=e["type"].upper(),
                            confidence=1.0
                        ))
                return cls.deduplicate_entities(entities)
            
            logger.warning("No JSON found in LLM entity extraction response. Falling back to regex.")
            return cls._extract_entities_regex(text, entity_types)

        except Exception as e:
            logger.error(f"LLM entity extraction failed: {e}. Falling back to regex.")
            return cls._extract_entities_regex(text, entity_types)
