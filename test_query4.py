import os
import psycopg2
import json

conn = psycopg2.connect("postgresql://graphmind:graphmind_password@localhost:5433/graphmind")
cur = conn.cursor()
cur.execute("SELECT * FROM public.document_chunks WHERE kb_id='d94d810d-e42c-40e1-ae7f-1e6c43771056' ORDER BY id ASC LIMIT 1;")
rows = cur.fetchall()
colnames = [desc[0] for desc in cur.description]
print("Columns:", colnames)
if rows:
    row = rows[0]
    for i, col in enumerate(colnames):
        val = row[i]
        if col != 'embedding':
            print(f"{col}: {str(val)[:500]}")

cur.close()
conn.close()
