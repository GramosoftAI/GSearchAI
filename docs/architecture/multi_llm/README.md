# Multi-LLM Architecture

This directory contains the Architectural Decision Records (ADRs) and reference documentation for the Pluggable Multi-LLM Orchestration Platform.

## Documents

- [01-overview.md](01-overview.md): High-level architecture, invariants, and extension points.
- [02-request-lifecycle.md](02-request-lifecycle.md): End-to-end request lifecycle and sequence diagrams.
- [03-provider-contract.md](03-provider-contract.md): Provider implementation requirements and capabilities.
- [04-routing.md](04-routing.md): Declarative routing rules and constraints.
- [05-middleware.md](05-middleware.md): Middleware protocols and composition.
- [06-resilience.md](06-resilience.md): Retry, circuit breaking, and failure semantics.
- [07-context.md](07-context.md): The `LLMExecutionContext` structure.
- [08-telemetry.md](08-telemetry.md): Event catalog and sink implementation.
- [09-cost.md](09-cost.md): Pricing model and estimation.
- [10-rollout.md](10-rollout.md): Migration runbook and shadow mode.
