"""REST routes for graph visualization data"""

from fastapi import APIRouter, Request, HTTPException
import logging
import uuid

from ...core.neo4j import get_neo4j_driver
from ...utils.formatters import format_success, format_error

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/graphs", tags=["graphs"])

def get_tenant_id(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return str(tenant_id)

@router.get("/tenant")
async def get_tenant_graph(request: Request, limit: int = 100):
    """
    Get graph data (nodes + edges) for the current tenant.
    Format compatible with neo4j-viz / D3.js.
    """
    tenant_id = get_tenant_id(request)
    
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
            
            async for record in result:
                # Node extraction helper
                def extract_node(node):
                    if not node: return None
                    node_id = node.get("id") or str(node.element_id)
                    if node_id not in nodes:
                        label = node.get("name") or node.get("subject")
                        if not label:
                            label = node.get("text", "")[:20] + "..." if node.get("text") else node.get("id")
                            
                        nodes[node_id] = {
                            "id": node_id,
                            "label": label,
                            "type": list(node.labels)[0] if node.labels else "Unknown",
                            "properties": dict(node)
                        }
                    return node_id

                # Process Node N
                source_id = extract_node(record["n"])
                
                # Process Node M
                target_id = extract_node(record["m"])
                
                # Process Relationship R
                r = record["r"]
                if r and source_id and target_id:
                    edges.append({
                        "id": str(r.element_id),
                        "type": r.type,
                        "source": source_id,
                        "target": target_id,
                        "properties": dict(r)
                    })
            
            return format_success({
                "nodes": list(nodes.values()),
                "edges": edges,
                "count": len(nodes)
            })
            
    except Exception as e:
        logger.error(f"Failed to fetch tenant graph: {e}")
        return format_error(f"Failed to fetch graph: {str(e)}")

@router.get("/knowledge-base/{kb_id}")
async def get_kb_graph(request: Request, kb_id: str, limit: int = 200):
    """
    Get graph data for a specific Knowledge Base.
    """
    tenant_id = get_tenant_id(request)
    
    query = """
    MATCH (kb:KnowledgeBase {id: $kb_id, tenant_id: $tenant_id})
    MATCH (kb)-[:HAS_CHUNK]->(c:Chunk)
    WITH c LIMIT $limit
    OPTIONAL MATCH (c)-[r:MENTIONS|NEXT|RELATED]-(m {tenant_id: $tenant_id})
    RETURN c, r, m
    """
    
    try:
        driver = await get_neo4j_driver()
        async with driver.session() as session:
            result = await session.run(query, {
                "tenant_id": tenant_id, 
                "kb_id": kb_id,
                "limit": limit
            })
            
            nodes = {}
            edges = []
            
            async for record in result:
                c = record["c"]
                if c and str(c.id) not in nodes:
                    nodes[str(c.id)] = {"id": str(c.id), "labels": list(c.labels), "properties": dict(c)}
                
                m = record["m"]
                if m and str(m.id) not in nodes:
                    nodes[str(m.id)] = {"id": str(m.id), "labels": list(m.labels), "properties": dict(m)}
                
                r = record["r"]
                if r:
                    edges.append({
                        "id": str(r.id),
                        "type": r.type,
                        "source": str(r.start_node.id),
                        "target": str(r.end_node.id),
                        "properties": dict(r)
                    })
            
            return format_success({
                "nodes": list(nodes.values()),
                "edges": edges
            })
    except Exception as e:
        logger.error(f"Failed to fetch KB graph: {e}")
        return format_error(f"Failed to fetch graph: {str(e)}")


@router.get("/agent/{agent_id}")
async def get_agent_graph(request: Request, agent_id: str, limit: int = 300):
    """
    Get full knowledge graph for a specific Agent.
    Hierarchy: Agent -> KnowledgeBase -> Chunk -> Entity/Other Chunks
    """
    tenant_id = get_tenant_id(request)
    
    query = """
    MATCH (a:Agent {id: $agent_id, tenant_id: $tenant_id})
    OPTIONAL MATCH (a)-[r1:OWNS_KB]->(kb:KnowledgeBase)
    OPTIONAL MATCH (kb)-[r2:HAS_CHUNK]->(c:Chunk)
    WITH a, kb, c, r1, r2 LIMIT $limit
    OPTIONAL MATCH (c)-[r3:MENTIONS|NEXT|RELATED|EXTRACTED_FROM|SENT|BELONGS_TO]-(m {tenant_id: $tenant_id})
    RETURN a, kb, c, m, r1, r2, r3
    """
    
    try:
        driver = await get_neo4j_driver()
        async with driver.session() as session:
            result = await session.run(query, {
                "tenant_id": tenant_id, 
                "agent_id": agent_id,
                "limit": limit
            })
            
            nodes = {}
            edges = []
            
            def extract_node(node):
                if not node: return None
                node_id = node.get("id") or str(node.element_id)
                if node_id not in nodes:
                    label = node.get("name") or node.get("subject")
                    if not label:
                        label = node.get("text", "")[:20] + "..." if node.get("text") else node.get("id")
                    
                    nodes[node_id] = {
                        "id": node_id,
                        "label": label,
                        "type": list(node.labels)[0] if node.labels else "Unknown",
                        "properties": dict(node)
                    }
                return node_id

            async for record in result:
                extract_node(record["a"])
                extract_node(record["kb"])
                extract_node(record["c"])
                extract_node(record["m"])
                
                # Edges
                for r_key in ["r1", "r2", "r3"]:
                    r = record[r_key]
                    if r:
                        s_id = r.start_node.get("id") or str(r.start_node.element_id)
                        t_id = r.end_node.get("id") or str(r.end_node.element_id)
                        edge_id = str(r.element_id)
                        if not any(e["id"] == edge_id for e in edges):
                            edges.append({
                                "id": edge_id,
                                "type": r.type,
                                "source": s_id,
                                "target": t_id,
                                "properties": dict(r)
                            })
            
            return format_success({
                "nodes": list(nodes.values()),
                "edges": edges,
                "agent_id": agent_id
            })
    except Exception as e:
        logger.error(f"Failed to fetch Agent graph: {e}")
        return format_error(f"Failed to fetch graph: {str(e)}")
