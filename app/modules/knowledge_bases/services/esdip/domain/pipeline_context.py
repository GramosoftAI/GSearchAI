from dataclasses import dataclass, field
from typing import List, Optional
from .workbook import Workbook
from ..registries.business_object_registry import BusinessObjectRegistry

@dataclass
class PipelineContext:
    """
    A strongly typed orchestration context that carries immutable discovery artifacts 
    and controlled stage outputs between engines.
    It owns references (registries/stores) rather than raw arrays.
    """
    tenant_id: str
    kb_id: str
    file_bytes: bytes
    filename: str
    
    workbook: Optional[Workbook] = None
    business_object_store: BusinessObjectRegistry = field(default_factory=BusinessObjectRegistry)
    
    # Validation & Telemetry Tracking
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    
    def log(self, message: str):
        self.logs.append(message)
        
    def add_error(self, error: str):
        self.errors.append(error)
        
    def add_warning(self, warning: str):
        self.warnings.append(warning)
