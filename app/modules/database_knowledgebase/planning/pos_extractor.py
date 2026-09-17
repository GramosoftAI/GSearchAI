"""POS Candidate Extractor for Schema-Grounded Entity Resolution

Extracts candidate unigrams and bigrams from natural language queries with
soft verb/adjective flagging rather than lossy hard filtering.
"""

import re
from typing import List, Set
from pydantic import BaseModel, ConfigDict, Field


class Candidate(BaseModel):
    """Candidate entity or predicate token/phrase extracted from query."""
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., description="Unigram or bigram candidate text")
    likely_verb: bool = Field(default=False, description="Soft signal indicating participle/verb inflection")
    is_ngram: bool = Field(default=False, description="True if candidate is an n-gram (e.g. bigram)")


class POSCandidateExtractor:
    """
    Lightweight, deterministic candidate extractor.
    Hard-drops ONLY closed-class non-content tokens (comparatives, auxiliaries,
    prepositions, determiners). Soft-flags potential verb conjugations and gerunds
    so the schema resolver can evaluate them with safety thresholds.
    """

    # Closed-class non-content words to strictly drop from entity candidate pools
    CLOSED_CLASS_FUNCTION_WORDS: Set[str] = {
        # SQL / Query conversational commands
        "select", "show", "list", "get", "find", "fetch", "display", "tell", "give",
        "which", "what", "who", "whom", "whose", "where", "when", "why", "how",
        # Determiners, quantifiers, and articles
        "the", "a", "an", "all", "any", "some", "every", "each", "both", "either",
        "neither", "this", "that", "these", "those", "my", "your", "his", "her",
        "its", "our", "their", "me", "us", "them", "him",
        # Comparatives, relational operators, and prepositions
        "more", "less", "than", "greater", "lesser", "higher", "lower", "above",
        "below", "under", "over", "equal", "between", "after", "before", "of",
        "in", "on", "at", "to", "for", "with", "without", "by", "from", "and",
        "or", "but", "as", "into", "onto", "upon", "about", "through", "during",
        "along", "across", "amid", "among", "per",
        # Auxiliary & modal verbs
        "is", "are", "was", "were", "be", "been", "being",
        "has", "have", "had", "having",
        "do", "does", "did", "done", "doing",
        "can", "could", "will", "would", "shall", "should", "may", "might", "must",
        "need", "want", "please",
        # Miscellaneous closed-class particles & time markers
        "not", "no", "yes", "so", "too", "very", "just", "now", "then", "there",
        "here", "again", "also", "only", "total", "count", "average", "avg", "sum",
        "max", "min", "top", "bottom", "first", "last", "limit", "current", "previous",
        "active", "inactive", "latest", "historical", "past",
        # Generic structural and metadata qualifiers (never standalone domain entity tables)
        "number", "numbers", "code", "id", "value", "values", "type", "data", "info",
        "record", "records", "item", "items",
    }

    # Known irregular past tense and past participle verbs
    IRREGULAR_VERBS: Set[str] = {
        "spent", "made", "paid", "built", "bought", "sold", "sent", "left", "kept",
        "brought", "caught", "held", "found", "given", "taken", "seen", "done",
        "grown", "drawn", "driven", "known", "written", "become", "run", "met",
        "led", "read", "lost", "won", "felt", "heard", "told", "cost", "set",
        "cut", "put", "hit", "let", "shot", "came", "come", "went", "gone", "took",
    }

    # Common verb stems that frequently take 3rd-person -s in comparative query phrasing
    COMMON_VERB_STEMS: Set[str] = {
        "earn", "make", "spend", "cost", "pay", "receive", "take", "give", "bill",
        "gross", "net", "hire", "work", "join", "belong", "operate", "manage",
        "generate", "produce", "require", "exceed", "total", "come", "arrive",
        "enter", "leave", "clock",
    }

    @classmethod
    def is_closed_class(cls, token: str) -> bool:
        """Check whether token is a closed-class function word that should be hard-dropped."""
        t = token.lower().strip()
        return t in cls.CLOSED_CLASS_FUNCTION_WORDS or t.isdigit()

    @classmethod
    def detect_likely_verb(cls, token: str) -> bool:
        """
        Soft-flag tokens that exhibit participle, gerund, or past-tense verbal morphology.
        Does NOT drop the token; returns a soft signal so the resolver can demand
        HIGH confidence if treating it as a schema entity.
        """
        t = token.lower().strip()
        if len(t) < 3:
            return False

        # Irregular past/participle
        if t in cls.IRREGULAR_VERBS:
            return True

        # Verb stems
        if t in cls.COMMON_VERB_STEMS:
            return True

        # Gerund / Present participle: -ing
        if t.endswith("ing") and len(t) > 4:
            # e.g. earning, spending, grossing, billing, receiving, making, working
            return True

        # Past tense / Past participle: -ed
        if t.endswith("ed") and len(t) > 4:
            # e.g. earned, billed, grossed, received, joined, hired
            return True

        # 3rd person singular present: e.g. earns, spends, grosses, makes, bills
        if t.endswith("s") and len(t) > 3:
            stem = t[:-1]
            if stem in cls.COMMON_VERB_STEMS:
                return True
            if t.endswith("es") and len(t) > 4:
                stem_es = t[:-2]
                if stem_es in cls.COMMON_VERB_STEMS:
                    return True

        return False

    @classmethod
    def extract(cls, query: str) -> List[Candidate]:
        """
        Extract unigram and adjacent bigram candidates with soft verb flagging.
        """
        # Tokenize retaining alphanumeric characters and underscores
        raw_tokens = re.findall(r"\b[a-zA-Z_]{2,}\b", query)
        content_tokens: List[str] = []
        candidates: List[Candidate] = []
        seen_texts: Set[str] = set()

        for tok in raw_tokens:
            tok_lower = tok.lower()
            if cls.is_closed_class(tok_lower):
                continue

            content_tokens.append(tok_lower)

            # Unigram candidate
            if tok_lower not in seen_texts:
                likely_v = cls.detect_likely_verb(tok_lower)
                candidates.append(
                    Candidate(
                        text=tok_lower,
                        likely_verb=likely_v,
                        is_ngram=False,
                    )
                )
                seen_texts.add(tok_lower)

        # Generate adjacent bigram candidates from contiguous content tokens
        for i in range(len(content_tokens) - 1):
            bigram = f"{content_tokens[i]} {content_tokens[i+1]}"
            if bigram not in seen_texts:
                # Bigrams inherit likely_verb only if BOTH tokens are verb-like
                bigram_verb = (
                    cls.detect_likely_verb(content_tokens[i])
                    and cls.detect_likely_verb(content_tokens[i+1])
                )
                candidates.append(
                    Candidate(
                        text=bigram,
                        likely_verb=bigram_verb,
                        is_ngram=True,
                    )
                )
                seen_texts.add(bigram)

        return candidates
