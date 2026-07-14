# ADR 009: Evidence-Backed Retrieval

## Status
Accepted

## Context
Standard RAG retrieves text blocks and relies on the LLM to understand relationships. This breaks down for tabular logic where precise relationships between disconnected entities (e.g., invoices and payments) must be respected.

## Decision
Retrieval is fully decoupled from AI generation. The retrieval pipeline constructs a verified context block (the `Response Assembler`) comprised solely of `BusinessObjects` and their proven `Relationships`. The AI strictly interprets this assembled evidence.

## Consequences
- **Positive:** Zero hallucinations in structured facts. Total auditability.
- **Negative:** Increased complexity in the retrieval logic, requiring graph traversal and vector hybridization before any text is generated.
