# ADR 005: PipelineContext Contract

## Status
Accepted

## Context
Data ingestion pipelines historically suffer from "God Objects"—huge dictionaries passed between stages that consume immense memory and lack type safety.

## Decision
We enforce a strict `PipelineContext` contract. It owns registries (like `BusinessObjectRegistry`) and stores references rather than massive memory arrays. Engines communicate exclusively through this context and are permitted to modify only the domains they own.

## Consequences
- **Positive:** Prevents memory bloat, ensures deterministic testing of individual engines, and provides type safety.
- **Negative:** Slightly more boilerplate required when fetching objects from the registries within an engine.
