"use client";

import React, { useState, useEffect } from "react";
import {
  Typography,
  Button,
  Card,
  Row,
  Col,
  Input,
  InputNumber,
  Select,
  Modal,
  Tag,
  Space,
  Table,
  Badge,
  Spin,
  Tabs,
  Collapse,
  Tooltip,
  Divider,
  Alert,
  Drawer,
  Statistic,
  Progress,
  Dropdown,
  Empty,
  Popconfirm,
  Radio,
  Segmented,
  Checkbox,
} from "antd";
import {
  DatabaseOutlined,
  PlusOutlined,
  SyncOutlined,
  LoadingOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ThunderboltOutlined,
  SearchOutlined,
  EyeOutlined,
  ApartmentOutlined,
  TableOutlined,
  CodeOutlined,
  FieldTimeOutlined,
  SafetyCertificateOutlined,
  InfoCircleOutlined,
  QuestionCircleOutlined,
  ArrowRightOutlined,
  DeleteOutlined,
  DownloadOutlined,
  CopyOutlined,
  FileTextOutlined,
  BookOutlined,
  DownOutlined,
  FilterOutlined,
  FullscreenOutlined,
  FullscreenExitOutlined,
  KeyOutlined,
  LinkOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import { BsDatabaseFillGear } from "react-icons/bs";
import { marked } from "marked";
import { toast } from "react-hot-toast";
import { getCookie } from "../../config/cookies";
import { API_BASE_URL } from "../../config/config";
import { DatabaseStreamClient, DatabaseStreamEvent } from "../../services/databaseStreamClient";
import { DatabasePipelineProgress } from "../../components/DatabasePipelineProgress";
import { SchemaERDiagramViewer } from "../../components/SchemaERDiagramViewer";

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

interface DBKnowledgebase {
  id: string;
  name: string;
  description: string;
  database_type: string;
  status: string;
  schema_version?: string;
  last_introspected_at?: string;
  created_at: string;
  updated_at: string;
}

interface TableColumn {
  name: string;
  data_type: string;
  is_primary_key: boolean;
  is_nullable: boolean;
  comment?: string;
}

interface TableSchemaInfo {
  table_name: string;
  table_type: string;
  comment?: string;
  columns: TableColumn[];
  primary_key?: { constrained_columns: string[] };
  foreign_keys?: Array<{
    constrained_columns: string[];
    referred_table: string;
    referred_columns: string[];
  }>;
}

interface SchemaSummary {
  table_count: number;
  column_count: number;
  foreign_key_count: number;
  relationship_count: number;
}

interface SchemaResponse {
  database_name: string;
  database_type: string;
  fingerprint: string;
  introspected_at: string;
  summary: SchemaSummary;
  schemas: Record<string, { schema_name: string; tables: Record<string, TableSchemaInfo> }>;
}

interface PipelineTrace {
  query_id: string;
  database_knowledgebase_id: string;
  schema_version: string;
  user_query: string;
  success: boolean;
  total_latency_ms: number;
  error?: string;
  retrieval: {
    retrieved_tables: string[];
    table_scores: Record<string, number>;
    omitted_tables: string[];
    retrieved_columns: Record<string, string[]>;
    selected_relationships: string[];
    latency_ms: number;
  };
  planning: {
    intent: string;
    tables: string[];
    joins: string[];
    filters: string[];
    aggregations: string[];
    group_by: string[];
    order_by: string[];
    limit?: number;
    latency_ms: number;
  };
  sql_generation: {
    candidate_sql: string;
    parameters: Record<string, any>;
    ast_valid: boolean;
    ast_errors: string[];
    ast_warnings: string[];
    repair_attempts: number;
    latency_ms: number;
  };
  execution: {
    executed: boolean;
    row_count: number;
    truncated: boolean;
    execution_time_ms: number;
    column_count: number;
    error?: string;
  };
  synthesis: {
    answer_type: string;
    deterministic: boolean;
    grounding_status: string;
    verification_status: string;
    repair_attempts: number;
    latency_ms: number;
  };
}

interface GroundedAnswer {
  query_id: string;
  database_knowledgebase_id: string;
  schema_version: string;
  answer_text: string;
  answer_type: string;
  grounding_status: string;
  verification_status: string;
  source_columns: string[];
  row_count: number;
  truncated: boolean;
  warnings: string[];
  generation_metadata: Record<string, any>;
  rows: Record<string, any>[];
  columns: string[];
  pipeline_trace?: PipelineTrace;
}

interface OperationalMetrics {
  counts: {
    total_queries: number;
    successful_queries: number;
    failed_queries: number;
    security_rejections: number;
    execution_failures: number;
    timeouts: number;
    grounding_failures: number;
    fallback_count: number;
    llm_usage: number;
    llm_repairs: number;
    result_truncations: number;
  };
  rates: {
    query_success_rate: number;
    query_failure_rate: number;
    security_rejection_rate: number;
    execution_success_rate: number;
    grounding_success_rate: number;
    fallback_rate: number;
    llm_usage_rate: number;
    llm_repair_rate: number;
    result_truncation_rate: number;
    timeout_rate: number;
  };
  latencies_ms: {
    total: { p50: number; p95: number; p99: number; avg: number };
    database_execution: { p50: number; p95: number; p99: number; avg: number };
    llm: { p50: number; p95: number; p99: number; avg: number };
  };
}

interface DBHealthStatus {
  status: string;
  database_connectivity: boolean;
  database_ping_ms: number;
  read_only_enforced: boolean;
  schema_version: string;
  schema_freshness_status: string;
  metrics_summary: any;
  error?: string;
}

interface AuditLogEntry {
  id: string;
  query_id: string;
  request_id?: string;
  schema_version?: string;
  request_timestamp: string;
  sanitized_user_query: string;
  final_status: string;
  total_latency_ms: number;
  retrieval_latency_ms: number;
  planning_latency_ms: number;
  sql_generation_latency_ms: number;
  validation_latency_ms: number;
  database_execution_latency_ms: number;
  result_normalization_latency_ms: number;
  answer_synthesis_latency_ms: number;
  grounding_verification_latency_ms: number;
  row_count: number;
  truncated: boolean;
  column_count: number;
  answer_type: string;
  llm_used: boolean;
  repair_attempts: number;
  ast_valid: boolean;
  grounding_status: string;
  verification_status: string;
  fallback_used: boolean;
  error_type?: string;
  sanitized_error?: string;
  audit_metadata?: any;
}

interface PipelineProgressState {
  is_active: boolean;
  progress_percent: number;
  current_stage?: string;
  current_stage_label?: string;
  status: string;
  error?: string | null;
}

export default function DatabaseKnowledgePage() {
  const [kbList, setKbList] = useState<DBKnowledgebase[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedKb, setSelectedKb] = useState<DBKnowledgebase | null>(null);
  const [pipelineProgressMap, setPipelineProgressMap] = useState<Record<string, PipelineProgressState>>({});

  const pollPipelineStatus = async (kbId: string) => {
    try {
      const res = await fetch(`${API_BASE_URL}/database-knowledgebases/${kbId}/pipeline-status`, {
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setPipelineProgressMap((prev) => ({
          ...prev,
          [kbId]: {
            is_active: data.is_active,
            progress_percent: data.progress_percent || 0,
            current_stage: data.current_stage,
            current_stage_label: data.current_stage_label,
            status: data.status,
            error: data.error,
          },
        }));

        if (data.is_active) {
          setTimeout(() => pollPipelineStatus(kbId), 3000);
        } else if (data.status === "succeeded" || data.status === "succeeded_with_warnings") {
          await fetchKnowledgebases();
        }
      }
    } catch (e) {
      console.error("Failed to poll pipeline status:", e);
    }
  };

  // Connection Modal state
  const [modalOpen, setModalOpen] = useState(false);
  const [testLoading, setTestLoading] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; latency_ms?: number; message?: string } | null>(null);

  // Form State
  const [formDbType, setFormDbType] = useState<"postgresql" | "mariadb" | "mysql">("postgresql");
  const [formName, setFormName] = useState("HRMS Enterprise Database (Demo)");

  const handleDbTypeChange = (newType: "postgresql" | "mariadb" | "mysql") => {
    setFormDbType(newType);
    if (newType === "mariadb" || newType === "mysql") {
      if (formPort === 5432 || formPort === 5433) {
        setFormPort(3306);
      }
    } else if (newType === "postgresql") {
      if (formPort === 3306 || formPort === 3307) {
        setFormPort(5432);
      }
    }
  };
  const [formDesc, setFormDesc] = useState("14-table HRMS demo database covering employees, departments, payroll, attendance, and projects");
  const [formHost, setFormHost] = useState("localhost");
  const [formPort, setFormPort] = useState(5433);
  const [formDbName, setFormDbName] = useState("gsearch_hrms_demo_db");
  const [formUser, setFormUser] = useState("test_ro_user");
  const [formPassword, setFormPassword] = useState("test_ro_password");
  const [formSsl, setFormSsl] = useState("disable");

  // Schema Explorer state
  const [schemaModalOpen, setSchemaModalOpen] = useState(false);
  const [schemaLoading, setSchemaLoading] = useState(false);
  const [schemaData, setSchemaData] = useState<SchemaResponse | null>(null);
  const [schemaSearchQuery, setSchemaSearchQuery] = useState("");
  const [schemaViewMode, setSchemaViewMode] = useState<"list" | "diagram">("diagram");
  const [schemaFullscreen, setSchemaFullscreen] = useState(false);
  const [schemaEditMode, setSchemaEditMode] = useState(false);
  const isDiagramHeaderHidden = (schemaFullscreen || schemaEditMode) && schemaViewMode === "diagram";

  function getAuthHeaders() {
    const token = getCookie("AUTH_TOKEN");
    return {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    };
  }

  // Table view custom names & expansion state
  const [expandedTableKeys, setExpandedTableKeys] = useState<string[]>([]);
  const [tableCustomNames, setTableCustomNames] = useState<Record<string, string[]>>({});
  const [newTableTagInput, setNewTableTagInput] = useState<Record<string, string>>({});
  const [columnCustomNames, setColumnCustomNames] = useState<Record<string, Record<string, string[]>>>({});
  const [newColumnTagInput, setNewColumnTagInput] = useState<Record<string, string>>({});
  const [aliasNotesModalOpen, setAliasNotesModalOpen] = useState(false);
  const [aliasNotesSearch, setAliasNotesSearch] = useState("");

  // Compute grouped alternative names summary for preview & export
  const getAliasSummaryList = () => {
    // Gather all table names from schemaData or tableCustomNames or columnCustomNames
    const allTableNamesSet = new Set<string>();
    Object.keys(tableCustomNames || {}).forEach((t) => allTableNamesSet.add(t));
    Object.keys(columnCustomNames || {}).forEach((t) => allTableNamesSet.add(t));
    if (schemaData?.schemas) {
      Object.values(schemaData.schemas).forEach((s: any) => {
        if (s?.tables) Object.keys(s.tables).forEach((t) => allTableNamesSet.add(t));
      });
    }

    const items: Array<{
      tableName: string;
      tableAliases: string[];
      columnAliases: Array<{ columnName: string; aliases: string[] }>;
    }> = [];

    allTableNamesSet.forEach((tableName) => {
      const tAliases = (tableCustomNames[tableName] || []).filter(Boolean);
      const colsMap = columnCustomNames[tableName] || {};
      const colAliasesList: Array<{ columnName: string; aliases: string[] }> = [];

      Object.entries(colsMap).forEach(([colName, aList]) => {
        const cleanAliases = (aList || []).filter(Boolean);
        if (cleanAliases.length > 0) {
          colAliasesList.push({ columnName: colName, aliases: cleanAliases });
        }
      });

      // Include if table has alternative names OR any columns have alternative names
      if (tAliases.length > 0 || colAliasesList.length > 0) {
        items.push({
          tableName,
          tableAliases: tAliases,
          columnAliases: colAliasesList,
        });
      }
    });

    items.sort((a, b) => a.tableName.localeCompare(b.tableName));
    return items;
  };

  const handleDownloadAliasNotes = (format: "json" | "txt" = "txt") => {
    const list = getAliasSummaryList();
    if (list.length === 0) {
      toast.error("No alternative names have been added yet to download.");
      return;
    }

    const kbTitle = selectedKb?.name || "Database";
    const timestamp = new Date().toISOString().replace(/[:.]/g, "-");

    if (format === "json") {
      const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(list, null, 2));
      const downloadAnchor = document.createElement("a");
      downloadAnchor.setAttribute("href", dataStr);
      downloadAnchor.setAttribute("download", `${kbTitle}_alternative_names_${timestamp}.json`);
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      downloadAnchor.remove();
      toast.success("Downloaded alternative names JSON successfully!");
      return;
    }

    // Formatted Text / Instructions format
    let doc = `====================================================================\n`;
    doc += `       ALTERNATIVE NAMES DICTIONARY & NOTES PREVIEW                 \n`;
    doc += ` Knowledgebase: ${kbTitle}\n`;
    doc += ` Generated On : ${new Date().toLocaleString()}\n`;
    doc += ` Total Configured Tables: ${list.length}\n`;
    doc += `====================================================================\n\n`;
    doc += `GUIDE & INSTRUCTIONS:\n`;
    doc += `  • When end-users or queries ask about an alternative table or column name,\n`;
    doc += `    GSearchAI maps it accurately to the corresponding original database entity.\n\n`;
    doc += `--------------------------------------------------------------------\n`;

    list.forEach((item, idx) => {
      doc += `\n[${idx + 1}] TABLE: ${item.tableName}`;
      if (item.tableAliases.length > 0) {
        doc += `  --> Alternative Name(s): ${item.tableAliases.join(", ")}\n`;
      } else {
        doc += `  (No alternative table name set, original table name used)\n`;
      }

      if (item.columnAliases.length > 0) {
        doc += `    Under this table, the following alternative column names are defined:\n`;
        item.columnAliases.forEach((c) => {
          doc += `      • Column: "${c.columnName}" --> Alternative Word(s): ${c.aliases.join(", ")}\n`;
        });
      } else {
        doc += `    (No alternative column names defined for this table)\n`;
      }
      doc += `--------------------------------------------------------------------\n`;
    });

    const dataBlob = new Blob([doc], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(dataBlob);
    const downloadAnchor = document.createElement("a");
    downloadAnchor.setAttribute("href", url);
    downloadAnchor.setAttribute("download", `${kbTitle}_alternative_names_${timestamp}.txt`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
    URL.revokeObjectURL(url);
    toast.success("Downloaded alternative names notes successfully!");
  };

  // Load table aliases from PostgreSQL DB API with localStorage fallback
  useEffect(() => {
    if (typeof window !== "undefined" && selectedKb?.id) {
      try {
        const saved = localStorage.getItem(`k2b_table_names_${selectedKb.id}`);
        if (saved) {
          setTableCustomNames(JSON.parse(saved));
        }
      } catch (err) {
        console.error("Failed to load saved table names:", err);
      }

      // Fetch persistent table aliases from backend PostgreSQL API
      fetch(`${API_BASE_URL}/database-knowledgebases/${selectedKb.id}/table-aliases`, {
        headers: getAuthHeaders(),
      })
        .then((res) => (res.ok ? res.json() : null))
        .then((json) => {
          if (json && json.table_aliases) {
            setTableCustomNames(json.table_aliases);
            localStorage.setItem(`k2b_table_names_${selectedKb.id}`, JSON.stringify(json.table_aliases));
          }
        })
        .catch((err) => console.warn("Failed to load table aliases from server:", err));

      // Fetch persistent column aliases from backend PostgreSQL API with localStorage cache
      try {
        const savedCol = localStorage.getItem(`k2b_col_names_${selectedKb.id}`);
        if (savedCol) setColumnCustomNames(JSON.parse(savedCol));
      } catch (e) {}

      fetch(`${API_BASE_URL}/database-knowledgebases/${selectedKb.id}/column-aliases`, {
        headers: getAuthHeaders(),
      })
        .then((res) => (res.ok ? res.json() : null))
        .then((json) => {
          if (json && json.column_aliases) {
            setColumnCustomNames(json.column_aliases);
            localStorage.setItem(`k2b_col_names_${selectedKb.id}`, JSON.stringify(json.column_aliases));
          }
        })
        .catch((err) => console.warn("Failed to load column aliases from server:", err));
    }
    if (selectedKb?.id) {
      fetch(`${API_BASE_URL}/database-knowledgebases/${selectedKb.id}/schema`, {
        headers: getAuthHeaders(),
      })
        .then((res) => (res.ok ? res.json() : null))
        .then((json) => {
          if (json) {
            const raw = json.schema_data || json;
            const tbls: string[] = [];
            if (raw.schemas) {
              Object.values(raw.schemas).forEach((s: any) => {
                if (s && s.tables) {
                  tbls.push(...Object.keys(s.tables));
                }
              });
            } else if (raw.tables) {
              tbls.push(...Object.keys(raw.tables));
            }
            if (tbls.length > 0) {
              setAllDbTablesList(Array.from(new Set(tbls)).sort());
            }
          }
        })
        .catch((e) => console.warn("Failed to load schema for search:", e));
    }
  }, [selectedKb?.id]);

  // Handle Escape key to cleanly exit fullscreen or edit mode schema modal
  useEffect(() => {
    if ((!schemaFullscreen && !schemaEditMode) || !schemaModalOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setSchemaFullscreen(false);
        setSchemaEditMode(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [schemaFullscreen, schemaEditMode, schemaModalOpen]);

  const handleAddTableName = (tableName: string, nameToAdd?: string) => {
    const text = (nameToAdd || newTableTagInput[tableName] || "").trim();
    if (!text) return;

    setTableCustomNames((prev) => {
      const existingList = prev[tableName] || [];
      if (existingList.includes(text)) {
        toast.error(`"${text}" already exists for table "${tableName}".`);
        return prev;
      }
      const updatedList = [...existingList, text];
      const nextState = {
        ...prev,
        [tableName]: updatedList,
      };
      if (selectedKb?.id) {
        localStorage.setItem(`k2b_table_names_${selectedKb.id}`, JSON.stringify(nextState));
        // Auto-persist to backend so aliases are active immediately without requiring Save button
        fetch(`${API_BASE_URL}/database-knowledgebases/${selectedKb.id}/table-aliases`, {
          method: "POST",
          headers: getAuthHeaders(),
          body: JSON.stringify({
            table_name: tableName,
            aliases: updatedList,
          }),
        })
          .then((res) => {
            if (res.ok) {
              toast.success(`Saved alternative name "${text}" for "${tableName}" in AI Knowledgebase!`);
            }
          })
          .catch((err) => console.warn("Failed to auto-sync alias to server:", err));
      }
      return nextState;
    });
    setNewTableTagInput((prev) => ({ ...prev, [tableName]: "" }));
  };

  const handleRemoveTableSingleName = async (tableName: string, nameToRemove: string) => {
    const existingList = tableCustomNames[tableName] || [];
    const updatedList = existingList.filter((n) => n !== nameToRemove);
    const nextState = {
      ...tableCustomNames,
      [tableName]: updatedList,
    };
    setTableCustomNames(nextState);
    if (selectedKb?.id) {
      localStorage.setItem(`k2b_table_names_${selectedKb.id}`, JSON.stringify(nextState));
      try {
        await fetch(`${API_BASE_URL}/database-knowledgebases/${selectedKb.id}/table-aliases`, {
          method: "POST",
          headers: getAuthHeaders(),
          body: JSON.stringify({
            table_name: tableName,
            aliases: updatedList,
          }),
        });
      } catch (err) {
        console.warn("Failed to sync alias deletion to server:", err);
      }
    }
    toast.success(`Removed "${nameToRemove}" from "${tableName}"`);
  };

  const handleSaveTableName = async (tableName: string) => {
    const pendingText = (newTableTagInput[tableName] || "").trim();
    let currentNames = tableCustomNames[tableName] || [];
    if (pendingText && !currentNames.includes(pendingText)) {
      currentNames = [...currentNames, pendingText];
      setNewTableTagInput((prev) => ({ ...prev, [tableName]: "" }));
    }
    const nextState = {
      ...tableCustomNames,
      [tableName]: currentNames,
    };
    setTableCustomNames(nextState);
    if (selectedKb?.id) {
      localStorage.setItem(`k2b_table_names_${selectedKb.id}`, JSON.stringify(nextState));
      try {
        const res = await fetch(`${API_BASE_URL}/database-knowledgebases/${selectedKb.id}/table-aliases`, {
          method: "POST",
          headers: getAuthHeaders(),
          body: JSON.stringify({
            table_name: tableName,
            aliases: currentNames,
          }),
        });
        if (res.ok) {
          toast.success(`Saved alternative names for "${tableName}" in AI Knowledgebase!`);
          return;
        }
      } catch (err) {
        console.warn("Failed to save table aliases to server:", err);
      }
    }
    toast.success(`Saved names for table "${tableName}" successfully!`);
  };

  const handleClearTableNames = async (tableName: string) => {
    const nextState = {
      ...tableCustomNames,
      [tableName]: [],
    };
    setTableCustomNames(nextState);
    setNewTableTagInput((prev) => ({ ...prev, [tableName]: "" }));
    if (selectedKb?.id) {
      localStorage.setItem(`k2b_table_names_${selectedKb.id}`, JSON.stringify(nextState));
      try {
        await fetch(`${API_BASE_URL}/database-knowledgebases/${selectedKb.id}/table-aliases/${encodeURIComponent(tableName)}`, {
          method: "DELETE",
          headers: getAuthHeaders(),
        });
      } catch (err) {
        console.warn("Failed to delete table alias from server:", err);
      }
    }
    toast.success(`Removed names for table "${tableName}"`);
  };

  const handleAddColumnName = (tableName: string, columnName: string, nameToAdd?: string) => {
    const tagKey = `${tableName}.${columnName}`;
    const text = (nameToAdd || newColumnTagInput[tagKey] || "").trim();
    if (!text) return;

    // Validate NO DUPLICATE aliases across ANY column in the database
    const textLower = text.toLowerCase();
    for (const [tbl, cols] of Object.entries(columnCustomNames)) {
      for (const [col, aliases] of Object.entries(cols || {})) {
        if (aliases.some((a) => a.toLowerCase() === textLower)) {
          if (tbl === tableName && col === columnName) {
            toast.error(`"${text}" already exists for ${tableName}.${columnName}.`);
          } else {
            toast.error(`"${text}" is already assigned to "${tbl}.${col}". Duplicates are not allowed across columns!`);
          }
          return;
        }
      }
    }

    setColumnCustomNames((prev) => {
      const tblCols = prev[tableName] || {};
      const existingList = tblCols[columnName] || [];
      const updatedList = [...existingList, text];
      const nextState = {
        ...prev,
        [tableName]: {
          ...tblCols,
          [columnName]: updatedList,
        },
      };

      if (selectedKb?.id) {
        localStorage.setItem(`k2b_col_names_${selectedKb.id}`, JSON.stringify(nextState));
        fetch(`${API_BASE_URL}/database-knowledgebases/${selectedKb.id}/column-aliases`, {
          method: "POST",
          headers: getAuthHeaders(),
          body: JSON.stringify({
            table_name: tableName,
            column_name: columnName,
            aliases: updatedList,
          }),
        })
          .then(async (res) => {
            if (res.ok) {
              toast.success(`Saved column alias "${text}" for ${tableName}.${columnName}!`);
            } else {
              const errJson = await res.json().catch(() => ({}));
              toast.error(errJson.detail || "Failed to save column alias.");
            }
          })
          .catch((err) => console.warn("Failed to save column alias:", err));
      }

      return nextState;
    });

    setNewColumnTagInput((prev) => ({ ...prev, [tagKey]: "" }));
  };

  const handleRemoveColumnSingleName = async (tableName: string, columnName: string, nameToRemove: string) => {
    const tagKey = `${tableName}.${columnName}`;
    const tblCols = columnCustomNames[tableName] || {};
    const existingList = tblCols[columnName] || [];
    const updatedList = existingList.filter((n) => n !== nameToRemove);

    const nextState = {
      ...columnCustomNames,
      [tableName]: {
        ...tblCols,
        [columnName]: updatedList,
      },
    };
    setColumnCustomNames(nextState);

    if (selectedKb?.id) {
      localStorage.setItem(`k2b_col_names_${selectedKb.id}`, JSON.stringify(nextState));
      try {
        await fetch(`${API_BASE_URL}/database-knowledgebases/${selectedKb.id}/column-aliases`, {
          method: "POST",
          headers: getAuthHeaders(),
          body: JSON.stringify({
            table_name: tableName,
            column_name: columnName,
            aliases: updatedList,
          }),
        });
        toast.success(`Removed "${nameToRemove}" from ${tableName}.${columnName}`);
      } catch (err) {
        console.warn("Failed to sync column alias removal:", err);
      }
    }
  };

  // Query Agent State
  const [userQuery, setUserQuery] = useState("");
  const [queryLoading, setQueryLoading] = useState(false);
  const [groundedAnswer, setGroundedAnswer] = useState<GroundedAnswer | null>(null);
  const [tableFilter, setTableFilter] = useState("");
  const [answerViewMode, setAnswerViewMode] = useState<"formatted" | "raw">("formatted");
  const [copiedAnswer, setCopiedAnswer] = useState(false);
  const [observabilityOpen, setObservabilityOpen] = useState(false);
  const [streamEvents, setStreamEvents] = useState<DatabaseStreamEvent[]>([]);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [isCancelled, setIsCancelled] = useState<boolean>(false);
  const [abortController, setAbortController] = useState<AbortController | null>(null);
  const [disambiguationData, setDisambiguationData] = useState<{ message: string; options: any[]; entity_type?: string; candidate_tables?: any[]; all_tables?: string[]; table_aliases?: Record<string, string[]> } | null>(null);
  const [selectedTablesForExecution, setSelectedTablesForExecution] = useState<string[]>([]);
  const [multiTableStrategy, setMultiTableStrategy] = useState<"separate" | "union">("separate");
  const [tableSearchFilter, setTableSearchFilter] = useState<string>('');
  const [allDbTablesList, setAllDbTablesList] = useState<string[]>([]);

  // Phase 3B Tabs & Observability State
  const [activeTab, setActiveTab] = useState<string>("query");
  const [metricsData, setMetricsData] = useState<OperationalMetrics | null>(null);
  const [healthData, setHealthData] = useState<DBHealthStatus | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditPage, setAuditPage] = useState(1);
  const [auditStatusFilter, setAuditStatusFilter] = useState<string>("ALL");
  const [auditLoading, setAuditLoading] = useState(false);
  const [inspectedTrace, setInspectedTrace] = useState<any>(null);

  const fetchKnowledgebases = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/database-knowledgebases`, {
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        const json = await res.json();
        const data = json.data || [];
        setKbList(data);
        if (data.length > 0 && !selectedKb) {
          setSelectedKb(data[0]);
        }
      } else {
        toast.error("Failed to load database knowledgebases.");
      }
    } catch (err) {
      console.error(err);
      toast.error("Network error while loading knowledgebases.");
    } finally {
      setLoading(false);
    }
  };

  const fetchMetricsAndHealth = async (kbId: string) => {
    setMetricsLoading(true);
    try {
      const [mRes, hRes] = await Promise.all([
        fetch(`${API_BASE_URL}/database-knowledgebases/${kbId}/metrics`, { headers: getAuthHeaders() }),
        fetch(`${API_BASE_URL}/database-knowledgebases/${kbId}/health`, { headers: getAuthHeaders() }),
      ]);
      if (mRes.ok) {
        const mJson = await mRes.json();
        setMetricsData(mJson.data);
      }
      if (hRes.ok) {
        const hJson = await hRes.json();
        setHealthData(hJson);
      }
    } catch (err) {
      console.error("Failed to load metrics/health:", err);
    } finally {
      setMetricsLoading(false);
    }
  };

  const fetchAuditLogs = async (kbId: string, page = 1, status = "ALL") => {
    setAuditLoading(true);
    try {
      const offset = (page - 1) * 20;
      let url = `${API_BASE_URL}/database-knowledgebases/${kbId}/audit-logs?limit=20&offset=${offset}`;
      if (status !== "ALL") {
        url += `&final_status=${status}`;
      }
      const res = await fetch(url, { headers: getAuthHeaders() });
      if (res.ok) {
        const json = await res.json();
        setAuditLogs(json.items || []);
        setAuditTotal(json.total || 0);
        setAuditPage(page);
      }
    } catch (err) {
      console.error("Failed to load audit logs:", err);
    } finally {
      setAuditLoading(false);
    }
  };

  useEffect(() => {
    fetchKnowledgebases();
  }, []);

  useEffect(() => {
    if (kbList.length > 0) {
      kbList.forEach((kb) => {
        pollPipelineStatus(kb.id);
      });
    }
  }, [kbList.map((k) => k.id).join(",")]);

  useEffect(() => {
    if (selectedKb) {
      fetchMetricsAndHealth(selectedKb.id);
      fetchAuditLogs(selectedKb.id, 1, auditStatusFilter);
    }
    if (selectedKb?.id) {
      fetch(`${API_BASE_URL}/database-knowledgebases/${selectedKb.id}/schema`, {
        headers: getAuthHeaders(),
      })
        .then((res) => (res.ok ? res.json() : null))
        .then((json) => {
          if (json) {
            const raw = json.schema_data || json;
            const tbls: string[] = [];
            if (raw.schemas) {
              Object.values(raw.schemas).forEach((s: any) => {
                if (s && s.tables) {
                  tbls.push(...Object.keys(s.tables));
                }
              });
            } else if (raw.tables) {
              tbls.push(...Object.keys(raw.tables));
            }
            if (tbls.length > 0) {
              setAllDbTablesList(Array.from(new Set(tbls)).sort());
            }
          }
        })
        .catch((e) => console.warn("Failed to load schema for search:", e));
    }
  }, [selectedKb?.id]);

  const handleTestConnection = async () => {
    setTestLoading(true);
    setTestResult(null);
    try {
      const res = await fetch(`${API_BASE_URL}/database-knowledgebases/test-connection-adhoc`, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({
          db_type: formDbType,
          host: formHost,
          port: formPort,
          database_name: formDbName,
          username: formUser,
          password: formPassword,
          ssl_mode: formSsl,
        }),
      });
      const data = await res.json();
      if (res.ok && data.success) {
        setTestResult({
          success: true,
          latency_ms: data.latency_ms,
          message: `Connected successfully (${data.latency_ms?.toFixed(1)} ms).`,
        });
        toast.success(`Connection verified (${data.latency_ms?.toFixed(1)} ms)`);
      } else {
        setTestResult({
          success: false,
          message: data.error_message || "Connection failed. Please check host, port, credentials, and SSL mode.",
        });
        toast.error("Connection failed.");
      }
    } catch (err: any) {
      setTestResult({ success: false, message: err.message || "Network error" });
      toast.error("Connection test failed.");
    } finally {
      setTestLoading(false);
    }
  };

  const handleSaveConnection = async () => {
    if (!formName.trim()) {
      toast.error("Please provide a database knowledgebase name.");
      return;
    }
    setSaveLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/database-knowledgebases`, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({
          name: formName,
          description: formDesc,
          connection: {
            db_type: formDbType,
            host: formHost,
            port: formPort,
            database_name: formDbName,
            username: formUser,
            password: formPassword,
            ssl_mode: formSsl,
          },
        }),
      });
      if (res.ok) {
        toast.success("Database Knowledgebase registered successfully!");
        setModalOpen(false);
        await fetchKnowledgebases();
      } else {
        const err = await res.json();
        toast.error(err.detail || "Failed to create database knowledgebase.");
      }
    } catch (err: any) {
      toast.error(err.message || "Failed to create database knowledgebase.");
    } finally {
      setSaveLoading(false);
    }
  };

  const handleSyncSchema = async (kbId: string) => {
    setLoading(true);
    setPipelineProgressMap((prev) => ({
      ...prev,
      [kbId]: {
        is_active: true,
        progress_percent: 5,
        current_stage_label: "Introspecting schema and catalogs...",
        status: "running",
      },
    }));
    try {
      const res = await fetch(`${API_BASE_URL}/database-knowledgebases/${kbId}/introspect`, {
        method: "POST",
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        toast.success("Database schema synchronized! Starting Phase 2 knowledge processing...");
        await fetchKnowledgebases();
        try {
          fetch(`${API_BASE_URL}/database-knowledgebases/${kbId}/knowledge/pipeline/run?force_recompute=true&run_inline=false`, {
            method: "POST",
            headers: getAuthHeaders(),
          }).catch(() => {});
        } catch {}
        pollPipelineStatus(kbId);
      } else {
        const err = await res.json();
        toast.error(err.detail || "Schema introspection failed.");
        setPipelineProgressMap((prev) => ({
          ...prev,
          [kbId]: {
            is_active: false,
            progress_percent: 0,
            current_stage_label: "Introspection failed",
            status: "failed",
          },
        }));
      }
    } catch (err: any) {
      toast.error(err.message || "Schema introspection error.");
      setPipelineProgressMap((prev) => ({
        ...prev,
        [kbId]: {
          is_active: false,
          progress_percent: 0,
          current_stage_label: "Introspection error",
          status: "failed",
        },
      }));
    } finally {
      setLoading(false);
    }
  };

  const confirmDeleteDatabase = (kb: DBKnowledgebase) => {
    Modal.confirm({
      title: (
        <div className="flex items-center gap-2 text-red-500 font-semibold text-base">
          <DeleteOutlined />
          <span>Delete Connected Database</span>
        </div>
      ),
      content: (
        <div className="py-2">
          <p className="text-sm text-[var(--app-text)] font-medium">
            Are you sure you want to delete &quot;{kb.name}&quot;?
          </p>
          <p className="text-xs text-gray-400 mt-2 leading-relaxed">
            This action will disconnect the database from GraphMind, remove its catalog registration, and delete its indexed canonical schema snapshot.
          </p>
        </div>
      ),
      okText: "Delete Database",
      okButtonProps: { danger: true },
      cancelText: "Cancel",
      onOk: async () => {
        try {
          const res = await fetch(`${API_BASE_URL}/database-knowledgebases/${kb.id}`, {
            method: "DELETE",
            headers: getAuthHeaders(),
          });
          if (res.ok) {
            toast.success(`Database "${kb.name}" deleted successfully.`);
            const updatedList = kbList.filter((item) => item.id !== kb.id);
            setKbList(updatedList);
            if (selectedKb?.id === kb.id) {
              setSelectedKb(updatedList.length > 0 ? updatedList[0] : null);
            }
          } else {
            const err = await res.json().catch(() => ({}));
            toast.error(err.detail || "Failed to delete database.");
          }
        } catch (err: any) {
          console.error("Delete database error:", err);
          toast.error(err.message || "Network error while deleting database.");
        }
      },
    });
  };

  const handleViewSchema = async (kbId: string) => {
    setSchemaLoading(true);
    setSchemaModalOpen(true);
    setSchemaData(null);
    setSchemaSearchQuery("");
    try {
      const res = await fetch(`${API_BASE_URL}/database-knowledgebases/${kbId}/schema`, {
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        const json = await res.json();
        const rawSchema = json.schema_data || json;

        // Aggregate tables across all schemas (public, etc.)
        let tablesDict: Record<string, any> = {};
        if (rawSchema.schemas) {
          for (const s of Object.values(rawSchema.schemas) as any[]) {
            if (s && s.tables) {
              tablesDict = { ...tablesDict, ...s.tables };
            }
          }
        }

        // Normalize columns (convert dict to array if needed)
        const normalizedTables: Record<string, any> = {};
        for (const [tblName, tblObj] of Object.entries(tablesDict) as any[]) {
          const rawCols = tblObj.columns || {};
          const colList = Array.isArray(rawCols) ? rawCols : Object.values(rawCols);
          normalizedTables[tblName] = {
            ...tblObj,
            columns: colList,
          };
        }

        const normalizedData: SchemaResponse = {
          database_name: rawSchema.database_name || "Database",
          database_type: rawSchema.database_type || "postgresql",
          fingerprint: json.schema_version || rawSchema.fingerprint || "",
          introspected_at: json.introspected_at || rawSchema.introspected_at || "",
          summary: rawSchema.summary || {
            table_count: Object.keys(normalizedTables).length,
            column_count: Object.values(normalizedTables).reduce(
              (acc: number, t: any) => acc + (t.columns?.length || 0),
              0
            ),
            foreign_key_count: 0,
            relationship_count: 0,
          },
          schemas: {
            public: {
              schema_name: "public",
              tables: normalizedTables,
            },
          },
        };

        setSchemaData(normalizedData);
      } else {
        toast.error("No canonical schema snapshot found. Please sync schema first.");
      }
    } catch (err) {
      console.error(err);
      toast.error("Failed to load schema.");
    } finally {
      setSchemaLoading(false);
    }
  };

  const handleSaveCustomMappings = async (mappings: Array<{ sourceTable: string; sourceColumn: string; targetTable: string; targetColumn: string }>) => {
    if (!selectedKb?.id) return;
    try {
      const res = await fetch(`${API_BASE_URL}/database-knowledgebases/${selectedKb.id}/user-mappings`, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({ mappings }),
      });
      if (res.ok) {
        toast.success("Relationships saved to database and pipeline updated!");
        handleViewSchema(selectedKb.id);
      } else {
        const errJson = await res.json().catch(() => ({}));
        toast.error(errJson.detail || "Failed to save mappings to database.");
      }
    } catch (err) {
      console.error("Error saving user mappings:", err);
      toast.error("Failed to persist mappings to backend.");
    }
  };

  const handleDownloadSchema = (format: "json" | "sql" = "json") => {
    if (!schemaData) {
      toast.error("No schema data available to download.");
      return;
    }

    const dbName = (schemaData.database_name || "database").toLowerCase().replace(/[^a-z0-9_]/g, "_");
    const version = (schemaData.fingerprint || "snapshot").substring(0, 8);

    if (format === "json") {
      const jsonString = JSON.stringify(schemaData, null, 2);
      const blob = new Blob([jsonString], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `schema_${dbName}_${version}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast.success("Full schema snapshot exported as JSON.");
    } else if (format === "sql") {
      let ddl = `-- Canonical Schema DDL for ${schemaData.database_name || "database"}\n`;
      ddl += `-- Engine: ${schemaData.database_type || "PostgreSQL"}\n`;
      ddl += `-- Introspected at: ${schemaData.introspected_at || new Date().toISOString()}\n`;
      ddl += `-- Fingerprint: ${schemaData.fingerprint}\n\n`;

      const tables = Object.values(schemaData.schemas?.public?.tables || {});
      for (const tbl of tables as any[]) {
        ddl += `CREATE TABLE IF NOT EXISTS "${tbl.table_name}" (\n`;
        const cols = Array.isArray(tbl.columns) ? tbl.columns : Object.values(tbl.columns || {});
        const colDefs = cols.map((col: any) => {
          let def = `  "${col.name}" ${col.data_type.toUpperCase()}`;
          if (!col.is_nullable) def += " NOT NULL";
          if (col.is_primary_key) def += " PRIMARY KEY";
          return def;
        });
        if (tbl.foreign_keys && tbl.foreign_keys.length > 0) {
          for (const fk of tbl.foreign_keys) {
            const srcCols = (fk.constrained_columns || []).map((c: string) => `"${c}"`).join(", ");
            const refCols = (fk.referred_columns || []).map((c: string) => `"${c}"`).join(", ");
            colDefs.push(`  FOREIGN KEY (${srcCols}) REFERENCES "${fk.referred_table}" (${refCols})`);
          }
        }
        ddl += colDefs.join(",\n");
        ddl += `\n);\n\n`;
      }

      const blob = new Blob([ddl], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `schema_${dbName}_${version}.sql`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast.success("Full schema DDL script exported as SQL.");
    }
  };

  const parseMarkdownTable = (text: string): { columns: string[]; rows: Record<string, any>[] } => {
    if (!text) return { columns: [], rows: [] };
    const lines = text
      .trim()
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l.startsWith("|") && l.endsWith("|"));

    if (lines.length < 3) return { columns: [], rows: [] };

    // 1. Header row
    const rawHeaders = lines[0]
      .slice(1, -1)
      .split("|")
      .map((h) => h.trim());

    // 2. Divider row validation (| --- | --- |)
    const isDivider = lines[1]
      .slice(1, -1)
      .split("|")
      .every((cell) => /^[:\s-]+$/.test(cell.trim()));

    if (!isDivider || rawHeaders.length === 0) return { columns: [], rows: [] };

    const columns = rawHeaders;
    const rows: Record<string, any>[] = [];

    // 3. Parse data rows
    for (let i = 2; i < lines.length; i++) {
      const rawCells = lines[i].slice(1, -1).split("|").map((c) => c.trim());
      const rowObj: Record<string, any> = {};
      columns.forEach((col, idx) => {
        const val = idx < rawCells.length ? rawCells[idx] : "";
        const colLower = col.toLowerCase().replace(/\s+/g, "_");
        // Disambiguated indexed key to prevent collision with duplicate column names
        rowObj[`${colLower}_${idx}`] = val;
        // Direct key
        if (rowObj[col] === undefined) {
          rowObj[col] = val;
        }
      });
      rows.push(rowObj);
    }

    return { columns, rows };
  };

  const handleExportCSV = () => {
    if (!groundedAnswer || effectiveRows.length === 0) {
      toast.error("No tabular records available to export.");
      return;
    }

    const cols = effectiveColumns.length > 0 ? effectiveColumns : Object.keys(effectiveRows[0]);
    const headerRow = cols.map((c) => `"${c.replace(/"/g, '""')}"`).join(",");
    const dataRows = effectiveRows.map((r: any) =>
      cols
        .map((c: string, idx: number) => {
          const colLower = c.toLowerCase().replace(/\s+/g, "_");
          const fallbackKey = `${colLower}_${idx}`;
          const val = r[c] !== undefined ? r[c] : (r[fallbackKey] !== undefined ? r[fallbackKey] : "");
          if (val === null || val === undefined) return '""';
          return `"${String(val).replace(/"/g, '""')}"`;
        })
        .join(",")
    );

    const csvContent = "\uFEFF" + [headerRow, ...dataRows].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `query_result_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "_")}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast.success(`Exported ${effectiveRows.length} records as CSV.`);
  };

  const handleCopyAnswer = () => {
    if (!groundedAnswer) return;
    navigator.clipboard.writeText(groundedAnswer.answer_text);
    setCopiedAnswer(true);
    toast.success("Answer copied to clipboard!");
    setTimeout(() => setCopiedAnswer(false), 2000);
  };

  const handleCancelQuery = () => {
    if (abortController) {
      abortController.abort();
      setAbortController(null);
    }
    setIsCancelled(true);
    setQueryLoading(false);
    toast("Query cancelled by user.", { icon: "🛑" });
  };

  const handleSelectDisambiguation = (option: any) => {
    const isTable = disambiguationData?.entity_type === 'table' || option.table_name || option.table;
    const tblName = option.table_name || option.table || (typeof option.id === 'string' ? option.id : null);
    setDisambiguationData(null);
    if (isTable && tblName) {
      handleRunQuery(userQuery, undefined, [tblName]);
    } else {
      handleRunQuery(userQuery, [option]);
    }
  };

  const handleRunQuery = async (
    queryText?: string,
    explicitResolvedEntities?: any[],
    explicitSelectedTables?: string[],
    explicitStrategy?: "separate" | "union"
  ) => {
    const q = queryText || userQuery;
    if (!q.trim()) {
      toast.error("Please enter a question.");
      return;
    }
    if (!selectedKb) {
      toast.error("Please select a database knowledgebase first.");
      return;
    }

    if (abortController) {
      abortController.abort();
    }

    const controller = new AbortController();
    setAbortController(controller);
    setQueryLoading(true);
    setGroundedAnswer(null);
    setStreamEvents([]);
    setStreamError(null);
    setIsCancelled(false);
    if (!explicitResolvedEntities && !explicitSelectedTables) {
      setDisambiguationData(null);
    }

    try {
      const token = getCookie("AUTH_TOKEN");
      await DatabaseStreamClient.streamQuery({
        apiBaseUrl: API_BASE_URL,
        kbId: selectedKb.id,
        query: q,
        token: token || undefined,
        useLlm: true,
        resolvedEntities: explicitResolvedEntities,
        selectedTables: explicitSelectedTables,
        executionStrategy: explicitStrategy,
        abortSignal: controller.signal,
        onEvent: (event: DatabaseStreamEvent) => {
          setStreamEvents((prev) => [...prev, event]);
        },
        onDisambiguationRequired: (data) => {
          setDisambiguationData(data);
          setQueryLoading(false);
        },
        onAnswer: (answerData: any) => {
          // Normalize answer structure
          const normEvidence = answerData.evidence || {};
          let parsedRows = answerData.rows || normEvidence.rows || [];
          let parsedCols = answerData.columns || normEvidence.columns || [];

          // Robust fallback: if rows array is missing or empty, parse structured rows from markdown table
          if ((!parsedRows || parsedRows.length === 0) && answerData.answer_text) {
            const parsed = parseMarkdownTable(answerData.answer_text);
            if (parsed.rows.length > 0) {
              parsedRows = parsed.rows;
              parsedCols = parsed.columns;
            }
          }

          const ans: GroundedAnswer = {
            query_id: answerData.query_id || "",
            database_knowledgebase_id: selectedKb.id,
            schema_version: answerData.schema_version || "",
            answer_text: answerData.answer_text || "",
            answer_type: answerData.answer_type || "NARRATIVE",
            grounding_status: answerData.grounding_status || "VERIFIED",
            verification_status: answerData.verification_status || "PASSED",
            source_columns: answerData.source_columns || parsedCols || [],
            row_count: answerData.row_count !== undefined ? answerData.row_count : (parsedRows.length || normEvidence.row_count || 0),
            truncated: Boolean(answerData.truncated || normEvidence.truncated),
            warnings: answerData.warnings || [],
            generation_metadata: answerData.generation_metadata || {},
            rows: parsedRows,
            columns: parsedCols,
            pipeline_trace: answerData.pipeline_trace,
          };
          setGroundedAnswer(ans);
          setQueryLoading(false);
          toast.success("Grounded database answer synthesized!");
        },
        onError: (err: any) => {
          setStreamError(`${err.code}: ${err.message}`);
          setQueryLoading(false);
          toast.error(err.message || "Query execution failed.");
        },
        onCancelled: (reason?: string) => {
          setIsCancelled(true);
          setQueryLoading(false);
        },
        onComplete: () => {
          setQueryLoading(false);
        },
      });
    } catch (err: any) {
      if (err.name !== "AbortError") {
        setStreamError(err.message || "Query streaming error.");
        toast.error(err.message || "Query execution failed.");
      }
      setQueryLoading(false);
    } finally {
      setAbortController(null);
    }
  };

  const formatColumnTitle = (raw: string, count: number) => {
    let title = raw
      .replace(/_id_id$/, "_id")
      .replace(/_/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase());
    if (count > 1) {
      title = `${title} (#${count})`;
    }
    return title;
  };

  // Extract effective structured rows and columns from groundedAnswer or fallback markdown table
  const effectiveRows = React.useMemo(() => {
    if (!groundedAnswer) return [];
    if (groundedAnswer.rows && groundedAnswer.rows.length > 0) {
      return groundedAnswer.rows;
    }
    if (groundedAnswer.answer_text) {
      const parsed = parseMarkdownTable(groundedAnswer.answer_text);
      return parsed.rows;
    }
    return [];
  }, [groundedAnswer]);

  const effectiveColumns = React.useMemo(() => {
    if (!groundedAnswer) return [];
    if (groundedAnswer.columns && groundedAnswer.columns.length > 0) {
      return groundedAnswer.columns;
    }
    if (effectiveRows.length > 0) {
      const parsed = parseMarkdownTable(groundedAnswer.answer_text || "");
      if (parsed.columns.length > 0) return parsed.columns;
      return Object.keys(effectiveRows[0]);
    }
    return [];
  }, [groundedAnswer, effectiveRows]);

  // Disambiguate duplicate column names from multi-table joins (e.g. Id, Id, Email, Email)
  const disambiguatedColumns = React.useMemo(() => {
    const rawCols = effectiveColumns.length > 0 ? effectiveColumns : (effectiveRows.length > 0 ? Object.keys(effectiveRows[0]) : []);
    if (rawCols.length === 0) return [];

    const counts: Record<string, number> = {};
    return rawCols.map((col, idx) => {
      counts[col] = (counts[col] || 0) + 1;
      const displayTitle = formatColumnTitle(col, counts[col]);
      const colLower = col.toLowerCase();
      let colWidth = 150;
      let align: "left" | "center" | "right" = "left";

      if (colLower === "id" || colLower.endsWith("_id")) {
        colWidth = 75;
        align = "center";
      } else if (colLower.includes("status") || colLower.includes("rating") || colLower.includes("gender")) {
        colWidth = 110;
        align = "center";
      } else if (colLower.includes("date") || colLower.includes("time") || colLower.includes("dob")) {
        colWidth = 120;
        align = "center";
      } else if (colLower.includes("salary") || colLower.includes("amount") || colLower.includes("expense") || colLower.includes("cost") || colLower.includes("budget") || colLower.includes("total")) {
        colWidth = 125;
        align = "right";
      } else if (colLower.includes("email")) {
        colWidth = 190;
      } else if (colLower.includes("phone") || colLower.includes("mobile")) {
        colWidth = 135;
      } else if (colLower.includes("address") || colLower.includes("location") || colLower.includes("description") || colLower.includes("notes") || colLower.includes("comment") || colLower.includes("reason")) {
        colWidth = 230;
      } else if (colLower.includes("name") || colLower.includes("title") || colLower.includes("department") || colLower.includes("city")) {
        colWidth = 160;
      }

      const fallbackKey = `${colLower.replace(/\s+/g, "_")}_${idx}`;
      const directKey = col;

      return {
        title: displayTitle,
        key: `${col}_${idx}`,
        width: colWidth,
        align,
        ellipsis: true,
        sorter: (a: any, b: any) => {
          const valA = a[fallbackKey] !== undefined ? a[fallbackKey] : (a[directKey] !== undefined ? a[directKey] : "");
          const valB = b[fallbackKey] !== undefined ? b[fallbackKey] : (b[directKey] !== undefined ? b[directKey] : "");
          if (typeof valA === "number" && typeof valB === "number") return valA - valB;
          return String(valA ?? "").localeCompare(String(valB ?? ""));
        },
        render: (_: any, record: any) => {
          const val = record[fallbackKey] !== undefined ? record[fallbackKey] : (record[directKey] !== undefined ? record[directKey] : null);
          if (val === null || val === undefined || val === "" || val === "-") {
            return <span className="text-gray-400 italic text-xs">NULL</span>;
          }
          const strVal = String(val);
          const lower = strVal.toLowerCase();
          if (lower === "approved" || lower === "active" || lower === "completed" || lower === "verified" || lower === "present") {
            return <Tag color="green" style={{ borderRadius: 4, margin: 0, fontSize: 11 }}>{strVal.toUpperCase()}</Tag>;
          }
          if (lower === "rejected" || lower === "failed" || lower === "inactive" || lower === "cancelled" || lower === "absent" || lower === "expired") {
            return <Tag color="red" style={{ borderRadius: 4, margin: 0, fontSize: 11 }}>{strVal.toUpperCase()}</Tag>;
          }
          if (lower === "pending" || lower === "in_progress" || lower === "configured" || lower === "half_day" || lower === "new") {
            return <Tag color="orange" style={{ borderRadius: 4, margin: 0, fontSize: 11 }}>{strVal.toUpperCase()}</Tag>;
          }
          if (lower.includes("@") && lower.includes(".")) {
            return (
              <Tooltip title={strVal}>
                <a href={`mailto:${strVal}`} className="text-teal-400 hover:underline truncate block font-mono text-xs">
                  {strVal}
                </a>
              </Tooltip>
            );
          }
          return (
            <Tooltip title={strVal.length > 25 ? strVal : undefined}>
              <span className="text-xs font-sans truncate block">{strVal}</span>
            </Tooltip>
          );
        },
      };
    });
  }, [effectiveColumns, effectiveRows]);

  const filteredEvidenceRows = React.useMemo(() => {
    if (effectiveRows.length === 0) return [];
    if (!tableFilter.trim()) return effectiveRows;
    const q = tableFilter.toLowerCase();
    return effectiveRows.filter((row: any) =>
      Object.values(row).some((val) => String(val || "").toLowerCase().includes(q))
    );
  }, [effectiveRows, tableFilter]);

  const parsedMarkdownHtml = React.useMemo(() => {
    if (!groundedAnswer || !groundedAnswer.answer_text) return "";
    try {
      const markedObj = marked as any;
      return typeof markedObj === "function"
        ? markedObj(groundedAnswer.answer_text)
        : markedObj.parse(groundedAnswer.answer_text);
    } catch (e) {
      console.error("Failed to parse markdown:", e);
      return groundedAnswer.answer_text;
    }
  }, [groundedAnswer?.answer_text]);

  const { introMarkdownHtml, summaryMarkdownHtml } = React.useMemo(() => {
    if (!groundedAnswer || !groundedAnswer.answer_text) {
      return { introMarkdownHtml: "", summaryMarkdownHtml: "" };
    }
    const markedObj = marked as any;
    const renderMd = (txt: string) => {
      if (!txt.trim()) return "";
      try {
        return typeof markedObj === "function" ? markedObj(txt) : markedObj.parse(txt);
      } catch (e) {
        return txt;
      }
    };

    const lines = groundedAnswer.answer_text.split("\n");
    let tableStart = -1;
    let tableEnd = -1;

    for (let i = 0; i < lines.length; i++) {
      const trimmed = lines[i].trim();
      if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
        if (tableStart === -1) tableStart = i;
        tableEnd = i;
      }
    }

    if (tableStart === -1) {
      return {
        introMarkdownHtml: renderMd(groundedAnswer.answer_text.trim()),
        summaryMarkdownHtml: "",
      };
    }

    const intro = lines.slice(0, tableStart).join("\n").trim();
    const summary = lines.slice(tableEnd + 1).join("\n").trim();

    return {
      introMarkdownHtml: renderMd(intro),
      summaryMarkdownHtml: renderMd(summary),
    };
  }, [groundedAnswer?.answer_text]);

  const isTabularAnswer = React.useMemo(() => {
    if (!groundedAnswer) return false;
    const text = groundedAnswer.answer_text.trim();
    return (
      effectiveRows.length > 0 ||
      (text.startsWith("|") && text.includes("---"))
    );
  }, [groundedAnswer, effectiveRows]);

  const allSchemaTables = React.useMemo(() => {
    if (!schemaData?.schemas?.public?.tables) return [];
    return Object.values(schemaData.schemas.public.tables);
  }, [schemaData]);

  const filteredSchemaTables = React.useMemo(() => {
    if (!allSchemaTables.length) return [];
    if (!schemaSearchQuery.trim()) return allSchemaTables;
    const q = schemaSearchQuery.toLowerCase();
    return allSchemaTables.filter((tbl: any) => {
      const tName = tbl.table_name || "";
      if (tName.toLowerCase().includes(q)) return true;
      if (tbl.comment && tbl.comment.toLowerCase().includes(q)) return true;

      // Also filter by alternative table names / aliases
      const aliases = tableCustomNames[tName] || tableCustomNames[tName.toLowerCase()] || [];
      if (aliases.some((a: string) => a.toLowerCase().includes(q))) return true;

      const cols = Array.isArray(tbl.columns) ? tbl.columns : Object.values(tbl.columns || {});
      const tblColAliases = columnCustomNames[tName] || columnCustomNames[tName.toLowerCase()] || {};

      return cols.some(
        (c: any) => {
          if (c.name.toLowerCase().includes(q)) return true;
          if (c.comment && c.comment.toLowerCase().includes(q)) return true;
          const colAliases = tblColAliases[c.name] || tblColAliases[c.name.toLowerCase()] || [];
          return colAliases.some((ca: string) => ca.toLowerCase().includes(q));
        }
      );
    });
  }, [allSchemaTables, schemaSearchQuery, tableCustomNames, columnCustomNames]);

  return (
    <div className="database-knowledge-page p-6 md:p-8 pb-36 max-w-[1600px] mx-auto min-h-screen text-[var(--app-text)]">
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-[var(--app-border)]">
        <div>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-teal-500/10 text-teal-500 flex items-center justify-center font-bold text-xl">
              <BsDatabaseFillGear style={{ fontSize: 22 }} />
            </div>
            <div>
              <Title level={2} style={{ margin: 0, color: "var(--app-text)" }}>
                Database Knowledgebase
              </Title>
              <Text style={{ color: "#8c8c8c" }}>
                Safe Read-Only Relational Intelligence & Semantic Grounded Synthesis
              </Text>
            </div>
          </div>
        </div>

        <Space>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setTestResult(null);
              setModalOpen(true);
            }}
            style={{
              backgroundColor: "var(--app-primary)",
              borderColor: "var(--app-primary)",
              height: 42,
              padding: "0 20px",
              borderRadius: 8,
              fontWeight: 600,
            }}
          >
            Connect Database
          </Button>
        </Space>
      </div>

      {/* Workspace Section Header: Perfectly Aligned Headers Across Both Columns */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-center mt-6 mb-3">
        {/* Left Subheader: Connected Databases */}
        <div className="lg:col-span-4 xl:col-span-4 2xl:col-span-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span style={{ fontSize: 14.5, fontWeight: 750, color: "#1e293b" }}>
              Connected Databases
            </span>
            <span
              style={{
                fontSize: 11,
                fontWeight: 700,
                backgroundColor: "#f0fdfa",
                color: "#0f766e",
                border: "1px solid #99f6e4",
                padding: "1px 7px",
                borderRadius: 9999,
              }}
            >
              {kbList.length}
            </span>
          </div>
          <Button
            type="text"
            size="small"
            icon={<SyncOutlined spin={loading} style={{ fontSize: 11 }} />}
            onClick={fetchKnowledgebases}
            style={{ fontSize: 12, color: "#64748b", borderRadius: 6 }}
            className="hover:text-teal-600 hover:bg-teal-50"
          >
            Refresh
          </Button>
        </div>

        {/* Right Subheader: Active Database Workspace */}
        <div className="lg:col-span-8 xl:col-span-8 2xl:col-span-9 hidden lg:flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span style={{ fontSize: 14.5, fontWeight: 750, color: "#1e293b" }}>
              Active Database Workspace
            </span>
            <span
              style={{
                fontSize: 11,
                fontWeight: 700,
                backgroundColor: "#f0fdfa",
                color: "#0f766e",
                border: "1px solid #99f6e4",
                padding: "1px 7px",
                borderRadius: 9999,
              }}
            >
              ACTIVE
            </span>
          </div>
          <span style={{ fontSize: 12, color: "#64748b", fontWeight: 500 }}>
            {selectedKb?.database_type ? `${selectedKb.database_type.toUpperCase()} Engine` : "Knowledge Base"}
          </span>
        </div>
      </div>

      {/* Main Workspace Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Configured Databases */}
        <div className="lg:col-span-4 xl:col-span-4 2xl:col-span-3 flex flex-col gap-3.5">
          {loading && kbList.length === 0 ? (
            <div className="py-12 text-center">
              <Spin size="large" />
              <Paragraph style={{ marginTop: 16, color: "#8c8c8c" }}>Loading databases...</Paragraph>
            </div>
          ) : kbList.length === 0 ? (
            <Card
              style={{
                textAlign: "center",
                padding: "32px 16px",
                background: "var(--app-surface)",
                borderColor: "var(--app-border)",
                borderRadius: 16,
              }}
            >
              <BsDatabaseFillGear style={{ fontSize: 36, color: "#bfbfbf", marginBottom: 12 }} />
              <Paragraph style={{ color: "#8c8c8c" }}>No relational databases connected yet.</Paragraph>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => setModalOpen(true)}
                style={{ backgroundColor: "var(--app-primary)", borderRadius: 8 }}
              >
                Connect HRMS Database
              </Button>
            </Card>
          ) : (
            <div className="flex flex-col gap-3.5">
              {kbList.map((kb) => {
                const isSelected = selectedKb?.id === kb.id;
                const isReady = kb.status === "introspected" || kb.status === "indexed";
                return (
                  <div
                    key={kb.id}
                    onClick={() => setSelectedKb(kb)}
                    style={{
                      borderRadius: 16,
                      border: isSelected ? "1.5px solid #0d9488" : "1px solid #e2e8f0",
                      background: isSelected
                        ? "linear-gradient(180deg, rgba(13, 148, 136, 0.04) 0%, #ffffff 100%)"
                        : "#ffffff",
                      boxShadow: isSelected
                        ? "0 8px 24px -4px rgba(13, 148, 136, 0.16), 0 0 0 1px rgba(13, 148, 136, 0.25)"
                        : "0 2px 8px -2px rgba(0, 0, 0, 0.04)",
                      padding: "16px",
                      cursor: "pointer",
                      transition: "all 0.2s ease",
                      position: "relative",
                    }}
                    className="group hover:border-teal-500/80 hover:shadow-md"
                  >
                    {/* Active Selected Left Accent Bar */}
                    {isSelected && (
                      <div
                        style={{
                          position: "absolute",
                          left: 0,
                          top: 14,
                          bottom: 14,
                          width: 4,
                          backgroundColor: "#0d9488",
                          borderTopRightRadius: 4,
                          borderBottomRightRadius: 4,
                        }}
                      />
                    )}

                    {/* Top Header: Icon + Title + Status Pill + Delete */}
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-start gap-2.5 min-w-0 flex-1">
                        {/* Database Badge Avatar */}
                        <div
                          style={{
                            width: 38,
                            height: 38,
                            borderRadius: 10,
                            background: isSelected
                              ? "linear-gradient(135deg, #0d9488 0%, #0f766e 100%)"
                              : "linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%)",
                            color: isSelected ? "#ffffff" : "#475569",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            flexShrink: 0,
                            boxShadow: isSelected ? "0 4px 10px rgba(13, 148, 136, 0.3)" : "none",
                            transition: "all 0.2s ease",
                          }}
                        >
                          <DatabaseOutlined style={{ fontSize: 17 }} />
                        </div>

                        <div className="min-w-0 flex-1">
                          <span
                            style={{
                              fontSize: 14,
                              fontWeight: 700,
                              color: isSelected ? "#0f766e" : "#1e293b",
                              display: "block",
                              lineHeight: 1.3,
                            }}
                            className="truncate"
                            title={kb.name}
                          >
                            {kb.name}
                          </span>
                          <span
                            style={{
                              fontSize: 11.5,
                              color: "#64748b",
                              display: "-webkit-box",
                              WebkitLineClamp: 2,
                              WebkitBoxOrient: "vertical",
                              overflow: "hidden",
                              marginTop: 3,
                              lineHeight: 1.45,
                            }}
                          >
                            {kb.description || "PostgreSQL Knowledgebase"}
                          </span>
                        </div>
                      </div>

                      {/* Top Right: Status Pill & Delete Button */}
                      <div className="flex items-center gap-1.5 shrink-0">
                        {pipelineProgressMap[kb.id]?.is_active ? (
                          <Tooltip
                            title={`${pipelineProgressMap[kb.id]?.current_stage_label || "Processing"} (${pipelineProgressMap[kb.id]?.progress_percent || 0}%)`}
                          >
                            <div
                              style={{
                                display: "inline-flex",
                                alignItems: "center",
                                gap: 5,
                                padding: "2px 7px 2px 4px",
                                borderRadius: 9999,
                                backgroundColor: "#f0fdfa",
                                border: "1px solid #99f6e4",
                                boxShadow: "0 1px 3px rgba(13, 148, 136, 0.12)",
                              }}
                            >
                              <Progress
                                type="circle"
                                percent={pipelineProgressMap[kb.id]?.progress_percent || 0}
                                size={20}
                                strokeColor={{ "0%": "#14b8a6", "100%": "#0d9488" }}
                                trailColor="#e2e8f0"
                                strokeWidth={14}
                                showInfo={false}
                              />
                              <span
                                style={{
                                  fontSize: 10.5,
                                  fontWeight: 700,
                                  color: "#0f766e",
                                  fontFamily: "ui-monospace, monospace",
                                }}
                              >
                                {pipelineProgressMap[kb.id]?.progress_percent || 0}%
                              </span>
                            </div>
                          </Tooltip>
                        ) : (
                          <span
                            style={{
                              fontSize: 10,
                              fontWeight: 700,
                              letterSpacing: "0.5px",
                              padding: "2px 7px",
                              borderRadius: 9999,
                              backgroundColor: isReady ? "#ecfdf5" : "#f0f9ff",
                              color: isReady ? "#047857" : "#0369a1",
                              border: isReady ? "1px solid #a7f3d0" : "1px solid #bae6fd",
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 4,
                              textTransform: "uppercase",
                            }}
                          >
                            <span
                              style={{
                                width: 5,
                                height: 5,
                                borderRadius: "50%",
                                backgroundColor: isReady ? "#10b981" : "#0ea5e9",
                              }}
                            />
                            {kb.status}
                          </span>
                        )}

                        <Tooltip title="Delete Database">
                          <Button
                            danger
                            type="text"
                            size="small"
                            icon={<DeleteOutlined style={{ fontSize: 12 }} />}
                            style={{
                              color: "#94a3b8",
                              borderRadius: 8,
                              padding: "4px",
                              height: 26,
                              width: 26,
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                            }}
                            className="hover:text-red-500 hover:bg-red-50"
                            onClick={(e) => {
                              e.stopPropagation();
                              confirmDeleteDatabase(kb);
                            }}
                          />
                        </Tooltip>
                      </div>
                    </div>

                    {/* Metadata Row: Engine & Fingerprint */}
                    <div
                      style={{
                        marginTop: 12,
                        paddingTop: 10,
                        borderTop: "1px dashed #e2e8f0",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        fontSize: 11,
                      }}
                    >
                      <span
                        style={{
                          fontFamily: "ui-monospace, monospace",
                          fontWeight: 600,
                          color: "#475569",
                          backgroundColor: "#f8fafc",
                          border: "1px solid #e2e8f0",
                          padding: "2px 8px",
                          borderRadius: 6,
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 4,
                          fontSize: 10.5,
                        }}
                      >
                        <span style={{ width: 4, height: 4, borderRadius: "50%", backgroundColor: "#0d9488" }} />
                        ENGINE: {kb.database_type.toUpperCase()}
                      </span>

                      {kb.schema_version && (
                        <Tooltip title={`Fingerprint: ${kb.schema_version}`}>
                          <span
                            style={{
                              fontFamily: "ui-monospace, monospace",
                              fontSize: 10.5,
                              fontWeight: 600,
                              color: "#0f766e",
                              backgroundColor: "#f0fdfa",
                              border: "1px solid #ccfbf1",
                              padding: "2px 7px",
                              borderRadius: 6,
                            }}
                          >
                            v:{kb.schema_version.substring(0, 8)}
                          </span>
                        </Tooltip>
                      )}
                    </div>

                    {/* Action Buttons: Sync Schema & Explore Schema */}
                    <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                      <Button
                        size="small"
                        icon={
                          pipelineProgressMap[kb.id]?.is_active ? (
                            <LoadingOutlined spin style={{ fontSize: 11, color: "#0d9488" }} />
                          ) : (
                            <SyncOutlined style={{ fontSize: 11 }} />
                          )
                        }
                        disabled={pipelineProgressMap[kb.id]?.is_active}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleSyncSchema(kb.id);
                        }}
                        style={{
                          borderRadius: 8,
                          fontSize: 11.5,
                          fontWeight: 600,
                          borderColor: pipelineProgressMap[kb.id]?.is_active ? "#99f6e4" : "#cbd5e1",
                          backgroundColor: pipelineProgressMap[kb.id]?.is_active ? "#f0fdfa" : "#ffffff",
                          color: pipelineProgressMap[kb.id]?.is_active ? "#0f766e" : "#334155",
                          height: 30,
                        }}
                        className="hover:border-teal-500 hover:text-teal-600"
                      >
                        {pipelineProgressMap[kb.id]?.is_active
                          ? `Syncing (${pipelineProgressMap[kb.id]?.progress_percent || 0}%)`
                          : "Sync Schema"}
                      </Button>
                      <Button
                        size="small"
                        icon={<TableOutlined style={{ fontSize: 11 }} />}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleViewSchema(kb.id);
                        }}
                        style={{
                          borderRadius: 8,
                          fontSize: 11.5,
                          fontWeight: 700,
                          backgroundColor: "#f0fdfa",
                          borderColor: "#99f6e4",
                          color: "#0f766e",
                          height: 30,
                        }}
                        className="hover:bg-teal-100 hover:border-teal-400"
                      >
                        Explore Schema
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Right Column: Query & Grounded Answer Agent */}
        <div className="lg:col-span-8 xl:col-span-8 2xl:col-span-9 flex flex-col gap-6">
          {selectedKb ? (
            <>
              {/* Selected DB Header */}
              <div
                style={{
                  backgroundColor: "#ffffff",
                  border: "1px solid #e2e8f0",
                  borderRadius: 16,
                  padding: "18px 22px",
                  boxShadow: "0 2px 10px rgba(0, 0, 0, 0.03)",
                }}
              >
                <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                  {/* Left Info: Avatar + Title + Status + Copyable ID */}
                  <div className="flex items-start gap-3.5 min-w-0 flex-1">
                    <div
                      style={{
                        width: 46,
                        height: 46,
                        borderRadius: 12,
                        background: "linear-gradient(135deg, #0d9488 0%, #0f766e 50%, #115e59 100%)",
                        color: "#ffffff",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        flexShrink: 0,
                        boxShadow: "0 6px 14px -2px rgba(13, 148, 136, 0.35)",
                      }}
                    >
                      <DatabaseOutlined style={{ fontSize: 22 }} />
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2.5 flex-wrap">
                        <h2
                          style={{
                            margin: 0,
                            fontSize: 18,
                            fontWeight: 800,
                            color: "#0f172a",
                            letterSpacing: "-0.3px",
                          }}
                          title={selectedKb.name}
                        >
                          {selectedKb.name}
                        </h2>
                        <span
                          style={{
                            fontSize: 11,
                            fontWeight: 700,
                            padding: "3px 9px",
                            borderRadius: 9999,
                            backgroundColor: "#f0fdfa",
                            color: "#0f766e",
                            border: "1px solid #99f6e4",
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 5,
                          }}
                        >
                          <span
                            style={{
                              width: 6,
                              height: 6,
                              borderRadius: "50%",
                              backgroundColor: "#0d9488",
                            }}
                          />
                          Active Query Agent
                        </span>
                      </div>

                      {/* Database ID with copy button */}
                      <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                        <span style={{ color: "#64748b", fontSize: 12, fontWeight: 500 }}>Database ID:</span>
                        <button
                          type="button"
                          onClick={() => {
                            navigator.clipboard.writeText(selectedKb.id);
                            toast.success("Database ID copied to clipboard!");
                          }}
                          title="Click to copy full Database ID"
                          style={{
                            fontFamily: "ui-monospace, monospace",
                            fontSize: 11.5,
                            color: "#334155",
                            backgroundColor: "#f8fafc",
                            border: "1px solid #cbd5e1",
                            borderRadius: 6,
                            padding: "2px 8px",
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 6,
                            cursor: "pointer",
                          }}
                          className="hover:bg-slate-100 hover:border-slate-400 transition-colors"
                        >
                          <span>{selectedKb.id}</span>
                          <CopyOutlined style={{ fontSize: 11, color: "#64748b" }} />
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Right Action Buttons */}
                  <div className="shrink-0 flex items-center gap-2.5 flex-wrap">
                    <Button
                      type="primary"
                      icon={<TableOutlined />}
                      onClick={() => handleViewSchema(selectedKb.id)}
                      style={{
                        backgroundColor: "#0d6e65",
                        borderColor: "#0d6e65",
                        borderRadius: 10,
                        fontWeight: 700,
                        fontSize: 13,
                        height: 38,
                        padding: "0 16px",
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        boxShadow: "0 2px 8px rgba(13, 110, 101, 0.35)",
                      }}
                    >
                      Browse Schema
                    </Button>
                    {selectedKb && pipelineProgressMap[selectedKb.id]?.is_active && (
                      <Tooltip title={pipelineProgressMap[selectedKb.id]?.current_stage_label}>
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                            padding: "3px 10px 3px 6px",
                            borderRadius: 10,
                            backgroundColor: "#f0fdfa",
                            border: "1.5px solid #99f6e4",
                            boxShadow: "0 2px 8px rgba(13, 148, 136, 0.12)",
                          }}
                        >
                          <Progress
                            type="circle"
                            percent={pipelineProgressMap[selectedKb.id]?.progress_percent || 0}
                            size={26}
                            strokeColor={{ "0%": "#14b8a6", "100%": "#0d9488" }}
                            trailColor="#cbd5e1"
                            strokeWidth={14}
                            format={(pct) => (
                              <span style={{ fontSize: 9, fontWeight: 800, color: "#0f766e" }}>
                                {pct}%
                              </span>
                            )}
                          />
                          <div style={{ display: "flex", flexDirection: "column", textAlign: "left" }}>
                            <span style={{ fontSize: 11, fontWeight: 700, color: "#0f766e", lineHeight: 1.2 }}>
                              Phase 2 Syncing ({pipelineProgressMap[selectedKb.id]?.progress_percent || 0}%)
                            </span>
                            <span
                              style={{
                                fontSize: 9.5,
                                color: "#64748b",
                                maxWidth: 160,
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                                marginTop: 1,
                              }}
                            >
                              {pipelineProgressMap[selectedKb.id]?.current_stage_label || "Processing stages..."}
                            </span>
                          </div>
                        </div>
                      </Tooltip>
                    )}
                    <Button
                      icon={<SyncOutlined spin={Boolean(selectedKb && pipelineProgressMap[selectedKb.id]?.is_active)} />}
                      disabled={Boolean(selectedKb && pipelineProgressMap[selectedKb.id]?.is_active)}
                      onClick={() => handleSyncSchema(selectedKb.id)}
                      style={{
                        borderRadius: 10,
                        borderColor: Boolean(selectedKb && pipelineProgressMap[selectedKb.id]?.is_active) ? "#99f6e4" : "#cbd5e1",
                        backgroundColor: Boolean(selectedKb && pipelineProgressMap[selectedKb.id]?.is_active) ? "#f0fdfa" : "#ffffff",
                        color: Boolean(selectedKb && pipelineProgressMap[selectedKb.id]?.is_active) ? "#0f766e" : "#334155",
                        fontWeight: 600,
                        fontSize: 13,
                        height: 38,
                        padding: "0 14px",
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                      }}
                    >
                      {selectedKb && pipelineProgressMap[selectedKb.id]?.is_active
                        ? `Re-Syncing (${pipelineProgressMap[selectedKb.id]?.progress_percent || 0}%)`
                        : "Re-Sync"}
                    </Button>
                    <Button
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => confirmDeleteDatabase(selectedKb)}
                      style={{
                        borderRadius: 10,
                        borderColor: "#fecdd3",
                        backgroundColor: "#fff1f2",
                        color: "#e11d48",
                        fontWeight: 600,
                        fontSize: 13,
                        height: 38,
                        padding: "0 14px",
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                      }}
                    >
                      Delete
                    </Button>
                  </div>
                </div>
              </div>

              {/* Phase 3B Navigation Tabs */}
              <Tabs
                activeKey={activeTab}
                onChange={(key) => {
                  setActiveTab(key);
                  if (key === "telemetry" && selectedKb) {
                    fetchMetricsAndHealth(selectedKb.id);
                  } else if (key === "audit" && selectedKb) {
                    fetchAuditLogs(selectedKb.id, 1, auditStatusFilter);
                  }
                }}
                style={{ marginTop: 4 }}
                items={[
                  {
                    key: "query",
                    label: (
                      <span style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 650, fontSize: 13 }}>
                        <SearchOutlined style={{ color: activeTab === "query" ? "#0d6e65" : "#94a3b8" }} />
                        Natural Language Query Agent
                      </span>
                    ),
                    children: (
                      <div className="flex flex-col gap-4">
                        {/* Query Input Box */}
                        <div
                          style={{
                            backgroundColor: "#ffffff",
                            border: "1.5px solid #e2e8f0",
                            borderRadius: 16,
                            padding: "16px 20px",
                            boxShadow: "0 4px 16px -2px rgba(0, 0, 0, 0.05)",
                            transition: "border 0.2s ease, box-shadow 0.2s ease",
                          }}
                          className="hover:border-slate-300 focus-within:border-teal-500 focus-within:ring-2 focus-within:ring-teal-500/20"
                        >
                          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 w-full">
                            <div className="relative flex-1 flex items-center">
                              <SearchOutlined
                                style={{
                                  position: "absolute",
                                  left: 14,
                                  fontSize: 16,
                                  color: "#94a3b8",
                                  pointerEvents: "none",
                                }}
                              />
                              <input
                                type="text"
                                placeholder="Ask any natural-language question about this database..."
                                value={userQuery}
                                onChange={(e) => setUserQuery(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter" && !queryLoading) {
                                    handleRunQuery();
                                  }
                                }}
                                disabled={queryLoading}
                                style={{
                                  width: "100%",
                                  paddingLeft: 42,
                                  paddingRight: 14,
                                  paddingTop: 10,
                                  paddingBottom: 10,
                                  borderRadius: 10,
                                  border: "1px solid #cbd5e1",
                                  backgroundColor: "#faf9f6",
                                  color: "#1e293b",
                                  fontSize: 14,
                                  fontWeight: 500,
                                  outline: "none",
                                }}
                                className="focus:border-teal-500 focus:bg-white transition-all placeholder:text-slate-400"
                              />
                            </div>
                            <Button
                              type="primary"
                              size="large"
                              loading={queryLoading}
                              onClick={() => handleRunQuery()}
                              style={{
                                backgroundColor: "#0d6e65",
                                borderColor: "#0d6e65",
                                borderRadius: 10,
                                fontWeight: 700,
                                fontSize: 13,
                                height: 42,
                                paddingLeft: 22,
                                paddingRight: 22,
                                display: "flex",
                                alignItems: "center",
                                gap: 6,
                                boxShadow: "0 2px 10px rgba(13, 110, 101, 0.35)",
                              }}
                              className="shrink-0"
                            >
                              Ask Database
                            </Button>
                          </div>

                          {/* Quick Suggested Queries / Hint Chips */}
                          <div className="mt-3 pt-2.5 border-t border-slate-100 flex items-center gap-2 flex-wrap">
                            <span style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                              Suggested:
                            </span>
                            {[
                              "Show top 5 departments by headcount",
                              "List all active employees and their roles",
                              "Total payroll expenses by department",
                            ].map((promptText, pIdx) => (
                              <button
                                key={pIdx}
                                type="button"
                                onClick={() => setUserQuery(promptText)}
                                style={{
                                  fontSize: 11.5,
                                  fontWeight: 500,
                                  color: "#475569",
                                  backgroundColor: "#f8fafc",
                                  border: "1px solid #e2e8f0",
                                  borderRadius: 6,
                                  padding: "3px 9px",
                                  cursor: "pointer",
                                  transition: "all 0.15s ease",
                                }}
                                className="hover:bg-teal-50 hover:text-teal-700 hover:border-teal-200"
                              >
                                {promptText}
                              </button>
                            ))}
                          </div>
                        </div>

                        {/* Interactive Disambiguation Prompt / Multi-Select Table Selection */}
                        {disambiguationData && !queryLoading && (
                          <div className="mt-4 p-5 rounded-2xl border border-teal-300 dark:border-teal-800 bg-teal-50/60 dark:bg-teal-950/20 shadow-md transition-all animate-fadeIn">
                            <div className="flex items-start gap-3.5">
                              <div className="p-2.5 rounded-xl bg-teal-100 dark:bg-teal-900/50 text-teal-700 dark:text-teal-400 mt-0.5 shadow-sm">
                                <QuestionCircleOutlined style={{ fontSize: 22 }} />
                              </div>
                              <div className="flex-1">
                                <div className="flex items-center justify-between flex-wrap gap-2">
                                  <Text strong style={{ fontSize: 16, color: "var(--app-text)" }}>
                                    {disambiguationData.message}
                                  </Text>
                                  <Tag color={(disambiguationData.entity_type === "table" || Boolean(disambiguationData.candidate_tables && disambiguationData.candidate_tables.length > 0) || (disambiguationData.options && disambiguationData.options.length > 0 && Boolean(disambiguationData.options[0].table || disambiguationData.options[0].table_name))) ? "cyan" : "orange"} style={{ borderRadius: 8, fontWeight: 700, padding: "2px 10px" }}>
                                    {(disambiguationData.entity_type === "table" || Boolean(disambiguationData.candidate_tables && disambiguationData.candidate_tables.length > 0) || (disambiguationData.options && disambiguationData.options.length > 0 && Boolean(disambiguationData.options[0].table || disambiguationData.options[0].table_name))) ? "Table Selection Required" : "Action Required"}
                                  </Tag>
                                </div>

                                {(disambiguationData.entity_type === "table" || Boolean(disambiguationData.candidate_tables && disambiguationData.candidate_tables.length > 0) || (disambiguationData.options && disambiguationData.options.length > 0 && Boolean(disambiguationData.options[0].table || disambiguationData.options[0].table_name))) ? (
                                  <div className="mt-3 space-y-3.5">
                                    <p className="text-xs text-gray-600 dark:text-gray-300 m-0">
                                      Your question was broad. Choose which candidate table(s) to query, or search any other table in this database:
                                    </p>

                                    {/* Live Table Filter Search Bar */}
                                    <div className="relative max-w-md">
                                      <Input
                                        placeholder="Filter tables (e.g. work_flows, users, monitor)..."
                                        prefix={<SearchOutlined style={{ color: "#0d6e65" }} />}
                                        value={tableSearchFilter}
                                        onChange={(e) => setTableSearchFilter(e.target.value)}
                                        allowClear
                                        size="middle"
                                        style={{ borderRadius: 8 }}
                                      />
                                    </div>

                                    {/* Candidate & Searched Tables Grid */}
                                    {(() => {
                                      // Extract candidate tables from candidate_tables OR options
                                      const rawCandidates = (disambiguationData.candidate_tables && disambiguationData.candidate_tables.length > 0)
                                        ? disambiguationData.candidate_tables
                                        : (disambiguationData.options || []);

                                      const filterLower = (tableSearchFilter || "").toLowerCase().trim();
                                      // Merge backend table_aliases with local/state tableCustomNames case-insensitively
                                      const aliasMap: Record<string, string[]> = {};
                                      const registerAliases = (source?: Record<string, string[]>) => {
                                        if (!source) return;
                                        Object.entries(source).forEach(([k, vals]) => {
                                          if (!vals || !Array.isArray(vals)) return;
                                          const kLower = k.toLowerCase();
                                          if (!aliasMap[kLower]) aliasMap[kLower] = [];
                                          vals.forEach((v) => {
                                            if (v && !aliasMap[kLower].includes(v)) aliasMap[kLower].push(v);
                                          });
                                          if (!aliasMap[k]) aliasMap[k] = aliasMap[kLower];
                                        });
                                      };
                                      registerAliases(tableCustomNames);
                                      registerAliases(disambiguationData.table_aliases);

                                      const getAliasesForTable = (tbl: string): string[] => {
                                        return aliasMap[tbl] || aliasMap[tbl.toLowerCase()] || [];
                                      };

                                      let displayTables: { name: string; isCandidate: boolean; score?: number; isBackup?: boolean }[] = [];
                                      const seenNames = new Set<string>();

                                      rawCandidates.forEach((c: any) => {
                                        const tName = typeof c === "string" ? c : (c.table_name || c.table || c.name || c.label || c.id);
                                        if (tName && typeof tName === "string" && !seenNames.has(tName.toLowerCase())) {
                                          seenNames.add(tName.toLowerCase());
                                          const aliases = getAliasesForTable(tName);
                                          const aliasMatches = aliases.some((a: string) => a.toLowerCase().includes(filterLower));
                                          if (!filterLower || tName.toLowerCase().includes(filterLower) || aliasMatches) {
                                            displayTables.push({
                                              name: tName,
                                              isCandidate: true,
                                              score: c.score,
                                              isBackup: Boolean(c.is_backup || tName.includes("_bk_") || tName.startsWith("archive_")),
                                            });
                                          }
                                        }
                                      });

                                      // Also include schema tables or all_tables if user searches or if candidates are empty
                                      const schemaTableList: string[] = [];
                                      if (disambiguationData.all_tables && disambiguationData.all_tables.length > 0) {
                                        schemaTableList.push(...disambiguationData.all_tables);
                                      }
                                      if (allDbTablesList && allDbTablesList.length > 0) {
                                        schemaTableList.push(...allDbTablesList);
                                      }
                                      if ((selectedKb as any)?.schema?.schemas) {
                                        Object.values((selectedKb as any).schema.schemas).forEach((s: any) => {
                                          if (s?.tables) {
                                            schemaTableList.push(...Object.keys(s.tables));
                                          }
                                        });
                                      }
                                      if (schemaData?.schemas) {
                                        Object.values(schemaData.schemas).forEach((s: any) => {
                                          if (s?.tables) {
                                            schemaTableList.push(...Object.keys(s.tables));
                                          }
                                        });
                                      }
                                      // Include all tables having aliases so they are always searchable
                                      Object.keys(aliasMap).forEach((t) => schemaTableList.push(t));

                                      schemaTableList.forEach((tName: string) => {
                                        if (tName && !seenNames.has(tName.toLowerCase())) {
                                          const aliases = getAliasesForTable(tName);
                                          const aliasMatches = aliases.some((a: string) => a.toLowerCase().includes(filterLower));
                                          if (filterLower && (tName.toLowerCase().includes(filterLower) || aliasMatches)) {
                                            seenNames.add(tName.toLowerCase());
                                            displayTables.push({
                                              name: tName,
                                              isCandidate: false,
                                            });
                                          }
                                        }
                                      });

                                      const allSelected = displayTables.length > 0 && displayTables.every((t) => selectedTablesForExecution.includes(t.name));

                                      return (
                                        <div className="space-y-3">
                                          {/* Select All Row */}
                                          <div className="flex items-center justify-between pb-1 border-b border-teal-200/60 dark:border-teal-900/60">
                                            <Checkbox
                                              checked={allSelected}
                                              indeterminate={selectedTablesForExecution.length > 0 && !allSelected}
                                              onChange={(e) => {
                                                if (e.target.checked) {
                                                  const newSel = Array.from(new Set([...selectedTablesForExecution, ...displayTables.map((t) => t.name)]));
                                                  setSelectedTablesForExecution(newSel);
                                                } else {
                                                  const displayedSet = new Set(displayTables.map((t) => t.name));
                                                  setSelectedTablesForExecution(selectedTablesForExecution.filter((x) => !displayedSet.has(x)));
                                                }
                                              }}
                                            >
                                              <span className="text-xs font-semibold text-gray-700 dark:text-gray-200">
                                                Select All Displayed ({displayTables.length} tables)
                                              </span>
                                            </Checkbox>

                                            <span className="text-xs text-teal-800 dark:text-teal-300 font-medium">
                                              {selectedTablesForExecution.length} selected
                                            </span>
                                          </div>

                                          {/* Checkbox List */}
                                          <div className="max-h-56 overflow-y-auto pr-1 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
                                            {displayTables.map((item, idx) => {
                                              const isChecked = selectedTablesForExecution.includes(item.name);
                                              return (
                                                <div
                                                  key={idx}
                                                  onClick={() => {
                                                    if (isChecked) {
                                                      setSelectedTablesForExecution(selectedTablesForExecution.filter((t) => t !== item.name));
                                                    } else {
                                                      setSelectedTablesForExecution([...selectedTablesForExecution, item.name]);
                                                    }
                                                  }}
                                                  className={`flex items-center justify-between p-2 rounded-lg border text-xs cursor-pointer transition-all ${
                                                    isChecked
                                                      ? "bg-teal-100/70 dark:bg-teal-900/40 border-teal-500 font-semibold"
                                                      : "bg-white dark:bg-slate-900/60 border-slate-200 dark:border-slate-800 hover:border-teal-400"
                                                  }`}
                                                >
                                                  {(() => {
                                                    const aliases = getAliasesForTable(item.name);
                                                    const primaryAlias = aliases.length > 0 ? aliases.join(", ") : null;
                                                    const fullTitle = primaryAlias ? `${item.name} / ${primaryAlias}` : item.name;

                                                    return (
                                                      <div className="flex items-center gap-2 truncate">
                                                        <Checkbox
                                                          checked={isChecked}
                                                          onChange={(e) => e.stopPropagation()}
                                                        />
                                                        <div className="flex items-baseline gap-1.5 truncate" title={fullTitle}>
                                                          <span className="truncate text-gray-800 dark:text-gray-100 font-medium">
                                                            {item.name}
                                                          </span>
                                                          {primaryAlias && (
                                                            <span className="text-[11px] text-teal-600 dark:text-teal-400 truncate font-normal">
                                                              / {primaryAlias}
                                                            </span>
                                                          )}
                                                        </div>
                                                      </div>
                                                    );
                                                  })()}
                                                  {item.score !== undefined && (
                                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-teal-50 dark:bg-teal-950 text-teal-700 dark:text-teal-300 border border-teal-200 dark:border-teal-800 shrink-0">
                                                      {item.score}
                                                    </span>
                                                  )}
                                                </div>
                                              );
                                            })}
                                          </div>

                                          {/* Execution Strategy Selector when multiple tables are selected */}
                                          {selectedTablesForExecution.length > 1 && (
                                            <div className="p-3 bg-teal-50/70 dark:bg-slate-900/80 rounded-xl border border-teal-200 dark:border-teal-900/70 text-xs">
                                              <div className="font-semibold text-teal-900 dark:text-teal-200 mb-2 flex items-center justify-between">
                                                <span>Choose Execution Strategy for {selectedTablesForExecution.length} Tables:</span>
                                                <Tag color="cyan" style={{ fontSize: 10, borderRadius: 4 }}>Required</Tag>
                                              </div>
                                              <Radio.Group
                                                value={multiTableStrategy}
                                                onChange={(e) => setMultiTableStrategy(e.target.value)}
                                                className="flex flex-col gap-2"
                                              >
                                                <Radio value="separate" className="items-start">
                                                  <div className="ml-1">
                                                    <div className="font-bold text-gray-800 dark:text-gray-100">
                                                      Separate Execution (Per-Table Breakdown)
                                                      <span className="ml-1.5 text-[10px] text-teal-600 dark:text-teal-400 font-normal">[Recommended]</span>
                                                    </div>
                                                    <div className="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">
                                                      Executes the query independently on each selected table and returns all results in a clear table-by-table summary.
                                                    </div>
                                                  </div>
                                                </Radio>
                                                <Radio value="union" className="items-start">
                                                  <div className="ml-1">
                                                    <div className="font-bold text-gray-800 dark:text-gray-100">
                                                      Union Search (Merged Results)
                                                    </div>
                                                    <div className="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">
                                                      Combines matching records across selected tables using SQL UNION into one unified view.
                                                    </div>
                                                  </div>
                                                </Radio>
                                              </Radio.Group>
                                            </div>
                                          )}

                                          {/* Action Execution Button */}
                                          <div className="flex items-center gap-2 pt-2 border-t border-teal-200/60 dark:border-teal-900/60">
                                            <Button
                                              type="primary"
                                              size="middle"
                                              disabled={selectedTablesForExecution.length === 0}
                                              style={{
                                                borderRadius: 8,
                                                fontWeight: 700,
                                                backgroundColor: selectedTablesForExecution.length > 0 ? "#0d6e65" : undefined,
                                                borderColor: selectedTablesForExecution.length > 0 ? "#0d6e65" : undefined,
                                              }}
                                              onClick={() => {
                                                const sel = [...selectedTablesForExecution];
                                                const strat = sel.length > 1 ? multiTableStrategy : undefined;
                                                setDisambiguationData(null);
                                                setSelectedTablesForExecution([]);
                                                setTableSearchFilter("");
                                                handleRunQuery(userQuery, undefined, sel, strat);
                                              }}
                                            >
                                              Execute on {selectedTablesForExecution.length} Selected Table{selectedTablesForExecution.length === 1 ? "" : "s"}
                                              {selectedTablesForExecution.length > 1 ? (multiTableStrategy === "separate" ? " (Separate)" : " (Union)") : ""}
                                            </Button>

                                            <Button
                                              type="text"
                                              danger
                                              size="small"
                                              onClick={() => {
                                                setDisambiguationData(null);
                                                setSelectedTablesForExecution([]);
                                                setTableSearchFilter("");
                                              }}
                                            >
                                              Cancel
                                            </Button>
                                          </div>
                                        </div>
                                      );
                                    })()}
                                  </div>
                                ) : (
                                  <div>
                                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 mb-4">
                                      Multiple matching records were found in the database. Please select which one you want to inspect, or query all of them:
                                    </p>
                                    <div className="flex flex-wrap items-center gap-2.5">
                                      {disambiguationData.options.map((opt: any, idx: number) => {
                                        const isAll = opt.id === "all" || Array.isArray(opt.id);
                                        return (
                                          <Button
                                            key={idx}
                                            type={isAll ? "default" : "primary"}
                                            style={{
                                              borderRadius: 8,
                                              fontWeight: 600,
                                              borderColor: isAll ? "#d97706" : "#0d6e65",
                                              color: isAll ? "#d97706" : "#ffffff",
                                              backgroundColor: isAll ? "#ffffff" : "#0d6e65",
                                              boxShadow: "0 2px 4px rgba(0,0,0,0.08)",
                                            }}
                                            onClick={() => handleSelectDisambiguation(opt)}
                                          >
                                            {opt.label || opt.name}
                                          </Button>
                                        );
                                      })}
                                      <Button
                                        type="text"
                                        danger
                                        size="small"
                                        onClick={() => setDisambiguationData(null)}
                                      >
                                        Cancel
                                      </Button>
                                    </div>
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        )}

                        {/* Real-Time Pipeline Progress Stepper (Phase 3E) */}
                        {(queryLoading || streamEvents.length > 0 || streamError || isCancelled) && (
                          <div className="mt-2">
                            <DatabasePipelineProgress
                              events={streamEvents}
                              isStreaming={queryLoading}
                              onCancel={handleCancelQuery}
                              error={streamError}
                              cancelled={isCancelled}
                            />
                          </div>
                        )}

                        {groundedAnswer && !queryLoading && (
                          <Card
                            style={{
                              background: "var(--app-surface)",
                              borderColor: "var(--app-border)",
                              borderRadius: 16,
                              boxShadow: "0 4px 20px rgba(0, 0, 0, 0.05)",
                              marginBottom: "2.5rem",
                            }}
                            styles={{ body: { padding: 24 } }}
                          >
                            {/* Executive Header: Status Badges & Action Toolbar */}
                            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-[var(--app-border)] pb-4">
                              <div className="flex flex-wrap items-center gap-2">
                                <Tag
                                  color={groundedAnswer.grounding_status.includes("VERIFIED") ? "green" : "cyan"}
                                  icon={<CheckCircleOutlined />}
                                  style={{ padding: "3px 8px", borderRadius: 10, fontWeight: 600 }}
                                >
                                  {groundedAnswer.grounding_status.replace("GroundingStatus.", "").replace("_", " ")}
                                </Tag>
                                <Tag
                                  color={groundedAnswer.verification_status === "PASSED" ? "blue" : "orange"}
                                  icon={<SafetyCertificateOutlined />}
                                  style={{ padding: "3px 8px", borderRadius: 10 }}
                                >
                                  VERIFICATION: {groundedAnswer.verification_status}
                                </Tag>
                                <Tag
                                  color="purple"
                                  style={{ padding: "3px 8px", borderRadius: 10 }}
                                >
                                  {groundedAnswer.answer_type.toUpperCase()}
                                </Tag>
                                {(groundedAnswer.row_count !== undefined || effectiveRows.length > 0) && (
                                  <Tag color="geekblue" style={{ padding: "3px 8px", borderRadius: 10 }}>
                                    {groundedAnswer.row_count || effectiveRows.length} {(groundedAnswer.row_count || effectiveRows.length) === 1 ? "Record" : "Records"}
                                  </Tag>
                                )}
                                {groundedAnswer.pipeline_trace?.execution?.execution_time_ms && (
                                  <Tag color="default" style={{ padding: "3px 8px", borderRadius: 10 }}>
                                    ⚡ {groundedAnswer.pipeline_trace.execution.execution_time_ms.toFixed(1)} ms
                                  </Tag>
                                )}
                              </div>

                              <div className="shrink-0 flex items-center gap-2">
                                <Tooltip title="Copy full response text to clipboard">
                                  <Button
                                    icon={<CopyOutlined />}
                                    onClick={handleCopyAnswer}
                                    size="small"
                                  >
                                    {copiedAnswer ? "Copied!" : "Copy Answer"}
                                  </Button>
                                </Tooltip>
                                {effectiveRows.length > 0 && (
                                  <Tooltip title="Export records as CSV spreadsheet">
                                    <Button
                                      icon={<DownloadOutlined />}
                                      onClick={handleExportCSV}
                                      size="small"
                                    >
                                      Export CSV
                                    </Button>
                                  </Tooltip>
                                )}
                                <Button
                                  icon={<EyeOutlined />}
                                  onClick={() => {
                                    setInspectedTrace(null);
                                    setObservabilityOpen(true);
                                  }}
                                  size="small"
                                >
                                  Inspect Trace
                                </Button>
                              </div>
                            </div>

                            {/* Query Execution Notices */}
                            {groundedAnswer.warnings && groundedAnswer.warnings.length > 0 && (
                              <div className="mt-4">
                                <Alert
                                  type="warning"
                                  showIcon
                                  title="Query Execution Notices"
                                  description={
                                    <ul className="list-disc pl-4 text-xs mt-1">
                                      {groundedAnswer.warnings.map((w, i) => (
                                        <li key={i}>{w}</li>
                                      ))}
                                    </ul>
                                  }
                                />
                              </div>
                            )}

                            {/* Main Content Area */}
                            {isTabularAnswer && effectiveRows.length > 0 ? (
                              <div className="mt-5">
                                <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 mb-3">
                                  <div className="flex items-center gap-2">
                                    <Text strong style={{ fontSize: 15, color: "var(--app-text)" }}>
                                      Relational Result Set ({groundedAnswer.row_count || effectiveRows.length} {(groundedAnswer.row_count || effectiveRows.length) === 1 ? "Record" : "Records"})
                                    </Text>
                                    {groundedAnswer.truncated && (
                                      <Tag color="orange">Truncated to Safe Limit</Tag>
                                    )}
                                  </div>

                                  <div className="flex items-center gap-3">
                                    <Input
                                      size="small"
                                      prefix={<SearchOutlined style={{ color: "#8c8c8c" }} />}
                                      placeholder="Filter records..."
                                      value={tableFilter}
                                      onChange={(e) => setTableFilter(e.target.value)}
                                      allowClear
                                      style={{ width: 220 }}
                                    />
                                    <Radio.Group
                                      size="small"
                                      value={answerViewMode}
                                      onChange={(e) => setAnswerViewMode(e.target.value)}
                                    >
                                      <Radio.Button value="formatted">Table View</Radio.Button>
                                      <Radio.Button value="raw">Raw Markdown</Radio.Button>
                                    </Radio.Group>
                                  </div>
                                </div>

                                {answerViewMode === "formatted" ? (
                                  <div className="space-y-4">
                                    {introMarkdownHtml && (
                                      <div
                                        className="grounded-markdown-container text-sm text-[var(--app-text)] mb-3"
                                        dangerouslySetInnerHTML={{ __html: introMarkdownHtml }}
                                      />
                                    )}
                                    <div className="w-full overflow-hidden rounded-xl border border-[var(--app-border)] bg-[var(--app-surface)]">
                                      <Table
                                        className="database-evidence-table"
                                        size="small"
                                        bordered
                                        dataSource={filteredEvidenceRows.map((r, i) => ({ ...r, key: i }))}
                                        columns={disambiguatedColumns}
                                        pagination={{
                                          defaultPageSize: 10,
                                          pageSizeOptions: ["10", "25", "50", "100"],
                                          showSizeChanger: true,
                                          showTotal: (total, range) => `Showing ${range[0]}-${range[1]} of ${total} records`,
                                        }}
                                        scroll={{ x: "max-content", y: 460 }}
                                        style={{
                                          background: "var(--app-surface)",
                                        }}
                                      />
                                    </div>
                                    {summaryMarkdownHtml && (
                                      <div className="p-4 rounded-xl bg-[var(--app-surface-muted)] border border-[var(--app-border)] text-sm text-[var(--app-text)] mt-3">
                                        <div
                                          className="grounded-markdown-container"
                                          dangerouslySetInnerHTML={{ __html: summaryMarkdownHtml }}
                                        />
                                      </div>
                                    )}
                                  </div>
                                ) : (
                                  <div className="p-4 rounded-xl bg-gray-900 border border-gray-800 text-gray-200 font-mono text-xs overflow-x-auto whitespace-pre">
                                    {groundedAnswer.answer_text}
                                  </div>
                                )}
                              </div>
                            ) : (
                              <div className="mt-4 p-5 rounded-xl bg-[var(--app-surface-muted)] border border-[var(--app-border)] overflow-x-auto max-w-full custom-scrollbar">
                                <div
                                  className="grounded-markdown-container max-w-full"
                                  dangerouslySetInnerHTML={{ __html: parsedMarkdownHtml }}
                                />
                              </div>
                            )}
                          </Card>
                        )}
                      </div>
                    ),
                  },
                  {
                    key: "telemetry",
                    label: (
                      <span className="flex items-center gap-1">
                        <ThunderboltOutlined /> Operations & Telemetry
                      </span>
                    ),
                    children: (
                      <div className="flex flex-col gap-4">
                        {/* Health & Diagnostic Probe Card */}
                        <div
                          style={{
                            backgroundColor: "#ffffff",
                            border: "1px solid #e2e8f0",
                            borderRadius: 16,
                            padding: "20px 22px",
                            boxShadow: "0 2px 10px rgba(0, 0, 0, 0.03)",
                          }}
                        >
                          {/* Header */}
                          <div className="flex items-center justify-between pb-4 border-b border-slate-100">
                            <div className="flex items-center gap-2.5">
                              <div
                                style={{
                                  width: 36,
                                  height: 36,
                                  borderRadius: 10,
                                  backgroundColor: "#f0fdfa",
                                  border: "1px solid #99f6e4",
                                  color: "#0d9488",
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                }}
                              >
                                <SafetyCertificateOutlined style={{ fontSize: 18 }} />
                              </div>
                              <div>
                                <h3 style={{ margin: 0, fontSize: 15, fontWeight: 750, color: "#0f172a" }}>
                                  Subsystem Health & Diagnostics Probe
                                </h3>
                                <p style={{ margin: 0, fontSize: 11.5, color: "#64748b", marginTop: 2 }}>
                                  Live connection probe and runtime security posture
                                </p>
                              </div>
                            </div>

                            <Button
                              size="small"
                              icon={<SyncOutlined spin={metricsLoading} style={{ fontSize: 11 }} />}
                              onClick={() => fetchMetricsAndHealth(selectedKb.id)}
                              style={{
                                borderRadius: 8,
                                fontSize: 12,
                                fontWeight: 600,
                                borderColor: "#cbd5e1",
                                color: "#334155",
                                height: 32,
                                paddingLeft: 12,
                                paddingRight: 12,
                              }}
                              className="hover:border-teal-500 hover:text-teal-600"
                            >
                              Run Diagnostics
                            </Button>
                          </div>

                          {/* 4 Health Status Cards */}
                          <div className="grid grid-cols-2 sm:grid-cols-2 xl:grid-cols-4 gap-3.5 mt-4">
                            {/* 1. Connectivity */}
                            <div
                              style={{
                                padding: "14px 16px",
                                borderRadius: 12,
                                backgroundColor: healthData?.status === "HEALTHY" ? "#f0fdf4" : "#fef2f2",
                                border: healthData?.status === "HEALTHY" ? "1px solid #bbf7d0" : "1px solid #fecaca",
                                display: "flex",
                                flexDirection: "column",
                                justifyContent: "space-between",
                                minHeight: 90,
                              }}
                            >
                              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                                <span style={{ fontSize: 12, fontWeight: 700, color: "#475569" }}>
                                  Connectivity
                                </span>
                                <span
                                  style={{
                                    width: 7,
                                    height: 7,
                                    borderRadius: "50%",
                                    backgroundColor: healthData?.status === "HEALTHY" ? "#10b981" : "#ef4444",
                                  }}
                                />
                              </div>
                              <div style={{ marginTop: 8 }}>
                                <span
                                  style={{
                                    fontSize: 11.5,
                                    fontWeight: 800,
                                    padding: "3px 9px",
                                    borderRadius: 9999,
                                    backgroundColor: healthData?.status === "HEALTHY" ? "#dcfce7" : "#fee2e2",
                                    color: healthData?.status === "HEALTHY" ? "#15803d" : "#b91c1c",
                                    border: healthData?.status === "HEALTHY" ? "1px solid #86efac" : "1px solid #fca5a5",
                                    display: "inline-flex",
                                    alignItems: "center",
                                    gap: 5,
                                    whiteSpace: "nowrap",
                                  }}
                                >
                                  {healthData?.status === "HEALTHY" ? "✓ HEALTHY" : (healthData?.status || "UNKNOWN")}
                                </span>
                              </div>
                            </div>

                            {/* 2. Target DB Ping */}
                            <div
                              style={{
                                padding: "14px 16px",
                                borderRadius: 12,
                                backgroundColor: "#f8fafc",
                                border: "1px solid #e2e8f0",
                                display: "flex",
                                flexDirection: "column",
                                justifyContent: "space-between",
                                minHeight: 90,
                              }}
                            >
                              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                                <span style={{ fontSize: 12, fontWeight: 700, color: "#475569" }}>
                                  Target DB Ping
                                </span>
                                <span style={{ fontSize: 13, color: "#0d9488" }}>⚡</span>
                              </div>
                              <div style={{ marginTop: 8, display: "flex", alignItems: "baseline", gap: 3 }}>
                                <span style={{ fontSize: 20, fontWeight: 850, fontFamily: "ui-monospace, monospace", color: "#0f766e" }}>
                                  {healthData?.database_ping_ms !== undefined ? healthData.database_ping_ms : "N/A"}
                                </span>
                                {healthData?.database_ping_ms !== undefined && (
                                  <span style={{ fontSize: 11.5, fontWeight: 600, color: "#64748b" }}>ms</span>
                                )}
                              </div>
                            </div>

                            {/* 3. Read-Only Policy */}
                            <div
                              style={{
                                padding: "14px 16px",
                                borderRadius: 12,
                                backgroundColor: "#f0f9ff",
                                border: "1px solid #bae6fd",
                                display: "flex",
                                flexDirection: "column",
                                justifyContent: "space-between",
                                minHeight: 90,
                              }}
                            >
                              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                                <span style={{ fontSize: 12, fontWeight: 700, color: "#0369a1" }}>
                                  Read-Only Policy
                                </span>
                                <span style={{ fontSize: 12, color: "#0284c7" }}>🔒</span>
                              </div>
                              <div style={{ marginTop: 8 }}>
                                <span
                                  style={{
                                    fontSize: 11,
                                    fontWeight: 750,
                                    padding: "3px 8px",
                                    borderRadius: 9999,
                                    backgroundColor: "#e0f2fe",
                                    color: "#0369a1",
                                    border: "1px solid #7dd3fc",
                                    display: "inline-block",
                                    whiteSpace: "nowrap",
                                  }}
                                >
                                  READ-ONLY (SELECT)
                                </span>
                              </div>
                            </div>

                            {/* 4. Schema State */}
                            <div
                              style={{
                                padding: "14px 16px",
                                borderRadius: 12,
                                backgroundColor: "#f5f3ff",
                                border: "1px solid #ddd6fe",
                                display: "flex",
                                flexDirection: "column",
                                justifyContent: "space-between",
                                minHeight: 90,
                              }}
                            >
                              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                                <span style={{ fontSize: 12, fontWeight: 700, color: "#6d28d9" }}>
                                  Schema State
                                </span>
                                <span style={{ fontSize: 12, color: "#7c3aed" }}>📊</span>
                              </div>
                              <div style={{ marginTop: 8 }}>
                                <span
                                  style={{
                                    fontSize: 11,
                                    fontWeight: 750,
                                    padding: "3px 8px",
                                    borderRadius: 9999,
                                    backgroundColor: "#ede9fe",
                                    color: "#6d28d9",
                                    border: "1px solid #c4b5fd",
                                    display: "inline-block",
                                  }}
                                >
                                  {healthData?.schema_freshness_status || "CURRENT"}
                                </span>
                              </div>
                            </div>
                          </div>
                        </div>

                        {/* Operational KPIs Card */}
                        <div
                          style={{
                            backgroundColor: "#ffffff",
                            border: "1px solid #e2e8f0",
                            borderRadius: 16,
                            padding: "20px 22px",
                            boxShadow: "0 2px 10px rgba(0, 0, 0, 0.03)",
                          }}
                        >
                          <div className="pb-3 border-b border-slate-100 flex items-center justify-between">
                            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 750, color: "#0f172a" }}>
                              Production Operational Metrics
                            </h3>
                            <span style={{ fontSize: 11.5, color: "#64748b", fontWeight: 500 }}>
                              Rolling telemetry & driver performance
                            </span>
                          </div>

                          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3.5 mt-4">
                            {/* 1. Success Rate */}
                            <div
                              style={{
                                padding: "15px 16px",
                                borderRadius: 14,
                                backgroundColor: "#ffffff",
                                border: "1px solid #e2e8f0",
                                boxShadow: "0 1px 3px rgba(0,0,0,0.02)",
                                display: "flex",
                                flexDirection: "column",
                                justifyContent: "space-between",
                                minHeight: 96,
                              }}
                              className="hover:border-slate-300 hover:shadow-xs transition-all"
                            >
                              <div className="flex items-center justify-between gap-1">
                                <span style={{ fontSize: 12.5, fontWeight: 650, color: "#64748b" }} title="Success Rate">
                                  Success Rate
                                </span>
                                <span style={{ fontSize: 13, color: "#059669" }}>✓</span>
                              </div>
                              <div style={{ marginTop: 8, display: "flex", alignItems: "baseline", gap: 3 }}>
                                <span style={{ fontSize: 22, fontWeight: 800, color: "#059669", fontFamily: "ui-monospace, monospace", lineHeight: 1 }}>
                                  {metricsData ? (metricsData.rates.query_success_rate * 100).toFixed(1) : "100.0"}
                                </span>
                                <span style={{ fontSize: 12, fontWeight: 600, color: "#059669" }}>%</span>
                              </div>
                            </div>

                            {/* 2. Total Queries */}
                            <div
                              style={{
                                padding: "15px 16px",
                                borderRadius: 14,
                                backgroundColor: "#ffffff",
                                border: "1px solid #e2e8f0",
                                boxShadow: "0 1px 3px rgba(0,0,0,0.02)",
                                display: "flex",
                                flexDirection: "column",
                                justifyContent: "space-between",
                                minHeight: 96,
                              }}
                              className="hover:border-slate-300 hover:shadow-xs transition-all"
                            >
                              <div className="flex items-center justify-between gap-1">
                                <span style={{ fontSize: 12.5, fontWeight: 650, color: "#64748b" }} title="Total Queries">
                                  Total Queries
                                </span>
                                <span style={{ fontSize: 13, color: "#64748b" }}>📊</span>
                              </div>
                              <div style={{ marginTop: 8, display: "flex", alignItems: "baseline", gap: 2 }}>
                                <span style={{ fontSize: 22, fontWeight: 800, color: "#1e293b", fontFamily: "ui-monospace, monospace", lineHeight: 1 }}>
                                  {metricsData?.counts.total_queries || 0}
                                </span>
                              </div>
                            </div>

                            {/* 3. P95 Latency */}
                            <div
                              style={{
                                padding: "15px 16px",
                                borderRadius: 14,
                                backgroundColor: "#ffffff",
                                border: "1px solid #e2e8f0",
                                boxShadow: "0 1px 3px rgba(0,0,0,0.02)",
                                display: "flex",
                                flexDirection: "column",
                                justifyContent: "space-between",
                                minHeight: 96,
                              }}
                              className="hover:border-slate-300 hover:shadow-xs transition-all"
                            >
                              <div className="flex items-center justify-between gap-1">
                                <span style={{ fontSize: 12.5, fontWeight: 650, color: "#64748b" }} title="P95 Latency">
                                  P95 Latency
                                </span>
                                <span style={{ fontSize: 13, color: "#0284c7" }}>⚡</span>
                              </div>
                              <div style={{ marginTop: 8, display: "flex", alignItems: "baseline", gap: 3 }}>
                                <span style={{ fontSize: 22, fontWeight: 800, color: "#0284c7", fontFamily: "ui-monospace, monospace", lineHeight: 1 }}>
                                  {metricsData?.latencies_ms.total.p95 ? metricsData.latencies_ms.total.p95.toFixed(0) : "0"}
                                </span>
                                <span style={{ fontSize: 12, fontWeight: 600, color: "#64748b" }}>ms</span>
                              </div>
                            </div>

                            {/* 4. DB Driver Avg */}
                            <div
                              style={{
                                padding: "15px 16px",
                                borderRadius: 14,
                                backgroundColor: "#ffffff",
                                border: "1px solid #e2e8f0",
                                boxShadow: "0 1px 3px rgba(0,0,0,0.02)",
                                display: "flex",
                                flexDirection: "column",
                                justifyContent: "space-between",
                                minHeight: 96,
                              }}
                              className="hover:border-slate-300 hover:shadow-xs transition-all"
                            >
                              <div className="flex items-center justify-between gap-1">
                                <span style={{ fontSize: 12.5, fontWeight: 650, color: "#64748b" }} title="DB Driver Avg">
                                  DB Driver Avg
                                </span>
                                <span style={{ fontSize: 13, color: "#7c3aed" }}>⏱️</span>
                              </div>
                              <div style={{ marginTop: 8, display: "flex", alignItems: "baseline", gap: 3 }}>
                                <span style={{ fontSize: 22, fontWeight: 800, color: "#7c3aed", fontFamily: "ui-monospace, monospace", lineHeight: 1 }}>
                                  {metricsData?.latencies_ms.database_execution.avg ? metricsData.latencies_ms.database_execution.avg.toFixed(1) : "0"}
                                </span>
                                <span style={{ fontSize: 12, fontWeight: 600, color: "#64748b" }}>ms</span>
                              </div>
                            </div>

                            {/* 5. Security Rejections */}
                            <div
                              style={{
                                padding: "15px 16px",
                                borderRadius: 14,
                                backgroundColor: "#ffffff",
                                border: "1px solid #e2e8f0",
                                boxShadow: "0 1px 3px rgba(0,0,0,0.02)",
                                display: "flex",
                                flexDirection: "column",
                                justifyContent: "space-between",
                                minHeight: 96,
                              }}
                              className="hover:border-slate-300 hover:shadow-xs transition-all"
                            >
                              <div className="flex items-center justify-between gap-1">
                                <span style={{ fontSize: 12.5, fontWeight: 650, color: "#64748b" }} title="Security Rejections">
                                  Security Rejections
                                </span>
                                <span style={{ fontSize: 13, color: metricsData?.counts.security_rejections ? "#e11d48" : "#059669" }}>🛡️</span>
                              </div>
                              <div style={{ marginTop: 8, display: "flex", alignItems: "baseline", gap: 2 }}>
                                <span
                                  style={{
                                    fontSize: 22,
                                    fontWeight: 800,
                                    color: metricsData?.counts.security_rejections ? "#e11d48" : "#059669",
                                    fontFamily: "ui-monospace, monospace",
                                    lineHeight: 1,
                                  }}
                                >
                                  {metricsData?.counts.security_rejections || 0}
                                </span>
                              </div>
                            </div>

                            {/* 6. Fallback Rate */}
                            <div
                              style={{
                                padding: "15px 16px",
                                borderRadius: 14,
                                backgroundColor: "#ffffff",
                                border: "1px solid #e2e8f0",
                                boxShadow: "0 1px 3px rgba(0,0,0,0.02)",
                                display: "flex",
                                flexDirection: "column",
                                justifyContent: "space-between",
                                minHeight: 96,
                              }}
                              className="hover:border-slate-300 hover:shadow-xs transition-all"
                            >
                              <div className="flex items-center justify-between gap-1">
                                <span style={{ fontSize: 12.5, fontWeight: 650, color: "#64748b" }} title="Fallback Rate">
                                  Fallback Rate
                                </span>
                                <span style={{ fontSize: 13, color: "#d97706" }}>🔄</span>
                              </div>
                              <div style={{ marginTop: 8, display: "flex", alignItems: "baseline", gap: 3 }}>
                                <span style={{ fontSize: 22, fontWeight: 800, color: "#d97706", fontFamily: "ui-monospace, monospace", lineHeight: 1 }}>
                                  {metricsData ? (metricsData.rates.fallback_rate * 100).toFixed(1) : "0.0"}
                                </span>
                                <span style={{ fontSize: 12, fontWeight: 600, color: "#d97706" }}>%</span>
                              </div>
                            </div>
                          </div>
                        </div>

                        {/* Pipeline Stage Latencies Breakdown */}
                        <div
                          style={{
                            backgroundColor: "#ffffff",
                            border: "1px solid #e2e8f0",
                            borderRadius: 16,
                            padding: "20px 22px",
                            boxShadow: "0 2px 10px rgba(0, 0, 0, 0.03)",
                          }}
                        >
                          <div className="pb-3 border-b border-slate-100 flex items-center justify-between">
                            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 750, color: "#0f172a" }}>
                              Stage Latency Breakdown & Observability Overview
                            </h3>
                            <span style={{ fontSize: 11.5, color: "#64748b", fontWeight: 500 }}>
                              5-stage query execution pipeline
                            </span>
                          </div>

                          <div className="flex flex-col divide-y divide-slate-100 mt-2">
                            {[
                              {
                                step: "1",
                                title: "Schema Retrieval (Phase 2A)",
                                desc: "Semantic cosine ranking & join graph discovery",
                              },
                              {
                                step: "2",
                                title: "Query Planning (Phase 2B)",
                                desc: "QueryPlanIR schema validation & join safety",
                              },
                              {
                                step: "3",
                                title: "Candidate SQL Generation & AST Policy (Phase 2B)",
                                desc: "Parameterization & strict read-only AST boundary",
                              },
                              {
                                step: "4",
                                title: "Safe Driver Execution (Phase 2C)",
                                desc: "asyncpg read-only session with strict timeouts",
                              },
                              {
                                step: "5",
                                title: "Grounded Synthesis & Verification (Phase 2D)",
                                desc: "Deterministic fast-path & entity anti-hallucination verification",
                              },
                            ].map((stage, idx) => (
                              <div key={idx} className="flex flex-col sm:flex-row sm:items-center justify-between py-2.5 gap-2">
                                <div className="flex items-center gap-2.5">
                                  <span
                                    style={{
                                      width: 22,
                                      height: 22,
                                      borderRadius: "50%",
                                      backgroundColor: "#f0fdfa",
                                      color: "#0f766e",
                                      border: "1px solid #99f6e4",
                                      display: "flex",
                                      alignItems: "center",
                                      justifyContent: "center",
                                      fontSize: 11,
                                      fontWeight: 800,
                                    }}
                                  >
                                    {stage.step}
                                  </span>
                                  <span style={{ fontSize: 12.5, fontWeight: 650, color: "#334155" }}>
                                    {stage.title}
                                  </span>
                                </div>
                                <span
                                  style={{
                                    fontSize: 12,
                                    fontFamily: "ui-monospace, monospace",
                                    fontWeight: 500,
                                    color: "#0f766e",
                                    backgroundColor: "#f8fafc",
                                    padding: "2px 8px",
                                    borderRadius: 6,
                                    border: "1px solid #e2e8f0",
                                  }}
                                >
                                  {stage.desc}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    ),
                  },
                  {
                    key: "audit",
                    label: (
                      <span className="flex items-center gap-1">
                        <SafetyCertificateOutlined /> Audit Trail & Compliance
                      </span>
                    ),
                    children: (
                      <Card
                        title={
                          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                            <span>Historical Query Execution Audit Trail</span>
                            <Space>
                              <Select
                                value={auditStatusFilter}
                                onChange={(val) => {
                                  setAuditStatusFilter(val);
                                  if (selectedKb) fetchAuditLogs(selectedKb.id, 1, val);
                                }}
                                style={{ width: 160 }}
                                options={[
                                  { value: "ALL", label: "All Statuses" },
                                  { value: "SUCCESS", label: "SUCCESS" },
                                  { value: "SECURITY_REJECTED", label: "SECURITY_REJECTED" },
                                  { value: "QUERY_FAILED", label: "QUERY_FAILED" },
                                ]}
                              />
                              <Button
                                icon={<SyncOutlined spin={auditLoading} />}
                                onClick={() => selectedKb && fetchAuditLogs(selectedKb.id, auditPage, auditStatusFilter)}
                              >
                                Refresh
                              </Button>
                            </Space>
                          </div>
                        }
                        style={{
                          background: "var(--app-surface)",
                          borderColor: "var(--app-border)",
                          borderRadius: 12,
                        }}
                      >
                        <div className="mb-3 text-xs text-gray-400">
                          <Tag color="cyan">Zero-Data Leakage Enforced</Tag>
                          SQL parameter values are type-abstracted and database row contents are never logged.
                        </div>
                        <Table
                          size="small"
                          loading={auditLoading}
                          dataSource={auditLogs.map((item) => ({ ...item, key: item.id }))}
                          columns={[
                            {
                              title: "Timestamp",
                              dataIndex: "request_timestamp",
                              key: "time",
                              render: (ts: string) => new Date(ts).toLocaleTimeString(),
                              width: 100,
                            },
                            {
                              title: "Sanitized Question",
                              dataIndex: "sanitized_user_query",
                              key: "query",
                              ellipsis: true,
                            },
                            {
                              title: "Status",
                              dataIndex: "final_status",
                              key: "status",
                              width: 140,
                              render: (st: string) => {
                                let color = "green";
                                if (st === "SECURITY_REJECTED") color = "red";
                                if (st === "QUERY_FAILED") color = "orange";
                                return <Tag color={color}>{st}</Tag>;
                              },
                            },
                            {
                              title: "Latency",
                              dataIndex: "total_latency_ms",
                              key: "latency",
                              width: 100,
                              render: (ms: number) => `${ms.toFixed(1)} ms`,
                            },
                            {
                              title: "Rows",
                              dataIndex: "row_count",
                              key: "rows",
                              width: 70,
                            },
                            {
                              title: "Action",
                              key: "action",
                              width: 90,
                              render: (_: any, record: AuditLogEntry) => (
                                <Button
                                  size="small"
                                  type="link"
                                  onClick={() => {
                                    setInspectedTrace(record);
                                    setObservabilityOpen(true);
                                  }}
                                >
                                  Inspect
                                </Button>
                              ),
                            },
                          ]}
                          pagination={{
                            current: auditPage,
                            pageSize: 20,
                            total: auditTotal,
                            onChange: (p) => selectedKb && fetchAuditLogs(selectedKb.id, p, auditStatusFilter),
                          }}
                          scroll={{ x: "max-content" }}
                        />
                      </Card>
                    ),
                  },
                ]}
              />
            </>
          ) : (
            <Card
              style={{
                background: "var(--app-surface)",
                borderColor: "var(--app-border)",
                textAlign: "center",
                padding: "60px 20px",
                borderRadius: 12,
              }}
            >
              <DatabaseOutlined style={{ fontSize: 48, color: "#8c8c8c", marginBottom: 16 }} />
              <Title level={4} style={{ color: "var(--app-text)" }}>Select a Database Knowledgebase</Title>
              <Paragraph style={{ color: "#8c8c8c" }}>
                Choose a connected database on the left or register a new one to start querying.
              </Paragraph>
            </Card>
          )}
        </div>
      </div>

      {/* Connect Database Modal */}
      <Modal
        title={
          <div className="flex items-center gap-2">
            <DatabaseOutlined style={{ color: "var(--app-primary)" }} />
            <span>Connect PostgreSQL Database Knowledgebase</span>
          </div>
        }
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={null}
        width={680}
      >
        <div className="flex flex-col gap-4 pt-4">
          <div>
            <Text strong>Knowledgebase Name</Text>
            <Input
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              placeholder="e.g. HRMS Enterprise Database"
              className="mt-1"
            />
          </div>

          <div>
            <Text strong>Description</Text>
            <TextArea
              rows={2}
              value={formDesc}
              onChange={(e) => setFormDesc(e.target.value)}
              placeholder="Optional description of this relational database source"
              className="mt-1"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <Text strong>Database Engine</Text>
              <Select
                value={formDbType}
                onChange={handleDbTypeChange}
                className="w-full mt-1"
                options={[
                  { label: "PostgreSQL", value: "postgresql" },
                  { label: "MariaDB", value: "mariadb" },
                  { label: "MySQL", value: "mysql" },
                ]}
              />
            </div>
            <div>
              <Text strong>SSL Mode</Text>
              <Select
                value={formSsl}
                onChange={(v) => setFormSsl(v)}
                className="w-full mt-1"
                options={[
                  { label: "Disable (Local / Internal)", value: "disable" },
                  { label: "Prefer (Opportunistic TLS)", value: "prefer" },
                  { label: "Require (Strict TLS)", value: "require" },
                ]}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <Text strong>Host</Text>
              <Input
                value={formHost}
                onChange={(e) => setFormHost(e.target.value)}
                placeholder="localhost"
                className="mt-1"
              />
            </div>
            <div>
              <Text strong>Port</Text>
              <InputNumber
                value={formPort}
                onChange={(v) => setFormPort(v || (formDbType === "postgresql" ? 5432 : 3306))}
                className="w-full mt-1"
              />
            </div>
          </div>

          <div>
            <Text strong>Database Name</Text>
            <Input
              value={formDbName}
              onChange={(e) => setFormDbName(e.target.value)}
              placeholder="gsearch_hrms_demo_db"
              className="mt-1"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <Text strong>Username</Text>
              <Input
                value={formUser}
                onChange={(e) => setFormUser(e.target.value)}
                placeholder="test_ro_user"
                className="mt-1"
              />
            </div>
            <div>
              <Text strong>Password</Text>
              <Input.Password
                value={formPassword}
                onChange={(e) => setFormPassword(e.target.value)}
                placeholder="Database password"
                className="mt-1"
              />
            </div>
          </div>

          {/* Test Connection Result Alert */}
          {testResult && (
            <Alert
              type={testResult.success ? "success" : "error"}
              showIcon
              title={testResult.success ? "Connection Succeeded" : "Connection Failed"}
              description={testResult.message}
            />
          )}

          {/* Action Buttons */}
          <div className="flex items-center justify-between pt-4 border-t border-[var(--app-border)]">
            <Button
              icon={<ThunderboltOutlined />}
              loading={testLoading}
              onClick={handleTestConnection}
            >
              Test Connection
            </Button>
            <Space>
              <Button onClick={() => setModalOpen(false)}>Cancel</Button>
              <Button
                type="primary"
                loading={saveLoading}
                onClick={handleSaveConnection}
                style={{ backgroundColor: "var(--app-primary)", borderColor: "var(--app-primary)" }}
              >
                Save & Connect
              </Button>
            </Space>
          </div>
        </div>
      </Modal>

      {/* Schema Explorer Modal */}
      <Modal
        title={
          !isDiagramHeaderHidden ? (
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pr-4 w-full">
            <div className="flex items-center gap-3 flex-wrap">
              {/* 3D Network Node Logo */}
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-teal-500/10 to-teal-500/20 flex items-center justify-center border border-teal-500/30 shadow-sm">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                  <circle cx="5" cy="12" r="3" fill="#0d9488" stroke="#ffffff" strokeWidth="1.5" />
                  <circle cx="12" cy="5" r="3" fill="#0284c7" stroke="#ffffff" strokeWidth="1.5" />
                  <circle cx="19" cy="12" r="3" fill="#0d9488" stroke="#ffffff" strokeWidth="1.5" />
                  <circle cx="12" cy="19" r="3" fill="#10b981" stroke="#ffffff" strokeWidth="1.5" />
                  <circle cx="12" cy="12" r="2.5" fill="#1e293b" />
                  <line x1="7.5" y1="10.5" x2="10" y2="7" stroke="#0f766e" strokeWidth="1.5" />
                  <line x1="14" y1="7" x2="16.5" y2="10.5" stroke="#0f766e" strokeWidth="1.5" />
                  <line x1="16.5" y1="13.5" x2="14" y2="17" stroke="#0f766e" strokeWidth="1.5" />
                  <line x1="10" y1="17" x2="7.5" y2="13.5" stroke="#0f766e" strokeWidth="1.5" />
                  <line x1="5" y1="12" x2="9.5" y2="12" stroke="#0d9488" strokeWidth="1.5" />
                  <line x1="14.5" y1="12" x2="19" y2="12" stroke="#0d9488" strokeWidth="1.5" />
                </svg>
              </div>

              {/* Title & Badges */}
              <div className="flex items-center gap-2.5 flex-wrap">
                <span className="font-extrabold text-lg text-slate-800 dark:text-slate-100 tracking-tight">
                  Canonical Schema Intelligence
                </span>

                {/* Engine & Status Badge */}
                <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-sky-50 dark:bg-sky-950/40 text-sky-700 dark:text-sky-300 border border-sky-200 dark:border-sky-800">
                  <DatabaseOutlined style={{ fontSize: 12, color: "#0284c7" }} />
                  <span>{selectedKb?.database_type || "PostgreSQL"}</span>
                  <span className="text-sky-300">|</span>
                  <span className="text-emerald-600 dark:text-emerald-400 font-bold">Introspected</span>
                </div>

                {/* Fingerprint Badge with Reveal / Copy */}
                {schemaData?.fingerprint && (
                  <div
                    onClick={() => {
                      navigator.clipboard.writeText(schemaData.fingerprint);
                      toast.success("Fingerprint copied to clipboard!");
                    }}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700 cursor-pointer hover:bg-slate-200 transition-colors"
                    title="Click to copy full fingerprint"
                  >
                    <span>🔒</span>
                    <span>{schemaData.fingerprint.substring(0, 11)}...</span>
                    <span className="text-blue-500 font-sans font-semibold text-[11px] underline">Reveal</span>
                  </div>
                )}
              </div>
            </div>

            {/* Right Side Header Controls */}
            <div className="flex items-center gap-2.5 flex-wrap">
              <Segmented
                value={schemaViewMode}
                onChange={(val) => setSchemaViewMode(val as "list" | "diagram")}
                options={[
                  {
                    label: "ER Diagram",
                    value: "diagram",
                    icon: <ApartmentOutlined />,
                  },
                  {
                    label: "Data Dictionary",
                    value: "list",
                    icon: <TableOutlined />,
                  },
                ]}
                className="bg-slate-100 dark:bg-slate-800 font-semibold text-xs"
              />

              {schemaData && (
                <Dropdown
                  menu={{
                    items: [
                      {
                        key: "json",
                        label: "Download Schema as JSON (.json)",
                        icon: <FileTextOutlined />,
                        onClick: () => handleDownloadSchema("json"),
                      },
                      {
                        key: "sql",
                        label: "Download Schema as SQL DDL (.sql)",
                        icon: <CodeOutlined />,
                        onClick: () => handleDownloadSchema("sql"),
                      },
                    ],
                  }}
                >
                  <Button
                    type="primary"
                    icon={<DownloadOutlined />}
                    style={{
                      backgroundColor: "#0d6e65",
                      borderColor: "#0d6e65",
                      borderRadius: 10,
                      fontWeight: 700,
                      fontSize: 13,
                      padding: "6px 16px",
                      display: "flex",
                      alignItems: "center",
                      gap: 4,
                      boxShadow: "0 2px 8px rgba(13, 110, 101, 0.35)",
                    }}
                  >
                    Export <DownOutlined style={{ fontSize: 10 }} />
                  </Button>
                </Dropdown>
              )}

              <Button
                icon={schemaFullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
                onClick={() => setSchemaFullscreen(!schemaFullscreen)}
                title={schemaFullscreen ? "Exit Fullscreen" : "Fullscreen"}
                style={{ borderRadius: 10, border: "1px solid #cbd5e1" }}
              />
            </div>
          </div>
        ) : null}
        closable={!isDiagramHeaderHidden}
        open={schemaModalOpen}
        onCancel={() => {
          setSchemaModalOpen(false);
          setSchemaFullscreen(false);
          setSchemaEditMode(false);
        }}
        footer={null}
        width={schemaFullscreen || schemaEditMode ? "100vw" : "min(1440px, 97vw)"}
        style={schemaFullscreen || schemaEditMode ? { top: 0, margin: 0, paddingBottom: 0, maxWidth: "100vw" } : { top: 12 }}
        styles={{
          container: isDiagramHeaderHidden
            ? { borderRadius: 0, height: "100vh", display: "flex", flexDirection: "column", backgroundColor: "#faf9f6", padding: 0 }
            : schemaFullscreen
            ? { borderRadius: 0, height: "100vh", display: "flex", flexDirection: "column", backgroundColor: "#faf9f6" }
            : { borderRadius: 20, backgroundColor: "#faf9f6" },
          body: isDiagramHeaderHidden
            ? { flex: 1, overflowY: "hidden", padding: 0, backgroundColor: "#faf9f6", height: "100vh" }
            : schemaFullscreen
            ? { flex: 1, overflowY: schemaViewMode === "diagram" ? "hidden" : "auto", padding: schemaViewMode === "diagram" ? "12px 16px" : "16px 20px", backgroundColor: "#faf9f6" }
            : { padding: "16px 20px", backgroundColor: "#faf9f6" },
        }}
      >
        {schemaLoading ? (
          <div className="py-20 text-center">
            <Spin size="large" />
            <Paragraph style={{ marginTop: 16, color: "#8c8c8c" }}>
              Introspecting and loading canonical schema snapshot...
            </Paragraph>
          </div>
        ) : schemaData ? (
          <div>
            {/* The 4 Exact Executive Visual Stat Cards */}
            {((!schemaFullscreen && !schemaEditMode) || schemaViewMode === "list") && (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5 mb-4">
              {/* 1. ACTIVE TABLES CARD */}
              <div
                style={{
                  background: "linear-gradient(135deg, #094a44 0%, #0d6e65 40%, #159384 100%)",
                  borderRadius: 16,
                  padding: "16px 18px",
                  color: "#ffffff",
                  position: "relative",
                  overflow: "hidden",
                  boxShadow: "0 10px 20px -5px rgba(13, 110, 101, 0.3)",
                }}
              >
                <div className="flex items-start justify-between">
                  <div>
                    <span style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.8px", color: "rgba(255,255,255,0.85)", textTransform: "uppercase" }}>
                      ACTIVE TABLES
                    </span>
                    <div style={{ fontSize: 32, fontWeight: 900, lineHeight: 1.15, marginTop: 4, letterSpacing: "-0.5px" }}>
                      {schemaData.summary?.table_count ?? allSchemaTables.length}
                    </div>
                    <span style={{ fontSize: 12, fontWeight: 600, color: "rgba(255,255,255,0.9)", marginTop: 2, display: "block" }}>
                      Core Entities
                    </span>
                  </div>

                  {/* 3D Round Glass Table Badge */}
                  <div className="relative w-16 h-16 flex items-center justify-center flex-shrink-0">
                    <div
                      style={{
                        width: 54,
                        height: 54,
                        borderRadius: "50%",
                        backgroundColor: "rgba(255, 255, 255, 0.2)",
                        border: "2px solid rgba(255, 255, 255, 0.45)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        boxShadow: "0 6px 16px rgba(0,0,0,0.15)",
                        backdropFilter: "blur(4px)",
                      }}
                    >
                      <svg width="28" height="22" viewBox="0 0 28 22" fill="none">
                        <rect x="1" y="1" width="26" height="20" rx="3" fill="#ffffff" stroke="#10b981" strokeWidth="1.5" />
                        <line x1="1" y1="7" x2="27" y2="7" stroke="#10b981" strokeWidth="1.5" />
                        <line x1="1" y1="14" x2="27" y2="14" stroke="#10b981" strokeWidth="1.5" />
                        <line x1="10" y1="1" x2="10" y2="21" stroke="#10b981" strokeWidth="1.5" />
                        <line x1="19" y1="1" x2="19" y2="21" stroke="#10b981" strokeWidth="1.5" />
                      </svg>
                    </div>
                    {/* Bottom Sparkline */}
                    <svg className="absolute -bottom-1 -right-1 w-14 h-5" viewBox="0 0 50 18" fill="none">
                      <path d="M0 14 Q 15 16, 28 8 T 48 3" stroke="#a7f3d0" strokeWidth="2" fill="none" strokeLinecap="round" />
                      <circle cx="47" cy="3" r="2.5" fill="#ffffff" />
                    </svg>
                  </div>
                </div>
              </div>

              {/* 2. UNIQUE ATTRIBUTES CARD */}
              <div
                style={{
                  background: "linear-gradient(135deg, #0e1e2d 0%, #173347 50%, #204b66 100%)",
                  borderRadius: 16,
                  padding: "16px 18px",
                  color: "#ffffff",
                  position: "relative",
                  overflow: "hidden",
                  boxShadow: "0 10px 20px -5px rgba(23, 51, 71, 0.3)",
                }}
              >
                <div className="flex items-start justify-between">
                  <div>
                    <span style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.8px", color: "#94a3b8", textTransform: "uppercase" }}>
                      UNIQUE ATTRIBUTES
                    </span>
                    <div style={{ fontSize: 32, fontWeight: 900, lineHeight: 1.15, marginTop: 4, letterSpacing: "-0.5px" }}>
                      {(schemaData.summary?.column_count ?? 0).toLocaleString()}
                    </div>
                    <span style={{ fontSize: 12, fontWeight: 600, color: "#94a3b8", marginTop: 2, display: "block" }}>
                      Total Columns
                    </span>
                  </div>

                  {/* 3D Stacked Isometric Cubes */}
                  <div className="w-16 h-16 flex items-center justify-center flex-shrink-0">
                    <svg width="54" height="54" viewBox="0 0 54 54" fill="none">
                      {/* Top Cube (Yellow/Orange) */}
                      <polygon points="27,4 37,10 27,16 17,10" fill="#fcd34d" />
                      <polygon points="17,10 27,16 27,27 17,21" fill="#f59e0b" />
                      <polygon points="27,16 37,10 37,21 27,27" fill="#d97706" />

                      {/* Left Cube (Teal/Emerald) */}
                      <polygon points="16,22 26,28 16,34 6,28" fill="#6ee7b7" />
                      <polygon points="6,28 16,34 16,45 6,39" fill="#10b981" />
                      <polygon points="16,34 26,28 26,39 16,45" fill="#047857" />

                      {/* Right Cube (Blue/Indigo) */}
                      <polygon points="38,22 48,28 38,34 28,28" fill="#93c5fd" />
                      <polygon points="28,28 38,34 38,45 28,39" fill="#3b82f6" />
                      <polygon points="38,34 48,28 48,39 38,45" fill="#1d4ed8" />
                    </svg>
                  </div>
                </div>
              </div>

              {/* 3. LOGICAL CONSTRAINTS CARD */}
              <div
                style={{
                  background: "linear-gradient(135deg, #fef2d6 0%, #fedfa0 50%, #fed382 100%)",
                  borderRadius: 16,
                  padding: "16px 18px",
                  color: "#683506",
                  border: "1px solid #f6c05d",
                  position: "relative",
                  overflow: "hidden",
                  boxShadow: "0 10px 20px -5px rgba(245, 158, 11, 0.2)",
                }}
              >
                <div className="flex items-start justify-between">
                  <div>
                    <span style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.8px", color: "#78350f", textTransform: "uppercase" }}>
                      LOGICAL CONSTRAINTS
                    </span>
                    <div style={{ fontSize: 32, fontWeight: 900, lineHeight: 1.15, marginTop: 4, letterSpacing: "-0.5px", color: "#78350f" }}>
                      {schemaData.summary?.foreign_key_count ?? 0}
                    </div>
                    <span style={{ fontSize: 12, fontWeight: 600, color: "#92400e", marginTop: 2, display: "block" }}>
                      FK, PK, Graph Join Counts
                    </span>
                  </div>

                  {/* 3D Golden Key & Lock Illustration */}
                  <div className="relative w-16 h-16 flex items-center justify-center flex-shrink-0">
                    <svg width="52" height="48" viewBox="0 0 52 48" fill="none">
                      {/* Golden Key */}
                      <circle cx="16" cy="18" r="9" fill="#f59e0b" stroke="#b45309" strokeWidth="2" />
                      <circle cx="16" cy="18" r="4" fill="#fef3c7" />
                      <rect x="23" y="15" width="22" height="5" rx="1.5" fill="#f59e0b" stroke="#b45309" strokeWidth="1.5" />
                      <rect x="36" y="20" width="4" height="6" rx="1" fill="#f59e0b" stroke="#b45309" strokeWidth="1.5" />
                      <rect x="41" y="20" width="3" height="4" rx="1" fill="#f59e0b" stroke="#b45309" strokeWidth="1.5" />

                      {/* Small Green Padlock */}
                      <rect x="26" y="26" width="18" height="15" rx="3" fill="#10b981" stroke="#047857" strokeWidth="1.5" />
                      <path d="M30 26 V21 C30 18 34 18 34 21 V26" stroke="#047857" strokeWidth="2" fill="none" />
                      <circle cx="35" cy="33" r="1.8" fill="#ffffff" />
                    </svg>

                    {/* Bottom Gold Sparkline */}
                    <svg className="absolute -bottom-1 -right-1 w-14 h-5" viewBox="0 0 50 18" fill="none">
                      <path d="M0 13 Q 15 15, 28 8 T 48 3" stroke="#b45309" strokeWidth="2" fill="none" strokeLinecap="round" />
                      <circle cx="47" cy="3" r="2.5" fill="#b45309" />
                    </svg>
                  </div>
                </div>
              </div>

              {/* 4. GRAPH RELATIONS CARD */}
              <div
                style={{
                  background: "linear-gradient(135deg, #24164b 0%, #3e267d 50%, #5733a8 100%)",
                  borderRadius: 16,
                  padding: "16px 18px",
                  color: "#ffffff",
                  position: "relative",
                  overflow: "hidden",
                  boxShadow: "0 10px 20px -5px rgba(62, 38, 125, 0.3)",
                }}
              >
                <div className="flex items-start justify-between">
                  <div>
                    <span style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.8px", color: "#c7d2fe", textTransform: "uppercase" }}>
                      GRAPH RELATIONS
                    </span>
                    <div style={{ fontSize: 32, fontWeight: 900, lineHeight: 1.15, marginTop: 4, letterSpacing: "-0.5px" }}>
                      {schemaData.summary?.relationship_count ?? 0}
                    </div>
                    <span style={{ fontSize: 12, fontWeight: 600, color: "#c7d2fe", marginTop: 2, display: "block" }}>
                      Active Joins & Network Density
                    </span>
                  </div>

                  {/* 3D Glowing Isometric Network Cluster */}
                  <div className="w-16 h-16 flex items-center justify-center flex-shrink-0">
                    <svg width="52" height="52" viewBox="0 0 52 52" fill="none">
                      {/* Connection Lines */}
                      <line x1="26" y1="26" x2="10" y2="12" stroke="#818cf8" strokeWidth="1.5" strokeDasharray="2 2" />
                      <line x1="26" y1="26" x2="42" y2="12" stroke="#a78bfa" strokeWidth="1.5" />
                      <line x1="26" y1="26" x2="10" y2="40" stroke="#818cf8" strokeWidth="1.5" />
                      <line x1="26" y1="26" x2="42" y2="40" stroke="#a78bfa" strokeWidth="1.5" strokeDasharray="2 2" />

                      {/* Outer Nodes */}
                      <circle cx="10" cy="12" r="4.5" fill="#38bdf8" stroke="#ffffff" strokeWidth="1.5" />
                      <circle cx="42" cy="12" r="4.5" fill="#f43f5e" stroke="#ffffff" strokeWidth="1.5" />
                      <circle cx="10" cy="40" r="4.5" fill="#34d399" stroke="#ffffff" strokeWidth="1.5" />
                      <circle cx="42" cy="40" r="4.5" fill="#fbbf24" stroke="#ffffff" strokeWidth="1.5" />

                      {/* Center 3D Isometric Cube */}
                      <polygon points="26,17 33,21 26,25 19,21" fill="#38bdf8" />
                      <polygon points="19,21 26,25 26,33 19,29" fill="#0284c7" />
                      <polygon points="26,25 33,21 33,29 26,33" fill="#0369a1" />
                    </svg>
                  </div>
                </div>
              </div>
            </div>
          )}

            {/* In Table List view, render a dedicated search filter */}
            {schemaViewMode === "list" && (
              <div className="flex items-center justify-between gap-3 mb-4 p-3 rounded-xl bg-white border border-[#e5e7eb] shadow-sm">
                <Input
                  prefix={<SearchOutlined style={{ color: "#8c8c8c" }} />}
                  placeholder="Filter dictionary by table or column name..."
                  value={schemaSearchQuery}
                  onChange={(e) => setSchemaSearchQuery(e.target.value)}
                  allowClear
                  style={{ maxWidth: 380, borderRadius: 8 }}
                />
                <div className="flex items-center gap-3">
                  {/* Circle Shaped Notes Button for Configured Alternative Names */}
                  {(() => {
                    const aliasList = getAliasSummaryList();
                    const totalAliasesCount = aliasList.reduce((acc, curr) => {
                      return acc + curr.tableAliases.length + curr.columnAliases.reduce((cAcc, c) => cAcc + c.aliases.length, 0);
                    }, 0);

                    return (
                      <Tooltip
                        title={
                          <div className="text-xs p-1">
                            <div className="font-bold text-teal-300 mb-0.5">Alternative Names Notes & Preview</div>
                            <div>
                              {totalAliasesCount > 0
                                ? `${totalAliasesCount} alternative name(s) configured across ${aliasList.length} table(s). Click to preview or download.`
                                : "No alternative names added yet. Click to view notes."}
                            </div>
                          </div>
                        }
                        placement="top"
                      >
                        <button
                          type="button"
                          onClick={() => setAliasNotesModalOpen(true)}
                          className="relative flex items-center justify-center w-8 h-8 rounded-full transition-all duration-200 cursor-pointer shadow-sm border focus:outline-none hover:scale-105 active:scale-95"
                          style={{
                            backgroundColor: totalAliasesCount > 0 ? "#f0fdfa" : "#f8fafc",
                            borderColor: totalAliasesCount > 0 ? "#0d9488" : "#cbd5e1",
                            boxShadow: totalAliasesCount > 0 ? "0 2px 8px rgba(13, 148, 136, 0.25)" : "0 1px 3px rgba(0,0,0,0.08)",
                          }}
                          aria-label="Alternative Names Notes"
                        >
                          <BookOutlined
                            style={{
                              fontSize: 15,
                              color: totalAliasesCount > 0 ? "#0d9488" : "#64748b",
                            }}
                          />
                          {totalAliasesCount > 0 && (
                            <span
                              className="absolute -top-1 -right-1 flex items-center justify-center min-w-[17px] h-[17px] px-1 text-[9px] font-bold text-white rounded-full border-2 border-white"
                              style={{ backgroundColor: "#0f766e" }}
                            >
                              {totalAliasesCount}
                            </span>
                          )}
                        </button>
                      </Tooltip>
                    );
                  })()}

                  <span className="text-xs text-gray-500 font-semibold">
                    Showing <strong className="text-teal-600">{filteredSchemaTables.length}</strong> of {allSchemaTables.length} tables
                  </span>
                </div>
              </div>
            )}

            {/* View Switching: ER Diagram vs Table List */}
            {schemaViewMode === "diagram" ? (
              <SchemaERDiagramViewer
                onSaveCustomMapping={handleSaveCustomMappings}
                tables={
                  schemaData?.schemas?.public?.tables ||
                  (schemaData?.schemas ? Object.values(schemaData.schemas)[0]?.tables : {}) ||
                  {}
                }
                filterQuery={schemaSearchQuery}
                isFullscreen={schemaFullscreen}
                onToggleFullscreen={() => setSchemaFullscreen((prev) => !prev)}
                isEditMode={schemaEditMode}
                onEditModeChange={(isEdit) => {
                  setSchemaEditMode(isEdit);
                  if (isEdit && !schemaFullscreen) {
                    setSchemaFullscreen(true);
                  }
                }}
                onClose={() => {
                  setSchemaModalOpen(false);
                  setSchemaFullscreen(false);
                  setSchemaEditMode(false);
                }}
                kbId={selectedKb?.id || "default_kb"}
              />
            ) : filteredSchemaTables.length === 0 ? (
              <div className="py-12 text-center">
                <Empty description="No tables match your search query." />
              </div>
            ) : (
              <div className="max-h-[60vh] overflow-y-auto pr-1 custom-scrollbar">
                <Table
                  rowKey="table_name"
                  dataSource={filteredSchemaTables}
                  scroll={{ x: 720 }}
                  pagination={{ pageSize: 15, showSizeChanger: true, pageSizeOptions: ["10", "15", "30", "50"] }}
                  className="border border-[#e2e8f0] rounded-xl overflow-hidden shadow-sm bg-white dark:bg-slate-900"
                  expandable={{
                    expandedRowRender: (tbl: any) => {
                      const cols = Array.isArray(tbl.columns) ? tbl.columns : Object.values(tbl.columns || {});

                      return (
                        <div className="p-3 bg-slate-50 dark:bg-slate-900/60 rounded-xl border border-slate-200 dark:border-slate-800 my-1">
                          <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-200 dark:border-slate-800">
                            <span className="font-mono font-bold text-xs text-slate-700 dark:text-slate-300">
                              Columns in &quot;{tbl.table_name}&quot; ({cols.length} total)
                            </span>
                          </div>

                          <Table
                            size="small"
                            dataSource={cols.map((c: any) => ({ ...c, key: c.name }))}
                            columns={[
                              {
                                title: "Column",
                                dataIndex: "name",
                                key: "name",
                                render: (name: string, record: TableColumn) => (
                                  <span className="font-mono text-xs font-medium">
                                    {name}{" "}
                                    {record.is_primary_key && (
                                      <Tag color="gold" style={{ fontSize: 10, padding: "0 4px" }}>
                                        PK
                                      </Tag>
                                    )}
                                  </span>
                                ),
                              },
                              {
                                title: "Data Type",
                                dataIndex: "data_type",
                                key: "data_type",
                                render: (type: string) => (
                                  <Tag color="purple" style={{ fontSize: 11 }}>
                                    {type}
                                  </Tag>
                                ),
                              },
                              {
                                title: "Nullable",
                                dataIndex: "is_nullable",
                                key: "is_nullable",
                                render: (n: boolean) =>
                                  n ? (
                                    <span className="text-gray-400 text-xs">YES</span>
                                  ) : (
                                    <Tag color="default" style={{ fontSize: 10 }}>
                                      NOT NULL
                                    </Tag>
                                  ),
                              },
                              {
                                title: "Description / Comment",
                                dataIndex: "comment",
                                key: "comment",
                                render: (c: string) => (
                                  <span className="text-gray-400 text-xs">{c || "—"}</span>
                                ),
                              },
                              {
                                title: "Alternative Column Names",
                                key: "column_aliases",
                                width: "42%",
                                render: (_: any, record: TableColumn) => {
                                  const colName = record.name;
                                  const tblName = tbl.table_name;
                                  const tagKey = `${tblName}.${colName}`;
                                  const namesList = (columnCustomNames[tblName] && columnCustomNames[tblName][colName]) || [];
                                  const inputValue = newColumnTagInput[tagKey] || "";

                                  return (
                                    <div className="flex flex-col gap-1.5 py-1" onClick={(e) => e.stopPropagation()}>
                                      {/* Tags display */}
                                      <div className="flex flex-wrap gap-1.5 items-center">
                                        {namesList.map((tag, tagIdx) => (
                                          <Tag
                                            key={tagIdx}
                                            closable
                                            onClose={(e) => {
                                              e.preventDefault();
                                              handleRemoveColumnSingleName(tblName, colName, tag);
                                            }}
                                            color="cyan"
                                            style={{
                                              borderRadius: 6,
                                              fontSize: 11,
                                              fontWeight: 600,
                                              padding: "1px 6px",
                                              margin: 0,
                                              border: "1px solid #a5f3fc",
                                              display: "inline-flex",
                                              alignItems: "center",
                                              gap: 4,
                                            }}
                                          >
                                            {tag}
                                          </Tag>
                                        ))}

                                        {namesList.length === 0 && (
                                          <span className="text-[11px] text-gray-400 italic">
                                            No alternative names added
                                          </span>
                                        )}
                                      </div>

                                      {/* Add Tag Input */}
                                      <div className="flex items-center gap-1.5 mt-0.5">
                                        <Input
                                          size="small"
                                          placeholder="Type alias (e.g. stage, status) & press Enter..."
                                          value={inputValue}
                                          onChange={(e) =>
                                            setNewColumnTagInput((prev) => ({
                                              ...prev,
                                              [tagKey]: e.target.value,
                                            }))
                                          }
                                          onKeyDown={(e) => {
                                            if (e.key === "Enter") {
                                              e.preventDefault();
                                              handleAddColumnName(tblName, colName);
                                            }
                                          }}
                                          style={{
                                            maxWidth: 240,
                                            fontSize: 11,
                                            borderRadius: 6,
                                          }}
                                        />
                                        <Button
                                          size="small"
                                          icon={<PlusOutlined style={{ fontSize: 10 }} />}
                                          onClick={() => handleAddColumnName(tblName, colName)}
                                          disabled={!inputValue.trim()}
                                          style={{
                                            fontSize: 11,
                                            borderRadius: 6,
                                            height: 24,
                                            padding: "0 8px",
                                            display: "inline-flex",
                                            alignItems: "center",
                                          }}
                                        >
                                          Add
                                        </Button>
                                      </div>
                                    </div>
                                  );
                                },
                              },
                            ]}
                            pagination={false}
                            className="border border-[#e2e8f0] rounded-lg overflow-hidden bg-white dark:bg-slate-900"
                          />

                          {tbl.foreign_keys && tbl.foreign_keys.length > 0 && (
                            <div className="mt-3 p-2.5 rounded-lg bg-[var(--app-surface-muted)] border border-[var(--app-border)]">
                              <Text strong style={{ fontSize: 11, color: "var(--app-text)" }}>
                                Foreign Key Outgoing Links:
                              </Text>
                              <div className="flex flex-col gap-1 mt-1">
                                {tbl.foreign_keys.map((fk: any, idx: number) => (
                                  <Text key={idx} className="text-[11px] text-gray-500 font-mono">
                                    ↳ ({(fk.constrained_columns || []).join(", ")}) references{" "}
                                    <Text strong className="text-[var(--app-primary)]">{fk.referred_table}</Text>
                                    ({(fk.referred_columns || []).join(", ")})
                                  </Text>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    },
                    expandedRowKeys: expandedTableKeys,
                    onExpandedRowsChange: (keys) => setExpandedTableKeys(keys as string[]),
                  }}
                  onRow={(record) => ({
                    onClick: () => {
                      setExpandedTableKeys((prev) =>
                        prev.includes(record.table_name)
                          ? prev.filter((k) => k !== record.table_name)
                          : [...prev, record.table_name]
                      );
                    },
                    style: { cursor: "pointer" },
                  })}
                  columns={[
                    {
                      title: "Table Name",
                      dataIndex: "table_name",
                      key: "table_name",
                      width: "30%",
                      render: (tableName: string, record: any) => {
                        const isExpanded = expandedTableKeys.includes(tableName);
                        return (
                          <div className="flex items-center gap-2.5">
                            <div className="w-8 h-8 rounded-lg bg-teal-50 dark:bg-teal-950/40 flex items-center justify-center text-teal-600 border border-teal-200 dark:border-teal-800 flex-shrink-0">
                              <DatabaseOutlined style={{ fontSize: 14 }} />
                            </div>
                            <div className="min-w-0">
                              <div className="font-mono font-bold text-sm text-slate-800 dark:text-slate-100 flex items-center gap-2 truncate">
                                <span>{tableName}</span>
                                {record.comment && (
                                  <Tag color="blue" style={{ fontSize: 10, padding: "0 5px" }}>
                                    {record.comment}
                                  </Tag>
                                )}
                              </div>
                              <span className="text-[11px] text-teal-600 font-medium">
                                {isExpanded ? "▾ Click to collapse columns" : "▸ Click to view columns"}
                              </span>
                            </div>
                          </div>
                        );
                      },
                    },
                    {
                      title: "Columns",
                      key: "columns_count",
                      width: "15%",
                      render: (_: any, record: any) => {
                        const cols = Array.isArray(record.columns) ? record.columns : Object.values(record.columns || {});
                        return (
                          <Tag color="cyan" style={{ fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 6 }}>
                            {cols.length} columns
                          </Tag>
                        );
                      },
                    },
                    {
                      title: "Name",
                      key: "name_aliases",
                      width: "55%",
                      render: (_: any, record: any) => {
                        const tableName = record.table_name;
                        const namesList = tableCustomNames[tableName] || [];
                        const inputValue = newTableTagInput[tableName] || "";

                        return (
                          <div
                            className="flex flex-col gap-2 py-1"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {/* Multiple Names Tag Badges */}
                            <div className="flex flex-wrap items-center gap-1.5 min-h-[26px]">
                              {namesList.length === 0 ? (
                                <span className="text-xs text-gray-400 italic">No alternative names added</span>
                              ) : (
                                namesList.map((nameStr, idx) => (
                                  <Tag
                                    key={idx}
                                    closable
                                    onClose={(e) => {
                                      e.preventDefault();
                                      handleRemoveTableSingleName(tableName, nameStr);
                                    }}
                                    color="cyan"
                                    style={{
                                      fontSize: 11,
                                      fontWeight: 600,
                                      borderRadius: 6,
                                      padding: "2px 8px",
                                      backgroundColor: "#f0fdfa",
                                      borderColor: "#99f6e4",
                                      color: "#0f766e",
                                      display: "inline-flex",
                                      alignItems: "center",
                                      gap: 4,
                                    }}
                                  >
                                    {nameStr}
                                  </Tag>
                                ))
                              )}
                            </div>

                            {/* Add Name Input & Action Buttons */}
                            <div className="flex items-center gap-2 flex-wrap">
                              <Input
                                size="small"
                                placeholder="Type a name & press Enter..."
                                value={inputValue}
                                onChange={(e) =>
                                  setNewTableTagInput((prev) => ({ ...prev, [tableName]: e.target.value }))
                                }
                                onKeyDown={(e) => {
                                  if (e.key === "Enter") {
                                    e.preventDefault();
                                    handleAddTableName(tableName);
                                  }
                                }}
                                style={{ width: 200, fontSize: 12, borderRadius: 6 }}
                              />
                              <Button
                                size="small"
                                icon={<PlusOutlined />}
                                onClick={() => handleAddTableName(tableName)}
                                style={{ borderRadius: 6, fontSize: 11 }}
                              >
                                Add
                              </Button>
                              <Button
                                size="small"
                                type="primary"
                                icon={<SaveOutlined />}
                                onClick={() => handleSaveTableName(tableName)}
                                style={{
                                  backgroundColor: "#0d9488",
                                  borderColor: "#0d9488",
                                  borderRadius: 6,
                                  fontSize: 11,
                                  fontWeight: 600,
                                }}
                              >
                                Save
                              </Button>
                              {namesList.length > 0 && (
                                <Button
                                  size="small"
                                  danger
                                  icon={<DeleteOutlined />}
                                  onClick={() => handleClearTableNames(tableName)}
                                  style={{ borderRadius: 6, fontSize: 11 }}
                                >
                                  Remove
                                </Button>
                              )}
                            </div>
                          </div>
                        );
                      },
                    },
                  ]}
                />
              </div>
            )}
          </div>
        ) : (
          <Alert type="warning" title="No canonical schema information available. Please sync schema first." />
        )}
      </Modal>

      {/* Alternative Names Notes & Preview Modal */}
      <Modal
        open={aliasNotesModalOpen}
        onCancel={() => {
          setAliasNotesModalOpen(false);
          setAliasNotesSearch("");
        }}
        footer={null}
        width="min(860px, 95vw)"
        styles={{
          container: { borderRadius: 20, overflow: "hidden" },
          body: { padding: "20px 24px", backgroundColor: "#faf9f6" },
        }}
        title={
          <div className="flex items-center justify-between pr-6 py-1">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-full bg-teal-50 border border-teal-200 flex items-center justify-center text-teal-700 shadow-sm">
                <BookOutlined style={{ fontSize: 17 }} />
              </div>
              <div>
                <div className="text-base font-bold text-slate-800 leading-tight">
                  Configured Alternative Names
                </div>
                <div className="text-xs text-gray-500 font-normal mt-0.5">
                  Overview of all original table & column names mapped to user-defined aliases
                </div>
              </div>
            </div>

            {/* Download and Action Buttons */}
            <div className="flex items-center gap-2">
              <Button
                size="small"
                icon={<DownloadOutlined />}
                onClick={() => handleDownloadAliasNotes("txt")}
                style={{
                  borderRadius: 8,
                  fontWeight: 600,
                  fontSize: 12,
                  borderColor: "#0d6e65",
                  color: "#0d6e65",
                  backgroundColor: "#f0fdfa",
                }}
              >
                Download (.txt)
              </Button>
              <Button
                size="small"
                icon={<DownloadOutlined />}
                onClick={() => handleDownloadAliasNotes("json")}
                style={{
                  borderRadius: 8,
                  fontWeight: 600,
                  fontSize: 12,
                  borderColor: "#cbd5e1",
                  color: "#475569",
                }}
              >
                JSON
              </Button>
            </div>
          </div>
        }
      >
        {(() => {
          const allAliases = getAliasSummaryList();
          const filterQ = aliasNotesSearch.trim().toLowerCase();

          const filteredList = allAliases.filter((item) => {
            if (!filterQ) return true;
            if (item.tableName.toLowerCase().includes(filterQ)) return true;
            if (item.tableAliases.some((a) => a.toLowerCase().includes(filterQ))) return true;
            return item.columnAliases.some(
              (c) =>
                c.columnName.toLowerCase().includes(filterQ) ||
                c.aliases.some((a) => a.toLowerCase().includes(filterQ))
            );
          });

          const totalConfiguredTables = allAliases.length;
          const totalColumnAliases = allAliases.reduce(
            (sum, item) => sum + item.columnAliases.reduce((cSum, c) => cSum + c.aliases.length, 0),
            0
          );
          const totalTableAliases = allAliases.reduce((sum, item) => sum + item.tableAliases.length, 0);

          return (
            <div className="flex flex-col gap-4 pt-1">
              {/* Instructions & Summary Banner */}
              <div className="p-3.5 rounded-xl bg-gradient-to-r from-teal-50 via-emerald-50 to-cyan-50 border border-teal-200/80 shadow-xs">
                <div className="flex items-start gap-2.5">
                  <InfoCircleOutlined style={{ color: "#0d9488", fontSize: 16, marginTop: 2 }} />
                  <div className="text-xs text-slate-700 leading-relaxed flex-1">
                    <div className="font-bold text-teal-900 mb-0.5">How Alternative Names Work</div>
                    When users ask questions using these alternative words (e.g. non-technical synonyms or custom aliases), 
                    the GSearchAI retrieval engine automatically resolves them to their exact database tables and columns.
                  </div>
                </div>

                {/* Quick stats pills */}
                <div className="flex flex-wrap items-center gap-2 mt-3 pt-2.5 border-t border-teal-200/60 text-xs font-medium">
                  <Tag color="cyan" style={{ borderRadius: 6, padding: "2px 10px", fontWeight: 600 }}>
                    {totalConfiguredTables} Tables with Aliases
                  </Tag>
                  <Tag color="teal" style={{ borderRadius: 6, padding: "2px 10px", fontWeight: 600 }}>
                    {totalTableAliases} Alternative Table Names
                  </Tag>
                  <Tag color="blue" style={{ borderRadius: 6, padding: "2px 10px", fontWeight: 600 }}>
                    {totalColumnAliases} Alternative Column Names
                  </Tag>
                </div>
              </div>

              {/* Search filter for notes */}
              {allAliases.length > 0 && (
                <div className="flex items-center gap-2">
                  <Input
                    prefix={<SearchOutlined style={{ color: "#94a3b8" }} />}
                    placeholder="Filter notes by table, column, or alias word..."
                    value={aliasNotesSearch}
                    onChange={(e) => setAliasNotesSearch(e.target.value)}
                    allowClear
                    size="middle"
                    style={{ borderRadius: 8 }}
                  />
                </div>
              )}

              {/* List of Alternative Names clean and clear */}
              {allAliases.length === 0 ? (
                <div className="py-12 text-center bg-white rounded-xl border border-gray-200">
                  <Empty
                    description={
                      <div className="text-sm text-gray-500">
                        <div className="font-semibold mb-1">No alternative names added yet</div>
                        <div>You can add alternative table names or column names from the Data Dictionary table list.</div>
                      </div>
                    }
                  />
                </div>
              ) : filteredList.length === 0 ? (
                <div className="py-8 text-center bg-white rounded-xl border border-gray-200">
                  <Empty description="No alternative names matched your search." />
                </div>
              ) : (
                <div className="flex flex-col gap-3 max-h-[55vh] overflow-y-auto pr-1 custom-scrollbar">
                  {filteredList.map((item, idx) => {
                    const hasTableAliases = item.tableAliases.length > 0;
                    const hasColAliases = item.columnAliases.length > 0;

                    return (
                      <div
                        key={item.tableName}
                        className="p-4 rounded-xl bg-white border border-slate-200 hover:border-teal-300 transition-all shadow-xs flex flex-col gap-3"
                      >
                        {/* Table Header Row: original table name --> alternative name */}
                        <div className="flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-slate-100">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="w-6 h-6 rounded-full bg-slate-100 text-slate-600 font-mono text-xs font-bold flex items-center justify-center">
                              {idx + 1}
                            </span>
                            <span className="font-mono font-bold text-sm text-slate-800 bg-slate-100 px-2 py-0.5 rounded">
                              {item.tableName}
                            </span>

                            {hasTableAliases ? (
                              <div className="flex items-center gap-1.5">
                                <ArrowRightOutlined style={{ fontSize: 11, color: "#0d9488" }} />
                                <span className="text-xs font-medium text-gray-500">Alternative Name:</span>
                                {item.tableAliases.map((aliasStr, aIdx) => (
                                  <Tag
                                    key={aIdx}
                                    color="cyan"
                                    style={{
                                      fontSize: 12,
                                      fontWeight: 700,
                                      borderRadius: 6,
                                      padding: "2px 9px",
                                      backgroundColor: "#f0fdfa",
                                      borderColor: "#99f6e4",
                                      color: "#0f766e",
                                    }}
                                  >
                                    {aliasStr}
                                  </Tag>
                                ))}
                              </div>
                            ) : (
                              <span className="text-xs text-gray-400 italic">
                                (No alternative table name set — original table name used)
                              </span>
                            )}
                          </div>

                          <Tag color={hasTableAliases ? "teal" : "default"} style={{ fontSize: 11, borderRadius: 6 }}>
                            {item.columnAliases.length} column(s) with aliases
                          </Tag>
                        </div>

                        {/* Column Aliases Section Under Table */}
                        {hasColAliases ? (
                          <div className="bg-slate-50/80 rounded-lg p-3 border border-slate-100 flex flex-col gap-2">
                            <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider flex items-center gap-1">
                              <span>Under &quot;{item.tableName}&quot;, column alternative words:</span>
                            </div>
                            <div className="flex flex-col gap-2 pl-2">
                              {item.columnAliases.map((colItem) => (
                                <div
                                  key={colItem.columnName}
                                  className="flex flex-wrap items-center gap-2 text-xs"
                                >
                                  <span className="font-mono font-bold text-slate-700 bg-white border border-slate-200 px-2 py-0.5 rounded shadow-2xs">
                                    {colItem.columnName}
                                  </span>
                                  <ArrowRightOutlined style={{ fontSize: 10, color: "#0284c7" }} />
                                  <span className="text-xs text-slate-500 font-medium">Alternative Word(s):</span>
                                  {colItem.aliases.map((colAlias, cIdx) => (
                                    <Tag
                                      key={cIdx}
                                      color="blue"
                                      style={{
                                        fontSize: 11,
                                        fontWeight: 600,
                                        borderRadius: 6,
                                        padding: "2px 8px",
                                        backgroundColor: "#f0f9ff",
                                        borderColor: "#bae6fd",
                                        color: "#0369a1",
                                      }}
                                    >
                                      {colAlias}
                                    </Tag>
                                  ))}
                                </div>
                              ))}
                            </div>
                          </div>
                        ) : (
                          <div className="text-xs text-gray-400 italic pl-1">
                            No alternative column names defined for this table.
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })()}
      </Modal>

      {/* Observability Trace Drawer */}
      <Drawer
        title={
          <div className="flex items-center gap-2">
            <ThunderboltOutlined style={{ color: "var(--app-primary)" }} />
            <span>
              {inspectedTrace ? "Historical Query Audit Trace" : "End-to-End Pipeline Observability Trace"}
            </span>
          </div>
        }
        width={750}
        open={observabilityOpen}
        onClose={() => {
          setObservabilityOpen(false);
          setInspectedTrace(null);
        }}
      >
        {inspectedTrace ? (
          <div className="flex flex-col gap-6">
            {/* Total Latency Header */}
            <div className="flex items-center justify-between p-3 rounded-lg bg-teal-500/10 border border-teal-500/30">
              <div>
                <Text strong style={{ color: "var(--app-text)" }}>Total Query Latency:</Text>
                <div className="text-2xl font-bold text-teal-400">
                  {inspectedTrace.total_latency_ms.toFixed(1)} ms
                </div>
              </div>
              <Space direction="vertical" orientation="vertical" align="end">
                <Tag color={inspectedTrace.final_status === "SUCCESS" ? "green" : inspectedTrace.final_status === "SECURITY_REJECTED" ? "red" : "orange"}>
                  {inspectedTrace.final_status}
                </Tag>
                <span className="text-xs font-mono text-gray-400">
                  ID: {inspectedTrace.query_id ? inspectedTrace.query_id.substring(0, 13) : inspectedTrace.id.substring(0, 13)}...
                </span>
              </Space>
            </div>

            {/* Question */}
            <Card size="small" title="User Question">
              <div className="text-sm font-sans text-gray-200">
                {inspectedTrace.sanitized_user_query}
              </div>
            </Card>

            {/* Stage Latencies Overview */}
            <Card size="small" title="Pipeline Stage Latencies Breakdown">
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
                <div className="p-2 bg-gray-900 rounded border border-gray-800">
                  <Text type="secondary">Retrieval</Text>
                  <div className="font-bold text-teal-300">{inspectedTrace.retrieval_latency_ms?.toFixed(1) || 0} ms</div>
                </div>
                <div className="p-2 bg-gray-900 rounded border border-gray-800">
                  <Text type="secondary">Planning</Text>
                  <div className="font-bold text-teal-300">{inspectedTrace.planning_latency_ms?.toFixed(1) || 0} ms</div>
                </div>
                <div className="p-2 bg-gray-900 rounded border border-gray-800">
                  <Text type="secondary">SQL Generation</Text>
                  <div className="font-bold text-teal-300">{inspectedTrace.sql_generation_latency_ms?.toFixed(1) || 0} ms</div>
                </div>
                <div className="p-2 bg-gray-900 rounded border border-gray-800">
                  <Text type="secondary">AST Validation</Text>
                  <div className="font-bold text-teal-300">{inspectedTrace.validation_latency_ms?.toFixed(1) || 0} ms</div>
                </div>
                <div className="p-2 bg-gray-900 rounded border border-gray-800">
                  <Text type="secondary">DB Driver Exec</Text>
                  <div className="font-bold text-teal-300">{inspectedTrace.database_execution_latency_ms?.toFixed(1) || 0} ms</div>
                </div>
                <div className="p-2 bg-gray-900 rounded border border-gray-800">
                  <Text type="secondary">Answer Synthesis</Text>
                  <div className="font-bold text-teal-300">{inspectedTrace.answer_synthesis_latency_ms?.toFixed(1) || 0} ms</div>
                </div>
              </div>
            </Card>

            {/* Execution Result Summary */}
            <Card size="small" title="Database Execution Result Summary">
              <div className="grid grid-cols-3 gap-2 text-xs text-center">
                <div className="p-2 bg-gray-900 rounded">
                  <Text type="secondary">Rows Returned</Text>
                  <div className="font-bold text-base">{inspectedTrace.row_count}</div>
                </div>
                <div className="p-2 bg-gray-900 rounded">
                  <Text type="secondary">Columns</Text>
                  <div className="font-bold text-base">{inspectedTrace.column_count}</div>
                </div>
                <div className="p-2 bg-gray-900 rounded">
                  <Text type="secondary">Truncated</Text>
                  <div className="font-bold text-base">
                    {inspectedTrace.truncated ? "YES" : "NO"}
                  </div>
                </div>
              </div>
            </Card>

            {/* Security & Grounding Policy Status */}
            <Card size="small" title="Security & Grounding Status">
              <div className="flex flex-col gap-2 text-xs">
                <div className="flex items-center justify-between">
                  <span>AST Security Policy:</span>
                  <Tag color={inspectedTrace.ast_valid ? "green" : "red"}>
                    {inspectedTrace.ast_valid ? "AST VALID" : "AST REJECTED"}
                  </Tag>
                </div>
                <div className="flex items-center justify-between">
                  <span>Grounding Status:</span>
                  <Tag color="green">{inspectedTrace.grounding_status}</Tag>
                </div>
                <div className="flex items-center justify-between">
                  <span>Verification Status:</span>
                  <Tag color="blue">{inspectedTrace.verification_status}</Tag>
                </div>
                {inspectedTrace.fallback_used && (
                  <Alert type="warning" title="Deterministic Fallback Activated for this query" showIcon />
                )}
                {inspectedTrace.sanitized_error && (
                  <Alert type="error" title={`Error: ${inspectedTrace.sanitized_error}`} showIcon />
                )}
              </div>
            </Card>
          </div>
        ) : groundedAnswer?.pipeline_trace ? (
          <div className="flex flex-col gap-6">
            {/* Total Latency Header */}
            <div className="flex items-center justify-between p-3 rounded-lg bg-teal-500/10 border border-teal-500/30">
              <div>
                <Text strong style={{ color: "var(--app-text)" }}>Total Query Latency:</Text>
                <div className="text-2xl font-bold text-teal-400">
                  {groundedAnswer.pipeline_trace.total_latency_ms} ms
                </div>
              </div>
              <Space direction="vertical" orientation="vertical" align="end">
                <Tag color={groundedAnswer.pipeline_trace.success ? "green" : "red"}>
                  {groundedAnswer.pipeline_trace.success ? "PIPELINE SUCCESS" : "PIPELINE FAILED"}
                </Tag>
                <span className="text-xs font-mono text-gray-400">
                  ID: {groundedAnswer.pipeline_trace.query_id.substring(0, 13)}...
                </span>
              </Space>
            </div>

            {/* Stage 1: Phase 2A Retrieval */}
            <Card
              size="small"
              title={
                <div className="flex items-center justify-between">
                  <span>1. Phase 2A: Semantic Schema Retrieval</span>
                  <Tag color="cyan">{groundedAnswer.pipeline_trace.retrieval.latency_ms} ms</Tag>
                </div>
              }
            >
              <div className="flex flex-col gap-2 text-xs">
                <div>
                  <Text strong>Selected Tables ({groundedAnswer.pipeline_trace.retrieval.retrieved_tables.length}): </Text>
                  {groundedAnswer.pipeline_trace.retrieval.retrieved_tables.map((t) => (
                    <Tag key={t} color="blue">{t}</Tag>
                  ))}
                </div>

                {Object.keys(groundedAnswer.pipeline_trace.retrieval.table_scores).length > 0 && (
                  <div>
                    <Text strong>Relevance Scores: </Text>
                    <div className="font-mono text-gray-300 mt-1">
                      {Object.entries(groundedAnswer.pipeline_trace.retrieval.table_scores).map(([tbl, sc]: [string, any]) => (
                        <span key={tbl} className="mr-3">
                          {tbl}: <b>
                            {typeof sc === "object" 
                              ? (sc.final_score !== undefined ? sc.final_score.toFixed(3) : JSON.stringify(sc)) 
                              : (typeof sc === "number" ? sc.toFixed(3) : String(sc))}
                          </b>
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {groundedAnswer.pipeline_trace.retrieval.selected_relationships.length > 0 && (
                  <div>
                    <Text strong>Selected Foreign Key Paths: </Text>
                    <ul className="list-disc pl-4 font-mono text-gray-300">
                      {groundedAnswer.pipeline_trace.retrieval.selected_relationships.map((rel, i) => (
                        <li key={i}>{rel}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </Card>

            {/* Stage 2: Phase 2B Query Planning */}
            <Card
              size="small"
              title={
                <div className="flex items-center justify-between">
                  <span>2. Phase 2B: Query Planning (QueryPlanIR)</span>
                  <Tag color="cyan">{groundedAnswer.pipeline_trace.planning.latency_ms} ms</Tag>
                </div>
              }
            >
              <div className="flex flex-col gap-2 text-xs">
                <div>
                  <Text strong>Classified Intent: </Text>
                  <Tag color="purple">{groundedAnswer.pipeline_trace.planning.intent}</Tag>
                </div>
                <div>
                  <Text strong>Target Tables: </Text>
                  {groundedAnswer.pipeline_trace.planning.tables.join(", ")}
                </div>
                {groundedAnswer.pipeline_trace.planning.joins.length > 0 && (
                  <div>
                    <Text strong>Join Conditions: </Text>
                    <ul className="list-disc pl-4 font-mono text-gray-300">
                      {groundedAnswer.pipeline_trace.planning.joins.map((j, i) => (
                        <li key={i}>{j}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {groundedAnswer.pipeline_trace.planning.filters.length > 0 && (
                  <div>
                    <Text strong>Filters: </Text>
                    <span className="font-mono text-gray-300">
                      {groundedAnswer.pipeline_trace.planning.filters.join(" AND ")}
                    </span>
                  </div>
                )}
                {groundedAnswer.pipeline_trace.planning.aggregations.length > 0 && (
                  <div>
                    <Text strong>Aggregations: </Text>
                    <span className="font-mono text-gray-300">
                      {groundedAnswer.pipeline_trace.planning.aggregations.join(", ")}
                    </span>
                  </div>
                )}
              </div>
            </Card>

            {/* Stage 3: Phase 2B SQL Generation & AST Validation */}
            <Card
              size="small"
              title={
                <div className="flex items-center justify-between">
                  <span>3. Phase 2B: SQL Generation & AST Security</span>
                  <Tag color="cyan">{groundedAnswer.pipeline_trace.sql_generation.latency_ms} ms</Tag>
                </div>
              }
            >
              <div className="flex flex-col gap-2 text-xs">
                <div className="flex items-center justify-between">
                  <div>
                    <Text strong>AST Validation: </Text>
                    <Tag color={groundedAnswer.pipeline_trace.sql_generation.ast_valid ? "green" : "red"}>
                      {groundedAnswer.pipeline_trace.sql_generation.ast_valid ? "AST PASSED" : "AST REJECTED"}
                    </Tag>
                  </div>
                  <div>
                    <Text strong>Repair Loops: </Text>
                    <span>{groundedAnswer.pipeline_trace.sql_generation.repair_attempts}</span>
                  </div>
                </div>

                <div>
                  <Text strong>Parameterized Candidate SQL: </Text>
                  <pre className="p-3 bg-gray-900 text-teal-300 rounded font-mono text-xs overflow-x-auto mt-1">
                    {groundedAnswer.pipeline_trace.sql_generation.candidate_sql}
                  </pre>
                </div>

                {Object.keys(groundedAnswer.pipeline_trace.sql_generation.parameters).length > 0 && (
                  <div>
                    <Text strong>Parameters: </Text>
                    <pre className="p-2 bg-gray-900 text-gray-300 rounded font-mono text-xs mt-1">
                      {JSON.stringify(groundedAnswer.pipeline_trace.sql_generation.parameters, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            </Card>

            {/* Stage 4: Phase 2C Read-Only Execution */}
            <Card
              size="small"
              title={
                <div className="flex items-center justify-between">
                  <span>4. Phase 2C: Read-Only Driver Execution</span>
                  <Tag color="cyan">{groundedAnswer.pipeline_trace.execution.execution_time_ms} ms</Tag>
                </div>
              }
            >
              <div className="grid grid-cols-3 gap-2 text-xs text-center">
                <div className="p-2 bg-gray-900 rounded">
                  <Text type="secondary">Rows Returned</Text>
                  <div className="font-bold text-base">{groundedAnswer.pipeline_trace.execution.row_count}</div>
                </div>
                <div className="p-2 bg-gray-900 rounded">
                  <Text type="secondary">Columns</Text>
                  <div className="font-bold text-base">{groundedAnswer.pipeline_trace.execution.column_count}</div>
                </div>
                <div className="p-2 bg-gray-900 rounded">
                  <Text type="secondary">Truncated</Text>
                  <div className="font-bold text-base">
                    {groundedAnswer.pipeline_trace.execution.truncated ? "YES" : "NO"}
                  </div>
                </div>
              </div>
            </Card>

            {/* Stage 5: Phase 2D Grounded Synthesis */}
            <Card
              size="small"
              title={
                <div className="flex items-center justify-between">
                  <span>5. Phase 2D: Grounded Synthesis & Verification</span>
                  <Tag color="cyan">{groundedAnswer.pipeline_trace.synthesis.latency_ms} ms</Tag>
                </div>
              }
            >
              <div className="flex flex-col gap-2 text-xs">
                <div className="flex items-center justify-between">
                  <span>Path: <b>{groundedAnswer.pipeline_trace.synthesis.deterministic ? "Deterministic Fast-Path (Zero LLM)" : "LLM Synthesized"}</b></span>
                  <Tag color="green">{groundedAnswer.pipeline_trace.synthesis.grounding_status}</Tag>
                </div>
                <div className="flex items-center justify-between">
                  <span>Verifier Gate: <b>{groundedAnswer.pipeline_trace.synthesis.verification_status}</b></span>
                  <span>Repair Attempts: <b>{groundedAnswer.pipeline_trace.synthesis.repair_attempts}</b></span>
                </div>
              </div>
            </Card>
          </div>
        ) : (
          <Alert title="No trace telemetry available for this query." type="info" />
        )}
      </Drawer>
    </div>
  );
}
