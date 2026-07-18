# ADR 1: LLM Prohibited from Generating Structured Facts

## Status
Accepted

## Context
During the design of the Enterprise Structured Data Intelligence Platform (ESDIP), we evaluated whether to use generative AI (LLMs) to extract and map structured fields from tabular data (like Excel/CSV). While LLMs offer powerful semantic understanding, they are prone to hallucinations, precision loss in numeric fields, and non-deterministic behavior.

## Decision
**AI may never create, modify, or replace structured business facts.** 

All structured values (numeric, alphanumeric, dates, identifiers, currencies) must be retrieved directly from deterministically parsed `BusinessObjects`. The LLM is invoked only *after* retrieval and is strictly limited to interpreting, summarizing, comparing, or explaining the retrieved evidence.

## Consequences
- **Positive:** Guarantees 100% preservation of structured data fidelity. Eliminates hallucinations in financial or sensitive data.
- **Negative:** Requires writing deterministic parsing and heuristics engines for schema mapping, increasing upfront engineering complexity.
