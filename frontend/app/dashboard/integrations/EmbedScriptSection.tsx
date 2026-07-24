"use client";
import { Flex, Typography, Card, Button, Tooltip, App, Radio, Input, Modal } from "antd";
import { CopyOutlined, CheckCircleOutlined, SettingOutlined, EyeOutlined } from "@ant-design/icons";
import { useState, useEffect, useRef } from "react";
import AgentList from "../../components/ui/AgentList";
import useAxios from "../../hooks/useAxios";
import { useStore } from "../../hooks/useStore";
import type { Agent } from "../../components/ui/type";

const { Title, Text } = Typography;

type Message = {
  role: "user" | "assistant";
  content: string;
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

// Preset colors for brand theme picker
const COLOR_PRESETS = [
  { name: "Teal", hex: "#0fb5a1" },
  { name: "Blue", hex: "#0066cc" },
  { name: "Purple", hex: "#7f00ff" },
  { name: "Green", hex: "#22c55e" },
  { name: "Red", hex: "#ef4444" },
];


export default function EmbedScriptSection() {
  const { notification } = App.useApp();
  const [copied, setCopied] = useState(false);
  const setAgentList = useStore((state) => state.setAgentList);
  const setBotsCache = useStore((state) => state.setBotsCache);
  const [agentresp, setAgentresponse] = useState<any>(null);
  const [agent, setAgent] = useState<{ id: string; name: string } | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [getAgents] = useAxios<AgentListResponse>({ endpoint: "GETAGENTLIST", hideErrorMsg: true });
  

  // Customization States (Applied / Saved)
  const [chatType, setChatType] = useState<"icon" | "search">("icon");
  const [position, setPosition] = useState<"center" | "right">("center");
  const [placeholderText, setPlaceholderText] = useState("Ask about web scraping, Zyte API, anything data extraction...");
   const [themeColor, setThemeColor] = useState("#0fb5a1");
  // Modal Customizer Draft States
  const [isCustomizerOpen, setIsCustomizerOpen] = useState(false);
  const [draftChatType, setDraftChatType] = useState<"icon" | "search">("icon");
  const [draftPosition, setDraftPosition] = useState<"center" | "right">("center");
  const [draftPlaceholderText, setDraftPlaceholderText] = useState("Ask about web scraping, Zyte API, anything data extraction...");
  const [draftThemeColor, setDraftThemeColor] = useState("#0fb5a1");
  // Sandbox Live Preview States (Inside Modal)
  const [previewMessages, setPreviewMessages] = useState<any[]>([]);
  const [previewInput, setPreviewInput] = useState("");
  const [previewIsOpen, setPreviewIsOpen] = useState(false);
  const [previewIsTyping, setPreviewIsTyping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  
  const isWideLayout = draftChatType === "search" && draftPosition === "center";
  
  // Dynamic Theme state observer
  const [isDarkTheme, setIsDarkTheme] = useState(false);
  useEffect(() => {
    if (typeof window !== "undefined") {
      const checkDark = () => {
        return (
          document.documentElement.classList.contains("dark") ||
          document.documentElement.getAttribute("data-theme") === "dark"
        );
      };
      setIsDarkTheme(checkDark());
      const observer = new MutationObserver(() => {
        setIsDarkTheme(checkDark());
      });
      observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["class", "data-theme"],
      });
      return () => observer.disconnect();
    }
  }, []);

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

  // Reset sandbox chat state when switching draft modes in live preview
  useEffect(() => {
    setPreviewMessages([]);
    setPreviewIsOpen(false);
    setPreviewIsTyping(false);
    setPreviewInput("");
  }, [draftChatType, draftPosition]);
  useEffect(() => {
    if (previewIsOpen) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [previewMessages, previewIsTyping, previewIsOpen]);

  // Open customizer and copy values to drafts
  const openCustomizer = () => {
    setDraftChatType(chatType);
    setDraftPosition(position);
    setDraftPlaceholderText(placeholderText);
    setDraftThemeColor(themeColor);
    setIsCustomizerOpen(true);
  };
  // Apply customizations and update the code block
  const handleApply = () => {
    setChatType(draftChatType);
    setPosition(draftPosition);
    setPlaceholderText(draftPlaceholderText);
    setThemeColor(draftThemeColor);
    setIsCustomizerOpen(false);
    notification.success({
      message: "Style Applied Successfully",
      description: "The HTML script snippet has been updated with your new layout configurations.",
      placement: "topRight",
    });
  };
  // Revert draft changes and close
  const handleCancel = () => {
    setDraftChatType(chatType);
    setDraftPosition(position);
    setDraftPlaceholderText(placeholderText);
    setDraftThemeColor(themeColor);
    setIsCustomizerOpen(false);
  };
  // Generate dynamic embed script block based on APPLIED states

  const scriptCode = `<script src='${process.env.NEXT_PUBLIC_API_BASES_URL || "http://grag.gramopro.ai"}/chat.js'
  data-agent-id="${agent?.id || "YOUR_AGENT_ID"}"
  data-tenant-id="${agentresp?.[0]?.tenant_id || "YOUR_TENANT_ID"}"
  data-chat-type="${chatType}"${chatType === "search" ? `\n  data-position="${position}"\n  data-placeholder="${placeholderText}"` : ""}
  data-theme-color="${themeColor}"
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

  const handlePreviewSend = (text: string) => {
    const query = text.trim();
    if (!query) return;
   
    setPreviewIsOpen(true);
    setPreviewMessages((prev) => [...prev, { role: "user", content: query }]);
    setPreviewInput("");
    setPreviewIsTyping(true);
    setTimeout(() => {
      setPreviewIsTyping(false);
      setPreviewMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `This is a **live simulated response** using theme color (**${draftThemeColor}**)! \n\nOnce embedded, it streams real-time responses from AI Agent (**${
            agent?.name || "Gsearch AI"
          }**).`,
        },
      ]);
    }, 1200);
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

     {/* Embed Control card on page */}
      <Card
        className="bg-[var(--app-surface)] border border-[var(--app-border)] rounded-3xl shadow-md overflow-hidden"
        styles={{ body: { padding: "24px md:36px" } }}
      >
          <Flex vertical gap={24}>
            <Flex justify="space-between" align="center" wrap="wrap" gap={16}>
              <div className="space-y-1">
                <Title level={3} className="!m-0 !text-[var(--app-text)] !font-bold !text-xl tracking-tight">
                  Embed Script Snippet
                </Title>
                <Text className="text-[var(--app-text-soft)] text-xs font-medium uppercase tracking-wider block">
                  Copy the snippet below to initialize the custom widget on your host page.
                </Text>
              </div>
              
              <Flex gap={12} wrap="wrap" className="w-full sm:w-auto">
                <Button
                  type="default"
                  size="large"
                  icon={<SettingOutlined />}
                  onClick={openCustomizer}
                  className="w-full sm:w-auto !h-11 !px-5 !rounded-xl !border-[#0fb5a1] !text-[#0fb5a1] hover:!text-[#0a8576] hover:!border-[#0a8576] !font-semibold transition-transform active:scale-95 flex items-center justify-center gap-1.5"
                >
                  Customize Chat Style
                </Button>
                  <Tooltip title={copied ? "Copied!" : "Copy Script"}>
                    <Button
                      type="primary"
                      size="large"
                      icon={copied ? <CheckCircleOutlined /> : <CopyOutlined />}
                      onClick={handleCopy}
                      className="w-full sm:w-auto !h-11 !px-6 !rounded-xl !bg-[#0fb5a1] !border-none !font-semibold transition-transform active:scale-95 flex items-center justify-center gap-2"
                    >
                      {copied ? "Copied" : "Copy Code"}
                    </Button>
                  </Tooltip>
                </Flex>
              </Flex>
        <div className="flex items-center gap-4 bg-[var(--app-surface-muted)] p-3 rounded-2xl border border-[var(--app-border)] max-w-sm">
              <Text className="text-xs font-bold uppercase tracking-wider text-[var(--app-text-muted)] shrink-0">Select AI Agent:</Text>
              <div className="flex-1" style={{ minWidth: "180px", maxWidth: "240px" }}>
                <AgentList
                  selectedId={agent?.id}
                  size="middle"
                  style={{ width: "100%", height: 38 }}
                  onChange={(id: string, name: string) => {
                    const existing = sessions.find((s) => s.agentId === id);
                    if (existing) loadSession(existing);
                    else startNewChat({ id, name });
                  }}
                />
              </div>
            </div>

            {/* Code block window display */}
            <div className="relative group rounded-2xl border border-[var(--app-border)] bg-[var(--app-surface-muted)] overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--app-border)] bg-[var(--app-surface)]/50">
                <div className="flex gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-red-400/70" />
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-400/70" />
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-400/70" />
                </div>
                <Text className="text-[9px] font-bold uppercase tracking-widest text-slate-400">HTML</Text>
              </div>
              <pre className="p-4 md:p-5 overflow-x-auto custom-scrollbar m-0">
                <code className="text-[var(--app-text)] font-mono text-xs leading-relaxed block whitespace-pre">
                  <span className="text-[#0fb5a1] opacity-80">{"<script "}</span>
                  <span className="text-[#3b82f6]">src=</span>
                  <span className="text-emerald-500">{`'${process.env.NEXT_PUBLIC_API_BASES_URL || "http://grag.gramopro.ai"}/chat.js'`}</span>
                  {"\n  "}
                  <span className="text-[#3b82f6]">data-agent-id=</span>
                  <span className="text-emerald-500">{`"${agent?.id || "YOUR_AGENT_ID"}"`}</span>
                  {"\n  "}
                  <span className="text-[#3b82f6]">data-tenant-id=</span>
                  <span className="text-emerald-500">{`"${agentresp?.[0]?.tenant_id || "YOUR_TENANT_ID"}"`}</span>
                  {"\n  "}
                  <span className="text-[#3b82f6]">data-chat-type=</span>
                  <span className="text-emerald-500">{`"${chatType}"`}</span>
                  {chatType === "search" && (
                    <>
                      {"\n  "}
                      <span className="text-[#3b82f6]">data-position=</span>
                      <span className="text-emerald-500">{`"${position}"`}</span>
                      {"\n  "}
                      <span className="text-[#3b82f6]">data-placeholder=</span>
                      <span className="text-emerald-500">{`"${placeholderText}"`}</span>
                    </>
                  )}
                  {"\n  "}
                  <span className="text-[#3b82f6]">data-theme-color=</span>
                  <span className="text-emerald-500">{`"${themeColor}"`}</span>
                  <span className="text-[#0fb5a1] opacity-80">{">"}</span>
                  <span className="text-[#0fb5a1] opacity-80">{"</script>"}</span>
                </code>
              </pre>
            </div>
          </Flex>
        </Card>
      {/* FULL CUSTOMIZATION POPUP MODAL (Wider width, showing options on left and live preview sandbox on right) */}
      <Modal
        title={
          <div className="text-lg font-extrabold text-slate-800 dark:text-slate-100 border-b border-slate-100 dark:border-slate-800 pb-3 flex items-center gap-2">
            <span className="w-7 h-7 rounded-lg bg-[#0fb5a1]/10 flex items-center justify-center text-[#0fb5a1]">
              <SettingOutlined size={16} />
            </span>
            Customize Chat Widget Style & Color
          </div>
        }
        open={isCustomizerOpen}
        onOk={handleApply}
        onCancel={handleCancel}
        okText="OK"
        cancelText="Cancel"
        okButtonProps={{
          className: "!bg-[#0fb5a1] hover:!bg-[#0a8576] !border-none !rounded-xl !h-10 !px-6 !font-semibold"
        }}
        cancelButtonProps={{
          className: "!rounded-xl !h-10 !px-5"
        }}
        width={1100}
        centered
        className="custom-widget-modal"
      >
         <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 py-5 items-stretch min-h-[460px]">
          {/* Modal Left Column: Config Panel (span 5) */}
          <div className="lg:col-span-5 flex flex-col gap-6">
            {/* 1. Interface Layout Selection */}
            <div className="space-y-2">
              <label className="text-xs font-bold uppercase tracking-wider text-slate-400 block">
                1. Choose Interface Layout
              </label>
              <div className="grid grid-cols-2 gap-3">
                <div
                  onClick={() => setDraftChatType("icon")}
                  className={`p-3.5 rounded-2xl border-2 cursor-pointer transition-all duration-200 flex flex-col items-center text-center gap-2 bg-slate-50/50 dark:bg-slate-900/50 ${
                    draftChatType === "icon"
                      ? "border-[#0fb5a1] bg-[#0fb5a1]/5 ring-2 ring-[#0fb5a1]/10"
                      : "border-slate-200 dark:border-slate-800 hover:border-slate-300"
                  }`}
                >
                  <div
                    className="w-9 h-9 rounded-full flex items-center justify-center transition-colors"
                    style={{ background: `${draftThemeColor}15`, color: draftThemeColor }}
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                    </svg>
                  </div>
                  <div>
                    <div className="font-bold text-xs text-slate-800 dark:text-slate-200">Icon Bubble</div>
                    <div className="text-[10px] text-slate-400 mt-0.5 leading-tight">Floating circular chat corner button</div>
                  </div>
                  </div>
                    <div
                  onClick={() => setDraftChatType("search")}
                  className={`p-3.5 rounded-2xl border-2 cursor-pointer transition-all duration-200 flex flex-col items-center text-center gap-2 bg-slate-50/50 dark:bg-slate-900/50 ${
                    draftChatType === "search"
                      ? "border-[#0fb5a1] bg-[#0fb5a1]/5 ring-2 ring-[#0fb5a1]/10"
                      : "border-slate-200 dark:border-slate-800 hover:border-slate-300"
                  }`}
                >
                  <div
                    className="w-9 h-9 rounded-full flex items-center justify-center transition-colors"
                    style={{ background: `${draftThemeColor}15`, color: draftThemeColor }}
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <rect x="3" y="3" width="18" height="18" rx="2"/>
                      <line x1="9" y1="9" x2="15" y2="9"/>
                      <line x1="9" y1="13" x2="15" y2="13"/>
                      <line x1="9" y1="17" x2="11" y2="17"/>
                    </svg>
                  </div>
                  <div>
                    <div className="font-bold text-xs text-slate-800 dark:text-slate-200">Search Bar</div>
                    <div className="text-[10px] text-slate-400 mt-0.5 leading-tight">Zyte-like search input field layout</div>
                  </div>
                </div>

              </div>
              </div>
              {/* 2. Positioning & Placeholders for Search Layout */}
            {draftChatType === "search" && (
              <div className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 space-y-4 animate-in fade-in duration-200">
                <div className="space-y-1.5">
                  <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                    2. Alignment Position
                  </label>
                  <Radio.Group value={draftPosition} onChange={(e) => setDraftPosition(e.target.value)} size="small">
                    <Radio.Button value="center" className="!rounded-l-lg">Center Bottom</Radio.Button>
                    <Radio.Button value="right" className="!rounded-r-lg">Right Bottom</Radio.Button>
                  </Radio.Group>
                </div>
                 <div className="space-y-1.5">
                  <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                    3. Input Placeholder Text
                  </label>
                  <Input
                    value={draftPlaceholderText}
                    onChange={(e) => setDraftPlaceholderText(e.target.value)}
                    placeholder="Customize search bar placeholder..."
                    className="rounded-lg h-9 text-xs border-slate-300 dark:border-slate-700 dark:bg-slate-950 focus:border-[#0fb5a1]"
                  />
                </div>
              </div>
              )}
            {/* 3. Theme Brand Color Picker (Applied dynamically to the Sandbox on the right) */}
            <div className="space-y-2.5">
              <label className="text-xs font-bold uppercase tracking-wider text-slate-400 block">
                {draftChatType === "search" ? "4. Select Theme Color" : "2. Select Theme Color"}
              </label>
              <div className="flex items-center gap-3">
                {/* Preset Circles */}
                {COLOR_PRESETS.map((color) => (
                  <button
                    key={color.hex}
                    onClick={() => setDraftThemeColor(color.hex)}
                    style={{ background: color.hex }}
                    className={`w-7 h-7 rounded-full border-2 transition-transform duration-200 active:scale-90 relative ${
                      draftThemeColor.toLowerCase() === color.hex.toLowerCase()
                        ? "border-slate-800 scale-110 shadow-md"
                        : "border-transparent hover:scale-105"
                    }`}
                    title={color.name}
                  >
                    {draftThemeColor.toLowerCase() === color.hex.toLowerCase() && (
                      <span className="absolute inset-0 flex items-center justify-center text-white text-[10px]">
                        ✓
                      </span>
                    )}
                  </button>
                ))}
                {/* Custom Color Input */}
                <div className="flex items-center gap-2 border border-slate-200 dark:border-slate-800 rounded-lg p-1 bg-slate-50 dark:bg-slate-900 ml-1">
                  <input
                    type="color"
                    value={draftThemeColor}
                    onChange={(e) => setDraftThemeColor(e.target.value)}
                    className="w-7 h-7 rounded-md border-0 cursor-pointer p-0 bg-transparent shrink-0 outline-none"
                    title="Custom hex color"
                  />
                  <span className="text-[11px] font-mono pr-1 text-slate-500 font-bold select-all uppercase">
                    {draftThemeColor}
                  </span>
                </div>
              </div>
            </div>
          </div>
            {/* Modal Right Column: Live Web Sandbox Preview (span 7) */}
          <div className="lg:col-span-7 flex flex-col gap-3">
            <div className="flex justify-between items-center px-1">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <EyeOutlined /> Live Sandbox Preview
              </span>
              <span className="px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-emerald-500 bg-emerald-500/10 rounded-full">
                Interactive
              </span>
            </div>
            {/* Sandbox Browser frame mockup */}
               <div
              style={{
                backgroundColor: isDarkTheme ? "#0f172a" : "#ffffff",
                borderColor: isDarkTheme ? "#1e293b" : "#e2e8f0"
              }}
              className="border rounded-2xl overflow-hidden shadow-xl w-full flex-1 flex flex-col relative min-h-[420px] h-[420px]"
            >
              {/* Browser bar */}
              <div
                style={{
                  backgroundColor: isDarkTheme ? "#0b0f19" : "#f1f5f9",
                  borderBottomColor: isDarkTheme ? "#1e293b" : "#cbd5e1"
                }}
                className="flex items-center justify-between px-3 py-2 border-b"
              >
                <div className="flex gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-red-500/60" />
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-500/60" />
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/60" />
                </div>
                 <div
                  style={{
                    backgroundColor: isDarkTheme ? "#090d16" : "#ffffff",
                    borderColor: isDarkTheme ? "#1e293b" : "#e2e8f0",
                    color: isDarkTheme ? "#94a3b8" : "#64748b"
                  }}
                  className="border rounded-md px-3 py-0.5 text-[10px] font-mono w-2/5 text-center truncate"
                >
                  https://your-website.com
                </div>
                <div className="w-10" />
              </div>
              {/* Website canvas */}
              <div
                style={{
                  background: isDarkTheme
                    ? "linear-gradient(135deg, #090d16 0%, #0f172a 50%, #1e1b4b 100%)"
                    : "linear-gradient(135deg, #f8fafc 0%, #f1f5f9 50%, #e2e8f0 100%)"
                }}
                className="flex-1 flex flex-col items-center justify-center p-6 text-center relative select-none overflow-hidden"
              >
                <div
                  style={{ backgroundColor: isDarkTheme ? "rgba(99, 102, 241, 0.1)" : "rgba(59, 130, 246, 0.05)" }}
                  className="absolute top-1/4 left-1/4 w-32 h-32 rounded-full blur-[60px]"
                />
                <div
                  style={{ backgroundColor: isDarkTheme ? "rgba(15, 181, 161, 0.1)" : "rgba(15, 181, 161, 0.05)" }}
                  className="absolute bottom-1/4 right-1/4 w-32 h-32 rounded-full blur-[60px]"
                />
                <div className="space-y-3 max-w-sm relative z-10 p-3">
                  <h4
                    style={{ color: isDarkTheme ? "#ffffff" : "#1e293b" }}
                    className="m-0 font-extrabold text-xl tracking-tight leading-tight"
                  >
                    Welcome to Your Website
                  </h4>
                  <p
                    style={{ color: isDarkTheme ? "#94a3b8" : "#64748b" }}
                    className="m-0 text-xs leading-relaxed font-light"
                  >
                    Observe layout shifts, active glow states, and header accents changing dynamically as you select theme colors on the left.
                  </p>
                </div>
                {/* RENDER PREVIEW OPTION 1: Floating Icon Style (Using draftThemeColor) */}
                {draftChatType === "icon" && (
                  <div
                    onClick={() => setPreviewIsOpen(!previewIsOpen)}
                    className="absolute bottom-5 right-5 w-12 h-12 bg-white border border-slate-200/80 rounded-full shadow-lg flex items-center justify-center cursor-pointer hover:scale-105 transition-transform duration-200 z-30 animate-bounce [animation-duration:3s]"
                  >
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={draftThemeColor} stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M21 11.5C21 16.7467 16.9706 21 12 21C10.1302 21 8.39632 20.3992 6.97743 19.3722L3 20.5L4.15064 16.6329C3.41732 15.1543 3 13.4754 3 11.5C3 6.25329 7.02944 2 12 2C16.9706 2 21 6.25329 21 11.5Z" fill={draftThemeColor} stroke={draftThemeColor} />
                      <path d="M8 10H16M8 14H14" stroke="white" stroke-width="2" />
                    </svg>
                  </div>
                )}
                {/* RENDER PREVIEW OPTION 2: Search Bar Style (Using draftThemeColor & Hidden if Chat Panel is open to prevent double inputs!) */}
                {(draftChatType === "search" && !previewIsOpen) && (
                  <div
                    className={`absolute z-30 w-[90%] bottom-5 ${
                      draftPosition === "center"
                        ? "left-1/2 -translate-x-1/2"
                        : "right-5"
                    }`}
                    style={{ maxWidth: draftPosition === "center" ? "90%" : "340px" }}
                  >
                    {/* Glowing outline wrapper focused/hovered with theme color */}
                    <div
                      className="p-[1.5px] rounded-[24px] transition-all duration-300 shadow-md"
                      style={{ background: isDarkTheme ? "#334155" : "#cbd5e1" }}
                      onMouseEnter={(e) => { e.currentTarget.style.background = draftThemeColor; e.currentTarget.style.boxShadow = `0 4px 16px ${draftThemeColor}40`; }}
                      onMouseLeave={(e) => { e.currentTarget.style.background = isDarkTheme ? "#334155" : "#cbd5e1"; e.currentTarget.style.boxShadow = "none"; }}
                    >
                      <div
                        style={{
                          backgroundColor: isDarkTheme ? "#090d16" : "#ffffff",
                          borderColor: isDarkTheme ? "#1e293b" : "#e2e8f0"
                        }}
                        className="flex items-center border rounded-[22.5px] px-3.5 py-1.5 gap-2 w-full"
                      >
                        <span className="flex items-center text-slate-400 hover:text-slate-600 cursor-pointer" onClick={() => setPreviewIsOpen(true)}>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="10"/>
                            <polyline points="12 6 12 12 16 14"/>
                          </svg>
                        </span>
                        <input
                          type="text"
                          value={previewInput}
                          onChange={(e) => setPreviewInput(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handlePreviewSend(previewInput);
                          }}
                          placeholder={draftPlaceholderText}
                           style={{
                            backgroundColor: "transparent",
                            color: isDarkTheme ? "#ffffff" : "#1e293b",
                            border: "none",
                            outline: "none",
                            flex: 1,
                            fontSize: "11px",
                            paddingTop: "4px",
                            paddingBottom: "4px"
                          }}

                        />
                        <button
                          onClick={() => handlePreviewSend(previewInput)}
                          disabled={!previewInput.trim()}
                          style={{
                             background: previewInput.trim() ? draftThemeColor : (isDarkTheme ? "#1e293b" : "#f1f5f9"),
                            color: previewInput.trim() ? "#ffffff" : (isDarkTheme ? "#475569" : "#94a3b8")
                          }}
                          className="w-6 h-6 rounded-full flex items-center justify-center border-none transition-all duration-200 cursor-pointer"
                        >
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                            <line x1="12" y1="19" x2="12" y2="5"/>
                            <polyline points="5 12 12 5 19 12"/>
                          </svg>
                        </button>
                      </div>
                    </div>
                  </div>
                )}
                {/* RENDER MOCK CHAT PANEL FRAME OVERLAY (Positions dynamically at bottom-5 when open to seamlessly replace input!) */}
                {previewIsOpen && (
                  <div
                     style={{
                      backgroundColor: isDarkTheme ? "#0f172a" : "#ffffff",
                      borderColor: isDarkTheme ? "#1e293b" : "#e2e8f0"
                    }}
                    className={`absolute rounded-2xl shadow-2xl flex flex-col border z-40 transition-all duration-300 h-[340px] bottom-5 ${
                      isWideLayout
                        ? "w-[90%] left-1/2 -translate-x-1/2"
                        : "w-[90%] max-w-[340px] " + (draftChatType === "icon" || draftPosition === "right" ? "right-5" : "left-1/2 -translate-x-1/2")
                    }`}
                  >
                    {/* Mock Chat Header (accented with brand color) */}
                    <div
                      style={{
                        backgroundColor: isDarkTheme ? "#1e293b" : "#f8fafc",
                        borderBottom: isDarkTheme ? "1px solid #334155" : "1px solid #e2e8f0"
                      }}
                      className="flex items-center justify-between px-3.5 py-2.5 rounded-t-2xl text-left"
                    >
                      <div className="flex items-center gap-2">
                        <div
                          className="w-7 h-7 rounded-lg flex items-center justify-center text-white transition-colors"
                          style={{ background: draftThemeColor }}
                        >
                          <svg width="14" height="14" fill="white" viewBox="0 0 24 24">
                            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 17h-2v-2h2v2zm2.07-7.75l-.9.92C13.45 12.9 13 13.5 13 15h-2v-.5c0-1.1.45-2.1 1.17-2.83l1.24-1.26c.37-.36.59-.86.59-1.41 0-1.1-.9-2-2-2s-2 .9-2 2H7c0-2.76 2.24-5 5-5s5 2.24 5 5c0 1.04-.42 1.99-1.07 2.75z"/>
                          </svg>
                        </div>
                        <div>
                          <div
                            style={{ color: isDarkTheme ? "#ffffff" : "#1e293b" }}
                            className="text-xs font-bold flex items-center gap-1 leading-none"
                          >
                            {agent?.name || "Gsearch AI"}
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                          </div>
                         <span style={{ color: isDarkTheme ? "#94a3b8" : "#64748b" }} className="text-[9px] block mt-0.5 leading-none">AI Assistant Widget</span>
                        </div>
                      </div>
                      <button
                        onClick={() => setPreviewIsOpen(false)}
                        className="border-none bg-transparent text-slate-400 hover:text-slate-700 cursor-pointer text-sm font-semibold"
                      >
                        ✕
                      </button>
                    </div>
                    {/* Mock Chat Feed */}
                    <div
                     style={{ backgroundColor: isDarkTheme ? "#090d16" : "#f1f5f9" }}
                      className="flex-1 overflow-y-auto p-3.5 flex flex-col gap-2.5 text-left"
                    >
                      {previewMessages.length === 0 ? (
                        <div className="flex flex-col items-center justify-center text-center h-full text-slate-400 p-4">
                          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" className="mb-1.5 opacity-50">
                            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                          </svg>
                          <span className="text-[10px]">No messages yet. Send a query to test!</span>
                        </div>
                      ) : (
                        previewMessages.map((msg, index) => {
                          const isUser = msg.role === "user";
                          return (
                            <div key={index} className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}>
                              <span className="text-[8px] text-slate-400 mb-0.5">{isUser ? "You" : agent?.name || "Agent"}</span>
                              <div
                                style={{
                                  background: isUser
                                    ? (isDarkTheme ? "#1e293b" : "#f1f5f9")
                                    : (isDarkTheme ? "#0f172a" : "#ffffff"),
                                  borderColor: isUser
                                    ? (isDarkTheme ? "#334155" : "#e2e8f0")
                                    : (isDarkTheme ? "#1e293b" : "#f1f5f9"),
                                  color: isDarkTheme ? "#ffffff" : "#1e293b",
                                }}
                                className={`px-2.5 py-1.5 rounded-2xl text-[11px] max-w-[85%] border shadow-sm leading-normal`}
                              >
                                {msg.content}
                              </div>
                            </div>
                          );
                        })
                      )}
                      {previewIsTyping && (
                        <div className="flex flex-col items-start animate-fade-in">
                          <span className="text-[8px] text-slate-400 mb-0.5">Agent is typing...</span>
                          <div className="px-2.5 py-1.5 rounded-2xl bg-white border border-slate-100 shadow-sm flex items-center gap-1">
                            <span className="w-1 h-1 rounded-full bg-slate-400 animate-bounce" />
                            <span className="w-1 h-1 rounded-full bg-slate-400 animate-bounce [animation-delay:0.2s]" />
                            <span className="w-1 h-1 rounded-full bg-slate-400 animate-bounce [animation-delay:0.4s]" />
                          </div>
                        </div>
                      )}
                      <div ref={messagesEndRef} />
                    </div>
                    {/* Mock Input Bar inside Open Chat Panel */}
                    <div
                      className="p-2.5 border-t rounded-b-2xl"
                      style={{
                        backgroundColor: isDarkTheme ? "#0f172a" : "#ffffff",
                        borderTopColor: isDarkTheme ? "#1e293b" : "#f1f5f9"
                      }}
                    >
                      <div
                        className="flex items-center border rounded-full px-2.5 py-1 gap-1.5"
                        style={{
                          backgroundColor: isDarkTheme ? "#090d16" : "#f8fafc",
                          borderColor: isDarkTheme ? "#1e293b" : "#e2e8f0"
                        }}
                      >
                        <input
                          type="text"
                          value={previewInput}
                          onChange={(e) => setPreviewInput(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handlePreviewSend(previewInput);
                          }}
                          placeholder={draftChatType === "search" ? "Ask a follow up..." : "Type your message..."}
                          style={{
                            backgroundColor: "transparent",
                            color: isDarkTheme ? "#ffffff" : "#1e293b",
                            border: "none",
                            outline: "none",
                            flex: 1,
                            fontSize: "11px",
                          }}
                        />
                        <button
                          onClick={() => handlePreviewSend(previewInput)}
                          disabled={!previewInput.trim()}
                          style={{
                            background: previewInput.trim() ? draftThemeColor : "#e2e8f0",
                            color: previewInput.trim() ? "#ffffff" : "#94a3b8",
                          }}
                          className="w-5.5 h-5.5 rounded-full flex items-center justify-center border-none cursor-pointer text-xs transition-colors duration-200"
                        >
                          ↑
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div></div>
      </Modal>
      <style jsx global>{`
        .custom-widget-modal .ant-modal-content {
          border-radius: 28px !important;
          padding: 24px 32px !important;
          box-shadow: 0 24px 50px rgba(0,0,0,0.2) !important;
          background: #ffffff !important;
        }
          .dark .custom-widget-modal .ant-modal-content {
          background: #151b26 !important;
          border: 1px solid #1f293d !important;
        }
        .custom-widget-modal .ant-modal-header {
          background: transparent !important;
          border-bottom: none !important;
          margin-bottom: 0 !important;
        }
        .custom-widget-modal .ant-modal-title {
          background: transparent !important;
        }
        .custom-widget-modal .ant-modal-close {
          color: #94a3b8 !important;
        }
        .custom-widget-modal .ant-modal-close:hover {
          color: #64748b !important;
        }
      `}</style>
    </Flex>
  );
}
