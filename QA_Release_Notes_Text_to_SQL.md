# QA Release Notes & Testing Guide: Text-to-SQL Engine Enhancements

**Module:** Database Knowledgebase (Natural Language to SQL / Grounded RAG Pipeline)  
**Target Audience:** QA Engineers, Test Automation Teams, and Product Owners  
**Target Service:** `GSearchAI` (`app.modules.database_knowledgebase`)  
**Date:** October 2026  

---

## 1. Executive Summary & Core Changes

Recent updates to the Text-to-SQL pipeline enhance schema retrieval accuracy, eliminate hallucinated table joins, support complex polymorphic associations, and introduce iterative self-healing for PostgreSQL queries.

All enhancements are **100% dynamic, generic, and schema-agnostic**—operating without hardcoded table names, column names, or static conditions across any connected relational database.

---

## 2. Technical Modifications Overview

### A. Schema Markdown Generator (`app/modules/database_knowledgebase/schema/markdown_doc_generator.py`)
* **On-the-Fly DDL Markdown Synthesis:** If table documents do not have pre-computed vector embeddings in `db_schema_embeddings`, the system automatically synthesizes AI-understandable Markdown documents directly from the canonical DDL schema snapshot in real time.
* **Unified Method Signatures:** Exposed `generate_table_markdown` with alias `generate_table_document` to ensure seamless compatibility across semantic retrieval and dynamic self-healing loops.
* **Enriched Schema Metadata:** Generated Markdown documents now provide:
  * Table definitions, comments, and column counts.
  * Exact column data types, nullability, defaults, primary keys, and foreign keys.
  * Polymorphic and association columns (`entity_type`, `entity_id`, `journable_type`, `journable_id`) for accurate LLM reasoning.

### B. Dynamic Fact Hub & Junction Discovery (`retrieval/schema_doc_retriever.py` & `services/service.py`)
* **Multi-Entity Fact Prioritization:** When a query references multiple dimension entities (e.g., User + Project + Issue Type), the retriever scans the schema for central fact/transaction tables (e.g., `work_packages`) that connect them.
* **Junction Ranking:** Tables linking $\ge 2$ queried entities are boosted with high priority (score `0.95`–`1.0`), preventing the context window from being flooded by peripheral tables.
* **Integration Table Filtering:** Automatically excludes third-party integration tables (`github_*`, `gitlab_*`, `scim_*`, `good_job_*`, `bcf_*`) unless explicitly requested in the query.

### C. Polymorphic & Dual Association Joins (`sql_generator/grounded_generator.py`)
* **Polymorphic Foreign Key Support:** Handles tracking and log tables (such as `time_entries` and `journals`) where direct foreign keys (e.g., `work_package_id`) may be `NULL` in favor of polymorphic references (`entity_type = 'WorkPackage' AND entity_id = wp.id`).
* **Dialect & Syntax Hardening:**
  * **PostgreSQL `ORDER BY` Alignment:** Ensures that when `SELECT DISTINCT` is used, every expression in `ORDER BY` matches the `SELECT` list.
  * **Split Name Resolution:** Accurately queries databases with split names (`firstname`, `lastname`) using `CONCAT` or individual `ILIKE` clauses instead of assuming a single `name` column exists.
  * **Entity ID Grounding:** Injects resolved dimension entity IDs directly into foreign key filters (e.g., `project_id = 95`) rather than performing loose wildcard text searches on task subjects.

### D. Iterative Dynamic Self-Healing Loop (`services/service.py`)
* **Multi-Attempt Repair Loop:** Expanded the auto-repair mechanism into a 2-attempt iterative loop. If a repaired query encounters a secondary syntax or column issue, the exact PostgreSQL error message is fed back to the LLM to self-heal and re-execute safely.
* **Scope Fix in Entity Resolver:** Resolved scope variable assignment in `GroundedEntityResolver` to guarantee consistent entity resolution.

---

## 3. QA Test Scenarios & Detailed Test Cases

### Test Case TC-SQL-01: Multi-Dimension Fact Query (User + Project + Type)
* **Objective:** Verify that queries referencing multiple entities retrieve the central fact table and return correct timestamps without hallucinating direct dimension joins.
* **Test Input Query:**
  ```text
  On what date did Elakkiya most recently create a bug in GSearch?
  ```
* **Expected System Behavior:**
  1. Resolves `users` (Elakkiya $\rightarrow$ ID 104), `projects` (GSearch $\rightarrow$ ID 95), and `types` (Bug $\rightarrow$ ID 7).
  2. Dynamically pulls `work_packages` as the central connecting fact table.
  3. Joins `work_packages` $\rightarrow$ `projects`, `types`, and `users`.
  4. Avoids invalid direct joins (e.g., no `types.id = projects.id` or `projects.creator_id`).
  5. Returns the single most recent creation date (`2026-09-22`).

---

### Test Case TC-SQL-02: Polymorphic Associations & Logged Time
* **Objective:** Verify queries requesting task updates and logged hours where timesheet tables use polymorphic `entity_type` / `entity_id` links.
* **Test Input Query:**
  ```text
  Who updated tasks in the GSearch (Graph RAG) project on 13 October 2026? Show the user's name, task subject, and the actual hours logged for each task
  ```
