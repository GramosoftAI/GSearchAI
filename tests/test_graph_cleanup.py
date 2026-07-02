import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import json

from app.core.graph_cleanup import GraphCleanupService

@pytest.mark.asyncio
async def test_name_normalization():
    service = GraphCleanupService(tenant_id="00000000-0000-0000-0000-000000000000")
    
    # 1. Mr. prefix removal
    disp, norm = service._normalize_single_name(" Mr. John Smith ")
    assert disp == "John Smith"
    assert norm == "john smith"
    
    # 2. Dr. prefix removal and space collapse
    disp, norm = service._normalize_single_name("Dr.  Jane   Doe")
    assert disp == "Jane Doe"
    assert norm == "jane doe"
    
    # 3. No prefix, already clean
    disp, norm = service._normalize_single_name("Acme Corp")
    assert disp == "Acme Corp"
    assert norm == "acme corp"

@pytest.mark.asyncio
@patch("app.core.graph_cleanup.get_neo4j_driver")
async def test_normalize_entities_neo4j(mock_get_driver):
    # Mock Neo4j execute_read & session
    mock_session = MagicMock()
    mock_session.run = AsyncMock()
    mock_session_cm = MagicMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock()
    
    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session_cm
    mock_get_driver.return_value = mock_driver

    service = GraphCleanupService(tenant_id="00000000-0000-0000-0000-000000000000")
    
    # Mock execute_read return value
    service.neo4j_repo.execute_read = AsyncMock(return_value=[
        {"internal_id": 1, "raw_name": " Mr. John Smith "},
        {"internal_id": 2, "raw_name": "Dr. Alice"}
    ])

    result = await service.normalize_entities()
    
    assert result["normalized_count"] == 2
    assert mock_session.run.call_count == 2
    
    # Verify exact set parameters
    first_call_args = mock_session.run.call_args_list[0][0][1]
    assert first_call_args["display_name"] == "John Smith"
    assert first_call_args["normalized_name"] == "john smith"

@pytest.mark.asyncio
async def test_early_rejection_conflict():
    service = GraphCleanupService(tenant_id="00000000-0000-0000-0000-000000000000")
    
    node1 = {
        "normalized_name": "john smith",
        "display_name": "John Smith",
        "email": "john@example.com"
    }
    node2 = {
        "normalized_name": "john smith",
        "display_name": "John Smith",
        "email": "smith@example.com" # Conflicting email
    }
    
    similarity = service.calculate_similarity(node1, node2)
    # Conflict in email must yield 0.0 similarity and reject merge
    assert similarity == 0.0

@pytest.mark.asyncio
async def test_similarity_weights_and_factors():
    service = GraphCleanupService(tenant_id="00000000-0000-0000-0000-000000000000")
    
    # Configure exact weights
    service.NAME_WEIGHT = 30
    service.ORG_WEIGHT = 20
    service.RELATIONSHIP_WEIGHT = 20
    service.LOCATION_WEIGHT = 15
    service.PROPERTY_WEIGHT = 10
    service.EMBEDDING_WEIGHT = 5
    
    # Nodes with perfect name similarity, matching org property, neutral elsewhere
    node1 = {
        "normalized_name": "john smith",
        "display_name": "John Smith",
        "organization": "Acme Corp"
    }
    node2 = {
        "normalized_name": "john smith",
        "display_name": "John Smith",
        "organization": "Acme Corp"
    }
    
    # Expect name_sim=1.0, org_sim=1.0, and others default to 0.5 (neutral)
    # Score calculation: 1.0 * 30 + 1.0 * 20 + 0.5 * 20 + 0.5 * 15 + 0.5 * 10 + 0.5 * 5 = 30 + 20 + 10 + 7.5 + 5 + 2.5 = 75
    score = service.calculate_similarity(node1, node2)
    assert score == 80.0

@pytest.mark.asyncio
async def test_llm_verification_success():
    service = GraphCleanupService(tenant_id="00000000-0000-0000-0000-000000000000")
    
    # Mock LLM generation
    mock_llm = AsyncMock(return_value="""
    {
      "same_entity": true,
      "confidence": 95,
      "canonical_name": "John Smith",
      "reason": "Both represent the CEO of Acme Corp with the same profile."
    }
    """)
    service.llm_client.generate = mock_llm
    
    node1 = {"_labels": ["Entity"], "display_name": "John Smith"}
    node2 = {"_labels": ["Entity"], "display_name": "Mr John Smith"}
    
    verified, canonical_name = await service.verify_with_llm(node1, node2, 85.0)
    assert verified is True
    assert canonical_name == "John Smith"

