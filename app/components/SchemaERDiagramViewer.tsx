"use client";

import React, { useMemo, useState, useCallback, useEffect, useRef } from "react";
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
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";
import {
  KeyOutlined,
  LinkOutlined,
  DatabaseOutlined,
  SwapOutlined,
  EditOutlined,
  CheckOutlined,
  DeleteOutlined,
  CopyOutlined,
  AimOutlined,
  FullscreenOutlined,
  FullscreenExitOutlined,
  SearchOutlined,
  TableOutlined,
  ApartmentOutlined,
  InfoCircleOutlined,
  CheckSquareOutlined,
  BorderOutlined,
  CloseOutlined,
} from "@ant-design/icons";
import {
  ZoomIn,
  ZoomOut,
  Layers,
  Sparkles,
  Filter,
  Save,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  SlidersHorizontal,
} from "lucide-react";
import { toast } from "react-hot-toast";

interface ColumnItem {
  name: string;
  data_type: string;
  is_primary_key?: boolean;
  is_foreign_key?: boolean;
  is_nullable?: boolean;
  referred_table?: string;
  referred_column?: string;
}

interface TableNodeData {
  tableName: string;
  columns: ColumnItem[];
  tableType?: string;
  isSource?: boolean;
  isTarget?: boolean;
  isSelected?: boolean;
  highlighted?: boolean;
  dimmed?: boolean;
  isEditMode?: boolean;
  isFocused?: boolean;
  searchQuery?: string;
  onFocusNode?: (nodeId: string) => void;
  onSelectNode?: (nodeId: string) => void;
  [key: string]: unknown;
}

