"""REST routes for graph visualization data"""

from fastapi import APIRouter, Request, HTTPException
import logging
import uuid
from typing import Dict, Any, List, Optional
from sqlalchemy import select

from ...core.database import AsyncSessionLocal
from ...core.neo4j import get_neo4j_driver
from ...utils.formatters import format_success, format_error
from ..agents.models import Agent
from ..knowledge_bases.models import KnowledgeBase, DocumentChunk
from ..auth.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/graphs", tags=["graphs"])


def get_context(request: Request) -> tuple[str, str]:
    """Extract authenticated tenant_id and user_id from request state."""
    tenant_id = getattr(request.state, "tenant_id", None)
    user_id = getattr(request.state, "user_id", None)
    if not tenant_id or not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return str(tenant_id), str(user_id)


def sanitize_node_properties(raw_props: dict) -> dict:
    """Strip embedding vectors and excessive nested arrays to keep graph visualization lightweight."""
    clean = {}
    for k, v in raw_props.items():
        if k in ("embedding", "embedding_bge") or (isinstance(v, list) and len(v) > 20):
            continue
        clean[k] = v
    return clean


@router.get("/tenant")
async def get_tenant_graph(request: Request, limit: int = 150):
    """
    Get graph data (nodes + edges) for the current tenant.
    Format compatible with ForceGraph2D / D3.js.
    """
    tenant_id, _ = get_context(request)

    query = """
    MATCH (n {tenant_id: $tenant_id})
    WITH n LIMIT $limit
    OPTIONAL MATCH (n)-[r]->(m {tenant_id: $tenant_id})
    RETURN n, r, m
    """

    try:
        driver = await get_neo4j_driver()
        async with driver.session() as session:
            result = await session.run(query, {"tenant_id": tenant_id, "limit": limit})

            nodes = {}
            edges = []

            def extract_node(node):
                if not node:
                    return None
                node_id = node.get("id") or str(node.element_id)
                if node_id not in nodes:
                    label = node.get("name") or node.get("subject")
                    if not label:
                        label = node.get("text", "")[:25] + "..." if node.get("text") else node_id

                    nodes[node_id] = {
                        "id": str(node_id),
                        "label": str(label),
                        "type": list(node.labels)[0] if node.labels else "Unknown",
                        "properties": sanitize_node_properties(dict(node)),
                    }
                return str(node_id)

            async for record in result:
                source_id = extract_node(record["n"])
                target_id = extract_node(record["m"])
                r = record["r"]
                if r and source_id and target_id:
                    edges.append({
                        "id": str(r.element_id),
                        "type": r.type,
                        "source": source_id,
                        "target": target_id,
                        "properties": sanitize_node_properties(dict(r)),
                    })

            return format_success({
                "nodes": list(nodes.values()),
                "edges": edges,
                "count": len(nodes),
            })

    except Exception as e:
        logger.error(f"Failed to fetch tenant graph: {e}", exc_info=True)
        return format_error(f"Failed to fetch graph: {str(e)}")


