"""
Configuration for Graph Schema Enforcement.
Provides ALLOWED_SCHEMA_MATRIX to enforce mathematical guarantees against hallucinated predicates.
"""

# Tuple format: (SUBJECT_TYPE, PREDICATE, OBJECT_TYPE)
# This matrix will be used as a post-parse whitelist filter in unified_extractor.py
ALLOWED_SCHEMA_MATRIX = {
    ("ORGANIZATION", "LOCATED_IN", "LOCATION"),
    ("ORGANIZATION", "WORKS_AT", "ORGANIZATION"), # For B2B relations
    ("ORGANIZATION", "ACQUIRED", "ORGANIZATION"),
    ("ORGANIZATION", "PRODUCES", "CONCEPT"),
    
    ("PERSON", "WORKS_AT", "ORGANIZATION"),
    ("PERSON", "EMPLOYEE_OF", "ORGANIZATION"),
    ("PERSON", "LIVES_IN", "LOCATION"),
    ("PERSON", "SPOUSE", "PERSON"),
    ("PERSON", "RELATES_TO", "PERSON"),
    
    ("CONCEPT", "RELATES_TO", "CONCEPT"),
    ("ORGANIZATION", "RELATES_TO", "CONCEPT"),
    ("PERSON", "RELATES_TO", "CONCEPT"),
    
    ("DOCUMENT", "MENTIONS", "ORGANIZATION"),
    ("DOCUMENT", "MENTIONS", "PERSON"),
    ("DOCUMENT", "MENTIONS", "LOCATION"),
    ("DOCUMENT", "MENTIONS", "CONCEPT"),
    
    # Structural Document Edges
    ("DOCUMENT", "HAS_SECTION", "SECTION"),
    ("SECTION", "HAS_SUBSECTION", "SECTION"),
    ("SECTION", "HAS_TABLE", "TABLE"),
    ("SECTION", "HAS_TEXT", "TEXT"),
    ("SECTION", "HAS_LIST", "LIST"),
    ("SECTION", "HAS_CODE", "CODE"),
    ("SECTION", "HAS_IDENTIFIER", "STRUCTURED_IDENTIFIER"),
    ("TABLE", "HAS_ROW", "ROW"),
    ("DOCUMENT", "PART_OF", "DOCUMENT"),
    
    # Web Extraction Edges
    ("ORGANIZATION", "HAS_WEBSITE", "URL"),
    ("ORGANIZATION", "HAS_WEBSITE", "CONCEPT"),
    ("PERSON", "HAS_WEBSITE", "URL"),
    ("CONCEPT", "HAS_URL", "URL"),
    
    # Generic and Abstract relations for LLM flexibility
    ("CONCEPT", "IN", "CONCEPT"),
    ("PERSON", "HAS_EXPERIENCE", "CONCEPT"),
    ("ORGANIZATION", "HAS_EXPERIENCE", "CONCEPT"),
    
    # Quality Assurance & Academic Ontology Additions
    ("CONCEPT", "DEFINED_AS", "CONCEPT"),
    ("CONCEPT", "REFERRED_TO", "CONCEPT"),
    ("CONCEPT", "AIMS_FOR", "CONCEPT"),
    ("CONCEPT", "DETERMINES", "CONCEPT"),
    ("PERSON", "DEVELOPED", "CONCEPT"),
    ("PERSON", "DEFINED", "CONCEPT"),
    ("NAME", "ORIGINATOR_OF", "CONCEPT"),
}
