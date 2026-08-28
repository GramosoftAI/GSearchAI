import asyncio
from sqlalchemy import text
from app.core.database import engine

async def main():
    async with engine.begin() as conn:
        print("Adding columns to users...")
        user_columns = [
            ("preferred_llm_model", "VARCHAR(255)"),
        ]
        for col_name, col_type in user_columns:
            try:
                await conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col_name} {col_type}"))
            except Exception as e:
                print(f"  Note on user.{col_name}: {e}")

        print("Adding columns to analytics_query_logs...")
        aql_columns = [
            ("request_id", "VARCHAR(255)"),
            ("model_name", "VARCHAR(255)"),
            ("total_tokens", "INTEGER DEFAULT 0 NOT NULL"),
            ("llm_input_tokens", "INTEGER DEFAULT 0 NOT NULL"),
            ("llm_output_tokens", "INTEGER DEFAULT 0 NOT NULL"),
            ("embedding_tokens", "INTEGER DEFAULT 0 NOT NULL"),
            ("llm_cost_usd", "DOUBLE PRECISION DEFAULT 0.0 NOT NULL"),
            ("embedding_cost_usd", "DOUBLE PRECISION DEFAULT 0.0 NOT NULL"),
            ("total_cost_usd", "DOUBLE PRECISION DEFAULT 0.0 NOT NULL"),
            ("user_id", "UUID REFERENCES users(id) ON DELETE SET NULL")
        ]
        for col_name, col_type in aql_columns:
            try:
                await conn.execute(text(f"ALTER TABLE analytics_query_logs ADD COLUMN IF NOT EXISTS {col_name} {col_type}"))
            except Exception as e:
                print(f"  Note on {col_name}: {e}")
        
        print("Adding columns to document_chunks...")
        dc_columns = [
            ("section", "VARCHAR")
        ]
        for col_name, col_type in dc_columns:
            try:
                await conn.execute(text(f"ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS {col_name} {col_type}"))
            except Exception as e:
                print(f"  Note on {col_name}: {e}")
        
        print("Adding columns to document_ingestion_runs...")
        dir_columns = [
            ("chunk_count", "INTEGER DEFAULT 0 NOT NULL"),
            ("entity_count", "INTEGER DEFAULT 0 NOT NULL"),
            ("triplet_count", "INTEGER DEFAULT 0 NOT NULL"),
            ("identifier_count", "INTEGER DEFAULT 0 NOT NULL"),
            ("extractor_version", "VARCHAR(50) DEFAULT 'unified_extractor_v1'"),
            ("schema_version", "VARCHAR(50) DEFAULT '1.0'"),
            ("model_name", "VARCHAR(100) DEFAULT 'deepseek-v3'"),
            ("repair_count", "INTEGER DEFAULT 0 NOT NULL"),
            ("retry_count", "INTEGER DEFAULT 0 NOT NULL"),
            ("fallback_count", "INTEGER DEFAULT 0 NOT NULL"),
            ("llm_calls", "INTEGER DEFAULT 0 NOT NULL"),
            ("llm_input_tokens", "INTEGER DEFAULT 0 NOT NULL"),
            ("llm_output_tokens", "INTEGER DEFAULT 0 NOT NULL"),
            ("embedding_tokens", "INTEGER DEFAULT 0 NOT NULL"),
            ("embedding_cost_usd", "DOUBLE PRECISION DEFAULT 0.0 NOT NULL"),
            ("extraction_duration_ms", "INTEGER DEFAULT 0 NOT NULL"),
            ("graph_write_duration_ms", "INTEGER DEFAULT 0 NOT NULL"),
            ("total_duration_ms", "INTEGER DEFAULT 0 NOT NULL"),
            ("nodes_created", "INTEGER DEFAULT 0 NOT NULL"),
            ("relationships_created", "INTEGER DEFAULT 0 NOT NULL"),
            ("nodes_merged", "INTEGER DEFAULT 0 NOT NULL"),
            ("relationships_merged", "INTEGER DEFAULT 0 NOT NULL"),
            ("fluff_chunks_skipped", "INTEGER DEFAULT 0 NOT NULL"),
            ("processed_chunks", "INTEGER DEFAULT 0 NOT NULL"),
            ("routing_version", "VARCHAR(50) DEFAULT '1.0'"),
            ("cache_hits", "INTEGER DEFAULT 0 NOT NULL"),
            ("kg_extraction_calls", "INTEGER DEFAULT 0 NOT NULL"),
            ("document_category", "VARCHAR(100) DEFAULT 'general_document' NOT NULL"),
            ("sample_entities", "JSON"),
            ("sample_triplets", "JSON"),
            ("baseline_entities_per_chunk", "DOUBLE PRECISION"),
            ("current_entities_per_chunk", "DOUBLE PRECISION"),
            ("deviation_percent", "DOUBLE PRECISION"),
            ("baseline_documents", "INTEGER"),
            ("fallback_chunks", "JSON"),
            ("status", "VARCHAR(50) DEFAULT 'IN_PROGRESS' NOT NULL"),
            ("error_message", "TEXT"),
        ]
        for col_name, col_type in dir_columns:
            try:
                await conn.execute(text(f"ALTER TABLE document_ingestion_runs ADD COLUMN IF NOT EXISTS {col_name} {col_type}"))
            except Exception as e:
                print(f"  Note on {col_name}: {e}")
        
        print("Adding columns to knowledge_bases...")
        kb_columns = [
            ("dataset_schema", "JSONB"),
            ("categorical_values", "JSONB"),
            ("noisy_words", "JSONB"),
            ("noisy_words_generated_at", "TIMESTAMP WITH TIME ZONE"),
            ("summary_embedding", "vector(4096)"),
            ("s3_path", "VARCHAR(1024)"),
            ("parsed_path", "VARCHAR(1024)"),
            ("file_hash", "VARCHAR(64)")
        ]
        for col_name, col_type in kb_columns:
            try:
                await conn.execute(text(f"ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS {col_name} {col_type}"))
            except Exception as e:
                print(f"  Note on knowledge_bases.{col_name}: {e}")

        print("Successfully updated database schema!")

if __name__ == "__main__":
    asyncio.run(main())
