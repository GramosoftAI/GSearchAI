import asyncio
import httpx
import os
from dotenv import load_dotenv

load_dotenv(r"c:\Users\hp\Desktop\GSOFT\RAG\GSearchAI\.env")

async def run_llm_completion(system_prompt: str, user_prompt: str) -> str:
    llm_base = os.getenv("LLM_BASE_URL", "https://api.deepinfra.com/v1/openai").rstrip('/')
    api_key = os.getenv("LLM_GATEWAY_API_KEY", os.getenv("DEEPINFRA_API_KEY", ""))
    chat_model = os.getenv("MEMORY_CHAT_MODEL", "meta-llama/Meta-Llama-3.1-8B-Instruct")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    endpoint = f"{llm_base}/chat/completions" if llm_base.endswith("/openai") else f"{llm_base}/v1/chat/completions"
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            endpoint,
            headers=headers,
            json={
                "model": chat_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "max_tokens": 512,
                "temperature": 0.0
            },
            timeout=90.0
        )
        data = resp.json()
        return data["choices"][0]["message"]["content"]

async def test_semantic_fallback():
    print("Running Semantic LLM Classifier Tests...\n")
    
    test_cases = [
        "I don't have any information about Vijay in my current knowledge base.",
        "I don't have any information about CMvijay in my current knowledge base.",
        "That's outside what I can answer based on the documents I have access to.",
        "The context provided is silent on this matter, so I'm unable to give you a definitive answer."
    ]
    
    system_prompt = (
        "Does this response contain actual substantive information that answers the question, "
        "or does it indicate that no information/answer was found? "
        "Reply with exactly one word: FOUND or NOT_FOUND."
    )
    
    for idx, resp in enumerate(test_cases, 1):
        print(f"Test {idx}: '{resp}'")
        
        # 1. Fast-path check (just word count)
        words = resp.split()
        if len(words) > 150:
            print("  Result: -> False (Fast-path: too long to be a simple not-found)")
            continue
            
        # 2. LLM Call
        result = await run_llm_completion(system_prompt, resp)
        print(f"  Classifier Output: -> {result}")
        if "NOT_FOUND" in result.upper():
            print("  Final Decision: TRUE (Skip Write)")
        else:
            print("  Final Decision: FALSE (Write to DB)")
        print()

if __name__ == "__main__":
    asyncio.run(test_semantic_fallback())
