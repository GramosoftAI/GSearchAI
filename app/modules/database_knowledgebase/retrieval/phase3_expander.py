import uuid
import logging
from typing import List, Dict, Any, Set
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


class Phase3ExpansionResult(BaseModel):
    primary_tables: List[Dict[str, Any]]
    expanded_tables: List[Dict[str, Any]]
    expansion_paths: List[str]
    final_evidence_context: str


class Phase3Expander:
    """
    Isolated FK Relationship Expansion (Phase 3).
    Expands from Phase 2 seed documents using strictly defined FKs.
    Enforces isolation by tenant_id, kb_id, and schema_hash.
    """

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID):
        self.session = session
        self.tenant_id = tenant_id

    async def expand(
        self,
        seed_documents: List[Dict[str, Any]],
        kb_id: uuid.UUID,
        schema_hash: str,
        max_hops: int = 1,
        max_related_tables: int = 5
    ) -> Phase3ExpansionResult:
        logger.info(f"Phase 3 Expansion starting with {len(seed_documents)} seeds, max_hops={max_hops}")
        
        visited_tables: Set[str] = {doc.get("table_name") for doc in seed_documents if doc.get("table_name")}
        primary_tables = seed_documents.copy()
        expanded_tables: List[Dict[str, Any]] = []
        expansion_paths: List[str] = []
        
        # We will use a queue for BFS expansion
        queue = [(doc.get("table_name"), 0) for doc in seed_documents if doc.get("table_name")]
        
        while queue and len(expanded_tables) < max_related_tables:
            current_table, current_hop = queue.pop(0)
            
            if current_hop >= max_hops:
                continue
                
            # 1. Forward Relationships: tables that current_table references
            # We already have the relationships in the document if it was a seed, but to be robust, 
            # we query document_chunks for current_table and get its relationships.
            stmt_current = text("""
                SELECT metadata_json
                FROM document_chunks
                WHERE 
                    tenant_id = :tenant_id
                    AND kb_id = :kb_id
                    AND section = 'SCHEMA_INDEX'
                    AND metadata_json->>'schema_hash' = :schema_hash
                    AND metadata_json->>'table_name' = :table_name
                LIMIT 1
            """)
            params = {
                "tenant_id": str(self.tenant_id),
                "kb_id": str(kb_id),
                "schema_hash": schema_hash,
                "table_name": current_table
            }
            res_current = await self.session.execute(stmt_current, params)
            row_current = res_current.fetchone()
            
            if row_current:
                meta = row_current[0]
                rels = meta.get("relationships", [])
                for rel in rels:
                    ref_table = rel.get("referenced_table")
                    ref_col = rel.get("referenced_column")
                    col = rel.get("column")
                    
                    if ref_table and ref_table not in visited_tables and len(expanded_tables) < max_related_tables:
                        # Fetch the referenced table to ensure it exists and matches constraints
                        stmt_ref = text("""
                            SELECT text, metadata_json
                            FROM document_chunks
                            WHERE 
                                tenant_id = :tenant_id
                                AND kb_id = :kb_id
                                AND section = 'SCHEMA_INDEX'
                                AND metadata_json->>'schema_hash' = :schema_hash
                                AND metadata_json->>'table_name' = :ref_table
                            LIMIT 1
                        """)
                        params_ref = params.copy()
                        params_ref["ref_table"] = ref_table
                        res_ref = await self.session.execute(stmt_ref, params_ref)
                        row_ref = res_ref.fetchone()
                        
                        if row_ref:
                            ref_meta = row_ref[1]
                            ref_meta["_semantic_text"] = row_ref[0]
                            expanded_tables.append(ref_meta)
                            visited_tables.add(ref_table)
                            queue.append((ref_table, current_hop + 1))
                            path_desc = f"{current_table}.{col} -> {ref_table}.{ref_col}"
                            expansion_paths.append(path_desc)
                            logger.debug(f"Expanded forward: {path_desc}")
            
            # 2. Reverse Relationships: tables that reference current_table
            # We use a JSON path/contains query to find tables whose 'relationships' list points to current_table
            stmt_reverse = text("""
                SELECT text, metadata_json
                FROM document_chunks
                WHERE 
                    tenant_id = :tenant_id
                    AND kb_id = :kb_id
                    AND section = 'SCHEMA_INDEX'
                    AND metadata_json->>'schema_hash' = :schema_hash
                    AND metadata_json->'relationships' @> :ref_json::jsonb
            """)
            # JSONB contains check for an array containing an object with referenced_table = current_table
            import json
            ref_json = json.dumps([{"referenced_table": current_table}])
            params_rev = params.copy()
            params_rev["ref_json"] = ref_json
            
            res_rev = await self.session.execute(stmt_reverse, params_rev)
            rows_rev = res_rev.fetchall()
            
            for r_text, r_meta in rows_rev:
                r_table = r_meta.get("table_name")
                if r_table and r_table not in visited_tables and len(expanded_tables) < max_related_tables:
                    r_meta["_semantic_text"] = r_text
                    expanded_tables.append(r_meta)
                    visited_tables.add(r_table)
                    queue.append((r_table, current_hop + 1))
                    
                    # Find the specific column used for the reverse relationship to build the path string
                    for rel in r_meta.get("relationships", []):
                        if rel.get("referenced_table") == current_table:
                            path_desc = f"{r_table}.{rel.get('column')} -> {current_table}.{rel.get('referenced_column')}"
                            expansion_paths.append(path_desc)
                            logger.debug(f"Expanded reverse: {path_desc}")

        # 3. Format Evidence Context
        evidence_lines = []
        evidence_lines.append("PRIMARY RETRIEVAL")
        for doc in primary_tables:
            evidence_lines.append(f"--- Table: {doc.get('table_name')} ---")
            if "_semantic_text" in doc:
                evidence_lines.append(doc["_semantic_text"])
            elif "content" in doc:
                evidence_lines.append(doc["content"])
                
        if expanded_tables:
            evidence_lines.append("\nRELATIONSHIP EXPANSION")
            for path in expansion_paths:
                evidence_lines.append(path)
            
            evidence_lines.append("")
            for doc in expanded_tables:
                evidence_lines.append(f"--- Table: {doc.get('table_name')} (Expanded) ---")
                if "_semantic_text" in doc:
                    evidence_lines.append(doc["_semantic_text"])
                elif "content" in doc:
                    evidence_lines.append(doc["content"])
                    
        final_evidence_context = "\n".join(evidence_lines)

        return Phase3ExpansionResult(
            primary_tables=primary_tables,
            expanded_tables=expanded_tables,
            expansion_paths=expansion_paths,
            final_evidence_context=final_evidence_context
        )
