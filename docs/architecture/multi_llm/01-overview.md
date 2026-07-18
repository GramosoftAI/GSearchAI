# 01 Overview

The Pluggable Multi-LLM Orchestration Platform is designed around a single guiding principle: **Providers are plugins. Routing is data. Business logic never knows which model answered.**

## Architectural Invariants

The following invariants are structural rules that must not be violated. PR reviewers should flag violations on sight:

- **Business services must never instantiate providers directly.** They must only interact with the `LLMService` façade.
- **Providers must not emit telemetry.** Telemetry is the responsibility of the middleware pipeline.
- **Providers must not contain retry logic.** Retry policies are managed exclusively by `RetryMiddleware`.
- **Routing decisions belong only to the router.** Individual components or providers must not dictate routing.
- **Middleware must be independently testable.** No middleware depends on another middleware's internals—only on shared `LLMExecutionContext` fields.
- **Cost calculation must not mutate provider responses.** 
- **`LLMExecutionContext` is the single source of truth for request state.** All terminal data must be recorded here.

## Extension Points

When adding new capabilities to the platform, use the defined extension points rather than modifying the core orchestration loop:

| Feature | Extension point |
|---|---|
| New provider | `providers/` + `PROVIDER_REGISTRY` |
| New middleware | `middlewares/` + `MIDDLEWARE_REGISTRY` |
| New routing rule | `config.yaml` |
| New pricing | `pricing.yaml` |
| New telemetry backend | `TelemetrySink` implementation |
| New cost model | `CostEstimator` |
