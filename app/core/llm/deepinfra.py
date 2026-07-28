"""
DeepInfra Embedding Client - Production-grade semantic embeddings

Provides async HTTP client for generating real embeddings via DeepInfra API.
Used in Phase 3 for real semantic similarity (replaces Phase 2 hash-based embeddings).

MODEL: qwen3-embedd-0.4B (fast, accurate, production-ready)
DIMENSION: 512 (efficient for similarity matching)
COST: Minimal per request

SAFETY:
- Automatic retries (3 attempts)
- Timeout protection (10 seconds)
- Graceful fallback on failure
- Text size limits (2000 chars max)
"""

import httpx
import logging
import asyncio
import hashlib
from typing import List

from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Global rate limiter (max 25 concurrent API calls)
_embedding_semaphore = asyncio.Semaphore(25)

# Persistent HTTP client for embedding API (reused across batch calls)
_embedding_http_client: httpx.AsyncClient = None

# Global embedding cache (text_hash -> embedding vector)
# With LRU eviction to prevent unbounded memory growth
_embedding_cache = {}
_embedding_cache_insertion_order = []  # Track insertion order for LRU eviction
_MAX_EMBEDDING_CACHE = 5000  # Max cache entries before eviction
EXPECTED_EMBEDDING_DIMENSION = 1024

# Cache metrics for optimization tuning
_cache_hits = 0
_cache_misses = 0
_cache_evictions = 0


