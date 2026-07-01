"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Empty, Input, Spin, Badge, Space, Typography } from "antd";
import { ReloadOutlined, ZoomInOutlined, InfoCircleOutlined } from "@ant-design/icons";
import dynamic from "next/dynamic";
import AgentList from "../../components/ui/AgentList";
import type { Agent } from "../../components/ui/type";
import useAxios from "../../hooks/useAxios";
import { useStore } from "../../hooks/useStore";
import { useTheme } from "../../components/provider/ThemeProvider";

const { Title, Text } = Typography;
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

type NodeType = "Agent" | "KnowledgeBase" | "Chunk" | "Entity";

type RawNode = {
  id: string;
  type?: string;
  label?: string;
  properties?: Record<string, unknown>;
};

type RawEdge = {
  source: string;
  target: string;
  from?: string;
  to?: string;
  type?: string;
  properties?: Record<string, unknown>;
};

type GraphPayload = {
  nodes?: RawNode[];
  edges?: RawEdge[];
};

type GraphResponse = {
  data?: GraphPayload;
  nodes?: RawNode[];
  edges?: RawEdge[];
};

type AgentListResponse = {
  data?: {
    agents?: Agent[];
  };
};

type GraphNode = {
  id: string;
  type: NodeType;
  label: string;
  val: number;
  color: string;
  properties: Record<string, unknown>;
  x?: number;
  y?: number;
  fx?: number;
  fy?: number;
};

type GraphLink = {
  source: string | GraphNode;
  target: string | GraphNode;
  label: string;
  type: string;
};

const NODE_COLORS: Record<NodeType, string> = {
  Agent: "#6366f1", 
  KnowledgeBase: "#06b6d4", 
  Chunk: "#8b5cf6", 
  Entity: "#f59e0b", 
};

const ENTITY_SUB_COLORS: Record<string, string> = {
  PERSON: "#ec4899",
  ORGANIZATION: "#f97316",
  CONCEPT: "#a855f7",
  LOCATION: "#22c55e",
};

function getEntityColor(node: RawNode): string {
  const subType = String(node.properties?.type ?? "");
  return ENTITY_SUB_COLORS[subType] || NODE_COLORS.Entity;
}

const NODE_VALUES: Record<NodeType, number> = {
  Agent: 12,
  KnowledgeBase: 8,
  Chunk: 5,
  Entity: 3,
};

const NODE_TYPES = Object.keys(NODE_COLORS) as NodeType[];

function normalizeType(type?: string): NodeType {
  if (type === "Agent" || type === "KnowledgeBase" || type === "Chunk" || type === "Entity") {
    return type;
  }
  return "Entity";
}

function getNodeLabel(node: RawNode) {
  const properties = node.properties ?? {};
  return String(properties.name ?? properties.title ?? properties.text ?? node.label ?? node.id);
}

function getGraphPayload(response?: GraphResponse): GraphPayload {
  if (response?.data?.nodes || response?.data?.edges) return response.data;
  return { nodes: response?.nodes, edges: response?.edges };
}

function toGraphData(response?: GraphResponse) {
  const payload = getGraphPayload(response);
  const apiNodes = payload.nodes ?? [];
  const apiEdges = payload.edges ?? [];
  const nodeIds = new Set(apiNodes.map((node) => node.id));

  return {
    nodes: apiNodes.map((node): GraphNode => {
      const type = normalizeType(node.type);
      const color = type === "Entity" ? getEntityColor(node) : NODE_COLORS[type];
      const rawProps = node.properties ?? {};
      const filteredProps: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(rawProps)) {
        if (k === "embedding" || (Array.isArray(v) && v.length > 10)) continue;
        filteredProps[k] = v;
      }
      return {
        id: String(node.id),
        type,
        label: getNodeLabel(node),
        val: NODE_VALUES[type],
        color,
        properties: filteredProps,
      };
    }),
    links: (() => {
      const linksMap = new Map<string, GraphLink>();

      apiEdges.forEach((edge) => {
        const src = String(edge.source ?? edge.from ?? "");
        const tgt = String(edge.target ?? edge.to ?? "");
        if (nodeIds.has(src) && nodeIds.has(tgt)) {
          const type = String(edge.type ?? "RELATED_TO");
          linksMap.set(`${src}-${tgt}-${type}`, { source: src, target: tgt, label: type, type });
        }
      });

      const agents = apiNodes.filter((n) => normalizeType(n.type) === "Agent");
      const kbs = apiNodes.filter((n) => normalizeType(n.type) === "KnowledgeBase");
      const chunks = apiNodes.filter((n) => normalizeType(n.type) === "Chunk");

      if (agents.length > 0 && kbs.length > 0) {
        const primaryAgent = agents[0];
        kbs.forEach((kb) => {
          const key = `${primaryAgent.id}-${kb.id}-OWNS_KB`;
          if (!linksMap.has(key)) {
            linksMap.set(key, { source: primaryAgent.id, target: kb.id, label: "OWNS_KB", type: "OWNS_KB" });
          }
        });
      }

      if (kbs.length > 0 && chunks.length > 0) {
        chunks.forEach((chunk) => {
          const props = chunk.properties || {};
          const kbId = props.knowledge_base_id ?? props.kb_id ?? props.document_id;
          let targetKb = kbs.find((k) => k.id === kbId || k.properties?.document_id === kbId || k.properties?.id === kbId);
          if (!targetKb) targetKb = kbs[0];

          const key = `${targetKb.id}-${chunk.id}-HAS_CHUNK`;
          if (!linksMap.has(key)) {
            linksMap.set(key, { source: targetKb.id, target: chunk.id, label: "HAS_CHUNK", type: "HAS_CHUNK" });
          }
        });
      }

      return Array.from(linksMap.values());
    })(),
  };
}

