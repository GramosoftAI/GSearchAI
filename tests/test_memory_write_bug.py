def _is_no_answer_found(ai_response: str) -> bool:
    if not ai_response:
        return False
    ai_resp_lower = ai_response.lower()
    negative_indicators = [
        "couldn't find", "could not find", "don't know", "do not know",
        "no mention", "no information", "not present in dataset",
        "not found", "unable to find", "no matching record",
        "does not exist", "unanswered",
        "don't have any specific information", "don’t have any specific information",
        "does not include information", "don't have information",
        "not covered in the documents", "not covered in the provided context",
        "context does not contain", "i recommend contacting",
        "no information available", "does not provide information",
        "i could not find information about", "not present in the uploaded content"
    ]
    return any(indicator in ai_resp_lower for indicator in negative_indicators)

def test_no_answer_found():
    print("Running Regression Tests for memory write bug...")
    
    # 1. Answer not found -> skips
    resp1 = "The provided context does not include information regarding coverage for terrorist attacks."
    assert _is_no_answer_found(resp1) == True
    print("Test 1 (Answer not found) -> passed")
    
    resp2 = "Based on the provided context, I couldn't find any information about that."
    assert _is_no_answer_found(resp2) == True
    print("Test 2 (Answer not found variant) -> passed")
    
    # 2. Genuine answer found -> saves normally
    resp3 = "Yes, terrorist attacks ARE covered under section 4."
    assert _is_no_answer_found(resp3) == False
    print("Test 3 (Genuine answer) -> passed")
    
    # 3. Partial answer -> skips (because it contains the phrase)
    resp4 = "We cover terrorist attacks, but the provided context does not include information regarding COVID."
    assert _is_no_answer_found(resp4) == True
    print("Test 4 (Partial answer) -> passed")
    
    print("\nAll 4 tests passed successfully!")

if __name__ == "__main__":
    test_no_answer_found()
