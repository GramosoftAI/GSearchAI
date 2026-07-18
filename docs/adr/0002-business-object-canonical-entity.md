# ADR 2: BusinessObject as the Canonical Entity

## Status
Accepted

## Context
Data ingested from multiple formats (Excel, CSV, SQL) naturally contains variations in naming, types, and groupings. A single ingestion pipeline that passes raw dictionaries between stages becomes untrackable and impossible to govern.

## Decision
We establish `BusinessObject` as the universal canonical entity. Every row or conceptual grouping discovered is mapped into an autonomous `BusinessObject`. It tracks its own `Provenance`, references a single `SchemaSnapshot`, maintains its `ObjectState` lifecycle, and holds its `Relationships`.

## Consequences
- **Positive:** Creates a clean, strongly typed domain model that decouples the persistence layer from the ingestion source.
- **Negative:** Requires storing intermediate references in a `BusinessObjectRegistry` during processing to manage memory consumption.
