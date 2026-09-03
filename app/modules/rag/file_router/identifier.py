import re
from typing import List, Dict, Any
from .schema import FileMatch

def match_exact_identifiers(query: str, kb_metadata: Dict[str, Any]) -> List[FileMatch]:
    matches = []
    query_lower = query.lower()
    
    for kb_id, meta in kb_metadata.items():
        name = meta.get("name", "")
        identifiers_to_check = []
        if name:
            identifiers_to_check.append(("filename", name))
            
        global_identifiers = meta.get("global_identifiers", {})
        if isinstance(global_identifiers, dict):
            for k, v in global_identifiers.items():
                if v and isinstance(v, str):
                    identifiers_to_check.append((f"global_identifiers.{k}", v))
                elif v and isinstance(v, list):
                    for item in v:
                        if item and isinstance(item, str):
                            identifiers_to_check.append((f"global_identifiers.{k}", item))
                            
        for field, value in identifiers_to_check:
            value_str = str(value).lower()
            escaped_val = re.escape(value_str)
            # Use regex with word boundaries to avoid partial substring false positives
            pattern = rf'\b{escaped_val}\b'
            if re.search(pattern, query_lower):
                matches.append(
                    FileMatch(
                        kb_id=kb_id,
                        name=name,
                        match_type="exact_identifier",
                        score=1.0,
                        matched_on=value_str
                    )
                )
                
    return matches
