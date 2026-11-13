import os
import psycopg2
import json

conn = psycopg2.connect("postgresql://graphmind:graphmind_password@localhost:5433/graphmind")
cur = conn.cursor()
cur.execute("SELECT text_content, metadata FROM public.document_chunks WHERE kb_id='d94d810d-e42c-40e1-ae7f-1e6c43771056' ORDER BY id ASC LIMIT 5;")
rows = cur.fetchall()
for i, row in enumerate(rows):
    print(f"--- Chunk {i} ---")
    print(f"Metadata: {json.dumps(row[1])}")
    print("Content:", row[0][:500])

cur.close()
conn.close()
