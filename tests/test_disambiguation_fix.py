import asyncio
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.modules.database_knowledgebase.disambiguation.extractor import EntityExtractor
from app.modules.database_knowledgebase.disambiguation.collision_detector import CollisionDetector
from app.modules.database_knowledgebase.schemas.canonical import DatabaseSchema, SchemaInfo, TableSchema, ColumnSchema, ColumnDataType


@pytest.mark.asyncio
async def test_extractor_domain_words_excluded():
    """Verify generic domain nouns and stop words are strictly excluded."""
    query = "how many employees are absent today or on leave with eod progress attendance"
    candidates = await EntityExtractor.extract_person_names(query)
    assert candidates == [], f"Expected empty candidates, got: {candidates}"


@pytest.mark.asyncio
async def test_extractor_schema_and_alias_exclusion():
    """Verify table names, column names, and aliases are excluded even if not in stop words."""
    schema = DatabaseSchema(
        database_name="test_db",
        schemas={
            "public": SchemaInfo(
                schema_name="public",
                tables={
                    "custom_billing": TableSchema(
                        table_name="custom_billing",
                        columns={
                            "invoice_num": ColumnSchema(name="invoice_num", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
                            "payout_code": ColumnSchema(name="payout_code", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
                        }
                    )
                }
            )
        }
    )
    aliases = {"custom_billing": ["billing_alias", "cb_alias"]}
    
    query = "check custom_billing invoice_num cb_alias payout_code"
    candidates = await EntityExtractor.extract_person_names(
        query=query,
        canonical_schema=schema,
        aliases=aliases,
    )
    assert candidates == [], f"Expected schema/alias terms to be excluded, got: {candidates}"


@pytest.mark.asyncio
async def test_extractor_drops_unindexed_tokens():
    """Verify that tokens surviving stop words are dropped if not in kb2_entity_values."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # Not found in kb2_entity_values
    mock_session.execute.return_value = mock_result

    kb_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    query = "tell me Foobarbaz info"

    candidates = await EntityExtractor.extract_person_names(
        query=query,
        session=mock_session,
        tenant_id=tenant_id,
        kb_id=kb_id,
    )
    assert candidates == [], f"Expected Foobarbaz to be dropped because not in kb2_entity_values, got: {candidates}"


@pytest.mark.asyncio
async def test_extractor_retains_indexed_names():
    """Verify that tokens matching kb2_entity_values are retained as candidates."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = uuid.uuid4()  # Found in kb2_entity_values
    mock_session.execute.return_value = mock_result

    kb_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    query = "tell me Arun N yesterday progress"

    candidates = await EntityExtractor.extract_person_names(
        query=query,
        session=mock_session,
        tenant_id=tenant_id,
        kb_id=kb_id,
    )
    assert "Arun" in candidates, f"Expected Arun to be retained, got: {candidates}"


@pytest.mark.asyncio
async def test_collision_detector_local_no_match():
    """Verify that CollisionDetector returns None when candidate is not in local kb2_entity_values."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []  # 0 rows in kb2_entity_values
    mock_session.execute.return_value = mock_result

    schema = DatabaseSchema(
        database_name="test_db",
        schemas={
            "public": SchemaInfo(
                schema_name="public",
                tables={
                    "employees": TableSchema(
                        table_name="employees",
                        columns={
                            "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="int", is_primary_key=True),
                            "name": ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
                        }
                    )
                }
            )
        }
    )
    kb_entity = MagicMock(id=uuid.uuid4(), tenant_id=uuid.uuid4(), settings={})

    res = await CollisionDetector.check_for_user_collisions(
        extracted_name="UnknownPerson",
        kb_entity=kb_entity,
        canonical_schema=schema,
        session=mock_session,
    )
    assert res is None, f"Expected None for no match, got: {res}"


@pytest.mark.asyncio
async def test_collision_detector_local_single_match():
    """Verify that CollisionDetector returns resolved entity from local kb2_entity_values."""
    mock_record = MagicMock(
        raw_value="Arun N",
        normalized_value="arun n",
        table_name="employees",
        column_name="name",
    )
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_record]
    mock_session.execute.return_value = mock_result

    schema = DatabaseSchema(
        database_name="test_db",
        schemas={
            "public": SchemaInfo(
                schema_name="public",
                tables={
                    "employees": TableSchema(
                        table_name="employees",
                        columns={
                            "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="int", is_primary_key=True),
                            "name": ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
                        }
                    )
                }
            )
        }
    )
    kb_entity = MagicMock(id=uuid.uuid4(), tenant_id=uuid.uuid4(), settings={})

    res = await CollisionDetector.check_for_user_collisions(
        extracted_name="Arun",
        kb_entity=kb_entity,
        canonical_schema=schema,
        session=mock_session,
    )
    assert res is not None
    assert res["ids"] == "Arun N"
    assert res["table"] == "employees"
    assert res["pk_column"] == "name"
    assert res["is_multiple"] is False


@pytest.mark.asyncio
async def test_collision_detector_local_multiple_match():
    """Verify that CollisionDetector returns multiple collision when multiple entity values match."""
    rec1 = MagicMock(raw_value="Arun Kumar", normalized_value="arun kumar", table_name="employees", column_name="name")
    rec2 = MagicMock(raw_value="Arun Sharma", normalized_value="arun sharma", table_name="employees", column_name="name")
    
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [rec1, rec2]
    mock_session.execute.return_value = mock_result

    schema = DatabaseSchema(
        database_name="test_db",
        schemas={
            "public": SchemaInfo(
                schema_name="public",
                tables={
                    "employees": TableSchema(
                        table_name="employees",
                        columns={
                            "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="int", is_primary_key=True),
                            "name": ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
                        }
                    )
                }
            )
        }
    )
    kb_entity = MagicMock(id=uuid.uuid4(), tenant_id=uuid.uuid4(), settings={})

    res = await CollisionDetector.check_for_user_collisions(
        extracted_name="Arun",
        kb_entity=kb_entity,
        canonical_schema=schema,
        session=mock_session,
    )
    assert res is not None
    assert res["is_multiple"] is True
    assert "Arun Kumar" in res["ids"]
    assert "Arun Sharma" in res["ids"]
