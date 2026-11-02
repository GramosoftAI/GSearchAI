import json
from collections import defaultdict
from pathlib import Path

d = json.loads(Path("baseline_reports/golden_e2e_baseline.json").read_text(encoding="utf-8"))
print("=== PER CASE ===")
for r in d["results"]:
    mark = "PASS" if r["passed"] else "FAIL"
    tables = r.get("planned_tables") or r.get("retrieved_tables")
    detail = (r.get("failure_detail") or "")[:200]
    print(
        f"{r['case_id']} {mark:4} grp={r.get('failure_group') or '-':22} "
        f"tables={tables} rows={r.get('row_count')} lat={r.get('latency_ms'):.0f} llm={r.get('llm_call_count')}"
    )
    if not r["passed"]:
        print(f"       {detail}")
        sql = r.get("generated_sql")
        if sql:
            print(f"       SQL: {sql[:180]}")
        ans = r.get("final_answer")
        if ans:
            print(f"       ANS: {str(ans)[:160]}")

print("=== BY CATEGORY ===")
cat = defaultdict(lambda: [0, 0])
for r in d["results"]:
    c = r["category"]
    cat[c][1] += 1
    if r["passed"]:
        cat[c][0] += 1
for c, v in cat.items():
    print(f"{c}: {v[0]}/{v[1]}")
