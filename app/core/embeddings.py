"""Embedding generation using DeepInfra API for semantic search"""



import httpx

import logging

from typing import List

from functools import lru_cache



from .config import get_settings

from .llm.deepinfra import DeepInfraEmbeddingClient



logger = logging.getLogger(__name__)

settings = get_settings()



# Initialize DeepInfra client (lazy - created on first use)

_deepinfra_client = None





def _get_deepinfra_client():

    """Get or create DeepInfra embedding client (singleton)"""

    global _deepinfra_client

    if _deepinfra_client is None:

        _deepinfra_client = DeepInfraEmbeddingClient()

    return _deepinfra_client





class EmbeddingGenerator:

    """

    Generate text embeddings using DeepInfra API.



    Production-grade embeddings for semantic search and similarity.

    Each embedding is typically a 512-dimensional vector (Production)

    or matches the configured settings.embedding_dimension.

    """



    @staticmethod

    def get_dimension() -> int:

        """Get the configured embedding dimension."""

        return settings.embedding_dimension



    # API endpoint for embeddings

    # Using meta-llama/Llama-2-7b-hf as embedding model is NOT right

    # We need actual embedding model. For now using a simple approach.

    # In production: use sentence-transformers hosted endpoint

    EMBEDDING_API = getattr(settings, "deepinfra_api_url", "https://api.deepinfra.com/v1/openai")



    # Track if we've logged the embedding mode (avoid spam)

    _mode_logged = False



    # Simple in-memory cache for exact-match queries across requests

    _query_cache: dict[str, tuple[List[float], int]] = {}

    _cache_max_size: int = 1000



    @staticmethod
    async def generate_embedding(text: str, is_query: bool = False) -> List[float]:
        """
        Generate embedding for text using feature flag for Phase switching.
        """
        vector, _ = await EmbeddingGenerator.generate_embedding_with_usage(text, is_query=is_query)
        return vector

    @staticmethod
    async def generate_embedding_with_usage(text: str, request_id: str = "unknown", is_query: bool = False) -> tuple[List[float], int]:
        """
        Generate embedding for text, returning (embedding vector, token count).
        """
        if not EmbeddingGenerator._mode_logged:
            mode = (
                "REAL (DeepInfra API)"
                if settings.use_real_embeddings
                else "HASH (Phase 2)"
            )
            logger.info(f"Using embedding mode: {mode}")
            EmbeddingGenerator._mode_logged = True

        if not text or len(text.strip()) == 0:
            return [0.0] * settings.embedding_dimension, 0

        # BGE models require a specific prefix for retrieval queries
        if is_query and "bge" in getattr(settings, "model_embedding", "").lower():
            if not text.startswith("Represent this sentence"):
                text = f"Represent this sentence for searching relevant passages: {text}"

        cache_key = text.lower().strip()
        if cache_key in EmbeddingGenerator._query_cache:
            logger.info(f"[EMBEDDING_CACHE_HIT] request_id={request_id} (text length: {len(text)})")
            return EmbeddingGenerator._query_cache[cache_key]

        try:
            if settings.use_real_embeddings:
                import time
                client = _get_deepinfra_client()
                t0 = time.perf_counter()
                result = await client.generate_embedding_with_usage(text)
                t1 = time.perf_counter()
                dur_s = t1 - t0
                dur_ms = round(dur_s * 1000.0, 2)
                
                logger.info(
                    f"[QUERY_EMBEDDING] request_id={request_id} model={client.model} "
                    f"generated_once=true latency_ms={dur_ms}"
                )
                
                warm_state = "warm" if dur_ms < 2000.0 else "cold"
                logger.info(
                    f"[EMBEDDING_LATENCY] request_id={request_id} latency_ms={dur_ms} "
                    f"status=200 warm_state={warm_state}"
                )
                
                if dur_ms >= 2000.0:
                    logger.warning(
                        f"[EMBEDDING_COLD_START] request_id={request_id} latency_ms={dur_ms} "
                        f"threshold_ms=2000 possible_provider_cold_start=true"
                    )
                
                # Add to cache
                if len(EmbeddingGenerator._query_cache) >= EmbeddingGenerator._cache_max_size:
                    EmbeddingGenerator._query_cache.clear()
                EmbeddingGenerator._query_cache[cache_key] = result
                return result
            else:
                logger.debug(
                    f"Embedding source: Hash (Phase 2) for text: {text[:50]}..."
                )
                return EmbeddingGenerator._hash_to_embedding(text), 0
        except Exception as e:
            logger.warning(
                f"Failed to generate embedding: {e}. Falling back to hash."
            )
            logger.info(
                f"Embedding source: Fallback Hash (API failed) for text: {text[:50]}..."
            )
            return EmbeddingGenerator._hash_to_embedding(text), 0



    @staticmethod

    def _hash_to_embedding(text: str) -> List[float]:

        """

        Convert text to deterministic embedding using hash (Phase 2).



        This is NOT production-grade but allows testing without DeepInfra.

        Ensures same text always gets same embedding.



        Phase 3: Replace with actual embedding model call.



        Args:

            text: Text to embed



        Returns:

            Deterministic vector matches settings.embedding_dimension

        """

        import hashlib



        # Create hash of text

        hash_obj = hashlib.sha256(text.encode())

        hash_int = int(hash_obj.hexdigest(), 16)



        # Seed random number generator with hash

        import random



        rng = random.Random(hash_int)



        # Generate 768-dimensional vector from hash

        # All values in range [-1.0, 1.0] (typical for embeddings after normalization)

        embedding = [

            rng.uniform(-1.0, 1.0) for _ in range(settings.embedding_dimension)

        ]



        return embedding



    @staticmethod
    async def generate_embeddings_batch(texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts in parallel.
        """
        vectors, _ = await EmbeddingGenerator.generate_embeddings_batch_with_usage(texts)
        return vectors

    @staticmethod
    async def generate_embeddings_batch_with_usage(texts: List[str]) -> tuple[List[List[float]], int]:
        """
        Generate embeddings for multiple texts, returning (list of vectors, total token count).
        """
        if not texts:
            return [], 0

        try:
            if settings.use_real_embeddings:
                import time
                client = _get_deepinfra_client()
                t0 = time.perf_counter()
                result = await client.generate_embeddings_batch_with_usage(texts)
                t1 = time.perf_counter()
                if t1 - t0 > 10.0:
                    logger.warning(f"HIGH LATENCY: DeepInfra embeddings batch call took {t1 - t0:.2f}s")
                return result
            else:
                return [EmbeddingGenerator._hash_to_embedding(text) for text in texts], 0
        except Exception as e:
            logger.warning(
                f"Failed to generate real embeddings batch: {e}. Falling back to hash-based."
            )
            return [EmbeddingGenerator._hash_to_embedding(text) for text in texts], 0



    @staticmethod

    def cosine_similarity(embedding1: List[float], embedding2: List[float]) -> float:

        """

        Calculate cosine similarity between two embeddings.



        CRITICAL for Chunk-[:SIMILAR]->Chunk relationships.



        Args:

            embedding1: First embedding vector

            embedding2: Second embedding vector



        Returns:

            Similarity score in [0, 1] (0=opposite, 1=identical)

        """

        import math



        # Handle zero vectors

        if embedding1 is None or embedding2 is None or len(embedding1) == 0 or len(embedding2) == 0:

            return 0.0



        # Compute dot product

        dot_product = sum(a * b for a, b in zip(embedding1, embedding2))



        # Compute magnitudes

        magnitude1 = math.sqrt(sum(a * a for a in embedding1))

        magnitude2 = math.sqrt(sum(b * b for b in embedding2))



        # Avoid division by zero

        if magnitude1 == 0 or magnitude2 == 0:

            return 0.0



        # Cosine similarity

        similarity = dot_product / (magnitude1 * magnitude2)



        # Normalize to [0, 1] (cosine similarity is typically in [-1, 1])

        # Map -1 to 0, 1 to 1

        normalized = (similarity + 1) / 2.0



        return max(0.0, min(1.0, normalized))  # Clamp to [0, 1]

