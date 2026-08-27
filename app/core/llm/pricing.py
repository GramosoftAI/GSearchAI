"""
LiteLLM-Powered Model Pricing and Cost Calculation Engine for GraphMind.

Provides unified, multi-provider model pricing lookups, token cost calculations,
and model metadata backed by GraphMind's application-controlled pricing registry
layered on top of LiteLLM's in-memory model cost database.

Architecture:
    LiteLLM Built-in Registry
              +
    Remote Master Registry (Validated)
              +
    GraphMind Custom Overrides
              ↓
    GraphMindPricingRegistry (Controlled Application Source of Truth)
              ↓
    Resolved O(1) Cache (_RESOLVED_PRICING_CACHE)
              ↓
    Cost Calculation Engine (Chat + Ingestion + Embeddings)

Features:
- O(1) in-memory pricing lookups with zero network requests during execution.
- Multi-provider support (DeepInfra, OpenAI, Anthropic, Groq, Ollama, Azure, Bedrock, Together AI, etc.).
- DeepInfra remains the default provider.
- Full support for provider-qualified model strings (e.g. 'openai/gpt-4o', 'deepinfra/meta-llama/Llama-3.3-70B-Instruct-Turbo').
- Dynamic embedding model pricing (e.g., Qwen/Qwen3-Embedding-8B, text-embedding-3-small).
- Explicit unknown pricing notices (prevents misleading "$0.00 free" reporting when rates are unverified).
- Application-controlled registry versioning, audit metadata, and circuit-breaker fallbacks.
"""

import os
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple, Set
from dataclasses import dataclass, field

import litellm

litellm.suppress_debug_info = True
litellm.drop_params = True

logger = logging.getLogger(__name__)

# Default model and provider settings
DEFAULT_PROVIDER = "deepinfra"
DEFAULT_MODEL = "meta-llama/Llama-3.3-70B-Instruct-Turbo"
DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
DEFAULT_EMBEDDING_PRICE_PER_1M = 0.010

# Set of known provider prefixes for parsing provider-qualified model strings
KNOWN_PROVIDERS = {
    "deepinfra",
    "openai",
    "anthropic",
    "groq",
    "ollama",
    "azure",
    "bedrock",
    "together_ai",
    "together",
    "mistral",
    "cohere",
    "replicate",
    "vertex_ai",
    "gemini",
    "openrouter",
    "huggingface",
}

# Cache of unknown model warnings to prevent log flooding in production
_WARNED_UNKNOWN_MODELS: Set[Tuple[str, str]] = set()


@dataclass
class ModelPricingInfo:
    """
    Model pricing details returned by get_model_pricing.
    Supports 2-element tuple unpacking (input_price_per_1m, output_price_per_1m)
    for seamless backward compatibility.
    """
    provider: str
    model: str
    input_price_per_1m: Optional[float]
    output_price_per_1m: Optional[float]
    input_cost_per_token: Optional[float] = None
    output_cost_per_token: Optional[float] = None
    cached_price_per_1m: Optional[float] = None
    pricing_status: str = "known"  # "known" or "unknown"
    pricing_source: str = "unknown"
    is_pricing_available: bool = True
    pricing_notice: Optional[str] = None
    context_window: int = 32768
    litellm_provider: Optional[str] = None
    display_name: str = ""
    description: str = ""
    is_chat_model: bool = True

    @property
    def model_id(self) -> str:
        """Alias for model identifier."""
        return self.model

    def __iter__(self):
        """Allow backward compatible unpacking: inp_price, out_price = get_model_pricing(...)"""
        yield self.input_price_per_1m if self.input_price_per_1m is not None else 0.0
        yield self.output_price_per_1m if self.output_price_per_1m is not None else 0.0

    def __getitem__(self, idx: int):
        return [
            self.input_price_per_1m if self.input_price_per_1m is not None else 0.0,
            self.output_price_per_1m if self.output_price_per_1m is not None else 0.0,
        ][idx]

    def __len__(self) -> int:
        return 2


