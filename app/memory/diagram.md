┌────────────────────────────────────────┐
                         │          Main Client Browser           │
                         └───────────────────┬────────────────────┘
                                             │
                                (1) User sends New Query
                                             │
                                             ▼
  ┌────────────────────────────────────────────────────────────────────────────────────────┐
  │                           FASTAPI WEBSOCKET RAG ROUTER                                 │
  │                              (websocket_routes.py)                                     │
  └───────┬──────────────────────────────────┬──────────────────────────────────────▲──────┘
          │                                  │                                      │
          │ (2A) Fast-Path HTTP POST         │ (2B) Direct Database Fetch           │ (5) Final Streamed
          │      /process-turn               │      (No Vector Search)              │     Response[cite: 1]
          │                                  │                                      │
          ▼                                  ▼                                      │
┌───────────────────────────┐      ┌──────────────────────────────────┐             │
│   LONG-TERM MEMORY-API    │      │    SHORT-TERM SESSION MEMORY     │             │
│         (main.py)         │     │   (Chronological Sliding Window) │[cite: 1]     │
└─────────┬─────────────────┘      └─────────────────┬────────────────┘             │
          │                                          │                              │
          ▼ [Vector Engine Scan]                     ▼ [Database Slice]             │
   Takes current query and                    Queries core DB for the               │
   performs a pgvector cosine                 absolute **Last 10 Messages**         │
   distance search across the                 associated with this session          │
   entire historical archive.        ID chronologically[cite: 1].          │
          │                                          │                              │
          ▼                                          ▼                              │
┌───────────────────────────┐      ┌──────────────────────────────────┐             │
│ Outputs:                  │      │ Outputs:                         │             │
│ Top 3 Summary Blocks      │     │ Exact Chat Transcript            │[cite: 1]             │
│ ("Recent Lessons & Prefs")│      │ (Preserves immediate context)    │             │
└─────────┬─────────────────┘      └─────────────────┬────────────────┘             │
          │                                          │                              │
          └───────────────────┬──────────────────────┘                              │
                              │                                                     │
                              ▼ Combined Memory Inputs                              │
               ┌──────────────────────────────┐                                     │
               │    Knowledge Base Search     │                                     │
               │ (Fetches Grounding Documents)│[cite: 1]                                    │
               └──────────────┬───────────────┘                                     │
                              │                                                     │
                              ▼                                                     │
               ┌──────────────────────────────┐                                     │
               │   COMPLETE PACKAGED PROMPT   │                                     │
               │                              │                                     │
               │  [Long-Term Injections]      │[cite: 1]                                 │
               │              +               │                                     │
               │  [Last 10 Chat History]      │[cite: 1]                                    │
               │              +               │                                     │
               │  [Current Active Query]      │[cite: 1]                                    │
               │              +               │                                     │
               │  [Retrieved KB Documents]    │[cite: 1]                                    │
               └──────────────┬───────────────┘                                     │
                              │                                                     │
                              ▼ (4) Evaluates whole package                         │
               ┌──────────────────────────────┐                                     │
               │      Core Inference LLM      │─────────────────────────────────────┘
               │  (Resolves dependencies and  │
               │   generates the response)    │[cite: 1]
               └──────────────────────────────┘