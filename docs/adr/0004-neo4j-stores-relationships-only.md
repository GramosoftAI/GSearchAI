# ADR 004: Neo4j Stores Relationships Only

## Status
Accepted

## Context
When persisting `BusinessObject` graphs, we need both scalable relational querying (for attributes) and scalable graph traversal (for lineage and foreign keys). Storing heavy attributes in Neo4j causes performance degradation during deep traversals.

## Decision
Neo4j will be strictly utilized for storing nodes (representing IDs and types) and edges (Relationships). All heavy attributes and nested `BusinessObject` data remain in PostgreSQL.

## Consequences
- **Positive:** Neo4j traversals remain incredibly fast and focused purely on structure.
- **Negative:** Retrieval layer must perform a join/federated query between Neo4j (for the structural path) and Postgres (for the rich attributes).
