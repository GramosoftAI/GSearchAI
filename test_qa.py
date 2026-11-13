import asyncio
import json
from app.modules.rag.orchestrator.query_analyzer import QueryAnalyzer

async def main():
    analyzer = QueryAnalyzer()
    res = await analyzer.analyze_query("What was the probable cause of the Beech A23 airplane accident in Death Valley, CA on November 29, 2007?")
    print("Intent:", res.intent)
    print("Keywords:", res.metadata.keywords)
    print("Year:", res.metadata.year)
    print("Is Tabular:", res.is_tabular)

if __name__ == "__main__":
    asyncio.run(main())
