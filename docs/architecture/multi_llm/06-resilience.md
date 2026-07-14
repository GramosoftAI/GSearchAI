# 06 Resilience

This document outlines the operational failure semantics, including the interaction between retries, circuit breaking, and fallbacks.

## Failure Semantics Reference Table

| Failure | Retry | Fallback | Circuit breaker |
|---|---|---|---|
| Timeout | Yes | Yes | Yes |
| 429 | Yes | Yes | Yes |
| 502/503 | Yes | Yes | Yes |
| Invalid API key | No | Yes | No |
| Invalid prompt (400) | No | No | No |
| Unsupported capability | No | Next route | No |
