import pytest
import asyncio
import websockets
import json
import uuid

# These tests are designed to run against a live local instance of the application
# e.g., ws://localhost:8000/api/v1/embed/chats/{agent_id}/ws?tenant_id=...
# Ensure the backend is running before executing.

BASE_URL = "ws://localhost:8000/api/v1"
TEST_AGENT_ID = "00000000-0000-0000-0000-000000000000" # Replace with valid agent ID
TEST_TENANT_ID = "00000000-0000-0000-0000-000000000000" # Replace with valid tenant ID

@pytest.mark.asyncio
async def test_embed_format_boundary():
    """Test that the embed endpoint returns enveloped JSON format"""
    uri = f"{BASE_URL}/embed/chats/{TEST_AGENT_ID}/ws?tenant_id={TEST_TENANT_ID}"
    try:
        async with websockets.connect(uri) as websocket:
            # 1. We expect an initial session control message with vtoken
            vtoken_msg = await websocket.recv()
            vtoken_data = json.loads(vtoken_msg)
            assert vtoken_data.get("type") == "session"
            assert "vtoken" in vtoken_data
            
            # Send query
            await websocket.send(json.dumps({"message": "Hello!"}))
            
            # 2. We expect a start message
            start_msg = await websocket.recv()
            start_data = json.loads(start_msg)
            assert start_data.get("type") == "start"
            
            # 3. We expect content chunks
            chunk_msg = await websocket.recv()
            chunk_data = json.loads(chunk_msg)
            # The unified loop sends 'content' delta for tokens
            assert chunk_data.get("type") in ["content", "sources"]
            
    except websockets.exceptions.InvalidURI:
        pytest.skip("Test requires valid agent/tenant IDs and running server.")
    except ConnectionRefusedError:
        pytest.skip("Server not running.")

@pytest.mark.asyncio
async def test_visitor_identity_isolation():
    """Test that two connections without vtokens get distinct visitors"""
    uri = f"{BASE_URL}/embed/chats/{TEST_AGENT_ID}/ws?tenant_id={TEST_TENANT_ID}"
    try:
        async with websockets.connect(uri) as ws1:
            msg1 = json.loads(await ws1.recv())
            vtoken1 = msg1.get("vtoken")
            
        async with websockets.connect(uri) as ws2:
            msg2 = json.loads(await ws2.recv())
            vtoken2 = msg2.get("vtoken")
            
        assert vtoken1 is not None
        assert vtoken2 is not None
        assert vtoken1 != vtoken2 # Ensure they are distinct
        
    except websockets.exceptions.InvalidURI:
        pytest.skip("Test requires valid agent/tenant IDs and running server.")
    except ConnectionRefusedError:
        pytest.skip("Server not running.")
        
@pytest.mark.asyncio
async def test_dashboard_format_boundary():
    """Test that the dashboard endpoint returns raw text / metadata"""
    # Requires a valid JWT access token for authorization
    pytest.skip("Requires JWT Auth setup to test dashboard websocket")

def test_unified_chat_request_schema():
    from app.modules.rag.schemas import UnifiedChatRequest
    
    # 1. request with session_id
    payload1 = {"query": "hello", "session_id": "12345"}
    req1 = UnifiedChatRequest.from_raw(payload1)
    assert req1.session_id == "12345"
    assert req1.query == "hello"

    # 2. request with session_id=null
    payload2 = {"query": "who is rajesh", "file": None, "session_id": None, "embed": False}
    req2 = UnifiedChatRequest.from_raw(payload2)
    assert req2.session_id is None
    assert req2.query == "who is rajesh"

    # 3. request without session_id for backward compatibility
    payload3 = {"message": "hello"}
    req3 = UnifiedChatRequest.from_raw(payload3)
    assert req3.session_id is None
    assert req3.query == "hello"