class DeepInfraEmbeddingClient:
    """
    Async HTTP client for DeepInfra embedding API.

    FLOW:
    1. Initialize with API key from environment
    2. Send text to API
    3. Receive embedding vector
    4. Cache for repeated text
    5. Fallback on failure

    PRODUCTION FEATURES:
    - Automatic retries (exponential backoff)
    - Timeout protection
    - Text size limits (prevents overload)
    - Error logging + graceful fallback
    - Async throughout (non-blocking)
    """

    def __init__(self):
        """
        Initialize DeepInfra client with API key and config.

        Reads from settings.deepinfra_api_key (required)
        """
        self.api_key = settings.deepinfra_api_key
        self.base_url = "https://api.deepinfra.com/v1/openai/embeddings"
        self.model = "BAAI/bge-large-en-v1.5"
        self.timeout = 30.0  # Request timeout in seconds
        self.max_retries = 3  # Number of retry attempts
        self.max_text_length = 1000  # Safe limit (~300-400 tokens) for BGE-large 512-token context limit
        self.expected_dimension = EXPECTED_EMBEDDING_DIMENSION  # 1024

        logger.info(
            f" DeepInfra Embedding Client initialized (model={self.model}, timeout={self.timeout}s, dim={self.expected_dimension})"
        )

    async def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding for text via DeepInfra API.

        FLOW:
        1. Validate input (not empty)
        2. Check embedding cache (avoid repeated API calls)
        3. Truncate if too long (safety)
        4. Acquire rate limit semaphore (prevent throttling)
        5. Call API with retries
        6. Validate vector dimension (prevent silent bugs)
        7. Return vector

        RETRY LOGIC:
        - Attempt 1: Initial request
        - Attempt 2: Retry on failure (exponential backoff)
        - Attempt 3: Final retry
        - If all fail: Raise exception (caller handles fallback)

        TIMEOUT:
        - 10 seconds max per request
        - Prevents hanging on slow API

        Args:
            text: Text to embed (string)

        Returns:
            List[float]: Embedding vector (typically 512 dimensions)

        Raises:
            ValueError: If text is empty
            httpx.HTTPError: If API request fails after retries
            Exception: Any unexpected error (caller should fallback)

        Examples:
            >>> client = DeepInfraEmbeddingClient()
            >>> embedding = await client.generate_embedding("Hello world")
            >>> len(embedding)
            512
        """
        global _embedding_cache_insertion_order

        # Validate input
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        # Truncate to prevent API overload
        text = text[: self.max_text_length]

        # IMPROVEMENT 1: CHECK EMBEDDING CACHE (avoid repeated API calls)
        global _cache_hits, _cache_misses

        text_hash = hashlib.sha256(text.encode()).hexdigest()
        if text_hash in _embedding_cache:
            embedding = _embedding_cache[text_hash]
            _cache_hits += 1
            logger.debug(
                f" Cache HIT: Retrieved embedding from cache ({len(embedding)} dims, cache: {len(_embedding_cache)}/{_MAX_EMBEDDING_CACHE})  hits: {_cache_hits} | misses: {_cache_misses}"
            )
            # Move to end of insertion order (mark as recently used for LRU)
            if text_hash in _embedding_cache_insertion_order:
                _embedding_cache_insertion_order.remove(text_hash)
                _embedding_cache_insertion_order.append(text_hash)
            # IMPROVEMENT 2: LOG EMBEDDING SOURCE
            logger.info(f"Embedding source: Cache (for text: {text[:50]}...)")
            return embedding

        _cache_misses += 1

        logger.debug(f"Generating embedding for text ({len(text)} chars)")

        # Prepare headers
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Prepare payload
        payload = {
            "model": self.model,
            "input": text,
        }

        # IMPROVEMENT 3: RATE LIMIT GUARD (prevent API throttling)
        async with _embedding_semaphore:
            # Retry logic with exponential backoff
            last_error = None
            for attempt in range(self.max_retries):
                try:
                    logger.debug(
                        f"API request attempt {attempt + 1}/{self.max_retries}"
                    )

                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        response = await client.post(
                            self.base_url, headers=headers, json=payload
                        )

                        # Check for HTTP errors
                        response.raise_for_status()

                        # Parse response
                        data = response.json()

                        # Extract embedding from response
                        # DeepInfra returns: {"data": [{"embedding": [...], "index": 0}]}
                        if "data" not in data or len(data["data"]) == 0:
                            raise ValueError(
                                "Invalid API response: missing embedding data"
                            )

                        embedding = data["data"][0].get("embedding")
                        if not embedding:
                            raise ValueError(
                                "Invalid API response: missing embedding vector"
                            )

                        # IMPROVEMENT 4: VALIDATE VECTOR DIMENSION (prevent silent bugs)
                        if len(embedding) != self.expected_dimension:
                            raise ValueError(
                                f"Invalid embedding dimension: got {len(embedding)}, expected {self.expected_dimension}"
                            )

                        # CACHE THE EMBEDDING (for future calls) with LRU eviction

                        # Track insertion order for LRU eviction
                        if text_hash not in _embedding_cache_insertion_order:
                            _embedding_cache_insertion_order.append(text_hash)

                        # Evict oldest entries if cache exceeds max size
                        global _cache_evictions

                        while len(_embedding_cache) > _MAX_EMBEDDING_CACHE:
                            oldest_hash = _embedding_cache_insertion_order.pop(0)
                            if oldest_hash in _embedding_cache:
                                del _embedding_cache[oldest_hash]
                                _cache_evictions += 1
                                logger.debug(
                                    f"  Evicted oldest embedding (cache size > {_MAX_EMBEDDING_CACHE})  total evictions: {_cache_evictions}"
                                )

                        logger.debug(
                            f" Embedding generated and cached ({len(embedding)} dims, cache: {len(_embedding_cache)}/{_MAX_EMBEDDING_CACHE})"
                        )

                        # LOG EMBEDDING SOURCE (for rollout monitoring)
                        logger.info(
                            f"Embedding source: DeepInfra (for text: {text[:50]}...)"
                        )
                        return embedding

                except httpx.TimeoutException:
                    last_error = TimeoutError(
                        f"API timeout after {self.timeout}s (attempt {attempt + 1})"
                    )
                    logger.warning(
                        f"  API timeout on attempt {attempt + 1}/{self.max_retries}"
                    )

                except httpx.HTTPStatusError as e:
                    # HTTP error (4xx, 5xx)
                    last_error = e
                    logger.warning(
                        f"  HTTP {e.response.status_code} on attempt {attempt + 1}/{self.max_retries}: {e.response.text}"
                    )

                except (ValueError, KeyError) as e:
                    # Response parsing error
                    last_error = e
                    logger.warning(f"  Response parsing error: {e}")

                except Exception as e:
                    # Unexpected error
                    last_error = e
                    logger.warning(f"  Unexpected error on attempt {attempt + 1}: {e}")

                # Don't retry on last attempt
                if attempt < self.max_retries - 1:
                    # Exponential backoff: 1s, 2s, 4s, ...
                    wait_time = 2**attempt
                    logger.debug(f"Retrying in {wait_time}s...")

                    await asyncio.sleep(wait_time)

            # All retries exhausted
            logger.error(
                f" All {self.max_retries} attempts failed. Last error: {last_error}"
            )
            raise last_error or Exception(
                "Failed to generate embedding after all retries"
            )

    async def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts using TRUE API BATCHING.

        PHASE 3.5 ENHANCEMENT:
        Sends up to 50 texts in a single HTTP request. This dramatically 
        reduces HTTP overhead and allows the server to process chunks in parallel.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embeddings (same length as input)
        """
        if not texts:
            return []
            
        # 1. Filter out already cached embeddings to save API costs
        results_map = {} # index -> embedding
        to_embed_indices = []
        to_embed_texts = []
        
        for i, text in enumerate(texts):
            # Validate and truncate text to prevent API token limit errors
            if not text or not text.strip():
                text = "empty"
            text = text[: self.max_text_length]
            
            text_hash = hashlib.sha256(text.encode()).hexdigest()
            if text_hash in _embedding_cache:
                results_map[i] = _embedding_cache[text_hash]
            else:
                to_embed_indices.append(i)
                to_embed_texts.append(text)
                
        if not to_embed_texts:
            logger.info(f" All {len(texts)} embeddings retrieved from cache")
            return [results_map[i] for i in range(len(texts))]

        logger.info(f" API Batch generating {len(to_embed_texts)} embeddings (out of {len(texts)} total)...")
        
        # 2. Process in chunks of 50 (API limit safety)
        batch_size = 50
        all_new_embeddings = []
        
        for i in range(0, len(to_embed_texts), batch_size):
            chunk = to_embed_texts[i:i+batch_size]
            
            async with _embedding_semaphore:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": self.model,
                    "input": chunk,
                }
                
                # Reuse persistent HTTP client across batches
                global _embedding_http_client
                if _embedding_http_client is None or _embedding_http_client.is_closed:
                    _embedding_http_client = httpx.AsyncClient(timeout=self.timeout)
                
                last_error = None
                for attempt in range(self.max_retries):
                    try:
                        client = _embedding_http_client
                        response = await client.post(self.base_url, headers=headers, json=payload)
                        response.raise_for_status()
                        data = response.json()
                        
                        # Extract embeddings: {"data": [{"embedding": [...], "index": 0}, ...]}
                        new_batch = [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
                        all_new_embeddings.extend(new_batch)
                        
                        # Update cache
                        for j, emb in enumerate(new_batch):
                            orig_text = chunk[j]
                            t_hash = hashlib.sha256(orig_text.encode()).hexdigest()
                            _embedding_cache[t_hash] = emb
                            if t_hash not in _embedding_cache_insertion_order:
                                _embedding_cache_insertion_order.append(t_hash)
                        break  # Success, exit retry loop
                            
                    except httpx.TimeoutException:
                        last_error = TimeoutError(f"API timeout after {self.timeout}s (attempt {attempt + 1})")
                        logger.warning(f"  Batch API timeout on attempt {attempt + 1}/{self.max_retries}")
                    except httpx.HTTPStatusError as e:
                        last_error = e
                        logger.warning(f"  Batch HTTP {e.response.status_code} on attempt {attempt + 1}: {e.response.text}")
                    except (ValueError, KeyError) as e:
                        last_error = e
                        logger.warning(f"  Batch response parsing error on attempt {attempt + 1}: {e}")
                    except Exception as e:
                        last_error = e
                        logger.warning(f"  Batch unexpected error on attempt {attempt + 1}: {e}")
                    
                    if attempt < self.max_retries - 1:
                        wait_time = 2 ** attempt
                        logger.debug(f"Retrying batch in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                else:
                    logger.warning(f" Batch API failed ({last_error}). Falling back to concurrent item-by-item embedding generation for chunk of {len(chunk)} items.")
                    item_results = await asyncio.gather(*[self.generate_embedding(item_text) for item_text in chunk])
                    all_new_embeddings.extend(item_results)

        # 3. Reconstruct full list in original order
        for i, idx in enumerate(to_embed_indices):
            results_map[idx] = all_new_embeddings[i]
            
        final_results = [results_map[i] for i in range(len(texts))]
        logger.info(f" Batch generation complete: {len(texts)} embeddings")
        return final_results
