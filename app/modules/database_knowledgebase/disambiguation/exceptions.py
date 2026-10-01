from typing import List, Dict, Any

class DisambiguationRequiredError(Exception):
    """
    Raised when a user query contains an ambiguous entity that needs 
    to be resolved by the user before SQL generation can proceed.
    """
    def __init__(self, message: str, options: List[Dict[str, Any]], entity_type: str = "user"):
        self.message = message
        self.options = options
        self.entity_type = entity_type
        super().__init__(self.message)
