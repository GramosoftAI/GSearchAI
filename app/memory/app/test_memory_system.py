import pytest
import httpx
import asyncio
import uuid

MEMORY_API_URL = "http://localhost:8002/api/v1/memory"

TENANT_ID = "test_tenant_demo"
USER_ID = f"user_{uuid.uuid4().hex[:6]}"
AGENT_ID = "agent_finance_bot"

SESSION_1 = f"session_alpha_{uuid.uuid4().hex[:4]}"
SESSION_2 = f"session_beta_{uuid.uuid4().hex[:4]}"
SESSION_3 = f"session_gamma_{uuid.uuid4().hex[:4]}"


async def wait_for_ingestion(client: httpx.AsyncClient, session_id: str, min_expected_turns: int, max_wait_sec: int = 120):
    """
    Polls process-turn until the background worker finishes embedding
    and saving the data into the database.
    """
    start = asyncio.get_event_loop().time()
    while (asyncio.get_event_loop().time() - start) < max_wait_sec:
        resp = await client.post(
            f"{MEMORY_API_URL}/process-turn",
            json={
                "query": "What were we discussing in our last session?",
                "session_id": f"temp_poll_{uuid.uuid4().hex[:4]}",
                "agent_id": AGENT_ID,
                "user_id": USER_ID,
                "tenant_id": TENANT_ID,
            },
        )
        if resp.status_code == 200:
            guidance = resp.json().get("guidance_context", "").lower()
            # Count how many item summaries have landed in the DB
            if guidance.count("user interacted regarding:") >= min_expected_turns:
                print(f"\n[OK] DB Ingestion complete ({min_expected_turns} turns processed).")
                return True
        await asyncio.sleep(4.0)

    raise RuntimeError(f"Timed out waiting {max_wait_sec}s for background ingestion of session {session_id}")


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.mark.asyncio
async def test_01_ingest_session_1_interactions():
    """Step 1: Ingest interactions into Session 1 and WAIT until DB commits them."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        # Turn A: Expense Policy
        resp1 = await client.post(
            f"{MEMORY_API_URL}/save-turn",
            json={
                "query": "What is the company policy for travel expense claims?",
                "ai_response": "Travel expense claims must be submitted within 14 days with itemized receipts for anything over $25.",
                "session_id": SESSION_1,
                "agent_id": AGENT_ID,
                "user_id": USER_ID,
                "tenant_id": TENANT_ID,
            },
        )
        assert resp1.status_code == 200

        # Turn B: Sarah Connor / Entity Fact
        resp2 = await client.post(
            f"{MEMORY_API_URL}/save-turn",
            json={
                "query": "Who approves my travel expenses?",
                "ai_response": "Sarah Connor is the Finance Manager in charge of travel expense approvals.",
                "session_id": SESSION_1,
                "agent_id": AGENT_ID,
                "user_id": USER_ID,
                "tenant_id": TENANT_ID,
            },
        )
        assert resp2.status_code == 200

        # Turn C: User Preference Statement
        resp3 = await client.post(
            f"{MEMORY_API_URL}/save-turn",
            json={
                "query": "Remember that I prefer bullet points in all your responses",
                "ai_response": "Understood, I will format all future responses using bullet points.",
                "session_id": SESSION_1,
                "agent_id": AGENT_ID,
                "user_id": USER_ID,
                "tenant_id": TENANT_ID,
                "is_feedback_only": True,
            },
        )
        assert resp3.status_code == 200

        print("\nWaiting for background workers to process turns into Postgres/Neo4j...")
        # Dynamically wait until at least 2 non-feedback turns land in the DB
        await wait_for_ingestion(client, SESSION_1, min_expected_turns=2, max_wait_sec=180)


@pytest.mark.asyncio
async def test_02_verify_meta_history_recall_in_new_session():
    """Step 2: Meta-History Structural Recall in Session 2."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{MEMORY_API_URL}/process-turn",
            json={
                "query": "What were we discussing in our last session?",
                "session_id": SESSION_2,
                "agent_id": AGENT_ID,
                "user_id": USER_ID,
                "tenant_id": TENANT_ID,
            },
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data.get("is_history_query") is True
        guidance = data.get("guidance_context", "").lower()

        print("\n--- [TEST 02] META HISTORY CONTEXT ---")
        print(guidance)
        print("--------------------------------------")

        assert "expense" in guidance or "travel" in guidance


@pytest.mark.asyncio
async def test_03_verify_cross_session_semantic_search():
    """Step 3: Concept-Based Vector Recall in Session 3."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{MEMORY_API_URL}/process-turn",
            json={
                "query": "How long do I have to submit my receipt?",
                "session_id": SESSION_3,
                "agent_id": AGENT_ID,
                "user_id": USER_ID,
                "tenant_id": TENANT_ID,
            },
        )
        assert resp.status_code == 200
        data = resp.json()

        guidance = data.get("guidance_context", "").lower()

        print("\n--- [TEST 03] SEMANTIC VECTOR CONTEXT ---")
        print(guidance)
        print("----------------------------------------")

        assert any(term in guidance for term in ["14 days", "expense", "receipt", "policy", "clai"])


@pytest.mark.asyncio
async def test_04_verify_knowledge_graph_fact_recall():
    """Step 4: Neo4j Triplet / Entity Recall in Session 3."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{MEMORY_API_URL}/process-turn",
            json={
                "query": "Tell me about Sarah Connor and her role",
                "session_id": SESSION_3,
                "agent_id": AGENT_ID,
                "user_id": USER_ID,
                "tenant_id": TENANT_ID,
            },
        )
        assert resp.status_code == 200
        data = resp.json()

        guidance = data.get("guidance_context", "").lower()

        print("\n--- [TEST 04] KNOWLEDGE GRAPH FACTS ---")
        print(guidance)
        print("---------------------------------------")

        assert any(term in guidance for term in ["sarah connor", "finance manager", "approves", "approval"])