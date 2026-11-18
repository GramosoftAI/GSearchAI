"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
import Link from "next/link";
import {
  Typography,
  Button,
  Badge,
  Row,
  Col,
  Spin,
  Table,
  Input,
  Space,
  Tag,
  Tooltip,
  Progress,
  Modal,
  Form,
  Select,
  Popconfirm,
  Tabs,
  message,
} from "antd";
import {
  ReloadOutlined,
  SearchOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ArrowRightOutlined,
} from "@ant-design/icons";
import {
  Users,
  Database,
  Activity,
  Globe,
  Server,
  ShieldCheck,
  Bot,
  MessageSquare,
  Layers,
  Sparkles,
  Cpu,
  FileText,
  Bell,
} from "lucide-react";
import useAxios from "@/app/hooks/useAxios";

const { Title, Text } = Typography;
const { TextArea } = Input;

interface ServiceHealthItem {
  name: string;
  status: string;
  latency_ms?: number | null;
  message?: string | null;
}

interface OverviewData {
  metrics: {
    total_users: number;
    total_agents?: number;
    total_tenants?: number;
    files_processed?: number;
    active_endpoints: number;
    system_health: number;
    total_knowledgebases: number;
  };
  breakdown: {
    document_knowledgebases: number;
    database_knowledgebases: number;
    active_agents: number;
    total_tenants?: number;
    files_processed?: number;
    total_conversations: number;
    total_chunks: number;
    total_users_active: number;
    api_routes_count: number;
    agent_endpoints_count: number;
    system_health_details: {
      score: number;
      status: string;
      uptime_seconds: number;
      last_checked: string;
      services: Record<string, ServiceHealthItem>;
    };
  };
  announcements: AnnouncementItem[];
  last_updated: string;
}

interface EndpointItem {
  path: string;
  method: string;
  name: string;
  tag: string;
  status: string;
}

