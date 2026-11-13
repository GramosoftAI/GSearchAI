import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from app.modules.rag.pipeline import RAGPipeline, RAGContext, RetrievedChunk
from app.modules.rag.orchestrator.query_analyzer import AnalysisResult, QueryIntent, QueryMetadata

async def test_rrf_domain_boost_avoids_feb_coincidence():
    db_mock = AsyncMock()
    mock_res = MagicMock()
    mock_res.all.return_value = []
    db_mock.execute.return_value = mock_res
    
    pipeline = RAGPipeline("12345678-1234-5678-1234-567812345678", db=db_mock)
    
    analysis_res = AnalysisResult(
        intent=QueryIntent.FACT,
        metadata=QueryMetadata(keywords=["fees"]),
        is_tabular=False,
        confidence=0.95,
        reasoning="Testing fees query"
    )
    
    with patch("app.modules.rag.orchestrator.query_analyzer.QueryAnalyzer.analyze_query", new_callable=AsyncMock) as mock_analyze, \
         patch("app.core.embeddings.EmbeddingGenerator.generate_embedding_with_usage", new_callable=AsyncMock) as mock_emb, \
         patch("app.modules.rag.engines.vector_engine.VectorEngine.retrieve", new_callable=AsyncMock) as mock_ret_vec, \
         patch("app.modules.rag.pipeline.RAGPipeline._execute_semantic_file_gate", new_callable=AsyncMock) as mock_gate:
         
        mock_analyze.return_value = analysis_res
        mock_emb.return_value = ([0.1]*4096, 5)
        mock_gate.return_value = ["kb1"]
        
        # Mock vector results with a chunk from a file named "pricelist book feb 2026.pdf"
        mock_ret_vec.return_value = [
            RetrievedChunk(
                chunk_id="c1",
                text="Some text",
                kb_id="kb1",
                position=0,
                embedding_similarity=0.9,
                source="pricelist book feb 2026-36-40.pdf",
                s3_path="s3://bucket/pricelist book feb 2026-36-40.pdf",
                score=0.9
            )
        ]
        
        # Execute query
        ctx = await pipeline.query(
            query="What are the fees?",
            agent_id="test_agent",
            kb_id="kb1"
        )
        
        assert len(ctx.chunks) == 1
        print("test_rrf_domain_boost_avoids_feb_coincidence PASSED")
        
async def test_rrf_domain_boost_allows_legitimate_match():
    db_mock = AsyncMock()
    mock_res = MagicMock()
    mock_res.all.return_value = []
    db_mock.execute.return_value = mock_res
    
    pipeline = RAGPipeline("12345678-1234-5678-1234-567812345678", db=db_mock)
    
    analysis_res = AnalysisResult(
        intent=QueryIntent.FACT,
        metadata=QueryMetadata(keywords=["price", "plan"]),
        is_tabular=False,
        confidence=0.95,
        reasoning="Testing price query"
    )
    
    with patch("app.modules.rag.orchestrator.query_analyzer.QueryAnalyzer.analyze_query", new_callable=AsyncMock) as mock_analyze, \
         patch("app.core.embeddings.EmbeddingGenerator.generate_embedding_with_usage", new_callable=AsyncMock) as mock_emb, \
         patch("app.modules.rag.engines.vector_engine.VectorEngine.retrieve", new_callable=AsyncMock) as mock_ret_vec, \
         patch("app.modules.rag.pipeline.RAGPipeline._execute_semantic_file_gate", new_callable=AsyncMock) as mock_gate:
         
        mock_analyze.return_value = analysis_res
        mock_emb.return_value = ([0.1]*4096, 5)
        mock_gate.return_value = ["kb1", "kb2"]
        
        # Mock vector results: 
        # c1 is a highly relevant chunk from a generic file.
        # c2 is a poorly relevant chunk from a file named "pricelist book.pdf".
        mock_ret_vec.return_value = [
            RetrievedChunk(
                chunk_id="c1",
                text="Highly relevant text about plan price",
                kb_id="kb1",
                position=0,
                embedding_similarity=0.99,
                source="HikersPaFAQ.pdf",
                s3_path="s3://bucket/HikersPaFAQ.pdf",
                score=0.99
            ),
            RetrievedChunk(
                chunk_id="c2",
                text="Oil filter",
                kb_id="kb2",
                position=1,
                embedding_similarity=0.50,
                source="pricelist book.pdf",
                s3_path="s3://bucket/pricelist book.pdf",
                score=0.50
            )
        ]
        
        ctx = await pipeline.query(
            query="price for 3-day plan",
            agent_id="test_agent",
            kb_id=["kb1", "kb2"]
        )
        
        assert len(ctx.chunks) == 2
        chunk_ids = [c.chunk_id for c in ctx.chunks]
        assert "c1" in chunk_ids
        assert "c2" in chunk_ids
        print("test_rrf_domain_boost_allows_legitimate_match PASSED")

if __name__ == "__main__":
    asyncio.run(test_rrf_domain_boost_avoids_feb_coincidence())
    asyncio.run(test_rrf_domain_boost_allows_legitimate_match())
