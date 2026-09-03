import logging
import json
from sqlalchemy import select
from uuid import UUID

from app.modules.knowledge_bases.models import KnowledgeBase, DocumentChunk, DocumentTableRow
from app.core.embeddings import EmbeddingGenerator
from app.core.llm.deepinfra_llm import DeepInfraLLMClient

logger = logging.getLogger(__name__)

async def generate_kb_summary_embedding(kb_id: str, db) -> None:
    """Generates a summary for a KB based on its first few chunks/rows, embeds it, and saves it."""
    try:
        # Fetch the KB
        kb_uuid = UUID(kb_id) if isinstance(kb_id, str) else kb_id
        stmt_kb = select(KnowledgeBase).where(KnowledgeBase.id == kb_uuid)
        result_kb = await db.execute(stmt_kb)
        kb = result_kb.scalar_one_or_none()
        
        if not kb:
            logger.error(f"Cannot generate summary embedding: KB {kb_id} not found.")
            return

        # Try fetching text chunks first
        stmt = select(DocumentChunk.text).where(
            DocumentChunk.kb_id == kb_uuid
        ).order_by(DocumentChunk.chunk_index.asc()).limit(5)
        
        result = await db.execute(stmt)
        chunks = result.scalars().all()
        
        document_text = ""
        if chunks:
            document_text = "\n\n".join(chunks)
        else:
            # If no chunks, try fetching table rows (for CSV/Excel)
            stmt_rows = select(DocumentTableRow.row_data).where(
                DocumentTableRow.kb_id == kb_uuid
            ).order_by(DocumentTableRow.row_index.asc()).limit(5)
            
            result_rows = await db.execute(stmt_rows)
            rows = result_rows.scalars().all()
            
            if rows:
                row_strs = [json.dumps(r) for r in rows if r]
                document_text = "\n".join(row_strs)
                
        if not document_text:
            logger.warning(f"KB {kb.id} ({kb.name}) has no chunks or rows. Falling back to filename-only summary.")
            document_text = f"This is a structured dataset or file named {kb.name}. The content is stored externally (e.g. as parquet or s3 path) and is not available in chunk form."
            
        # Use a fast LLM call to summarize the document
        prompt = f"""
        You are an expert indexer. Summarize the following document accurately in 2-3 sentences.
        Focus strictly on the core topics, entities, and purpose of the document so a search engine can route queries to it.
        
        Title: {kb.name}
        Content Excerpt:
        {document_text[:4000]}
        
        Summary:
        """
        
        logger.info(f"Generating summary for KB: {kb.name} ({kb.id})")
        llm = DeepInfraLLMClient()
        summary = await llm.generate(prompt, temperature=0.0)
        
        logger.info(f"Generated Summary: {summary.strip()}")
        
        # Generate the semantic centroid embedding
        logger.info(f"Generating embedding for KB summary...")
        embedding, _ = await EmbeddingGenerator.generate_embedding_with_usage(f"Title: {kb.name}\nSummary: {summary.strip()}")
        
        # Save to DB
        kb.summary_embedding = embedding
        db.add(kb)
        await db.commit()
        logger.info(f"Successfully generated and saved summary_embedding for KB: {kb.name}")
        
    except Exception as e:
        logger.error(f"Failed to generate summary embedding for KB {kb_id}: {e}", exc_info=True)
        # Re-raise so caller can handle/log it properly
        raise
