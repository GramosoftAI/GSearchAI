import asyncio
import json
import time
import os
import uuid
import sys
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# Import the existing DB engine and settings from the app
from app.core.database import AsyncSessionLocal, engine
from app.modules.database_knowledgebase.services.service import DatabaseKnowledgebaseService

async def main():
    os.makedirs('baseline', exist_ok=True)
    
    # Pre-defined benchmark questions
    questions = [
        "How many tables are in the database?",
        "What is the total number of employees?",
        "List the top 5 departments by employee count.",
        "What is the average joining date of employees?",
        "Show me the names of employees in the sales department."
    ]
    
    with open('baseline/questions.json', 'w') as f:
        json.dump(questions, f, indent=2)

    async with AsyncSessionLocal() as session:
        # Get a test DB KB
        res = await session.execute(text("SELECT id, tenant_id, name FROM database_knowledgebases LIMIT 1"))
        kb = res.fetchone()
        
        if not kb:
            print("No database knowledgebases found. Cannot run benchmark.")
            # For the sake of having a baseline, we'll write empty results if none exist
            kb_id = uuid.uuid4()
            tenant_id = uuid.uuid4()
            print("Continuing with dummy IDs just to output a failure baseline.")
        else:
            kb_id = kb.id
            tenant_id = kb.tenant_id
            print(f"Using KB: {kb.name} ({kb_id}) for Tenant: {tenant_id}")
            # Set RLS for the session
            await session.execute(text("SELECT set_config('app.current_tenant', :tenant_id, false)"), {"tenant_id": str(tenant_id)})
            
        service = DatabaseKnowledgebaseService(db=session, tenant_id=str(tenant_id))
        
        results = []
        metrics = {
            "total_questions": len(questions),
            "successful_sql_generation": 0,
            "successful_execution": 0,
            "total_latency_ms": 0,
        }
        failure_analysis = []
        
        for q in questions:
            print(f"\nProcessing: '{q}'")
            start_time = time.perf_counter()
            
            sql_valid = False
            execution_success = False
            generated_sql = None
            failure_type = None
            error_details = None
            
            try:
                if not kb: raise Exception("No Knowledgebase found")
                
                # Use generate_candidate_sql then execute_candidate_sql
                # or just query_database depending on the actual API. I will use plan_query then generate
                answer = await service.query_database(
                    kb_id=kb_id,
                    user_query=q,
                    top_k_tables=5,
                    use_llm=True
                )
                
                generated_sql = answer.executed_sql if hasattr(answer, 'executed_sql') else getattr(answer, 'sql', "Unknown")
                sql_valid = True
                execution_success = True
                print(f"  -> SUCCESS. SQL: {generated_sql}")
            except Exception as e:
                error_details = str(e)
                print(f"  -> FAILED: {error_details}")
                if "Syntax" in error_details or "syntax" in error_details:
                    failure_type = "SYNTAX_ERROR"
                elif "does not exist" in error_details or "knowledgebase" in error_details.lower():
                    failure_type = "SCHEMA_ERROR"
                elif "Timeout" in error_details:
                    failure_type = "TIMEOUT"
                else:
                    failure_type = "OTHER_ERROR"
            
            latency_ms = (time.perf_counter() - start_time) * 1000
            
            results.append({
                "question": q,
                "generated_sql": generated_sql,
                "sql_valid": sql_valid,
                "execution_success": execution_success,
                "latency_ms": latency_ms,
                "failure_type": failure_type
            })
            
            if not execution_success:
                failure_analysis.append({
                    "question": q,
                    "failure_type": failure_type,
                    "error": error_details
                })
            
            if sql_valid: metrics["successful_sql_generation"] += 1
            if execution_success: metrics["successful_execution"] += 1
            metrics["total_latency_ms"] += latency_ms
            
        metrics["average_latency_ms"] = metrics["total_latency_ms"] / len(questions) if questions else 0
        
        with open('baseline/results.json', 'w') as f:
            json.dump(results, f, indent=2)
            
        with open('baseline/metrics.json', 'w') as f:
            json.dump(metrics, f, indent=2)
            
        with open('baseline/failure_analysis.json', 'w') as f:
            json.dump(failure_analysis, f, indent=2)
            
        print("\nBenchmark complete. Results written to baseline/")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