// Custom Table Node matching the clean, readable card design
const DatabaseTableNode = ({ id, data }: NodeProps<Node<TableNodeData>>) => {
  const {
    tableName,
    columns = [],
    isSource,
    isTarget,
    isSelected,
    highlighted,
    dimmed,
    isEditMode,
    isFocused,
    searchQuery = "",
    onFocusNode,
    onSelectNode,
  } = data;

  const [expanded, setExpanded] = useState(false);
  const maxInitialColumns = 7;
  const hasMoreColumns = columns.length > maxInitialColumns;
  const visibleColumns = expanded ? columns : columns.slice(0, maxInitialColumns);

  const handleCopyName = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(tableName);
    toast.success(`Copied table "${tableName}"`);
  };

  const handleFocusClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (onFocusNode) {
      onFocusNode(id);
    }
  };

  const handleClick = (e: React.MouseEvent) => {
    if (onSelectNode) {
      onSelectNode(id);
    }
  };

  const borderColor = isSelected
    ? "#0d9488" // Brand Teal
    : isFocused
    ? "#3b82f6"
    : isEditMode
    ? "#f59e0b"
    : isSource
    ? "#2563eb"
    : isTarget
    ? "#10b981"
    : highlighted
    ? "#8b5cf6"
    : "#cbd5e1";

  const pkCount = columns.filter((c) => c.is_primary_key).length;
  const fkCount = columns.filter((c) => c.is_foreign_key).length;

  return (
    <div
      onClick={handleClick}
      style={{
        width: 295,
        backgroundColor: "#ffffff",
        borderRadius: 12,
        border: `2px solid ${borderColor}`,
        boxShadow: isSelected
          ? "0 0 0 4px rgba(13, 148, 136, 0.25), 0 16px 28px -6px rgba(13, 148, 136, 0.2)"
          : isFocused
          ? "0 0 0 4px rgba(59, 130, 246, 0.35), 0 16px 28px -6px rgba(15, 23, 42, 0.2)"
          : isEditMode
          ? "0 12px 24px -6px rgba(245, 158, 11, 0.35)"
          : "0 6px 16px rgba(15, 23, 42, 0.08)",
        overflow: "visible",
        fontSize: 12,
        fontFamily: "var(--font-geist-sans), system-ui, -apple-system, sans-serif",
        opacity: dimmed ? 0.25 : 1,
        cursor: "pointer",
        transition: "all 0.18s cubic-bezier(0.4, 0, 0.2, 1)",
      }}
    >
      {/* Table Header */}
      <div
        style={{
          background: isSelected ? "linear-gradient(135deg, #094a44 0%, #1e293b 100%)" : "#1e293b",
          color: "#ffffff",
          padding: "8px 12px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          borderTopLeftRadius: 10,
          borderTopRightRadius: 10,
          borderBottom: "1px solid rgba(255, 255, 255, 0.1)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0, flex: 1 }}>
          <DatabaseOutlined style={{ fontSize: 13, color: isSelected ? "#5eead4" : "#94a3b8" }} />
          <span
            style={{
              fontWeight: 700,
              fontSize: 12.5,
              fontFamily: "ui-monospace, monospace",
              letterSpacing: "-0.2px",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
              color: "#ffffff",
            }}
            title={tableName}
          >
            {tableName}
          </span>
          {isSource && (
            <span
              style={{
                fontSize: 9,
                fontWeight: 800,
                backgroundColor: "#2563eb",
                color: "#ffffff",
                padding: "1px 5px",
                borderRadius: 4,
                letterSpacing: "0.5px",
                flexShrink: 0,
              }}
            >
              SRC
            </span>
          )}
          {isTarget && (
            <span
              style={{
                fontSize: 9,
                fontWeight: 800,
                backgroundColor: "#16a34a",
                color: "#ffffff",
                padding: "1px 5px",
                borderRadius: 4,
                letterSpacing: "0.5px",
                flexShrink: 0,
              }}
            >
              DEST
            </span>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 4, flexShrink: 0 }}>
          {/* Copy Table Name */}
          <button
            type="button"
            onClick={handleCopyName}
            title="Copy table name"
            style={{
              background: "rgba(255, 255, 255, 0.12)",
              border: "none",
              borderRadius: 4,
              color: "#cbd5e1",
              cursor: "pointer",
              padding: "2px 5px",
              display: "flex",
              alignItems: "center",
              fontSize: 10.5,
            }}
          >
            <CopyOutlined />
          </button>

          {/* Focus Camera on Table */}
          {onFocusNode && (
            <button
              type="button"
              onClick={handleFocusClick}
              title="Center camera on table"
              style={{
                background: "rgba(255, 255, 255, 0.12)",
                border: "none",
                borderRadius: 4,
                color: "#cbd5e1",
                cursor: "pointer",
                padding: "2px 5px",
                display: "flex",
                alignItems: "center",
                fontSize: 10.5,
              }}
            >
              <AimOutlined />
            </button>
          )}

          {/* Column Count Badge */}
          <span
            style={{
              fontSize: 10,
              padding: "2px 6px",
              borderRadius: 9999,
              backgroundColor: "rgba(255, 255, 255, 0.18)",
              color: "#e2e8f0",
              fontWeight: 600,
            }}
          >
            {columns.length} cols
          </span>
        </div>
      </div>

      {/* Subheader summary badge if table has PKs */}
      {pkCount > 0 && (
        <div
          style={{
            backgroundColor: "#fef9c3",
            borderBottom: "1px solid #fef08a",
            padding: "3px 12px",
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 10.5,
            color: "#854d0e",
            fontWeight: 700,
          }}
        >
          <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
            <KeyOutlined style={{ fontSize: 9.5 }} /> {pkCount} PK
          </span>
          {fkCount > 0 && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 3, color: "#065f46", marginLeft: 6 }}>
              <LinkOutlined style={{ fontSize: 9.5 }} /> {fkCount} FK
            </span>
          )}
        </div>
      )}

      {/* Columns List */}
      <div style={{ backgroundColor: "#ffffff" }}>
        {visibleColumns.map((col, idx) => {
          const isPK = Boolean(col.is_primary_key);
          const isFK = Boolean(col.is_foreign_key);
          const isColMatch =
            Boolean(searchQuery.trim()) &&
            col.name.toLowerCase().includes(searchQuery.toLowerCase().trim());

          return (
            <div
              key={col.name || idx}
              style={{
                position: "relative",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "5.5px 12px",
                borderBottom: idx === visibleColumns.length - 1 && !hasMoreColumns ? "none" : "1px solid #f1f5f9",
                backgroundColor: isColMatch
                  ? "#fef08a"
                  : isPK
                  ? "#fef9c3"
                  : idx % 2 === 0
                  ? "#ffffff"
                  : "#fafbfc",
                gap: 8,
              }}
            >
              {/* Left Connector Handle */}
              <Handle
                type="target"
                position={Position.Left}
                id={`${tableName}-${col.name}-target`}
                style={{
                  top: "50%",
                  left: isEditMode ? -8 : -5,
                  width: isEditMode ? 14 : 7,
                  height: isEditMode ? 14 : 7,
                  backgroundColor: isPK ? "#eab308" : "#3b82f6",
                  border: isEditMode ? "2px solid #ffffff" : "1.5px solid #ffffff",
                  borderRadius: "50%",
                  cursor: isEditMode ? "crosshair" : "default",
                  boxShadow: isEditMode ? "0 0 8px rgba(59, 130, 246, 0.8)" : "none",
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
                      fontWeight: 800,
                      color: "#854d0e",
                      backgroundColor: "#fef08a",
                      padding: "1px 5px",
                      borderRadius: 4,
                      border: "1px solid #fde047",
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
                      fontWeight: 800,
                      color: "#047857",
                      backgroundColor: "#d1fae5",
                      padding: "1px 5px",
                      borderRadius: 4,
                      border: "1px solid #a7f3d0",
                    }}
                    title={col.referred_table ? `Foreign Key ➔ ${col.referred_table}` : "Foreign Key"}
                  >
                    <LinkOutlined style={{ fontSize: 9 }} /> FK
                  </span>
                )}
                <span
                  style={{
                    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                    fontSize: 11.5,
                    fontWeight: isPK ? 700 : 500,
                    color: isPK ? "#713f12" : isFK ? "#065f46" : "#1e293b",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                  title={col.name}
                >
                  {col.name}
                </span>
              </div>

              {/* Right Side: Data Type Pill & (+) Connector Handle */}
              <div style={{ display: "flex", alignItems: "center", gap: 6, position: "relative" }}>
                <span
                  style={{
                    fontSize: 9.5,
                    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                    fontWeight: 700,
                    color: "#64748b",
                    backgroundColor: "#f1f5f9",
                    padding: "1px 6px",
                    borderRadius: 4,
                    textTransform: "uppercase",
                    whiteSpace: "nowrap",
                    border: "1px solid #e2e8f0",
                  }}
                >
                  {col.data_type}
                </span>

                {/* Right Handle */}
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
                          width: 20,
                          height: 20,
                          borderRadius: "50%",
                          backgroundColor: "#10b981",
                          border: "2px solid #ffffff",
                          display: "inline-flex",
                          alignItems: "center",
                          justifyContent: "center",
                          cursor: "crosshair",
                          boxShadow: "0 2px 6px rgba(16, 185, 129, 0.6)",
                          zIndex: 30,
                        }
                      : {
                          top: "50%",
                          right: -5,
                          width: 7,
                          height: 7,
                          backgroundColor: isFK ? "#10b981" : "#94a3b8",
                          border: "1.5px solid #ffffff",
                          borderRadius: "50%",
                        }
                  }
                >
                  {isEditMode && (
                    <span
                      style={{
                        fontSize: 12,
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

        {/* Show all columns expander */}
        {hasMoreColumns && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setExpanded(!expanded);
            }}
            style={{
              width: "100%",
              padding: "5px 12px",
              backgroundColor: "#f8fafc",
              border: "none",
              borderTop: "1px solid #f1f5f9",
              borderBottomLeftRadius: 10,
              borderBottomRightRadius: 10,
              color: "#475569",
              fontSize: 10.5,
              fontWeight: 600,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 4,
            }}
          >
            {expanded ? (
              <>Collapse columns ({columns.length})</>
            ) : (
              <>+ Show {columns.length - maxInitialColumns} more columns</>
            )}
          </button>
        )}
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
  onToggleFullscreen?: () => void;
  kbId?: string;
  onSaveCustomMapping?: (newForeignKeys: Array<{ sourceTable: string; sourceColumn: string; targetTable: string; targetColumn: string }>) => void;
  isEditMode?: boolean;
  onEditModeChange?: (isEdit: boolean) => void;
  onClose?: () => void;
}

// Compact Matrix Grid Layout
function getCleanOrderedLayout(nodes: Node[], edges: Edge[], columnsPerRow = 4) {
  const colWidth = 295;
  const colGap = 70;
  const rowGap = 50;

  const rowHeights: number[] = [];

  nodes.forEach((node, index) => {
    const colCount = Math.min((node.data as any)?.columns?.length || 5, 8);
    const estimatedHeight = 55 + colCount * 30;
    const rowIndex = Math.floor(index / columnsPerRow);
    rowHeights[rowIndex] = Math.max(rowHeights[rowIndex] || 0, estimatedHeight);
  });

  const layoutedNodes = nodes.map((node, index) => {
    const rowIndex = Math.floor(index / columnsPerRow);
    const colIndex = index % columnsPerRow;

    let yPos = 40;
    for (let r = 0; r < rowIndex; r++) {
      yPos += (rowHeights[r] || 240) + rowGap;
    }

    const xPos = 40 + colIndex * (colWidth + colGap);

    return {
      ...node,
      position: { x: xPos, y: yPos },
    };
  });

  return { nodes: layoutedNodes, edges };
}

// Dagre Directed Relational Flow
function getDagreLayout(nodes: Node[], edges: Edge[]) {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));

  dagreGraph.setGraph({
    rankdir: "LR",
    nodesep: 80,
    ranksep: 180,
    marginx: 40,
    marginy: 40,
  });

  nodes.forEach((node) => {
    const colCount = Math.min((node.data as any)?.columns?.length || 5, 8);
    const estimatedHeight = 55 + colCount * 30;
    dagreGraph.setNode(node.id, { width: 295, height: estimatedHeight });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    const colCount = Math.min((node.data as any)?.columns?.length || 5, 8);
    const estimatedHeight = 55 + colCount * 30;

    return {
      ...node,
      position: {
        x: (nodeWithPosition?.x || 0) - 145,
        y: (nodeWithPosition?.y || 0) - estimatedHeight / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
}

// Interactive Studio Controller Component
const SchemaERDiagramCanvas: React.FC<{
  tables: Record<string, any>;
  filterQuery: string;
  activeFullscreen: boolean;
  isControlledFullscreen: boolean;
  setToggleFullscreen: () => void;
  kbId: string;
  onSaveCustomMapping?: (newForeignKeys: Array<{ sourceTable: string; sourceColumn: string; targetTable: string; targetColumn: string }>) => void;
  isControlledEditMode?: boolean;
  isEditModeProp?: boolean;
  onEditModeChange?: (isEdit: boolean) => void;
  onClose?: () => void;
}> = ({
  tables,
  filterQuery,
  activeFullscreen,
  isControlledFullscreen,
  setToggleFullscreen,
  kbId,
  onSaveCustomMapping,
  isControlledEditMode,
  isEditModeProp,
  onEditModeChange,
  onClose,
}) => {
  const { fitView, zoomIn, zoomOut, zoomTo, setCenter, getNode } = useReactFlow();

  // Listen for Escape key to exit fullscreen when active
  useEffect(() => {
    if (!activeFullscreen || isControlledFullscreen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setToggleFullscreen();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [activeFullscreen, isControlledFullscreen, setToggleFullscreen]);

  // Trigger resize event when fullscreen mode changes so ReactFlow adjusts cleanly
  useEffect(() => {
    const timer = setTimeout(() => {
      window.dispatchEvent(new Event("resize"));
    }, 150);
    return () => clearTimeout(timer);
  }, [activeFullscreen]);

  const storageKey = `k2b_custom_wiring_${kbId}`;
  const [spotlightSearch, setSpotlightSearch] = useState("");
  const [sourceSearch, setSourceSearch] = useState("");
  const [targetSearch, setTargetSearch] = useState("");
  const [viewMode, setViewMode] = useState<"grid" | "flow">("grid");
  const batchSize = 15;
  const [filterMode, setFilterMode] = useState<"batch" | "connected" | "custom" | "all">("batch");
  const [currentBatchIndex, setCurrentBatchIndex] = useState<number>(0);
  const [isInteractive, setIsInteractive] = useState<boolean>(true);
  const [currentZoomPercent, setCurrentZoomPercent] = useState<number>(100);
  const [showMiniMap, setShowMiniMap] = useState(false);
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);

  // Edit / Studio Mode Toggle
  const [internalEditMode, setInternalEditMode] = useState(false);
  const isEditMode = isControlledEditMode && typeof isEditModeProp === "boolean" ? isEditModeProp : internalEditMode;

  const setIsEditMode = useCallback(
    (next: boolean | ((prev: boolean) => boolean)) => {
      const resolved = typeof next === "function" ? next(isEditMode) : next;
      if (onEditModeChange) {
        onEditModeChange(resolved);
      }
      setInternalEditMode(resolved);
    },
    [isEditMode, onEditModeChange]
  );
  const [leftPanelOpen, setLeftPanelOpen] = useState(true);
  const [rightPanelOpen, setRightPanelOpen] = useState(true);
  const [paletteSearch, setPaletteSearch] = useState("");

  const allTableNames = useMemo(() => Object.keys(tables).sort(), [tables]);
  const totalBatches = Math.max(1, Math.ceil(allTableNames.length / batchSize));

  // Selected tables for Custom Selection
  const [customSelectedTables, setCustomSelectedTables] = useState<Set<string>>(() => {
    return new Set(allTableNames.slice(0, 15));
  });

  // Selected Table for Right Inspector
  const [selectedTableId, setSelectedTableId] = useState<string | null>(() => {
    return allTableNames[0] || null;
  });

  // Compute foreign key maps
  const { fkMap, tableReferredMap, connectedTables } = useMemo(() => {
    const fkMapData: Record<string, Set<string>> = {};
    const tableReferredMapData: Record<string, Record<string, { table: string; col: string }>> = {};
    const connected = new Set<string>();

    Object.entries(tables).forEach(([tblName, tblObj]: [string, any]) => {
      const foreignKeys = tblObj.foreign_keys || [];
      foreignKeys.forEach((fk: any) => {
        const cols = fk.constrained_columns || [];
        const refCols = fk.referred_columns || [];
        if (!fkMapData[tblName]) fkMapData[tblName] = new Set();
        if (!tableReferredMapData[tblName]) tableReferredMapData[tblName] = {};

        cols.forEach((col: string, idx: number) => {
          fkMapData[tblName].add(col);
          tableReferredMapData[tblName][col] = {
            table: fk.referred_table,
            col: refCols[idx] || "id",
          };
        });

        if (fk.referred_table) {
          connected.add(tblName);
          connected.add(fk.referred_table);
        }
      });
    });

    return { fkMap: fkMapData, tableReferredMap: tableReferredMapData, connectedTables: connected };
  }, [tables]);

  // Load custom saved connections from localStorage
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

  // Autocomplete options
  const spotlightOptions = useMemo(() => {
    if (!spotlightSearch.trim()) return [];
    const q = spotlightSearch.toLowerCase().trim();
    return allTableNames.filter((t) => t.toLowerCase().includes(q)).slice(0, 8);
  }, [allTableNames, spotlightSearch]);

  const sourceOptions = useMemo(() => {
    if (!sourceSearch.trim()) return [];
    const q = sourceSearch.toLowerCase().trim();
    return allTableNames.filter((t) => t.toLowerCase().includes(q) && t.toLowerCase() !== q).slice(0, 8);
  }, [allTableNames, sourceSearch]);

  const targetOptions = useMemo(() => {
    if (!targetSearch.trim()) return [];
    const q = targetSearch.toLowerCase().trim();
    return allTableNames.filter((t) => t.toLowerCase().includes(q) && t.toLowerCase() !== q).slice(0, 8);
  }, [allTableNames, targetSearch]);

  const handleSwapSrcDest = () => {
    const temp = sourceSearch;
    setSourceSearch(targetSearch);
    setTargetSearch(temp);
  };

  // Focus and select node
  const handleFocusNode = useCallback(
    (nodeId: string) => {
      setSelectedTableId(nodeId);
      setFocusedNodeId(nodeId);
      const node = getNode(nodeId);
      if (node) {
        setCenter(node.position.x + 145, node.position.y + 120, {
          zoom: 1.0,
          duration: 600,
        });
        toast(`Focused on table "${nodeId}"`, { icon: "🎯" });
      }
      setTimeout(() => {
        setFocusedNodeId(null);
      }, 3000);
    },
    [getNode, setCenter]
  );

  const handleSelectNode = useCallback((nodeId: string) => {
    setSelectedTableId(nodeId);
  }, []);

  // Determine active tables to render based on current filters and density limit
  const activeTablesList = useMemo(() => {
    let list = allTableNames;

    const src = sourceSearch.trim().toLowerCase();
    const tgt = targetSearch.trim().toLowerCase();

    // If source or dest search is active, prioritize matching tables & their connected relationships
    if (src || tgt) {
      const matched = new Set<string>();
      if (src) {
        allTableNames.forEach((t) => {
          if (t.toLowerCase() === src || t.toLowerCase().includes(src)) {
            matched.add(t);
            const fks = tables[t]?.foreign_keys || [];
            fks.forEach((fk: any) => {
              if (fk.referred_table) matched.add(fk.referred_table);
            });
            Object.entries(tables).forEach(([otherTbl, otherObj]: [string, any]) => {
              (otherObj.foreign_keys || []).forEach((fk: any) => {
                if (fk.referred_table === t) matched.add(otherTbl);
              });
            });
          }
        });
      }
      if (tgt) {
        allTableNames.forEach((t) => {
          if (t.toLowerCase() === tgt || t.toLowerCase().includes(tgt)) {
            matched.add(t);
            const fks = tables[t]?.foreign_keys || [];
            fks.forEach((fk: any) => {
              if (fk.referred_table) matched.add(fk.referred_table);
            });
            Object.entries(tables).forEach(([otherTbl, otherObj]: [string, any]) => {
              (otherObj.foreign_keys || []).forEach((fk: any) => {
                if (fk.referred_table === t) matched.add(otherTbl);
              });
            });
          }
        });
      }
      if (matched.size > 0) {
        return Array.from(matched);
      }
    }

    if (filterMode === "connected") {
      list = allTableNames.filter((t) => connectedTables.has(t));
    } else if (filterMode === "custom") {
      list = allTableNames.filter((t) => customSelectedTables.has(t));
    } else if (filterMode === "all") {
      list = allTableNames;
    } else {
      // "batch"
      const start = currentBatchIndex * batchSize;
      list = allTableNames.slice(start, start + batchSize);
    }

    // Keep selectedTableId visible so inspection doesn't disappear
    if (selectedTableId && !list.includes(selectedTableId) && tables[selectedTableId]) {
      return [...list, selectedTableId];
    }

    return list;
  }, [allTableNames, sourceSearch, targetSearch, filterMode, currentBatchIndex, batchSize, connectedTables, customSelectedTables, selectedTableId, tables]);

  // Build Graph Nodes & Edges
  const { initialNodes, initialEdges } = useMemo(() => {
    const nodesList: Node[] = [];
    const edgesList: Edge[] = [];
    const query = filterQuery.toLowerCase().trim();

    const renderSet = new Set(activeTablesList);

    // Build Nodes
    activeTablesList.forEach((tblName) => {
      const tblObj = tables[tblName];
      const rawCols = tblObj?.columns || [];
      const colList: ColumnItem[] = (Array.isArray(rawCols) ? rawCols : Object.values(rawCols)).map(
        (c: any) => ({
          name: c.name,
          data_type: c.data_type,
          is_primary_key: Boolean(c.is_primary_key),
          is_foreign_key: fkMap[tblName]?.has(c.name) ?? false,
          is_nullable: Boolean(c.is_nullable),
          referred_table: tableReferredMap[tblName]?.[c.name]?.table,
          referred_column: tableReferredMap[tblName]?.[c.name]?.col,
        })
      );

      const isSearchMatch = Boolean(query && tblName.toLowerCase().includes(query));
      const isSourceNode = Boolean(
        sourceSearch.trim() && tblName.toLowerCase() === sourceSearch.trim().toLowerCase()
      );
      const isTargetNode = Boolean(
        targetSearch.trim() && tblName.toLowerCase() === targetSearch.trim().toLowerCase()
      );

      nodesList.push({
        id: tblName,
        type: "tableNode",
        position: { x: 0, y: 0 },
        data: {
          tableName: tblName,
          columns: colList,
          tableType: tblObj?.table_type,
          isSource: isSourceNode,
          isTarget: isTargetNode,
          isSelected: selectedTableId === tblName,
          highlighted: isSearchMatch || isSourceNode || isTargetNode,
          dimmed: false,
          isEditMode,
          isFocused: focusedNodeId === tblName,
          searchQuery: query,
          onFocusNode: handleFocusNode,
          onSelectNode: handleSelectNode,
        },
      });
    });

    const edgeColors = ["#0d9488", "#8b5cf6", "#f59e0b", "#059669", "#2563eb", "#ec4899"];

    // Build Curved Edges
    let colorIdx = 0;
    activeTablesList.forEach((tblName) => {
      const tblObj = tables[tblName];
      const foreignKeys = tblObj?.foreign_keys || [];
      foreignKeys.forEach((fk: any, fkIdx: number) => {
        const targetTable = fk.referred_table;
        if (!renderSet.has(targetTable)) return;

        const sourceCols = fk.constrained_columns || [];
        const targetCols = fk.referred_columns || [];
        const srcCol = sourceCols[0] || "";
        const tgtCol = targetCols[0] || "";

        const isSourceTargetLink = Boolean(
          sourceSearch.trim() &&
          targetSearch.trim() &&
          ((tblName.toLowerCase() === sourceSearch.trim().toLowerCase() && targetTable.toLowerCase() === targetSearch.trim().toLowerCase()) ||
           (tblName.toLowerCase() === targetSearch.trim().toLowerCase() && targetTable.toLowerCase() === sourceSearch.trim().toLowerCase()))
        );

        const isDirect = Boolean(
          isSourceTargetLink ||
          (selectedTableId && (tblName === selectedTableId || targetTable === selectedTableId))
        );
        const strokeColor = isSourceTargetLink ? "#2563eb" : isDirect ? "#0d9488" : edgeColors[colorIdx % edgeColors.length];
        colorIdx++;

        const strokeWidth = isSourceTargetLink ? 3.5 : isDirect ? 3 : 2;
        const edgeId = `fk-${tblName}-${srcCol}->${targetTable}-${tgtCol}-${fkIdx}`;

        edgesList.push({
          id: edgeId,
          source: tblName,
          target: targetTable,
          sourceHandle: srcCol ? `${tblName}-${srcCol}-source` : undefined,
          targetHandle: tgtCol ? `${targetTable}-${tgtCol}-target` : undefined,
          type: "default", // Smooth curved Bezier cables
          animated: isDirect || isSourceTargetLink,
          label: `${srcCol} ➔ ${tgtCol}`,
          labelStyle: {
            fill: strokeColor,
            fontWeight: 700,
            fontSize: 10,
          },
          labelBgStyle: {
            fill: "#ffffff",
            fillOpacity: 0.95,
            rx: 6,
            ry: 6,
            stroke: strokeColor,
            strokeWidth: 1,
          },
          labelBgPadding: [6, 3] as [number, number],
          style: {
            stroke: strokeColor,
            strokeWidth,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            width: 14,
            height: 14,
            color: strokeColor,
          },
        });
      });
    });

    customAddedEdges.forEach((edge) => {
      if (renderSet.has(edge.source) && renderSet.has(edge.target)) {
        edgesList.push(edge);
      }
    });

    const columnsPerRow = isEditMode ? 3 : 4;
    const layoutResult =
      viewMode === "grid"
        ? getCleanOrderedLayout(nodesList, edgesList, columnsPerRow)
        : getDagreLayout(nodesList, edgesList);

    return { initialNodes: layoutResult.nodes, initialEdges: layoutResult.edges };
  }, [
    tables,
    filterQuery,
    sourceSearch,
    targetSearch,
    activeTablesList,
    viewMode,
    isEditMode,
    customAddedEdges,
    focusedNodeId,
    selectedTableId,
    fkMap,
    tableReferredMap,
    handleFocusNode,
    handleSelectNode,
  ]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
  }, [initialNodes, initialEdges, setNodes, setEdges]);

  // Auto framing: minZoom: 0.85 ensures crisp readable text immediately!
  useEffect(() => {
    if (nodes.length > 0) {
      const timer = setTimeout(() => {
        fitView({
          padding: 0.16,
          minZoom: 0.82,
          maxZoom: 1.0,
          duration: 400,
        });
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [nodes.length, viewMode, filterMode, currentBatchIndex, isEditMode, fitView]);

  // Wire new foreign key connection
  const onConnect = useCallback(
    (connection: Connection) => {
      const srcHandle = connection.sourceHandle || "";
      const tgtHandle = connection.targetHandle || "";

      const srcCol = srcHandle.split("-")[1] || "fk";
      const tgtCol = tgtHandle.split("-")[1] || "id";

      const newEdge: Edge = {
        id: `custom-fk-${connection.source}-${srcCol}->${connection.target}-${tgtCol}-${Date.now()}`,
        source: connection.source,
        target: connection.target,
        sourceHandle: connection.sourceHandle,
        targetHandle: connection.targetHandle,
        type: "default",
        animated: true,
        label: `NEW: ${srcCol} ➔ ${tgtCol}`,
        labelStyle: {
          fill: "#b45309",
          fontWeight: 800,
          fontSize: 10,
        },
        labelBgStyle: {
          fill: "#fffbeb",
          fillOpacity: 0.95,
          rx: 6,
          ry: 6,
          stroke: "#f59e0b",
          strokeWidth: 1.5,
        },
        style: {
          stroke: "#f59e0b",
          strokeWidth: 2.5,
          strokeDasharray: "4 4",
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 14,
          height: 14,
          color: "#f59e0b",
        },
      };

      setEdges((eds) => addEdge(newEdge, eds));
      setCustomAddedEdges((prev) => [...prev, newEdge]);
      toast.success(`Connected foreign key: ${connection.source}.${srcCol} ➔ ${connection.target}.${tgtCol}`);
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

  // Toggle table in custom selection
  const handleToggleTableCustom = (tblName: string) => {
    setCustomSelectedTables((prev) => {
      const next = new Set(prev);
      if (next.has(tblName)) {
        if (next.size > 1) next.delete(tblName);
        else toast.error("At least one table must remain selected.");
      } else {
        next.add(tblName);
      }
      return next;
    });
  };

  // Selected table info for Right Inspector
  const selectedTableObj = selectedTableId ? tables[selectedTableId] : null;
  const selectedColsRaw = selectedTableObj?.columns || [];
  const selectedColumns: ColumnItem[] = (Array.isArray(selectedColsRaw) ? selectedColsRaw : Object.values(selectedColsRaw)).map((c: any) => ({
    name: c.name,
    data_type: c.data_type,
    is_primary_key: Boolean(c.is_primary_key),
    is_foreign_key: selectedTableId ? fkMap[selectedTableId]?.has(c.name) : false,
    is_nullable: Boolean(c.is_nullable),
    referred_table: selectedTableId ? tableReferredMap[selectedTableId]?.[c.name]?.table : undefined,
    referred_column: selectedTableId ? tableReferredMap[selectedTableId]?.[c.name]?.col : undefined,
  }));
  const selectedForeignKeys = selectedTableObj?.foreign_keys || [];

  return (
    <div
      style={
        activeFullscreen && !isControlledFullscreen
          ? {
              position: "fixed",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              zIndex: 1050,
              backgroundColor: "#faf8f5",
              display: "flex",
              flexDirection: "column",
            }
          : {
              width: "100%",
              height: activeFullscreen ? "100vh" : "calc(86vh - 180px)",
              minHeight: activeFullscreen ? "100vh" : 540,
              backgroundColor: "#faf8f5",
              borderRadius: activeFullscreen ? 0 : 16,
              border: activeFullscreen ? "none" : (isEditMode ? "2px solid #f59e0b" : "1px solid #e7e5df"),
              position: "relative",
              display: "flex",
              flexDirection: "column",
              overflow: "hidden",
              boxShadow: activeFullscreen ? "none" : "0 8px 24px -4px rgba(0, 0, 0, 0.06)",
              transition: "border 0.2s ease",
            }
      }
    >
      {/* ========================================================= */}
      {/* TOP UNIFIED TOOLBAR: Clean, Minimal, Non-Cluttered       */}
      {/* ========================================================= */}
      <div
        style={{
          padding: "8px 16px",
          backgroundColor: isEditMode ? "#fffbeb" : "#ffffff",
          borderBottom: isEditMode ? "1px solid #fde68a" : "1px solid #e7e5df",
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 10,
          zIndex: 20,
          transition: "background 0.2s ease",
        }}
      >
        {/* Left Section: Jump & Batch / Group Selector */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          {/* Jump to table search input */}
          <div style={{ position: "relative" }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                backgroundColor: "#ffffff",
                border: "1px solid #cbd5e1",
                borderRadius: 9999,
                padding: "4px 12px",
                width: 175,
              }}
            >
              <AimOutlined style={{ color: "#64748b", fontSize: 13 }} />
              <input
                type="text"
                placeholder="Jump to table..."
                value={spotlightSearch}
                onChange={(e) => setSpotlightSearch(e.target.value)}
                style={{
                  border: "none",
                  outline: "none",
                  backgroundColor: "transparent",
                  fontSize: 11.5,
                  width: "100%",
                  color: "#1e293b",
                }}
              />
              {spotlightSearch && (
                <button
                  type="button"
                  onClick={() => setSpotlightSearch("")}
                  style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", fontSize: 10 }}
                >
                  ✕
                </button>
              )}
            </div>

            {spotlightOptions.length > 0 && spotlightSearch.toLowerCase() !== spotlightOptions[0]?.toLowerCase() && (
              <div
                style={{
                  position: "absolute",
                  top: "100%",
                  left: 0,
                  marginTop: 4,
                  backgroundColor: "#ffffff",
                  border: "1px solid #e2e8f0",
                  borderRadius: 10,
                  boxShadow: "0 10px 20px rgba(0,0,0,0.12)",
                  zIndex: 50,
                  width: 210,
                  maxHeight: 180,
                  overflowY: "auto",
                }}
              >
                {spotlightOptions.map((t) => (
                  <div
                    key={t}
                    onClick={() => {
                      setSpotlightSearch(t);
                      handleFocusNode(t);
                    }}
                    style={{
                      padding: "6px 12px",
                      fontSize: 11.5,
                      fontFamily: "monospace",
                      cursor: "pointer",
                      borderBottom: "1px solid #f8fafc",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "#f1f5f9")}
                    onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "#ffffff")}
                  >
                    {t}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Table Batch / Group Partition Dropdown */}
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: "#64748b" }}>Show:</span>
            <select
              value={filterMode === "batch" ? `batch_${currentBatchIndex}` : filterMode}
              onChange={(e) => {
                const val = e.target.value;
                if (val.startsWith("batch_")) {
                  setFilterMode("batch");
                  setCurrentBatchIndex(Number(val.replace("batch_", "")));
                } else {
                  setFilterMode(val as any);
                }
              }}
              style={{
                padding: "5px 10px",
                borderRadius: 8,
                border: "1.5px solid #cbd5e1",
                fontSize: 11.5,
                fontWeight: 600,
                color: "#1e293b",
                backgroundColor: "#ffffff",
                cursor: "pointer",
                outline: "none",
              }}
            >
              {/* Batches divided neatly by 15 tables */}
              {Array.from({ length: totalBatches }).map((_, idx) => {
                const start = idx * batchSize + 1;
                const end = Math.min((idx + 1) * batchSize, allTableNames.length);
                return (
                  <option key={`batch_${idx}`} value={`batch_${idx}`}>
                    Tables {start} - {end} ({idx === 0 ? "Recommended" : `Batch ${idx + 1}`})
                  </option>
                );
              })}
              <option value="connected">Connected Tables ({connectedTables.size})</option>
              <option value="custom">Custom Selected ({customSelectedTables.size})</option>
              <option value="all">Show All Tables ({allTableNames.length})</option>
            </select>
          </div>

          {/* Layout Mode Segment: GRID vs FLOW */}
          <div style={{ display: "flex", backgroundColor: "#f1f5f9", padding: "2px", borderRadius: 8, border: "1px solid #e2e8f0" }}>
            <button
              type="button"
              onClick={() => setViewMode("grid")}
              style={{
                padding: "3px 9px",
                fontSize: 11,
                fontWeight: 700,
                borderRadius: 6,
                border: "none",
                cursor: "pointer",
                backgroundColor: viewMode === "grid" ? "#ffffff" : "transparent",
                color: viewMode === "grid" ? "#0f172a" : "#64748b",
                boxShadow: viewMode === "grid" ? "0 1px 2px rgba(0,0,0,0.08)" : "none",
              }}
            >
              Grid
            </button>
            <button
              type="button"
              onClick={() => setViewMode("flow")}
              style={{
                padding: "3px 9px",
                fontSize: 11,
                fontWeight: 700,
                borderRadius: 6,
                border: "none",
                cursor: "pointer",
                backgroundColor: viewMode === "flow" ? "#ffffff" : "transparent",
                color: viewMode === "flow" ? "#0f172a" : "#64748b",
                boxShadow: viewMode === "flow" ? "0 1px 2px rgba(0,0,0,0.08)" : "none",
              }}
            >
              Flow
            </button>
          </div>
        </div>

        {/* Right Section: Edit & Studio Mode Toggle + Fullscreen */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {/* Main Hero Button: EDIT & STUDIO MODE */}
          <button
            type="button"
            onClick={() => {
              const nextState = !isEditMode;
              setIsEditMode(nextState);
              if (nextState) {
                setLeftPanelOpen(true);
                setRightPanelOpen(true);
                toast("Studio & Wiring Mode Enabled! Panels active.", { icon: "⚡" });
              } else {
                toast("Exited Studio Mode. Full view restored.", { icon: "✓" });
              }
            }}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "6px 14px",
              fontSize: 11.5,
              fontWeight: 700,
              borderRadius: 8,
              cursor: "pointer",
              backgroundColor: isEditMode ? "#f59e0b" : "#0d6e65",
              color: "#ffffff",
              border: isEditMode ? "1px solid #d97706" : "1px solid #0f766e",
              boxShadow: isEditMode
                ? "0 2px 8px rgba(245, 158, 11, 0.45)"
                : "0 2px 8px rgba(13, 110, 101, 0.35)",
              transition: "all 0.15s ease",
            }}
          >
            {isEditMode ? <CheckOutlined /> : <EditOutlined />}
            <span>{isEditMode ? "Exit Studio Mode (Done)" : "⚡ Edit & Studio Mode"}</span>
          </button>

          {/* Fullscreen Expansion */}
          <button
            type="button"
            onClick={setToggleFullscreen}
            title={activeFullscreen ? "Exit Fullscreen" : "Fullscreen"}
            style={{
              backgroundColor: "#ffffff",
              color: "#334155",
              border: "1px solid #cbd5e1",
              borderRadius: 8,
              padding: "5px 10px",
              fontSize: 12,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
            }}
          >
            {activeFullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
          </button>

          {/* Close Modal Button (available in fullscreen or edit mode when modal header is hidden) */}
          {(activeFullscreen || isEditMode) && (
            <button
              type="button"
              onClick={() => {
                if (onClose) {
                  onClose();
                } else {
                  setToggleFullscreen();
                }
              }}
              title="Close Diagram (Esc)"
              style={{
                backgroundColor: "#fff1f2",
                color: "#e11d48",
                border: "1px solid #fecdd3",
                borderRadius: 8,
                padding: "5px 10px",
                fontSize: 12,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 4,
              }}
              className="hover:bg-red-100 transition-colors"
            >
              <CloseOutlined style={{ fontSize: 11 }} />
              <span style={{ fontSize: 11, fontWeight: 700 }}>Close</span>
            </button>
          )}
        </div>
      </div>

      {/* Wiring Banner (shown when Studio Mode is active) */}
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
            zIndex: 10,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span>⚡ <strong>Studio Mode Active:</strong> Choose tables from the left palette, drag from column (+) handles to wire foreign keys, and inspect attributes on the right.</span>
          </div>

          {customAddedEdges.length > 0 && (
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <button
                type="button"
                onClick={handleSaveWireMappings}
                style={{
                  backgroundColor: "#0d6e65",
                  color: "#ffffff",
                  border: "none",
                  borderRadius: 6,
                  padding: "3px 10px",
                  fontSize: 11,
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                Save ({customAddedEdges.length}) Wires
              </button>
              <button
                type="button"
                onClick={handleClearCustomWires}
                style={{
                  backgroundColor: "#fee2e2",
                  color: "#dc2626",
                  border: "1px solid #fca5a5",
                  borderRadius: 6,
                  padding: "3px 8px",
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Reset
              </button>
            </div>
          )}
        </div>
      )}

      {/* ========================================================= */}
      {/* WORKSPACE: DYNAMIC 100% CANVAS OR 3-PANEL STUDIO          */}
      {/* ========================================================= */}
      <div style={{ flex: 1, display: "flex", width: "100%", overflow: "hidden", position: "relative" }}>
        {/* ========================================================= */}
        {/* LEFT PANEL: TABLE SELECTOR PALETTE (Shown in Studio Mode) */}
        {/* ========================================================= */}
        {isEditMode && (
          <div
            style={{
              width: leftPanelOpen ? 270 : 0,
              minWidth: leftPanelOpen ? 270 : 0,
              transition: "width 0.22s cubic-bezier(0.4, 0, 0.2, 1)",
              backgroundColor: "#ffffff",
              borderRight: leftPanelOpen ? "1px solid #e7e5df" : "none",
              display: "flex",
              flexDirection: "column",
              overflow: "hidden",
              zIndex: 15,
            }}
          >
            {/* Left Header */}
            <div
              style={{
                padding: "10px 14px",
                borderBottom: "1px solid #f1f3f5",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                backgroundColor: "#fafbfd",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <ApartmentOutlined style={{ color: "#0d9488", fontSize: 13 }} />
                <span style={{ fontWeight: 800, fontSize: 11.5, color: "#1e293b" }}>Table Selector</span>
                <span style={{ fontSize: 10, fontWeight: 700, backgroundColor: "#e0f2fe", color: "#0369a1", padding: "1px 6px", borderRadius: 9999 }}>
                  {activeTablesList.length} shown
                </span>
              </div>
              <button
                type="button"
                onClick={() => setLeftPanelOpen(false)}
                title="Collapse Panel"
                style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", padding: "4px" }}
              >
                <PanelLeftClose size={15} />
              </button>
            </div>

            {/* Palette Search Input */}
            <div style={{ padding: "8px 12px", borderBottom: "1px solid #f8fafc" }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  backgroundColor: "#f8fafc",
                  border: "1px solid #e2e8f0",
                  borderRadius: 6,
                  padding: "4px 8px",
                }}
              >
                <SearchOutlined style={{ color: "#94a3b8", fontSize: 12 }} />
                <input
                  type="text"
                  placeholder="Filter tables..."
                  value={paletteSearch}
                  onChange={(e) => setPaletteSearch(e.target.value)}
                  style={{ border: "none", outline: "none", backgroundColor: "transparent", fontSize: 11, width: "100%" }}
                />
              </div>
            </div>

            {/* Quick Actions in Left Palette */}
            <div style={{ padding: "6px 12px", display: "flex", gap: 5, borderBottom: "1px solid #f1f3f5" }}>
              <button
                type="button"
                onClick={() => {
                  setFilterMode("custom");
                  setCustomSelectedTables(new Set(allTableNames));
                }}
                style={{
                  flex: 1,
                  padding: "3px 6px",
                  fontSize: 10,
                  fontWeight: 700,
                  borderRadius: 5,
                  border: "1px solid #cbd5e1",
                  backgroundColor: "#ffffff",
                  cursor: "pointer",
                }}
              >
                Select All
              </button>
              <button
                type="button"
                onClick={() => {
                  setFilterMode("connected");
                }}
                style={{
                  flex: 1,
                  padding: "3px 6px",
                  fontSize: 10,
                  fontWeight: 700,
                  borderRadius: 5,
                  border: "1px solid #cbd5e1",
                  backgroundColor: "#ffffff",
                  cursor: "pointer",
                }}
              >
                Connected
              </button>
            </div>

            {/* Scrollable Tables List with Selection Checkboxes */}
            <div style={{ flex: 1, overflowY: "auto", padding: "6px" }} className="custom-scrollbar">
              {allTableNames
                .filter((t) => (!paletteSearch.trim() ? true : t.toLowerCase().includes(paletteSearch.toLowerCase().trim())))
                .map((tblName) => {
                  const isShown = activeTablesList.includes(tblName);
                  const isSelected = selectedTableId === tblName;

                  return (
                    <div
                      key={tblName}
                      style={{
                        padding: "6px 10px",
                        borderRadius: 6,
                        marginBottom: 2,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        cursor: "pointer",
                        backgroundColor: isSelected ? "#f0fdfa" : "transparent",
                        border: isSelected ? "1px solid #99f6e4" : "1px solid transparent",
                      }}
                      onClick={() => handleFocusNode(tblName)}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 0, flex: 1 }}>
                        <span
                          onClick={(e) => {
                            e.stopPropagation();
                            setFilterMode("custom");
                            handleToggleTableCustom(tblName);
                          }}
                          style={{ color: isShown ? "#0d9488" : "#cbd5e1", cursor: "pointer", fontSize: 13 }}
                        >
                          {isShown ? <CheckSquareOutlined /> : <BorderOutlined />}
                        </span>
                        <span
                          style={{
                            fontSize: 11,
                            fontFamily: "ui-monospace, monospace",
                            fontWeight: isSelected ? 700 : 500,
                            color: isSelected ? "#0f766e" : "#1e293b",
                            whiteSpace: "nowrap",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                          }}
                        >
                          {tblName}
                        </span>
                      </div>

                      <span style={{ fontSize: 9.5, color: "#64748b", backgroundColor: "#f1f5f9", padding: "1px 5px", borderRadius: 4 }}>
                        {((tables[tblName]?.columns || []).length || Object.keys(tables[tblName]?.columns || {}).length)}c
                      </span>
                    </div>
                  );
                })}
            </div>
          </div>
        )}

        {/* ========================================================= */}
        {/* CENTER AREA: CANVAS & CAMERA HUD                          */}
        {/* ========================================================= */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, position: "relative" }}>
          {/* If left panel was collapsed in edit mode, show a small expand tab */}
          {isEditMode && !leftPanelOpen && (
            <button
              type="button"
              onClick={() => setLeftPanelOpen(true)}
              style={{
                position: "absolute",
                top: 10,
                left: 10,
                zIndex: 20,
                backgroundColor: "#ffffff",
                border: "1.5px solid #0d9488",
                color: "#0f766e",
                borderRadius: 6,
                padding: "4px 8px",
                fontSize: 10.5,
                fontWeight: 700,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 4,
                boxShadow: "0 2px 6px rgba(0,0,0,0.1)",
              }}
            >
              <PanelLeftOpen size={13} />
              <span>Palette</span>
            </button>
          )}

          {/* If right inspector was collapsed in edit mode, show a small expand tab */}
          {isEditMode && !rightPanelOpen && (
            <button
              type="button"
              onClick={() => setRightPanelOpen(true)}
              style={{
                position: "absolute",
                top: 10,
                right: 10,
                zIndex: 20,
                backgroundColor: "#ffffff",
                border: "1.5px solid #0d9488",
                color: "#0f766e",
                borderRadius: 6,
                padding: "4px 8px",
                fontSize: 10.5,
                fontWeight: 700,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 4,
                boxShadow: "0 2px 6px rgba(0,0,0,0.1)",
              }}
            >
              <PanelRightOpen size={13} />
              <span>Inspector</span>
            </button>
          )}

          {/* Canvas Component */}
          <div style={{ flex: 1, width: "100%", position: "relative", backgroundColor: "#faf8f5" }}>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={isEditMode ? onConnect : undefined}
              connectionMode={ConnectionMode.Loose}
              nodeTypes={nodeTypes}
              onNodeClick={(evt, node) => {
                setSelectedTableId(node.id);
                if (isEditMode) setRightPanelOpen(true);
              }}
              onMove={(evt, viewport) => {
                setCurrentZoomPercent(Math.round(viewport.zoom * 100));
              }}
              minZoom={0.2}
              maxZoom={2.0}
            >
              <Background color="#e5e2da" gap={20} size={1} />

              {showMiniMap && (
                <MiniMap
                  nodeStrokeWidth={2}
                  zoomable
                  pannable
                  nodeColor={(node: any) =>
                    node.data?.isSource
                      ? "#2563eb"
                      : node.data?.isTarget
                      ? "#10b981"
                      : "#94a3b8"
                  }
                  style={{
                    backgroundColor: "#ffffff",
                    borderRadius: 8,
                    border: "1px solid #e2e8f0",
                    right: 14,
                    bottom: 14,
                  }}
                />
              )}
            </ReactFlow>

            {/* Floating Camera Dock (HUD) at bottom-left */}
            <div
              style={{
                position: "absolute",
                bottom: 14,
                left: 14,
                backgroundColor: "rgba(255, 255, 255, 0.95)",
                backdropFilter: "blur(8px)",
                border: "1px solid #e2e8f0",
                borderRadius: 10,
                padding: "3px 8px",
                display: "flex",
                alignItems: "center",
                gap: 6,
                boxShadow: "0 6px 16px rgba(0, 0, 0, 0.08)",
                zIndex: 20,
              }}
            >
              <button
                type="button"
                onClick={() => zoomOut({ duration: 200 })}
                title="Zoom Out"
                style={{ background: "none", border: "none", cursor: "pointer", padding: "4px", color: "#475569" }}
              >
                <ZoomOut size={13} />
              </button>
              <span style={{ fontSize: 11, fontWeight: 700, fontFamily: "monospace", color: "#334155", minWidth: 38, textAlign: "center" }}>
                {currentZoomPercent}%
              </span>
              <button
                type="button"
                onClick={() => zoomIn({ duration: 200 })}
                title="Zoom In"
                style={{ background: "none", border: "none", cursor: "pointer", padding: "4px", color: "#475569" }}
              >
                <ZoomIn size={13} />
              </button>
              <div style={{ width: 1, height: 14, backgroundColor: "#e2e8f0" }} />
              <button
                type="button"
                onClick={() => zoomTo(1.0, { duration: 300 })}
                style={{ background: "none", border: "none", cursor: "pointer", fontSize: 10.5, fontWeight: 700, color: "#1e293b" }}
              >
                100%
              </button>
              <button
                type="button"
                onClick={() => fitView({ padding: 0.16, minZoom: 0.82, maxZoom: 1.0, duration: 400 })}
                style={{ background: "none", border: "none", cursor: "pointer", fontSize: 10.5, fontWeight: 700, color: "#0d6e65", display: "flex", alignItems: "center", gap: 3 }}
              >
                <Sparkles size={11} />
                <span>Smart Fit</span>
              </button>
              <div style={{ width: 1, height: 14, backgroundColor: "#e2e8f0" }} />
              <button
                type="button"
                onClick={() => setShowMiniMap(!showMiniMap)}
                title="Toggle MiniMap"
                style={{ background: showMiniMap ? "#eff6ff" : "none", border: "none", cursor: "pointer", padding: "4px", color: showMiniMap ? "#2563eb" : "#64748b" }}
              >
                <Layers size={13} />
              </button>
            </div>
          </div>
        </div>

        {/* ========================================================= */}
        {/* RIGHT PANEL: ENTITY INSPECTOR (Shown in Studio Mode)      */}
        {/* ========================================================= */}
        {isEditMode && (
          <div
            style={{
              width: rightPanelOpen ? 310 : 0,
              minWidth: rightPanelOpen ? 310 : 0,
              transition: "width 0.22s cubic-bezier(0.4, 0, 0.2, 1)",
              backgroundColor: "#ffffff",
              borderLeft: rightPanelOpen ? "1px solid #e7e5df" : "none",
              display: "flex",
              flexDirection: "column",
              overflow: "hidden",
              zIndex: 15,
            }}
          >
            {/* Right Header */}
            <div
              style={{
                padding: "10px 14px",
                borderBottom: "1px solid #f1f3f5",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                backgroundColor: "#fafbfd",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <TableOutlined style={{ color: "#0d9488", fontSize: 13 }} />
                <span style={{ fontWeight: 800, fontSize: 11.5, color: "#1e293b" }}>Entity Inspector</span>
              </div>
              <button
                type="button"
                onClick={() => setRightPanelOpen(false)}
                title="Collapse Panel"
                style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", padding: "4px" }}
              >
                <PanelRightClose size={15} />
              </button>
            </div>

            {/* Inspector Details */}
            <div style={{ flex: 1, overflowY: "auto", padding: "14px" }} className="custom-scrollbar">
              {selectedTableId && selectedTableObj ? (
                <div>
                  <div style={{ marginBottom: 12 }}>
                    <div style={{ fontSize: 9.5, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase" }}>
                      Selected Entity
                    </div>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 2 }}>
                      <span style={{ fontSize: 15, fontWeight: 800, fontFamily: "ui-monospace, monospace", color: "#0f172a" }}>
                        {selectedTableId}
                      </span>
                      <button
                        type="button"
                        onClick={() => handleFocusNode(selectedTableId)}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 3,
                          padding: "2px 7px",
                          fontSize: 10,
                          fontWeight: 700,
                          backgroundColor: "#f0fdfa",
                          color: "#0f766e",
                          border: "1px solid #99f6e4",
                          borderRadius: 6,
                          cursor: "pointer",
                        }}
                      >
                        <AimOutlined />
                        <span>Center</span>
                      </button>
                    </div>
                    <div style={{ display: "flex", gap: 5, marginTop: 5 }}>
                      <span style={{ fontSize: 9.5, padding: "1px 5px", borderRadius: 4, backgroundColor: "#f1f5f9", color: "#475569", fontWeight: 600 }}>
                        {selectedColumns.length} Attributes
                      </span>
                      <span style={{ fontSize: 9.5, padding: "1px 5px", borderRadius: 4, backgroundColor: "#fef3c7", color: "#b45309", fontWeight: 700 }}>
                        {selectedColumns.filter((c) => c.is_primary_key).length} PKs
                      </span>
                      <span style={{ fontSize: 9.5, padding: "1px 5px", borderRadius: 4, backgroundColor: "#d1fae5", color: "#047857", fontWeight: 700 }}>
                        {selectedForeignKeys.length} FK Links
                      </span>
                    </div>
                  </div>

                  {/* Attributes Table */}
                  <div style={{ marginBottom: 14 }}>
                    <div style={{ fontSize: 10.5, fontWeight: 800, color: "#334155", marginBottom: 5 }}>Attributes</div>
                    <div style={{ borderRadius: 6, border: "1px solid #e2e8f0", overflow: "hidden" }}>
                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 10.5 }}>
                        <thead>
                          <tr style={{ backgroundColor: "#f8fafc", borderBottom: "1px solid #e2e8f0", textAlign: "left" }}>
                            <th style={{ padding: "5px 7px", color: "#64748b", fontWeight: 700 }}>Name</th>
                            <th style={{ padding: "5px 7px", color: "#64748b", fontWeight: 700 }}>Type</th>
                            <th style={{ padding: "5px 7px", color: "#64748b", fontWeight: 700, textAlign: "right" }}>Key</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selectedColumns.map((col, idx) => (
                            <tr
                              key={col.name}
                              style={{
                                borderBottom: idx === selectedColumns.length - 1 ? "none" : "1px solid #f1f5f9",
                                backgroundColor: col.is_primary_key ? "#fffbeb" : idx % 2 === 0 ? "#ffffff" : "#fafbfc",
                              }}
                            >
                              <td style={{ padding: "5px 7px", fontFamily: "ui-monospace, monospace", fontWeight: col.is_primary_key ? 700 : 500, color: "#1e293b" }}>
                                {col.name}
                              </td>
                              <td style={{ padding: "5px 7px", color: "#64748b", fontSize: 9.5, fontFamily: "monospace" }}>
                                {col.data_type}
                              </td>
                              <td style={{ padding: "5px 7px", textAlign: "right" }}>
                                {col.is_primary_key && (
                                  <span style={{ fontSize: 8.5, fontWeight: 800, backgroundColor: "#fde68a", color: "#92400e", padding: "1px 4px", borderRadius: 3 }}>
                                    PK
                                  </span>
                                )}
                                {col.is_foreign_key && (
                                  <span style={{ fontSize: 8.5, fontWeight: 800, backgroundColor: "#a7f3d0", color: "#065f46", padding: "1px 4px", borderRadius: 3, marginLeft: 2 }}>
                                    FK
                                  </span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {/* Foreign Key Links */}
                  {selectedForeignKeys.length > 0 && (
                    <div>
                      <div style={{ fontSize: 10.5, fontWeight: 800, color: "#334155", marginBottom: 5 }}>Relationships</div>
                      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                        {selectedForeignKeys.map((fk: any, idx: number) => {
                          const targetTbl = fk.referred_table;
                          const srcCols = (fk.constrained_columns || []).join(", ");
                          const refCols = (fk.referred_columns || []).join(", ");

                          return (
                            <div
                              key={idx}
                              onClick={() => handleFocusNode(targetTbl)}
                              style={{
                                padding: "6px 8px",
                                borderRadius: 6,
                                backgroundColor: "#f8fafc",
                                border: "1px solid #e2e8f0",
                                cursor: "pointer",
                              }}
                            >
                              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 2 }}>
                                <span style={{ fontSize: 10.5, fontWeight: 700, color: "#2563eb", display: "flex", alignItems: "center", gap: 3 }}>
                                  <LinkOutlined />
                                  <span>➔ {targetTbl}</span>
                                </span>
                                <span style={{ fontSize: 9, color: "#94a3b8" }}>Jump ➔</span>
                              </div>
                              <div style={{ fontSize: 9.5, fontFamily: "monospace", color: "#64748b" }}>
                                {srcCols} references {targetTbl}.({refCols})
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div style={{ padding: "30px 10px", textAlign: "center", color: "#94a3b8" }}>
                  <InfoCircleOutlined style={{ fontSize: 20, marginBottom: 6, color: "#cbd5e1" }} />
                  <div style={{ fontSize: 11, fontWeight: 600 }}>Select a table</div>
                  <div style={{ fontSize: 10, marginTop: 2 }}>Click any table to inspect attributes.</div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export const SchemaERDiagramViewer: React.FC<SchemaERDiagramViewerProps> = (props) => {
  const [internalFullscreen, setInternalFullscreen] = useState(false);
  const isControlled = typeof props.isFullscreen === "boolean";
  const activeFullscreen = isControlled ? Boolean(props.isFullscreen) : internalFullscreen;

  const handleToggleFullscreen = () => {
    if (props.onToggleFullscreen) {
      props.onToggleFullscreen();
    } else {
      setInternalFullscreen((prev) => !prev);
    }
  };

  return (
    <ReactFlowProvider>
      <SchemaERDiagramCanvas
        tables={props.tables}
        filterQuery={props.filterQuery || ""}
        activeFullscreen={activeFullscreen}
        isControlledFullscreen={isControlled}
        setToggleFullscreen={handleToggleFullscreen}
        kbId={props.kbId || "default_kb"}
        onSaveCustomMapping={props.onSaveCustomMapping}
        isControlledEditMode={typeof props.isEditMode === "boolean"}
        isEditModeProp={props.isEditMode}
        onEditModeChange={props.onEditModeChange}
        onClose={props.onClose}
      />
    </ReactFlowProvider>
  );
};
