import httpx
import asyncio

# Target the newly exposed port 8002
MEMORY_API_URL = "http://localhost:8002/api/v1/memory"

# Mock variables
TEST_SESSION = "simulated_session_999"
TEST_USER = "user_123"
TEST_AGENT = "agent_456"
TEST_TENANT = "tenant_test"

async def test_pipeline():
    async with httpx.AsyncClient(timeout=60.0) as client:
        print("=== 1. SENDING RULE / INSTRUCTION ===")
        t1_query = "From now on, always add [SECURE] at the start of your answers."
        
        # Call process-turn (Expect is_feedback_only: True)
        print(f"Sending check for: '{t1_query}'...")
        r1 = await client.post(
            f"{MEMORY_API_URL}/process-turn",
            json={
                "query": t1_query,
                "session_id": TEST_SESSION,
                "agent_id": TEST_AGENT,
                "user_id": TEST_USER,
                "tenant_id": TEST_TENANT
            }
        )
        print(f"-> Process Response: {r1.json()}")
        
        # Save the transaction to vector database
        print("Saving rule to database...")
        s1 = await client.post(
            f"{MEMORY_API_URL}/save-turn",
            json={
                "query": t1_query,
                "ai_response": "Acknowledged and updated rules.",
                "session_id": TEST_SESSION,
                "agent_id": TEST_AGENT,
                "user_id": TEST_USER,
                "tenant_id": TEST_TENANT
            }
        )
        print(f"-> Save Status: {s1.json()}")
        
        print("\nWaiting 2 seconds for background DB commit...")
        await asyncio.sleep(2)

        print("\n=== 2. SENDING FOLLOW-UP QUERY ===")
        t2_query = "What is the capital of France?"
        print(f"Sending query: '{t2_query}'...")
        
        # Call process-turn again (Expect is_feedback_only: False, and guidance_context to be populated)
        r2 = await client.post(
            f"{MEMORY_API_URL}/process-turn",
            json={
                "query": t2_query,
                "session_id": TEST_SESSION,
                "agent_id": TEST_AGENT,
                "user_id": TEST_USER,
                "tenant_id": TEST_TENANT
            }
        )
        res_data = r2.json()
        print(f"-> Process Response: {res_data}")
        
        print("\n=== VERIFICATION RESULT ===")
        context = res_data.get("guidance_context") or ""
        if "[SECURE]" in context:
            print("🎉 SUCCESS! The memory microservice embedded, saved, and recalled the instruction correctly using bge-m3 and phi4-mini!")
        else:
            print("❌ FAILURE: The context was empty or did not contain your rule. Check your 'docker compose logs memory-api' window to see the error.")

if __name__ == "__main__":
    asyncio.run(test_pipeline())