# 🚀 Release Notes for QA Testing

## What's New in this Release
We’ve shipped major backend optimizations to improve how fast the AI responds, and fixed bugs related to handling multiple documents at once. We need you to verify that answers are accurate and that latency is within acceptable bounds.

---

### ✅ Test Case 1: Multi-Document Search
**Goal:** Ensure the AI can successfully synthesize information across multiple PDFs within a single agent without confusing the sources.

1. Create a new Agent.
2. Upload **multiple PDFs** into that single Agent (e.g., 3 to 5 different documents).
3. Wait for ingestion to finish successfully.
4. **Action:** Ask questions that require the AI to pull information from *different* PDFs (e.g., "Compare the revenue in Document A with the revenue in Document B").
5. **Expected Result:** The AI should answer correctly, cite the correct sources, and should not get confused between the different documents.

---

### ✅ Test Case 2: System Latency (Speed Check)
**Goal:** Verify that the system responds quickly and that our new aggressive timeout fallbacks prevent infinite loading states.

1. Send a variety of questions to your Agent (some simple facts, some complex comparisons).
2. **Action:** Time how long it takes for the AI to start streaming its answer.
3. **Expected Result:** 
   - Typical questions should start answering quickly (under 5–8 seconds).
   - *Even if the AI struggles internally with a complex query, it should NEVER hang for 20+ seconds.* It should quickly fall back and give you an answer within 5 seconds.

---

### ✅ Test Case 3: Admin Panel Token Tracking
**Goal:** Verify that all AI processing (including query analysis) is correctly logged and billed in the Admin Panel.

1. Submit a few test queries to an Agent.
2. Log into the **Admin Panel**.
3. Navigate to the **Token Consumption / Usage** section for your tenant.
4. **Expected Result:** You should see new token usage entries properly logged. Specifically, look for tokens consumed by "Intent Detection" or standard Answer Generation, ensuring that costs are properly tracked and not slipping through the cracks.
