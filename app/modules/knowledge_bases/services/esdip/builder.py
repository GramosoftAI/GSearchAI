import logging
import uuid
import pandas as pd
from typing import List, Dict, Any
from .discovery import LogicalTable

logger = logging.getLogger(__name__)

class BusinessObject:
    def __init__(self, id: str, entity_type: str, provenance: Dict[str, Any], attributes: Dict[str, Any]):
        self.id = id
        self.entity_type = entity_type
        self.provenance = provenance
        self.attributes = attributes
        self.relationships: List[Dict[str, Any]] = []

class BusinessObjectBuilder:
    """
    Stage 7: Business Object Builder
    Converts logical table rows into structured Business Objects.
    """
    @staticmethod
    def build(table: LogicalTable) -> List[BusinessObject]:
        logger.info(f"Stage 7: Business Object Builder for table in '{table.sheet_name}'")
        objects = []
        df = table.dataframe
        primary_key_col = table.schema.get("_primary_key_candidate")
        
        # Heuristic: the sheet name often represents the entity type.
        entity_type = "".join([c for c in table.sheet_name if c.isalnum()]).upper()
        if not entity_type:
            entity_type = "RECORD"
            
        for i, row in df.iterrows():
            row_dict = row.dropna().to_dict()
            
            # Primary Key
            if primary_key_col and primary_key_col in row_dict:
                pk_val = str(row_dict[primary_key_col])
            else:
                pk_val = f"row_{i}"
                
            obj_id = f"{entity_type}_{pk_val}"
            
            provenance = {
                "sheet_name": table.sheet_name,
                "row_index": i + table.start_row + 1  # 1-indexed for the user, relative to original sheet
            }
            
            obj = BusinessObject(
                id=obj_id,
                entity_type=entity_type,
                provenance=provenance,
                attributes=row_dict
            )
            objects.append(obj)
            
        return objects

class RelationshipDiscovery:
    """
    Stage 8: Relationship Discovery
    Infers relationships based on column naming conventions and data overlap (foreign keys).
    """
    @staticmethod
    def discover(objects: List[BusinessObject], table: LogicalTable) -> List[BusinessObject]:
        logger.info(f"Stage 8: Relationship Discovery for table in '{table.sheet_name}'")
        
        # Basic heuristic: columns ending in '_id' or 'id' might be foreign keys
        # We'll tag them as potential relationships.
        
        for obj in objects:
            for key, val in obj.attributes.items():
                if key.endswith("_id") and key != table.schema.get("_primary_key_candidate"):
                    target_type = key[:-3].upper()
                    
                    obj.relationships.append({
                        "target_id": f"{target_type}_{val}",
                        "target_type": target_type,
                        "relation": f"HAS_{target_type}",
                        "evidence": f"Column '{key}' suggests a foreign key to {target_type}",
                        "confidence": 0.8
                    })
                    
        return objects