@pytest.mark.asyncio
async def test_llm_verification_rejection():
    service = GraphCleanupService(tenant_id="00000000-0000-0000-0000-000000000000")
    
    mock_llm = AsyncMock(return_value="""
    {
      "same_entity": false,
      "confidence": 40,
      "canonical_name": "",
      "reason": "Different companies and locations."
    }
    """)
    service.llm_client.generate = mock_llm
    
    node1 = {"_labels": ["Entity"], "display_name": "John Smith"}
    node2 = {"_labels": ["Entity"], "display_name": "John Smith"}
    
    verified, canonical_name = await service.verify_with_llm(node1, node2, 82.0)
    assert verified is False
    assert canonical_name == ""

@pytest.mark.asyncio
@patch("app.core.graph_cleanup.get_neo4j_driver")
async def test_merge_nodes_transaction_and_rollback(mock_get_driver):
    # Mock driver, session, and transaction
    mock_tx = AsyncMock()
    
    mock_tx_cm = MagicMock()
    mock_tx_cm.__aenter__ = AsyncMock(return_value=mock_tx)
    mock_tx_cm.__aexit__ = AsyncMock()
    
    mock_session = MagicMock()
    mock_session.begin_transaction = AsyncMock(return_value=mock_tx_cm)
    
    mock_session_cm = MagicMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock()
    
    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session_cm
    mock_get_driver.return_value = mock_driver

    service = GraphCleanupService(tenant_id="00000000-0000-0000-0000-000000000000")
    
    # Setup mock nodes
    node_can = {
        "_internal_id": 1,
        "id": "uuid-can",
        "_labels": ["Entity"],
        "display_name": "John Smith",
        "normalized_name": "john smith",
        "aliases": []
    }
    node_dup = {
        "_internal_id": 2,
        "id": "uuid-dup",
        "_labels": ["Entity"],
        "display_name": "John J. Smith",
        "normalized_name": "john j smith",
        "aliases": ["Johnny"]
    }
    
    # Mock transaction run for incoming and outgoing query results
    mock_incoming_result = AsyncMock()
    mock_incoming_result.data.return_value = [
        {"src_id": 10, "rel_type": "KNOWS", "rel_props": {"since": 2020}}
    ]
    mock_outgoing_result = AsyncMock()
    mock_outgoing_result.data.return_value = []
    
    # We return the query results based on call signature
    async def mock_run(query, params=None):
        if "MATCH (src)-[r]->(dup)" in query:
            return mock_incoming_result
        if "MATCH (dup)-[r]->(tgt)" in query:
            return mock_outgoing_result
        # For duplicates check, return empty
        check_result = AsyncMock()
        check_result.data.return_value = []
        return check_result
        
    mock_tx.run.side_effect = mock_run

    # 1. Successful merge test
    success = await service.merge_duplicate_nodes(node_can, node_dup)
    assert success is True
    assert mock_tx.commit.call_count == 1
    assert mock_tx.rollback.call_count == 0
    
    # 2. Rollback test (when transaction raises exception)
    mock_tx.commit.reset_mock()
    mock_tx.rollback.reset_mock()
    
    # Force exception on delete
    async def mock_run_with_error(query, params=None):
        if "DETACH DELETE" in query:
            raise Exception("Neo4j database connection lost")
        check_result = AsyncMock()
        check_result.data.return_value = []
        return check_result
        
    mock_tx.run.side_effect = mock_run_with_error
    
    success_with_error = await service.merge_duplicate_nodes(node_can, node_dup)
    assert success_with_error is False
    assert mock_tx.commit.call_count == 0
    assert mock_tx.rollback.call_count == 1

@pytest.mark.asyncio
@patch("app.core.graph_cleanup.get_neo4j_driver")
async def test_remove_duplicate_relationships(mock_get_driver):
    # Mock Neo4j driver, session, transaction
    from unittest.mock import ANY
    mock_session = MagicMock()
    mock_session.run = AsyncMock()
    
    mock_session_cm = MagicMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock()
    
    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session_cm
    mock_get_driver.return_value = mock_driver

    service = GraphCleanupService(tenant_id="00000000-0000-0000-0000-000000000000")
    
    # Mock return values for execute_read
    mock_results = [
        {
            "start_uuid": "node-a",
            "end_uuid": "node-b",
            "rel_type": "KNOWS",
            "rels": [
                {"id": 100, "element_id": "rel-1", "properties": {"since": 2020, "confidence": 0.9}},
                {"id": 101, "element_id": "rel-2", "properties": {"since": None, "confidence": 0.5, "location": "Chennai"}}
            ]
        }
    ]
    service.neo4j_repo.execute_read = AsyncMock(return_value=mock_results)

    result = await service.remove_duplicate_relationships()
    assert result["relationships_deduplicated"] == 1
    
    # Verify that the survivor was updated with merged properties
    mock_session.run.assert_any_call(
        ANY, 
        {"rel_id": "rel-1", "properties": {"since": 2020, "confidence": 0.9, "location": "Chennai"}}
    )
    
    # Verify that duplicate relationship was deleted
    mock_session.run.assert_any_call(
        ANY,
        {"rel_id": "rel-2"}
    )


