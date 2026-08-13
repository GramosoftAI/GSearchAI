"""
Graph Database Cleanup (Entity Resolution and Deduplication) Module

Provides GraphCleanupService to identify and merge duplicate entities, re-route
relationships, resolve canonical names/properties, and remove duplicate relationships
within a Neo4j knowledge graph using a safe, multi-factor similarity algorithm
and LLM-based verification.
"""

import re
import asyncio
import json
import logging
import uuid
from typing import List, Dict, Any, Tuple, Optional
from collections import deque

from app.core.neo4j import get_neo4j_driver
from app.core.embeddings import EmbeddingGenerator
from app.core.llm.deepinfra_llm import DeepInfraLLMClient
from app.core.neo4j_repository import Neo4jRepository

logger = logging.getLogger(__name__)


def _safe_dict_prop(val: Any) -> Dict[str, Any]:
    if isinstance(val, dict):
        return dict(val)
    if isinstance(val, str) and val.strip():
        try:
            parsed = json.loads(val)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


class GraphCleanupService:
    """
    Service to execute Graph Database Cleanup (Entity Resolution & Deduplication).
    
    Guarantees:
    - Tenant isolation (never leak or merge cross-tenant data)
    - Safety first (never merge on name alone, avoid identifier conflicts)
    - Data integrity (never lose properties or relationships, rollback on failure)
    """

    def __init__(
        self,
        tenant_id: str,
        kb_id: Optional[str] = None,
        auto_merge_threshold: float = 95.0,
        llm_review_threshold: float = 85.0
    ):
        if not tenant_id:
            raise ValueError("tenant_id is required for GraphCleanupService")
        self.tenant_id = tenant_id
        self.kb_id = kb_id
        self.auto_merge_threshold = auto_merge_threshold
        self.llm_review_threshold = llm_review_threshold
        self.embedding_override_threshold = 0.85
        
        self.llm_client = DeepInfraLLMClient()
        self.neo4j_repo = Neo4jRepository(tenant_id)

        # Similarity calculation weights (must sum to 100)
        self.NAME_WEIGHT = 30
        self.ORG_WEIGHT = 20
        self.RELATIONSHIP_WEIGHT = 20
        self.LOCATION_WEIGHT = 15
        self.PROPERTY_WEIGHT = 10
        self.EMBEDDING_WEIGHT = 5

        # Unique identifier keys that strictly forbid merge if values conflict
        self.UNIQUE_KEYS = [
            "email", "passport_number", "employee_id", "uuid", "ssn", 
            "tax_id", "phone"
        ]

    def _is_deduplicable_node(self, node: Dict[str, Any]) -> bool:
        """
        Check if an entity node is actually candidate for deduplication.
        Filters out dates, numbers, emails, URLs, short tags, and garbage placeholders.
        """
        etype = node.get("type", "UNKNOWN").upper().strip()
        if etype not in ["NAME", "ORGANIZATION", "LOCATION", "CONCEPT"]:
            return False
        
        name = (node.get("display_name") or node.get("normalized_name") or node.get("name") or "").strip()
        if not name or len(name) < 3:
            return False
            
        # Check if name is purely numeric or decimal
        if re.match(r'^\d+(\.\d+)?$', name):
            return False
            
        # Check if name has number ranges
        if re.search(r'\d+\s+to\s+\d+', name, re.IGNORECASE):
            return False
            
        # Check if it matches code pattern (e.g. e100, e200)
        if re.match(r'^[eE]\d+$', name):
            return False
            
        # Date-like patterns
        date_patterns = [
            r'^\d{4}[-/.]\d{2}[-/.]\d{2}',
            r'^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}',
            r'^\d{4}$',
        ]
        for pattern in date_patterns:
            if re.search(pattern, name):
                return False
                
        # Email pattern
        if "@" in name and "." in name:
            return False
            
        # URL pattern
        if name.startswith("http://") or name.startswith("https://") or name.startswith("www."):
            return False
            
        # Phone number pattern
        if re.match(r'^\+?\d[\d\s-]{7,15}$', name):
            return False
            
        # Specific garbage/placeholder terms
        if name.lower() in ["reading 1", "reading 2", "unknown", "none", "null", "n/a", "a +", "a -"]:
            return False
            
        return True

    def _normalize_single_name(self, name: str) -> Tuple[str, str]:
        """
        Normalize entity name for comparison while preserving display name.
        """
        if not name:
            return "", ""
        cleaned = re.sub(r'\s+', ' ', name.strip())
        prefix_pattern = re.compile(
            r'^(?:mr|mrs|ms|dr|prof)\b\.?\s*', 
            re.IGNORECASE
        )
        display_name = prefix_pattern.sub('', cleaned).strip()
        normalized_name = display_name.lower()
        return display_name, normalized_name

    def _is_acronym_match(self, s1: str, s2: str) -> bool:
        """Check if one string is an acronym of the other."""
        if not s1 or not s2:
            return False
            
        n1 = s1.lower().strip()
        n2 = s2.lower().strip()
        
        if n1 == n2:
            return True
            
        if len(n1) > len(n2):
            n1, n2 = n2, n1
            
        n1 = n1.replace(".", "").replace(" ", "")
        
        if len(n1) < 2:
            return False
            
        tokens = re.split(r'[\s\-]+', n2)
        tokens = [t for t in tokens if t]
        
        if not tokens:
            return False
            
        first_letters = "".join([t[0] for t in tokens if t])
        if first_letters == n1:
            return True
            
        stop_words = {"and", "of", "the", "for", "in", "to", "a", "an", "with", "by", "at", "on"}
        significant_tokens = [t for t in tokens if t not in stop_words]
        first_letters_sig = "".join([t[0] for t in significant_tokens if t])
        if first_letters_sig == n1:
            return True
            
        return False

    async def normalize_entities(self) -> Dict[str, Any]:
        """
        Scans normalized nodes of label Entity and TripletEntity, computes
        display_name and normalized_name, and updates them in Neo4j.
        """
        logger.info(f"Normalizing entity names for tenant {self.tenant_id}...")

        if self.kb_id:
            query = """
            MATCH (c:Chunk {kb_id: $kb_id, tenant_id: $tenant_id})
            MATCH (c)-[:MENTIONS|EXTRACTED_FROM*1..2]-(n)
            WHERE (n:Entity OR n:TripletEntity) AND n.tenant_id = $tenant_id
            RETURN DISTINCT elementId(n) AS internal_id, coalesce(n.name, n.text, n.display_name, '') AS raw_name
            """
            results = await self.neo4j_repo.execute_read(query, {"tenant_id": self.tenant_id, "kb_id": self.kb_id})
        else:
            query = """
            MATCH (n)
            WHERE (n:Entity OR n:TripletEntity) AND n.tenant_id = $tenant_id
            RETURN elementId(n) AS internal_id, coalesce(n.name, n.text, n.display_name, '') AS raw_name
            """
            results = await self.neo4j_repo.execute_read(query, {"tenant_id": self.tenant_id})

        updated_count = 0
        driver = await get_neo4j_driver()
        async with driver.session() as session:
            for record in results:
                internal_id = record["internal_id"]
                raw_name = record["raw_name"]
                if not raw_name:
                    continue

                display_name, normalized_name = self._normalize_single_name(raw_name)

                # Set display_name and normalized_name using elementId
                update_query = """
                MATCH (n)
                WHERE elementId(n) = $internal_id AND n.tenant_id = $tenant_id
                SET n.display_name = $display_name, n.normalized_name = $normalized_name
                """
                try:
                    await session.run(update_query, {
                        "internal_id": internal_id,
                        "tenant_id": self.tenant_id,
                        "display_name": display_name,
                        "normalized_name": normalized_name
                    })
                    updated_count += 1
                except Exception as e:
                    logger.error(f"Failed to update normalized properties: {e}")

        logger.info(f"Normalized {updated_count} entity names in graph.")
        return {"normalized_count": updated_count}

    async def find_duplicate_candidates(self) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """
        Identify candidates for merging using a Sorted Neighborhood blocker + bucket index.
        Returns:
             List of candidate node dictionary pairs.
        """
        logger.info(f"Finding duplicate candidates for tenant {self.tenant_id}...")

        # Fetch nodes with their labels, properties, and relationship context
        if self.kb_id:
            # Document-scoped cleanup
            query = """
            MATCH (c:Chunk {kb_id: $kb_id, tenant_id: $tenant_id})
            OPTIONAL MATCH (c)-[:MENTIONS]->(e:Entity)
            OPTIONAL MATCH (c)-[:HAS_TRIPLET]->(:Triplet)-[:SUBJECT|OBJECT]->(t:TripletEntity)
            WITH collect(e) + collect(t) AS all_e
            UNWIND all_e AS n
            WITH DISTINCT n
            WHERE n IS NOT NULL AND (n:Entity OR n:TripletEntity) AND n.tenant_id = $tenant_id
            
            RETURN n, labels(n) AS labels, elementId(n) as internal_id,
                   [(n)-[r]->(target) WHERE target.tenant_id = $tenant_id | {type: type(r), target_id: target.id, target_label: labels(target)[0], target_name: coalesce(target.name, target.display_name, target["title"])}] AS outgoing,
                   [(source)-[r_in]->(n) WHERE source.tenant_id = $tenant_id | {type: type(r_in), source_id: source.id, source_label: labels(source)[0], source_name: coalesce(source.name, source.display_name, source["title"])}] AS incoming
            """
            results = await self.neo4j_repo.execute_read(query, {"tenant_id": self.tenant_id, "kb_id": self.kb_id})
        else:
            # Full tenant cleanup (for background jobs)
            query = """
            MATCH (n)
            WHERE (n:Entity OR n:TripletEntity) AND n.tenant_id = $tenant_id
            
            RETURN n, labels(n) AS labels, elementId(n) as internal_id,
                   [(n)-[r]->(target) WHERE target.tenant_id = $tenant_id | {type: type(r), target_id: target.id, target_label: labels(target)[0], target_name: coalesce(target.name, target.display_name, target["title"])}] AS outgoing,
                   [(source)-[r_in]->(n) WHERE source.tenant_id = $tenant_id | {type: type(r_in), source_id: source.id, source_label: labels(source)[0], source_name: coalesce(source.name, source.display_name, source["title"])}] AS incoming
            """
            results = await self.neo4j_repo.execute_read(query, {"tenant_id": self.tenant_id})

        nodes = []
        for record in results:
            node_props = dict(record["n"])
            node_props["_internal_id"] = record["internal_id"]
            node_props["_labels"] = record["labels"]

            # Filter out empty relationships
            outgoing = [o for o in record["outgoing"] if o.get("target_id") is not None]
            incoming = [i for i in record["incoming"] if i.get("source_id") is not None]

            node_props["_outgoing"] = outgoing
            node_props["_incoming"] = incoming

            # Ensure normalization properties exist
            if "normalized_name" not in node_props or "display_name" not in node_props:
                raw_name = node_props.get("name") or node_props.get("text") or node_props.get("display_name") or ""
                disp, norm = self._normalize_single_name(raw_name)
                node_props["display_name"] = disp
                node_props["normalized_name"] = norm

            nodes.append(node_props)

        # Group nodes by type property
        groups = {}
        for node in nodes:
            if not self._is_deduplicable_node(node):
                continue
            entity_type = node.get("type", "UNKNOWN").upper().strip()

            group_key = entity_type
            if group_key not in groups:
                groups[group_key] = []
            groups[group_key].append(node)

        candidate_pairs = []
        seen_pairs = set()

        def add_pair(node_a, node_b):
            id_a, id_b = node_a["_internal_id"], node_b["_internal_id"]
            if id_a == id_b:
                return
            pair_key = tuple(sorted([str(id_a), str(id_b)]))
            if pair_key not in seen_pairs:
                seen_pairs.add(pair_key)
                candidate_pairs.append((node_a, node_b))

        # Perform blocking for each group
        for etype, group_nodes in groups.items():
            if len(group_nodes) < 2:
                continue

            valid_nodes = [n for n in group_nodes if n.get("normalized_name")]

            # 1. Bucket Indexing
            first_token_buckets = {}
            prefix_buckets = {}
            for node in valid_nodes:
                norm_name = node["normalized_name"]

                # First token bucket
                tokens = norm_name.split()
                if tokens:
                    first_token = tokens[0]
                    if first_token not in first_token_buckets:
                        first_token_buckets[first_token] = []
                    first_token_buckets[first_token].append(node)

                # 3-char prefix bucket
                prefix = norm_name[:3]
                if len(prefix) >= 3:
                    if prefix not in prefix_buckets:
                        prefix_buckets[prefix] = []
                    prefix_buckets[prefix].append(node)

            # Pair up bucket members
            for bucket in first_token_buckets.values():
                for i in range(len(bucket)):
                    for j in range(i + 1, len(bucket)):
                        add_pair(bucket[i], bucket[j])

            for bucket in prefix_buckets.values():
                for i in range(len(bucket)):
                    for j in range(i + 1, len(bucket)):
                        add_pair(bucket[i], bucket[j])

            # 2. Sorted Neighborhood sliding window
            sorted_nodes = sorted(valid_nodes, key=lambda x: x["normalized_name"])
            window_size = 15
            for i in range(len(sorted_nodes)):
                for j in range(i + 1, min(i + 1 + window_size, len(sorted_nodes))):
                    add_pair(sorted_nodes[i], sorted_nodes[j])

            # 3. Acronym & High Embedding Similarity pairing
            for i in range(len(valid_nodes)):
                node_a = valid_nodes[i]
                name_a = node_a["normalized_name"]
                emb_a = node_a.get("embedding")
                if isinstance(emb_a, str):
                    try:
                        emb_a = json.loads(emb_a)
                    except Exception:
                        emb_a = None

                for j in range(i + 1, len(valid_nodes)):
                    node_b = valid_nodes[j]
                    name_b = node_b["normalized_name"]

                    if self._is_acronym_match(name_a, name_b):
                        add_pair(node_a, node_b)
                        continue

                    emb_b = node_b.get("embedding")
                    if isinstance(emb_b, str):
                        try:
                            emb_b = json.loads(emb_b)
                        except Exception:
                            emb_b = None

                    if emb_a and emb_b and len(emb_a) > 0 and len(emb_b) > 0:
                        sim = EmbeddingGenerator.cosine_similarity(emb_a, emb_b)
                        if sim >= self.embedding_override_threshold:
                            add_pair(node_a, node_b)

        logger.info(f"Found {len(candidate_pairs)} candidate pairs.")
        return candidate_pairs

    def _levenshtein_similarity(self, s1: str, s2: str) -> float:
        """Calculate Levenshtein distance similarity ratio."""
        if not s1 or not s2:
            return 0.0
        if s1 == s2:
            return 1.0
        m, n = len(s1), len(s2)
        if m < n:
            s1, s2 = s2, s1
            m, n = n, m
        prev = list(range(n + 1))
        for i in range(1, m + 1):
            curr = [i] + [0] * n
            for j in range(1, n + 1):
                if s1[i - 1] == s2[j - 1]:
                    curr[j] = prev[j - 1]
                else:
                    curr[j] = min(prev[j - 1], prev[j], curr[j - 1]) + 1
            prev = curr
        dist = prev[n]
        return 1.0 - (dist / max(m, n))

    def _calculate_org_similarity(self, node1: Dict[str, Any], node2: Dict[str, Any]) -> float:
        """Compare properties and relationships related to Organization."""
        keys = ["organization", "company", "employer", "works_at", "worksat"]
        val1 = next((node1.get(k) for k in keys if node1.get(k)), None)
        val2 = next((node2.get(k) for k in keys if node2.get(k)), None)

        prop_score = None
        if val1 and val2:
            prop_score = 1.0 if str(val1).strip().lower() == str(val2).strip().lower() else 0.0

        rel_vals1 = {
            o["target_name"].strip().lower() 
            for o in node1.get("_outgoing", []) 
            if (o["type"] in ["WORKS_AT", "EMPLOYEE_OF"] or (o["type"] == "RELATES_TO" and o.get("target_label") in ["Organization", "Company"])) and o.get("target_name")
        }
        rel_vals2 = {
            o["target_name"].strip().lower() 
            for o in node2.get("_outgoing", []) 
            if (o["type"] in ["WORKS_AT", "EMPLOYEE_OF"] or (o["type"] == "RELATES_TO" and o.get("target_label") in ["Organization", "Company"])) and o.get("target_name")
        }

        # Filter to organization-like target names if relationship type is generic
        org_keywords = {"tech", "company", "corp", "inc", "ltd", "university", "school", "college", "solutions", "limited", "academy", "instit", "industr"}
        filtered_rels1 = {
            name for name in rel_vals1 
            if any(keyword in name for keyword in org_keywords)
        }
        filtered_rels2 = {
            name for name in rel_vals2 
            if any(keyword in name for keyword in org_keywords)
        }

        rel_score = None
        if filtered_rels1 and filtered_rels2:
            rel_score = 1.0 if filtered_rels1.intersection(filtered_rels2) else 0.0

        scores = [s for s in [prop_score, rel_score] if s is not None]
        return sum(scores) / len(scores) if scores else 0.5

    def _calculate_loc_similarity(self, node1: Dict[str, Any], node2: Dict[str, Any]) -> float:
        """Compare properties and relationships related to Location."""
        keys = ["location", "city", "country", "address", "state"]
        val1 = next((node1.get(k) for k in keys if node1.get(k)), None)
        val2 = next((node2.get(k) for k in keys if node2.get(k)), None)

        prop_score = None
        if val1 and val2:
            prop_score = 1.0 if str(val1).strip().lower() == str(val2).strip().lower() else 0.0

        rel_vals1 = {
            o["target_name"].strip().lower() 
            for o in node1.get("_outgoing", []) 
            if (o["type"] in ["LIVES_IN", "LOCATED_IN"] or (o["type"] == "RELATES_TO" and o.get("target_label") == "Location")) and o.get("target_name")
        }
        rel_vals2 = {
            o["target_name"].strip().lower() 
            for o in node2.get("_outgoing", []) 
            if (o["type"] in ["LIVES_IN", "LOCATED_IN"] or (o["type"] == "RELATES_TO" and o.get("target_label") == "Location")) and o.get("target_name")
        }

        # Filter out common organization keywords to prevent matching companies as locations
        org_keywords = {"tech", "company", "corp", "inc", "ltd", "university", "school", "college", "solutions", "limited", "academy", "instit", "industr"}
        filtered_rels1 = {
            name for name in rel_vals1 
            if not any(keyword in name for keyword in org_keywords)
        }
        filtered_rels2 = {
            name for name in rel_vals2 
            if not any(keyword in name for keyword in org_keywords)
        }

        rel_score = None
        if filtered_rels1 and filtered_rels2:
            rel_score = 1.0 if filtered_rels1.intersection(filtered_rels2) else 0.0

        scores = [s for s in [prop_score, rel_score] if s is not None]
        return sum(scores) / len(scores) if scores else 0.5

    def _calculate_relationship_similarity(self, node1: Dict[str, Any], node2: Dict[str, Any]) -> float:
        """Compute Jaccard similarity of relationship neighborhoods and penalize conflict."""
        rels1 = set()
        for o in node1.get("_outgoing", []):
            if o.get("target_name"):
                rels1.add((o["type"], o.get("target_label"), o["target_name"].strip().lower()))
        for i in node1.get("_incoming", []):
            if i.get("source_name"):
                rels1.add((i["type"], i.get("source_label"), i["source_name"].strip().lower()))

        rels2 = set()
        for o in node2.get("_outgoing", []):
            if o.get("target_name"):
                rels2.add((o["type"], o.get("target_label"), o["target_name"].strip().lower()))
        for i in node2.get("_incoming", []):
            if i.get("source_name"):
                rels2.add((i["type"], i.get("source_label"), i["source_name"].strip().lower()))

        if not rels1 or not rels2:
            return 0.5

        union = rels1.union(rels2)
        intersection = rels1.intersection(rels2)

        # Single-valued conflict check (different employers or locations)
        conflict_penalty = 0.0
        single_valued_types = {"WORKS_AT", "EMPLOYEE_OF", "SPOUSE", "LIVES_IN"}
        for rtype in single_valued_types:
            targets1 = {target for type_, _, target in rels1 if type_ == rtype}
            targets2 = {target for type_, _, target in rels2 if type_ == rtype}
            if targets1 and targets2 and not targets1.intersection(targets2):
                conflict_penalty = 0.3

        jaccard = len(intersection) / len(union) if union else 0.5
        return max(0.0, jaccard - conflict_penalty)

    def _calculate_properties_overlap(self, node1: Dict[str, Any], node2: Dict[str, Any]) -> float:
        """Calculate overlap matching ratio of standard property values."""
        exclude = {
            "id", "tenant_id", "created_at", "normalized_name", "display_name",
            "aliases", "embedding", "_internal_id", "_labels", "_outgoing", "_incoming", "chunk_id"
        }
        keys1 = {k for k in node1.keys() if k not in exclude and node1.get(k) is not None}
        keys2 = {k for k in node2.keys() if k not in exclude and node2.get(k) is not None}

        shared = keys1.intersection(keys2)
        if not shared:
            return 0.5

        matches = 0
        for k in shared:
            val1 = str(node1[k]).strip().lower()
            val2 = str(node2[k]).strip().lower()
            if val1 == val2:
                matches += 1

        return matches / len(shared)

    def _calculate_embedding_similarity(self, node1: Dict[str, Any], node2: Dict[str, Any]) -> float:
        """Calculate cosine similarity between node embeddings."""
        emb1 = node1.get("embedding")
        emb2 = node2.get("embedding")

        if isinstance(emb1, str):
            try:
                emb1 = json.loads(emb1)
            except Exception:
                emb1 = None
        if isinstance(emb2, str):
            try:
                emb2 = json.loads(emb2)
            except Exception:
                emb2 = None

        if emb1 and emb2 and len(emb1) > 0 and len(emb2) > 0:
            return EmbeddingGenerator.cosine_similarity(emb1, emb2)
        return 0.5

    def calculate_similarity(self, node1: Dict[str, Any], node2: Dict[str, Any]) -> float:
        """
        Calculate a multi-factor similarity score between 0 and 100.
        Checks for unique identifier conflicts early and returns 0.0 if conflicted.
        """
        # Early rejection: check unique identifier conflicts
        for key in self.UNIQUE_KEYS:
            val1 = node1.get(key)
            val2 = node2.get(key)
            if val1 and val2:
                if str(val1).strip().lower() != str(val2).strip().lower():
                    logger.debug(
                        f"Merge rejected: conflicting unique identifier '{key}': "
                        f"{val1} != {val2}"
                    )
                    return 0.0

        # Calculate scores
        name1 = node1.get("normalized_name", "")
        name2 = node2.get("normalized_name", "")
        if self._is_acronym_match(name1, name2):
            name_sim = 1.0
        else:
            name_sim = self._levenshtein_similarity(name1, name2)
        org_sim = self._calculate_org_similarity(node1, node2)
        loc_sim = self._calculate_loc_similarity(node1, node2)
        rel_sim = self._calculate_relationship_similarity(node1, node2)
        prop_sim = self._calculate_properties_overlap(node1, node2)
        emb_sim = self._calculate_embedding_similarity(node1, node2)

        # Weighted calculation
        score = (
            name_sim * self.NAME_WEIGHT +
            org_sim * self.ORG_WEIGHT +
            loc_sim * self.LOCATION_WEIGHT +
            rel_sim * self.RELATIONSHIP_WEIGHT +
            prop_sim * self.PROPERTY_WEIGHT +
            emb_sim * self.EMBEDDING_WEIGHT
        )
        return float(max(0.0, min(100.0, score)))

    async def verify_with_llm(
        self, 
        node1: Dict[str, Any], 
        node2: Dict[str, Any], 
        confidence: float
    ) -> Tuple[bool, str]:
        """
        Verify duplicate candidate with LLM for ambiguous scores.
        """
        logger.info(
            f"Invoking LLM verification for candidates: '{node1.get('display_name')}' "
            f"and '{node2.get('display_name')}' (confidence={confidence:.1f}%)"
        )

        def clean_node_for_llm(node):
            exclude = {"embedding", "_internal_id", "_labels", "_outgoing", "_incoming"}
            props = {k: v for k, v in node.items() if k not in exclude and v is not None}
            outgoing = [f"-[{o['type']}]-> ({o['target_name']} : {o['target_label']})" for o in node.get("_outgoing", [])[:10]]
            incoming = [f"<-[{i['type']}]- ({i['source_name']} : {i['source_label']})" for i in node.get("_incoming", [])[:10]]
            return {
                "label": next((l for l in node["_labels"] if l in ["Entity", "TripletEntity"]), "Entity"),
                "properties": props,
                "incoming_relationships": incoming,
                "outgoing_relationships": outgoing
            }

        node_a_info = clean_node_for_llm(node1)
        node_b_info = clean_node_for_llm(node2)

        system_prompt = (
            "You are a highly precise Entity Resolution agent in a Knowledge Graph pipeline.\n"
            "Your task is to determine whether two entities refer to the same real-world entity.\n"
            "Guidelines:\n"
            "1. For People: name variations (e.g. abbreviations, initials, titles like Dr./PhD, or missing middle names) are highly likely to be the same person unless there is a clear conflict (e.g. different employers, emails, or locations).\n"
            "2. For Companies/Organizations: legal suffixes (Inc., Ltd., LLC, Corp.) and minor branding variations (e.g., 'Apex Digital Solutions' vs 'Apex Solutions Inc.') are highly likely to be the same organization, especially if they share common relationships (like 'Acme Corporation Ltd.'). Geographically overlapping or related terms (e.g. 'San Jose' and 'Silicon Valley') support the merge.\n"
            "3. For Locations: street suffixes or abbreviations (Pkwy vs Parkway) and building designations are highly likely to be the same location.\n"
            "If they represent the same entity, return 'same_entity': true, high confidence, and a cleaned canonical name.\n"
            "You must return a valid JSON object only."
        )

        prompt = f"""Evaluate whether the following two nodes represent the exact same entity in the real world.
        
Node A:
Labels: {node_a_info['label']}
Properties: {json.dumps(node_a_info['properties'], indent=2)}
Incoming Relationships: {json.dumps(node_a_info['incoming_relationships'], indent=2)}
Outgoing Relationships: {json.dumps(node_a_info['outgoing_relationships'], indent=2)}

Node B:
Labels: {node_b_info['label']}
Properties: {json.dumps(node_b_info['properties'], indent=2)}
Incoming Relationships: {json.dumps(node_b_info['incoming_relationships'], indent=2)}
Outgoing Relationships: {json.dumps(node_b_info['outgoing_relationships'], indent=2)}

Return ONLY a pure JSON response in the following format (do not include any comments or other text):
{{
  "same_entity": true,
  "confidence": 95,
  "canonical_name": "John Smith",
  "reason": "explanation of decision"
}}
"""
        try:
            response = await self.llm_client.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.1,
                max_tokens=1024
            )

            clean_res = response.strip()
            if "```json" in clean_res:
                clean_res = clean_res.split("```json", 1)[1]
            if "```" in clean_res:
                clean_res = clean_res.split("```", 1)[0]
            clean_res = clean_res.strip()

            data = json.loads(clean_res)
            same_entity = data.get("same_entity", False)
            llm_confidence = data.get("confidence", 0)
            canonical_name = data.get("canonical_name", "")
            reason = data.get("reason", "")

            logger.info(
                f"LLM verification result: same_entity={same_entity}, "
                f"confidence={llm_confidence}, canonical_name='{canonical_name}', "
                f"reason='{reason}'"
            )

            if same_entity and llm_confidence >= 70:
                return True, canonical_name
            return False, ""

        except Exception as e:
            logger.error(f"LLM verification failed: {e}. Raw response: {response!r}", exc_info=True)
            return False, ""

    async def merge_duplicate_nodes(
        self,
        canonical_node: Dict[str, Any],
        duplicate_node: Dict[str, Any],
        canonical_name_override: Optional[str] = None
    ) -> bool:
        """
        Merge duplicate node into canonical node: redirect relationships,
        combine properties, add aliases, and delete duplicate.
        """
        canonical_id = canonical_node["_internal_id"]
        duplicate_id = duplicate_node["_internal_id"]
        canonical_uuid = canonical_node.get("id")
        duplicate_uuid = duplicate_node.get("id")

        label = next((l for l in canonical_node["_labels"] if l in ["Entity", "TripletEntity"]), "Entity")

        logger.info(f"Merging duplicate node {duplicate_uuid} into canonical node {canonical_uuid} (Label: {label})")

        # 1. Merge Properties
        merged_props = dict(canonical_node)
        exclude = {"_internal_id", "_labels", "_outgoing", "_incoming"}
        for k in exclude:
            merged_props.pop(k, None)

        for k, v in duplicate_node.items():
            if k in exclude:
                continue
            if merged_props.get(k) is None and v is not None:
                merged_props[k] = v

        if canonical_name_override:
            disp, norm = self._normalize_single_name(canonical_name_override)
            merged_props["display_name"] = disp
            merged_props["normalized_name"] = norm

        # Update Aliases
        aliases = merged_props.get("aliases", [])
        if isinstance(aliases, str):
            try:
                aliases = json.loads(aliases)
            except Exception:
                aliases = [aliases] if aliases else []
        elif not isinstance(aliases, list):
            aliases = []

        dup_names = [
            duplicate_node.get("display_name"),
            duplicate_node.get("name"),
            duplicate_node.get("text")
        ]
        dup_aliases = duplicate_node.get("aliases", [])
        if isinstance(dup_aliases, str):
            try:
                dup_aliases = json.loads(dup_aliases)
            except Exception:
                dup_aliases = [dup_aliases] if dup_aliases else []
        elif isinstance(dup_aliases, list):
            dup_names.extend(dup_aliases)

        for name in dup_names:
            if name:
                disp, _ = self._normalize_single_name(name)
                if disp and disp != merged_props.get("display_name") and disp not in aliases:
                    aliases.append(disp)

        merged_props["aliases"] = aliases

        # Stringify structured properties for Neo4j compatibility
        for k, v in merged_props.items():
            if isinstance(v, uuid.UUID):
                merged_props[k] = str(v)
            elif isinstance(v, (list, dict)):
                if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                    merged_props[k] = json.dumps(v)
                elif isinstance(v, dict):
                    merged_props[k] = json.dumps(v)

        driver = await get_neo4j_driver()
        async with driver.session() as session:
            tx = await session.begin_transaction()
            async with tx as tx:
                try:
                    # Redirect Incoming Relationships
                    inc_query = """
                    MATCH (src)-[r]->(dup)
                    WHERE elementId(dup) = $duplicate_id AND dup.tenant_id = $tenant_id AND src.tenant_id = $tenant_id
                    RETURN elementId(src) AS src_id, type(r) AS rel_type, properties(r) AS rel_props
                    """
                    inc_res = await tx.run(inc_query, {"duplicate_id": duplicate_id, "tenant_id": self.tenant_id})

                    inc_records = await inc_res.data()
                    for rec in inc_records:
                        src_id = rec["src_id"]
                        rel_type = rec["rel_type"]
                        rel_props = _safe_dict_prop(rec.get("rel_props"))

                        # Check existing relationship to canonical node
                        dup_check_query = """
                        MATCH (src)-[r:%s]->(can)
                        WHERE elementId(src) = $src_id AND elementId(can) = $canonical_id AND src.tenant_id = $tenant_id AND can.tenant_id = $tenant_id
                        RETURN properties(r) AS r_props
                        """ % rel_type

                        check_res = await tx.run(dup_check_query, {
                            "src_id": src_id,
                            "canonical_id": canonical_id,
                            "tenant_id": self.tenant_id
                        })

                        existing_rels = await check_res.data()

                        if existing_rels:
                            # Merge properties of duplicate incoming relations
                            existing_r_props = _safe_dict_prop(existing_rels[0].get("r_props"))
                            merged_rel_props = dict(existing_r_props)
                            for k, v in rel_props.items():
                                if merged_rel_props.get(k) is None:
                                    merged_rel_props[k] = v
                            
                            update_rel_query = """
                            MATCH (src)-[r:%s]->(can)
                            WHERE elementId(src) = $src_id AND elementId(can) = $canonical_id AND src.tenant_id = $tenant_id AND can.tenant_id = $tenant_id
                            SET r = $properties
                            """ % rel_type
                            await tx.run(update_rel_query, {
                                "src_id": src_id,
                                "canonical_id": canonical_id,
                                "tenant_id": self.tenant_id,
                                "properties": merged_rel_props
                            })
                        else:
                            # Create redirected relationship
                            create_rel_query = """
                            MATCH (src), (can)
                            WHERE elementId(src) = $src_id AND elementId(can) = $canonical_id AND src.tenant_id = $tenant_id AND can.tenant_id = $tenant_id
                            CREATE (src)-[r:%s]->(can)
                            SET r = $properties
                            """ % rel_type
                            await tx.run(create_rel_query, {
                                "src_id": src_id,
                                "canonical_id": canonical_id,
                                "tenant_id": self.tenant_id,
                                "properties": rel_props
                            })

                    # Redirect Outgoing Relationships
                    out_query = """
                    MATCH (dup)-[r]->(tgt)
                    WHERE elementId(dup) = $duplicate_id AND dup.tenant_id = $tenant_id AND tgt.tenant_id = $tenant_id
                    RETURN elementId(tgt) AS tgt_id, type(r) AS rel_type, properties(r) AS rel_props
                    """
                    out_res = await tx.run(out_query, {"duplicate_id": duplicate_id, "tenant_id": self.tenant_id})

                    out_records = await out_res.data()
                    for rec in out_records:
                        tgt_id = rec["tgt_id"]
                        rel_type = rec["rel_type"]
                        rel_props = _safe_dict_prop(rec.get("rel_props"))

                        # Check existing relationship to canonical node
                        dup_check_query = """
                        MATCH (can)-[r:%s]->(tgt)
                        WHERE elementId(can) = $canonical_id AND elementId(tgt) = $tgt_id AND can.tenant_id = $tenant_id AND tgt.tenant_id = $tenant_id
                        RETURN properties(r) AS r_props
                        """ % rel_type

                        check_res = await tx.run(dup_check_query, {
                            "canonical_id": canonical_id,
                            "tgt_id": tgt_id,
                            "tenant_id": self.tenant_id
                        })

                        existing_rels = await check_res.data()

                        if existing_rels:
                            existing_r_props = _safe_dict_prop(existing_rels[0].get("r_props"))
                            merged_rel_props = dict(existing_r_props)
                            for k, v in rel_props.items():
                                if merged_rel_props.get(k) is None:
                                    merged_rel_props[k] = v
                            
                            update_rel_query = """
                            MATCH (can)-[r:%s]->(tgt)
                            WHERE elementId(can) = $canonical_id AND elementId(tgt) = $tgt_id AND can.tenant_id = $tenant_id AND tgt.tenant_id = $tenant_id
                            SET r = $properties
                            """ % rel_type
                            await tx.run(update_rel_query, {
                                "canonical_id": canonical_id,
                                "tgt_id": tgt_id,
                                "tenant_id": self.tenant_id,
                                "properties": merged_rel_props
                            })
                        else:
                            # Create redirected relationship
                            create_rel_query = """
                            MATCH (can), (tgt)
                            WHERE elementId(can) = $canonical_id AND elementId(tgt) = $tgt_id AND can.tenant_id = $tenant_id AND tgt.tenant_id = $tenant_id
                            CREATE (can)-[r:%s]->(tgt)
                            SET r = $properties
                            """ % rel_type
                            await tx.run(create_rel_query, {
                                "canonical_id": canonical_id,
                                "tgt_id": tgt_id,
                                "tenant_id": self.tenant_id,
                                "properties": rel_props
                            })

                    # Detach and delete the duplicate node
                    delete_query = """
                    MATCH (dup)
                    WHERE elementId(dup) = $duplicate_id AND dup.tenant_id = $tenant_id
                    DETACH DELETE dup
                    """
                    await tx.run(delete_query, {"duplicate_id": duplicate_id, "tenant_id": self.tenant_id})

                    # Update canonical properties and labels (executed after delete to avoid unique constraint violations)
                    all_labels = set(canonical_node.get("_labels", [])) | set(duplicate_node.get("_labels", []))
                    labels_str = "".join([f":{l}" for l in all_labels if l])
                    
                    update_query = f"""
                    MATCH (n)
                    WHERE elementId(n) = $canonical_id AND n.tenant_id = $tenant_id
                    SET n = $properties
                    SET n {labels_str}
                    """
                    await tx.run(update_query, {
                        "canonical_id": canonical_id,
                        "tenant_id": self.tenant_id,
                        "properties": merged_props
                    })

                    await tx.commit()
                    logger.info("Merge transaction completed successfully.")
                    return True

                except Exception as tx_err:
                    logger.error(f"Merge transaction failed: {tx_err}, rolling back", exc_info=True)
                    await tx.rollback()
                    return False

    async def remove_duplicate_relationships(self) -> Dict[str, Any]:
        """
        Scan graph for duplicate relationships (same source, target, type)
        and merge properties into a single relationship.
        """
        logger.info(f"Removing duplicate relationships for tenant {self.tenant_id}...")

        query = """
        MATCH (s {tenant_id: $tenant_id})-[r]->(t {tenant_id: $tenant_id})
        WITH s, t, type(r) AS rel_type, collect({
            element_id: elementId(r),
            properties: properties(r)
        }) AS rels
        WHERE size(rels) > 1
        RETURN s.id AS start_uuid, t.id AS end_uuid, rel_type, rels
        """
        results = await self.neo4j_repo.execute_read(query)

        dedup_count = 0
        driver = await get_neo4j_driver()
        async with driver.session() as session:
            for record in results:
                rels = record["rels"]
                if len(rels) < 2:
                    continue

                survivor = rels[0]
                duplicates = rels[1:]

                # Merge properties
                merged_props = _safe_dict_prop(survivor.get("properties"))
                for dup in duplicates:
                    for k, v in _safe_dict_prop(dup.get("properties")).items():
                        if merged_props.get(k) is None and v is not None:
                            merged_props[k] = v

                survivor_id = survivor.get("element_id")
                if survivor_id is None:
                    continue

                update_query = """
                MATCH ()-[r]->()
                WHERE elementId(r) = $rel_id
                SET r = $properties
                """
                await session.run(update_query, {"rel_id": survivor_id, "properties": merged_props})

                # Delete duplicate relationships
                for dup in duplicates:
                    dup_id = dup.get("element_id")
                    if dup_id is None:
                        continue

                    delete_query = """
                    MATCH ()-[r]->()
                    WHERE elementId(r) = $rel_id
                    DELETE r
                    """
                    await session.run(delete_query, {"rel_id": dup_id})
                    dedup_count += 1

        logger.info(f"Deduplicated {dedup_count} relationships.")
        return {"relationships_deduplicated": dedup_count}

    async def cleanup_graph(self) -> Dict[str, Any]:
        """
        Main entry point for deduplicating the graph.
        """
        logger.info(f"Starting graph cleanup pipeline for tenant {self.tenant_id}...")

        # 1. Normalize all entity names
        norm_result = await self.normalize_entities()
        normalized_count = norm_result["normalized_count"]

        # 2. Find candidates
        candidates = await self.find_duplicate_candidates()

        stats = {
            "normalized_entities": normalized_count,
            "candidates_checked": len(candidates),
            "auto_merges": 0,
            "llm_merges": 0,
            "total_merges": 0,
            "relationships_deduplicated": 0,
            "relationships_pruned": 0
        }

        # 3. Evaluate candidate pairs (pre-classify and verify LLM matches in parallel)
        auto_merges_to_apply = []
        llm_verifications_to_run = []
        
        for n1, n2 in candidates:
            score = self.calculate_similarity(n1, n2)
            if score >= self.auto_merge_threshold:
                auto_merges_to_apply.append((n1, n2, score, "auto", None))
            else:
                name_sim = self._levenshtein_similarity(n1.get("normalized_name", ""), n2.get("normalized_name", ""))
                emb_sim = self._calculate_embedding_similarity(n1, n2)
                if (
                    score >= self.llm_review_threshold 
                    or (emb_sim >= self.embedding_override_threshold and score >= 60.0)
                ):
                    llm_verifications_to_run.append((n1, n2, score))

        # Concurrently verify ambiguous candidate pairs using a Semaphore to prevent rate limiting
        sem = asyncio.Semaphore(15)
        
        async def sem_verify(node1, node2, conf):
            async with sem:
                verified, canonical_name = await self.verify_with_llm(node1, node2, conf)
                return node1, node2, conf, verified, canonical_name

        tasks = [sem_verify(n1, n2, score) for n1, n2, score in llm_verifications_to_run]
        llm_results = await asyncio.gather(*tasks) if tasks else []
        
        # Consolidate merges to apply
        merges_to_apply = []
        for n1, n2, score, m_type, canonical_name in auto_merges_to_apply:
            merges_to_apply.append((n1, n2, score, m_type, canonical_name))
        for n1, n2, score, verified, canonical_name in llm_results:
            if verified:
                merges_to_apply.append((n1, n2, score, "llm", canonical_name))

        # Sort merges by score descending to prioritize high-confidence merges first
        merges_to_apply.sort(key=lambda x: x[2], reverse=True)

        # Sequentially apply the merges to the database safely
        deleted_node_ids = set()
        for n1, n2, score, merge_type, llm_canonical_override in merges_to_apply:
            id1 = n1["_internal_id"]
            id2 = n2["_internal_id"]

            if id1 in deleted_node_ids or id2 in deleted_node_ids:
                continue

            # Choose canonical node
            def get_selection_score(node):
                props_count = len([k for k, v in node.items() if v is not None])
                rels_count = len(node.get("_outgoing", [])) + len(node.get("_incoming", []))
                name_len = len(node.get("display_name", ""))
                return props_count * 2 + rels_count * 3 + name_len

            if get_selection_score(n1) >= get_selection_score(n2):
                canonical, duplicate = n1, n2
            else:
                canonical, duplicate = n2, n1

            success = await self.merge_duplicate_nodes(
                canonical, 
                duplicate, 
                canonical_name_override=llm_canonical_override
            )

            if success:
                deleted_node_ids.add(duplicate["_internal_id"])
                stats["total_merges"] += 1
                if merge_type == "auto":
                    stats["auto_merges"] += 1
                else:
                    stats["llm_merges"] += 1

        # 3.5. Post-Cleanup Scan for exact matches on normalized_name and type
        logger.info("Starting post-cleanup exact match scan...")
        
        # Re-fetch all active nodes to get their latest state
        refreshed_nodes = []
        query_all = """
        MATCH (n)
        WHERE (n:Entity OR n:TripletEntity) AND n.tenant_id = $tenant_id
        
        RETURN n, labels(n) AS labels, elementId(n) as internal_id,
               [(n)-[r]->(target) WHERE target.tenant_id = $tenant_id | {type: type(r), target_id: target.id, target_label: labels(target)[0], target_name: coalesce(target.name, target.display_name, target["title"])}] AS outgoing,
               [(source)-[r_in]->(n) WHERE source.tenant_id = $tenant_id | {type: type(r_in), source_id: source.id, source_label: labels(source)[0], source_name: coalesce(source.name, source.display_name, source["title"])}] AS incoming
        """
        results_all = await self.neo4j_repo.execute_read(query_all)
        for record in results_all:
            node_props = dict(record["n"])
            node_props["_internal_id"] = record["internal_id"]
            node_props["_labels"] = record["labels"]
            
            outgoing = [o for o in record["outgoing"] if o.get("target_id") is not None]
            incoming = [i for i in record["incoming"] if i.get("source_id") is not None]
            node_props["_outgoing"] = outgoing
            node_props["_incoming"] = incoming
            
            if "normalized_name" not in node_props or "display_name" not in node_props:
                raw_name = node_props.get("name") or node_props.get("text") or node_props.get("display_name") or ""
                disp, norm = self._normalize_single_name(raw_name)
                node_props["display_name"] = disp
                node_props["normalized_name"] = norm
                
            refreshed_nodes.append(node_props)
            
        exact_groups = {}
        for node in refreshed_nodes:
            norm_name = node.get("normalized_name", "").strip().lower()
            if not norm_name:
                continue
            
            g_key = norm_name
            if g_key not in exact_groups:
                exact_groups[g_key] = []
            exact_groups[g_key].append(node)
            
        post_deleted_ids = set()
        for g_key, group_nodes in exact_groups.items():
            if len(group_nodes) < 2:
                continue
                
            # Sort by selection score descending
            def get_selection_score(node):
                props_count = len([k for k, v in node.items() if v is not None])
                rels_count = len(node.get("_outgoing", [])) + len(node.get("_incoming", []))
                name_len = len(node.get("display_name", ""))
                return props_count * 2 + rels_count * 3 + name_len
                
            sorted_nodes = sorted(group_nodes, key=get_selection_score, reverse=True)
            canonical = sorted_nodes[0]
            
            for duplicate in sorted_nodes[1:]:
                if canonical["_internal_id"] in post_deleted_ids or duplicate["_internal_id"] in post_deleted_ids:
                    continue
                    
                # Check for unique identifier conflict
                sim_score = self.calculate_similarity(canonical, duplicate)
                if sim_score == 0.0:
                    # Conflicting unique identifier, do not merge!
                    continue
                    
                success = await self.merge_duplicate_nodes(canonical, duplicate)
                if success:
                    post_deleted_ids.add(duplicate["_internal_id"])
                    stats["total_merges"] += 1
                    stats["auto_merges"] += 1
                    # Update canonical node's incoming/outgoing relations to prevent missing references
                    # in case of consecutive merges in the same loop
                    canonical["_outgoing"].extend(duplicate.get("_outgoing", []))
                    canonical["_incoming"].extend(duplicate.get("_incoming", []))
                    canonical["_labels"] = list(set(canonical["_labels"]) | set(duplicate.get("_labels", [])))

        # 4. Remove duplicate relationships
        rel_dedup_result = await self.remove_duplicate_relationships()
        stats["relationships_deduplicated"] = rel_dedup_result["relationships_deduplicated"]

        # 5. Prune redundant transitive relationships
        reduction_res = await self.transitive_reduction()
        stats["relationships_pruned"] = reduction_res["relationships_pruned"]

        logger.info(f"Graph cleanup completed: {stats}")
        return stats

    async def transitive_reduction(self) -> Dict[str, Any]:
        """
        Identify and prune redundant transitive relationships in hierarchical entity graphs.
        For example, if A -> B and B -> C exist, a direct edge A -> C of the same type is redundant.
        """
        logger.info(f"Starting transitive reduction pass for tenant {self.tenant_id}...")
        
        # Query all entity-to-entity relationships for this tenant
        query = """
        MATCH (a)-[r]->(b)
        WHERE a.tenant_id = $tenant_id AND b.tenant_id = $tenant_id
          AND (a:Entity OR a:TripletEntity) AND (b:Entity OR b:TripletEntity)
        RETURN type(r) AS rel_type, elementId(a) AS source_id, elementId(b) AS target_id, elementId(r) AS rel_id
        """
        records = await self.neo4j_repo.execute_read(query)
        
        # Group relationships by their type (e.g. RELATES_TO)
        rel_groups = {}
        for record in records:
            rtype = record["rel_type"]
            if rtype not in rel_groups:
                rel_groups[rtype] = []
            rel_groups[rtype].append({
                "source_id": record["source_id"],
                "target_id": record["target_id"],
                "rel_id": record["rel_id"]
            })
            
        redundant_rel_ids = []
        
        for rtype, edges in rel_groups.items():
            # Build adjacency list
            adj = {}
            for edge in edges:
                u = edge["source_id"]
                v = edge["target_id"]
                rid = edge["rel_id"]
                if u not in adj:
                    adj[u] = []
                adj[u].append((v, rid))
                
            
            edge_count = 0
            for edge in edges:
                edge_count += 1
                if edge_count % 100 == 0:
                    await asyncio.sleep(0) # Yield event loop
                
                u = edge["source_id"]
                v = edge["target_id"]
                rid = edge["rel_id"]
                
                # Temporarily remove this edge from adj[u]
                if u in adj:
                    original_list = adj[u]
                    adj[u] = [item for item in original_list if item[1] != rid]
                
                # Run BFS to check reachability (limited depth)
                visited = {u}
                queue = deque([(u, 0)]) # (node, depth)
                reachable = False
                
                while queue:
                    curr, depth = queue.popleft()
                    if curr == v and curr != u:
                        # Found alternative path!
                        reachable = True
                        break
                        
                    if depth < 3:  # Limit transitive search to 3 hops
                        for neighbor, _ in adj.get(curr, []):
                            if neighbor not in visited:
                                visited.add(neighbor)
                                queue.append((neighbor, depth + 1))
                            
                # Restore edge
                if u in adj:
                    adj[u] = original_list
                    
                if reachable:
                    logger.info(f"Found redundant transitive relationship of type '{rtype}': {u} -> {v} (ID: {rid})")
                    redundant_rel_ids.append(rid)
                    
        # Prune redundant relationships from Neo4j
        pruned_count = 0
        if redundant_rel_ids:
            logger.info(f"Pruning {len(redundant_rel_ids)} redundant relationships...")
            # We can delete them in batches using elementId
            delete_query = """
            UNWIND $rel_ids AS rid
            MATCH ()-[r]->()
            WHERE elementId(r) = rid
            DELETE r
            """
            driver = await get_neo4j_driver()
            async with driver.session() as session:
                await session.run(delete_query, {"rel_ids": redundant_rel_ids})
            pruned_count = len(redundant_rel_ids)
            logger.info(f"Successfully pruned {pruned_count} redundant relationships.")
            
        return {"relationships_pruned": pruned_count}