class TokenCost(float):
    """
    Float subclass representing token cost in USD with rich operational metadata.
    Behaves as a standard float for all arithmetic, comparisons, serialization, and round().
    """
    total_cost_usd: float
    input_cost_usd: float
    output_cost_usd: float
    embedding_cost_usd: float
    input_tokens: int
    output_tokens: int
    embedding_tokens: int
    total_tokens: int
    model: str
    provider: str
    task: str
    pricing_status: str
    is_pricing_available: bool
    pricing_notice: Optional[str]

    def __new__(
        cls,
        total_cost_usd: float,
        input_cost_usd: float = 0.0,
        output_cost_usd: float = 0.0,
        embedding_cost_usd: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        embedding_tokens: int = 0,
        total_tokens: int = 0,
        model: str = "",
        provider: str = DEFAULT_PROVIDER,
        task: str = "general",
        pricing_status: str = "known",
        is_pricing_available: bool = True,
        pricing_notice: Optional[str] = None,
    ):
        obj = super().__new__(cls, total_cost_usd)
        obj.total_cost_usd = total_cost_usd
        obj.input_cost_usd = input_cost_usd
        obj.output_cost_usd = output_cost_usd
        obj.embedding_cost_usd = embedding_cost_usd
        obj.input_tokens = input_tokens
        obj.output_tokens = output_tokens
        obj.embedding_tokens = embedding_tokens
        obj.total_tokens = total_tokens
        obj.model = model
        obj.provider = provider
        obj.task = task
        obj.pricing_status = pricing_status
        obj.is_pricing_available = is_pricing_available
        obj.pricing_notice = pricing_notice
        return obj


@dataclass
class TokenCostResult:
    """Detailed token cost calculation result schema."""
    provider: str
    model: str
    task: str
    input_tokens: int
    output_tokens: int
    embedding_tokens: int
    total_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    embedding_cost_usd: float
    total_cost_usd: float
    pricing_status: str
    is_pricing_available: bool = True
    pricing_notice: Optional[str] = None

    def __float__(self) -> float:
        return float(self.total_cost_usd)

    def __round__(self, ndigits: int = 6) -> float:
        return round(self.total_cost_usd, ndigits)


# Curated catalog of standard models for UI model selection / catalog endpoints
CURATED_CHAT_MODELS: List[Dict[str, Any]] = [
    {
        "model_id": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "display_name": "Llama 3.3 70B Instruct Turbo",
        "provider": "deepinfra",
        "context_window": 128000,
        "description": "High accuracy 70B parameter model with 128k context window.",
    },
    {
        "model_id": "deepseek-ai/DeepSeek-V3",
        "display_name": "DeepSeek V3",
        "provider": "deepinfra",
        "context_window": 64000,
        "description": "Flagship DeepSeek 671B MoE model for complex reasoning and synthesis.",
    },
    {
        "model_id": "deepseek-ai/DeepSeek-R1",
        "display_name": "DeepSeek R1 (Reasoning)",
        "provider": "deepinfra",
        "context_window": 64000,
        "description": "Deep reasoning model with step-by-step verification.",
    },
    {
        "model_id": "meta-llama/Meta-Llama-3.1-70B-Instruct",
        "display_name": "Meta Llama 3.1 70B Instruct",
        "provider": "deepinfra",
        "context_window": 128000,
        "description": "Balanced enterprise-grade model with 128k context.",
    },
    {
        "model_id": "meta-llama/Meta-Llama-3.1-8B-Instruct",
        "display_name": "Meta Llama 3.1 8B Instruct",
        "provider": "deepinfra",
        "context_window": 128000,
        "description": "Fast lightweight model for low-latency tasks.",
    },
    {
        "model_id": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        "display_name": "Meta Llama 3.1 8B Instruct Turbo",
        "provider": "deepinfra",
        "context_window": 128000,
        "description": "Turbo low-latency 8B model for routing, summarization, and metadata.",
    },
    {
        "model_id": "Qwen/Qwen2.5-72B-Instruct",
        "display_name": "Qwen 2.5 72B Instruct",
        "provider": "deepinfra",
        "context_window": 32768,
        "description": "High-performing multilingual reasoning and coding model.",
    },
    {
        "model_id": "Qwen/Qwen2.5-Coder-32B-Instruct",
        "display_name": "Qwen 2.5 Coder 32B Instruct",
        "provider": "deepinfra",
        "context_window": 32768,
        "description": "Specialized model for code generation and analysis.",
    },
    {
        "model_id": "microsoft/WizardLM-2-8x22B",
        "display_name": "WizardLM 2 8x22B",
        "provider": "deepinfra",
        "context_window": 64000,
        "description": "Microsoft WizardLM mixture of experts model.",
    },
    {
        "model_id": "google/gemma-2-27b-it",
        "display_name": "Google Gemma 2 27B IT",
        "provider": "deepinfra",
        "context_window": 8192,
        "description": "Google lightweight high-efficiency instruction tuned model.",
    },
    {
        "model_id": "gpt-4o",
        "display_name": "GPT-4o (Omni)",
        "provider": "openai",
        "context_window": 128000,
        "description": "OpenAI flagship high-intelligence model.",
    },
    {
        "model_id": "gpt-4o-mini",
        "display_name": "GPT-4o Mini",
        "provider": "openai",
        "context_window": 128000,
        "description": "OpenAI fast and cost-effective small model.",
    },
    {
        "model_id": "claude-3-7-sonnet-20250219",
        "display_name": "Claude 3.7 Sonnet",
        "provider": "anthropic",
        "context_window": 200000,
        "description": "Anthropic hybrid reasoning model with 200k context.",
    },
    {
        "model_id": "claude-3-5-haiku-20241022",
        "display_name": "Claude 3.5 Haiku",
        "provider": "anthropic",
        "context_window": 200000,
        "description": "Anthropic fastest and most cost-efficient Claude model.",
    },
    {
        "model_id": "llama-3.3-70b-versatile",
        "display_name": "Llama 3.3 70B Versatile (Groq)",
        "provider": "groq",
        "context_window": 128000,
        "description": "Ultra-fast inference on Groq LPU engine.",
    },
    {
        "model_id": "llama3",
        "display_name": "Llama 3 (Local Ollama)",
        "provider": "ollama",
        "context_window": 8192,
        "description": "Self-hosted local Ollama model ($0.00 API cost).",
    },
]


