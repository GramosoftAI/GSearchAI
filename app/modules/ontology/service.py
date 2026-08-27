"""Ontology service - manages entity and relationship types in the graph"""

import logging
from typing import List, Dict, Optional
from ...core.neo4j_repository import Neo4jRepository
from ...core.embeddings import EmbeddingGenerator
from . import schemas

logger = logging.getLogger(__name__)

class OntologyService:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.neo4j_repo = Neo4jRepository(tenant_id)

    async def create_class(self, request: schemas.OntologyClassCreate) -> dict:
        """Create a new grounded entity type (Ontology Class)"""
        name = request.name.upper().strip().replace(" ", "_")
        
        # Generate embedding for fuzzy matching later
        text_to_embed = f"{name}: {request.description or ''}"
        embedding = await EmbeddingGenerator.generate_embedding(text_to_embed)
        
        query = """
        MERGE (c:OntologyClass {tenant_id: $tenant_id, name: $name})
        SET c.description = $description,
            c.embedding = $embedding,
            c.updated_at = timestamp()
        RETURN c.name as name
        """
        
        await self.neo4j_repo.execute_write(query, {
            "tenant_id": self.tenant_id,
            "name": name,
            "description": request.description,
            "embedding": embedding
        })
        
        logger.info(f" Ontology Class created: {name} for tenant {self.tenant_id}")
        return {"success": True, "name": name}

    async def create_relation(self, request: schemas.OntologyRelationCreate) -> dict:
        """Create a new grounded relationship type"""
        name = request.name.upper().strip().replace(" ", "_")
        
        query = """
        MERGE (r:OntologyRelation {tenant_id: $tenant_id, name: $name})
        SET r.description = $description,
            r.updated_at = timestamp()
        RETURN r.name as name
        """
        
        await self.neo4j_repo.execute_write(query, {
            "tenant_id": self.tenant_id,
            "name": name,
            "description": request.description
        })
        
        logger.info(f" Ontology Relation created: {name}")
        return {"success": True, "name": name}

    async def create_rule(self, request: schemas.OntologyRuleCreate) -> dict:
        """Create a new strict ontology rule"""
        source = request.source_class.upper().strip().replace(" ", "_")
        relation = request.relation.upper().strip().replace(" ", "_")
        target = request.target_class.upper().strip().replace(" ", "_")
        
        query = """
        MERGE (c1:OntologyClass {tenant_id: $tenant_id, name: $source})
        MERGE (c2:OntologyClass {tenant_id: $tenant_id, name: $target})
        MERGE (r:OntologyRelation {tenant_id: $tenant_id, name: $relation})
        MERGE (c1)-[rule:ALLOWED_RELATION {name: $relation}]->(c2)
        SET rule.description = $description,
            rule.updated_at = timestamp()
        RETURN rule.name as name
        """
        
        await self.neo4j_repo.execute_write(query, {
            "tenant_id": self.tenant_id,
            "source": source,
            "relation": relation,
            "target": target,
            "description": request.description
        })
        
        logger.info(f" Ontology Rule created: {source} -[{relation}]-> {target}")
        return {"success": True, "source": source, "relation": relation, "target": target}

    _ontology_cache: Dict[str, tuple] = {}  # {tenant_id: (timestamp, data)}

    async def get_ontology(self) -> dict:
        """Fetch the full ontology for a tenant (cached for 60s)"""
        import time
        now = time.time()
        cached = self._ontology_cache.get(self.tenant_id)
        if cached and (now - cached[0]) < 60.0:
            return cached[1]

        query = """
        MATCH (c:OntologyClass {tenant_id: $tenant_id})
        WITH collect({name: c.name, description: c.description}) as classes
        
        OPTIONAL MATCH (r:OntologyRelation {tenant_id: $tenant_id})
        WITH classes, collect({name: r.name, description: r.description}) as relations
        
        OPTIONAL MATCH (c1:OntologyClass {tenant_id: $tenant_id})-[rule:ALLOWED_RELATION]->(c2:OntologyClass {tenant_id: $tenant_id})
        WITH classes, relations, collect({
            source_class: c1.name, 
            relation: rule.name, 
            target_class: c2.name, 
            description: rule.description
        }) as rules
        
        RETURN classes, relations, rules
        """
        
        results = await self.neo4j_repo.execute_read(query, {"tenant_id": self.tenant_id})
        data = results[0] if results else {"classes": [], "relations": [], "rules": []}
        self._ontology_cache[self.tenant_id] = (now, data)
        return data

    async def ground_type(self, raw_type: str) -> Optional[str]:
        """
        Fuzzy ground a raw extraction type to the nearest ontology class.
        Uses vector similarity.
        """
        raw_type = raw_type.upper().strip().replace(" ", "_")
        
        # 1. Try exact match first
        query_exact = """
        MATCH (c:OntologyClass {tenant_id: $tenant_id, name: $name})
        RETURN c.name as name
        """
        exact = await self.neo4j_repo.execute_read(query_exact, {"tenant_id": self.tenant_id, "name": raw_type})
        if exact:
            return exact[0]["name"]
            
        # 2. Try fuzzy match via embedding
        raw_embedding = await EmbeddingGenerator.generate_embedding(raw_type)
        if not raw_embedding:
            return None
            
        query_fuzzy = """
        MATCH (c:OntologyClass {tenant_id: $tenant_id})
        WHERE c.embedding IS NOT NULL AND size(c.embedding) > 0
        WITH c, vector.similarity.cosine(c.embedding, $embedding) as sim
        WHERE sim > 0.85
        RETURN c.name as name
        ORDER BY sim DESC
        LIMIT 1
        """
        
        fuzzy = await self.neo4j_repo.execute_read(query_fuzzy, {
            "tenant_id": self.tenant_id, 
            "embedding": raw_embedding
        })
        
        if fuzzy:
            return fuzzy[0]["name"]
            
        return None

    async def auto_register_schema(self, schema: Dict[str, List[Dict]]) -> None:
        """
        Dynamically register discovered classes and relations.
        Uses exact name matching (MERGE) to prevent duplicates.
        """
        classes = schema.get("classes", [])
        relations = schema.get("relations", [])
        
        logger.info(f"Auto-registering schema: {len(classes)} classes, {len(relations)} relations for tenant {self.tenant_id}")
        
        for c in classes:
            try:
                query = "MATCH (n:OntologyClass {tenant_id: $tenant_id, name: $name}) RETURN n"
                existing = await self.neo4j_repo.execute_read(query, {"tenant_id": self.tenant_id, "name": c["name"]})
                if not existing:
                    req = schemas.OntologyClassCreate(name=c["name"], description=c.get("description", ""))
                    await self.create_class(req)
            except Exception as e:
                logger.warning(f"Failed to auto-register class {c['name']}: {e}")
                
        for r in relations:
            try:
                query = "MATCH (n:OntologyRelation {tenant_id: $tenant_id, name: $name}) RETURN n"
                existing = await self.neo4j_repo.execute_read(query, {"tenant_id": self.tenant_id, "name": r["name"]})
                if not existing:
                    req = schemas.OntologyRelationCreate(name=r["name"], description=r.get("description", ""))
                    await self.create_relation(req)
            except Exception as e:
                logger.warning(f"Failed to auto-register relation {r['name']}: {e}")

    async def upload_ontology_file(self, file_content: bytes, format: str = "xml") -> dict:
        """
        Upload an RDF/OWL/TTL ontology file.
        1. Parses file into rdflib Graph.
        2. Extracts owl:Class and owl:ObjectProperty to sync with GRAG schema.
        3. Pushes full RDF graph natively into Neo4j via rdflib_neo4j.
        """
        from rdflib import Graph, URIRef
        from rdflib.namespace import OWL, RDFS, RDF
        from rdflib_neo4j import Neo4jStoreConfig, Neo4jStore, HANDLE_VOCAB_URI_STRATEGY
        from neo4j import GraphDatabase
        from ...core.config import get_settings
        
        # Parse into local memory graph first
        g = Graph()
        g.parse(data=file_content, format=format)
        
        classes_synced = 0
        relations_synced = 0
        
        # Sync Classes
        q_classes = """
        SELECT DISTINCT ?cls WHERE {
            { ?cls a owl:Class } UNION { ?cls a rdfs:Class }
            FILTER(isIRI(?cls))
        }
        """
        for row in g.query(q_classes):
            cls_uri = str(row[0])
            # Extract local name (e.g., http://example.org/ontology#Person -> Person)
            name = cls_uri.split("#")[-1].split("/")[-1]
            if name:
                req = schemas.OntologyClassCreate(name=name, description=f"Imported from {cls_uri}")
                await self.create_class(req)
                classes_synced += 1

        # Sync Relations
        q_props = """
        SELECT DISTINCT ?prop WHERE {
            ?prop a owl:ObjectProperty
            FILTER(isIRI(?prop))
        }
        """
        for row in g.query(q_props):
            prop_uri = str(row[0])
            name = prop_uri.split("#")[-1].split("/")[-1]
            if name:
                req = schemas.OntologyRelationCreate(name=name, description=f"Imported from {prop_uri}")
                await self.create_relation(req)
                relations_synced += 1
                
        # Push raw triples to Neo4j globally
        try:
            settings = get_settings()
            driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password)
            )
            config = Neo4jStoreConfig(
                batching=True,
                handle_vocab_uri_strategy=HANDLE_VOCAB_URI_STRATEGY.IGNORE
            )
            store = Neo4jStore(config=config, driver=driver)
            neo_g = Graph(store=store)
            neo_g.parse(data=file_content, format=format)
            driver.close()
            triples_pushed = len(g)
        except Exception as e:
            logger.error(f"Failed to push raw triples to Neo4j: {e}")
            triples_pushed = 0

        logger.info(f"Ontology file processed. Synced {classes_synced} classes, {relations_synced} relations.")
        return {
            "success": True,
            "classes_synced": classes_synced,
            "relations_synced": relations_synced,
            "raw_triples_pushed": triples_pushed
        }
