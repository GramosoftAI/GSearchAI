"use client";

import {
  Flex, Typography, Button, Badge, Space, Card, Row, Col,
  Tooltip, Modal, Form, Input, Select, Popconfirm,
} from "antd";
import {
  PlusOutlined, RobotOutlined, MessageOutlined, ThunderboltOutlined,
  EditOutlined, DeleteOutlined, SettingOutlined, CalendarOutlined,
  CheckCircleOutlined, ClockCircleOutlined, InfoCircleOutlined, SearchOutlined
} from "@ant-design/icons";
import { useEffect, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import useAxios from "../../hooks/useAxios";
import { useAgents } from "../../hooks/useAgents";
import { useStore } from "../../hooks/useStore";
import type { Agent } from "../../components/ui/type";
import { getCookie } from "../../config/cookies";
import { toast } from "react-hot-toast";
import { SYSTEM_PROMPT } from "./text";

const { Title, Text } = Typography;
const { TextArea } = Input;
const { Option } = Select;

// ─── Agent Card Component ─────────────────────────────────────────────────────
type AgentListResponse = {
  data?: {
    agents?: Agent[];
  };
};

function AgentCard({ agent, onManage, onSettings, onClick }: {
  agent: any;
  onManage: (agent: any) => void;
  onSettings: (agent: any) => void;
  onClick?: () => void;
}) {
  return (
    <Card
      hoverable
      onClick={onClick}
      className="group relative overflow-hidden bg-[var(--app-surface)] border border-[var(--app-border)] rounded-[32px] transition-all duration-500 hover:shadow-[0_20px_50px_rgba(40,93,145,0.08)] hover:-translate-y-1 cursor-pointer"
      styles={{ body: { padding: 32 } }}
    >
      {/* Visual Accent */}
      <div className="absolute top-0 right-0 w-32 h-32 bg-[#285d91]/5 rounded-bl-[100px] -mr-10 -mt-10 transition-all duration-500 group-hover:scale-150 group-hover:bg-[#285d91]/10" />

      <Flex vertical gap={24}>
        <Row justify="space-between" align="middle">
          <div className="w-16 h-16 rounded-2xl bg-[#285d91]/5 text-[#285d91] flex items-center justify-center text-3xl shadow-inner group-hover:bg-[#285d91] group-hover:text-white transition-all duration-500">
            <RobotOutlined />
          </div>
          <Space>
            <Badge status="processing" color="#10b981" />
            <Text className="text-[10px] font-black uppercase tracking-[0.2em] text-[#10b981]">Active</Text>
            <Tooltip title="View Intelligence Details">
              <Button
                type="text"
                shape="circle"
                icon={<InfoCircleOutlined className="text-xl text-[var(--app-text-soft)]" />}
                onClick={(e) => { e.stopPropagation(); onSettings(agent); }}
              />
            </Tooltip>
          </Space>
        </Row>

        <div>
          <Title level={3} className="!m-0 !text-[var(--app-text)] !font-black !text-2xl tracking-tighter">
            {agent.name}
          </Title>
          <Text className="text-[var(--app-text-muted)] font-bold text-sm mt-2 block leading-relaxed line-clamp-2">
            {agent.description || "Empower your workflows with this specialized intelligent agent designed for high-performance automation."}
          </Text>
          <div className="mt-3 flex items-center gap-2">
            <Badge color="#285d91" text={<Text className="text-[10px] font-black uppercase tracking-widest opacity-50">{agent.personality || "Professional"}</Text>} />
          </div>
        </div>

        <Row justify="space-between" align="middle" className="pt-6 border-t border-[var(--app-border)]">
          <Space size={16}>
            <Tooltip title="Total Conversations">
              <Space className="text-[var(--app-text-soft)] font-bold text-xs">
                <MessageOutlined /> {agent.total_conversations || 0}
              </Space>
            </Tooltip>
            <Tooltip title="Confidence Level">
              <Space className="text-[var(--app-text-soft)] font-bold text-xs">
                <ThunderboltOutlined /> {Math.round((agent.avg_confidence || 0) * 100)}%
              </Space>
            </Tooltip>
          </Space>
          <Button
            type="link"
            onClick={(e) => { e.stopPropagation(); onManage(agent); }}
            className="!text-[#285d91] !font-black !text-xs !uppercase !tracking-widest hover:!scale-105 transition-transform"
          >
            Manage +
          </Button>
        </Row>
      </Flex>
    </Card>
  );
}

// ─── Empty State Component ────────────────────────────────────────────────────
function EmptyState({ onDeploy }: { onDeploy: () => void }) {
  return (
    <Flex vertical align="center" justify="center" className="min-h-[60vh] py-20 animate-in fade-in duration-1000">
      <div className="relative mb-12">
        <div className="absolute inset-0 bg-[#285d91] rounded-full blur-[80px] opacity-10 animate-pulse" />
        <div className="w-32 h-32 rounded-[40px] bg-[var(--app-surface)] shadow-2xl flex items-center justify-center relative z-10 border border-[var(--app-border)]">
          <RobotOutlined className="text-6xl text-[#285d91]" />
        </div>
        {/* <div className="absolute -bottom-2 -right-2 w-10 h-10 bg-emerald-500 rounded-2xl flex items-center justify-center text-white shadow-lg border-4 border-[var(--app-surface)] animate-bounce">
          <PlusOutlined />
        </div> */}
      </div>

      <div className="text-center max-w-md px-6">
        <Title level={1} className="!m-0 !text-[var(--app-text)] !font-black !text-4xl md:!text-5xl tracking-tighter">
          Your AI Squad
        </Title>
        <Text className="text-[var(--app-text-muted)] font-semibold text-lg mt-4 block leading-relaxed">
          Architect, deploy, and scale your specialized AI agents with a single click.
        </Text>
      </div>

      <Button
        type="primary"
        size="large"
        icon={<PlusOutlined />}
        onClick={onDeploy}
        className="mt-12 !h-16 !px-10 !rounded-2xl !bg-[#285d91] !border-none !font-black !text-lg !uppercase !tracking-widest !shadow-2xl !shadow-blue-900/30 hover:!scale-[1.02] transition-all"
      >
        Deploy New Bot
      </Button>
    </Flex>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────
export default function BotsPage() {
  const router = useRouter();
  const { agents, fetchAgents, isLoading: loading } = useAgents();
  const [getAgents] = useAxios<AgentListResponse>({ endpoint: "GETAGENTLIST", hideErrorMsg: true });
  const [createAgent, getcreateAgent, creating] = useAxios({ endpoint: "CREATEAGENT", showSuccessMsg: true });
  const [updateAgent, , updating] = useAxios({ endpoint: "UPDATEAGENT", showSuccessMsg: true });
  const [deleteAgent, deleteRes, deleting] = useAxios({ endpoint: "DELETEAGENT", showSuccessMsg: true });

  const setAgentList = useStore((state) => state.setAgentList);
  const setBotsCache = useStore((state) => state.setBotsCache);

  const [userName] = useState<string>(() => {
    if (typeof window !== "undefined") {
      const storedName = localStorage.getItem("userName");
      return storedName ? storedName.split(' ')[0] : "";
    }
    return "";
  });

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isManageModalOpen, setIsManageModalOpen] = useState(false);
  const [isDetailsModalOpen, setIsDetailsModalOpen] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<any>(null);
  const [agentresp, setAgentresponse] = useState<any>(null)
  const [form] = Form.useForm();
  const [manageForm] = Form.useForm();

  // NEW: State for handling agent search
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [checkingKb, setCheckingKb] = useState(false);
  const [noKbModalOpen, setNoKbModalOpen] = useState(false);

  const handleAgentClick = async (agent: any) => {
    setCheckingKb(true);
    try {
      const token = getCookie("AUTH_TOKEN");
      const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;
      const res = await fetch(`${API_BASE_URL}/knowledge-bases/agents/${agent.id}?limit=50&offset=0`, {
        headers: {
          Authorization: `Bearer ${token}`
        }
      });
      if (res.ok) {
        const payload = await res.json();
        const sources = payload?.data?.sources ?? payload?.data?.kbs ?? payload?.sources ?? payload?.kbs ?? payload ?? [];
        if (Array.isArray(sources) && sources.length > 0) {
          router.push(`/dashboard/conversation?agentId=${agent.id}`);
        } else {
          setNoKbModalOpen(true);
        }
      } else {
        router.push(`/dashboard/conversation?agentId=${agent.id}`);
      }
    } catch (err) {
      console.error("Knowledge base validation failed:", err);
      router.push(`/dashboard/conversation?agentId=${agent.id}`);
    } finally {
      setCheckingKb(false);
    }
  };

  function mapAgentsToList(agents: Agent[]) {
    return agents.map((agent) => ({
      id: agent.id,
      name: agent.name,
      status: agent.is_active ? "active" : "draft",
    }));
  }

  const refreshAgents = () => {
    fetchAgents();
  };

  useEffect(() => {
    refreshAgents();
    getAgents(undefined, (payload) => {
      const agentsList = payload?.data?.agents ?? [];
      setAgentresponse(agentsList)
      setBotsCache(agentsList);
      setAgentList(mapAgentsToList(agentsList));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [getcreateAgent, deleteRes]);

  // NEW: Filter agents dynamically based on search query
  const filteredAgents = useMemo(() => {
    if (!agents) return [];
    return agents.filter((agent: any) =>
      agent.name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      agent.description?.toLowerCase().includes(searchQuery.toLowerCase())
    );
  }, [agents, searchQuery]);

  const handleCreate = async (values: any) => {
    await createAgent({ data: values });
    await getAgents(undefined, (payload) => {
      const agentsList = payload?.data?.agents ?? [];
      setAgentresponse(agentsList)
      setBotsCache(agentsList);
      setAgentList(mapAgentsToList(agentsList));
    });
    setIsModalOpen(false);
    form.resetFields();
    refreshAgents();
  };

  const handleUpdate = async (values: any) => {
    if (!selectedAgent?.id) return;
    await updateAgent({
      path: `/${selectedAgent.id}`,
      data: values
    });
    await getAgents(undefined, (payload) => {
      const agentsList = payload?.data?.agents ?? [];
      setAgentresponse(agentsList)
      setBotsCache(agentsList);
      setAgentList(mapAgentsToList(agentsList));
    });
    setIsManageModalOpen(false);
    refreshAgents();
  };

  const handleDelete = async () => {
    if (!selectedAgent?.id) return;
    await deleteAgent({
      path: `/${selectedAgent.id}`
    });
    await getAgents(undefined, (payload) => {
      const agentsList = payload?.data?.agents ?? [];
      setAgentresponse(agentsList)
      setBotsCache(agentsList);
      setAgentList(mapAgentsToList(agentsList));
    });
    setIsManageModalOpen(false);
    refreshAgents();
  };

  const openManageModal = (agent: any) => {
    const fullAgent = agentresp?.find(
      (x: any) => x.id === agent.id
    ) || agent;
    setSelectedAgent(fullAgent);
    manageForm.setFieldsValue({
      name: fullAgent.name || "",
      personality: fullAgent.personality || "Concise",
      system_prompt: fullAgent.system_prompt || ""
    });
    setIsManageModalOpen(true);
  };

  const openDetailsModal = (agent: any) => {
    console.log("Selected Agent:", agent.id);
    const fullAgent = agentresp.find(
      (x: any) => x.id === agent.id
    );

    console.log(fullAgent);
    setSelectedAgent(fullAgent);
    setIsDetailsModalOpen(true);
  };

  const formatDate = (dateStr: string) => {
    if (!dateStr) return "N/A";
    return new Date(dateStr).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  return (
    <div className="w-full p-4 md:p-10 relative">
      {/* Creation Modal */}
      <Modal
        title={
          <Title level={4} className="!m-0 !text-[var(--app-text)] !font-black tracking-tight">
            Deploy New Intelligence
          </Title>
        }
        open={isModalOpen}
        onCancel={() => setIsModalOpen(false)}
        footer={null}
        centered
        styles={{ body: { borderRadius: 32, padding: 32, background: 'var(--app-surface)' } }}
      >
        <Form form={form} layout="vertical" onFinish={handleCreate} className="mt-6" initialValues={{ personality: "Concise", system_prompt: SYSTEM_PROMPT }}>
          <Form.Item
            name="name"
            label={<Text className="font-black text-[10px] uppercase tracking-widest text-[var(--app-text-soft)]">Agent Name</Text>}
            rules={[
              { required: true, message: 'Please enter agent name' },
              { max: 50, message: 'Agent name must be 50 characters or less' }
            ]}
          >
            <Input
              placeholder="e.g. Resume Analyzer"
              maxLength={50}
              showCount
              className="h-14 !rounded-2xl !bg-[var(--app-surface-muted)] !border-none font-bold text-[var(--app-text)]"
            />
          </Form.Item>

          <Form.Item
            name="personality"
            label={<Text className="font-black text-[10px] uppercase tracking-widest text-[var(--app-text-soft)]">Personality Type</Text>}
          >
            <Select className="h-14 custom-select" placeholder="Select personality">
              <Option value="Concise">Concise & Professional</Option>
              <Option value="Creative">Creative & Explanatory</Option>
              <Option value="Friendly">Friendly & Approachable</Option>
              <Option value="Strict">Strict & Deterministic</Option>
            </Select>
          </Form.Item>

          <Form.Item
            name="system_prompt"
            label={<Text className="font-black text-[10px] uppercase tracking-widest text-[var(--app-text-soft)]">System Instruction Prompt</Text>}
            rules={[
              { max: 6000, message: 'System Instruction Prompt must be 1000 characters or less' }
            ]}
          >
            <TextArea
              rows={4}
              placeholder="Describe the specialized tasks and knowledge areas for this agent..."
              defaultValue=""
              maxLength={6000}
              showCount
              className="!rounded-2xl !bg-[var(--app-surface-muted)] !border-none font-bold text-[var(--app-text)]"
            />
          </Form.Item>

          <Button
            type="primary"
            htmlType="submit"
            loading={creating}
            className="w-full h-16 !rounded-2xl !bg-[#285d91] !border-none !font-black !text-lg !uppercase !tracking-widest !shadow-xl !shadow-blue-900/20 mt-4 hover:!scale-[1.02] transition-all"
          >
            Initiate Deployment
          </Button>
        </Form>
      </Modal>

      {/* Details Modal */}
      <Modal
        title={
          <Flex align="center" gap={12}>
            <div className="w-10 h-10 rounded-xl bg-[#285d91]/10 text-[#285d91] flex items-center justify-center text-xl">
              <RobotOutlined />
            </div>
            <Title level={4} className="!m-0 !text-[var(--app-text)] !font-black tracking-tight">
              {selectedAgent?.name} Details
            </Title>
          </Flex>
        }
        open={isDetailsModalOpen}
        onCancel={() => setIsDetailsModalOpen(false)}
        footer={null}
        centered
        styles={{ body: { borderRadius: 32, padding: 32, background: 'var(--app-surface)' } }}
      >
        <div className="mt-6 space-y-8">
          <div className="flex items-center justify-between p-6 bg-[var(--app-surface-muted)] rounded-2xl border border-[var(--app-border)]">
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 rounded-full bg-emerald-500/10 text-emerald-500 flex items-center justify-center">
                <CheckCircleOutlined />
              </div>
              <Text className="font-black uppercase tracking-widest text-[10px] text-[var(--app-text-soft)]">Deployment Status</Text>
            </div>
            <Badge status="processing" color="#10b981" text={<Text className="font-black text-[#10b981] uppercase tracking-widest text-[10px] ml-2">Active & Ready</Text>} />
          </div>

          <div className="grid grid-cols-2 gap-6">
            <div className="p-6 bg-[var(--app-surface-muted)] rounded-2xl border border-[var(--app-border)]">
              <Flex vertical gap={8}>
                <Flex align="center" gap={8} className="text-[#285d91]">
                  <CalendarOutlined />
                  <Text className="font-black uppercase tracking-widest text-[10px] text-[var(--app-text-soft)]">Genesis Date</Text>
                </Flex>
                <Text className="font-bold text-sm text-[var(--app-text)]">{formatDate(selectedAgent?.created_at)}</Text>
              </Flex>
            </div>
            <div className="p-6 bg-[var(--app-surface-muted)] rounded-2xl border border-[var(--app-border)]">
              <Flex vertical gap={8}>
                <Flex align="center" gap={8} className="text-[#285d91]">
                  <ClockCircleOutlined />
                  <Text className="font-black uppercase tracking-widest text-[10px] text-[var(--app-text-soft)]">Last Synced</Text>
                </Flex>
                <Text className="font-bold text-sm text-[var(--app-text)]">{formatDate(selectedAgent?.updated_at)}</Text>
              </Flex>
            </div>
          </div>

          <div className="p-6 bg-[var(--app-surface-muted)] rounded-2xl border border-[var(--app-border)]">
            <Flex vertical gap={12}>
              <Text className="font-black uppercase tracking-widest text-[10px] text-[var(--app-text-soft)]">Internal Identifiers</Text>
              <div className="flex items-center justify-between">
                <Text className="text-[10px] font-bold text-[var(--app-text-soft)] uppercase tracking-widest">ID</Text>
                <Text className="text-[10px] font-bold text-[var(--app-text)] font-mono">{selectedAgent?.id}</Text>
              </div>
              <div className="flex items-center justify-between">
                <Text className="text-[10px] font-bold text-[var(--app-text-soft)] uppercase tracking-widest">Tenant ID</Text>
                <Text className="text-[10px] font-bold text-[var(--app-text)] font-mono">{selectedAgent?.tenant_id ?? 0}</Text>
              </div>
            </Flex>
          </div>

          <Button
            type="primary"
            block
            onClick={() => setIsDetailsModalOpen(false)}
            className="h-14 !rounded-2xl !bg-[#285d91] !border-none !font-black !uppercase !tracking-widest"
          >
            Acknowledged
          </Button>
        </div>
      </Modal>

      {/* No Knowledge Base Modal */}
      <Modal
        title={
          <Flex align="center" gap={12}>
            <div className="w-10 h-10 rounded-xl bg-amber-500/10 text-amber-500 flex items-center justify-center text-xl">
              <InfoCircleOutlined />
            </div>
            <Title level={4} className="!m-0 !text-[var(--app-text)] !font-black tracking-tight">
              Knowledge Base Required
            </Title>
          </Flex>
        }
        open={noKbModalOpen}
        onCancel={() => setNoKbModalOpen(false)}
        footer={null}
        centered
        styles={{ body: { borderRadius: 32, padding: 32, background: 'var(--app-surface)' } }}
      >
        <div className="mt-6 space-y-6">
          <Text className="text-[var(--app-text-soft)] font-bold text-sm block leading-relaxed">
            This agent does not have any sources in the knowledge base. Please add a source first to enable conversations.
          </Text>

          <Button
            type="primary"
            block
            onClick={() => {
              setNoKbModalOpen(false);
              router.push("/dashboard/knowledge-base");
            }}
            className="h-14 !rounded-2xl !bg-[#285d91] !border-none !font-black !uppercase !tracking-widest"
          >
            OK
          </Button>
        </div>
      </Modal>

      {/* Manage/Edit Modal */}
      <Modal
        title={
          <Flex align="center" gap={12}>
            <div className="w-10 h-10 rounded-xl bg-[#285d91]/10 text-[#285d91] flex items-center justify-center">
              <SettingOutlined />
            </div>
            <Title level={4} className="!m-0 !text-[var(--app-text)] !font-black tracking-tight">
              Manage {selectedAgent?.name}
            </Title>
          </Flex>
        }
        open={isManageModalOpen}
        onCancel={() => setIsManageModalOpen(false)}
        footer={null}
        centered
        width={600}
        styles={{ body: { borderRadius: 32, padding: 32, background: 'var(--app-surface)' } }}
      >
        <Form form={manageForm} layout="vertical" onFinish={handleUpdate} className="mt-6">
          <Form.Item
            name="name"
            label={<Text className="font-black text-[10px] uppercase tracking-widest text-[var(--app-text-soft)]">Agent Name</Text>}
            rules={[
              { required: true, message: 'Please enter agent name' },
              { max: 50, message: 'Agent name must be 50 characters or less' }
            ]}
          >
            <Input
              placeholder="e.g. Resume Analyzer"
              maxLength={50}
              showCount
              className="h-14 !rounded-2xl !bg-[var(--app-surface-muted)] !border-none font-bold text-[var(--app-text)]"
            />
          </Form.Item>

          <Form.Item
            name="personality"
            label={<Text className="font-black text-[10px] uppercase tracking-widest text-[var(--app-text-soft)]">Agent Personality</Text>}
          >
            <Select className="h-14 custom-select">
             <Option value="Concise">Concise & Professional</Option>
              <Option value="Creative">Creative & Explanatory</Option>
              <Option value="Friendly">Friendly & Approachable</Option>
              <Option value="Strict">Strict & Deterministic</Option>
            </Select>
          </Form.Item>

          <Form.Item
            name="system_prompt"
            label={<Text className="font-black text-[10px] uppercase tracking-widest text-[var(--app-text-soft)]">System Instruction Prompt</Text>}
            rules={[
              { max: 6000, message: 'System Instruction Prompt must be 1000 characters or less' }
            ]}
          >
            <TextArea
              rows={6}
              placeholder="Always be very brief..."
              maxLength={6000}
              showCount
              className="!rounded-2xl !bg-[var(--app-surface-muted)] !border-none font-bold text-[var(--app-text)]"
            />
          </Form.Item>

          <Flex gap={16} className="mt-8">
            <Popconfirm
              title="Delete AI Agent?"
              description="This will permanently delete the agent and all associated knowledge base data. This action cannot be undone."
              onConfirm={handleDelete}
              okText="Yes, Delete"
              cancelText="No"
              okButtonProps={{ danger: true, className: "!rounded-xl !font-bold" }}
              cancelButtonProps={{ className: "!rounded-xl !font-bold" }}
            >
              <Button
                danger
                icon={<DeleteOutlined />}
                loading={deleting}
                className="h-16 flex-1 !rounded-2xl !font-black !text-sm !uppercase !tracking-widest transition-all"
              >
                Delete Agent
              </Button>
            </Popconfirm>

            <Button
              type="primary"
              htmlType="submit"
              loading={updating}
              icon={<EditOutlined />}
              className="h-16 flex-[2] !rounded-2xl !bg-[#285d91] !border-none !font-black !text-sm !uppercase !tracking-widest !shadow-xl !shadow-blue-900/20 hover:!scale-[1.02] transition-all"
            >
              Update Intelligence
            </Button>
          </Flex>
        </Form>
      </Modal>

      {/* Main Content Area */}
      {agents.length > 0 ? (
        <Flex vertical gap={48}>
          {/* Main Top Header Bar */}
          <Row justify="space-between" align="bottom" gutter={[16, 24]}>
            {/* Header Content */}
            <Col xs={24} lg={10} xl={12}>
              <Title level={1} className="!m-0 !text-[var(--app-text)] !font-black !text-4xl md:!text-5xl tracking-tighter">
                {userName ? `${userName}'s` : "Your"} AI Squad
              </Title>
              <Text className="text-[var(--app-text-muted)] font-semibold text-lg mt-2 block">
                Architect, deploy, and scale your specialized AI agents.
              </Text>
            </Col>

            {/* Action Bar Corner (Search + Deploy) */}
            <Col xs={24} lg={14} xl={12}>
              <div className="flex flex-col sm:flex-row items-center gap-3 justify-end w-full">
                {/* Search Input Bar Column */}
                <div className="w-full sm:flex-1 min-w-[200px]">
                  <Input
                    placeholder="Search agents by name..."
                    prefix={<SearchOutlined className="text-[var(--app-text-soft)] mr-2 text-base" />}
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    allowClear
                    className="h-14 w-full !rounded-2xl !bg-[var(--app-surface)] !border-[var(--app-border)] font-bold text-[var(--app-text)] shadow-sm hover:!border-[#285d91]/50 focus:!border-[#285d91]"
                  />
                </div>
                {/* Deploy Button Column */}
                <div className="w-full sm:w-auto sm:shrink-0 min-w-[140px]">
                  <Button 
                    type="primary" 
                    size="large" 
                    icon={<PlusOutlined />}
                    onClick={() => setIsModalOpen(true)}
                    className="!h-14 w-full !px-5 !rounded-2xl !bg-[#285d91] !border-none !font-black !uppercase !tracking-widest shadow-xl shadow-blue-900/10 hover:!scale-105 transition-all flex items-center justify-center gap-1.5"
                  >
                    Deploy
                  </Button>
                </div>
              </div>
            </Col>
          </Row>

          {/* Cards Grid Architecture */}
          <Row gutter={[32, 32]}>
            {/* MODIFIED: Renders dynamically filtered list instead of absolute base agents */}
            {filteredAgents.map((agent, i) => (
              <Col key={i} xs={24} sm={24} md={24} lg={12} xl={8}>
                <AgentCard
                  agent={agent}
                  onManage={openManageModal}
                  onSettings={openDetailsModal}
                  onClick={() => handleAgentClick(agent)}
                />
              </Col>
            ))}

            {/* New Agent Skeleton Card */}
            <Col xs={24} sm={24} md={24} lg={12} xl={8}>
              <div
                onClick={() => setIsModalOpen(true)}
                className="group h-full min-h-[300px] border-2 border-dashed border-[var(--app-border)] rounded-[32px] flex flex-col items-center justify-center gap-4 cursor-pointer hover:border-[#285d91]/30 hover:bg-[#285d91]/5 transition-all duration-500"
              >
                <div className="w-16 h-16 rounded-full bg-[var(--app-surface-muted)] flex items-center justify-center text-[var(--app-text-soft)] group-hover:bg-[var(--app-surface)] group-hover:text-[#285d91] group-hover:scale-110 shadow-sm transition-all">
                  <PlusOutlined className="text-2xl" />
                </div>
                <Text className="text-[var(--app-text-soft)] font-black uppercase tracking-[0.2em] group-hover:text-[#285d91]">New Agent</Text>
              </div>
            </Col>
          </Row>
        </Flex>
      ) : (
        <EmptyState onDeploy={() => setIsModalOpen(true)} />
      )}

      {/* Loading Overlay */}
      {(loading || deleting || updating || checkingKb) && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-transparent backdrop-blur-md transition-all duration-500">
          <div className="relative flex flex-col items-center gap-4 animate-in zoom-in-95 duration-500">
            <div className="relative">
              <div className="absolute inset-0 bg-[#285d91] rounded-full blur-[40px] opacity-20 animate-pulse" />
              <RobotOutlined className="text-5xl text-[#285d91] relative z-10 animate-bounce" />
            </div>
            <p className="text-[10px] font-black uppercase tracking-[0.3em] text-[#285d91] text-center opacity-80">
              {deleting ? "Purging Entity..." : updating ? "Upgrading Neural Link..." : checkingKb ? "Checking Knowledge Base..." : "Syncing Squad"}
            </p>
          </div>
        </div>
      )}

      <style jsx global>{`
        .custom-select .ant-select-selector {
          height: 56px !important;
          border-radius: 16px !important;
          background: var(--app-surface-muted) !important;
          border: none !important;
          padding: 0 20px !important;
          display: flex;
          align-items: center;
          font-weight: bold;
          color: var(--app-text) !important;
        }
        .ant-select-dropdown {
          background: var(--app-surface) !important;
          border-radius: 16px !important;
          padding: 8px !important;
          border: 1px solid var(--app-border) !important;
        }
        .ant-select-item-option-selected {
          background: #285d91 !important;
          color: white !important;
          border-radius: 10px !important;
        }
      `}</style>
    </div>
  );
}
