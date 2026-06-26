"use client";

import { Flex, Typography, Card, Button, Tooltip, App } from "antd";
import { CopyOutlined, CheckCircleOutlined } from "@ant-design/icons";
import { useState, useEffect } from "react";
import AgentList from "../../components/ui/AgentList";
import useAxios from "../../hooks/useAxios";
import { useStore } from "../../hooks/useStore";
import type { Agent } from "../../components/ui/type";

const { Title, Text } = Typography;

type Message = {
  role: "user" | "assistant";
  content: string;
  confidence?: number;
  nodes?: number;
  timestamp?: string;
  message_count?: number;
};

type AgentListResponse = {
  data?: {
    agents?: Agent[];
  };
};

type ChatSession = {
  id: string;
  agentId: string;
  agentName: string;
  messages: Message[];
  updatedAt: number;
  agent_id: string;
  title: string;
  message_count: number;
  is_active: boolean;
  last_message_at: string;
  created_at: string;
};

export default function EmbedScriptSection() {
  const { notification } = App.useApp();
  const [copied, setCopied] = useState(false);
  const setAgentList = useStore((state) => state.setAgentList);
  const setBotsCache = useStore((state) => state.setBotsCache);
  const [agentresp, setAgentresponse] = useState<any>(null);
  const [agent, setAgent] = useState<{ id: string; name: string } | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [getAgents] = useAxios<AgentListResponse>({ endpoint: "GETAGENTLIST", hideErrorMsg: true });

  function mapAgentsToList(agents: Agent[]) {
    return agents.map((agent) => ({
      id: agent.id,
      name: agent.name,
      status: agent.is_active ? "active" : "draft",
    }));
  }

  useEffect(() => {
    getAgents(undefined, (payload) => {
      const agents = payload?.data?.agents ?? [];
      setAgentresponse(agents);
      setBotsCache(agents);
      setAgentList(mapAgentsToList(agents));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const scriptCode = `<script src= '${process.env.NEXT_PUBLIC_API_BASES_URL}/chat.js'
                      data-agent-id=${agent?.id || "YOUR_AGENT_ID"}
                      data-tenant-id=${agentresp?.[0]?.tenant_id || "YOUR_TENANT_ID"}
                      >
                      </script>`;

  const handleCopy = () => {
    if (!agent?.id) {
      notification.warning({
        message: "Select an Agent",
        description: "Please select an agent before copying the script.",
        placement: "topRight",
      });
      return;
    }

    const textarea = document.createElement("textarea");
    textarea.value = scriptCode;
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    document.body.removeChild(textarea);

    setCopied(true);
    notification.success({
      message: "Copied to Clipboard",
      description: "The snippet is ready to be pasted into your web code base.",
      placement: "topRight",
    });

    setTimeout(() => setCopied(false), 2000);
  };

  const loadSession = (session: ChatSession) => {
    setAgent({
      id: session.agent_id || session.agentId,
      name: session.title || session.agentName,
    });
  };

  const startNewChat = (selectedAgent: { id: string; name: string }) => {
    const newSessionId = `session_${Date.now()}`;
    const newSession: any = {
      id: newSessionId,
      agentId: selectedAgent.id,
      agentName: selectedAgent.name,
      messages: [],
      updatedAt: Date.now(),
    };
    setSessions((prev) => [newSession, ...prev]);
    setAgent(selectedAgent);
  };

  return (
    <Flex vertical gap={40}>
      {/* Header Section */}
      <div className="space-y-3 max-w-3xl">
        <Title level={1} className="!m-0 !text-[var(--app-text)] !font-extrabold !text-3xl md:!text-5xl tracking-tight">
          Omnichannel Integrations
        </Title>
        <Text className="text-[var(--app-text-muted)] text-base md:text-lg block leading-relaxed">
          Deploy your cognitive AI agents across every customer touchpoint with seamless integration hooks.
        </Text>
      </div>

      {/* Embed Script Section */}
      <Card
        className="bg-[var(--app-surface)] border border-[var(--app-border)] rounded-3xl shadow-md overflow-hidden"
        styles={{ body: { padding: "24px md:40px" } }}
      >
        <Flex vertical gap={24}>
          <Flex justify="space-between" align="start" wrap="wrap" gap={16}>
            <div className="space-y-1">
              <Title level={3} className="!m-0 !text-[var(--app-text)] !font-bold !text-xl tracking-tight">
                Embed Script
              </Title>
              <Text className="text-[var(--app-text-soft)] text-xs font-medium uppercase tracking-wider block">
                Add this snippet to your website <code className="bg-[var(--app-surface-muted)] px-1 py-0.5 rounded text-xs">&lt;body&gt;</code> element to initialize the chat instance.
              </Text>
            </div>
            <div className="w-full sm:w-auto flex items-center">
              <AgentList
                selectedId={agent?.id}
                size="large"
                style={{ width: 220, height: 48 }}
                onChange={(id: string, name: string) => {
                  const existing = sessions.find((s) => s.agentId === id);
                  if (existing) loadSession(existing);
                  else startNewChat({ id, name });
                }}
              />
            </div>
            <Tooltip title={copied ? "Copied!" : "Copy Script"}>
              <Button
                type="primary"
                size="large"
                icon={copied ? <CheckCircleOutlined /> : <CopyOutlined />}
                onClick={handleCopy}
                className="w-full sm:w-auto !h-12 !px-6 !rounded-xl !bg-[#285d91] !border-none !font-semibold transition-transform active:scale-95 flex items-center justify-center gap-2"
              >
                {copied ? "Copied" : "Copy Code"}
              </Button>
            </Tooltip>
          </Flex>

          {/* Code Block Window */}
          <div className="relative group rounded-2xl border border-[var(--app-border)] bg-[var(--app-surface-muted)] overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--app-border)] bg-[var(--app-surface)]/50">
              <div className="flex gap-1.5">
                <span className="w-3 h-3 rounded-full bg-red-400/70" />
                <span className="w-3 h-3 rounded-full bg-amber-400/70" />
                <span className="w-3 h-3 rounded-full bg-emerald-400/70" />
              </div>
              <Text className="text-[10px] font-bold uppercase tracking-widest text-slate-400">HTML</Text>
            </div>

            <pre className="p-5 md:p-6 overflow-x-auto custom-scrollbar m-0">
              <code className="text-[var(--app-text)] font-mono text-xs md:text-sm leading-relaxed block whitespace-pre">
                <span className="text-[#285d91] opacity-80">{"<script "}</span>
                <span className="text-[#3b82f6]">src =</span>
                <span className="text-emerald-500">{`'${process.env.NEXT_PUBLIC_API_BASES_URL}/chat.js'`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-agent-id =</span>
                <span className="text-emerald-500">{`${agent?.id || "YOUR_AGENT_ID"}`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-tenant-id =</span>
                <span className="text-emerald-500">{`${agentresp?.[0]?.tenant_id || "YOUR_TENANT_ID"}`}</span>
                <span className="text-[#285d91] opacity-80">{">"}</span>
                <span className="text-[#285d91] opacity-80">{"</script>"}</span>
              </code>
            </pre>
          </div>
        </Flex>
      </Card>
    </Flex>
  );
}
