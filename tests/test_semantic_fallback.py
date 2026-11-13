import asyncio
import sys
import os
from dotenv import load_dotenv

sys.path.append(r"c:\Users\hp\Desktop\GSOFT\RAG\GSearchAI\app\memory\app")
load_dotenv(r"c:\Users\hp\Desktop\GSOFT\RAG\GSearchAI\.env")

from main import _is_no_answer_found

async def test_semantic_fallback():
    print("Running Semantic Fallback Tests...")
    
    test_cases = [
        # Exact failing cases
        "I don't have any information about Vijay in my current knowledge base.",
        "I don't have any information about CMvijay in my current knowledge base.",
        
        # Novel phrasings not explicitly in the fast-path list
        "That's outside what I can answer based on the documents I have access to.",
        "The context provided is silent on this matter, so I'm unable to give you a definitive answer.",
        "There is nothing in the text addressing your query about the new policy."
    ]
    
    all_passed = True
    for idx, resp in enumerate(test_cases, 1):
        result = await _is_no_answer_found(resp)
        print(f"Test {idx}: '{resp}' -> {result} (Expected: True)")
        if not result:
            print("  [FAILED]")
            all_passed = False
            
    if all_passed:
        print("\nAll 5 semantic fallback tests passed successfully!")
    else:
        print("\nSome tests failed!")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_semantic_fallback())
