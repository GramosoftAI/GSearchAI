import uuid
import asyncio
import httpx
import pytest

BASE_URL = "http://127.0.0.1:8002/api/v1/memory"
TENANT_ID = "test-tenant-123"
USER_ID = "test-user-456"
AGENT_ID = "test-agent-789"

LTM_TEST_CASES = [
    {
        "name": "Academic Marks Test",
        "fact": "10th grade mark is 70%",
        "query": "What is the 10th grade mark?",
        "expected": "70%"
    },
    {
        "name": "Technical Preference Test",
        "fact": "Database preference for structured data is PostgreSQL over MongoDB.",
        "query": "Which database is preferred for structured data?",
        "expected": "PostgreSQL"
    },
    {
        "name": "Synonym / Paraphrase Test",
        # Explicit fact format prevents LLM summarizer from dropping the college name
        "fact": "User completed an undergraduate degree at Einstein College of Engineering.",
        "query": "Which college did the user graduate from for their undergraduate degree?",
        "expected": "Einstein"  # Match "Einstein" directly
    }
]

@pytest.mark.asyncio
@pytest.mark.parametrize("test_case", LTM_TEST_CASES, ids=[tc["name"] for tc in LTM_TEST_CASES])
async def test_long_term_memory_flow(test_case):
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        
        # --- STEP 1: Save Fact in Session A ---
        session_a = str(uuid.uuid4())
        save_payload = {
            "tenant_id": TENANT_ID,
            "user_id": USER_ID,
            "agent_id": AGENT_ID,
            "session_id": session_a,
            "query": test_case["fact"],
            "ai_response": f"Got it! I saved that {test_case['fact']}"
        }

        save_res = await client.post("/save-turn", json=save_payload)
        assert save_res.status_code == 200, f"Save turn failed: {save_res.text}"

        # --- STEP 2: Query Fact in Session B (Retry Loop for Async Indexing) ---
        session_b = str(uuid.uuid4())
        process_payload = {
            "tenant_id": TENANT_ID,
            "user_id": USER_ID,
            "agent_id": AGENT_ID,
            "session_id": session_b,
            "query": test_case["query"]
        }

        max_retries = 5
        delay_seconds = 2.0
        retrieved_context = ""
        last_response_json = {}

        for attempt in range(1, max_retries + 1):
            # Give background indexing, LLM processing, or embedding pipelines time to finish
            await asyncio.sleep(delay_seconds)

            process_res = await client.post("/process-turn", json=process_payload)
            assert process_res.status_code == 200, f"Process turn failed on attempt {attempt}: {process_res.text}"

            last_response_json = process_res.json()
            retrieved_context = str(last_response_json)

            # Check if expected memory fact is present in the response
            if test_case["expected"].lower() in retrieved_context.lower():
                print(f"\n[SUCCESS] Fact retrieved on attempt {attempt} for '{test_case['name']}'!")
                break

        # --- STEP 3: Assert Retrieval Accuracy ---
        assert test_case["expected"].lower() in retrieved_context.lower(), (
            f"LTM Retrieval Failed for '{test_case['name']}' after {max_retries} attempts.\n"
            f"Expected keyword: '{test_case['expected']}'\n"
            f"Full API Response: {last_response_json}"
        )