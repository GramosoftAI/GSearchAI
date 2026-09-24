# Release Notes: Document Ingestion & Retrieval Testing

## Overview
This release focuses on testing and validating the ingestion pipeline and retrieval accuracy across multiple document formats.

## Supported Formats Tested
- **PDF** (`.pdf`)
- **CSV** (`.csv`)
- **Markdown** (`.md`)
- **Text** (`.txt`)
- **Word Document** (`.docx`)
- **Web URL** (HTML to Text)

## Testing Objectives
1. **Ingestion Validation:** Verify all formats can be successfully uploaded, parsed, chunked, and embedded into the vector database.
2. **Timing Measurement:** Measure the time taken to ingest files and URLs to establish baseline performance metrics.
3. **Response Accuracy:** Evaluate the quality and relevance of RAG responses based on the ingested content from different source types.

