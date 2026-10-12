import uuid
import logging
from typing import List, Dict, Any, Set, Optional
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, bindparam
from sqlalchemy.dialects.postgresql import JSONB

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
        canonical_schema: Optional[Any] = None,
        max_hops: int = 1,
        max_related_tables: int = 5
    ) -> Phase3ExpansionResult:
        logger.info(f"Phase 3 Expansion starting with {len(seed_documents)} seeds, max_hops={max_hops}")
        
        visited_tables: Set[str] = {doc.get("table_name").lower() for doc in seed_documents if doc.get("table_name")}
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
            found_forward = False
            try:
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
                        
                        if ref_table and ref_table.lower() not in visited_tables and len(expanded_tables) < max_related_tables:
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
                                visited_tables.add(ref_table.lower())
                                queue.append((ref_table, current_hop + 1))
                                path_desc = f"{current_table}.{col} -> {ref_table}.{ref_col}"
                                expansion_paths.append(path_desc)
                                found_forward = True
                                logger.debug(f"Expanded forward: {path_desc}")
            except Exception as e:
                logger.debug(f"Phase 3 document chunk forward query skipped: {e}")
            
            # Fallback for forward FKs using canonical_schema
            if not found_forward and canonical_schema:
                for s_val in canonical_schema.schemas.values():
                    if current_table in s_val.tables:
                        t_obj = s_val.tables[current_table]
                        for rel in t_obj.relationships:
                            ref_tbl = rel.target_table
                            if ref_tbl and ref_tbl.lower() not in visited_tables and len(expanded_tables) < max_related_tables:
                                expanded_tables.append({
                                    "table_name": ref_tbl,
                                    "schema_name": rel.target_schema,
                                    "columns": [],
                                })
                                visited_tables.add(ref_tbl.lower())
                                queue.append((ref_tbl, current_hop + 1))
                                path_desc = f"{current_table}.{','.join(rel.source_columns)} -> {ref_tbl}.{','.join(rel.target_columns)}"
                                expansion_paths.append(path_desc)
                                logger.debug(f"Expanded canonical forward: {path_desc}")

            # 2. Reverse Relationships: tables that reference current_table
            found_reverse = False
            try:
                stmt_reverse = text("""
                    SELECT text, metadata_json
                    FROM document_chunks
                    WHERE 
                        tenant_id = :tenant_id
                        AND kb_id = :kb_id
                        AND section = 'SCHEMA_INDEX'
                        AND metadata_json->>'schema_hash' = :schema_hash
                        AND metadata_json->'relationships' @> CAST(:ref_json AS jsonb)
                """).bindparams(bindparam("ref_json", type_=JSONB))
                params_rev = {
                    "tenant_id": str(self.tenant_id),
                    "kb_id": str(kb_id),
                    "schema_hash": schema_hash,
                    "ref_json": [{"referenced_table": current_table}]
                }
                
                res_rev = await self.session.execute(stmt_reverse, params_rev)
                rows_rev = res_rev.fetchall()
                
                for r_text, r_meta in rows_rev:
                    r_table = r_meta.get("table_name")
                    if r_table and r_table.lower() not in visited_tables and len(expanded_tables) < max_related_tables:
                        r_meta["_semantic_text"] = r_text
                        expanded_tables.append(r_meta)
                        visited_tables.add(r_table.lower())
                        queue.append((r_table, current_hop + 1))
                        found_reverse = True
                        for rel in r_meta.get("relationships", []):
                            if rel.get("referenced_table") == current_table:
                                path_desc = f"{r_table}.{rel.get('column')} -> {current_table}.{rel.get('referenced_column')}"
                                expansion_paths.append(path_desc)
                                logger.debug(f"Expanded reverse: {path_desc}")
            except Exception as e:
                logger.debug(f"Phase 3 document chunk reverse query skipped: {e}")

            # Fallback for reverse FKs using canonical_schema
            if not found_reverse and canonical_schema:
                for s_val in canonical_schema.schemas.values():
                    for cand_name, cand_tbl in s_val.tables.items():
                        if cand_name.lower() in visited_tables:
                            continue
                        for rel in cand_tbl.relationships:
                            if rel.target_table.lower() == current_table.lower() and len(expanded_tables) < max_related_tables:
                                expanded_tables.append({
                                    "table_name": cand_name,
                                    "schema_name": cand_tbl.schema_name,
                                    "columns": [],
                                })
                                visited_tables.add(cand_name.lower())
                                queue.append((cand_name, current_hop + 1))
                                path_desc = f"{cand_name}.{','.join(rel.source_columns)} -> {current_table}.{','.join(rel.target_columns)}"
                                expansion_paths.append(path_desc)
                                logger.debug(f"Expanded canonical reverse: {path_desc}")
                                break

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
