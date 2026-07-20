import logging
import re
from collections import Counter
from datetime import datetime
from uuid import UUID
from sqlalchemy import select, update
from app.core.database import AsyncSessionLocal
from app.core.config import get_settings
from app.modules.knowledge_bases.models import KnowledgeBase, DocumentChunk

logger = logging.getLogger(__name__)
settings = get_settings()

# Basic English grammatical stop words to ignore, so we only extract domain-specific noise words
GRAMMATICAL_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "when", "at", "by", 
    "for", "with", "about", "against", "between", "into", "through", "during", "before", 
    "after", "above", "below", "to", "from", "up", "down", "in", "out", "on", "off", 
    "over", "under", "again", "further", "then", "once", "here", "there", "when", "where", 
    "why", "how", "all", "any", "both", "each", "few", "more", "most", "other", "some", 
    "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "can", "will", "just", "should", "now", "i", "me", "my", "myself", "we", "our",
    "ours", "ourselves", "you", "your", "yours", "yourself", "yourselves", "he", "him",
    "his", "himself", "she", "her", "hers", "herself", "it", "its", "itself", "they",
    "them", "their", "theirs", "themselves", "what", "which", "who", "whom", "this",
    "that", "these", "those", "am", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having", "do", "does", "did", "doing", "would", "should",
    "could", "ought", "of", "to", "has"
}

def is_valid_candidate_word(word: str) -> bool:
    """
    Checks if a normalized word is a valid candidate for a domain-specific noisy word.
    Filters out:
    - empty or single-character words
    - pure numbers
    - UUIDs
    - hexadecimal or alphanumeric hashes/IDs (e.g. invoice IDs, hash strings)
    - grammatical stopwords
    """
    # 1. Ignore empty or single characters
    if len(word) <= 1:
        return False

    # 2. Ignore basic grammatical stop words
    if word in GRAMMATICAL_STOPWORDS:
        return False

    # 3. Ignore pure numbers (e.g., 2023, 10, 1.25, -1)
    if word.isdigit() or word.replace(".", "", 1).isdigit() or word.replace("-", "", 1).isdigit():
        return False

    # 4. Ignore UUID patterns (standard 36-char hex string)
    uuid_pattern = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
    if uuid_pattern.match(word):
        return False

    # 5. Ignore alphanumeric hashes / long IDs (e.g., invoice numbers, serials, hex strings)
    # Typically alphanumeric strings >= 8 characters containing at least one digit
    has_digit = any(c.isdigit() for c in word)
    if has_digit:
        if len(word) >= 8:
            return False
        # Matches patterns like inv-123, id_987, etc.
        if "-" in word or "_" in word:
            return False

    # 6. Check if it has a minimum level of alphabetic characters
    cleaned = "".join(c for c in word if c.isalpha())
    if len(cleaned) <= 1:
        return False

    return True

def get_adaptive_threshold(total_chunks: int, default_threshold: float) -> float:
    """
    Calculates an adaptive document-frequency threshold based on the total chunk count.
    If the user has set a non-default threshold, that is respected.
    """
    # Respect customized configurations (anything other than default 0.3)
    if abs(default_threshold - 0.3) > 1e-5:
        return default_threshold

    # Adaptive logic based on total chunks
    if total_chunks <= 20:
        return 0.50  # Small KBs: word must appear in at least 50% of chunks
    elif total_chunks <= 100:
        return 0.35  # Medium KBs: >= 35%
    elif total_chunks <= 1000:
        return 0.20  # Large KBs: >= 20%
    else:
        return 0.10  # Very large KBs: >= 10%

async def generate_kb_noisy_words(kb_id: str, tenant_id: str) -> None:
    """
    Asynchronously extracts and calculates Document Frequency (DF) based noise scores
    for all chunks belonging to a Knowledge Base, saving the results in the database.
    Invalidates the query-time TTL cache immediately upon completion.
    """
    logger.info(f"Starting background dynamic noisy words generation for KB={kb_id}, Tenant={tenant_id}")
    
    # Establish a fresh database connection session
    async with AsyncSessionLocal() as db:
        try:
            # 1. Fetch all chunks for this knowledge base
            kb_uuid = UUID(kb_id)
            tenant_uuid = UUID(tenant_id)
            
            # Set tenant config for RLS safety
            from sqlalchemy import text
            await db.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
                {"tenant_id": str(tenant_uuid)}
            )
            
            chunk_query = select(DocumentChunk.text).where(DocumentChunk.kb_id == kb_uuid)
            res = await db.execute(chunk_query)
            chunk_texts = [row[0] for row in res.fetchall()]
            
            total_chunks = len(chunk_texts)
            if total_chunks == 0:
                logger.warning(f"No chunks found for KB={kb_id}. Skipping noisy words generation.")
                return
                
            # 2. Tokenize chunks, normalize terms, and count document frequencies
            word_doc_counts = Counter()
            
            for text_content in chunk_texts:
                # Normalization: Lowercase, split on whitespace, strip punctuation/symbols
                unique_words_in_chunk = set()
                for word in text_content.split():
                    normalized = word.strip(".,;:!?\"'()[]{}<>_-@#$%^&*+=`~|\\/").lower()
                    if is_valid_candidate_word(normalized):
                        unique_words_in_chunk.add(normalized)
                
                for w in unique_words_in_chunk:
                    word_doc_counts[w] += 1
            
            # 3. Calculate noise scores and apply adaptive threshold
            config_threshold = settings.noisy_words_min_score_threshold
            min_score = get_adaptive_threshold(total_chunks, config_threshold)
            logger.info(f"Using adaptive noise threshold={min_score} for total_chunks={total_chunks}")
            
            noisy_words_list = []
            for word, df in word_doc_counts.items():
                score = round(df / total_chunks, 3)
                # Word must meet adaptive score threshold
                # And if total_chunks > 1, it must appear in at least 2 chunks
                if score >= min_score and (total_chunks == 1 or df >= 2):
                    noisy_words_list.append({"word": word, "score": score})
            
            # 4. Sort and cap to Top 50 highest-scoring terms
            noisy_words_list.sort(key=lambda x: x["score"], reverse=True)
            top_noisy_words = noisy_words_list[:50]
            
            logger.info(f"Generated {len(top_noisy_words)} noisy words for KB={kb_id}. Top words: {top_noisy_words[:5]}")
            
            # 5. Update the KnowledgeBase record in the database
            update_query = (
                update(KnowledgeBase)
                .where(KnowledgeBase.id == kb_uuid)
                .values(
                    noisy_words=top_noisy_words,
                    noisy_words_generated_at=datetime.utcnow()
                )
            )
            await db.execute(update_query)
            await db.commit()
            logger.info(f"Successfully updated dynamic noisy words in database for KB={kb_id}")
            
            # 6. IMMEDIATELY INVALIDATE QUERY-TIME TTL CACHE
            try:
                from app.modules.rag.pipeline import _KB_NOISY_WORDS_CACHE
                
                # Invalidate using both string and UUID representation
                invalidated = False
                for key in [kb_id, str(kb_uuid)]:
                    if key in _KB_NOISY_WORDS_CACHE:
                        del _KB_NOISY_WORDS_CACHE[key]
                        invalidated = True
                if invalidated:
                    logger.info(f"Invalidated TTL cache for KB={kb_id} after regeneration.")
            except Exception as cache_err:
                logger.warning(f"Failed to invalidate cache: {cache_err}")
                
        except Exception as e:
            await db.rollback()
            logger.error(f"Error generating dynamic noisy words for KB={kb_id}: {e}", exc_info=True)
