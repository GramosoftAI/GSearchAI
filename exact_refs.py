import os
import re

files_to_check = []
for root, _, files in os.walk('app'):
    for file in files:
        if file.endswith('.py'):
            files_to_check.append(os.path.join(root, file))

pattern = re.compile(r'\bDocumentChunk\.embedding\b(?!\w)|c\.embedding\b(?!\w)|chunk\.embedding\b(?!\w)')

print("--- SCAN RESULTS ---")
for path in files_to_check:
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        for i, line in enumerate(lines):
            if pattern.search(line):
                # Ensure it's a true access
                if 'embedding_bge' not in line and 'summary_embedding' not in line:
                    print(f"{path}:{i+1}: {line.strip()}")
