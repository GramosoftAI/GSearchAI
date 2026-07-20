# ADR 007: Persistence Coordinator

## Status
Accepted

## Context
When persisting objects to both PostgreSQL (attributes) and Neo4j (relationships), standard distributed transactions (two-phase commit) are often complex, brittle, and non-performant at scale.

## Decision
We utilize a `PersistenceCoordinator` that manages idempotent persistence operations across storage backends using durable operation identifiers and verification before marking the BusinessObject as `PERSISTED`.

## Consequences
- **Positive:** System recovers gracefully from partial persistence failures. Operations can be safely retried.
- **Negative:** Eventual consistency window exists between Postgres and Neo4j during the coordinator's lifecycle.