def resolve_model_and_provider(
    model_name: Optional[str] = None,
    provider: Optional[str] = None
) -> Tuple[str, str]:
    """
    Normalize model name and extract provider from provider-qualified names or explicit arguments.
    """
    raw_model = (model_name or DEFAULT_MODEL).strip()
    if not raw_model or raw_model.lower() == "default":
        raw_model = DEFAULT_MODEL

    clean_provider = provider.strip().lower() if provider and provider.strip() else None
    clean_model = raw_model

    # Check for prefix syntax e.g. "openai/gpt-4o", "anthropic/claude-3-5-sonnet-20241022", "groq/llama-3.3-70b-versatile"
    if "/" in clean_model:
        parts = clean_model.split("/", 1)
        prefix_candidate = parts[0].lower()
        if prefix_candidate in KNOWN_PROVIDERS:
            if not clean_provider:
                clean_provider = prefix_candidate
            clean_model = parts[1]

    # Check for dot syntax e.g. "anthropic.claude-3-5-sonnet-20241022"
    if not clean_provider and "." in clean_model:
        prefix_candidate = clean_model.split(".", 1)[0].lower()
        if prefix_candidate in KNOWN_PROVIDERS:
            clean_provider = prefix_candidate
            clean_model = clean_model.split(".", 1)[1]

    # Default provider heuristics
    if not clean_provider:
        if clean_model.startswith(("gpt-", "o1", "o3", "text-embedding-", "dall-e")):
            clean_provider = "openai"
        elif clean_model.startswith(("claude-",)):
            clean_provider = "anthropic"
        elif clean_model.startswith(("gemini-",)):
            clean_provider = "gemini"
        else:
            clean_provider = DEFAULT_PROVIDER

    return clean_model, clean_provider


def _warn_unknown_model_once(clean_model: str, clean_provider: str) -> None:
    """Log a missing pricing metadata warning once per model/provider to prevent log spam."""
    key = (clean_provider, clean_model)
    if key not in _WARNED_UNKNOWN_MODELS:
        _WARNED_UNKNOWN_MODELS.add(key)
        logger.warning(
            f"[PRICING_REGISTRY] Missing pricing metadata in LiteLLM registry for provider='{clean_provider}', model='{clean_model}'. "
            f"Calculated cost will default to $0.00 with pricing_status='unknown' (unverified)."
        )


# ============================================================================
# APPLICATION-LEVEL PRICING REGISTRY (GraphMind Controlled Source of Truth)
# ============================================================================

