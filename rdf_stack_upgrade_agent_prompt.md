# Agent task: upgrade triplet ingestion pipeline with RDF-stack-inspired validation

## Context

This codebase implements a triplet extraction and knowledge graph ingestion pipeline
with the following existing flow:

```
Ingestion Engine (Document/Chat)
  -> TripletExtractor (LLM)
  -> Ontology & URI Mapper
  -> TripletGraphWriter
  -> Neo4j (nodes + relationships, deduplicated via MERGE)
```

Goal: add a lightweight, RDF/RDFS/OWL/SHACL-inspired quality layer to this pipeline
**without** switching the underlying store away from Neo4j and **without** changing
the query layer (stays Cypher). This is not a request to adopt a full RDF triple
store — it's a request to borrow the *concepts* (structural validation, event
modeling) and implement them natively in Python/Cypher.

## Step 1 — Analyze before changing anything

Before writing any code, do the following and report back:

1. Locate and read the current implementation of:
   - The `TripletExtractor` (LLM extraction step, including its prompt)
   - The `Ontology & URI Mapper` (normalization / canonical predicate mapping)
   - The `TripletGraphWriter` (Cypher MERGE/CREATE logic)
   - Any existing Pydantic models or schema definitions for triplets
2. Identify the current triplet data shape (what fields exist: subject, predicate,
   object, types, chunk_id, tenant_id, etc.)
3. Identify whether entity/predicate types are already enumerated anywhere
   (an enum, a config file, a DB table) or if they're currently freeform strings
   coming from the LLM.
4. Summarize findings and confirm the plan below before implementing.

## Step 2 — Add a triplet classification decision (simple vs. event-hub)

Implement a deterministic function that decides, for each LLM-extracted fact,
whether it should be written as a **simple relationship** or as an **event-hub
node** in Neo4j. Do not rely on the LLM's own judgment alone — this must be a
code-level check applied after extraction.

Decision rule (implement as pure function, unit-testable):

```python
def needs_event_hub(fact: ExtractedFact) -> bool:
    """
    Returns True if this fact should be modeled as an event-hub node
    (a central node with multiple typed edges) rather than a single
    Neo4j relationship.

    Criteria (any one triggers True):
    - 3 or more distinct participant entities
    - 1 or more non-participant attributes (date, amount, status,
      quantity, location, etc.)
    - The fact is likely to be referenced again as its own entity
      (heuristic: extractor flags it as an "event" or "transaction" type)
    """
```

Also update the `TripletExtractor` prompt to ask the LLM to flag which mode it
believes applies (`relationship` vs `event`), but treat that as a *hint*, not
ground truth — always run it through `needs_event_hub` as the actual decision
point in the mapper/writer stage.

## Step 3 — Add lightweight structural validation ("SHACL-lite")

Do not add `pyshacl`/`rdflib`/`owlrl` as dependencies — that's heavier than this
project needs right now. Instead, implement validation as **Pydantic models**
acting as shape definitions, one per entity/event type, e.g.:

```python
class PersonShape(BaseModel):
    name: str
    entity_type: Literal["Person"]

class InvoiceEventShape(BaseModel):
    entity_type: Literal["InvoiceEvent"]
    issued_by: str
    issued_to: str
    amount: float
    issue_date: date
    # required fields enforced by Pydantic; reject on validation error
```

Requirements:
- Every triplet/event must be validated against the matching shape **before**
  being passed to `TripletGraphWriter`.
- On validation failure: do not write to Neo4j. Log a structured rejection
  record (chunk_id, tenant_id, reason, raw extracted fact) to a
  `rejected_triplets` sink (table, log stream, or file — match whatever
  logging/observability pattern already exists in this codebase).
- This must be tenant-aware: shapes may differ per tenant if the ontology is
  tenant-specific (check Step 1 findings for how tenant ontology is currently
  injected into the LLM prompt, and mirror that same tenant-scoping here).

## Step 4 — Update TripletGraphWriter for both patterns

- **Simple relationship** (existing pattern, keep as-is where already correct):
  `MERGE (a)-[:PREDICATE {chunk_id, ...props}]->(b)`
- **Event-hub pattern** (new): create a hub node plus typed edges to each
  participant, e.g.:
  ```cypher
  MERGE (event:Event:InvoiceEvent {id: $event_id})
  SET event += $event_props
  MERGE (issuer:TripletEntity {name: $issued_by})
  MERGE (recipient:TripletEntity {name: $issued_to})
  MERGE (event)-[:ISSUED_BY]->(issuer)
  MERGE (event)-[:ISSUED_TO]->(recipient)
  ```
  Route to this path only when `needs_event_hub()` returns True.

## Step 5 — Instrumentation

Add lightweight timing around the new steps (`needs_event_hub`, shape
validation, and the Neo4j write) so latency impact can be measured per chunk.
Use whatever timing/metrics pattern already exists in the codebase (structured
logs, OpenTelemetry spans, etc. — check Step 1 findings) rather than
introducing a new one.

## Step 6 — Tests

Add unit tests covering:
- `needs_event_hub` for: 2-party fact with no attributes (False), 2-party fact
  with an attribute like amount/date (True), 3+ party fact (True)
- Shape validation: a valid event passes, an event missing a required field is
  rejected with a clear reason
- Writer: a simple fact produces the expected Cypher relationship pattern; an
  event-hub fact produces the expected hub node + edges pattern

## Constraints

- Do not introduce `rdflib`, `owlrl`, or `pyshacl` — Pydantic-based validation
  only, per Step 3.
- Do not change the query layer — retrieval stays Cypher, this task only
  affects the ingestion/write path.
- Do not change existing simple-triplet behavior for facts that don't trigger
  `needs_event_hub` — this should be additive, not a rewrite of the working
  path.
- Preserve existing multi-tenant isolation guarantees (tenant_id scoping) in
  every new code path added.

## Deliverable

1. A short written plan (after Step 1 analysis) confirming file locations and
   approach before implementation.
2. Code changes implementing Steps 2-5.
3. Tests implementing Step 6.
4. A brief summary of latency impact observed in tests/local runs, if
   measurable.