* **Expected System Behavior:**
  1. Generates the polymorphic join condition:
     ```sql
     ON (te.work_package_id = wp.id OR (te.entity_type = 'WorkPackage' AND te.entity_id = wp.id))
     ```
  2. Query does **not** return 0 rows.
  3. Returns all active contributors who updated tasks on that date (e.g., Arun N, Elakkiya B, Ganeshamoorthi V, Girinath RG) with their logged hours.

---

### Test Case TC-SQL-03: Semantic Intent ("Working On" vs. "Members Of")
* **Objective:** Verify that "working on/under" queries tasks/work items, whereas "members of" queries the project roster.
* **Test Input Queries:**
  * **TC-SQL-03A (Active Contributors):**
    ```text
    List all users working under the CREAM_Reward project.
    ```
    *Expected:* Queries `work_packages` (assignees/authors), returning active contributors (e.g., 5 users).
  * **TC-SQL-03B (Project Membership Roster):**
    ```text
    How many users are members of the CREAM_Reward project?
    ```
    *Expected:* Queries `members` table, returning the complete roster count (e.g., 10 users).

---

### Test Case TC-SQL-04: Split Name Columns & Concatenation
* **Objective:** Ensure tables without a direct `name` column (using `firstname`/`lastname`) do not fail execution.
* **Test Input Query:**
  ```text
  Show all tasks assigned to Arun in GSearch.
  ```
* **Expected System Behavior:**
  1. Generates `(u.firstname ILIKE '%Arun%' OR u.lastname ILIKE '%Arun%')` or `CONCAT(u.firstname, ' ', u.lastname) ILIKE '%Arun%'`.
  2. Never produces `u.name ILIKE '%Arun%'`.

---

### Test Case TC-SQL-05: Self-Healing & Dialect Edge Cases
* **Objective:** Verify the LLM repair loop recovers when a database-specific syntax rule is violated.
* **Test Input Query:**
  ```text
  What was the latest task status change date in GSearch?
  ```
* **Expected System Behavior:**
  1. If an initial query triggers a PostgreSQL error (e.g., `ORDER BY expressions must appear in select list`), `[GROUNDED_AUTO_REPAIR]` activates.
  2. The pipeline logs `Invoking universal LLM repair loop (attempt 1/2)`.
  3. The repaired SQL executes successfully, returning HTTP 200 and a verified answer without throwing a 500 error.

---

## 4. Test Execution Instructions

### Method 1: Frontend UI Testing
1. Navigate to the GSearch AI web application (`http://localhost:3000` or staging environment).
2. Open the knowledgebase selector and select the target database (e.g., OpenProject DB `0e9ba617-55ed-4af8-9408-b3d4f3c00197`).
3. Enter the test queries from Section 3.
4. Expand the **Pipeline Trace Drawer** and inspect each stage:
   * **Phase 2A (Semantic Schema Retrieval):** Ensure retrieved tables are relevant and limited to $\le 8$ tables.
   * **Phase 2B (Query Planning & SQL Generation):** Inspect the generated SQL and parameters.
   * **Phase 2C (Read-Only Driver Execution):** Confirm row counts $> 0$ and check execution latency.
   * **Phase 2D (Grounded Synthesis):** Confirm the narrative answer accurately matches the returned rows.

### Method 2: Direct API Testing (cURL / Postman)
* **Method:** `POST`
* **URL:** `/api/v1/database-knowledgebases/0e9ba617-55ed-4af8-9408-b3d4f3c00197/query/stream`
* **Headers:** `Content-Type: application/json`
* **Request Body:**
  ```json
  {
    "user_query": "On what date did Elakkiya most recently create a bug in GSearch?",
    "top_k_tables": 8,
    "use_llm": true
  }
  ```
* **Stream Events to Verify:**
  * `QUERY_ACCEPTED`
  * `RETRIEVAL_COMPLETED` (returns `retrieved_tables`)
  * `PLANNING_STARTED` & `PLANNING_COMPLETED`
  * `SQL_GENERATED`
  * `DATABASE_EXECUTION_COMPLETED` (`row_count > 0`)
  * `ANSWER_GENERATED` (`grounding_status: "VERIFIED"`)

---

## 5. QA Sign-Off Checklist

| ID | Verification Item | Status | Notes |
|:---|:---|:---:|:---|
| 1 | No static/hardcoded tables or project IDs in source code | [ ] | Dynamic schema discovery |
| 2 | No invalid cross-joins between dimension tables (`projects.id = types.id`) | [ ] | Connected via fact tables |
| 3 | No `column does not exist` errors for split name columns (`users.name`) | [ ] | Uses `firstname` / `lastname` |
| 4 | Polymorphic associations return correct rows (`entity_type` / `entity_id`) | [ ] | Dual join condition verified |
| 5 | Self-healing loop resolves initial syntax errors within 2 attempts | [ ] | Verified on PostgreSQL |
| 6 | Execution security: all queries are strictly read-only (`SELECT`) | [ ] | Verified by AST validator |
| 7 | Zero regression on standard aggregations (`COUNT`, `SUM`, `AVG`) | [ ] | Verified |
