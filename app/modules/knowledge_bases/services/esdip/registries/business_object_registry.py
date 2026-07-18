from typing import List
from ..domain.business_object import BusinessObject

class BusinessObjectRegistry:
    """Stores references to business objects to avoid massive memory duplication."""
    def __init__(self):
        self._objects: List[BusinessObject] = []
        
    def add(self, obj: BusinessObject):
        self._objects.append(obj)
        
    def get_all(self) -> List[BusinessObject]:
        return self._objects
