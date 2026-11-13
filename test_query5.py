import os
import psycopg2

conn = psycopg2.connect("postgresql://graphmind:graphmind_password@localhost:5433/graphmind")
cur = conn.cursor()
cur.execute("SELECT chunk_index, text FROM public.document_chunks WHERE kb_id='d94d810d-e42c-40e1-ae7f-1e6c43771056' ORDER BY chunk_index ASC LIMIT 10;")
rows = cur.fetchall()
for row in rows:
    print(f"--- Chunk {row[0]} ---")
    print(row[1])

cur.close()
conn.close()
