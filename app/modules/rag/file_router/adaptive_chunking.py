import re
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from typing import List, Dict, Any, Callable
from tokenizers import Tokenizer

logger = logging.getLogger(__name__)

@dataclass
class ChunkResult:
    chunk_id: str
    parent_id: str
    text: str
    embed_text: str
    metadata: Dict[str, Any]
    tokens: int
    is_parent: bool

@dataclass(frozen=True)
class EmbedProfile:
    name: str
    max_tokens: int
    count: Callable[[str], int]
    child_target: int
    parent_target: int

def load_profile() -> EmbedProfile:
    tokenizer_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))),
        'models', 'tokenizer.json'
    )
    if os.path.exists(tokenizer_path):
        tokenizer = Tokenizer.from_file(tokenizer_path)
        count_fn = lambda text: len(tokenizer.encode(text).ids)
    else:
        # Fallback for testing if missing
        count_fn = lambda text: len(text.split())
    return EmbedProfile(
        name="BAAI/bge-large-en-v1.5",
        max_tokens=512,
        count=count_fn,
        child_target=350,
        parent_target=1200
    )

class AdaptiveChunker:
    def __init__(self, profile: EmbedProfile = None):
        self.profile = profile or load_profile()
        self.seen_hashes = set()
        
    def _hash(self, text: str) -> str:
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    def _trim(self, text: str, max_tokens: int) -> str:
        # naive binary search trim to fit token budget
        if self.profile.count(text) <= max_tokens:
            return text
        logger.warning(f"Truncating text to fit {max_tokens} tokens")
        
        words = text.split()
        low, high = 0, len(words)
        best = ""
        while low <= high:
            mid = (low + high) // 2
            cand = " ".join(words[:mid])
            if self.profile.count(cand) <= max_tokens:
                best = cand
                low = mid + 1
            else:
                high = mid - 1
        return best

    def chunk_document(self, sections: List[Dict[str, Any]], breadcrumb_fn: Callable[[Dict], str]) -> List[ChunkResult]:
        """
        sections: [{'title': '...', 'text': '...', 'kind': 'text' | 'table' | 'list', 'metadata': {...}}]
        """
        results = []
        
        merged_sections = []
        # Tiny section merge forward (not into tables)
        temp_sec = None
        for sec in sections:
            if sec.get('kind', 'text') == 'table':
                if temp_sec:
                    merged_sections.append(temp_sec)
                    temp_sec = None
                merged_sections.append(sec)
                continue
                
            text = sec.get('text', '')
            tokens = self.profile.count(text)
            
            if tokens < 80:
                if temp_sec:
                    temp_sec['text'] += "\n\n" + text
                else:
                    temp_sec = sec.copy()
            else:
                if temp_sec:
                    temp_sec['text'] += "\n\n" + text
                    merged_sections.append(temp_sec)
                    temp_sec = None
                else:
                    merged_sections.append(sec.copy())
                    
        if temp_sec:
            merged_sections.append(temp_sec)
            
        for sec in merged_sections:
            kind = sec.get('kind', 'text')
            if kind == 'table':
                results.extend(self._chunk_table(sec, breadcrumb_fn))
            elif kind == 'list':
                results.extend(self._chunk_list(sec, breadcrumb_fn))
            else:
                results.extend(self._chunk_text(sec, breadcrumb_fn))
                
        # deduplicate
        final_results = []
        self.seen_hashes.clear()
        for r in results:
            if r.chunk_id not in self.seen_hashes:
                self.seen_hashes.add(r.chunk_id)
                final_results.append(r)
                
        return final_results

    def _split_to_budget(self, text: str, budget: int, delimiters: List[str]) -> List[str]:
        if self.profile.count(text) <= budget:
            return [text]
        if not delimiters:
            return [self._trim(text, budget)]
            
        delim = delimiters[0]
        if delim == "SENTENCE":
            parts = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
            joiner = " "
        elif delim == "LINE":
            parts = text.split('\n')
            joiner = "\n"
        elif delim == "WORD":
            parts = text.split(' ')
            joiner = " "
        else:
            parts = text.split(delim)
            joiner = delim
            
        if len(parts) == 1:
            return self._split_to_budget(text, budget, delimiters[1:])
            
        chunks = []
        curr = ""
        for p in parts:
            # If a single part is still too big, split it further
            if self.profile.count(p) > budget:
                if curr:
                    chunks.append(curr.strip())
                    curr = ""
                sub_parts = self._split_to_budget(p, budget, delimiters[1:])
                chunks.extend(sub_parts)
            else:
                if self.profile.count((curr + joiner + p).strip()) > budget:
                    chunks.append(curr.strip())
                    curr = p
                else:
                    curr = (curr + joiner + p).strip() if curr else p
                    
        if curr:
            chunks.append(curr.strip())
        return chunks

    def _chunk_text(self, sec: Dict[str, Any], breadcrumb_fn: Callable[[Dict], str]) -> List[ChunkResult]:
        text = sec.get('text', '')
        chunks = self._split_to_budget(text, self.profile.child_target, ["SENTENCE", "LINE", "WORD"])
        return self._build_parent_child(chunks, sec, breadcrumb_fn)
        
    def _chunk_table(self, sec: Dict[str, Any], breadcrumb_fn: Callable[[Dict], str]) -> List[ChunkResult]:
        rows = sec.get('text', '').split('\n')
        if not rows:
            return []
        header = rows[0]
        data_rows = rows[1:]
        
        chunks = []
        curr = header
        for r in data_rows:
            if self.profile.count(curr + "\n" + r) > self.profile.child_target:
                if curr != header:
                    chunks.append(curr)
                # If a single row is too big (e.g. huge cell), split it
                if self.profile.count(header + "\n" + r) > self.profile.child_target:
                    row_chunks = self._split_to_budget(r, self.profile.child_target - self.profile.count(header + "\n"), ["WORD"])
                    for rc in row_chunks:
                        chunks.append(header + "\n" + rc)
                    curr = header
                else:
                    curr = header + "\n" + r
            else:
                curr += "\n" + r
        if curr != header:
            chunks.append(curr)
            
        return self._build_parent_child(chunks, sec, breadcrumb_fn)
        
    def _chunk_list(self, sec: Dict[str, Any], breadcrumb_fn: Callable[[Dict], str]) -> List[ChunkResult]:
        lines = sec.get('text', '').split('\n')
        if not lines:
            return []
        lead_in = lines[0] if not lines[0].strip().startswith('-') else ""
        items = lines[1:] if lead_in else lines
        
        chunks = []
        curr = lead_in
        for item in items:
            if self.profile.count(curr + "\n" + item) > self.profile.child_target:
                if curr != lead_in and curr:
                    chunks.append(curr)
                if self.profile.count(lead_in + "\n" + item) > self.profile.child_target:
                    item_chunks = self._split_to_budget(item, self.profile.child_target - self.profile.count(lead_in + "\n"), ["LINE", "WORD"])
                    for ic in item_chunks:
                        chunks.append(lead_in + "\n" + ic if lead_in else ic)
                    curr = lead_in
                else:
                    curr = lead_in + "\n" + item if lead_in else item
            else:
                curr += "\n" + item
        if curr != lead_in and curr:
            chunks.append(curr)
            
        return self._build_parent_child(chunks, sec, breadcrumb_fn)

    def _build_parent_child(self, chunks: List[str], sec: Dict[str, Any], breadcrumb_fn: Callable[[Dict], str]) -> List[ChunkResult]:
        results = []
        breadcrumb = breadcrumb_fn(sec)
        
        # Parent creation (group up to parent_target)
        parents = []
        curr_parent = []
        for c in chunks:
            if self.profile.count("\n\n".join(curr_parent + [c])) > self.profile.parent_target:
                if curr_parent:
                    parents.append("\n\n".join(curr_parent))
                curr_parent = [c]
            else:
                curr_parent.append(c)
        if curr_parent:
            parents.append("\n\n".join(curr_parent))
            
        # For each parent, we add it, and its children
        child_idx = 0
        for p_text in parents:
            p_full = breadcrumb + "\n\n" + p_text
            p_full = self._trim(p_full, self.profile.max_tokens)
            p_id = self._hash("parent:" + p_full)
            results.append(ChunkResult(
                chunk_id=p_id,
                parent_id=p_id,
                text=p_text,
                embed_text=p_full,
                metadata=sec.get('metadata', {}),
                tokens=self.profile.count(p_full),
                is_parent=True
            ))
            
            # Re-find children for this parent
            p_children = []
            while child_idx < len(chunks) and chunks[child_idx] in p_text:
                c_text = chunks[child_idx]
                c_full = breadcrumb + "\n\n" + c_text
                c_full = self._trim(c_full, self.profile.max_tokens)
                c_id = self._hash("child:" + c_full)
                results.append(ChunkResult(
                    chunk_id=c_id,
                    parent_id=p_id,
                    text=c_text,
                    embed_text=c_full,
                    metadata=sec.get('metadata', {}),
                    tokens=self.profile.count(c_full),
                    is_parent=False
                ))
                child_idx += 1
                
        return results
