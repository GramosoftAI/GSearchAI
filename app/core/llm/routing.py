from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Tuple
import time
import logging
import uuid
import asyncio

logger = logging.getLogger(__name__)

# =========================================================================
# CAPABILITY REGISTRY
# =========================================================================

@dataclass
class ModelCapabilities:
    supports_reasoning: bool = False
    supports_streaming: bool = True
    supports_json_mode: bool = False
    supports_tools: bool = False
    supports_vision: bool = False
    context_window: int = 8192

class CapabilityRegistry:
    """
    Maintains capabilities and pricing for models to abstract provider-specific details.
    """
    _capabilities: Dict[str, ModelCapabilities] = {
        # DeepSeek
        "deepseek-ai/DeepSeek-V3": ModelCapabilities(supports_reasoning=False, supports_streaming=True, supports_json_mode=True, context_window=64000),
        "deepseek-ai/DeepSeek-R1": ModelCapabilities(supports_reasoning=True, supports_streaming=True, supports_json_mode=False, context_window=64000),
        
        # Meta Llama 3.1
        "meta-llama/Meta-Llama-3.1-8B-Instruct": ModelCapabilities(supports_reasoning=False, supports_streaming=True, supports_json_mode=True, context_window=128000),
        "meta-llama/Meta-Llama-3.1-70B-Instruct": ModelCapabilities(supports_reasoning=False, supports_streaming=True, supports_json_mode=True, context_window=128000),
        
        # Meta Llama 3.3
        "meta-llama/Llama-3.3-70B-Instruct": ModelCapabilities(supports_reasoning=False, supports_streaming=True, supports_json_mode=True, context_window=128000),
        
        # Qwen
        "Qwen/Qwen2.5-72B-Instruct": ModelCapabilities(supports_reasoning=False, supports_streaming=True, supports_json_mode=True, context_window=32000),
        
        # Vision
        "meta-llama/Llama-3.2-11B-Vision-Instruct": ModelCapabilities(supports_reasoning=False, supports_streaming=True, supports_vision=True, context_window=128000),
    }

    _pricing: Dict[str, Tuple[float, float]] = {
        # Format: (input_cost_per_1M, output_cost_per_1M) in USD
        "deepseek-ai/DeepSeek-V3": (0.14, 0.28),
        "deepseek-ai/DeepSeek-R1": (0.55, 2.19),
        "meta-llama/Meta-Llama-3.1-8B-Instruct": (0.04, 0.04),
        "meta-llama/Meta-Llama-3.1-70B-Instruct": (0.23, 0.40),
        "meta-llama/Llama-3.3-70B-Instruct": (0.23, 0.40),
        "meta-llama/Llama-3.2-11B-Vision-Instruct": (0.05, 0.05),
        "Qwen/Qwen2.5-72B-Instruct": (0.23, 0.40),
    }

    @classmethod
    def get_capabilities(cls, model_name: str) -> ModelCapabilities:
        # Fallback for unknown models
        return cls._capabilities.get(model_name, ModelCapabilities())
        
    @classmethod
    def estimate_cost(cls, model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
        input_price, output_price = cls._pricing.get(model_name, (0.0, 0.0))
        return (prompt_tokens / 1_000_000 * input_price) + (completion_tokens / 1_000_000 * output_price)


# =========================================================================
# TASK CONFIGURATION
# =========================================================================

class LLMTask(Enum):
    INTENT_DETECTION = "intent_detection"
    ROUTER = "router"
    CYPHER_GENERATION = "cypher_generation"
    ANSWER_GENERATION = "answer_generation"
    EXTRACTION = "extraction"
    VISION = "vision"
    MEMORY = "memory"
    RERANKER = "reranker"
    CUSTOM = "custom" # For backward compatible dynamic calls

@dataclass
class LLMTaskConfig:
    model: str
    timeout: float
    temperature: float
    max_tokens: int
    stream: bool = False
    retries: int = 3


# =========================================================================
# TELEMETRY
# =========================================================================

@dataclass
class LLMTelemetry:
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task: str = "UNKNOWN"
    provider: str = "UNKNOWN"
    model: str = "UNKNOWN"
    latency_sec: float = 0.0
    retries: int = 0
    http_status: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost: float = 0.0
    error_category: Optional[str] = None
    success: bool = False
    
    def log(self):
        token_str = f"In:{self.prompt_tokens} Out:{self.completion_tokens}"
        status = "SUCCESS" if self.success else f"FAILED({self.error_category})"
        
        logger.info(
            f"[{self.request_id}] Task={self.task} Provider={self.provider} "
            f"Model={self.model} Latency={self.latency_sec:.2f}s Retries={self.retries} "
            f"Tokens=[{token_str}] Cost=${self.estimated_cost:.6f} Status={status}"
        )


# =========================================================================
# CIRCUIT BREAKER
# =========================================================================

class CircuitState(Enum):
    CLOSED = "CLOSED"      # Normal operation
    OPEN = "OPEN"          # Failing, block traffic
    HALF_OPEN = "HALF_OPEN"# Testing recovery

class CircuitBreaker:
    """
    Prevents cascading failures when a provider goes down.
    """
    def __init__(self, failure_threshold: int = 5, recovery_timeout_sec: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout_sec = recovery_timeout_sec
        
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.last_failure_time = 0.0
        
    def record_success(self):
        if self.state == CircuitState.HALF_OPEN:
            logger.info("CircuitBreaker: Provider recovered. Circuit CLOSED.")
            self.state = CircuitState.CLOSED
        self.failures = 0
            
    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        
        if self.state == CircuitState.CLOSED and self.failures >= self.failure_threshold:
            logger.error(f"CircuitBreaker: Provider failed {self.failures} times. Circuit OPEN.")
            self.state = CircuitState.OPEN
            
    def can_execute(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
            
        if self.state == CircuitState.OPEN:
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.recovery_timeout_sec:
                logger.info("CircuitBreaker: Recovery timeout reached. Circuit HALF_OPEN (Testing).")
                self.state = CircuitState.HALF_OPEN
                return True
            return False
            
        # HALF_OPEN allows exactly ONE request through to test
        # Further requests are blocked until this one succeeds or fails
        return True