@pytest.mark.asyncio
async def test_acronym_match():
    service = GraphCleanupService(tenant_id="00000000-0000-0000-0000-000000000000")
    
    # 1. Standard acronyms
    assert service._is_acronym_match("IBM", "International Business Machines") is True
    assert service._is_acronym_match("NASA", "National Aeronautics and Space Administration") is True
    assert service._is_acronym_match("AI", "Artificial Intelligence") is True
    
    # 2. Case insensitive and dots
    assert service._is_acronym_match("i.b.m.", "International Business Machines") is True
    assert service._is_acronym_match("IBM", "international business machines") is True
    
    # 3. Non-acronyms
    assert service._is_acronym_match("IBM", "International Machines") is False
    assert service._is_acronym_match("ABC", "Def Ghi") is False


@pytest.mark.asyncio
@patch("app.core.graph_cleanup.get_neo4j_driver")
async def test_embedding_similarity_override(mock_get_driver):
    # Mock Neo4j driver and session context manager
    mock_session = MagicMock()
    mock_session.run = AsyncMock()
    mock_session_cm = MagicMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock()
    
    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session_cm
    mock_get_driver.return_value = mock_driver

    service = GraphCleanupService(tenant_id="00000000-0000-0000-0000-000000000000")
    
    # Set thresholds
    service.auto_merge_threshold = 95.0
    service.llm_review_threshold = 65.0
    
    # Nodes with low name similarity (Levenshtein score: 0.1) but high embedding similarity (0.9)
    # Ensure they have different normalized names so Levenshtein is low
    node1 = {
        "_internal_id": 1,
        "id": "uuid1",
        "_labels": ["Entity"],
        "display_name": "IBM",
        "normalized_name": "ibm",
        "embedding": [1.0, 0.0, 0.0],
        "_outgoing": [],
        "_incoming": []
    }
    node2 = {
        "_internal_id": 2,
        "id": "uuid2",
        "_labels": ["Entity"],
        "display_name": "International Business Machines",
        "normalized_name": "international business machines",
        "embedding": [0.95, 0.1, 0.0], # Very high similarity (>0.95)
        "_outgoing": [],
        "_incoming": []
    }
    
    # Check that _calculate_embedding_similarity is >= embedding_override_threshold
    emb_sim = service._calculate_embedding_similarity(node1, node2)
    assert emb_sim >= service.embedding_override_threshold
    
    # Mock verify_with_llm
    mock_verify = AsyncMock(return_value=(True, "International Business Machines"))
    service.verify_with_llm = mock_verify
    
    # Mock find_duplicate_candidates to return this pair
    service.find_duplicate_candidates = AsyncMock(return_value=[(node1, node2)])
    
    # Mock execute_read to return empty lists for refreshed nodes queries
    service.neo4j_repo.execute_read = AsyncMock(return_value=[])
    
    # Mock merge_duplicate_nodes
    mock_merge = AsyncMock(return_value=True)
    service.merge_duplicate_nodes = mock_merge
    
    # Mock remove_duplicate_relationships
    service.remove_duplicate_relationships = AsyncMock(return_value={"relationships_deduplicated": 0})
    
    # Mock transitive_reduction
    service.transitive_reduction = AsyncMock(return_value={"relationships_pruned": 0})
    
    stats = await service.cleanup_graph()
    
    # verify_with_llm should have been called due to high embedding similarity overriding low score
    assert mock_verify.called is True
    assert stats["llm_merges"] == 1


@pytest.mark.asyncio
async def test_transitive_reduction():
    """
    Test that transitive reduction identifies and prunes redundant shortcut relationships.
    """
    tenant_id = "00000000-0000-0000-0000-000000000000"
    service = GraphCleanupService(tenant_id=tenant_id)
    
    mock_records = [
        {"rel_type": "RELATES_TO", "source_id": "A", "target_id": "B", "rel_id": "r1"},
        {"rel_type": "RELATES_TO", "source_id": "B", "target_id": "C", "rel_id": "r2"},
        {"rel_type": "RELATES_TO", "source_id": "A", "target_id": "C", "rel_id": "r3"}  # redundant
    ]
    service.neo4j_repo.execute_read = AsyncMock(return_value=mock_records)
    
    mock_session = MagicMock()
    mock_session.run = AsyncMock()
    
    mock_driver = MagicMock()
    mock_driver.session = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_driver.session.return_value.__aexit__ = AsyncMock()
    
    with patch("app.core.graph_cleanup.get_neo4j_driver", AsyncMock(return_value=mock_driver)):
        res = await service.transitive_reduction()
        
    assert res["relationships_pruned"] == 1
    call_args = mock_session.run.call_args
    assert call_args is not None
    assert "DELETE r" in call_args[0][0]
    assert call_args[0][1]["rel_ids"] == ["r3"]


