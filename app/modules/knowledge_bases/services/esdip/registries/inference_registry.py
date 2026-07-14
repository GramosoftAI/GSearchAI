from typing import List, Any

class InferenceRegistry:
    """Scalable registry for relationship detectors, classifiers, validators, and scorers."""
    def __init__(self):
        self._plugins: List[Any] = []
        
    def register(self, plugin: Any):
        self._plugins.append(plugin)
        
    def get_all(self) -> List[Any]:
        return self._plugins
