import sys; sys.path.insert(0, '.')
from app.core.parquet_ingester import ParquetIngester
import duckdb, os

p = ParquetIngester.get_active_dataset('dummy_employees_details')
print('Parquet path:', p)
print('Exists:', os.path.exists(p))

safe = p.replace('\\', '/')
conn = duckdb.connect(':memory:')
conn.execute(f"CREATE VIEW dataset AS SELECT * FROM read_parquet('{safe}')")
cols = [d[0] for d in conn.execute('DESCRIBE dataset').fetchall()]
print('Columns:', cols)
res = conn.execute("SELECT * FROM dataset WHERE \"Employee ID\" = 'EMP1005'").fetchall()
print('EMP1005 row:', res)
