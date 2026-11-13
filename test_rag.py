import asyncio
import logging
import sys
from dataclasses import dataclass

from app.modules.rag.pipeline import RAGPipeline

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

@dataclass
class MockRequest:
    query: str
    tenant_id: str
    user_id: str
    session_id: str
    mode: str = "hybrid"

async def main():
    tenant_id = "b91f23d9-7127-420d-acc9-fc420b46bf9e"
    # Agent ID from user's logs
    agent_id = "e80b87d5-cf19-46be-a4f9-4409602c9ddf"
    
    pipeline = RAGPipeline(tenant_id=tenant_id, agent_id=agent_id)
    
    request = MockRequest(
        query="What was the probable cause of the Beech A23 airplane accident in Death Valley, CA on November 29, 2007?",
        tenant_id=tenant_id,
        user_id="ed30c962-159b-44ba-897b-e3166fba367d",
        session_id="test_session_1"
    )
    
    response = await pipeline.query(request)
    print("--------------------------------------------------")
    print("Final Answer:")
    print(response.answer)
    print("--------------------------------------------------")
    print("Retrieved Chunks:")
    for c in response.context.chunks:
        print(f"- {c.source} (Score: {c.hybrid_score})")

if __name__ == "__main__":
    asyncio.run(main())
