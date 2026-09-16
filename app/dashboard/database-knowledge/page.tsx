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
} from "antd";
import {
  DatabaseOutlined,
  PlusOutlined,
  SyncOutlined,
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
  ArrowRightOutlined,
  DeleteOutlined,
  DownloadOutlined,
  CopyOutlined,
  FileTextOutlined,
  DownOutlined,
  FilterOutlined,
} from "@ant-design/icons";
import { BsDatabaseFillGear } from "react-icons/bs";
import { marked } from "marked";
import { toast } from "react-hot-toast";
import { getCookie } from "../../config/cookies";
import { API_BASE_URL } from "../../config/config";
import { DatabaseStreamClient, DatabaseStreamEvent } from "../../services/databaseStreamClient";
import { DatabasePipelineProgress } from "../../components/DatabasePipelineProgress";

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

export default function DatabaseKnowledgePage() {
  const [kbList, setKbList] = useState<DBKnowledgebase[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedKb, setSelectedKb] = useState<DBKnowledgebase | null>(null);

  // Connection Modal state
  const [modalOpen, setModalOpen] = useState(false);
  const [testLoading, setTestLoading] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; latency_ms?: number; message?: string } | null>(null);

  // Form State
  const [formName, setFormName] = useState("HRMS Enterprise Database (Demo)");
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

  const getAuthHeaders = () => {
    const token = getCookie("AUTH_TOKEN");
    return {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    };
  };

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
    if (selectedKb) {
      fetchMetricsAndHealth(selectedKb.id);
      fetchAuditLogs(selectedKb.id, 1, auditStatusFilter);
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
          db_type: "postgresql",
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
            db_type: "postgresql",
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
    try {
      const res = await fetch(`${API_BASE_URL}/database-knowledgebases/${kbId}/introspect`, {
        method: "POST",
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        toast.success("Database schema synchronized and indexed successfully!");
        await fetchKnowledgebases();
      } else {
        const err = await res.json();
        toast.error(err.detail || "Schema introspection failed.");
      }
    } catch (err: any) {
      toast.error(err.message || "Schema introspection error.");
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

  const handleRunQuery = async (queryText?: string) => {
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

    try {
      const token = getCookie("AUTH_TOKEN");
      await DatabaseStreamClient.streamQuery({
        apiBaseUrl: API_BASE_URL,
        kbId: selectedKb.id,
        query: q,
        token: token || undefined,
        useLlm: true,
        abortSignal: controller.signal,
        onEvent: (event: DatabaseStreamEvent) => {
          setStreamEvents((prev) => [...prev, event]);
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
      if (tbl.table_name.toLowerCase().includes(q)) return true;
      if (tbl.comment && tbl.comment.toLowerCase().includes(q)) return true;
      const cols = Array.isArray(tbl.columns) ? tbl.columns : Object.values(tbl.columns || {});
      return cols.some(
        (c: any) =>
          c.name.toLowerCase().includes(q) ||
          (c.comment && c.comment.toLowerCase().includes(q))
      );
    });
  }, [allSchemaTables, schemaSearchQuery]);

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

      {/* Main Workspace Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mt-6">
        {/* Left Column: Configured Databases */}
        <div className="lg:col-span-4 xl:col-span-4 2xl:col-span-3 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <Text strong style={{ fontSize: 16, color: "var(--app-text)" }}>
              Connected Databases ({kbList.length})
            </Text>
            <Button
              type="text"
              size="small"
              icon={<SyncOutlined spin={loading} />}
              onClick={fetchKnowledgebases}
            >
              Refresh
            </Button>
          </div>

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
                borderRadius: 12,
              }}
            >
              <BsDatabaseFillGear style={{ fontSize: 36, color: "#bfbfbf", marginBottom: 12 }} />
              <Paragraph style={{ color: "#8c8c8c" }}>No relational databases connected yet.</Paragraph>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => setModalOpen(true)}
                style={{ backgroundColor: "var(--app-primary)" }}
              >
                Connect HRMS Database
              </Button>
            </Card>
          ) : (
            <div className="flex flex-col gap-3">
              {kbList.map((kb) => {
                const isSelected = selectedKb?.id === kb.id;
                return (
                  <Card
                    key={kb.id}
                    hoverable
                    onClick={() => setSelectedKb(kb)}
                    style={{
                      background: isSelected ? "rgba(15, 181, 161, 0.05)" : "var(--app-surface)",
                      borderColor: isSelected ? "var(--app-primary)" : "var(--app-border)",
                      borderRadius: 12,
                      cursor: "pointer",
                      transition: "all 0.2s",
                      boxShadow: isSelected ? "0 0 0 1px var(--app-primary)" : "none",
                    }}
                    styles={{ body: { padding: 16 } }}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <Text strong style={{ fontSize: 15, color: "var(--app-text)" }} className="truncate block">
                            {kb.name}
                          </Text>
                          <Tag
                            color={kb.status === "introspected" || kb.status === "indexed" ? "green" : "blue"}
                            style={{ borderRadius: 4, margin: 0, fontSize: 11 }}
                          >
                            {kb.status.toUpperCase()}
                          </Tag>
                        </div>
                        <Text style={{ fontSize: 12, color: "#8c8c8c", display: "block", marginTop: 4 }} className="line-clamp-2">
                          {kb.description || "PostgreSQL Knowledgebase"}
                        </Text>
                      </div>
                      <Tooltip title="Delete Database">
                        <Button
                          danger
                          type="text"
                          size="small"
                          icon={<DeleteOutlined />}
                          className="shrink-0 text-gray-400 hover:text-red-500 hover:bg-red-500/10"
                          onClick={(e) => {
                            e.stopPropagation();
                            confirmDeleteDatabase(kb);
                          }}
                        />
                      </Tooltip>
                    </div>

                    <div className="mt-3 flex items-center justify-between text-xs text-gray-400">
                      <span className="font-mono text-[11px] uppercase tracking-wide">
                        Engine: {kb.database_type.toUpperCase()}
                      </span>
                      {kb.schema_version && (
                        <Tooltip title={`Fingerprint: ${kb.schema_version}`}>
                          <span className="font-mono bg-gray-800 text-gray-300 px-2 py-0.5 rounded text-[11px] border border-gray-700/50">
                            v:{kb.schema_version.substring(0, 8)}
                          </span>
                        </Tooltip>
                      )}
                    </div>

                    <div className="mt-3 pt-3 border-t border-[var(--app-border)] grid grid-cols-2 gap-2 w-full">
                      <Button
                        size="small"
                        icon={<SyncOutlined />}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleSyncSchema(kb.id);
                        }}
                        className="w-full flex items-center justify-center px-1"
                        style={{ fontSize: 12 }}
                      >
                        Sync Schema
                      </Button>
                      <Button
                        size="small"
                        type="default"
                        icon={<TableOutlined />}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleViewSchema(kb.id);
                        }}
                        className="w-full flex items-center justify-center px-1"
                        style={{ fontSize: 12 }}
                      >
                        Explore Schema
                      </Button>
                    </div>
                  </Card>
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
              <Card
                style={{
                  background: "var(--app-surface)",
                  borderColor: "var(--app-border)",
                  borderRadius: 12,
                }}
                styles={{ body: { padding: "16px 20px" } }}
              >
                <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2.5 flex-wrap sm:flex-nowrap">
                      <Title
                        level={4}
                        style={{
                          margin: 0,
                          color: "var(--app-text)",
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          fontWeight: 650,
                        }}
                        title={selectedKb.name}
                      >
                        {selectedKb.name}
                      </Title>
                      <Tag
                        color="cyan"
                        className="shrink-0"
                        style={{ borderRadius: 6, fontWeight: 500 }}
                      >
                        Active Query Agent
                      </Tag>
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <Text style={{ color: "#8c8c8c", fontSize: 12 }}>Database ID:</Text>
                      <Text
                        copyable={{ text: selectedKb.id }}
                        className="font-mono text-xs text-gray-400 bg-gray-800/60 px-2 py-0.5 rounded border border-gray-700/60"
                      >
                        {selectedKb.id}
                      </Text>
                    </div>
                  </div>
                  <div className="shrink-0 flex items-center gap-2 flex-wrap">
                    <Button
                      icon={<TableOutlined />}
                      onClick={() => handleViewSchema(selectedKb.id)}
                    >
                      Browse Schema
                    </Button>
                    <Button
                      icon={<SyncOutlined />}
                      onClick={() => handleSyncSchema(selectedKb.id)}
                    >
                      Re-Sync
                    </Button>
                    <Button
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => confirmDeleteDatabase(selectedKb)}
                    >
                      Delete
                    </Button>
                  </div>
                </div>
              </Card>

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
                type="card"
                items={[
                  {
                    key: "query",
                    label: (
                      <span className="flex items-center gap-1">
                        <SearchOutlined /> Natural Language Query Agent
                      </span>
                    ),
                    children: (
                      <div className="flex flex-col gap-4">
                        {/* Query Input */}
                        <Card
                          style={{
                            background: "var(--app-surface)",
                            borderColor: "var(--app-border)",
                            borderRadius: 12,
                          }}
                          styles={{ body: { padding: 16 } }}
                        >
                          <div className="flex gap-2 w-full">
                            <Input
                              size="large"
                              placeholder="Ask any natural-language question about this database..."
                              value={userQuery}
                              onChange={(e) => setUserQuery(e.target.value)}
                              onPressEnter={() => handleRunQuery()}
                              disabled={queryLoading}
                              prefix={<SearchOutlined style={{ color: "#8c8c8c" }} />}
                              style={{
                                borderRadius: 8,
                                background: "var(--app-surface)",
                                borderColor: "var(--app-border)",
                                color: "var(--app-text)",
                                flex: 1,
                                minWidth: 0,
                              }}
                            />
                            <Button
                              type="primary"
                              size="large"
                              loading={queryLoading}
                              onClick={() => handleRunQuery()}
                              className="shrink-0 whitespace-nowrap min-w-[140px] px-6"
                              style={{
                                backgroundColor: "var(--app-primary)",
                                borderColor: "var(--app-primary)",
                                borderRadius: 8,
                                fontWeight: 600,
                                flexShrink: 0,
                              }}
                            >
                              Ask Database
                            </Button>
                          </div>
                        </Card>

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
                                  message="Query Execution Notices"
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
                        <Card
                          title={
                            <div className="flex items-center justify-between">
                              <span className="flex items-center gap-2">
                                <SafetyCertificateOutlined style={{ color: "var(--app-primary)" }} />
                                Subsystem Health & Diagnostics Probe
                              </span>
                              <Button
                                size="small"
                                icon={<SyncOutlined spin={metricsLoading} />}
                                onClick={() => fetchMetricsAndHealth(selectedKb.id)}
                              >
                                Run Diagnostics
                              </Button>
                            </div>
                          }
                          style={{
                            background: "var(--app-surface)",
                            borderColor: "var(--app-border)",
                            borderRadius: 12,
                          }}
                        >
                          <Row gutter={[16, 16]}>
                            <Col xs={24} sm={12} md={6}>
                              <div className="p-3 bg-gray-900 rounded-lg text-center border border-gray-800">
                                <Text style={{ fontSize: 12, color: "#8c8c8c", display: "block" }}>
                                  Connectivity
                                </Text>
                                <Tag
                                  color={healthData?.status === "HEALTHY" ? "green" : "red"}
                                  style={{ marginTop: 6, fontSize: 13, padding: "2px 8px" }}
                                >
                                  {healthData?.status || "UNKNOWN"}
                                </Tag>
                              </div>
                            </Col>
                            <Col xs={24} sm={12} md={6}>
                              <div className="p-3 bg-gray-900 rounded-lg text-center border border-gray-800">
                                <Text style={{ fontSize: 12, color: "#8c8c8c", display: "block" }}>
                                  Target DB Ping
                                </Text>
                                <div className="text-lg font-mono font-bold text-teal-300 mt-1">
                                  {healthData?.database_ping_ms !== undefined ? `${healthData.database_ping_ms} ms` : "N/A"}
                                </div>
                              </div>
                            </Col>
                            <Col xs={24} sm={12} md={6}>
                              <div className="p-3 bg-gray-900 rounded-lg text-center border border-gray-800">
                                <Text style={{ fontSize: 12, color: "#8c8c8c", display: "block" }}>
                                  Read-Only Policy
                                </Text>
                                <Tag color="cyan" style={{ marginTop: 6, fontSize: 12 }}>
                                  READ-ONLY (SELECT)
                                </Tag>
                              </div>
                            </Col>
                            <Col xs={24} sm={12} md={6}>
                              <div className="p-3 bg-gray-900 rounded-lg text-center border border-gray-800">
                                <Text style={{ fontSize: 12, color: "#8c8c8c", display: "block" }}>
                                  Schema State
                                </Text>
                                <Tag color="blue" style={{ marginTop: 6, fontSize: 12 }}>
                                  {healthData?.schema_freshness_status || "CURRENT"}
                                </Tag>
                              </div>
                            </Col>
                          </Row>
                        </Card>

                        {/* Operational KPIs Card */}
                        <Card
                          title="Production Operational Metrics"
                          style={{
                            background: "var(--app-surface)",
                            borderColor: "var(--app-border)",
                            borderRadius: 12,
                          }}
                        >
                          <Row gutter={[16, 16]}>
                            <Col xs={12} sm={8} md={4}>
                              <Card size="small" style={{ background: "rgba(16, 185, 129, 0.05)", borderColor: "#10b981" }}>
                                <Statistic
                                  title="Success Rate"
                                  value={metricsData ? (metricsData.rates.query_success_rate * 100).toFixed(1) : 100}
                                  suffix="%"
                                  valueStyle={{ color: "#10b981", fontWeight: 700 }}
                                />
                              </Card>
                            </Col>
                            <Col xs={12} sm={8} md={4}>
                              <Card size="small" style={{ background: "var(--app-surface)", borderColor: "var(--app-border)" }}>
                                <Statistic
                                  title="Total Queries"
                                  value={metricsData?.counts.total_queries || 0}
                                  valueStyle={{ color: "var(--app-text)" }}
                                />
                              </Card>
                            </Col>
                            <Col xs={12} sm={8} md={4}>
                              <Card size="small" style={{ background: "var(--app-surface)", borderColor: "var(--app-border)" }}>
                                <Statistic
                                  title="P95 Latency"
                                  value={metricsData?.latencies_ms.total.p95 ? metricsData.latencies_ms.total.p95.toFixed(0) : 0}
                                  suffix="ms"
                                  valueStyle={{ color: "#38bdf8" }}
                                />
                              </Card>
                            </Col>
                            <Col xs={12} sm={8} md={4}>
                              <Card size="small" style={{ background: "var(--app-surface)", borderColor: "var(--app-border)" }}>
                                <Statistic
                                  title="DB Driver Avg"
                                  value={metricsData?.latencies_ms.database_execution.avg ? metricsData.latencies_ms.database_execution.avg.toFixed(1) : 0}
                                  suffix="ms"
                                  valueStyle={{ color: "#a855f7" }}
                                />
                              </Card>
                            </Col>
                            <Col xs={12} sm={8} md={4}>
                              <Card size="small" style={{ background: "var(--app-surface)", borderColor: "var(--app-border)" }}>
                                <Statistic
                                  title="Security Rejections"
                                  value={metricsData?.counts.security_rejections || 0}
                                  valueStyle={{ color: metricsData?.counts.security_rejections ? "#ef4444" : "#10b981" }}
                                />
                              </Card>
                            </Col>
                            <Col xs={12} sm={8} md={4}>
                              <Card size="small" style={{ background: "var(--app-surface)", borderColor: "var(--app-border)" }}>
                                <Statistic
                                  title="Fallback Rate"
                                  value={metricsData ? (metricsData.rates.fallback_rate * 100).toFixed(1) : 0}
                                  suffix="%"
                                  valueStyle={{ color: "#f59e0b" }}
                                />
                              </Card>
                            </Col>
                          </Row>
                        </Card>

                        {/* Pipeline Stage Latencies Breakdown */}
                        <Card
                          title="Stage Latency Breakdown & Observability Overview"
                          style={{
                            background: "var(--app-surface)",
                            borderColor: "var(--app-border)",
                            borderRadius: 12,
                          }}
                        >
                          <div className="flex flex-col gap-3">
                            <div className="flex items-center justify-between text-xs">
                              <span className="font-semibold">1. Schema Retrieval (Phase 2A):</span>
                              <span className="text-teal-400 font-mono">Semantic cosine ranking & join graph discovery</span>
                            </div>
                            <div className="flex items-center justify-between text-xs">
                              <span className="font-semibold">2. Query Planning (Phase 2B):</span>
                              <span className="text-teal-400 font-mono">QueryPlanIR schema validation & join safety</span>
                            </div>
                            <div className="flex items-center justify-between text-xs">
                              <span className="font-semibold">3. Candidate SQL Generation & AST Policy (Phase 2B):</span>
                              <span className="text-teal-400 font-mono">Parameterization & strict read-only AST boundary</span>
                            </div>
                            <div className="flex items-center justify-between text-xs">
                              <span className="font-semibold">4. Safe Driver Execution (Phase 2C):</span>
                              <span className="text-teal-400 font-mono">asyncpg read-only session with strict timeouts</span>
                            </div>
                            <div className="flex items-center justify-between text-xs">
                              <span className="font-semibold">5. Grounded Synthesis & Verification (Phase 2D):</span>
                              <span className="text-teal-400 font-mono">Deterministic fast-path & entity anti-hallucination verification</span>
                            </div>
                          </div>
                        </Card>
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
                onChange={(v) => setFormPort(v || 5432)}
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

          {/* Test Connection Result Alert */}
          {testResult && (
            <Alert
              type={testResult.success ? "success" : "error"}
              showIcon
              message={testResult.success ? "Connection Succeeded" : "Connection Failed"}
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
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pr-8 w-full">
            <div className="flex items-center gap-2">
              <ApartmentOutlined style={{ color: "var(--app-primary)", fontSize: 20 }} />
              <span className="font-semibold text-lg text-[var(--app-text)]">
                Database Canonical Schema Explorer
              </span>
            </div>
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
                    backgroundColor: "var(--app-primary)",
                    borderColor: "var(--app-primary)",
                    borderRadius: 8,
                    fontWeight: 600,
                  }}
                >
                  Download Schema <DownOutlined />
                </Button>
              </Dropdown>
            )}
          </div>
        }
        open={schemaModalOpen}
        onCancel={() => setSchemaModalOpen(false)}
        footer={null}
        width={1050}
        style={{ top: 24 }}
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
            {/* Schema Summary Cards */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-5">
              <Card size="small" className="text-center" style={{ background: "var(--app-surface)", borderColor: "var(--app-border)" }}>
                <Text type="secondary" style={{ fontSize: 12 }}>Tables Discovered</Text>
                <Title level={3} style={{ margin: "4px 0 0", color: "var(--app-primary)" }}>
                  {schemaData.summary?.table_count ?? allSchemaTables.length}
                </Title>
              </Card>
              <Card size="small" className="text-center" style={{ background: "var(--app-surface)", borderColor: "var(--app-border)" }}>
                <Text type="secondary" style={{ fontSize: 12 }}>Columns Discovered</Text>
                <Title level={3} style={{ margin: "4px 0 0", color: "var(--app-text)" }}>
                  {schemaData.summary?.column_count ?? 0}
                </Title>
              </Card>
              <Card size="small" className="text-center" style={{ background: "var(--app-surface)", borderColor: "var(--app-border)" }}>
                <Text type="secondary" style={{ fontSize: 12 }}>Foreign Keys</Text>
                <Title level={3} style={{ margin: "4px 0 0", color: "var(--app-text)" }}>
                  {schemaData.summary?.foreign_key_count ?? 0}
                </Title>
              </Card>
              <Card size="small" className="text-center" style={{ background: "var(--app-surface)", borderColor: "var(--app-border)" }}>
                <Text type="secondary" style={{ fontSize: 12 }}>Relationships</Text>
                <Title level={3} style={{ margin: "4px 0 0", color: "var(--app-text)" }}>
                  {schemaData.summary?.relationship_count ?? 0}
                </Title>
              </Card>
            </div>

            {/* Toolbar: Search Filter & Fingerprint */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4 p-3 rounded-xl bg-[var(--app-surface-muted)] border border-[var(--app-border)]">
              <Input
                prefix={<SearchOutlined style={{ color: "#8c8c8c" }} />}
                placeholder="Search tables or columns (e.g. employee, salary, department)..."
                value={schemaSearchQuery}
                onChange={(e) => setSchemaSearchQuery(e.target.value)}
                allowClear
                style={{ maxWidth: 420 }}
              />
              <div className="flex items-center gap-3 text-xs text-gray-400">
                <span>
                  Showing <strong className="text-[var(--app-primary)]">{filteredSchemaTables.length}</strong> of {allSchemaTables.length} tables
                </span>
                <span className="hidden md:inline">|</span>
                <span className="font-mono text-gray-400">
                  Fingerprint: {schemaData.fingerprint ? schemaData.fingerprint.substring(0, 10) : "N/A"}
                </span>
              </div>
            </div>

            {/* Tables Accordion or Empty State */}
            {filteredSchemaTables.length === 0 ? (
              <div className="py-12 text-center">
                <Empty description="No tables match your search query." />
              </div>
            ) : (
              <div className="max-h-[60vh] overflow-y-auto pr-1 custom-scrollbar">
                <Collapse
                  accordion
                  items={filteredSchemaTables.map((tbl: any) => {
                    const cols = Array.isArray(tbl.columns) ? tbl.columns : Object.values(tbl.columns || {});
                    return {
                      key: tbl.table_name,
                      label: (
                        <div className="flex items-center justify-between w-full pr-4">
                          <span className="font-mono font-semibold text-sm text-[var(--app-text)]">
                            {tbl.table_name}
                          </span>
                          <Space size="small">
                            {tbl.comment && <Tag color="blue">{tbl.comment}</Tag>}
                            <Tag color="cyan">{cols.length} columns</Tag>
                          </Space>
                        </div>
                      ),
                      children: (
                        <div>
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
                                    {name} {record.is_primary_key && <Tag color="gold" style={{ fontSize: 10, padding: "0 4px" }}>PK</Tag>}
                                  </span>
                                ),
                              },
                              {
                                title: "Data Type",
                                dataIndex: "data_type",
                                key: "data_type",
                                render: (type: string) => <Tag color="purple" style={{ fontSize: 11 }}>{type}</Tag>,
                              },
                              {
                                title: "Nullable",
                                dataIndex: "is_nullable",
                                key: "is_nullable",
                                render: (n: boolean) => (n ? <span className="text-gray-400 text-xs">YES</span> : <Tag color="default" style={{ fontSize: 10 }}>NOT NULL</Tag>),
                              },
                              {
                                title: "Description / Comment",
                                dataIndex: "comment",
                                key: "comment",
                                render: (c: string) => <span className="text-gray-400 text-xs">{c || "—"}</span>,
                              },
                            ]}
                            pagination={false}
                          />

                          {tbl.foreign_keys && tbl.foreign_keys.length > 0 && (
                            <div className="mt-3 p-3 rounded-lg bg-[var(--app-surface-muted)] border border-[var(--app-border)]">
                              <Text strong style={{ fontSize: 12, color: "var(--app-text)" }}>
                                Foreign Key Outgoing Links:
                              </Text>
                              <div className="flex flex-col gap-1.5 mt-1.5">
                                {tbl.foreign_keys.map((fk: any, idx: number) => (
                                  <Text key={idx} className="text-xs text-gray-400 font-mono">
                                    ↳ ({(fk.constrained_columns || []).join(", ")}) references{" "}
                                    <Text strong className="text-[var(--app-primary)]">{fk.referred_table}</Text>
                                    ({(fk.referred_columns || []).join(", ")})
                                  </Text>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      ),
                    };
                  })}
                />
              </div>
            )}
          </div>
        ) : (
          <Alert type="warning" message="No canonical schema information available. Please sync schema first." />
        )}
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
              <Space direction="vertical" align="end">
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
                  <Alert type="warning" message="Deterministic Fallback Activated for this query" showIcon />
                )}
                {inspectedTrace.sanitized_error && (
                  <Alert type="error" message={`Error: ${inspectedTrace.sanitized_error}`} showIcon />
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
              <Space direction="vertical" align="end">
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
                      {Object.entries(groundedAnswer.pipeline_trace.retrieval.table_scores).map(([tbl, sc]) => (
                        <span key={tbl} className="mr-3">
                          {tbl}: <b>{sc}</b>
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
          <Alert message="No trace telemetry available for this query." type="info" />
        )}
      </Drawer>
    </div>
  );
}
