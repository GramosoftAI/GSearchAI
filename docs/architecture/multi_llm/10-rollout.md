# 10 Rollout and Migration

This document serves as the operational runbook for migrating pipelines to the new orchestration platform.

## Migration Runbook

Concrete, repeatable checklist to execute per pipeline slice:

1. **Enable Feature Flag**: Set at 0% or a low percentage.
2. **Shadow Mode**: Run the new pipeline in shadow mode. Compare telemetry with the legacy path.
3. **Validate Metrics**: Validate latency and cost against established success criteria.
4. **Ramp Up**: Gradually increase the rollout percentage.
5. **Soak Period**: Observe stability.
6. **Remove Legacy Path**: Remove legacy paths only after a defined stability soak period for the entire migration.