@router.get("/knowledge-base/{kb_id}")
async def get_kb_graph(request: Request, kb_id: str, limit: int = 250):
    """
    Get graph data for a specific Knowledge Base with PostgreSQL verification and fail-safe fallback.
    """
    tenant_id, user_id = get_context(request)

    # 1. Authorize via PostgreSQL
    try:
        kb_uuid = uuid.UUID(kb_id)
        kb_filter = KnowledgeBase.id == kb_uuid
    except (ValueError, TypeError):
        kb_filter = KnowledgeBase.id == kb_id

    async with AsyncSessionLocal() as db_session:
        stmt = select(KnowledgeBase).where(kb_filter, KnowledgeBase.deleted_at.is_(None))
        res = await db_session.execute(stmt)
        kb = res.scalar_one_or_none()

        if not kb:
            return format_error(f"Knowledge Base not found: {kb_id}", meta={"status_code": 404})

        # Check tenant authorization
        is_admin = getattr(request.state, "is_admin", False)
        if not is_admin and str(kb.tenant_id) != tenant_id:
            return format_error("Forbidden: Access denied to knowledge base", meta={"status_code": 403})

        authoritative_tenant_id = str(kb.tenant_id)
        kb_name = kb.name or "KnowledgeBase"

    driver = await get_neo4j_driver()
    nodes = {}
    edges = []

    def extract_node(node):
        if not node:
            return None
        node_id = str(node.get("id") or node.element_id)
        if node_id not in nodes:
            label = node.get("name") or node.get("subject")
            if not label:
                label = node.get("text", "")[:25] + "..." if node.get("text") else node_id
            nodes[node_id] = {
                "id": node_id,
                "label": str(label),
                "type": list(node.labels)[0] if node.labels else "Unknown",
                "properties": sanitize_node_properties(dict(node)),
            }
        return node_id

    try:
        async with driver.session() as session:
            # Self-heal KB node in Neo4j
            await session.run("""
                MERGE (kb:KnowledgeBase {id: $kb_id})
                ON CREATE SET kb.name = $name, kb.tenant_id = $tenant_id, kb.created_at = timestamp()
                ON MATCH SET kb.name = $name, kb.tenant_id = $tenant_id
            """, {"kb_id": str(kb_id), "name": kb_name, "tenant_id": authoritative_tenant_id})

            query = """
            MATCH (kb:KnowledgeBase {id: $kb_id})
            OPTIONAL MATCH (kb)-[r1:HAS_CHUNK]->(c:Chunk)
            WITH kb, c, r1 LIMIT $limit
            OPTIONAL MATCH (c)-[r2]-(m)
            WHERE NOT m:KnowledgeBase AND NOT m:Agent
            RETURN kb, c, m, r1, r2
            """
            result = await session.run(query, {"kb_id": str(kb_id), "limit": limit})
            async for record in result:
                extract_node(record["kb"])
                extract_node(record["c"])
                extract_node(record["m"])

                for r_key in ["r1", "r2"]:
                    r = record[r_key]
                    if r:
                        s_id = str(r.start_node.get("id") or r.start_node.element_id)
                        t_id = str(r.end_node.get("id") or r.end_node.element_id)
                        edge_id = str(r.element_id)
                        if not any(e["id"] == edge_id for e in edges):
                            edges.append({
                                "id": edge_id,
                                "type": r.type,
                                "source": s_id,
                                "target": t_id,
                                "properties": sanitize_node_properties(dict(r)),
                            })

        # Fallback to PostgreSQL document_chunks if Neo4j has no chunks
        has_chunks = any(n.get("type") == "Chunk" for n in nodes.values())
        if not has_chunks:
            async with AsyncSessionLocal() as db_session:
                c_stmt = (
                    select(DocumentChunk)
                    .where(DocumentChunk.kb_id == kb.id)
                    .order_by(DocumentChunk.chunk_index)
                    .limit(limit)
                )
                c_res = await db_session.execute(c_stmt)
                for ch in c_res.scalars().all():
                    cid = str(ch.id)
                    kbid = str(kb.id)
                    nodes[cid] = {
                        "id": cid,
                        "label": f"Chunk {ch.chunk_index}",
                        "type": "Chunk",
                        "properties": {
                            "chunk_index": ch.chunk_index,
                            "text": ch.text[:200] if ch.text else "",
                            "kb_id": kbid,
                            "section": ch.section or "",
                        },
                    }
                    edges.append({
                        "id": f"{kbid}-{cid}-HAS_CHUNK",
                        "type": "HAS_CHUNK",
                        "source": kbid,
                        "target": cid,
                        "properties": {},
                    })

        return format_success({
            "nodes": list(nodes.values()),
            "edges": edges,
            "kb_id": str(kb_id),
            "count": len(nodes),
        })

    except Exception as e:
        logger.error(f"Failed to fetch KB graph: {e}", exc_info=True)
        return format_error(f"Failed to fetch graph: {str(e)}")


