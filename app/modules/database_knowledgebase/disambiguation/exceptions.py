from typing import List, Dict, Any, Optional

class DisambiguationRequiredError(Exception):
    """
    Raised when a user query contains an ambiguous entity that needs 
    to be resolved by the user before SQL generation can proceed.
    """
    def __init__(
        self,
        message: str,
        options: List[Dict[str, Any]],
        entity_type: str = "user",
        candidate_tables: Optional[List[Dict[str, Any]]] = None,
        all_tables: Optional[List[str]] = None,
        table_aliases: Optional[Dict[str, List[str]]] = None,
    ):
        self.message = message
        self.options = options
        self.entity_type = entity_type
        self.candidate_tables = candidate_tables or []
        self.all_tables = all_tables or []
        self.table_aliases = table_aliases or {}
        super().__init__(self.message)

