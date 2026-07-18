class ProviderError(Exception):
    """Base class for all provider-related errors."""
    def __init__(self, message: str, provider: str = "unknown"):
        self.provider = provider
        super().__init__(f"[{provider}] {message}")

class ProviderTimeoutError(ProviderError):
    """Raised when a provider request times out."""
    pass

class ProviderUnavailableError(ProviderError):
    """Raised when a provider is unreachable or returns a 5xx error."""
    pass

class ProviderAuthError(ProviderError):
    """Raised when a provider returns a 401 or 403 error."""
    pass

class CapabilityNotSupportedError(ProviderError):
    """Raised when a provider is asked to perform an operation it doesn't support."""
    pass

class AllProvidersFailedError(Exception):
    """Raised when all providers in a fallback chain fail."""
    def __init__(self, task_type: str, steps: list, last_err: Exception | None = None):
        self.task_type = task_type
        self.steps = steps
        self.last_err = last_err
        super().__init__(f"All providers failed for task '{task_type}'. Steps: {steps}. Last error: {last_err}")
