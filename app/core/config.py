"""Production-grade configuration system using Pydantic BaseSettings (reloaded)"""



from pydantic_settings import BaseSettings

from typing import Optional

from functools import lru_cache

import logging



logger = logging.getLogger(__name__)





class Settings(BaseSettings):

    """

    Main application settings loaded from .env file.



    Do NOT hardcode any sensitive values.

    Load all secrets from environment variables.

    """



    # ============= APPLICATION CORE =============

    app_name: str = "GraphMind"

    app_version: str = "1.0.0"

    app_env: str = "development"  # development, staging, production

    debug: bool = False



    # ============= SERVER SETTINGS =============

    host: str = "0.0.0.0"

    port: int = 8000

    FRONTEND_URL: str = "http://localhost:3000"



    # ============= EXTERNAL ALERTS =============
    slack_webhook_url: Optional[str] = None
    
    # ============= REDIS (ARQ) =============
    redis_url: str = "redis://localhost:6379"

    # ============= POSTGRESQL ASYNC =============

    postgres_user: str

    postgres_password: str

    postgres_host: str = "localhost"

    postgres_port: int = 5432

    postgres_db: str = "graphmind"
    
    # ============= LLM GATEWAY =============
    llm_base_url: str



    @property

    def database_url(self) -> str:

        """Construct async PostgreSQL URL from components"""

        import urllib.parse
        encoded_pw = urllib.parse.quote_plus(urllib.parse.unquote_plus(self.postgres_password))
        return f"postgresql+asyncpg://{self.postgres_user}:{encoded_pw}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"



    postgres_echo: bool = False  # Log SQL queries in debug mode

    postgres_pool_size: int = 10  # Connection pool size

    postgres_pool_recycle: int = 3600  # Recycle connections after 1 hour

    postgres_max_overflow: int = 20



    # ============= NEO4J GRAPH DATABASE =============

    neo4j_uri: str  # e.g., bolt://localhost:7687

    neo4j_user: str

    neo4j_password: str

    neo4j_pool_size: int = 10

    neo4j_max_connection_lifetime: int = 3600  # seconds



    # ============= JWT / SECURITY =============

    jwt_secret_key: str  # Must be strong and long (32+ chars)

    jwt_algorithm: str = "HS256"

    access_token_expire_minutes: int = 30

    refresh_token_expire_days: int = 7



    def validate_jwt_secret(self) -> None:

        """CRITICAL: Validate JWT secret on startup."""

        if len(self.jwt_secret_key) < 32:

            raise ValueError(

                f"JWT_SECRET_KEY too short: {len(self.jwt_secret_key)} chars. "

                f"Minimum 32 characters required for HS256 security. "

                f"Generated secure key: {self._generate_secure_key()}"

            )



    @staticmethod

    def _generate_secure_key() -> str:

        """Generate a secure random key for JWT_SECRET_KEY."""

        import secrets



        return secrets.token_urlsafe(32)  # ~43 chars base64-encoded



    # Password security

    password_min_length: int = 8

    password_require_uppercase: bool = True

    password_require_lowercase: bool = True

    password_require_digits: bool = True

    password_require_special: bool = False



    # ============= ENCRYPTION (PER-TENANT) =============

    encryption_algorithm: str = (

        "fernet"  # Keep as fernet for per-tenant symmetric encryption

    )

    # Individual tenant keys loaded from environment: TENANT_<tenant_id>_ENCRYPTION_KEY



    # ============= EMBEDDINGS CONFIGURATION =============

    # Dimension must match your embedding model

    # OpenAI text-embedding-3-small: 1536

    # OpenAI text-embedding-3-large: 3072

    # Open-source models (BERT, etc.): 768-1024

    embedding_dimension: int = 1024  # Standard for BAAI/bge-large-en-v1.5

    embedding_model: str = "BAAI/bge-large-en-v1.5"



    # ============= EMAIL SMTP SETTINGS =============

    email_host: str = ""

    email_port: int = 587

    email_username: str = ""

    email_password: str = ""

    email_from: str = ""



    # ============= EXTERNAL SERVICES =============

    deepinfra_api_key: Optional[str] = None  # For LLM inference

    deepinfra_api_url: str = "https://api.deepinfra.com/v1/openai"
    
    deepinfra_llm_model: str = "Qwen/Qwen2.5-7B-Instruct"

    gdocz_api_key: Optional[str] = None  # For PDF  Markdown extraction (primary)

    # ============= AWS S3 =============
    aws_region: Optional[str] = None
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_s3_bucket: Optional[str] = None



    # ============= LOGGING =============

    log_level: str = "INFO"

    log_format: str = "json"  # json or text



    # ============= EMAIL SMTP =============
    email_host: Optional[str] = None
    email_port: int = 465
    email_username: Optional[str] = None
    email_password: Optional[str] = None
    email_from: Optional[str] = None



    # ============= WEB CRAWLER API =============

    crawler_api_url: Optional[str] = None

    crawler_api_key: Optional[str] = None

    crawler_mode: str = "single"  # single or all (up to 10)

    crawler_enable_md: bool = True  # Always receive in markdown format



    # ============= GCRAWL API =============

    gcrawl_enabled: bool = True

    gcrawl_timeout: int = 30

    gcrawl_retry: int = 1



    # ============= FEATURE FLAGS (PHASE SWITCHING) =============

    # Phase 2 (MVP): Hash-based embeddings, regex entity extraction

    # Phase 3 (Prod): Real DeepInfra embeddings, LLM entity extraction

    # These flags enable gradual rollout, A/B testing, rollback safety



    use_real_embeddings: bool = False  # Phase 3: Switch to DeepInfra API

    use_llm_entity_extraction: bool = False  # Phase 3: Switch to LLM-based

    enable_pdf_fallback: bool = True  # Enable/disable heavy LLM fallback/pdfplumber mechanisms when Gdocz fails/is not configured

    enable_billing: bool = False  # Billing system toggle (per-tenant cost tracking)

    reset_db_on_start: bool = False  # DANGEROUS: Only True in development for testing

    reset_graph_db_on_start: bool = False  # DANGEROUS: Wipes Neo4j on startup

    reset_s3_on_start: bool = False  # DANGEROUS: Deletes S3 files on startup when resetting database



    # ============= PHASE 4A: KNOWLEDGE INTELLIGENCE =============

    # Triplet extraction: LLM extracts (Subject, Predicate, Object) from chunks

    # Runs as POST-INGESTION hook  existing pipeline unaffected when disabled

    use_triplet_extraction: bool = False  # Phase 4A: Enable triplet graph construction

    triplet_max_per_chunk: int = 10  # Max triplets to extract per chunk

    triplet_retrieval_top_k: int = 10  # Triplets to retrieve during RAG query

    use_personal_memory: bool = False  # Phase 5: Enable user-specific personalization (Mem0 Pattern)



    # ============= LLM OPTIMIZATIONS =============
    ingestion_llm_concurrency: int = 30  # Max parallel LLM extractions
    ingestion_llm_timeout: float = 120.0  # Extended timeout for complex extractions
    enable_thinking: bool = False  # Enable/disable thinking/reasoning mode in LLM calls

    

    # ============= SIMILARITY SEARCH CONFIG =============

    # Hybrid mode: Use O(n) for small KBs, vector index for large

    similarity_brute_force_threshold: int = 500  # Use O(n) if chunks < this

    similarity_min_threshold: float = 0.5  # Only link chunks with >50% similarity

    max_similar_per_chunk: int = 5  # Cap edges per chunk to keep graph clean

    noisy_words_min_score_threshold: float = 0.3



    # ============= RATE LIMITING =============

    rate_limit_enabled: bool = True

    rate_limit_requests_per_minute: int = 60

    rate_limit_requests_per_hour: int = 1000



    # ============= CORS =============

    # SECURITY: Never use "*" in production (allows any origin + credentials)

    cors_origins: list = ["*"]  # DEV ONLY - Change in production

    cors_credentials: bool = True

    cors_methods: list = ["*"]

    cors_headers: list = ["*"]



    def validate_cors(self) -> None:

        """CRITICAL: Validate CORS in production."""

        if self.app_env == "production" and "*" in self.cors_origins:

            raise ValueError(

                "CORS_ORIGINS contains '*' in production. "

                "This is a critical security issue (allows any origin + credentials). "

                "Set specific origins: CORS_ORIGINS=['https://example.com']"

            )



    def validate_similarity_search(self) -> None:

        """Validate similarity search configuration."""

        if self.max_similar_per_chunk <= 0:

            raise ValueError(

                f"max_similar_per_chunk must be > 0, got {self.max_similar_per_chunk}. "

                f"This controls the maximum number of semantic edges per chunk. "

                f"Recommended: 5 (prevents dense graph while keeping good coverage)."

            )



        if self.similarity_brute_force_threshold <= 0:

            raise ValueError(

                f"similarity_brute_force_threshold must be > 0, got {self.similarity_brute_force_threshold}. "

                f"This is the KB size threshold for using O(n) similarity computation. "

                f"Recommended: 500 (small KBs get full accuracy, large KBs defer to Phase 3 vector index)."

            )



        if self.similarity_min_threshold < 0 or self.similarity_min_threshold > 1.0:

            raise ValueError(

                f"similarity_min_threshold must be in [0, 1], got {self.similarity_min_threshold}. "

                f"This controls semantic relationship threshold (0=all, 1=identical only). "

                f"Recommended: 0.7 (link chunks with >70% semantic similarity)."

            )



    def validate_configuration(self) -> None:

        """

        Validate all configuration at startup.



        CRITICAL: This runs when settings are first loaded.

        If validation fails, the application will NOT start.

        """

        try:

            # Validate JWT security

            self.validate_jwt_secret()



            # Validate CORS security

            self.validate_cors()



            # Validate similarity search config

            self.validate_similarity_search()



            logger.info(" Configuration validation passed")



        except ValueError as e:

            logger.critical(f" Configuration validation failed: {e}")

            raise RuntimeError(f"Invalid configuration: {e}")



    def log_feature_flags(self) -> None:

        """Log feature flag status for debugging and rollout monitoring."""

        logger.info("=" * 80)

        logger.info("FEATURE FLAG STATUS")

        logger.info("=" * 80)



        embedding_mode = (

            "REAL (DeepInfra API)" if self.use_real_embeddings else "HASH (Phase 2)"

        )

        entity_extraction_mode = (

            "LLM (Phase 3)" if self.use_llm_entity_extraction else "REGEX (Phase 2)"

        )

        triplet_mode = (

            "ENABLED (LLM-based)" if self.use_triplet_extraction else "DISABLED"

        )



        logger.info(f"  use_real_embeddings: {embedding_mode}")

        logger.info(f"  use_llm_entity_extraction: {entity_extraction_mode}")

        logger.info(f"  use_triplet_extraction: {triplet_mode}")

        logger.info(f"  use_personal_memory: {self.use_personal_memory}")

        logger.info(

            f"  similarity_brute_force_threshold: {self.similarity_brute_force_threshold} chunks"

        )

        logger.info(f"  similarity_min_threshold: {self.similarity_min_threshold}")

        logger.info(f"  max_similar_per_chunk: {self.max_similar_per_chunk}")

        logger.info("=" * 80)



    class Config:

        env_file = ".env"

        env_file_encoding = "utf-8"

        case_sensitive = False

        extra = (

            "ignore"  # Pydantic v2: Ignore extra fields from .env (e.g., POSTGRES_URI)

        )

        # Load nested settings from environment

        # e.g., POSTGRES_USER, NEO4J_URI, JWT_SECRET_KEY





@lru_cache()

def get_settings() -> Settings:

    """

    Get cached settings instance (singleton pattern).



    Using @lru_cache ensures we only load and parse .env once.

    Performs configuration validation and logs feature flags.



    Raises:

        RuntimeError: If configuration validation fails



    Returns:

        Validated Settings instance (singleton)

    """

    settings_instance = Settings()



    # CRITICAL: Validate configuration at startup

    settings_instance.validate_configuration()



    # Log feature flags for debugging and monitoring

    settings_instance.log_feature_flags()



    return settings_instance





# For backward compatibility

settings = get_settings()

