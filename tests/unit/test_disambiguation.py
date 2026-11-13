
import pytest
from app.modules.database_knowledgebase.disambiguation.collision_detector import CollisionDetector
from app.modules.database_knowledgebase.disambiguation.rules_engine import RulesEngine
from app.modules.database_knowledgebase.disambiguation.exceptions import DisambiguationRequiredError
from unittest.mock import patch, MagicMock

@pytest.mark.asyncio
async def test_disambiguation_options_with_all_and_distinguishing_cols():
    # Mock schema, settings, connection, etc.
    canonical_schema = MagicMock()
    canonical_schema.schemas = {
        "public": MagicMock(columns={"id": MagicMock(name="id"), "login": MagicMock(name="login"), "email": MagicMock(name="email"), "department": MagicMock(name="department"), "password": MagicMock(name="password")})
    }
    
    kb_entity = MagicMock()
    kb_entity.settings = {}

    with patch("app.modules.database_knowledgebase.disambiguation.collision_detector.connect_to_database") as mock_conn:
        mock_db = MagicMock()
        mock_db.fetch.return_value = [
            {"id": 1, "login": "alice", "department": "engineering", "email": "alice@test.com"},
            {"id": 2, "login": "alice_smith", "department": "sales", "email": "alices@test.com"}
        ]
        mock_conn.return_value = mock_db

        with patch("app.modules.database_knowledgebase.disambiguation.collision_detector.CollisionDetector.discover_person_table_and_columns") as mock_disc:
            mock_disc.return_value = ("users", "id", ["login"], ["email", "department"])

            try:
                await CollisionDetector.check_for_user_collisions("alice", kb_entity, MagicMock())
                assert False, "Should have raised DisambiguationRequiredError"
            except DisambiguationRequiredError as e:
                assert len(e.options) == 3
                assert e.options[0]["id"] == 1
                assert "alice (email: alice@test.com, department: engineering)" in e.options[0]["label"]
                assert e.options[2]["label"] == "All 2 matches"
                assert e.options[2]["id"] == [1, 2]

def test_rules_engine_in_query():
    rules = RulesEngine.apply_glossary_rules([{"type": "user", "id": [1, 2]}], "alice details")
    assert any("IN (1, 2)" in r for r in rules)
