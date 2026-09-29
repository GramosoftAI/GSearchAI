import re

file_path = 'app/core/adaptive_chunker.py'
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if '"metadata": {"overlap_prefix_len": sc.get(' in line:
        # Check if we are inside a 'for sc in' block
        # We can just look up a few lines to see if there's a 'for sc in' 
        # But wait, it's safer to just replace 'sc' with the correct loop variable based on the context.
        # Let's just find the closest loop variable.
        # Actually, if we look at the line before, or 5 lines before:
        in_sc_loop = False
        for j in range(i-1, max(-1, i-6), -1):
            if 'for sc in' in lines[j]:
                in_sc_loop = True
                break
        
        if not in_sc_loop:
            # Replace it with '"metadata": {}'
            lines[i] = line.replace('"metadata": {"overlap_prefix_len": sc.get("overlap_prefix_len", 0)} if isinstance(sc, dict) else {}', '"metadata": {}')

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)
