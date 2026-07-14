# ADR 006: Governance Layer

## Status
Accepted

## Context
Without a dedicated governance layer, heuristics (like table detection or relationship mapping) silently fail or produce corrupted data that is instantly persisted to the database.

## Decision
We introduce a strict Governance Layer containing a `DecisionEngine`, `PolicyEngine`, and `QuarantineManager`. Every object must pass Validation and Acceptance policies before transitioning to a `READY` state. 

## Consequences
- **Positive:** Data corruption is caught before persistence. Problematic objects are safely quarantined for human review.
- **Negative:** Adds processing overhead to the ingestion pipeline.
