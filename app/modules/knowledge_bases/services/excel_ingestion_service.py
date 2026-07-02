"""
Excel/CSV Ingestion Service - High-Intelligence Ontological Graph Builder

Enables structured ingestion of Excel and CSV spreadsheets.
Preserves tabular relationships, column constraints, entity associations,
and row context by:
1. Dynamically discovering schema using LLM context mapping.
2. Grounding types against the tenant's active Enterprise Ontology.
3. Creating high-quality semantic row chunks and storing them in pgvector + Neo4j.
4. Spawning fine-grained ontological entity nodes and linking them with typed edges
   (e.g., REPORTS_TO, BELONGS_TO) in Neo4j.
5. Connecting row chunks to entities via MENTIONS for hybrid RAG compatibility.
"""

import io
import re
import json
import uuid
import logging
import pandas as pd
from typing import List, Dict, Any, Optional
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.knowledge_bases.models import DocumentChunk, DocumentTableRow
from app.modules.ontology.service import OntologyService
from app.core.neo4j_repository import Neo4jRepository
from app.core.neo4j_retry import retry_neo4j_operation
from app.core.embeddings import EmbeddingGenerator
from app.core.llm.deepinfra_llm import DeepInfraLLMClient

logger = logging.getLogger(__name__)

# LLM Prompt to discover relational spreadsheet mappings dynamically
SCHEMA_DISCOVERY_PROMPT = """You are an expert database schema mapping engine.
Analyze this spreadsheet's sheet name, headers, and sample data. 
Identify how to convert each row of this sheet into a clean Knowledge Graph under an Enterprise Ontology.

Identify:
1. The **Primary Entity Type**: What represents a single row (e.g., EMPLOYEE, SHIPMENT, CUSTOMER, TRANSACTION, INVOICE, VENDOR)?
2. The **Identifier Column**: Which column represents the unique key/ID of this primary entity (e.g., Employee ID, Transaction ID, Invoice Number)? If no clear ID column exists, specify null.
3. The **Attribute Columns**: Which columns directly describe this primary entity as simple properties (e.g., Salary, Amount, Status, Birth Date)?
4. The **Related Entities**: Which columns represent links to OTHER distinct entities (e.g., Department, Manager, Destination Country, Vendor Name)? 
   For each link, identify:
   - The column name.
   - The related entity type (e.g., DEPARTMENT, MANAGER, LOCATION, VENDOR).
   - The semantic **Relationship Type** (predicate) connecting the primary entity to this target (e.g., BELONGS_TO, REPORTS_TO, IMPORTED_FROM, SUPPLIED_BY). Relationship types MUST be standard UPPERCASE with underscores.

ACTIVE ENTERPRISE ONTOLOGY SCHEMAS:
Classes: {classes}
Allowed Rules: {rules}

Use this ontology to ground your types! If an entity type or relationship fits one of the active ontology classes or rules, you MUST use that exact class/relationship. Otherwise, suggest a natural UPPERCASE name.

TEXT SPECIFICATIONS:
Sheet Name: {sheet_name}
Headers: {headers}
Sample Rows (JSON format):
{sample_data}

Return ONLY valid JSON in this exact structure:
{{
    "primary_entity": {{
        "column": "Employee ID",
        "type": "EMPLOYEE"
    }},
    "attributes": {{
        "Employee Name": "name",
        "Salary Grade": "salary_grade",
        "Salary": "salary"
    }},
    "relationships": [
        {{
            "column": "Department",
            "relation": "BELONGS_TO",
            "target_type": "DEPARTMENT"
        }},
        {{
            "column": "Manager",
            "relation": "REPORTS_TO",
            "target_type": "MANAGER"
        }}
    ]
}}

JSON:"""


