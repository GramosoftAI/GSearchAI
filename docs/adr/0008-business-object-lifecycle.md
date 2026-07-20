# ADR 008: BusinessObject Lifecycle

## Status
Accepted

## Context
Data ingested through pipelines can fail at various stages. If an object fails validation but we lack a state machine, the system resorts to either dropping the object silently or halting the entire pipeline.

## Decision
Every `BusinessObject` is governed by a strict state machine lifecycle (`DISCOVERED → NORMALIZED → VALIDATED → RELATED → READY → PERSISTED`). Transitioning backwards is prohibited unless explicitly rolled back.

## Consequences
- **Positive:** Unambiguous pipeline visibility. Allows the `QuarantineManager` to intercept failed states without crashing the ingestion run.
- **Negative:** State transition boilerplate is required in the Engine frameworks.