function truncate(value: string, max = 72) {
  return value.length > max ? `${value.slice(0, max - 1)}...` : value;
}

function getLinkedNodeId(link: GraphLink, selectedId: string) {
  const sourceId = getEndpointId(link.source);
  const targetId = getEndpointId(link.target);
  if (sourceId !== selectedId) return sourceId;
  if (targetId !== selectedId) return targetId;
  return "";
}

function getEndpointId(endpoint: string | GraphNode) {
  return typeof endpoint === "string" ? endpoint : endpoint.id;
}

export default function GraphViewPage() {
  const { isDark } = useTheme();
  const requestedAgentsRef = useRef(false);
  const loadedGraphForRef = useRef("");
  const graphRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [search, setSearch] = useState("");
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [windowWidth, setWindowWidth] = useState(1200);

  const agentList = useStore((state) => state.agentList);
  const setAgentList = useStore((state) => state.setAgentList);
  const setBotsCache = useStore((state) => state.setBotsCache);

  const [getAgents] = useAxios<AgentListResponse>({ endpoint: "GETAGENTLIST", hideErrorMsg: true });
  const [getGraph, graphResponse, graphLoading] = useAxios<GraphResponse>({
    endpoint: "GRAPHVIEW",
    hideErrorMsg: false,
  });

  function mapAgentsToList(agents: Agent[]) {
    return agents.map((agent) => ({
      id: agent.id,
      name: agent.name,
      status: agent.is_active ? "active" : "draft",
    }));
  }

  // Window resize sync for safe client UI changes
  useEffect(() => {
    if (typeof window === "undefined") return;
    setWindowWidth(window.innerWidth);
    const handleWinResize = () => setWindowWidth(window.innerWidth);
    window.addEventListener("resize", handleWinResize);
    return () => window.removeEventListener("resize", handleWinResize);
  }, []);

  // Element resize logic with clean const bindings
  useEffect(() => {
    if (!containerRef.current) return;
    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width } = entry.contentRect;
        setDimensions({
          width: width || 800,
          height: window.innerWidth < 1024 ? 480 : 640
        });
      }
    });
    resizeObserver.observe(containerRef.current);
    return () => resizeObserver.disconnect();
  }, []);

  useEffect(() => {
    getAgents(undefined, (payload) => {
      const agents = payload?.data?.agents ?? [];
      setBotsCache(agents);
      setAgentList(mapAgentsToList(agents));
    });
     // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeAgentId = selectedAgentId || agentList[0]?.id || "";
  const activeAgentName = agentList.find((agent) => agent.id === activeAgentId)?.name ?? "Selected Agent";

  const graphData = useMemo(() => toGraphData(graphResponse), [graphResponse]);

  const nodeById = useMemo(() => {
    return new Map(graphData.nodes.map((node) => [node.id, node]));
  }, [graphData.nodes]);

  const filteredNodes = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return graphData.nodes;
    return graphData.nodes.filter((node) => {
      const properties = Object.values(node.properties).join(" ").toLowerCase();
      return `${node.label} ${node.type} ${properties}`.toLowerCase().includes(term);
    });
  }, [graphData.nodes, search]);

  const visibleNodeIds = useMemo(() => new Set(filteredNodes.map((node) => node.id)), [filteredNodes]);

  const visibleGraphData = useMemo(() => {
    return {
      nodes: filteredNodes,
      links: graphData.links.filter((link) => visibleNodeIds.has(getEndpointId(link.source)) && visibleNodeIds.has(getEndpointId(link.target))),
    };
  }, [filteredNodes, graphData.links, visibleNodeIds]);

  const selectedLinks = useMemo(() => {
    if (!selectedNode) return [];
    return graphData.links.filter((link) => getEndpointId(link.source) === selectedNode.id || getEndpointId(link.target) === selectedNode.id);
  }, [graphData.links, selectedNode]);

  const loadAgents = useCallback(() => {
    if (requestedAgentsRef.current || agentList.length > 0) return;
    requestedAgentsRef.current = true;
    getAgents(undefined, (payload) => {
      const agents = payload?.data?.agents ?? [];
      setBotsCache(agents);
      setAgentList(mapAgentsToList(agents));
    });
  }, [agentList.length, getAgents, setAgentList, setBotsCache]);

  const loadGraph = useCallback(
    (agentId: string, force = false) => {
      if (!agentId) return;
      if (!force && loadedGraphForRef.current === agentId) return;
      loadedGraphForRef.current = agentId;
      setSelectedNode(null);
      getGraph({ path: `/${agentId}` });
    },
    [getGraph],
  );

  useEffect(() => {
    loadAgents();
  }, [loadAgents]);

  useEffect(() => {
    loadGraph(activeAgentId);
  }, [activeAgentId, loadGraph]);

  useEffect(() => {
    if (!graphData.nodes.length) return;
    
    if (graphRef.current) {
      graphRef.current.d3Force("charge")?.strength(-600)?.distanceMax(1000);
      graphRef.current.d3Force("link")?.distance(140);
    }
    
    const timer = setTimeout(() => graphRef.current?.zoomToFit(450, 60), 120);
    return () => clearTimeout(timer);
  }, [graphData.nodes.length, dimensions.width]);

  const handleRefresh = () => {
    loadedGraphForRef.current = "";
    loadGraph(activeAgentId, true);
    graphRef.current?.d3ReheatSimulation();
  };

  const handleFit = () => {
    graphRef.current?.zoomToFit(450, 70);
  };

  const isMobile = windowWidth < 768;
  const isTablet = windowWidth < 1024;

  return (
    <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 24, padding:isMobile ? "20px" : "40px" }}>
      {/* Top Bar Layout Layer */}
      <div style={{ 
        display: "flex", 
        flexDirection: isMobile ? "column" : "row",
        alignItems: isMobile ? "flex-start" : "center", 
        justifyContent: "space-between", 
        gap: 20 
      }}>
        <div>
          <Title level={2} style={{ margin: 0, fontWeight: 700, letterSpacing: "-0.02em" }}>
            Graph View
          </Title>
          <Text type="secondary" style={{ fontSize: 15 }}>
            {activeAgentId ? activeAgentName : "Select an agent to render its knowledge graph"}
          </Text>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12, width: isMobile ? "100%" : "auto" ,flexWrap:"wrap"}}>
          <div style={{ flexGrow: isMobile ? 1 : 0 }}>
            <AgentList
              selectedId={activeAgentId || undefined}
              onChange={(id) => {
                setSelectedAgentId(id);
                loadedGraphForRef.current = "";
              }}
            />
          </div>
          <Space size={8}>
            <Button icon={<ZoomInOutlined />} onClick={handleFit} disabled={!graphData.nodes.length} />
            <Button icon={<ReloadOutlined />} onClick={handleRefresh} loading={graphLoading} disabled={!activeAgentId} />
          </Space>
        </div>
      </div>

      {/* Primary Split View Grid Layer */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: isTablet ? "1fr" : "minmax(0, 1fr) 360px",
          borderRadius: 16,
          border: "1px solid var(--app-border)",
          background: "var(--app-surface)",
          boxShadow: isDark
            ? "0 10px 30px -10px rgba(0,0,0,0.5), 0 1px 3px rgba(0,0,0,0.3)"
            : "0 10px 30px -10px rgba(0,0,0,0.04), 0 1px 3px rgba(0,0,0,0.02)",
          overflow: "hidden"
        }}
      >
        {/* Left Interactive Graph Module */}
        <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
          <div
            style={{
              display: "flex",
              flexDirection: isMobile ? "column" : "row",
              alignItems: isMobile ? "stretch" : "center",
              justifyContent: "space-between",
              gap: 16,
              padding: "16px 20px",
              borderBottom: "1px solid var(--app-border)",
              backgroundColor: "var(--app-surface-muted)"
            }}
          >
            <Space size={16} wrap>
              <Space size={8}>
                <Badge status="processing" color="#22c55e" />
                <Text strong style={{ fontSize: 12, letterSpacing: "0.05em", color: "#8c8c8c" }}>
                  KNOWLEDGE GRAPH
                </Text>
              </Space>
              <TagWrapper color="#e0e7ff" textColor="#4f46e5">
                {graphData.nodes.length} nodes · {graphData.links.length} relationships
              </TagWrapper>
            </Space>

            <Input.Search
              allowClear
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search graph attributes..."
              style={{ width: isMobile ? "100%" : 260 }}
            />
          </div>

          <div ref={containerRef} style={{ position: "relative", height: dimensions.height, background: "var(--app-surface)", overflow: "hidden" }}>
            <div
              style={{
                position: "absolute",
                inset: 0,
                pointerEvents: "none",
                backgroundImage: `radial-gradient(${isDark ? "#2e3347" : "#e8e8e8"} 1.2px, transparent 1.2px)`,
                backgroundSize: "24px 24px",
                opacity: 0.6,
              }}
            />

            {graphLoading && (
              <div
                style={{
                  position: "absolute",
                  inset: 0,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  background: isDark ? "rgba(13, 15, 23, 0.75)" : "rgba(255, 255, 255, 0.75)",
                  backdropFilter: "blur(2px)",
                  zIndex: 10,
                }}
              >
                <Spin size="large" tip="Loading Graph System..." />
              </div>
            )}

            {!activeAgentId && !graphLoading ? (
              <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <Empty description="No active agent configuration loaded" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              </div>
            ) : graphData.nodes.length === 0 && !graphLoading ? (
              <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <Empty description="No executable relational clusters found" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              </div>
            ) : (
              <ForceGraph2D
                ref={graphRef}
                graphData={visibleGraphData}
                width={dimensions.width}
                height={dimensions.height}
                backgroundColor="transparent"
                d3AlphaDecay={0.02}
                d3VelocityDecay={0.3}
                cooldownTicks={100}
                nodeId="id"
                nodeVal="val"
                nodeRelSize={6}
                nodeColor={(node) => node.color}
                nodeLabel={(node) => {
                  const title = `${node.type}: ${node.label}`;
                  const text = String(node.properties.text ?? node.properties.description ?? "");
                  return text ? `${title}\n${truncate(text, 160)}` : title;
                }}
                linkLabel={(link) => link.label}
                linkColor={(link: any) =>
                  selectedNode &&
                  (getEndpointId(link.source) === selectedNode.id || getEndpointId(link.target) === selectedNode.id)
                    ? (isDark ? "rgba(248, 250, 252, 0.9)" : "rgba(15, 23, 42, 0.9)")
                    : (isDark ? "rgba(71, 85, 105, 0.8)" : "rgba(226, 232, 240, 0.8)")
                }
                linkWidth={(link: any) =>
                  selectedNode &&
                  (getEndpointId(link.source) === selectedNode.id || getEndpointId(link.target) === selectedNode.id)
                    ? 2.5
                    : 1.2
                }
                linkCurvature={0}
                linkDirectionalArrowLength={5}
                linkDirectionalArrowRelPos={1}
                linkDirectionalParticles={(link: any) =>
                  selectedNode &&
                  (getEndpointId(link.source) === selectedNode.id || getEndpointId(link.target) === selectedNode.id)
                    ? 3
                    : 0
                }
                linkDirectionalParticleWidth={2.5}
                linkDirectionalParticleColor={() => "#6366f1"}
                linkDirectionalParticleSpeed={0.008}
                linkCanvasObjectMode={() => "after"}
                linkCanvasObject={(link: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
                  if (globalScale < 1.8) return;

                  const MAX_FONT_SIZE = 3.2;
                  const label = link.label;
                  const fontSize = Math.min(MAX_FONT_SIZE, 9 / globalScale);
                  ctx.font = `500 ${fontSize}px Inter, -apple-system, BlinkMacSystemFont, sans-serif`;

                  const start = typeof link.source === "string" ? { x: 0, y: 0 } : link.source;
                  const end = typeof link.target === "string" ? { x: 0, y: 0 } : link.target;
                  if (typeof start === "string" || typeof end === "string") return;

                  const textPos = {
                    x: start.x! + (end.x! - start.x!) / 2,
                    y: start.y! + (end.y! - start.y!) / 2,
                  };

                  const relAngle = Math.atan2(end.y! - start.y!, end.x! - start.x!);
                  const labelRotation = relAngle > Math.PI / 2 || relAngle < -Math.PI / 2 ? relAngle + Math.PI : relAngle;

                  ctx.save();
                  ctx.translate(textPos.x, textPos.y);
                  ctx.rotate(labelRotation);

                  const textWidth = ctx.measureText(label).width;
                  const padding = fontSize * 0.4;
                  const bckgDimensions = [textWidth + padding, fontSize + padding];

                  ctx.fillStyle = isDark ? "rgba(20, 22, 31, 0.95)" : "rgba(255, 255, 255, 0.95)";
                  ctx.beginPath();
                  const rx = bckgDimensions[0] / 2, ry = bckgDimensions[1] / 2;
                  ctx.roundRect(-rx, -ry, bckgDimensions[0], bckgDimensions[1], 2);
                  ctx.fill();

                  ctx.textAlign = "center";
                  ctx.textBaseline = "middle";
                  ctx.fillStyle = isDark ? "#cbd5e1" : "#475569";
                  ctx.fillText(label, 0, 0);
                  ctx.restore();
                }}
                onNodeClick={(node: any) => setSelectedNode(node)}
                onBackgroundClick={() => setSelectedNode(null)}
                onNodeDragEnd={(node: any) => {
                  node.fx = node.x;
                  node.fy = node.y;
                }}
                nodeCanvasObject={(node, ctx, globalScale) => {
                  const typeRadius: Record<string, number> = { Agent: 22, KnowledgeBase: 18, Chunk: 13, Entity: 15 };
                  const radius = typeRadius[node.type] ?? 14;
                  const isSelected = selectedNode?.id === node.id;
                  const isConnected = selectedNode && graphData.links.some(
                    (l) => (getEndpointId(l.source) === selectedNode.id || getEndpointId(l.target) === selectedNode.id) &&
                           (getEndpointId(l.source) === node.id || getEndpointId(l.target) === node.id)
                  );
                  const fontSize = Math.max(3.5, 9.5 / globalScale);
                  const label = truncate(node.label, node.type === "Chunk" ? 14 : 12);
                  const dimmed = selectedNode && !isSelected && !isConnected;

                  if (isSelected) {
                    ctx.beginPath();
                    ctx.arc(node.x ?? 0, node.y ?? 0, radius + 5, 0, 2 * Math.PI);
                    ctx.fillStyle = node.color + "25";
                    ctx.fill();
                  }

                  ctx.beginPath();
                  ctx.arc(node.x ?? 0, node.y ?? 0, radius, 0, 2 * Math.PI);
                  ctx.fillStyle = node.color + (dimmed ? "30" : "f5");
                  ctx.fill();

                  ctx.lineWidth = isSelected ? 2.5 : 1.2;
                  ctx.strokeStyle = isSelected ? (isDark ? "#ffffff" : "#0f172a") : (node.color + (dimmed ? "15" : "af"));
                  ctx.stroke();

                  ctx.font = `${isSelected ? "600" : "500"} ${fontSize}px Inter, -apple-system, sans-serif`;
                  ctx.textAlign = "center";
                  ctx.textBaseline = "middle";
                  ctx.fillStyle = dimmed 
                    ? (isDark ? "rgba(148,163,184,0.35)" : "rgba(100,116,139,0.35)") 
                    : (isDark ? "#f8fafc" : "#1e293b");
                  
                  if (label.length > 9) {
                    const mid = Math.floor(label.length / 2);
                    const splitPos = label.indexOf(" ", mid - 2) > -1 ? label.indexOf(" ", mid - 2) : mid;
                    ctx.fillText(label.slice(0, splitPos), node.x ?? 0, (node.y ?? 0) - fontSize * 0.55);
                    ctx.fillText(label.slice(splitPos).trim(), node.x ?? 0, (node.y ?? 0) + fontSize * 0.55);
                  } else {
                    ctx.fillText(label, node.x ?? 0, node.y ?? 0);
                  }
                }}
              />
            )}
          </div>
        </div>

        {/* Right Inspection Drawer / Sidebar */}
        <aside 
          style={{ 
            borderLeft: isTablet ? "none" : "1px solid var(--app-border)", 
            borderTop: isTablet ? "1px solid var(--app-border)" : "none",
            background: "var(--app-surface-muted)", 
            padding: 24, 
            display: "flex",
            flexDirection: "column",
            gap: 20,
            overflowY: "auto", 
            maxHeight: isTablet ? "none" : dimensions.height + 53 
          }}
        >
          {/* Legend Config */}
          <div>
            <Text strong style={{ fontSize: 11, color: "var(--app-text-soft)", letterSpacing: "0.05em", display: "block", marginBottom: 12 }}>
              NODE TYPES
            </Text>
            <div style={{ display: "flex", gap: "8px 10px", flexWrap: "wrap" }}>
              {NODE_TYPES.map((type) => (
                <span
                  key={type}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    color: NODE_COLORS[type],
                    background: "var(--app-surface)",
                    border: `1px solid ${NODE_COLORS[type]}30`,
                    borderRadius: 6,
                    padding: "4px 10px",
                    fontSize: 12,
                    fontWeight: 500,
                    boxShadow: "0 1px 2px rgba(0,0,0,0.02)"
                  }}
                >
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: NODE_COLORS[type] }} />
                  {type}
                </span>
              ))}
            </div>
          </div>

          <div style={{ borderTop: "1px solid var(--app-border)", paddingTop: 4 }} />

          {selectedNode ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
              <div>
                <span style={{ 
                  textTransform: "uppercase", 
                  fontSize: 10, 
                  fontWeight: 700, 
                  color: selectedNode.color, 
                  backgroundColor: selectedNode.color + "15",
                  padding: "2px 6px",
                  borderRadius: 4,
                  letterSpacing: "0.05em"
                }}>
                  {selectedNode.type}
                </span>
                <Title level={4} style={{ margin: "8px 0 0", color: "var(--app-text)", fontWeight: 600, lineHeight: 1.3 }}>
                  {selectedNode.label}
                </Title>
              </div>

              {/* Attributes Card Stack */}
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                {Object.entries(selectedNode.properties).map(([key, value]) => (
                  <div key={key} style={{ background: "var(--app-surface)", padding: "10px 14px", borderRadius: 8, border: "1px solid var(--app-border)" }}>
                    <div style={{ color: "var(--app-text-soft)", fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 4 }}>
                      {key}
                    </div>
                    <div style={{ color: "var(--app-text)", fontSize: 13, lineHeight: 1.5, overflowWrap: "anywhere" }}>
                      {String(value)}
                    </div>
                  </div>
                ))}
              </div>

              {/* Edge/Link Data */}
              {selectedLinks.length > 0 && (
                <div style={{ marginTop: 4, display: "flex", flexDirection: "column", gap: 10 }}>
                  <Text strong style={{ fontSize: 11, color: "var(--app-text-soft)", letterSpacing: "0.05em" }}>
                    CONNECTED GRAPH LINKS
                  </Text>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {selectedLinks.map((link, index) => {
                      const otherNode = nodeById.get(getLinkedNodeId(link, selectedNode.id));
                      return (
                        <div 
                          key={`${getEndpointId(link.source)}-${getEndpointId(link.target)}-${index}`} 
                          style={{ 
                            fontSize: 13, 
                            padding: "10px 12px", 
                            background: "var(--app-surface)", 
                            borderRadius: 8, 
                            border: "1px solid var(--app-border)",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            gap: 12
                          }}
                        >
                          <span style={{ color: "#4f46e5", fontWeight: 600, fontSize: 12 }}>{link.label}</span>
                          <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                            <span style={{ color: "var(--app-text-soft)" }}>→</span>
                            <span style={{ color: "var(--app-text)", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              {otherNode?.label ?? "Unknown Reference"}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div style={{ 
              height: "100%", 
              display: "flex", 
              flexDirection: "column", 
              alignItems: "center", 
              justifyContent: "center", 
              padding: "40px 0",
              color: "#94a3b8",
              textAlign: "center"
            }}>
              <InfoCircleOutlined style={{ fontSize: 26, marginBottom: 12, color: "#cbd5e1" }} />
              <Text type="secondary" style={{ fontSize: 13, maxWidth: 220 }}>
                Select any visual element node within the graph view to inspect properties.
              </Text>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function TagWrapper({ children, color, textColor }: { children: React.ReactNode, color: string, textColor: string }) {
  return (
    <span style={{
      display: "inline-flex",
      alignItems: "center",
      padding: "2px 8px",
      borderRadius: 6,
      fontSize: 12,
      fontWeight: 600,
      backgroundColor: color,
      color: textColor
    }}>
      {children}
    </span>
  );
}