class ExcelIngestionService:
    """
    Coordinates relational parsing, dynamic schema mapping,
    ontology grounding, and transaction-safe graph writing.
    """

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = str(tenant_id)
        self.neo4j_repo = Neo4jRepository(self.tenant_id)
        self.llm_client = DeepInfraLLMClient()
        self.ontology_service = OntologyService(self.tenant_id)

    async def ingest_file(
        self,
        kb_id: str,
        file_bytes: bytes,
        filename: str,
        mime_type: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Main entry point for Excel/CSV ingestion.
        Reads worksheets, discovers schema via LLM, and populates both databases.
        """
        logger.info(f" Ingesting structured file '{filename}' for KB {kb_id} under tenant {self.tenant_id}")
        
        # 1. Parse Excel or CSV into sheets dictionary
        sheets_data: Dict[str, pd.DataFrame] = {}
        ext = filename.lower().split(".")[-1] if "." in filename else ""

        # Fallback to mime_type if extension is empty or not standard
        if ext not in ["csv", "xlsx", "xls"] and mime_type:
            # Native Google Spreadsheets are exported as CSV bytes, so treat them as csv
            if "csv" in mime_type.lower() or mime_type == "application/vnd.google-apps.spreadsheet":
                ext = "csv"
            elif "spreadsheet" in mime_type.lower() or "excel" in mime_type.lower():
                ext = "xlsx"

        try:
            if ext == "csv":
                df = pd.read_csv(io.BytesIO(file_bytes))
                sheets_data["Sheet1"] = df
            elif ext in ["xlsx", "xls"]:
                xl = pd.ExcelFile(io.BytesIO(file_bytes))
                for sheet_name in xl.sheet_names:
                    sheets_data[sheet_name] = xl.parse(sheet_name)
            else:
                raise ValueError(f"Unsupported spreadsheet format: {ext or filename}")
        except Exception as parse_err:
            logger.error(f"Failed parsing spreadsheet file: {parse_err}")
            return {"success": False, "error": f"Failed to parse file: {str(parse_err)}"}

        total_chunks = 0
        total_entities = 0
        total_relationships = 0

        # Fetch Active Ontology to guide LLM mapping
        try:
            ontology = await self.ontology_service.get_ontology()
            ontology_classes = [c["name"] for c in ontology.get("classes", [])]
            ontology_rules = [f"({r['source_class']})-[:{r['relation']}]->({r['target_class']})" for r in ontology.get("rules", [])]
        except Exception as ont_err:
            logger.warning(f"Failed fetching active ontology (non-blocking): {ont_err}")
            ontology_classes = []
            ontology_rules = []

        # Process each sheet individually
        for sheet_name, df in sheets_data.items():
            # Clean dataframe
            df = df.dropna(how="all")  # Drop completely empty rows
            df = df.map(lambda x: str(x).strip() if pd.notnull(x) else None)
            df = df.where(pd.notnull(df), None)  # Replace NaN with None

            if df.empty:
                logger.info(f"Sheet '{sheet_name}' is empty, skipping.")
                continue

            headers = df.columns.tolist()
            sample_rows = df.head(5).to_dict(orient="records")

            # 2. Discover Schema Mapping via LLM
            mapping = await self._discover_schema_mapping(
                sheet_name=sheet_name,
                headers=headers,
                sample_data=sample_rows,
                ontology_classes=ontology_classes,
                ontology_rules=ontology_rules
            )

            if not mapping:
                logger.warning(f"Could not discover schema mapping for sheet '{sheet_name}', falling back to default mapping")
                mapping = self._generate_default_mapping(headers)

            # 3. Ground entity and relationship types against Active Ontology
            grounded_mapping = await self._ground_schema_mapping(mapping)
            
            # --- DYNAMIC SCHEMA REGISTRATION (Phase 4B Enhancement) ---
            schema_to_register = {"classes": [], "relations": []}
            primary_type = grounded_mapping.get("primary_entity", {}).get("type")
            if primary_type:
                schema_to_register["classes"].append({"name": primary_type, "description": f"Auto-discovered class from sheet {sheet_name}"})
                
            for rel in grounded_mapping.get("relationships", []):
                tgt_type = rel.get("target_type")
                if tgt_type:
                    schema_to_register["classes"].append({"name": tgt_type, "description": f"Auto-discovered target class from sheet {sheet_name}"})
                pred = rel.get("relation")
                if pred:
                    schema_to_register["relations"].append({"name": pred, "description": f"Auto-discovered relation from sheet {sheet_name}"})
                    
            if schema_to_register["classes"] or schema_to_register["relations"]:
                try:
                    await self.ontology_service.auto_register_schema(schema_to_register)
                except Exception as e:
                    logger.warning(f"Failed to auto-register schema from excel: {e}")
            # -----------------------------------------------------------

            # 4. Ingest and write sheet rows
            sheet_stats = await self._ingest_sheet_rows(
                kb_id=kb_id,
                sheet_name=sheet_name,
                df=df,
                mapping=grounded_mapping,
                source=source
            )

            total_chunks += sheet_stats.get("chunks_created", 0)
            total_entities += sheet_stats.get("entities_created", 0)
            total_relationships += sheet_stats.get("relationships_created", 0)

        return {
            "success": True,
            "data": {
                "kb_id": kb_id,
                "chunks_created": total_chunks,
                "entities_created": total_entities,
                "relationships_created": total_relationships
            }
        }

    async def _discover_schema_mapping(
        self,
        sheet_name: str,
        headers: List[str],
        sample_data: List[Dict],
        ontology_classes: List[str],
        ontology_rules: List[str]
    ) -> Optional[Dict]:
        """Call LLM client to parse headers/sample and return mapping config."""
        classes_str = ", ".join(ontology_classes) if ontology_classes else "None loaded"
        rules_str = "\n".join(ontology_rules) if ontology_rules else "None loaded"

        prompt = SCHEMA_DISCOVERY_PROMPT.format(
            sheet_name=sheet_name,
            headers=headers,
            sample_data=json.dumps(sample_data, indent=2),
            classes=classes_str,
            rules=rules_str
        )

        try:
            res_text = await self.llm_client.generate(
                prompt=prompt,
                system_prompt="You are a schema discovery JSON engine. Return strictly valid JSON structure only.",
                temperature=0.0,
                max_tokens=1024
            )

            # Extract JSON block
            match = re.search(r"\{.*\}", res_text, re.DOTALL)
            if not match:
                logger.error(f"No JSON found in schema discovery LLM response: {res_text}")
                return None

            mapping = json.loads(match.group(0))
            logger.info(f" Schema mapped successfully for sheet '{sheet_name}': {mapping}")
            return mapping

        except Exception as e:
            logger.error(f"LLM Schema mapping failed: {e}")
            return None

    def _generate_default_mapping(self, headers: List[str]) -> Dict:
        """Fallback heuristics to create a schema mapping if LLM fails."""
        primary_col = headers[0] if headers else "RowIndex"
        return {
            "primary_entity": {
                "column": primary_col,
                "type": "RECORD"
            },
            "attributes": {h: h.lower().replace(" ", "_") for h in headers[1:]},
            "relationships": []
        }

    async def _ground_schema_mapping(self, mapping: Dict) -> Dict:
        """Ground extracted types to the active ontology classes using fuzzy embedding match."""
        grounded = mapping.copy()

        # Ground primary entity type
        raw_primary_type = grounded["primary_entity"]["type"]
        grounded_primary = await self.ontology_service.ground_type(raw_primary_type)
        if grounded_primary:
            logger.info(f"Grounding: Primary entity type '{raw_primary_type}' -> '{grounded_primary}'")
            grounded["primary_entity"]["type"] = grounded_primary
        else:
            grounded["primary_entity"]["type"] = raw_primary_type.upper().strip().replace(" ", "_")

        # Ground related entity types
        for rel in grounded.get("relationships", []):
            raw_tgt_type = rel["target_type"]
            grounded_tgt = await self.ontology_service.ground_type(raw_tgt_type)
            if grounded_tgt:
                logger.info(f"Grounding: Target entity type '{raw_tgt_type}' -> '{grounded_tgt}'")
                rel["target_type"] = grounded_tgt
            else:
                rel["target_type"] = raw_tgt_type.upper().strip().replace(" ", "_")

            # Clean relationship type format
            rel["relation"] = rel["relation"].upper().strip().replace(" ", "_")

        return grounded

    async def _ingest_sheet_rows(
        self,
        kb_id: str,
        sheet_name: str,
        df: pd.DataFrame,
        mapping: Dict,
        source: Optional[str] = None
    ) -> Dict[str, int]:
        """Ingests rows of a dataframe, generates embeddings, stages pgvector & populates Neo4j using Row-Centric Strategy."""
        primary_col = mapping["primary_entity"]["column"]
        primary_type = mapping["primary_entity"]["type"]
        attributes_map = mapping.get("attributes", {})
        relationships_config = mapping.get("relationships", [])

        if primary_col not in df.columns:
            logger.warning(f"Primary column '{primary_col}' not found. Selecting first column as key.")
            primary_col = df.columns[0] if len(df.columns) > 0 else None

        mapped_cols = {primary_col}
        mapped_cols.update(attributes_map.keys())
        mapped_cols.update([rc.get("column") for rc in relationships_config if rc.get("column")])

        for col in df.columns:
            if col not in mapped_cols:
                logger.info(f"Adding unmapped column '{col}' as an attribute to prevent data loss.")
                attributes_map[col] = str(col).lower().replace(" ", "_")

        total_rows = len(df)
        if total_rows == 0:
            return {"chunks_created": 0, "entities_created": 0, "relationships_created": 0}

        # 1. Generate Row Chunks and Table Summary Chunk
        chunk_texts = []
        chunk_metadatas = []

        # Table Summary Chunk (Level 2)
        summary_text = f"Dataset Sheet: {sheet_name}.\nColumns: {', '.join(df.columns)}.\nTotal Rows: {total_rows}."
        chunk_texts.append(summary_text)
        chunk_metadatas.append({
            "chunk_type": "table_summary",
            "sheet_name": sheet_name,
            "row_count": total_rows,
            "entity_type": primary_type
        })

        # Process each row (Level 1)
        row_dicts = df.to_dict(orient="records")
        for i, row in enumerate(row_dicts):
            primary_val = str(row[primary_col]) if primary_col and pd.notnull(row.get(primary_col)) else f"row_{i}"
            
            # Build Semantic Text for Vector Search
            semantic_parts = [f"{primary_type}: {primary_val}"]
            
            # Attributes
            for col, prop_name in attributes_map.items():
                val = row.get(col)
                if pd.notnull(val) and str(val).strip():
                    semantic_parts.append(f"{col}: {val}")
                    
            # Relationships
            for rc in relationships_config:
                col = rc["column"]
                if pd.notnull(row.get(col)) and str(row[col]).strip():
                    semantic_parts.append(f"{col} ({rc['target_type']}): {row[col]}")
            
            semantic_text = " | ".join(semantic_parts)
            
            # Clean row dict to store in metadata
            clean_row = {k: v for k, v in row.items() if pd.notnull(v)}
            
            chunk_texts.append(semantic_text)
            chunk_metadatas.append({
                "chunk_type": "row",
                "row_id": f"{sheet_name}_row_{i}",
                "sheet_name": sheet_name,
                "row_number": i,
                "entity_type": primary_type,
                "raw_data": clean_row
            })

        chunks_created = len(chunk_texts)

        # 2. Embed all chunk texts in a single batch
        logger.info(f"Generating embeddings for {chunks_created} row/summary chunks...")
        embeddings = await EmbeddingGenerator.generate_embeddings_batch(chunk_texts)
        if len(embeddings) != chunks_created:
            raise RuntimeError("Embeddings batch generation failed or size mismatched.")

        # 3. Create PG Chunks with metadata_json
        chunk_ids = [str(uuid.uuid4()) for _ in range(chunks_created)]
        
        for idx in range(chunks_created):
            pg_chunk = DocumentChunk(
                id=uuid.UUID(chunk_ids[idx]),
                tenant_id=uuid.UUID(self.tenant_id),
                kb_id=uuid.UUID(kb_id),
                text=chunk_texts[idx],
                chunk_index=idx,
                embedding=embeddings[idx],
                metadata_json=chunk_metadatas[idx]
            )
            self.db.add(pg_chunk)
            
        logger.info(f" Staged {chunks_created} semantic row chunks in PostgreSQL")

        # 4. Populate Graph Database if within safe limits
        entities_created = set()
        relationships_created = 0
        
        if total_rows > 100000:
            logger.warning(f" Skipping Neo4j graph generation for {sheet_name} ({total_rows} rows > 100k limit).")
        else:
            logger.info(f" Generating Neo4j Graph Entities for {total_rows} rows...")
            clean_primary_label = re.sub(r"[^a-zA-Z0-9_]", "", primary_type.upper())
            
            for i, row in enumerate(row_dicts):
                primary_val = str(row[primary_col]) if primary_col and pd.notnull(row.get(primary_col)) else f"row_{i}"
                chunk_id = chunk_ids[i + 1] # Offset by 1 because index 0 is summary chunk
                
                row_attrs = {}
                for col, prop in attributes_map.items():
                    if pd.notnull(row.get(col)):
                        row_attrs[prop] = str(row[col])
                row_attrs["name"] = primary_val
                row_attrs["row_id"] = f"{sheet_name}_row_{i}"

                # Merge primary entity as the Row Entity
                primary_merge_query = f"""
                MERGE (e:Entity {clean_primary_label.join([':', ''])} {{tenant_id: $tenant_id, text: $id_val, type: $type}})
                ON CREATE SET e.id = randomUUID(), e.created_at = timestamp()
                SET e.properties = $properties, e.chunk_id = $chunk_id
                RETURN e.id as id
                """
                await retry_neo4j_operation(lambda: self.neo4j_repo.execute_write(
                    primary_merge_query,
                    {
                        "tenant_id": self.tenant_id,
                        "id_val": primary_val,
                        "type": primary_type,
                        "properties": row_attrs,
                        "chunk_id": chunk_id
                    }
                ))
                entities_created.add(f"{primary_val}|{primary_type}")

                # Merge target entities and create relationship links
                for rc in relationships_config:
                    col = rc["column"]
                    if pd.notnull(row.get(col)) and str(row[col]).strip():
                        tgt_val = str(row[col])
                        tgt_type = rc["target_type"]
                        pred = rc["relation"]

                        clean_tgt_label = re.sub(r"[^a-zA-Z0-9_]", "", tgt_type.upper())
                        clean_rel_type = re.sub(r"[^a-zA-Z0-9_]", "", pred.upper())

                        target_merge_query = f"""
                        MERGE (tgt:Entity {clean_tgt_label.join([':', ''])} {{tenant_id: $tenant_id, text: $tgt_val, type: $type}})
                        ON CREATE SET tgt.id = randomUUID(), tgt.created_at = timestamp()
                        RETURN tgt.id as id
                        """
                        await retry_neo4j_operation(lambda: self.neo4j_repo.execute_write(
                            target_merge_query,
                            {
                                "tenant_id": self.tenant_id,
                                "tgt_val": tgt_val,
                                "type": tgt_type
                            }
                        ))
                        entities_created.add(f"{tgt_val}|{tgt_type}")

                        edge_create_query = f"""
                        MATCH (src:Entity {{tenant_id: $tenant_id, text: $src_val, type: $src_type}})
                        MATCH (tgt:Entity {{tenant_id: $tenant_id, text: $tgt_val, type: $tgt_type}})
                        MERGE (src)-[r:{clean_rel_type} {{tenant_id: $tenant_id}}]->(tgt)
                        """
                        await retry_neo4j_operation(lambda: self.neo4j_repo.execute_write(
                            edge_create_query,
                            {
                                "tenant_id": self.tenant_id,
                                "src_val": primary_val,
                                "src_type": primary_type,
                                "tgt_val": tgt_val,
                                "tgt_type": tgt_type
                            }
                        ))
                        relationships_created += 1

        logger.info(f" Ingested sheet '{sheet_name}': {chunks_created} chunks, {len(entities_created)} entities, {relationships_created} relationships")

        return {
            "chunks_created": chunks_created,
            "entities_created": len(entities_created),
            "relationships_created": relationships_created
        }