class GraphMindPricingRegistry:
    """
    Application-controlled pricing registry that layers:
    1. GraphMind custom overrides
    2. Validated remote LiteLLM master sync data
    3. Built-in LiteLLM model cost registry
    
    Provides metadata tracking (version, sync timestamp, source, model count)
    and zero-latency in-memory lookups.
    """

    def __init__(self):
        self._custom_overrides: Dict[str, Any] = {}
        self._remote_registry: Dict[str, Any] = {}
        self._load_yaml_overrides()
        self._sync_metadata: Dict[str, Any] = {
            "version": "1.0.0",
            "last_synced_at": None,
            "sync_source": "models_yaml_and_litellm",
            "sync_status": "initialized",
            "total_models": len(litellm.model_cost) + len(self._custom_overrides),
        }

    def _load_yaml_overrides(self) -> None:
        """Load static model pricing definitions from app/core/multi_llm/config/models.yaml."""
        import pathlib
        import yaml

        # Path relative to this file: ../multi_llm/config/models.yaml
        yaml_path = pathlib.Path(__file__).resolve().parent.parent / "multi_llm" / "config" / "models.yaml"
        if not yaml_path.exists():
            # Fallback to workspace root relative path
            yaml_path = pathlib.Path("app/core/multi_llm/config/models.yaml").resolve()

        if yaml_path.exists():
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                pricing_sec = data.get("pricing", {})
                for provider, models in pricing_sec.items():
                    clean_prov = str(provider).strip().lower()
                    for m_name, p_data in models.items():
                        if not isinstance(p_data, dict):
                            continue
                        in_cost = float(p_data.get("input_per_1m", 0.0)) / 1_000_000.0
                        out_cost = float(p_data.get("output_per_1m", 0.0)) / 1_000_000.0
                        cached_cost = (
                            float(p_data.get("cached_per_1m", 0.0)) / 1_000_000.0
                            if "cached_per_1m" in p_data and p_data["cached_per_1m"] is not None
                            else None
                        )
                        entry = {
                            "input_cost_per_token": in_cost,
                            "output_cost_per_token": out_cost,
                            "cache_read_input_token_cost": cached_cost,
                            "litellm_provider": clean_prov,
                            "pricing_status": "known",
                            "is_pricing_available": True,
                            "max_tokens": 131072,
                        }

                        # Generate all lookup alias keys for robust resolution
                        keys = [
                            m_name,
                            f"{clean_prov}/{m_name}",
                            m_name.lower(),
                            f"{clean_prov}/{m_name.lower()}",
                        ]
                        if "Llama-" in m_name:
                            meta_var = m_name.replace("Llama-", "Meta-Llama-")
                            keys.extend([meta_var, f"{clean_prov}/{meta_var}", meta_var.lower(), f"{clean_prov}/{meta_var.lower()}"])
                        elif "Meta-Llama-" in m_name:
                            plain_var = m_name.replace("Meta-Llama-", "Llama-")
                            keys.extend([plain_var, f"{clean_prov}/{plain_var}", plain_var.lower(), f"{clean_prov}/{plain_var.lower()}"])

                        if "gpt-oss-" in m_name:
                            plain_oss = m_name.replace("deepinfra/gpt-oss-", "gpt-oss-").replace("openai/gpt-oss-", "gpt-oss-")
                            openai_oss = f"openai/{plain_oss}"
                            deepinfra_oss = f"deepinfra/{plain_oss}"
                            keys.extend([plain_oss, openai_oss, deepinfra_oss, f"{clean_prov}/{openai_oss}"])

                        if "DeepSeek-V3.2" in m_name:
                            hyphen_var = m_name.replace("DeepSeek-V3.2", "DeepSeek-V3-2")
                            keys.extend([hyphen_var, f"{clean_prov}/{hyphen_var}", hyphen_var.lower(), f"{clean_prov}/{hyphen_var.lower()}"])
                        elif "DeepSeek-V3-2" in m_name:
                            dot_var = m_name.replace("DeepSeek-V3-2", "DeepSeek-V3.2")
                            keys.extend([dot_var, f"{clean_prov}/{dot_var}", dot_var.lower(), f"{clean_prov}/{dot_var.lower()}"])

                        for k in keys:
                            self._custom_overrides[k] = entry
                litellm.model_cost.update(self._custom_overrides)
                logger.info(f"[PRICING_REGISTRY] Loaded {len(self._custom_overrides)} model pricing overrides from models.yaml into LiteLLM model_cost")
            except Exception as exc:
                logger.warning(f"[PRICING_REGISTRY] Failed to load models.yaml: {exc}")

    @property
    def metadata(self) -> Dict[str, Any]:
        """Return registry governance and audit metadata."""
        meta = dict(self._sync_metadata)
        meta["total_models"] = len(litellm.model_cost)
        return meta

    def set_custom_override(self, key: str, pricing_dict: Dict[str, Any]) -> None:
        """Register an application-specific custom model pricing override."""
        self._custom_overrides[key] = pricing_dict
        litellm.model_cost[key] = pricing_dict
        _RESOLVED_PRICING_CACHE.clear()

    def lookup_raw(self, clean_model: str, clean_provider: str) -> Optional[Dict[str, Any]]:
        """
        O(1) tiered in-memory lookup across:
        1. Custom overrides
        2. Remote registry overlay
        3. Built-in LiteLLM model cost
        """
        # Local / Ollama models have zero API cost
        if clean_provider == "ollama":
            return {
                "input_cost_per_token": 0.0,
                "output_cost_per_token": 0.0,
                "max_tokens": 131072,
                "litellm_provider": "ollama",
                "pricing_status": "known",
            }

        # Candidate keys in registry
        candidates = [
            f"{clean_provider}/{clean_model}",
            clean_model,
            f"{clean_provider}/{clean_model.lower()}",
            clean_model.lower(),
        ]

        if clean_provider == "deepinfra":
            candidates.extend([
                f"deepinfra/meta-llama/{clean_model}",
                f"deepinfra/deepseek-ai/{clean_model}",
                f"deepinfra/Qwen/{clean_model}",
                f"deepinfra/google/{clean_model}",
                f"deepinfra/openai/{clean_model}",
                f"deepinfra/mistralai/{clean_model}",
                f"deepinfra/BAAI/{clean_model}",
            ])
        elif clean_provider == "anthropic":
            candidates.extend([
                f"anthropic.{clean_model}",
                f"anthropic/{clean_model}",
            ])
            for k in litellm.model_cost:
                if clean_model in k and ("anthropic." in k or k.startswith("claude")):
                    candidates.append(k)

        # 1. Check remote validated registry (LiteLLM synced master) - FIRST PRIORITY
        for candidate in candidates:
            if candidate in self._remote_registry:
                entry = self._remote_registry[candidate]
                if entry.get("input_cost_per_token") is not None or entry.get("output_cost_per_token") is not None:
                    info = dict(entry)
                    info["matched_key"] = candidate
                    info["pricing_source"] = "remote_master_registry"
                    return info

        # 2. Check LiteLLM in-memory registry - FIRST PRIORITY
        for candidate in candidates:
            if candidate in litellm.model_cost:
                entry = litellm.model_cost[candidate]
                if entry.get("input_cost_per_token") is not None or entry.get("output_cost_per_token") is not None:
                    info = dict(entry)
                    info["matched_key"] = candidate
                    info["pricing_source"] = "litellm_built_in"
                    return info

        # 3. Check litellm.get_model_info helper
        try:
            info = litellm.get_model_info(model=clean_model, custom_llm_provider=clean_provider)
            if info and (info.get("input_cost_per_token") is not None or info.get("output_cost_per_token") is not None):
                info["pricing_source"] = "litellm_model_info"
                return info
        except Exception:
            pass

        try:
            info = litellm.get_model_info(model=f"{clean_provider}/{clean_model}")
            if info and (info.get("input_cost_per_token") is not None or info.get("output_cost_per_token") is not None):
                info["pricing_source"] = "litellm_model_info_qualified"
                return info
        except Exception:
            pass

        # 4. Fallback to custom overrides (models.yaml) when LiteLLM does not have the model
        for candidate in candidates:
            if candidate in self._custom_overrides:
                info = dict(self._custom_overrides[candidate])
                info["matched_key"] = candidate
                info["pricing_source"] = "graphmind_models_yaml_fallback"
                return info

        return None

    def apply_remote_sync(self, remote_data: Dict[str, Any], source_url: str) -> None:
        """Apply and activate validated remote pricing data."""
        self._remote_registry.update(remote_data)
        litellm.model_cost.update(remote_data)
        self._sync_metadata = {
            "version": "1.1.0",
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
            "sync_source": source_url,
            "sync_status": "success",
            "total_models": len(litellm.model_cost),
        }
        _RESOLVED_PRICING_CACHE.clear()


