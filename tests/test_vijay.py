import asyncio
import sys
import os
from dotenv import load_dotenv

sys.path.append(r"c:\Users\hp\Desktop\GSOFT\RAG\GSearchAI\app\memory")

# Load environment variables for the LLM
load_dotenv(r"c:\Users\hp\Desktop\GSOFT\RAG\GSearchAI\.env")

from app.main import _is_no_answer_found

async def test_vijay_query():
    print("Testing 'Vijay' query fallback...")
    
    # 1. Exact failing case
    resp1 = "I don't have any information about Vijay in my current knowledge base."
    
    # Run the function
    result = await _is_no_answer_found(resp1)
    print(f"Result for '{resp1}': {result} (Expected: True)")
    assert result == True, "Failed to catch the Vijay query!"
    
    print("\nLLM Fallback test passed successfully!")

if __name__ == "__main__":
    asyncio.run(test_vijay_query())