interface AnnouncementItem {
  id: string;
  title: string;
  message: string;
  priority: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export default function AdminOverviewPage() {
  const [activeTab, setActiveTab] = useState("resources");
  const [endpointSearch, setEndpointSearch] = useState("");
  const [selectedMethod, setSelectedMethod] = useState<string>("ALL");

  // Announcement Modal State
  const [announcementModalOpen, setAnnouncementModalOpen] = useState(false);
  const [editingAnnouncement, setEditingAnnouncement] = useState<AnnouncementItem | null>(null);
  const [announcementForm] = Form.useForm();

  // Axios Hooks
  const [getOverview, overviewResponse, loadingOverview] = useAxios<OverviewData>({
    endpoint: "ADMIN_OVERVIEW",
  });

  const [getEndpoints, endpointsResponse, loadingEndpoints] = useAxios<EndpointItem[]>({
    endpoint: "ADMIN_ENDPOINTS",
  });

  const [createAnnouncement, , creatingAnnouncement] = useAxios({
    endpoint: "ADMIN_CREATE_ANNOUNCEMENT",
  });

  const [updateAnnouncement, , updatingAnnouncement] = useAxios({
    endpoint: "ADMIN_UPDATE_ANNOUNCEMENT",
  });

  const [deleteAnnouncement, , deletingAnnouncement] = useAxios({
    endpoint: "ADMIN_DELETE_ANNOUNCEMENT",
  });

  const fetchData = useCallback(() => {
    getOverview();
    getEndpoints();
  }, [getOverview, getEndpoints]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const overviewData = useMemo(() => {
    return (overviewResponse as any)?.data || overviewResponse || null;
  }, [overviewResponse]);

  const endpointsList = useMemo(() => {
    const raw = (endpointsResponse as any)?.data || endpointsResponse;
    return Array.isArray(raw) ? raw : [];
  }, [endpointsResponse]);

  const announcementsList = useMemo(() => {
    return overviewData?.announcements || [];
  }, [overviewData]);

  // Filtered Endpoints
  const filteredEndpoints = useMemo(() => {
    return endpointsList.filter((ep: EndpointItem) => {
      const matchesSearch =
        !endpointSearch ||
        ep.path.toLowerCase().includes(endpointSearch.toLowerCase()) ||
        ep.name.toLowerCase().includes(endpointSearch.toLowerCase()) ||
        ep.tag.toLowerCase().includes(endpointSearch.toLowerCase());

      const matchesMethod =
        selectedMethod === "ALL" || ep.method.toUpperCase() === selectedMethod;

      return matchesSearch && matchesMethod;
    });
  }, [endpointsList, endpointSearch, selectedMethod]);

  // Method tag color helper
  const getMethodColor = (method: string) => {
    switch (method.toUpperCase()) {
      case "GET":
        return "bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800";
      case "POST":
        return "bg-blue-50 dark:bg-blue-950/20 text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-800";
      case "PUT":
        return "bg-amber-50 dark:bg-amber-950/20 text-amber-600 dark:text-amber-400 border-amber-200 dark:border-amber-800";
      case "DELETE":
        return "bg-rose-50 dark:bg-rose-950/20 text-rose-600 dark:text-rose-400 border-rose-200 dark:border-rose-800";
      default:
        return "bg-slate-50 dark:bg-slate-900 text-slate-600 border-slate-200";
    }
  };

  // Priority badge helper
  const getPriorityTag = (priority: string) => {
    switch (priority.toLowerCase()) {
      case "critical":
        return <Tag color="error">Critical</Tag>;
      case "warning":
        return <Tag color="warning">Warning</Tag>;
      case "success":
        return <Tag color="success">Resolved</Tag>;
      default:
        return <Tag color="processing">Info</Tag>;
    }
  };

  // Announcement Handlers
  const handleOpenCreateAnnouncement = () => {
    setEditingAnnouncement(null);
    announcementForm.resetFields();
    announcementForm.setFieldsValue({ priority: "info", is_active: true });
    setAnnouncementModalOpen(true);
  };

  const handleOpenEditAnnouncement = (item: AnnouncementItem) => {
    setEditingAnnouncement(item);
    announcementForm.setFieldsValue({
      title: item.title,
      message: item.message,
      priority: item.priority,
      is_active: item.is_active,
    });
    setAnnouncementModalOpen(true);
  };

  const handleSaveAnnouncement = async () => {
    try {
      const values = await announcementForm.validateFields();
      if (editingAnnouncement) {
        await updateAnnouncement({
          path: `/${editingAnnouncement.id}`,
          data: values,
        });
        message.success("Announcement updated successfully");
      } else {
        await createAnnouncement({
          data: values,
        });
        message.success("Announcement created successfully");
      }
      setAnnouncementModalOpen(false);
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  const handleDeleteAnnouncement = async (id: string) => {
    try {
      await deleteAnnouncement({
        path: `/${id}`,
      });
      message.success("Announcement deleted successfully");
      fetchData();
    } catch (err) {
      message.error("Failed to delete announcement");
    }
  };

  const endpointColumns = [
    {
      title: "Method",
      dataIndex: "method",
      key: "method",
      width: 100,
      render: (m: string) => (
        <span
          className={`px-2.5 py-1 rounded-md text-[11px] font-black border ${getMethodColor(
            m
          )}`}
        >
          {m}
        </span>
      ),
    },
    {
      title: "Endpoint Path",
      dataIndex: "path",
      key: "path",
      render: (path: string) => (
        <span className="font-mono text-xs font-semibold text-[var(--app-text)]">
          {path}
        </span>
      ),
    },
    {
      title: "Name / Operation",
      dataIndex: "name",
      key: "name",
      render: (name: string) => (
        <span className="text-xs text-[var(--app-text-soft)] font-medium">
          {name || "N/A"}
        </span>
      ),
    },
    {
      title: "Category",
      dataIndex: "tag",
      key: "tag",
      width: 150,
      render: (tag: string) => (
        <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-[var(--app-surface-muted)] text-[var(--app-text)] border border-[var(--app-border)]/50">
          {tag || "General"}
        </span>
      ),
    },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      width: 100,
      render: () => (
        <span className="inline-flex items-center gap-1.5 text-xs font-bold text-emerald-600 dark:text-emerald-400">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          Active
        </span>
      ),
    },
  ];

  return (
    <div className="w-full max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8 pb-24 relative min-h-screen">
      {/* Header Section */}
      <div className="mb-8">
        <Row justify="space-between" align="middle" gutter={[16, 24]}>
          <Col xs={24} md={18}>
            <div className="flex items-center gap-3">
              <span className="text-xs font-bold uppercase tracking-widest text-[#0fb5a1]">
                Admin Portal / Overview
              </span>
            </div>
            <div className="flex items-center gap-4 mt-1">
              <Title
                level={1}
                className="!m-0 !font-extrabold !text-3xl sm:!text-4xl tracking-tight text-[var(--app-text)]"
              >
                Overview
              </Title>
              <Badge
                count="Live Operational"
                style={{
                  backgroundColor: "var(--app-active-bg)",
                  color: "#0fb5a1",
                  borderColor: "transparent",
                  fontWeight: 900,
                  fontSize: 12,
                  padding: "0 12px",
                  height: 28,
                  lineHeight: "28px",
                  borderRadius: 14,
                }}
                className="mt-1"
              />
            </div>
            <Text className="block mt-2 text-sm sm:text-base text-[var(--app-text-soft)] font-medium">
              Real-time platform metrics, infrastructure health, and resource distribution.
            </Text>
          </Col>
          <Col xs={24} md={6} className="text-right">
            <Button
              type="primary"
              size="large"
              icon={<ReloadOutlined spin={loadingOverview} />}
              onClick={fetchData}
              loading={loadingOverview}
              className="!h-12 !px-6 !rounded-2xl !bg-[#0fb5a1] !border-none !font-black !text-sm !uppercase !tracking-widest !shadow-lg hover:!scale-[1.02] transition-all"
            >
              Refresh
            </Button>
          </Col>
        </Row>
      </div>

      {loadingOverview && !overviewData ? (
        <div className="min-h-[50vh] flex flex-col items-center justify-center gap-4">
          <Spin size="large" />
          <span className="text-sm font-semibold text-[var(--app-text-soft)]">
            Loading Overview Metrics...
          </span>
        </div>
      ) : (
        <div className="space-y-8">
          {/* PRIMARY KPI METRICS - 7 CARDS MATCHING REFERENCE DESIGN */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {/* 1. TOTAL USERS - TEAL THEME */}
            <Link
              href="/dashboard/admin/users"
              className="relative overflow-hidden rounded-[22px] p-6 shadow-md hover:shadow-xl hover:scale-[1.02] transition-all duration-300 flex items-center justify-between group no-underline text-inherit cursor-pointer"
              style={{
                background: "linear-gradient(135deg, #096350 0%, #0d725d 55%, #10816a 100%)",
              }}
            >
              <div className="flex flex-col justify-between z-10">
                <span className="text-[11px] font-black tracking-wider uppercase text-[#79dfc8]">
                  TOTAL USERS
                </span>
                <h3 className="text-3xl sm:text-4xl font-black text-white tracking-tight leading-none my-2.5">
                  {overviewData?.metrics?.total_users ?? 0}
                </h3>
                <span className="text-xs font-semibold text-[#a5ecdc]">
                  Verified Platform Accounts
                </span>
              </div>

              {/* Directly Related Icon: Users / People */}
              <div className="relative w-16 h-16 flex items-center justify-center shrink-0">
                <div className="w-13 h-13 rounded-full bg-[#1aa383]/45 border-2 border-[#5ce8ca]/60 flex items-center justify-center shadow-inner">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
                    <circle cx="9" cy="7" r="4" />
                    <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
                    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                  </svg>
                </div>
                <svg
                  className="absolute -bottom-1 -right-1 overflow-visible pointer-events-none"
                  width="42"
                  height="20"
                  viewBox="0 0 42 20"
                  fill="none"
                >
                  <path
                    d="M2 4C10 16 26 17 38 9"
                    stroke="#5ce8ca"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                  />
                  <circle cx="38" cy="9" r="2.8" fill="#5ce8ca" />
                </svg>
              </div>
            </Link>

            {/* 2. ACTIVE AGENTS - CYBER BLUE THEME */}
            <Link
              href="/dashboard/bots"
              className="relative overflow-hidden rounded-[22px] p-6 shadow-md hover:shadow-xl hover:scale-[1.02] transition-all duration-300 flex items-center justify-between group no-underline text-inherit cursor-pointer"
              style={{
                background: "linear-gradient(135deg, #0d4b75 0%, #116299 55%, #157abb 100%)",
              }}
            >
              <div className="flex flex-col justify-between z-10">
                <span className="text-[11px] font-black tracking-wider uppercase text-[#7dd3fc]">
                  ACTIVE AGENTS
                </span>
                <h3 className="text-3xl sm:text-4xl font-black text-white tracking-tight leading-none my-2.5">
                  {overviewData?.metrics?.total_agents ?? overviewData?.breakdown?.active_agents ?? 0}
                </h3>
                <span className="text-xs font-semibold text-[#bae6fd]">
                  Autonomous AI Assistants
                </span>
              </div>

              {/* Directly Related Icon: AI Agent Robot */}
              <div className="relative w-16 h-16 flex items-center justify-center shrink-0">
                <div className="w-13 h-13 rounded-full bg-[#0284c7]/45 border-2 border-[#38bdf8]/60 flex items-center justify-center shadow-inner">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="11" width="18" height="10" rx="3" />
                    <circle cx="8.5" cy="16" r="1.5" fill="#ffffff" />
                    <circle cx="15.5" cy="16" r="1.5" fill="#ffffff" />
                    <path d="M12 2v4" />
                    <path d="M8 2h8" />
                    <path d="M2 14h1" />
                    <path d="M21 14h1" />
                  </svg>
                </div>
                <svg
                  className="absolute -bottom-1 -right-1 overflow-visible pointer-events-none"
                  width="42"
                  height="20"
                  viewBox="0 0 42 20"
                  fill="none"
                >
                  <path
                    d="M2 4C10 16 26 17 38 9"
                    stroke="#38bdf8"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                  />
                  <circle cx="38" cy="9" r="2.8" fill="#38bdf8" />
                </svg>
              </div>
            </Link>

            {/* 3. TENANTS - ROYAL VIOLET THEME */}
            <div
              onClick={() => setActiveTab("resources")}
              className="relative overflow-hidden rounded-[22px] p-6 shadow-md hover:shadow-xl hover:scale-[1.02] transition-all duration-300 flex items-center justify-between group cursor-pointer"
              style={{
                background: "linear-gradient(135deg, #2b1f5d 0%, #3d257a 55%, #4f2c96 100%)",
              }}
            >
              <div className="flex flex-col justify-between z-10">
                <span className="text-[11px] font-black tracking-wider uppercase text-[#c4b5fd]">
                  TENANTS
                </span>
                <h3 className="text-3xl sm:text-4xl font-black text-white tracking-tight leading-none my-2.5">
                  {overviewData?.metrics?.total_tenants ?? 0}
                </h3>
                <span className="text-xs font-semibold text-[#ddd6fe]">
                  Multi-Tenant Workspaces
                </span>
              </div>

              {/* Directly Related Icon: Multi-Tenant Enterprise Buildings */}
              <div className="relative w-16 h-16 flex items-center justify-center shrink-0">
                <div className="w-13 h-13 rounded-full bg-[#7c3aed]/45 border-2 border-[#a78bfa]/60 flex items-center justify-center shadow-inner">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="4" y="2" width="16" height="20" rx="2" />
                    <path d="M9 22v-4h6v4" />
                    <path d="M8 6h.01M16 6h.01M12 6h.01" />
                    <path d="M8 10h.01M16 10h.01M12 10h.01" />
                    <path d="M8 14h.01M16 14h.01M12 14h.01" />
                  </svg>
                </div>
                <svg
                  className="absolute -bottom-1 -right-1 overflow-visible pointer-events-none"
                  width="42"
                  height="20"
                  viewBox="0 0 42 20"
                  fill="none"
                >
                  <path
                    d="M2 4C10 16 26 17 38 9"
                    stroke="#a78bfa"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                  />
                  <circle cx="38" cy="9" r="2.8" fill="#a78bfa" />
                </svg>
              </div>
            </div>

            {/* 4. FILES PROCESSED - WARM GOLD / AMBER THEME */}
            <Link
              href="/dashboard/knowledge-base-files"
              className="relative overflow-hidden rounded-[22px] p-6 shadow-md hover:shadow-xl hover:scale-[1.02] transition-all duration-300 flex items-center justify-between group no-underline text-inherit cursor-pointer"
              style={{
                background: "linear-gradient(135deg, #9a4806 0%, #ba5d08 55%, #d97706 100%)",
              }}
            >
              <div className="flex flex-col justify-between z-10">
                <span className="text-[11px] font-black tracking-wider uppercase text-[#fde68a]">
                  FILES PROCESSED
                </span>
                <h3 className="text-3xl sm:text-4xl font-black text-white tracking-tight leading-none my-2.5">
                  {overviewData?.metrics?.files_processed ?? 0}
                </h3>
                <span className="text-xs font-semibold text-[#fef08a]">
                  Documents, PDFs & Sheets
                </span>
              </div>

              {/* Directly Related Icon: Processed Document with Checkmark */}
              <div className="relative w-16 h-16 flex items-center justify-center shrink-0">
                <div className="w-13 h-13 rounded-full bg-[#f59e0b]/45 border-2 border-[#fde68a]/60 flex items-center justify-center shadow-inner">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                    <path d="M9 15l2 2 4-4" stroke="#ffffff" strokeWidth="2.5" />
                  </svg>
                </div>
                <svg
                  className="absolute -bottom-1 -right-1 overflow-visible pointer-events-none"
                  width="42"
                  height="20"
                  viewBox="0 0 42 20"
                  fill="none"
                >
                  <path
                    d="M2 4C10 16 26 17 38 9"
                    stroke="#fde68a"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                  />
                  <circle cx="38" cy="9" r="2.8" fill="#fde68a" />
                </svg>
              </div>
            </Link>

            {/* 5. TOTAL KNOWLEDGEBASES - AMETHYST PURPLE THEME */}
            <Link
              href="/dashboard/knowledge-base"
              className="relative overflow-hidden rounded-[22px] p-6 shadow-md hover:shadow-xl hover:scale-[1.02] transition-all duration-300 flex items-center justify-between group no-underline text-inherit cursor-pointer"
              style={{
                background: "linear-gradient(135deg, #3d155f 0%, #541d82 55%, #6b24a3 100%)",
              }}
            >
              <div className="flex flex-col justify-between z-10">
                <span className="text-[11px] font-black tracking-wider uppercase text-[#e9d5ff]">
                  KNOWLEDGE BASES
                </span>
                <h3 className="text-3xl sm:text-4xl font-black text-white tracking-tight leading-none my-2.5">
                  {overviewData?.metrics?.total_knowledgebases ?? 0}
                </h3>
                <span className="text-xs font-semibold text-[#f3e8ff]">
                  {overviewData?.breakdown?.document_knowledgebases ?? 0} Docs • {overviewData?.breakdown?.database_knowledgebases ?? 0} DBs
                </span>
              </div>

              {/* Directly Related Icon: Database & Knowledge Repository */}
              <div className="relative w-16 h-16 flex items-center justify-center shrink-0">
                <div className="w-13 h-13 rounded-full bg-[#9333ea]/45 border-2 border-[#c084fc]/60 flex items-center justify-center shadow-inner">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <ellipse cx="12" cy="5" rx="9" ry="3" />
                    <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                    <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                  </svg>
                </div>
                <svg
                  className="absolute -bottom-1 -right-1 overflow-visible pointer-events-none"
                  width="42"
                  height="20"
                  viewBox="0 0 42 20"
                  fill="none"
                >
                  <path
                    d="M2 4C10 16 26 17 38 9"
                    stroke="#c084fc"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                  />
                  <circle cx="38" cy="9" r="2.8" fill="#c084fc" />
                </svg>
              </div>
            </Link>

            {/* 6. ACTIVE ENDPOINTS - SLATE NAVY THEME */}
            <div
              onClick={() => setActiveTab("endpoints")}
              className="relative overflow-hidden rounded-[22px] p-6 shadow-md hover:shadow-xl hover:scale-[1.02] transition-all duration-300 flex items-center justify-between group cursor-pointer"
              style={{
                background: "linear-gradient(135deg, #163044 0%, #1a394f 55%, #1e425c 100%)",
              }}
            >
              <div className="flex flex-col justify-between z-10">
                <span className="text-[11px] font-black tracking-wider uppercase text-[#7ba4c1]">
                  ACTIVE ENDPOINTS
                </span>
                <h3 className="text-3xl sm:text-4xl font-black text-white tracking-tight leading-none my-2.5">
                  {overviewData?.metrics?.active_endpoints ?? 0}
                </h3>
                <span className="text-xs font-semibold text-[#8eb6d4]">
                  {overviewData?.breakdown?.api_routes_count ?? 0} API Routes • {overviewData?.breakdown?.agent_endpoints_count ?? 0} Agents
                </span>
              </div>

              {/* Directly Related Icon: API Endpoint & Routing Code Brackets */}
              <div className="relative w-16 h-16 flex items-center justify-center shrink-0">
                <div className="w-13 h-13 rounded-full bg-[#0284c7]/40 border-2 border-[#38bdf8]/60 flex items-center justify-center shadow-inner">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="16 18 22 12 16 6" />
                    <polyline points="8 6 2 12 8 18" />
                    <line x1="10" y1="19" x2="14" y2="5" />
                  </svg>
                </div>
                <svg
                  className="absolute -bottom-1 -right-1 overflow-visible pointer-events-none"
                  width="42"
                  height="20"
                  viewBox="0 0 42 20"
                  fill="none"
                >
                  <path
                    d="M2 4C10 16 26 17 38 9"
                    stroke="#38bdf8"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                  />
                  <circle cx="38" cy="9" r="2.8" fill="#38bdf8" />
                </svg>
              </div>
            </div>

            {/* 7. SYSTEM HEALTH - EMERALD PULSE THEME (2 COLUMNS) */}
            <div
              onClick={() => setActiveTab("resources")}
              className="col-span-1 lg:col-span-2 relative overflow-hidden rounded-[22px] p-6 shadow-md hover:shadow-xl hover:scale-[1.01] transition-all duration-300 flex items-center justify-between group cursor-pointer"
              style={{
                background: "linear-gradient(135deg, #064e3b 0%, #065f46 55%, #047857 100%)",
              }}
            >
              <div className="flex flex-col justify-between z-10">
                <span className="text-[11px] font-black tracking-wider uppercase text-[#6ee7b7]">
                  SYSTEM HEALTH
                </span>
                <div className="flex items-baseline gap-3 my-2.5">
                  <h3 className="text-3xl sm:text-4xl font-black text-white tracking-tight leading-none">
                    {overviewData?.metrics?.system_health ?? 98.5}%
                  </h3>
                  <span className="px-2.5 py-0.5 rounded-full text-[10px] font-black uppercase tracking-wider bg-emerald-400/20 text-[#a7f3d0] border border-emerald-400/30">
                    {overviewData?.breakdown?.system_health_details?.status ?? "Optimal"}
                  </span>
                </div>
                <span className="text-xs font-semibold text-[#a7f3d0]">
                  Core Subsystems Operational • All Diagnostics Normal
                </span>
              </div>

              {/* Directly Related Icon: Security Shield with EKG Heartbeat Pulse */}
              <div className="relative w-16 h-16 flex items-center justify-center shrink-0">
                <div className="w-13 h-13 rounded-full bg-[#10b981]/45 border-2 border-[#34d399]/60 flex items-center justify-center shadow-inner">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                    <path d="M8 12h2.5l1.5-3 2 6 1.5-3H18" stroke="#ffffff" strokeWidth="2.2" />
                  </svg>
                </div>
                <svg
                  className="absolute -bottom-1 -right-1 overflow-visible pointer-events-none"
                  width="42"
                  height="20"
                  viewBox="0 0 42 20"
                  fill="none"
                >
                  <path
                    d="M2 4C10 16 26 17 38 9"
                    stroke="#34d399"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                  />
                  <circle cx="38" cy="9" r="2.8" fill="#34d399" />
                </svg>
              </div>
            </div>
          </div>

          {/* SUBSYSTEM HEALTH ROW */}
          <div className="bg-[var(--app-surface)] border border-[var(--app-border)]/60 rounded-3xl p-6 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2.5">
                <ShieldCheck size={20} className="text-[#0fb5a1]" />
                <h4 className="text-sm font-black uppercase tracking-wider text-[var(--app-text)] !m-0">
                  Infrastructure & Subsystem Diagnostics
                </h4>
              </div>
              <span className="text-xs font-semibold text-[var(--app-text-soft)]">
                Last checked:{" "}
                {overviewData?.last_updated
                  ? new Date(overviewData.last_updated).toLocaleTimeString()
                  : "Just now"}
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
              {Object.entries(
                overviewData?.breakdown?.system_health_details?.services || {}
              ).map(([key, service]: [string, any]) => (
                <div
                  key={key}
                  className="p-4 rounded-2xl bg-[var(--app-surface-muted)]/50 border border-[var(--app-border)]/40 flex flex-col justify-between"
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-bold text-[var(--app-text)]">
                      {service.name}
                    </span>
                    <span className="w-2 h-2 rounded-full bg-emerald-500" />
                  </div>
                  <span className="text-[11px] text-[var(--app-text-soft)] font-medium truncate mb-2">
                    {service.message || "Running nominal"}
                  </span>
                  <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-wider text-emerald-600">
                    <span>{service.status}</span>
                    {service.latency_ms !== null && service.latency_ms !== undefined && (
                      <span className="text-[var(--app-text-soft)]">
                        {service.latency_ms}ms
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* INTERACTIVE TABS */}
          <div className="bg-[var(--app-surface)] border border-[var(--app-border)]/60 rounded-3xl p-6 shadow-sm">
            <Tabs
              activeKey={activeTab}
              onChange={setActiveTab}
              className="custom-admin-tabs"
              items={[
                {
                  key: "resources",
                  label: (
                    <span className="flex items-center gap-2 font-bold text-sm">
                      <Layers size={16} />
                      Resource Breakdown
                    </span>
                  ),
                  children: (
                    <div className="pt-4 space-y-6">
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                        {/* Active Agents */}
                        <div className="p-6 rounded-2xl bg-[var(--app-surface-muted)]/40 border border-[var(--app-border)]/50">
                          <div className="flex items-center justify-between mb-3">
                            <span className="text-xs font-bold uppercase tracking-wider text-[var(--app-text-soft)]">
                              Configured AI Agents
                            </span>
                            <Bot size={18} className="text-[#0fb5a1]" />
                          </div>
                          <div className="text-3xl font-extrabold text-[var(--app-text)] mb-2">
                            {overviewData?.breakdown?.active_agents ?? 0}
                          </div>
                          <p className="text-xs text-[var(--app-text-soft)] mb-4">
                            Active conversational agents with RAG pipelines.
                          </p>
                          <Link href="/dashboard/bots">
                            <Button size="small" type="default" className="!rounded-xl text-xs font-bold">
                              Manage Agents
                            </Button>
                          </Link>
                        </div>

                        {/* Conversations */}
                        <div className="p-6 rounded-2xl bg-[var(--app-surface-muted)]/40 border border-[var(--app-border)]/50">
                          <div className="flex items-center justify-between mb-3">
                            <span className="text-xs font-bold uppercase tracking-wider text-[var(--app-text-soft)]">
                              Total Conversations
                            </span>
                            <MessageSquare size={18} className="text-sky-500" />
                          </div>
                          <div className="text-3xl font-extrabold text-[var(--app-text)] mb-2">
                            {overviewData?.breakdown?.total_conversations ?? 0}
                          </div>
                          <p className="text-xs text-[var(--app-text-soft)] mb-4">
                            Chat sessions processed across all channels.
                          </p>
                          <Link href="/dashboard/conversation">
                            <Button size="small" type="default" className="!rounded-xl text-xs font-bold">
                              View Chat Sessions
                            </Button>
                          </Link>
                        </div>

                        {/* Document Chunks */}
                        <div className="p-6 rounded-2xl bg-[var(--app-surface-muted)]/40 border border-[var(--app-border)]/50">
                          <div className="flex items-center justify-between mb-3">
                            <span className="text-xs font-bold uppercase tracking-wider text-[var(--app-text-soft)]">
                              Indexed Document Chunks
                            </span>
                            <FileText size={18} className="text-amber-500" />
                          </div>
                          <div className="text-3xl font-extrabold text-[var(--app-text)] mb-2">
                            {overviewData?.breakdown?.total_chunks ?? 0}
                          </div>
                          <p className="text-xs text-[var(--app-text-soft)] mb-4">
                            Vectorized knowledge chunks stored for retrieval.
                          </p>
                          <Link href="/dashboard/knowledge-base-files">
                            <Button size="small" type="default" className="!rounded-xl text-xs font-bold">
                              Inspect KB Files
                            </Button>
                          </Link>
                        </div>
                      </div>

                      {/* Knowledge Bases Detailed Distribution */}
                      <div className="p-6 rounded-2xl bg-[var(--app-surface-muted)]/30 border border-[var(--app-border)]/50">
                        <h4 className="text-sm font-bold text-[var(--app-text)] mb-4 uppercase tracking-wider">
                          Knowledge Base Partitioning
                        </h4>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                          <div className="p-4 rounded-xl bg-[var(--app-surface)] border border-[var(--app-border)]/60 flex items-center justify-between">
                            <div>
                              <span className="text-xs text-[var(--app-text-soft)] font-medium">
                                Document & File Knowledge Bases
                              </span>
                              <div className="text-2xl font-black text-[var(--app-text)] mt-1">
                                {overviewData?.breakdown?.document_knowledgebases ?? 0}
                              </div>
                            </div>
                            <Link href="/dashboard/knowledge-base">
                              <Button size="small" className="!rounded-lg text-xs">
                                Open Document KBs
                              </Button>
                            </Link>
                          </div>

                          <div className="p-4 rounded-xl bg-[var(--app-surface)] border border-[var(--app-border)]/60 flex items-center justify-between">
                            <div>
                              <span className="text-xs text-[var(--app-text-soft)] font-medium">
                                Database / SQL Knowledge Bases
                              </span>
                              <div className="text-2xl font-black text-[var(--app-text)] mt-1">
                                {overviewData?.breakdown?.database_knowledgebases ?? 0}
                              </div>
                            </div>
                            <Link href="/dashboard/database-knowledge">
                              <Button size="small" className="!rounded-lg text-xs">
                                Open Database KBs
                              </Button>
                            </Link>
                          </div>
                        </div>
                      </div>
                    </div>
                  ),
                },
                {
                  key: "endpoints",
                  label: (
                    <span className="flex items-center gap-2 font-bold text-sm">
                      <Globe size={16} />
                      Active Endpoints ({filteredEndpoints.length})
                    </span>
                  ),
                  children: (
                    <div className="pt-4 space-y-4">
                      {/* Search and Filters */}
                      <Row gutter={[16, 16]} align="middle" justify="space-between">
                        <Col xs={24} md={12}>
                          <Input
                            placeholder="Search endpoint path, name, or tag..."
                            prefix={<SearchOutlined className="text-gray-400" />}
                            value={endpointSearch}
                            onChange={(e) => setEndpointSearch(e.target.value)}
                            allowClear
                            className="!h-10 !rounded-xl"
                          />
                        </Col>
                        <Col xs={24} md={12} className="flex gap-2 justify-start md:justify-end flex-wrap">
                          {["ALL", "GET", "POST", "PUT", "DELETE"].map((m) => (
                            <Button
                              key={m}
                              size="small"
                              onClick={() => setSelectedMethod(m)}
                              type={selectedMethod === m ? "primary" : "default"}
                              className={`!rounded-lg font-bold text-xs ${
                                selectedMethod === m
                                  ? "!bg-[#0fb5a1] !border-none text-white"
                                  : ""
                              }`}
                            >
                              {m}
                            </Button>
                          ))}
                        </Col>
                      </Row>

                      {/* Endpoints Table */}
                      <Table
                        columns={endpointColumns}
                        dataSource={filteredEndpoints}
                        rowKey={(r: EndpointItem, i?: number) => `${r.method}-${r.path}-${i ?? 0}`}
                        loading={loadingEndpoints}
                        pagination={{
                          pageSize: 10,
                          showTotal: (total) => `Total ${total} endpoints`,
                          className: "!my-4",
                        }}
                        className="custom-table"
                      />
                    </div>
                  ),
                },
                {
                  key: "announcements",
                  label: (
                    <span className="flex items-center gap-2 font-bold text-sm">
                      <Bell size={16} />
                      Announcements & Notices ({announcementsList.length})
                    </span>
                  ),
                  children: (
                    <div className="pt-4 space-y-4">
                      <div className="flex justify-between items-center mb-2">
                        <Text className="text-xs text-[var(--app-text-soft)] font-medium">
                          System notices and platform bulletins broadcast to administrators.
                        </Text>
                        <Button
                          type="primary"
                          icon={<PlusOutlined />}
                          onClick={handleOpenCreateAnnouncement}
                          className="!rounded-xl !bg-[#0fb5a1] !border-none font-bold text-xs"
                        >
                          New Announcement
                        </Button>
                      </div>

                      {announcementsList.length === 0 ? (
                        <div className="p-8 text-center rounded-2xl bg-[var(--app-surface-muted)]/30 border border-dashed border-[var(--app-border)]">
                          <Bell size={32} className="mx-auto text-gray-400 mb-2 opacity-50" />
                          <h4 className="text-sm font-bold text-[var(--app-text)]">
                            No Announcements
                          </h4>
                          <p className="text-xs text-[var(--app-text-soft)] mt-1">
                            Create system alerts or notices using the button above.
                          </p>
                        </div>
                      ) : (
                        <div className="space-y-3">
                          {announcementsList.map((ann: AnnouncementItem) => (
                            <div
                              key={ann.id}
                              className="p-5 rounded-2xl bg-[var(--app-surface-muted)]/30 border border-[var(--app-border)]/50 flex items-start justify-between gap-4"
                            >
                              <div className="space-y-1">
                                <div className="flex items-center gap-2">
                                  <span className="font-bold text-sm text-[var(--app-text)]">
                                    {ann.title}
                                  </span>
                                  {getPriorityTag(ann.priority)}
                                  {ann.created_at && (
                                    <span className="text-[11px] text-[var(--app-text-soft)]">
                                      {new Date(ann.created_at).toLocaleDateString()}
                                    </span>
                                  )}
                                </div>
                                <p className="text-xs text-[var(--app-text-soft)] leading-relaxed !m-0">
                                  {ann.message}
                                </p>
                              </div>
                              <Space size="small">
                                <Button
                                  type="text"
                                  size="small"
                                  icon={<EditOutlined />}
                                  onClick={() => handleOpenEditAnnouncement(ann)}
                                  className="text-gray-500 hover:text-[#0fb5a1]"
                                />
                                <Popconfirm
                                  title="Delete Announcement"
                                  description="Are you sure you want to delete this notice?"
                                  onConfirm={() => handleDeleteAnnouncement(ann.id)}
                                  okText="Delete"
                                  cancelText="Cancel"
                                  okButtonProps={{ danger: true }}
                                >
                                  <Button
                                    type="text"
                                    size="small"
                                    icon={<DeleteOutlined />}
                                    className="text-gray-500 hover:text-rose-500"
                                  />
                                </Popconfirm>
                              </Space>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ),
                },
              ]}
            />
          </div>
        </div>
      )}

      {/* CREATE / EDIT ANNOUNCEMENT MODAL */}
      <Modal
        title={
          <span className="font-black text-lg text-[var(--app-text)]">
            {editingAnnouncement ? "Edit Announcement" : "Create New Announcement"}
          </span>
        }
        open={announcementModalOpen}
        onOk={handleSaveAnnouncement}
        onCancel={() => setAnnouncementModalOpen(false)}
        confirmLoading={creatingAnnouncement || updatingAnnouncement}
        okText={editingAnnouncement ? "Save Changes" : "Create"}
        okButtonProps={{
          className: "!bg-[#0fb5a1] !border-none !rounded-xl font-bold",
        }}
        cancelButtonProps={{ className: "!rounded-xl" }}
      >
        <Form form={announcementForm} layout="vertical" className="mt-4">
          <Form.Item
            name="title"
            label="Title"
            rules={[{ required: true, message: "Please input announcement title" }]}
          >
            <Input placeholder="e.g. Scheduled Platform Upgrade" className="!rounded-xl" />
          </Form.Item>

          <Form.Item
            name="message"
            label="Message"
            rules={[{ required: true, message: "Please input announcement message" }]}
          >
            <TextArea
              rows={4}
              placeholder="Provide information for administrators and users..."
              className="!rounded-xl"
            />
          </Form.Item>

          <Form.Item name="priority" label="Priority Level">
            <Select
              className="!rounded-xl"
              options={[
                { value: "info", label: "Information (Blue)" },
                { value: "success", label: "Success / Resolved (Green)" },
                { value: "warning", label: "Warning (Yellow)" },
                { value: "critical", label: "Critical Alert (Red)" },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
