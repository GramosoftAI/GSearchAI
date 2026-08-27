import re
import logging
from typing import List, Optional, Any, Dict

logger = logging.getLogger(__name__)

# 1. Regex patterns for explicit human support requests
EXPLICIT_ESCALATION_PATTERN = re.compile(
    r"\b("
    r"human|agent|support|representative|rep|"
    r"talk to (a |an )?(human|person|agent|representative|manager|someone)|"
    r"speak to (a |an )?(human|person|agent|representative|manager|someone)|"
    r"connect (me )?(to|with) (a |an )?(human|person|agent|representative|support)|"
    r"transfer (me )?(to)?|"
    r"call (support|helpdesk|customer care|representative)|"
    r"live agent|real person|customer care|customer support|help desk|helpdesk|"
    r"raise (a )?ticket|create (a )?ticket|open (a )?ticket|"
    r"contact (support|team|human|person|us)|"
    r"escalat(e|ion)"
    r")\b",
    re.IGNORECASE
)

# 2. Common fallback indicators in assistant answers when knowledge is missing
FALLBACK_PHRASES = [
    "i do not have enough information",
    "i don't have enough information",
    "i don't have information",
    "i do not have information",
    "not mentioned in the provided",
    "not found in the documents",
    "not found in the knowledge base",
    "i cannot find any relevant information",
    "i am sorry, but i don't have",
    "i'm sorry, but i don't have",
    "unable to find relevant information",
    "please contact support",
    "feel free to reach out to our team",
    "reach out to our support",
]

# 3. User frustration indicators
FRUSTRATION_PATTERN = re.compile(
    r"\b("
    r"this is wrong|completely wrong|useless|terrible answer|bad bot|"
    r"you don't understand|you didn't answer|not helpful|"
    r"give me a real person|stop hallucinating"
    r")\b",
    re.IGNORECASE
)


def detect_escalation_intent(
    query: str,
    sources: Optional[List[Any]] = None,
    response_text: Optional[str] = None,
) -> bool:
    """
    Evaluates whether the current interaction should trigger a human support escalation.

    Returns:
        bool: True if human support escalation should be shown to the user, False otherwise.
    """
    if not query:
        return False

    clean_query = query.strip()

    # Rule 1: Explicit user request for human support or ticket creation
    if EXPLICIT_ESCALATION_PATTERN.search(clean_query):
        logger.info("Human escalation triggered via explicit user intent match.")
        return True

    # Rule 2: User expresses severe frustration with bot answer
    if FRUSTRATION_PATTERN.search(clean_query):
        logger.info("Human escalation triggered via user frustration match.")
        return True

    # Rule 3: RAG Fallback - No knowledge retrieved or assistant admits lack of knowledge
    if response_text:
        lower_resp = response_text.lower()
        has_fallback_phrase = any(phrase in lower_resp for phrase in FALLBACK_PHRASES)

        # If assistant has no sources AND uses a fallback phrase
        if (sources is None or len(sources) == 0) and has_fallback_phrase:
            logger.info("Human escalation triggered via RAG fallback (no sources + fallback response).")
            return True

        # If sources are present, check if all sources have zero/negligible relevance and response is a fallback
        if sources and len(sources) > 0 and has_fallback_phrase:
            max_score = 0.0
            for s in sources:
                if isinstance(s, dict):
                    score = s.get("score") or s.get("relevance_score") or 0.0
                else:
                    score = getattr(s, "score", 0.0) or getattr(s, "relevance_score", 0.0)
                try:
                    max_score = max(max_score, float(score))
                except (ValueError, TypeError):
                    pass

            if max_score < 0.35:
                logger.info(f"Human escalation triggered via low source relevance ({max_score:.2f}) + fallback.")
                return True

    return False