# Global Singleton Registry Instance
PRICING_REGISTRY = GraphMindPricingRegistry()
_RESOLVED_PRICING_CACHE: Dict[Tuple[str, str], ModelPricingInfo] = {}


def get_model_pricing(
    model_name: Optional[str] = None,
    provider: Optional[str] = None
) -> ModelPricingInfo:
    """
    Get pricing information for a given model from GraphMind's pricing registry in O(1) time.
    
    Supports tuple unpacking:
        inp_price_per_1m, out_price_per_1m = get_model_pricing(model_name)
    
    Returns ModelPricingInfo with pricing_status='known' or 'unknown',
    is_pricing_available (bool), and explicit pricing_notice when unverified.
    """
    clean_model, clean_provider = resolve_model_and_provider(model_name, provider)
    cache_key = (clean_provider, clean_model)
    if cache_key in _RESOLVED_PRICING_CACHE:
        return _RESOLVED_PRICING_CACHE[cache_key]

    raw_info = PRICING_REGISTRY.lookup_raw(clean_model, clean_provider)

    if raw_info is not None:
        in_token = raw_info.get("input_cost_per_token")
        out_token = raw_info.get("output_cost_per_token")
        cached_token = raw_info.get("cache_read_input_token_cost")
        ctx_win = raw_info.get("max_tokens") or raw_info.get("max_input_tokens") or 32768
        litellm_prov = raw_info.get("litellm_provider") or clean_provider

        in_1m = round(float(in_token) * 1_000_000.0, 6) if in_token is not None else 0.0
        out_1m = round(float(out_token) * 1_000_000.0, 6) if out_token is not None else 0.0
        cached_1m = round(float(cached_token) * 1_000_000.0, 6) if cached_token is not None else None

        info = ModelPricingInfo(
            provider=clean_provider,
            model=clean_model,
            input_price_per_1m=in_1m,
            output_price_per_1m=out_1m,
            input_cost_per_token=in_token,
            output_cost_per_token=out_token,
            cached_price_per_1m=cached_1m,
            pricing_status="known",
            pricing_source=raw_info.get("pricing_source", "litellm"),
            is_pricing_available=True,
            pricing_notice=None,
            context_window=ctx_win,
            litellm_provider=litellm_prov,
            display_name=clean_model,
        )
        _RESOLVED_PRICING_CACHE[cache_key] = info
        return info

    # Unknown model handling: log warning, mark unknown with explicit unverified notice
    _warn_unknown_model_once(clean_model, clean_provider)
    unknown_info = ModelPricingInfo(
        provider=clean_provider,
        model=clean_model,
        input_price_per_1m=None,
        output_price_per_1m=None,
        input_cost_per_token=None,
        output_cost_per_token=None,
        cached_price_per_1m=None,
        pricing_status="unknown",
        is_pricing_available=False,
        pricing_notice="Pricing unavailable in registry; cost reported as $0.00 (unverified)",
        context_window=32768,
        litellm_provider=None,
        display_name=clean_model,
    )
    _RESOLVED_PRICING_CACHE[cache_key] = unknown_info
    return unknown_info


