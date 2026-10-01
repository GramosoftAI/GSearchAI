import re

class EntityExtractor:
    """
    Extracts potential person names from the raw user query.
    Uses a large stop-word list to exclude common English and domain words,
    leaving only likely proper nouns (person names).
    """
    
    # Comprehensive stop words: common English + database/business domain terms
    STOP_WORDS = {
        # Common English
        "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "by", "from",
        "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
        "do", "does", "did", "can", "could", "should", "would", "will", "shall",
        "may", "might", "must", "need", "dare",
        "and", "or", "not", "no", "nor", "but", "if", "then", "else", "so", "than",
        "show", "me", "my", "mine", "your", "yours", "his", "her", "hers", "its",
        "our", "ours", "their", "theirs", "this", "that", "these", "those",
        "what", "which", "who", "whom", "whose", "how", "where", "when", "why",
        "i", "you", "he", "she", "it", "we", "they",
        "am", "im",
        "get", "got", "find", "list", "give", "tell", "name", "named",
        "please", "just", "also", "only", "about", "like", "want", "know",
        "very", "much", "many", "some", "any", "all", "each", "every",
        "more", "most", "less", "least", "few", "several",
        "here", "there", "up", "down", "out", "off", "over", "under",
        "between", "through", "during", "before", "after", "above", "below",
        # Time words
        "yesterday", "today", "tomorrow", "last", "next", "ago", "since",
        "week", "month", "year", "day", "date", "time", "hour", "minute",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "january", "february", "march", "april", "may", "june", 
        "july", "august", "september", "october", "november", "december",
        # Database / business domain
        "work", "package", "packages", "task", "tasks", "project", "projects",
        "user", "users", "author", "assignee", "assigned", "created", "updated",
        "status", "type", "priority", "id", "total", "count", "number", "sum", "average",
        "table", "column", "row", "data", "database", "query", "report", "result",
        "select", "filter", "sort", "group", "order", "limit",
        "first", "second", "third", "new", "old", "recent", "current", "previous",
    }
    
    @staticmethod
    async def extract_person_names(query: str) -> list[str]:
        """
        Extract likely person names from a natural language query.
        Returns only words that survive stop-word filtering and look like proper nouns.
        """
        words = re.findall(r'\b[a-zA-Z]+\b', query)
        
        candidates = []
        for w in words:
            if w.lower() in EntityExtractor.STOP_WORDS:
                continue
            if len(w) < 2:
                continue
            candidates.append(w)
        
        return candidates
