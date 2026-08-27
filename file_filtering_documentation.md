# Smart File Selection & Filtering: Executive Overview

This document provides a high-level overview of our new and improved file filtering system. The goal of this upgrade is to ensure that user questions are always answered using the most accurate and relevant documents, eliminating confusion when multiple files look similar.

---

## The Core Problem
Previously, when a user asked a question, the system used a basic text-matching approach to find the right file. 
- **The Issue:** If two different files had similar column names (like an "Employee Name" column in both an HR file and a Payroll file), the system struggled to know which one the user actually meant.
- **The Result:** The system might pull answers from the wrong file, leading to incorrect or incomplete responses.

---

## Our Solution: The 3-Layer Filtering System

We have replaced the old text-matching system with a highly intelligent, AI-driven **3-Layer Filtering System**. This ensures precise accuracy when deciding which file to search and which results to present.

### Layer 1: Semantic Layer (Intent & Keyword Extraction)
**What it does:** Before searching, the AI deeply analyzes the user's question to understand the true semantic meaning.
- **How it works:** It specifically extracts the most critical "Domain Keywords" (e.g., "hiking", "employee ID") and maps the query to the correct file schema. If multiple files have the same column headers, it evaluates the actual categorical data values inside the tables.
- **Business Value:** The system understands exactly *what* the user cares about semantically, guaranteeing it routes the request to the correct file.

### Layer 2: Gap Elimination Layer (Relevance Pruning)
**What it does:** It aggressively filters out files (Knowledge Bases) that are not highly relevant, preventing "noise" from diluting the answer.
- **How it works:** The pipeline dynamically compares the relevance scores of all candidate files. If a file's score falls below a strict dynamic threshold (`GAP_THRESHOLD = 0.15`) relative to the top-scoring file, it is completely eliminated from the search context.
- **Business Value:** Prevents the AI from hallucinating or pulling partial answers from loosely related, lower-quality files.

### Layer 3: RRF Layer (Reciprocal Rank Fusion & Domain Boosting)
**What it does:** It intelligently merges and ranks the final data chunks pulled from the remaining valid files.
- **How it works:** The RRF (Reciprocal Rank Fusion) algorithm fuses results from both the Vector search and Graph search. During this fusion phase, if a document's filename specifically matches the Semantic Layer's extracted keywords, a strong **Domain Boost** is applied to those chunks.
- **Business Value:** This guarantees that explicitly requested files (e.g., asking for the "2023 Employee Handbook") forcefully outrank generic text that happens to loosely match the query elsewhere.

---

## Summary of Impact
- **Before:** Basic keyword overlap. Easily confused by similar files. Blind to the actual data inside spreadsheets.
- **After:** A smart, AI-driven 3-layer system that understands user intent, maps it to the right file structures, and double-checks the actual row data to guarantee the most accurate answer possible.

---

## Performance & Technical Details
- **LLM Used:** DeepInfra LLM Engine (specifically using the `google/gemma-4-E4B-it` model, optimized for Intent & Routing classification).
- **Processing Time:** To ensure this 3-layer filter doesn't slow down the user experience, the LLM routing and keyword extraction run *concurrently* alongside standard searches. 
  - **Approximate Latency:** Typically resolves in **1 to 2 seconds**. 
  - **Failsafe:** It has a strict internal fast-fail timeout of **10.5 seconds** to guarantee that the system never hangs if the AI provider experiences a temporary delay.