def calculate_token_cost(
    model_name: Optional[str] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    embedding_tokens: int = 0,
    embedding_price_per_1m: Optional[float] = None,
    embedding_model: Optional[str] = None,
    provider: Optional[str] = None,
    task: Optional[str] = "general",
) -> TokenCost:
    """
    Calculate the total USD token cost for an LLM operation in O(1) time using LiteLLM pricing.
    
    Dynamically supports model-specific embedding pricing when embedding_model is specified.
    
    Returns TokenCost (subclass of float), providing both standard float arithmetic
    and rich metadata properties (total_cost_usd, input_cost_usd, output_cost_usd, pricing_status, task, provider, pricing_notice).
    """
    clean_model, clean_provider = resolve_model_and_provider(model_name, provider)
    pricing = get_model_pricing(clean_model, clean_provider)

    inp_tok = max(0, input_tokens)
    out_tok = max(0, output_tokens)
    emb_tok = max(0, embedding_tokens)
    tot_tok = inp_tok + out_tok + emb_tok

    if pricing.pricing_status == "known":
        inp_cost = (inp_tok / 1_000_000.0) * (pricing.input_price_per_1m or 0.0)
        out_cost = (out_tok / 1_000_000.0) * (pricing.output_price_per_1m or 0.0)
    else:
        inp_cost = 0.0
        out_cost = 0.0

    # Resolve dynamic embedding pricing if embedding tokens are present
    if emb_tok > 0:
        if embedding_price_per_1m is not None:
            resolved_emb_price = embedding_price_per_1m
        elif embedding_model:
            emb_info = get_model_pricing(embedding_model, clean_provider)
            resolved_emb_price = emb_info.input_price_per_1m if emb_info.input_price_per_1m is not None else DEFAULT_EMBEDDING_PRICE_PER_1M
        else:
            resolved_emb_price = DEFAULT_EMBEDDING_PRICE_PER_1M
        emb_cost = (emb_tok / 1_000_000.0) * resolved_emb_price
    else:
        emb_cost = 0.0

    total_cost = round(inp_cost + out_cost + emb_cost, 6)

    return TokenCost(
        total_cost_usd=total_cost,
        input_cost_usd=round(inp_cost, 6),
        output_cost_usd=round(out_cost, 6),
        embedding_cost_usd=round(emb_cost, 6),
        input_tokens=inp_tok,
        output_tokens=out_tok,
        embedding_tokens=emb_tok,
        total_tokens=tot_tok,
        model=clean_model,
        provider=clean_provider,
        task=task or "general",
        pricing_status=pricing.pricing_status,
        is_pricing_available=pricing.is_pricing_available,
        pricing_notice=pricing.pricing_notice,
    )


