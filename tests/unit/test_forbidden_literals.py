import os
import re
import pytest

def test_no_hardcoded_database_names():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../app/modules/database_knowledgebase"))
    
    # Specific forbidden patterns per the prompt rules
    forbidden_patterns = [
        r"assigned_to_id",
        r"oidc_[a-zA-Z0-9_]*",
    ]
    
    # allowlist only the seed migration and test fixtures
    allowlist = ["migrations", "test_fixtures", "test_"]
    
    errors = []
    
    for dirpath, _, filenames in os.walk(root_dir):
        if any(allowed in dirpath for allowed in allowlist):
            continue
            
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
                
            filepath = os.path.join(dirpath, filename)
            if any(allowed in filename for allowed in allowlist):
                continue
                
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                
            for pattern in forbidden_patterns:
                matches = re.finditer(pattern, content, re.IGNORECASE)
                for match in matches:
                    errors.append(f"Found forbidden literal {match.group(0)} in {filepath}")
                    
    assert not errors, "\n".join(errors)

