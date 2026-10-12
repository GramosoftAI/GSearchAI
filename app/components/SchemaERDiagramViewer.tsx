"use client";

import React, { useMemo, useState, useCallback } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  Handle,
  Position,
  MarkerType,
  NodeProps,
  Edge,
  Node,
  Connection,
  addEdge,
  ConnectionMode,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";
import {
  KeyOutlined,
  LinkOutlined,
  DatabaseOutlined,
  SwapOutlined,
  ClearOutlined,
  EditOutlined,
  CheckOutlined,
  PlusCircleOutlined,
  DeleteOutlined,
} from "@ant-design/icons";
import { toast } from "react-hot-toast";

interface ColumnItem {
  name: string;
  data_type: string;
  is_primary_key?: boolean;
  is_foreign_key?: boolean;
  is_nullable?: boolean;
}

interface TableNodeData {
  tableName: string;
  columns: ColumnItem[];
  tableType?: string;
  isSource?: boolean;
  isTarget?: boolean;
  highlighted?: boolean;
  dimmed?: boolean;
  isEditMode?: boolean;
  [key: string]: unknown;
}

// Custom Node for displaying a Database Table with interactive column-level wiring handles
const DatabaseTableNode = ({ data }: NodeProps<Node<TableNodeData>>) => {
  const { tableName, columns = [], isSource, isTarget, highlighted, dimmed, isEditMode } = data;

  const borderColor = isEditMode
    ? "#f59e0b" // Amber in Edit Mode
    : isSource
    ? "#3b82f6" // Vibrant Blue for Source
    : isTarget
    ? "#10b981" // Vibrant Emerald for Destination
    : highlighted
    ? "#8b5cf6" // Purple for search highlight
    : "#cbd5e1";

  const headerGradient = isEditMode
    ? "linear-gradient(135deg, #d97706 0%, #f59e0b 100%)"
    : isSource
    ? "linear-gradient(135deg, #1d4ed8 0%, #3b82f6 100%)"
    : isTarget
    ? "linear-gradient(135deg, #047857 0%, #10b981 100%)"
    : highlighted
    ? "linear-gradient(135deg, #6d28d9 0%, #8b5cf6 100%)"
    : "linear-gradient(135deg, #1e293b 0%, #334155 100%)";

  return (
    <div
      style={{
        minWidth: 260,
        maxWidth: 320,
        backgroundColor: "#ffffff",
        borderRadius: 10,
        border: `2px solid ${borderColor}`,
        boxShadow: isEditMode
          ? "0 14px 32px -6px rgba(245, 158, 11, 0.45)"
          : isSource || isTarget || highlighted
          ? `0 12px 28px -6px ${isSource ? "rgba(59, 130, 246, 0.4)" : isTarget ? "rgba(16, 185, 129, 0.4)" : "rgba(139, 92, 246, 0.4)"}`
          : "0 4px 12px rgba(0, 0, 0, 0.08)",
        overflow: isEditMode ? "visible" : "hidden",
        fontSize: 12,
        fontFamily: "var(--font-geist-sans), system-ui, -apple-system, sans-serif",
        opacity: dimmed ? 0.25 : 1,
        transition: "opacity 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease",
      }}
    >
      {/* Table Header */}
      <div
        style={{
          background: headerGradient,
          color: "#ffffff",
          padding: "10px 14px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          borderBottom: "1px solid rgba(255, 255, 255, 0.15)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, overflow: "hidden" }}>
          <DatabaseOutlined style={{ fontSize: 14, color: "#e2e8f0" }} />
          <span
            style={{
              fontWeight: 700,
              fontSize: 13,
              letterSpacing: "0.2px",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
            title={tableName}
          >
            {tableName}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
          {isEditMode && (
            <span
              style={{
                fontSize: 9,
                fontWeight: 800,
                padding: "2px 6px",
                borderRadius: 4,
                backgroundColor: "#ffffff",
                color: "#d97706",
                textTransform: "uppercase",
              }}
            >
              Wiring ON
            </span>
          )}
          {isSource && (
            <span
              style={{
                fontSize: 9,
                fontWeight: 700,
                padding: "2px 6px",
                borderRadius: 4,
                backgroundColor: "#ffffff",
                color: "#1d4ed8",
                textTransform: "uppercase",
              }}
            >
              Source
            </span>
          )}
          {isTarget && (
            <span
              style={{
                fontSize: 9,
                fontWeight: 700,
                padding: "2px 6px",
                borderRadius: 4,
                backgroundColor: "#ffffff",
                color: "#047857",
                textTransform: "uppercase",
              }}
            >
              Target
            </span>
          )}
          <span
            style={{
              fontSize: 10,
              padding: "2px 7px",
              borderRadius: 9999,
              backgroundColor: "rgba(255, 255, 255, 0.25)",
              fontWeight: 600,
            }}
          >
            {columns.length} cols
          </span>
        </div>
      </div>

      {/* Columns List */}
      <div style={{ maxHeight: 260, overflowY: "auto", backgroundColor: "#fafbfc" }}>
        {columns.map((col, idx) => {
          const isPK = col.is_primary_key;
          const isFK = col.is_foreign_key;

          return (
            <div
              key={col.name || idx}
              style={{
                position: "relative",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "7px 12px",
                borderBottom: "1px solid #f1f5f9",
                backgroundColor: isPK ? "#fffbeb" : isFK ? "#f0fdf4" : idx % 2 === 0 ? "#ffffff" : "#f8fafc",
                gap: 8,
              }}
            >
              {/* Left Connector Handle (Target for drop) */}
              <Handle
                type="target"
                position={Position.Left}
                id={`${tableName}-${col.name}-target`}
                style={{
                  top: "50%",
                  left: isEditMode ? -8 : -5,
                  width: isEditMode ? 16 : 8,
                  height: isEditMode ? 16 : 8,
                  backgroundColor: isPK ? "#f59e0b" : "#3b82f6",
                  border: isEditMode ? "2.5px solid #ffffff" : "2px solid #ffffff",
                  borderRadius: "50%",
                  cursor: isEditMode ? "crosshair" : "default",
                  boxShadow: isEditMode ? "0 0 10px rgba(59, 130, 246, 0.9)" : "none",
                  zIndex: 30,
                }}
              />

              {/* Column Name & Key Badges */}
              <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0, flex: 1 }}>
                {isPK && (
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 2,
                      fontSize: 9,
                      fontWeight: 700,
                      color: "#b45309",
                      backgroundColor: "#fef3c7",
                      padding: "1px 4px",
                      borderRadius: 4,
                      border: "1px solid #fde68a",
                    }}
                  >
                    <KeyOutlined style={{ fontSize: 9 }} /> PK
                  </span>
                )}
                {isFK && (
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 2,
                      fontSize: 9,
                      fontWeight: 700,
                      color: "#047857",
                      backgroundColor: "#d1fae5",
                      padding: "1px 4px",
                      borderRadius: 4,
                      border: "1px solid #a7f3d0",
                    }}
                  >
                    <LinkOutlined style={{ fontSize: 9 }} /> FK
                  </span>
                )}
                <span
                  style={{
                    fontFamily: "monospace",
                    fontSize: 11,
                    fontWeight: isPK || isFK ? 600 : 400,
                    color: isPK ? "#92400e" : isFK ? "#065f46" : "#1e293b",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                  title={col.name}
                >
                  {col.name}
                </span>
              </div>

              {/* Right Side: Column Data Type & (+) Connector Handle */}
              <div style={{ display: "flex", alignItems: "center", gap: 6, position: "relative" }}>
                <span
                  style={{
                    fontSize: 10,
                    fontFamily: "monospace",
                    color: "#64748b",
                    backgroundColor: "#f1f5f9",
                    padding: "1px 5px",
                    borderRadius: 4,
                    whiteSpace: "nowrap",
                  }}
                >
                  {col.data_type}
                </span>

                {/* The green (+) button IS the Handle in Edit Mode */}
                <Handle
                  type="source"
                  position={Position.Right}
                  id={`${tableName}-${col.name}-source`}
                  style={
                    isEditMode
                      ? {
                          position: "relative",
                          transform: "none",
                          top: "auto",
                          right: "auto",
                          width: 22,
                          height: 22,
                          borderRadius: "50%",
                          backgroundColor: "#10b981",
                          border: "2px solid #ffffff",
                          display: "inline-flex",
                          alignItems: "center",
                          justifyContent: "center",
                          cursor: "crosshair",
                          boxShadow: "0 2px 5px rgba(16, 185, 129, 0.5)",
                          zIndex: 30,
                        }
                      : {
                          top: "50%",
                          right: -5,
                          width: 8,
                          height: 8,
                          backgroundColor: isFK ? "#10b981" : "#64748b",
                          border: "2px solid #ffffff",
                          borderRadius: "50%",
                        }
                  }
                >
                  {isEditMode && (
                    <span
                      style={{
                        fontSize: 13,
                        fontWeight: 900,
                        color: "#ffffff",
                        lineHeight: 1,
                        userSelect: "none",
                        pointerEvents: "none",
                        marginBottom: 1,
                      }}
                    >
                      +
                    </span>
                  )}
                </Handle>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const nodeTypes = {
  tableNode: DatabaseTableNode,
};

interface SchemaERDiagramViewerProps {
  tables: Record<string, any>;
  filterQuery?: string;
  isFullscreen?: boolean;
  kbId?: string;
  onSaveCustomMapping?: (newForeignKeys: Array<{ sourceTable: string; sourceColumn: string; targetTable: string; targetColumn: string }>) => void;
}

// 4-Column Grid Clean Layout Function (Organized 4 tables per row, prevents messy overlapping)
function getCleanOrderedLayout(nodes: Node[], edges: Edge[], columnsPerRow = 4) {
  const colWidth = 320;
  const colGap = 160;
  const rowGap = 140;

  const rowHeights: number[] = [];

  nodes.forEach((node, index) => {
    const colCount = (node.data as any)?.columns?.length || 5;
    const estimatedHeight = Math.min(320, 50 + colCount * 28);
    const rowIndex = Math.floor(index / columnsPerRow);
    rowHeights[rowIndex] = Math.max(rowHeights[rowIndex] || 0, estimatedHeight);
  });

  const layoutedNodes = nodes.map((node, index) => {
    const rowIndex = Math.floor(index / columnsPerRow);
    const colIndex = index % columnsPerRow;

    let yPos = 40;
    for (let r = 0; r < rowIndex; r++) {
      yPos += (rowHeights[r] || 250) + rowGap;
    }

    const xPos = 40 + colIndex * (colWidth + colGap);

    return {
      ...node,
      position: { x: xPos, y: yPos },
    };
  });

  return { nodes: layoutedNodes, edges };
}

// Dagre Layout Algorithm for Directed Relationships
function getDagreLayout(nodes: Node[], edges: Edge[]) {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));

  dagreGraph.setGraph({
    rankdir: "LR",
    nodesep: 100,
    ranksep: 200,
    marginx: 50,
    marginy: 50,
  });

  nodes.forEach((node) => {
    const colCount = (node.data as any)?.columns?.length || 5;
    const estimatedHeight = Math.min(320, 50 + colCount * 28);
    dagreGraph.setNode(node.id, { width: 320, height: estimatedHeight });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    const colCount = (node.data as any)?.columns?.length || 5;
    const estimatedHeight = Math.min(320, 50 + colCount * 28);

    return {
      ...node,
      position: {
        x: (nodeWithPosition?.x || 0) - 160,
        y: (nodeWithPosition?.y || 0) - estimatedHeight / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
}

export const SchemaERDiagramViewer: React.FC<SchemaERDiagramViewerProps> = ({
  tables,
  filterQuery = "",
  isFullscreen = false,
  kbId = "default_kb",
  onSaveCustomMapping,
}) => {
  const storageKey = `k2b_custom_wiring_${kbId}`;
  const [sourceSearch, setSourceSearch] = useState("");
  const [targetSearch, setTargetSearch] = useState("");
  const [layoutMode, setLayoutMode] = useState<"grid" | "flow">("grid"); // 4-table order grid default
  const [maxDisplayLimit, setMaxDisplayLimit] = useState<number>(30);
  const [internalFullscreen, setInternalFullscreen] = useState(false);
  const [isEditMode, setIsEditMode] = useState(false); // Edit & Wiring Mode toggle

  // Load custom saved connections from localStorage so they persist across tabs/reopens
  const [customAddedEdges, setCustomAddedEdges] = useState<Edge[]>(() => {
    if (typeof window !== "undefined") {
      try {
        const saved = localStorage.getItem(`k2b_custom_wiring_${kbId}`);
        if (saved) return JSON.parse(saved);
      } catch (err) {
        console.error("Failed to load saved wiring from storage:", err);
      }
    }
    return [];
  });

  const activeFullscreen = isFullscreen || internalFullscreen;

  // Collect table names for dropdown / autocompletion
  const allTableNames = useMemo(() => Object.keys(tables).sort(), [tables]);

  const filteredSourceOptions = useMemo(() => {
    if (!sourceSearch.trim()) return [];
    const q = sourceSearch.toLowerCase().trim();
    return allTableNames.filter((t) => t.toLowerCase().includes(q)).slice(0, 8);
  }, [allTableNames, sourceSearch]);

  const filteredTargetOptions = useMemo(() => {
    if (!targetSearch.trim()) return [];
    const q = targetSearch.toLowerCase().trim();
    return allTableNames.filter((t) => t.toLowerCase().includes(q)).slice(0, 8);
  }, [allTableNames, targetSearch]);

  const { initialNodes, initialEdges } = useMemo(() => {
    const nodesList: Node[] = [];
    const edgesList: Edge[] = [];
    const query = filterQuery.toLowerCase().trim();
    const srcQuery = sourceSearch.toLowerCase().trim();
    const tgtQuery = targetSearch.toLowerCase().trim();

    // Map all foreign keys
    const fkMap: Record<string, Set<string>> = {};
    Object.entries(tables).forEach(([tblName, tblObj]: [string, any]) => {
      const foreignKeys = tblObj.foreign_keys || [];
      foreignKeys.forEach((fk: any) => {
        const cols = fk.constrained_columns || [];
        if (!fkMap[tblName]) fkMap[tblName] = new Set();
        cols.forEach((col: string) => fkMap[tblName].add(col));
      });
    });

    // Check which tables are involved in source/target filter
    const activeSrcTable = allTableNames.find((t) => t.toLowerCase() === srcQuery);
    const activeTgtTable = allTableNames.find((t) => t.toLowerCase() === tgtQuery);

    let candidateTableNames = allTableNames;

    if (activeSrcTable || activeTgtTable) {
      const connectedSet = new Set<string>();
      if (activeSrcTable) connectedSet.add(activeSrcTable);
      if (activeTgtTable) connectedSet.add(activeTgtTable);

      Object.entries(tables).forEach(([tblName, tblObj]: [string, any]) => {
        const foreignKeys = tblObj.foreign_keys || [];
        foreignKeys.forEach((fk: any) => {
          if (activeSrcTable && tblName === activeSrcTable) {
            connectedSet.add(fk.referred_table);
          }
          if (activeTgtTable && fk.referred_table === activeTgtTable) {
            connectedSet.add(tblName);
          }
        });
      });

      candidateTableNames = allTableNames.filter((t) => connectedSet.has(t));
    } else if (query) {
      candidateTableNames = allTableNames.filter((t) => {
        if (t.toLowerCase().includes(query)) return true;
        const tblObj = tables[t];
        const rawCols = tblObj?.columns || [];
        const cols = Array.isArray(rawCols) ? rawCols : Object.values(rawCols);
        return cols.some((c: any) => c.name?.toLowerCase().includes(query));
      });
    }

    const tablesToRender = candidateTableNames.slice(0, maxDisplayLimit);
    const renderSet = new Set(tablesToRender);

    // Build Nodes
    tablesToRender.forEach((tblName) => {
      const tblObj = tables[tblName];
      const rawCols = tblObj?.columns || [];
      const colList: ColumnItem[] = (Array.isArray(rawCols) ? rawCols : Object.values(rawCols)).map(
        (c: any) => ({
          name: c.name,
          data_type: c.data_type,
          is_primary_key: Boolean(c.is_primary_key),
          is_foreign_key: fkMap[tblName]?.has(c.name) ?? false,
          is_nullable: Boolean(c.is_nullable),
        })
      );

      const isSource = Boolean(activeSrcTable && tblName === activeSrcTable);
      const isTarget = Boolean(activeTgtTable && tblName === activeTgtTable);

      const isSearchMatch = Boolean(
        (srcQuery && tblName.toLowerCase().includes(srcQuery)) ||
        (tgtQuery && tblName.toLowerCase().includes(tgtQuery)) ||
        (query && tblName.toLowerCase().includes(query))
      );

      nodesList.push({
        id: tblName,
        type: "tableNode",
        position: { x: 0, y: 0 },
        data: {
          tableName: tblName,
          columns: colList,
          tableType: tblObj?.table_type,
          isSource,
          isTarget,
          highlighted: isSearchMatch,
          dimmed: (activeSrcTable || activeTgtTable) ? (!isSource && !isTarget && !renderSet.has(tblName)) : false,
          isEditMode,
        },
      });
    });

    // Build Bold Edges
    tablesToRender.forEach((tblName) => {
      const tblObj = tables[tblName];
      const foreignKeys = tblObj?.foreign_keys || [];
      foreignKeys.forEach((fk: any, fkIdx: number) => {
        const targetTable = fk.referred_table;
        if (!renderSet.has(targetTable)) return;

        const sourceCols = fk.constrained_columns || [];
        const targetCols = fk.referred_columns || [];
        const srcCol = sourceCols[0] || "";
        const tgtCol = targetCols[0] || "";

        const isDirectConnection =
          (activeSrcTable && activeTgtTable && tblName === activeSrcTable && targetTable === activeTgtTable) ||
          (activeSrcTable && tblName === activeSrcTable) ||
          (activeTgtTable && targetTable === activeTgtTable);

        const strokeColor = isDirectConnection ? "#2563eb" : "#059669";
        const strokeWidth = isDirectConnection ? 3.5 : 2.5;

        const edgeId = `fk-${tblName}-${srcCol}->${targetTable}-${tgtCol}-${fkIdx}`;

        edgesList.push({
          id: edgeId,
          source: tblName,
          target: targetTable,
          sourceHandle: srcCol ? `${tblName}-${srcCol}-source` : undefined,
          targetHandle: tgtCol ? `${targetTable}-${tgtCol}-target` : undefined,
          type: "smoothstep",
          animated: isDirectConnection,
          label: `${srcCol} ➔ ${tgtCol}`,
          labelStyle: {
            fill: isDirectConnection ? "#1e40af" : "#065f46",
            fontWeight: 800,
            fontSize: 11,
            letterSpacing: "0.2px",
          },
          labelBgStyle: {
            fill: "#ffffff",
            fillOpacity: 0.95,
            rx: 6,
            ry: 6,
            stroke: strokeColor,
            strokeWidth: 1.5,
          },
          labelBgPadding: [6, 4] as [number, number],
          style: {
            stroke: strokeColor,
            strokeWidth,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            width: isDirectConnection ? 20 : 16,
            height: isDirectConnection ? 20 : 16,
            color: strokeColor,
          },
        });
      });
    });

    // Merge any custom connected edges
    customAddedEdges.forEach((edge) => {
      if (renderSet.has(edge.source) && renderSet.has(edge.target)) {
        edgesList.push(edge);
      }
    });

    const layoutResult =
      layoutMode === "grid"
        ? getCleanOrderedLayout(nodesList, edgesList, 4)
        : getDagreLayout(nodesList, edgesList);

    return { initialNodes: layoutResult.nodes, initialEdges: layoutResult.edges };
  }, [tables, filterQuery, sourceSearch, targetSearch, layoutMode, maxDisplayLimit, allTableNames, isEditMode, customAddedEdges]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  React.useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
  }, [initialNodes, initialEdges, setNodes, setEdges]);

  // Wire new connection between foreign key source and target table column
  const onConnect = useCallback(
    (connection: Connection) => {
      const srcHandle = connection.sourceHandle || "";
      const tgtHandle = connection.targetHandle || "";

      // Parse column names from handle ids: tableName-colName-source
      const srcCol = srcHandle.split("-")[1] || "fk";
      const tgtCol = tgtHandle.split("-")[1] || "id";

      const newEdge: Edge = {
        id: `custom-fk-${connection.source}-${srcCol}->${connection.target}-${tgtCol}-${Date.now()}`,
        source: connection.source,
        target: connection.target,
        sourceHandle: connection.sourceHandle,
        targetHandle: connection.targetHandle,
        type: "smoothstep",
        animated: true,
        label: `NEW: ${srcCol} ➔ ${tgtCol}`,
        labelStyle: {
          fill: "#b45309",
          fontWeight: 800,
          fontSize: 11,
        },
        labelBgStyle: {
          fill: "#fffbeb",
          fillOpacity: 0.95,
          rx: 6,
          ry: 6,
          stroke: "#f59e0b",
          strokeWidth: 2,
        },
        style: {
          stroke: "#f59e0b", // Distinct Amber / Gold for newly wired connections
          strokeWidth: 3.5,
          strokeDasharray: "5 5",
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 18,
          height: 18,
          color: "#f59e0b",
        },
      };

      setEdges((eds) => addEdge(newEdge, eds));
      setCustomAddedEdges((prev) => [...prev, newEdge]);
      toast.success(`Wired foreign key: ${connection.source}.${srcCol} ➔ ${connection.target}.${tgtCol}`);
    },
    [setEdges]
  );

  const handleSaveWireMappings = () => {
    if (customAddedEdges.length === 0) {
      toast("No new wire mappings created yet.", { icon: "ℹ️" });
      return;
    }

    const formattedMappings = customAddedEdges.map((e) => {
      const srcCol = (e.sourceHandle || "").split("-")[1] || "";
      const tgtCol = (e.targetHandle || "").split("-")[1] || "";
      return {
        sourceTable: e.source,
        sourceColumn: srcCol,
        targetTable: e.target,
        targetColumn: tgtCol,
      };
    });

    if (typeof window !== "undefined") {
      try {
        localStorage.setItem(storageKey, JSON.stringify(customAddedEdges));
      } catch (err) {
        console.error("Failed to persist custom wiring to localStorage:", err);
      }
    }

    if (onSaveCustomMapping) {
      onSaveCustomMapping(formattedMappings);
    }

    toast.success(`Saved ${customAddedEdges.length} custom wire connection(s) permanently!`);
    setIsEditMode(false);
  };

  const handleClearCustomWires = () => {
    setCustomAddedEdges([]);
    if (typeof window !== "undefined") {
      try {
        localStorage.removeItem(storageKey);
      } catch (err) {
        console.error("Failed to clear custom wiring from storage:", err);
      }
    }
    toast.success("Reset custom wired connections.");
  };

  return (
    <div
      style={
        activeFullscreen
          ? {
              position: "fixed",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              zIndex: 99999,
              backgroundColor: "#f8fafc",
              display: "flex",
              flexDirection: "column",
            }
          : {
              width: "100%",
              height: "calc(82vh - 210px)",
              minHeight: 600,
              backgroundColor: "#f8fafc",
              borderRadius: 12,
              border: isEditMode ? "2px solid #f59e0b" : "1px solid #e2e8f0",
              position: "relative",
              display: "flex",
              flexDirection: "column",
              overflow: "hidden",
            }
      }
    >
      {/* Top Filter Bar: Source Point, Destination Point, Edit/Wiring Mode, 4-Table Layout & Fullscreen */}
      <div
        style={{
          padding: "10px 16px",
          backgroundColor: isEditMode ? "#fffbeb" : "#ffffff",
          borderBottom: isEditMode ? "1px solid #fde68a" : "1px solid #e2e8f0",
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          zIndex: 10,
          transition: "background-color 0.2s ease",
        }}
      >
        {/* Source and Destination Search Boxes */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          {/* Source Table Input */}
          <div style={{ position: "relative" }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                backgroundColor: "#eff6ff",
                border: "1.5px solid #3b82f6",
                borderRadius: 8,
                padding: "5px 10px",
              }}
            >
              <span style={{ fontSize: 11, fontWeight: 700, color: "#1d4ed8" }}>Source:</span>
              <input
                type="text"
                placeholder="Type source table (e.g. employee)..."
                value={sourceSearch}
                onChange={(e) => setSourceSearch(e.target.value)}
                style={{
                  border: "none",
                  outline: "none",
                  backgroundColor: "transparent",
                  fontSize: 12,
                  width: 170,
                  color: "#1e293b",
                  fontWeight: 500,
                }}
              />
              {sourceSearch && (
                <button
                  type="button"
                  onClick={() => setSourceSearch("")}
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    color: "#94a3b8",
                    fontSize: 11,
                  }}
                >
                  ✕
                </button>
              )}
            </div>

            {/* Source Autocomplete Dropdown */}
            {filteredSourceOptions.length > 0 && sourceSearch.toLowerCase() !== filteredSourceOptions[0]?.toLowerCase() && (
              <div
                style={{
                  position: "absolute",
                  top: "100%",
                  left: 0,
                  marginTop: 4,
                  backgroundColor: "#ffffff",
                  border: "1px solid #bfdbfe",
                  borderRadius: 8,
                  boxShadow: "0 10px 15px -3px rgba(0,0,0,0.1)",
                  zIndex: 50,
                  width: 240,
                  maxHeight: 180,
                  overflowY: "auto",
                }}
              >
                {filteredSourceOptions.map((t) => (
                  <div
                    key={t}
                    onClick={() => setSourceSearch(t)}
                    style={{
                      padding: "6px 12px",
                      fontSize: 11,
                      fontFamily: "monospace",
                      cursor: "pointer",
                      borderBottom: "1px solid #f1f5f9",
                      color: "#1e40af",
                      backgroundColor: "#ffffff",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "#eff6ff")}
                    onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "#ffffff")}
                  >
                    {t}
                  </div>
                ))}
              </div>
            )}
          </div>

          <SwapOutlined style={{ color: "#94a3b8", fontSize: 14 }} />

          {/* Destination Table Input */}
          <div style={{ position: "relative" }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                backgroundColor: "#ecfdf5",
                border: "1.5px solid #10b981",
                borderRadius: 8,
                padding: "5px 10px",
              }}
            >
              <span style={{ fontSize: 11, fontWeight: 700, color: "#047857" }}>Destination:</span>
              <input
                type="text"
                placeholder="Type destination table..."
                value={targetSearch}
                onChange={(e) => setTargetSearch(e.target.value)}
                style={{
                  border: "none",
                  outline: "none",
                  backgroundColor: "transparent",
                  fontSize: 12,
                  width: 170,
                  color: "#1e293b",
                  fontWeight: 500,
                }}
              />
              {targetSearch && (
                <button
                  type="button"
                  onClick={() => setTargetSearch("")}
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    color: "#94a3b8",
                    fontSize: 11,
                  }}
                >
                  ✕
                </button>
              )}
            </div>

            {/* Destination Autocomplete Dropdown */}
            {filteredTargetOptions.length > 0 && targetSearch.toLowerCase() !== filteredTargetOptions[0]?.toLowerCase() && (
              <div
                style={{
                  position: "absolute",
                  top: "100%",
                  left: 0,
                  marginTop: 4,
                  backgroundColor: "#ffffff",
                  border: "1px solid #a7f3d0",
                  borderRadius: 8,
                  boxShadow: "0 10px 15px -3px rgba(0,0,0,0.1)",
                  zIndex: 50,
                  width: 240,
                  maxHeight: 180,
                  overflowY: "auto",
                }}
              >
                {filteredTargetOptions.map((t) => (
                  <div
                    key={t}
                    onClick={() => setTargetSearch(t)}
                    style={{
                      padding: "6px 12px",
                      fontSize: 11,
                      fontFamily: "monospace",
                      cursor: "pointer",
                      borderBottom: "1px solid #f1f5f9",
                      color: "#065f46",
                      backgroundColor: "#ffffff",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "#ecfdf5")}
                    onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "#ffffff")}
                  >
                    {t}
                  </div>
                ))}
              </div>
            )}
          </div>

          {(sourceSearch || targetSearch) && (
            <button
              type="button"
              onClick={() => {
                setSourceSearch("");
                setTargetSearch("");
              }}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 4,
                backgroundColor: "#f1f5f9",
                border: "1px solid #cbd5e1",
                borderRadius: 6,
                padding: "5px 10px",
                fontSize: 11,
                cursor: "pointer",
                color: "#475569",
                fontWeight: 600,
              }}
            >
              <ClearOutlined /> Clear Filter
            </button>
          )}
        </div>

        {/* Action Controls: Edit/Wiring Mode, 4-Table Grid Switch, & Fullscreen */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          {/* Edit / Wiring Mode Button */}
          <button
            type="button"
            onClick={() => setIsEditMode(!isEditMode)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "5px 12px",
              fontSize: 12,
              fontWeight: 700,
              borderRadius: 8,
              cursor: "pointer",
              backgroundColor: isEditMode ? "#f59e0b" : "#ffffff",
              color: isEditMode ? "#ffffff" : "#b45309",
              border: isEditMode ? "1px solid #d97706" : "1.5px solid #f59e0b",
              boxShadow: isEditMode ? "0 2px 6px rgba(245, 158, 11, 0.4)" : "none",
            }}
          >
            {isEditMode ? <CheckOutlined /> : <EditOutlined />}
            {isEditMode ? "Editing: Click & Drag (+) Handles" : "Edit / Wire Connections"}
          </button>

          {/* Save & Clear Wires (shown when custom connections exist) */}
          {customAddedEdges.length > 0 && (
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <button
                type="button"
                onClick={handleSaveWireMappings}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  backgroundColor: "#10b981",
                  color: "#ffffff",
                  border: "none",
                  borderRadius: 6,
                  padding: "5px 10px",
                  fontSize: 11,
                  fontWeight: 700,
                  cursor: "pointer",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
                }}
              >
                <PlusCircleOutlined /> Save ({customAddedEdges.length})
              </button>
              <button
                type="button"
                onClick={handleClearCustomWires}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  backgroundColor: "#fee2e2",
                  color: "#dc2626",
                  border: "1px solid #fca5a5",
                  borderRadius: 6,
                  padding: "5px 8px",
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: "pointer",
                }}
                title="Reset custom wired links"
              >
                <DeleteOutlined />
              </button>
            </div>
          )}

          {/* Order layout buttons */}
          <div
            style={{
              display: "flex",
              backgroundColor: "#f1f5f9",
              padding: 3,
              borderRadius: 8,
              border: "1px solid #e2e8f0",
            }}
          >
            <button
              type="button"
              onClick={() => setLayoutMode("grid")}
              style={{
                padding: "4px 10px",
                fontSize: 11,
                fontWeight: 600,
                borderRadius: 6,
                border: "none",
                cursor: "pointer",
                backgroundColor: layoutMode === "grid" ? "#ffffff" : "transparent",
                color: layoutMode === "grid" ? "#0f172a" : "#64748b",
                boxShadow: layoutMode === "grid" ? "0 1px 3px rgba(0,0,0,0.1)" : "none",
              }}
            >
              4-Table Grid
            </button>
            <button
              type="button"
              onClick={() => setLayoutMode("flow")}
              style={{
                padding: "4px 10px",
                fontSize: 11,
                fontWeight: 600,
                borderRadius: 6,
                border: "none",
                cursor: "pointer",
                backgroundColor: layoutMode === "flow" ? "#ffffff" : "transparent",
                color: layoutMode === "flow" ? "#0f172a" : "#64748b",
                boxShadow: layoutMode === "flow" ? "0 1px 3px rgba(0,0,0,0.1)" : "none",
              }}
            >
              Relational Flow
            </button>
          </div>

          {/* Table display density selection */}
          <select
            value={maxDisplayLimit}
            onChange={(e) => setMaxDisplayLimit(Number(e.target.value))}
            style={{
              padding: "4px 8px",
              borderRadius: 6,
              border: "1px solid #cbd5e1",
              fontSize: 11,
              color: "#334155",
              backgroundColor: "#ffffff",
              cursor: "pointer",
            }}
          >
            <option value={20}>Show 20 tables</option>
            <option value={30}>Show 30 tables</option>
            <option value={50}>Show 50 tables</option>
            <option value={100}>Show 100 tables</option>
            <option value={allTableNames.length}>Show All ({allTableNames.length})</option>
          </select>

          {/* Fullscreen Button */}
          <button
            type="button"
            onClick={() => setInternalFullscreen(!internalFullscreen)}
            style={{
              backgroundColor: activeFullscreen ? "#0f172a" : "#ffffff",
              color: activeFullscreen ? "#ffffff" : "#334155",
              border: "1px solid #cbd5e1",
              borderRadius: 8,
              padding: "5px 12px",
              fontSize: 12,
              fontWeight: 600,
              cursor: "pointer",
              boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
            }}
          >
            {activeFullscreen ? "✕ Exit Fullscreen" : "⛶ Expand Full View"}
          </button>
        </div>
      </div>

      {/* Wiring Instruction Banner (When in Edit Mode) */}
      {isEditMode && (
        <div
          style={{
            backgroundColor: "#fef3c7",
            borderBottom: "1px solid #fde68a",
            padding: "6px 16px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            fontSize: 11,
            color: "#92400e",
            fontWeight: 600,
            zIndex: 9,
          }}
        >
          <span>
            ⚡ <strong>Wiring Mode Active:</strong> Click and drag from any column&apos;s green <strong>(+)</strong> handle on the right and drop onto another table&apos;s column handle to connect a foreign key.
          </span>
          <span style={{ fontSize: 10, color: "#b45309" }}>
            New connections will appear in amber dotted lines.
          </span>
        </div>
      )}

      {/* React Flow Canvas */}
      <div style={{ flex: 1, width: "100%", position: "relative" }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={isEditMode ? onConnect : undefined}
          connectionMode={ConnectionMode.Loose}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          minZoom={0.05}
          maxZoom={1.8}
        >
          <Background color="#cbd5e1" gap={24} size={1} />
          <Controls
            style={{
              borderRadius: 8,
              overflow: "hidden",
              boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.1)",
            }}
          />
          <MiniMap
            nodeStrokeWidth={3}
            zoomable
            pannable
            nodeColor={(node: any) =>
              node.data?.isSource
                ? "#3b82f6"
                : node.data?.isTarget
                ? "#10b981"
                : node.data?.highlighted
                ? "#8b5cf6"
                : "#64748b"
            }
            style={{
              backgroundColor: "#ffffff",
              borderRadius: 8,
              border: "1px solid #e2e8f0",
            }}
          />
        </ReactFlow>

        {/* Legend Overlay at bottom-right */}
        <div
          style={{
            position: "absolute",
            bottom: 14,
            right: 14,
            backgroundColor: "rgba(255, 255, 255, 0.95)",
            backdropFilter: "blur(6px)",
            border: "1px solid #e2e8f0",
            borderRadius: 8,
            padding: "8px 14px",
            display: "flex",
            alignItems: "center",
            gap: 14,
            fontSize: 11,
            color: "#475569",
            boxShadow: "0 4px 6px -1px rgba(0,0,0,0.05)",
            pointerEvents: "none",
            zIndex: 10,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", backgroundColor: "#3b82f6" }} />
            <span style={{ fontWeight: 600 }}>Source Point</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", backgroundColor: "#10b981" }} />
            <span style={{ fontWeight: 600 }}>Destination Point</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", backgroundColor: "#f59e0b" }} />
            <span>PK</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", backgroundColor: "#10b981" }} />
            <span>FK</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <span
              style={{
                display: "inline-block",
                width: 16,
                height: 3,
                backgroundColor: "#2563eb",
                borderRadius: 2,
              }}
            />
            <span style={{ fontWeight: 700, color: "#1e40af" }}>Bold Mapping Link</span>
          </div>
          {customAddedEdges.length > 0 && (
            <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <span
                style={{
                  display: "inline-block",
                  width: 16,
                  height: 3,
                  backgroundColor: "#f59e0b",
                  borderRadius: 2,
                }}
              />
              <span style={{ fontWeight: 700, color: "#b45309" }}>Custom Wired</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
