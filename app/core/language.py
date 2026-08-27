"""
Document Language Resolution Module.

Provides document-level language detection for PostgreSQL tsvector regconfig.

Rule:
- English confidently detected -> 'english'
- Everything else / Exception / Short text -> 'simple' (Safe, Non-Destructive)
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Try importing langdetect
try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0
    _LANGDETECT_AVAILABLE = True
except ImportError:
    _LANGDETECT_AVAILABLE = False
    logger.info("[LANG_DETECT] langdetect package not found; using zero-dependency English heuristic fallback.")


def _is_english_heuristic(text: str) -> bool:
    """
    Zero-dependency English detector heuristic.
    Validates ASCII character ratio and common English structural words.
    """
    clean_text = text.strip()
    if not clean_text:
        return False

    ascii_chars = sum(1 for c in clean_text if ord(c) < 128)
    ascii_ratio = ascii_chars / len(clean_text)
    if ascii_ratio < 0.85:
        return False

    words = [w.strip(".,!?;:\"'()[]{}").lower() for w in clean_text.split() if w.strip()]
    if not words:
        return False

    english_stopwords = {
        "the", "be", "to", "of", "and", "a", "in", "that", "have", "it", "for",
        "not", "on", "with", "as", "you", "do", "at", "this", "but", "by", "from",
        "is", "or", "an", "will", "all", "would", "there", "their", "what", "so",
        "if", "about", "which", "when", "can", "like", "time", "into", "your",
        "some", "could", "them", "other", "than", "then", "now", "only", "its",
        "over", "also", "after", "use", "how", "our", "work", "first", "well",
        "way", "even", "new", "want", "because", "any", "these", "give", "most"
    }

    matches = sum(1 for w in words if w in english_stopwords)
    ratio = matches / len(words)
    return ratio >= 0.05 or (len(words) >= 5 and matches >= 1)


def detect_document_language(full_text: Optional[str]) -> str:
    """
    Detect document-level language for PostgreSQL tsvector regconfig.
    
    Samples up to the first 4,000 characters for high statistical confidence.
    
    Returns:
    - 'english' if English is affirmatively detected
    - 'simple' for non-English languages, mixed text, code, short samples, or exceptions
    """
    if not full_text or len(full_text.strip()) < 30:
        return "simple"

    sample_text = full_text.strip()[:4000]

    if _LANGDETECT_AVAILABLE:
        try:
            detected_lang = detect(sample_text)
            if detected_lang == "en":
                return "english"
            else:
                return "simple"
        except Exception as exc:
            logger.debug(f"[LANG_DETECT] langdetect exception, falling back to heuristic: {exc}")

    if _is_english_heuristic(sample_text):
        return "english"

    return "simple"
