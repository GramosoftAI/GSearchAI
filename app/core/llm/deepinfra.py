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
EXPECTED_EMBEDDING_DIMENSION = settings.embedding_dimension

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
        base_url = getattr(settings, "deepinfra_api_url", "https://api.deepinfra.com/v1/openai")
        if not base_url.endswith("/embeddings"):
            if base_url.endswith("/openai"):
                base_url = f"{base_url}/embeddings"
            else:
                base_url = f"{base_url.rstrip('/')}/embeddings"
        self.base_url = base_url
        self.model = settings.model_embedding
        self.timeout = 12.0  # Request timeout in seconds
        self.max_retries = 3  # Number of retry attempts
        self.max_text_length = 1000  # Safe limit (~300-400 tokens)
        self.expected_dimension = settings.embedding_dimension  # Dynamic from settings

        logger.info(
            f" DeepInfra Embedding Client initialized (model={self.model}, timeout={self.timeout}s, dim={self.expected_dimension})"
        )

    async def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding for text via DeepInfra API (backward compatibility wrapper).
        """
        vector, _ = await self.generate_embedding_with_usage(text)
        return vector

    async def generate_embedding_with_usage(self, text: str) -> tuple[List[float], int]:
        """
        Generate embedding for text via DeepInfra API, returning the vector and token count.
        """
        global _embedding_cache_insertion_order

        # Validate input
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        # Truncate to prevent API overload
        text = text[: self.max_text_length]

        # CHECK EMBEDDING CACHE (avoid repeated API calls)
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
            logger.info(f"Embedding source: Cache (for text: {text[:50]}...)")
            return embedding, 0  # Cache hits consume 0 API tokens

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

        # RATE LIMIT GUARD (prevent API throttling)
        async with _embedding_semaphore:
            # Retry logic with exponential backoff
            last_error = None
            for attempt in range(self.max_retries):
                try:
                    logger.debug(
                        f"API request attempt {attempt + 1}/{self.max_retries}"
                    )

                    global _embedding_http_client
                    if _embedding_http_client is None or _embedding_http_client.is_closed:
                        _embedding_http_client = httpx.AsyncClient(
                            timeout=self.timeout,
                            limits=httpx.Limits(max_connections=200, max_keepalive_connections=50)
                        )
                    
                    import time
                    t0 = time.perf_counter()
                    client = _embedding_http_client
                    response = await client.post(
                        self.base_url, headers=headers, json=payload
                    )
                    t_req = time.perf_counter() - t0
                    logger.info(f"[LLM_TIMING] DeepInfra embedding request (single) took {t_req:.4f}s")

                    # Check for HTTP errors
                    response.raise_for_status()

                    # Parse response
                    data = response.json()

                    # Extract embedding from response
                    if "data" not in data or len(data["data"]) == 0:
                        raise ValueError(
                            "Invalid API response: missing embedding data"
                        )

                    embedding = data["data"][0].get("embedding")
                    if not embedding:
                        raise ValueError(
                            "Invalid API response: missing embedding vector"
                        )

                    # VALIDATE VECTOR DIMENSION
                    if len(embedding) != self.expected_dimension:
                        raise ValueError(
                            f"Invalid embedding dimension: got {len(embedding)}, expected {self.expected_dimension}"
                        )

                    # Extract prompt tokens from usage meta
                    prompt_tokens = data.get("usage", {}).get("prompt_tokens", 0)
                    if prompt_tokens == 0:
                        # Fallback token estimate
                        prompt_tokens = max(1, len(text) // 4)

                    # CACHE THE EMBEDDING (for future calls) with LRU eviction
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

                    logger.info(
                        f"Embedding source: DeepInfra (for text: {text[:50]}...)"
                    )
                    return embedding, prompt_tokens

                except httpx.TimeoutException:
                    last_error = TimeoutError(
                        f"API timeout after {self.timeout}s (attempt {attempt + 1})"
                    )
                    logger.warning(
                        f"  API timeout on attempt {attempt + 1}/{self.max_retries}"
                    )

                except httpx.HTTPStatusError as e:
                    last_error = e
                    logger.warning(
                        f"  HTTP {e.response.status_code} on attempt {attempt + 1}/{self.max_retries}: {e.response.text}"
                    )

                except (ValueError, KeyError) as e:
                    last_error = e
                    logger.warning(f"  Response parsing error: {e}")

                except Exception as e:
                    last_error = e
                    logger.warning(f"  Unexpected error on attempt {attempt + 1}: {e}")

                # Don't retry on last attempt
                if attempt < self.max_retries - 1:
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
        Generate embeddings for multiple texts (backward compatibility wrapper).
        """
        vectors, _ = await self.generate_embeddings_batch_with_usage(texts)
        return vectors

    async def generate_embeddings_batch_with_usage(self, texts: List[str]) -> tuple[List[List[float]], int]:
        """
        Generate embeddings for multiple texts using TRUE API BATCHING.
        Returns a tuple: (list of embeddings, total prompt tokens consumed).
        """
        if not texts:
            return [], 0
            
        # 1. Filter out already cached embeddings to save API costs
        results_map = {} # index -> embedding
        to_embed_indices = []
        to_embed_texts = []
        
        for i, text in enumerate(texts):
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
            return [results_map[i] for i in range(len(texts))], 0

        logger.info(f" API Batch generating {len(to_embed_texts)} embeddings (out of {len(texts)} total)...")
        
        # 2. Process in chunks of 50 (API limit safety)
        batch_size = 50

        async def _embed_batch(chunk: List[str], b_idx: int):
            async with _embedding_semaphore:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": self.model,
                    "input": chunk,
                }
                
                global _embedding_http_client
                if _embedding_http_client is None or _embedding_http_client.is_closed:
                    _embedding_http_client = httpx.AsyncClient(
                        timeout=self.timeout,
                        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50)
                    )
                
                last_error = None
                for attempt in range(self.max_retries):
                    try:
                        client = _embedding_http_client
                        import time
                        t0 = time.perf_counter()
                        response = await client.post(self.base_url, headers=headers, json=payload)
                        t_req = time.perf_counter() - t0
                        logger.info(f"[LLM_TIMING] DeepInfra embedding request (batch) took {t_req:.4f}s")
                        response.raise_for_status()
                        data = response.json()
                        
                        new_batch = [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
                        chunk_tokens = data.get("usage", {}).get("prompt_tokens", 0)
                        if chunk_tokens == 0:
                            chunk_tokens = sum(max(1, len(t) // 4) for t in chunk)
                            
                        for j, emb in enumerate(new_batch):
                            orig_text = chunk[j]
                            t_hash = hashlib.sha256(orig_text.encode()).hexdigest()
                            _embedding_cache[t_hash] = emb
                            if t_hash not in _embedding_cache_insertion_order:
                                _embedding_cache_insertion_order.append(t_hash)
                        return b_idx, new_batch, chunk_tokens
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
                
                logger.warning(f" Batch API failed ({last_error}). Falling back to concurrent item-by-item embedding generation for chunk of {len(chunk)} items.")
                item_results = await asyncio.gather(*[self.generate_embedding(item_text) for item_text in chunk])
                return b_idx, item_results, sum(max(1, len(t) // 4) for t in chunk)

        batches = [to_embed_texts[i:i+batch_size] for i in range(0, len(to_embed_texts), batch_size)]
        batch_results = await asyncio.gather(*[_embed_batch(chunk, idx) for idx, chunk in enumerate(batches)])
        batch_results.sort(key=lambda x: x[0])
        all_new_embeddings = []
        total_tokens = 0
        for _, embs, toks in batch_results:
            all_new_embeddings.extend(embs)
            total_tokens += toks

        # 3. Reconstruct full list in original order
        for i, idx in enumerate(to_embed_indices):
            results_map[idx] = all_new_embeddings[i]
            
        final_results = [results_map[i] for i in range(len(texts))]
        logger.info(f" Batch generation complete: {len(texts)} embeddings")
        return final_results, total_tokens


class DeepInfraEmbedder:
    def __init__(self):
        settings = get_settings()
        self.api_key = settings.deepinfra_api_key
        base_url = getattr(settings, "deepinfra_api_url", "https://api.deepinfra.com/v1/openai")
        if not base_url.endswith("/embeddings"):
            if base_url.endswith("/openai"):
                base_url = f"{base_url}/embeddings"
            else:
                base_url = f"{base_url.rstrip('/')}/embeddings"
        self.base_url = base_url
        self.model = settings.model_embedding  # ← from .env, never hardcoded
        self.dimension = settings.embedding_dimension

        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of texts.
        Returns a list of float vectors, one per input text.
        """
        payload = {
            "model": self.model,
            "input": texts,
        }
        response = await self.client.post("", json=payload)
        response.raise_for_status()
        data = response.json()
        return [item["embedding"] for item in data["data"]]

    async def embed_single(self, text: str) -> List[float]:
        """Embed a single string. Returns a flat float vector."""
        results = await self.embed([text])
        return results[0]

    async def close(self):
        await self.client.aclose()