def calculate_token_cost_details(
    model_name: Optional[str] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    embedding_tokens: int = 0,
    embedding_price_per_1m: Optional[float] = None,
    embedding_model: Optional[str] = None,
    provider: Optional[str] = None,
    task: Optional[str] = "general",
) -> TokenCostResult:
    """Detailed token cost calculation returning a structured TokenCostResult dataclass."""
    cost = calculate_token_cost(
        model_name=model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        embedding_tokens=embedding_tokens,
        embedding_price_per_1m=embedding_price_per_1m,
        embedding_model=embedding_model,
        provider=provider,
        task=task,
    )
    return TokenCostResult(
        provider=cost.provider,
        model=cost.model,
        task=cost.task,
        input_tokens=cost.input_tokens,
        output_tokens=cost.output_tokens,
        embedding_tokens=cost.embedding_tokens,
        total_tokens=cost.total_tokens,
        input_cost_usd=cost.input_cost_usd,
        output_cost_usd=cost.output_cost_usd,
        embedding_cost_usd=cost.embedding_cost_usd,
        total_cost_usd=cost.total_cost_usd,
        pricing_status=cost.pricing_status,
        is_pricing_available=cost.is_pricing_available,
        pricing_notice=cost.pricing_notice,
    )


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    embedding_tokens: int = 0,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    task: Optional[str] = "general",
    embedding_model: Optional[str] = None,
) -> TokenCost:
    """Convenience wrapper for request cost calculation."""
    return calculate_token_cost(
        model_name=model,
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        embedding_tokens=embedding_tokens,
        embedding_model=embedding_model,
        provider=provider,
        task=task,
    )


