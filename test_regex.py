import sys
sys.path.append('.')
from app.memory.app.main import _is_deterministic_preference_statement

query = 'List all transactions where the discount was greater than 25% and the sales amount was above ?5,000.'
print('Result:', _is_deterministic_preference_statement(query))

# Also let's print if it matches PREFERENCE_PATTERNS or DYNAMIC_FACT_PATTERN
from app.memory.app.main import _PREFERENCE_PATTERNS, _DYNAMIC_FACT_PATTERN

print('PREFERENCE:', bool(_PREFERENCE_PATTERNS.search(query)))
print('DYNAMIC FACT:', bool(_DYNAMIC_FACT_PATTERN.search(query)))
if _DYNAMIC_FACT_PATTERN.search(query):
    print('Dict:', _DYNAMIC_FACT_PATTERN.search(query).groupdict())
