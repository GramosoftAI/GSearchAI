# Extraction prompt  deterministic, structured output
# NOTE: All literal {{ }} are escaped for Python .format()  only {text} is a placeholder
TRIPLET_EXTRACTION_PROMPT = """Extract knowledge events and facts from the following text.

CRITICAL INSTRUCTION: Before extracting anything, first determine whether the AI's response actually contains retrieved information, or whether it expresses that no information was found / the AI doesn't know / the question is unanswerable from context. If the response expresses absence of information in ANY phrasing (not just specific keywords), output {{"facts": []}} — do not create relations like IS_UNKNOWN, LACKS_INFORMATION, HAS_VALUE=no, or any triplet that encodes the absence itself as a fact about the subject.

For each fact, decide its mode using this rule, in order:

1. If the fact involves 3 or more distinct participants, OR carries any
   attached attribute (date, amount, quantity, status, location, duration),
   you MUST use "event" mode. Do not split it into separate relationship
   facts under any circumstances.
2. Otherwise, if it is a direct two-entity relationship with no extra
   attributes, use "relationship" mode.

Provide a `mode_hint` field stating which rule applied.

CRITICAL: never represent one event as multiple separate relationship facts.
All participants and attributes belonging to the same event must appear
together inside a single event object's "participants" and "attributes"
lists.

--- CORRECT: one event, all details bundled together ---
{{
    "mode_hint": "event",
    "name": "Google acquisition of DeepMind",
    "event_type": "EVENT",
    "participants": [
        {{"entity": "Google", "role": "buyer", "entity_type": "ORGANIZATION"}},
        {{"entity": "DeepMind", "role": "acquired_company", "entity_type": "ORGANIZATION"}}
    ],
    "attributes": [
        {{"attribute": "date", "value": "2014", "entity_type": "DATE"}},
        {{"attribute": "amount", "value": "500 million dollars", "entity_type": "NUMERIC"}}
    ]
}}

--- WRONG: the same fact fragmented into separate relationship facts ---
--- Do NOT do this, even though each individual fact below looks valid ---
{{"mode_hint": "relationship", "predicate": "ACQUIRED", "subject": "Google", "object": "DeepMind"}}
{{"mode_hint": "relationship", "predicate": "ACQUISITION_DATE", "subject": "Google", "object": "2014"}}
{{"mode_hint": "relationship", "predicate": "ACQUISITION_AMOUNT", "subject": "Google", "object": "500 million dollars"}}

--- CORRECT: simple two-entity relationship, no attributes, stays flat ---
{{
    "mode_hint": "relationship",
    "name": "CEO_OF",
    "subject": "Demis Hassabis",
    "subject_type": "PERSON",
    "object": "DeepMind",
    "object_type": "ORGANIZATION"
}}

Return ONLY valid JSON in this exact format:
{{
    "facts": [
        {{
            "mode_hint": "event",
            "name": "Google acquisition of DeepMind",
            "event_type": "EVENT",
            "participants": [
                {{
                    "entity": "Google",
                    "role": "buyer",
                    "entity_type": "ORGANIZATION"
                }},
                {{
                    "entity": "DeepMind",
                    "role": "acquired_company",
                    "entity_type": "ORGANIZATION"
                }}
            ],
            "attributes": [
                {{
                    "attribute": "date",
                    "value": "2014",
                    "entity_type": "DATE"
                }},
                {{
                    "attribute": "amount",
                    "value": "500 million dollars",
                    "entity_type": "NUMERIC"
                }}
            ]
        }},
        {{
            "mode_hint": "relationship",
            "name": "CEO_OF",
            "subject": "Demis Hassabis",
            "subject_type": "PERSON",
            "object": "DeepMind",
            "object_type": "ORGANIZATION"
        }}
    ]
}}

Valid entity types: PERSON, ORGANIZATION, LOCATION, CONCEPT, EVENT, PRODUCT, TECHNOLOGY, NUMERIC, DATE, STRUCTURED_IDENTIFIER

TEXT:
{text}

JSON:"""