def get_available_chat_models(
    default_model: Optional[str] = None,
    provider: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Return available chat models with live LiteLLM-backed pricing for UI catalog and preference configuration.
    """
    active_default = default_model or os.getenv("MODEL_ANSWER", DEFAULT_MODEL)
    models_list = []

    for item in CURATED_CHAT_MODELS:
        m_id = item["model_id"]
        m_prov = item.get("provider", provider or DEFAULT_PROVIDER)
        pricing = get_model_pricing(m_id, m_prov)

        models_list.append({
            "model_id": m_id,
            "display_name": item.get("display_name", m_id),
            "provider": m_prov,
            "input_price_per_1m": pricing.input_price_per_1m if pricing.input_price_per_1m is not None else 0.0,
            "output_price_per_1m": pricing.output_price_per_1m if pricing.output_price_per_1m is not None else 0.0,
            "context_window": pricing.context_window or item.get("context_window", 32768),
            "description": item.get("description", ""),
            "is_default": (m_id == active_default or f"{m_prov}/{m_id}" == active_default),
            "pricing_status": pricing.pricing_status,
            "is_pricing_available": pricing.is_pricing_available,
        })

    return models_list


# Dynamic Supported Models Mapping for backward compatibility
class _SupportedModelsDict(dict):
    """Dict proxy that dynamically queries LiteLLM for any requested model."""
    def __getitem__(self, key: str) -> ModelPricingInfo:
        return get_model_pricing(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return get_model_pricing(key)
        except Exception:
            return default

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        clean_model, clean_prov = resolve_model_and_provider(key)
        return PRICING_REGISTRY.lookup_raw(clean_model, clean_prov) is not None


SUPPORTED_MODELS = _SupportedModelsDict()
MODEL_PRICING = SUPPORTED_MODELS

# Remote master pricing registry constants and sync engine
LITELLM_REMOTE_PRICING_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"


def validate_pricing_payload(data: Any) -> bool:
    """Validate remote pricing dictionary format and ensure valid model definitions exist."""
    if not isinstance(data, dict) or len(data) < 100:
        return False
    # Validate structure across a sample of entries
    valid_entries = 0
    for _, val in list(data.items())[:20]:
        if isinstance(val, dict) and ("input_cost_per_token" in val or "max_tokens" in val or "litellm_provider" in val):
            valid_entries += 1
    return valid_entries > 0


async def reload_litellm_pricing_registry(remote_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Safely download, validate, and apply updated pricing to GraphMind's pricing registry.
    Invalidates the internal resolved pricing cache on success.
    Falls back cleanly to the existing in-memory registry on network or validation errors.
    """
    url = remote_url or LITELLM_REMOTE_PRICING_URL
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                remote_data = resp.json()
                if validate_pricing_payload(remote_data):
                    PRICING_REGISTRY.apply_remote_sync(remote_data, source_url=url)
                    logger.info(f"[PRICING_REGISTRY] Successfully reloaded {len(remote_data)} models into GraphMind pricing registry.")
                    return {
                        "status": "success",
                        "source": "remote_registry",
                        "models_loaded": len(litellm.model_cost),
                        "registry_metadata": PRICING_REGISTRY.metadata,
                        "message": f"Successfully updated and validated {len(remote_data)} model price definitions from remote registry.",
                    }
                else:
                    logger.warning("[PRICING_REGISTRY] Remote pricing payload failed validation. Retaining current in-memory registry.")
                    return {
                        "status": "fallback_retained",
                        "source": "in_memory_registry",
                        "models_loaded": len(litellm.model_cost),
                        "registry_metadata": PRICING_REGISTRY.metadata,
                        "message": "Remote pricing data failed schema validation. In-memory registry retained.",
                    }
            else:
                logger.warning(f"[PRICING_REGISTRY] Remote registry returned HTTP {resp.status_code}. Retaining in-memory registry.")
                return {
                    "status": "fallback_retained",
                    "source": "in_memory_registry",
                    "models_loaded": len(litellm.model_cost),
                    "registry_metadata": PRICING_REGISTRY.metadata,
                    "message": f"Remote registry returned HTTP status {resp.status_code}. In-memory registry retained.",
                }
    except Exception as exc:
        logger.warning(f"[PRICING_REGISTRY] Remote sync failed ({exc}). Retaining in-memory registry.")
        return {
            "status": "fallback_retained",
            "source": "in_memory_registry",
            "models_loaded": len(litellm.model_cost),
            "registry_metadata": PRICING_REGISTRY.metadata,
            "message": f"Remote sync encountered an error: {str(exc)}. In-memory registry retained.",
        }


# ============================================================================
# SCHEDULED DAILY SYNC WORKER (24-Hour Interval)
# ============================================================================

_DAILY_SYNC_TASK: Optional[asyncio.Task] = None


async def _daily_pricing_sync_loop(interval_seconds: int = 86400):
    """
    Background worker loop running once daily (every 24 hours)
    to keep LiteLLM master pricing synced without manual intervention.
    """
    # 1. Initial sync on boot
    try:
        await reload_litellm_pricing_registry()
    except Exception as exc:
        logger.warning(f"[PRICING_REGISTRY] Initial startup pricing sync failed: {exc}")

    # 2. Recurring 24-hour sync loop
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            logger.info("[PRICING_REGISTRY] Starting scheduled daily LiteLLM pricing sync...")
            res = await reload_litellm_pricing_registry()
            logger.info(
                f"[PRICING_REGISTRY] Scheduled daily sync completed: status='{res.get('status')}', "
                f"models_loaded={res.get('models_loaded')}"
            )
        except asyncio.CancelledError:
            logger.info("[PRICING_REGISTRY] Daily pricing sync task cancelled.")
            break
        except Exception as exc:
            logger.warning(f"[PRICING_REGISTRY] Scheduled daily pricing sync error: {exc}")


def start_daily_pricing_sync_worker(interval_seconds: int = 86400) -> Optional[asyncio.Task]:
    """Start the recurring daily pricing synchronization background task."""
    global _DAILY_SYNC_TASK
    if _DAILY_SYNC_TASK is None or _DAILY_SYNC_TASK.done():
        try:
            loop = asyncio.get_running_loop()
            _DAILY_SYNC_TASK = loop.create_task(_daily_pricing_sync_loop(interval_seconds=interval_seconds))
            logger.info("[PRICING_REGISTRY] Recurring daily LiteLLM pricing sync worker started (24-hour interval).")
            return _DAILY_SYNC_TASK
        except RuntimeError:
            logger.warning("[PRICING_REGISTRY] No running event loop to start daily pricing sync worker.")
    return _DAILY_SYNC_TASK


def stop_daily_pricing_sync_worker() -> None:
    """Cancel the recurring daily pricing synchronization background task."""
    global _DAILY_SYNC_TASK
    if _DAILY_SYNC_TASK and not _DAILY_SYNC_TASK.done():
        _DAILY_SYNC_TASK.cancel()
        _DAILY_SYNC_TASK = None
        logger.info("[PRICING_REGISTRY] Daily pricing sync worker stopped.")

