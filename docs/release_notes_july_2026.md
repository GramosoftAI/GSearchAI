# GSearchAI Release Notes (July 29 - July 30)

This release introduces significant speed improvements, stronger guardrails against incorrect answers, and fixes to ensure search results from both spreadsheets (Excel/CSV) and documents (PDF) are seamlessly combined.

---

## 1. Speed & Reliability Improvements

### Fast and Concurrent Searching (Parallel Hybrid RAG)
* **What was happening**: Previously, the system had to spend 3 to 5 seconds deciding whether to search your Excel/CSV files or your PDFs before starting the search. If it searched both, it did so one after another, causing long wait times.
* **The Improvement**: The system now searches **both** your spreadsheets and documents at the exact same time. This ensures 100% accurate results without making you wait any longer.

### Faster Spreadsheet Searches
* **What was happening**: Excel/CSV search was doing extra hidden processing steps to write text explanations of tables, adding up to 60 seconds of delay.
* **The Improvement**: Removed the redundant steps. The system now passes the table data directly to the final assistant, resulting in near-instant spreadsheet searches.

### Preventing Connection Drops
* **What was happening**: For larger databases or complex questions, the system took too long to think, causing the chat screen to disconnect or timeout.
* **The Improvement**: The system now instantly streams back the source citations and document references while the AI finishes preparing the detailed answer. This keeps the chat connection alive and healthy.

---

## 2. Stronger Accuracy & Guardrails

### Filtering Out Irrelevant Information
* **What was happening**: When searching documents, the database would sometimes return completely unrelated paragraphs. The AI would read these anyway, leading to confusing or "hallucinated" answers.
* **The Improvement**: Added a smart filter that blocks text below a strict relevance score. If no relevant information is found, the system cleanly states, *"I couldn't find it,"* preventing false answers.

### Restoring Missing Spreadsheet Answers
* **What was happening**: If you asked about a specific record in a spreadsheet (like an employee ID), the system found it. However, if that record wasn't also mentioned in the PDFs, the system would throw the spreadsheet answer away and say it couldn't find it.
* **The Improvement**: Fixed the merging pipeline. Spreadsheet answers are now preserved and displayed even if the PDF search returns zero matches.

---

## 3. Bug Fixes & Stability

### Complex Search Crashes Resolved
* **What was happening**: Certain symbols in complex search instructions caused the intent classifier to crash silently, reverting the system to slow fallback modes.
* **The Improvement**: Corrected the formatting of search instructions to prevent crashes, making the classifier stable under all conditions.

### DeepInfra Server Fixes
* **What was happening**: An internal connection setup error caused the system to fail to contact the AI model for spreadsheet lookups, returning blank results.
* **The Improvement**: Fixed the communication headers so the system always establishes a secure, successful connection to the AI provider.
