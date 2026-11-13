import xml.etree.ElementTree as ET
from pathlib import Path

for name in ["unit", "integration", "redteam", "existing_golden"]:
    p = Path(f"baseline_reports/{name}.xml")
    if not p.exists():
        print(name, "MISSING")
        continue
    root = ET.parse(p).getroot()
    suites = root.findall("testsuite")
    if root.tag == "testsuite":
        suites = [root]
    total = fail = err = skip = 0
    time = 0.0
    for s in suites:
        total += int(s.attrib.get("tests", 0))
        fail += int(s.attrib.get("failures", 0))
        err += int(s.attrib.get("errors", 0))
        skip += int(s.attrib.get("skipped", 0))
        time += float(s.attrib.get("time", 0))
    passed = total - fail - err - skip
    print(
        f"{name}: total={total} passed={passed} failed={fail} "
        f"errors={err} skipped={skip} duration={time:.2f}s"
    )