@router.get("/agent/{agent_id}")
async def get_agent_graph(request: Request, agent_id: str, limit: int = 300):
    """
    Get full knowledge graph for a specific Agent.
    Hierarchy: Agent -> KnowledgeBase -> Chunk -> Entity/Other Chunks

    Production Architecture Guarantees:
    1. Authoritative security & ownership verification via PostgreSQL.
    2. Self-healing Neo4j Agent and KnowledgeBase nodes and OWNS_KB links.
    3. Multi-relationship traversal (SIMILAR, NEXT, MENTIONS, HAS_EVENT_HUB, TRIPLET, etc.).
    4. Seamless PostgreSQL fallback if Neo4j is empty or recovering.
    """
    tenant_id, user_id = get_context(request)

    # 1. Authorize via PostgreSQL (Source of Truth)
    try:
        agent_uuid = uuid.UUID(agent_id)
        agent_filter = Agent.id == agent_uuid
    except (ValueError, TypeError):
        agent_filter = Agent.id == agent_id

    async with AsyncSessionLocal() as db_session:
        stmt = select(Agent).where(agent_filter, Agent.deleted_at.is_(None))
        res = await db_session.execute(stmt)
        agent = res.scalar_one_or_none()

        if not agent:
            return format_error(f"Agent not found: {agent_id}", meta={"status_code": 404})

        # Check tenant / user authorization
        is_admin = getattr(request.state, "is_admin", False)
        if not is_admin and str(agent.tenant_id) != tenant_id and str(agent.user_id) != user_id:
            # Check user role if caller is admin
            caller_res = await db_session.execute(select(User).where(User.id == uuid.UUID(user_id)))
            caller = caller_res.scalar_one_or_none()
            if not (caller and (getattr(caller, "is_admin", False) or getattr(caller, "role", "") == "admin")):
                return format_error("Forbidden: Access denied to agent", meta={"status_code": 403})

        authoritative_tenant_id = str(agent.tenant_id)
        agent_name = agent.name or "Agent"

        # Fetch all active KnowledgeBases linked to this agent
        kb_stmt = select(KnowledgeBase).where(
            KnowledgeBase.agent_id == agent.id,
            KnowledgeBase.deleted_at.is_(None)
        )
        kb_res = await db_session.execute(kb_stmt)
        pg_kbs = kb_res.scalars().all()
        kbs_payload = [{"id": str(k.id), "name": k.name or "KnowledgeBase"} for k in pg_kbs]

    driver = await get_neo4j_driver()
    nodes = {}
    edges = []

    def extract_node(node):
        if not node:
            return None
        node_id = str(node.get("id") or node.element_id)
        if node_id not in nodes:
            label = node.get("name") or node.get("subject")
            if not label:
                label = node.get("text", "")[:25] + "..." if node.get("text") else node_id

            node_type = list(node.labels)[0] if node.labels else "Entity"
            nodes[node_id] = {
                "id": node_id,
                "label": str(label),
                "type": node_type,
                "properties": sanitize_node_properties(dict(node)),
            }
        return node_id

    try:
        async with driver.session() as session:
            # Self-heal Agent node in Neo4j
            await session.run("""
                MERGE (a:Agent {id: $agent_id})
                ON CREATE SET a.name = $agent_name, a.tenant_id = $tenant_id, a.created_at = timestamp()
                ON MATCH SET a.name = $agent_name, a.tenant_id = $tenant_id
            """, {"agent_id": str(agent_id), "agent_name": agent_name, "tenant_id": authoritative_tenant_id})

            # Self-heal KnowledgeBase nodes and OWNS_KB links
            if kbs_payload:
                await session.run("""
                    MATCH (a:Agent {id: $agent_id})
                    UNWIND $kbs AS item
                    MERGE (kb:KnowledgeBase {id: item.id})
                    ON CREATE SET kb.name = item.name, kb.tenant_id = $tenant_id, kb.agent_id = $agent_id, kb.created_at = timestamp()
                    ON MATCH SET kb.name = item.name, kb.tenant_id = $tenant_id, kb.agent_id = $agent_id
                    MERGE (a)-[:OWNS_KB]->(kb)
                """, {"agent_id": str(agent_id), "kbs": kbs_payload, "tenant_id": authoritative_tenant_id})

            # Traverse full agent graph (Agent -> KB -> Chunk -> Entities)
            query = """
            MATCH (a:Agent {id: $agent_id})
            OPTIONAL MATCH (a)-[r1:OWNS_KB]->(kb:KnowledgeBase)
            OPTIONAL MATCH (kb)-[r2:HAS_CHUNK]->(c:Chunk)
            WITH a, kb, c, r1, r2 LIMIT $limit
            OPTIONAL MATCH (c)-[r3]-(m)
            WHERE NOT m:KnowledgeBase AND NOT m:Agent
            RETURN a, kb, c, m, r1, r2, r3
            """
            result = await session.run(query, {"agent_id": str(agent_id), "limit": limit})
            async for record in result:
                extract_node(record["a"])
                extract_node(record["kb"])
                extract_node(record["c"])
                extract_node(record["m"])

                for r_key in ["r1", "r2", "r3"]:
                    r = record[r_key]
                    if r:
                        s_id = str(r.start_node.get("id") or r.start_node.element_id)
                        t_id = str(r.end_node.get("id") or r.end_node.element_id)
                        edge_id = str(r.element_id)
                        if not any(e["id"] == edge_id for e in edges):
                            edges.append({
                                "id": edge_id,
                                "type": r.type,
                                "source": s_id,
                                "target": t_id,
                                "properties": sanitize_node_properties(dict(r)),
                            })

        # Fallback to PostgreSQL document_chunks if Neo4j has no chunks for this agent's KBs
        has_chunks = any(n.get("type") == "Chunk" for n in nodes.values())
        if not has_chunks and pg_kbs:
            logger.info(f"Agent {agent_id} has PostgreSQL KBs but 0 Neo4j chunks; activating PostgreSQL fail-safe fallback.")
            async with AsyncSessionLocal() as db_session:
                kb_ids = [kb.id for kb in pg_kbs]
                c_stmt = (
                    select(DocumentChunk)
                    .where(DocumentChunk.kb_id.in_(kb_ids))
                    .order_by(DocumentChunk.chunk_index)
                    .limit(limit)
                )
                c_res = await db_session.execute(c_stmt)
                for ch in c_res.scalars().all():
                    cid = str(ch.id)
                    kbid = str(ch.kb_id)
                    nodes[cid] = {
                        "id": cid,
                        "label": f"Chunk {ch.chunk_index}",
                        "type": "Chunk",
                        "properties": {
                            "chunk_index": ch.chunk_index,
                            "text": ch.text[:200] if ch.text else "",
                            "kb_id": kbid,
                            "section": ch.section or "",
                        },
                    }
                    edges.append({
                        "id": f"{kbid}-{cid}-HAS_CHUNK",
                        "type": "HAS_CHUNK",
                        "source": kbid,
                        "target": cid,
                        "properties": {},
                    })

        return format_success({
            "nodes": list(nodes.values()),
            "edges": edges,
            "agent_id": str(agent_id),
            "count": len(nodes),
        })

    except Exception as e:
        logger.error(f"Failed to fetch Agent graph: {e}", exc_info=True)
        return format_error(f"Failed to fetch graph: {str(e)}")
