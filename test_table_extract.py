import re
from app.core.pdf_extractor import PDFExtractor
import asyncio

raw_markdown = """
Example table
This is an example of a data table.

Disability Category	Participants	Ballots Completed	Ballots Incomplete/Terminated	Results	Accuracy	Time to complete
Blind	5	1	4	34.5%, n=1	1199 sec, n=1	
Low Vision	5	2	3	98.3% n=2 (97.7%, n=3)	1716 sec, n=3 (1934 sec, n=2)	
Dexterity	5	4	1	98.3%, n=4	1672.1 sec, n=4	
Mobility	3	3	0	95.4%, n=3	1416 sec, n=3	
"""

async def test():
    res = await PDFExtractor.extract_tables_to_json(b"", raw_markdown)
    for r in res:
        print(r)

asyncio.run(test())
