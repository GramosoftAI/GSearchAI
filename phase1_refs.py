import os

files_to_check = []
for root, _, files in os.walk('app'):
    for file in files:
        if file.endswith('.py'):
            files_to_check.append(os.path.join(root, file))

for path in files_to_check:
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        for i, line in enumerate(lines):
            if 'DocumentChunk.embedding' in line or '.embedding' in line:
                if 'embedding_bge' not in line and 'summary_embedding' not in line:
                    if 'c.embedding' in line or 'chunk.embedding' in line or 'DocumentChunk.embedding' in line:
                        print(f"{path}:{i+1}: {line.strip()}")
