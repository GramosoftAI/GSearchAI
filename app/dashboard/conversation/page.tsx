"use client";

import { Flex, Typography, Button, Input, Tooltip, Avatar, Drawer, Grid, Upload, message } from "antd";
import React, { useState, useRef, useEffect, useCallback } from "react";
import { LuBot, LuHistory, LuSearch, LuPlus, LuPaperclip, LuFileText,} from "react-icons/lu";
import {
  FiUser,
  FiSend,
  FiMoreVertical,
  FiTrash2,
  FiX,
  FiCopy,
  FiEdit2,
} from "react-icons/fi";
import { MdBarChart as MdBarChartIcon } from "react-icons/md";
import { PiGraphLight } from "react-icons/pi";
import { getCookie } from "../../config/cookies";
import { AUTH_COOKIE_KEY, API_BASE_URL } from "../../config/config";
import AgentList from "../../components/ui/AgentList";
import useAxios from "../../hooks/useAxios";
import { useStore } from "../../hooks/useStore";
import type { Agent } from "../../components/ui/type";
import type { UploadFile } from "antd";
import { Switch } from "antd";

const { Text, Title } = Typography;

// ─── Types ───────────────────────────────────────────────────────────────────
type MessageSource = {
  fileName: string;
  positions: number[];
};
type Message = {
  role: "user" | "assistant";
  content: string;
  confidence?: number;
  nodes?: number;
  timestamp?: string;
  message_count?: number;
  sources?: MessageSource[];
  file?: {
    name: string;
    type: string;
    url: string;
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

type Agents = { id: string; name: string } | null;

// ─── API Helpers ──────────────────────────────────────────────────────────────

function authHeaders() {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${getCookie(AUTH_COOKIE_KEY)}`,
  };
}

async function fetchSessions(agent: Agents): Promise<ChatSession[]> {
  try {
    const res = await fetch(`${API_BASE_URL}/chats/${agent?.id}/sessions?limit=20&offset=0`, {
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(`${res.status}`);
    const result = await res.json();
    return result.data ?? [];
  } catch (e) {
    console.error("fetchSessions failed:", e);
    return [];
  }
}

type AgentListResponse = {
  data?: {
    agents?: Agent[];
  };
};

export default function ChatPlaygroundPage() {
  const [agent, setAgent] = useState<{ id: string; name: string } | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<any>([]);
  const [historyDrawerOpen, setHistoryDrawerOpen] = useState(false);
  const screen = Grid.useBreakpoint();
  const setAgentList = useStore((state) => state.setAgentList);
  const setBotsCache = useStore((state) => state.setBotsCache);
  const [input, setInput] = useState("");
  const [streamingText, setStreamingText] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [wsStatus, setWsStatus] = useState<"connecting" | "open" | "closed" | "error">("closed");
  const [getAgents] = useAxios<AgentListResponse>({ endpoint: "GETAGENTLIST", hideErrorMsg: true });
  const bottomRef = useRef<HTMLDivElement>(null);
  const ws = useRef<WebSocket | null>(null);
  const streamingTextRef = useRef<string>("");
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const [isEnabled, setIsEnabled] = useState(false);

// ─── IPPO ADD PANNA VENDIYA STATES ───────────────────────────────────
const [editingMessageIndex, setEditingMessageIndex] = useState<number | null>(null);
const [tempEditText, setTempEditText] = useState("");
  // File Upload State Tracker
  const [attachedFile, setAttachedFile] = useState<UploadFile | null>(null);

  function mapAgentsToList(agents: Agent[]) {
    return agents.map((agent) => ({
      id: agent.id,
      name: agent.name,
      status: agent.is_active ? "active" : "draft",
    }));
  }

  // ─── Persistence Logic ──────────────────────────────────────────────────────
  useEffect(() => {
    getAgents(undefined, (payload) => {
      const agents = payload?.data?.agents ?? [];
      setBotsCache(agents);
      setAgentList(mapAgentsToList(agents));
    });
     // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (agent) {
      (async () => {
        const data = await fetchSessions(agent);
        setSessions(data);
      })();
    }
    return () => {
      ws.current?.close();
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    };
  }, [agent]);

  // ─── WebSocket Logic ────────────────────────────────────────────────────────

  const connectWs = useCallback(function connectSocket() {
    if (!agent?.id) return;

    if (ws.current) {
      ws.current.close();
    }

    setWsStatus("connecting");

    const defaultWsHost = API_BASE_URL
      .replace(/^http/, "ws")
      .split("/api/v1")[0];

    const wsHost = process.env.NEXT_PUBLIC_WS_URL || defaultWsHost;
    const wsUrl = `${wsHost}/api/v1/rag/ws/${agent.id}?token=${getCookie(AUTH_COOKIE_KEY)}`;

    const socket = new WebSocket(wsUrl);
    ws.current = socket;

    socket.onopen = () => {
      setWsStatus("open");
      console.log("opend");
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };

    socket.onmessage = (event) => {
      const rawData = String(event.data);
      console.log("onmessage");
      if (!rawData.startsWith("{") ) { //&& !rawData.startsWith("[")) rawData.length === 1 || (
        streamingTextRef.current += rawData;
        setStreamingText(streamingTextRef.current);
        setIsTyping(true);
        return;
      }

      try {
        const data = JSON.parse(rawData);
        if (data.type === "metadata") return;

        if (data.type === "done") {
          const accumulated = streamingTextRef.current;
          console.log("DELTA:",accumulated)
          let textContent = accumulated.replace(/<think>[\s\S]*?<\/think>/g, "");
          const extractedSources: MessageSource[] = [];

          // const sourceRegex =
          //     /\[Source:\s*(.+?)(?:\s*-\s*Position\s*([^\]]+))?\]/g;
          const sourceRegex =
          /(?:\[Source:\s*(.+?)(?:\s*-\s*Position\s*([^\]]+))?\]|\(Source:\s*(.+?)(?:\s*-\s*Position\s*([^)]+))?\))/g;

            let match;

            while ((match = sourceRegex.exec(accumulated)) !== null) {
              const fileName = match[1]?.trim() || "";

              const positions = match[2]
                ? match[2]
                    .split(",")
                    .map((p) => parseInt(p.trim()))
                    .filter((p) => !isNaN(p))
                : [];

              const exists = extractedSources.some(
              (source) => source.fileName === fileName
            );

            if (!exists) {
              extractedSources.push({
                fileName,
                positions,
              });
            }
            }

          if (extractedSources.length > 0) {
            textContent = accumulated.replace(/\[Source:[^\]]+\]/g, "").replace(/<think>[\s\S]*?<\/think>/g, "").trim();
          }
          if (accumulated) {
            setMessages((prev: any) => [
              ...prev,
              {
                role: "assistant",
                content: textContent,
                sources: extractedSources.length > 0 ? extractedSources : undefined,
                timestamp: new Date().toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                }),
              },
            ]);
          }
          streamingTextRef.current = "";
          setStreamingText("");
          setIsTyping(false);
          return;
        }

        if (data.type === "chunk" || data.type === "delta" || data.type === "content" || data.type === "text") {
          const textChunk = data.message || data.content || data.text || "";
          streamingTextRef.current += textChunk;
          setStreamingText(streamingTextRef.current);
          setIsTyping(true);
          return;
        }
      } catch (err) {
        streamingTextRef.current += rawData;
        setStreamingText(streamingTextRef.current);
        setIsTyping(true);
        console.log(err);
      }
    };

    socket.onclose = () => {
      setWsStatus("closed");
      console.log("conlose");
      reconnectTimeoutRef.current = setTimeout(() => {
        if (agent?.id) {
          connectSocket();
        }
      }, 3000);
    };

    socket.onerror = () => {
      setWsStatus("error");
    };
  }, [agent?.id]);

  useEffect(() => {
    connectWs();
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      ws.current?.close();
    };
  }, [connectWs]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText]);

  // ─── Actions ───────────────────────────────────────────────────────────────

  const startNewChat = (selectedAgent: { id: string; name: string }) => {
    const newSessionId = `session_${Date.now()}`;
    const newSession: any = {
      id: newSessionId,
      agentId: selectedAgent.id,
      agentName: selectedAgent.name,
      messages: [],
      updatedAt: Date.now()
    };
    setSessions(prev => [newSession, ...prev]);
    setCurrentSessionId(newSessionId);
    setMessages([]);
    setAgent(selectedAgent);
  };

  const loadSession = (session: ChatSession) => {
    setCurrentSessionId(session.id);
    
    const mappedMessages = (session.messages || []).map((msg: any) => ({
      role: msg.role,
      content: msg.content,
      file: msg.file, 
      timestamp: msg.created_at 
        ? new Date(msg.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    }));

    setMessages(mappedMessages);
    setAgent({ 
      id: session.agent_id || session.agentId, 
      name: session.title || session.agentName 
    });
    setHistoryDrawerOpen(false);
  };

  const deleteSession = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    setSessions(prev => prev.filter(s => s.id !== id));
    if (currentSessionId === id) {
      setCurrentSessionId(null);
      setMessages([]);
      setAgent(null);
    }
  };

  // Process files dynamically before upload triggers
  const handleBeforeUpload = (file: UploadFile) => {
    const isValidSize = (file.size ?? 0) / 1024 / 1024 < 25; // 25MB limit
    if (!isValidSize) {
      message.error("File details exceed security isolation thresholds (25MB max).");
      return Upload.LIST_IGNORE;
    }
    
    // Formulate dynamic object properties for UI preview rendering
    file.url = URL.createObjectURL(file as any);
    setAttachedFile(file);
    return false; // Stop auto post action upload handling
  };

  const handleSend = () => {
    const trimmed = input.trim();
    if ((!trimmed && !attachedFile) || !agent?.id || wsStatus !== "open") return;

    if (!currentSessionId) {
      const newId = `session_${Date.now()}`;
      const newSession: any = {
        id: newId,
        agentId: agent.id,
        agentName: agent.name,
        messages: [],
        updatedAt: Date.now()
      };
      setSessions(prev => [newSession, ...prev]);
      setCurrentSessionId(newId);
    }

    // Build payload structure containing optional file metrics
    let payloadFile:any = undefined;
    if (attachedFile) {
      payloadFile = {
        name: attachedFile.name,
        type: attachedFile.type || "",
        url: attachedFile.url || "",
      };
    }

    setMessages((prev: any) => [...prev, { 
      role: "user", 
      content: trimmed,
      file: payloadFile,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) 
    }]);
    
    // Dispatch structural data to active micro-orchestration node
    ws.current?.send(JSON.stringify({ 
      query: trimmed,
      file: payloadFile ? { name: payloadFile.name, type: payloadFile.type } : null 
    }));

    setInput("");
    setAttachedFile(null); // Clear dock frame tracking parameters
    streamingTextRef.current = "";
    setStreamingText("");
    setIsTyping(true);
  };

  const handleCopyMessage = async (text: string) => {
  try {
    await navigator.clipboard.writeText(text);
    message.success("Copied");
  } catch {
    message.error("Copy failed");
  }
};
const handleEditMessage = (index: number, content: string) => {
  setEditingMessageIndex(index);
  setTempEditText(content);
};

const handleSaveEdit = (index: number) => {
  if (!tempEditText.trim() || !agent?.id || wsStatus !== "open") return;

  // 1. Logic Fix: Edited message-oda cut panni, pazhaya bot responses-ai remove panniduvom
  const updatedMessages = messages.slice(0, index + 1);
  
  // 2. Ippo edit panna message-ai mattrum update pannuvom
  updatedMessages[index].content = tempEditText.trim();
  setMessages(updatedMessages);

  // 3. Edit mode-ai close seiyavum
  setEditingMessageIndex(null);

  // 4. WebSocket-il puthu query-ai anupavum
  ws.current?.send(JSON.stringify({ 
    query: tempEditText.trim(),
    file: null 
  }));

  setIsTyping(true);
};

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") handleSend();
  };

  return (
    <div className="h-[calc(100vh-60px)] md:h-[calc(100vh-100px)] w-full flex items-center justify-center p-0 md:p-8 bg-[var(--app-bg-deep)]/20 antialiased selection:bg-[#285d91]/20">
      
      <Flex vertical className="w-full h-full bg-gradient-to-b from-[var(--app-surface)] via-[var(--app-surface)]/95 to-[var(--app-surface)] rounded-none md:rounded-[28px] border-0 md:border border-[var(--app-border)]/60 shadow-2xl overflow-hidden relative">
        
        {/* Top Header */}
        <div className="w-full px-4 md:px-8 py-4 border-b border-[var(--app-border)]/40 backdrop-blur-md bg-[var(--app-surface)]/50 sticky top-0 z-40 transition-all">
          <Flex justify="space-between" align="center" className="gap-2">
            
           {screen.md && <Flex align="center" gap={12} className="min-w-0">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-[#285d91] to-[#3a7cb3] text-white flex items-center justify-center shadow-md shadow-blue-900/10 shrink-0">
                <LuBot size={20} className="animate-pulse" />
              </div>
              <Flex vertical className="min-w-0">
                <Title level={5} className="!m-0 !text-[var(--app-text)] !font-extrabold tracking-tight truncate text-sm md:text-base">
                  {agent?.name || "Neural Cortex"}
                </Title>
                <Flex align="center" gap={5} className="mt-0.5">
                  <span className={`w-1.5 h-1.5 rounded-full ${wsStatus === "open" ? "bg-emerald-500 animate-pulse" : "bg-amber-500"}`} />
                  <Text className="text-[9px] font-bold uppercase tracking-widest text-[var(--app-text-soft)] opacity-80 truncate">
                    {wsStatus === "open" ? "Link Stabilized" : "Syncing Link Core..."}
                  </Text>
                  <Switch
                  checked={isEnabled}
                  onChange={(checked) => {
                    setIsEnabled(checked);
                    console.log(checked); // true or false
                  }}
                />
                </Flex>
              </Flex>
            </Flex>}
            
            <Flex align="center" gap={8} className="shrink-0">
              <div className="scale-90 md:scale-100 origin-right">
                <AgentList
                  selectedId={agent?.id}
                  onChange={(id: string, name: string) => {
                    const existing = sessions.find(s => s.agentId === id);
                    if (existing) loadSession(existing);
                    else startNewChat({ id, name });
                  }}
                />
              </div>
              <Button 
                type="text" 
                icon={<FiMoreVertical className="text-lg text-[var(--app-text-soft)]" />} 
                onClick={() => setHistoryDrawerOpen(true)}
                className="hover:bg-[var(--app-hover)] !rounded-xl w-10 h-10 flex items-center justify-center transition-colors"
              />
            </Flex>
          </Flex>
        </div>

        {/* Conversation Stream */}
        <div className="flex-1 overflow-y-auto px-4 md:px-12 py-6 md:py-10 space-y-6 custom-scrollbar bg-dots-pattern">
          {messages.length === 0 && !isTyping && (
            <Flex vertical align="center" justify="center" className="h-full space-y-5 opacity-80 select-none">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-b from-[var(--app-surface-muted)] to-[var(--app-border)]/20 flex items-center justify-center relative shadow-inner">
                <div className="absolute inset-0 bg-[#285d91]/5 rounded-2xl blur-xl" />
                <LuBot size={32} className="text-[#285d91]/60" />
              </div>
              <div className="text-center max-w-sm px-4">
                <h3 className="m-0 text-[var(--app-text)] font-black text-lg md:text-xl tracking-tight">Initiate Thought Sequence</h3>
                <Text className="text-[var(--app-text-muted)] text-xs font-medium mt-1 block">
                  Select a workflow node structure above or query directly to execute runtime analysis loop frames.
                </Text>
              </div>
            </Flex>
          )}

          {messages.map((msg: any, i: any) => {
            const isUser = msg.role === "user";
            const hasImage = msg.file?.type?.startsWith("image/");
            const hasDoc = msg.file && !hasImage;

            return (
              <div key={i} className={`flex w-full ${isUser ? "justify-end" : "justify-start"} animate-in fade-in slide-in-from-bottom-2 duration-300`}>
                <div className={`flex gap-3 max-w-[88%] md:max-w-[75%] ${isUser ? "flex-row-reverse" : "flex-row"}`}>
                  
                  <Avatar 
                    size={32}
                    icon={isUser ? <FiUser /> : <LuBot />} 
                    className={`${isUser ? "bg-emerald-500/10 !text-emerald-600" : "bg-[#285d91]/10 !text-[#285d91]"} shadow-none shrink-0 border border-current/10 font-bold`}
                  />

                  <div className="flex flex-col space-y-1">
                    <span className={`text-[9px] font-bold text-[var(--app-text-soft)] px-1 ${isUser ? "text-right" : "text-left"}`}>
                      {msg.timestamp}
                    </span>

                    {/* <div className={`p-4 md:p-5 rounded-2xl transition-all duration-200 shadow-sm border ${ */}
                    <div
                          className={`group relative p-4 md:p-5 rounded-2xl transition-all duration-200 shadow-sm border ${
                      isUser 
                        ? "bg-[#285d91] text-white rounded-tr-none border-[#285d91]/20 font-medium" 
                        : "bg-[var(--app-surface-muted)] text-[var(--app-text)] rounded-tl-none border-[var(--app-border)]/40 font-normal"
                    }`}>
                      
                      {/* Dynamic File Rendering UI Framework */}
                      <div className="absolute -bottom-10 right-0 opacity-0 group-hover:opacity-100 transition-all duration-200 flex gap-2 z-20">
                          <button
                            onClick={() => handleCopyMessage(msg.content)}
                            className="bg-neutral-800 text-white p-2 rounded-lg hover:bg-neutral-700 cursor-pointer"
                          >
                            <FiCopy size={14} />
                          </button>

                          {isUser && (
                          <button
                            onClick={() => handleEditMessage(i, msg.content)} // <-- Ingu 'i' add seiyapattuள்ளது
                            className="bg-neutral-800 text-white p-2 rounded-lg hover:bg-neutral-700 cursor-pointer"
                          >
                            <FiEdit2 size={14} />
                          </button>
                        )}
                        </div>
                      {hasImage && (
                        <div className="mb-3 overflow-hidden rounded-xl max-w-[280px] border border-white/10 shadow-sm">
                          <img src={msg.file.url} alt={msg.file.name} className="w-full h-auto object-cover max-h-52 dynamic-img-render" />
                        </div>
                      )}

                      {hasDoc && (
                        <Flex align="center" gap={10} className={`mb-3 p-3 rounded-xl border ${isUser ? "bg-black/10 border-white/10" : "bg-[var(--app-surface)] border-[var(--app-border)]/60"} max-w-[280px]`}>
                          <div className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${isUser ? "bg-white/10 text-white" : "bg-[#285d91]/10 text-[#285d91]"}`}>
                            <LuFileText size={18} />
                          </div>
                          <Flex vertical className="min-w-0 flex-1">
                            <Text className={`text-xs font-bold truncate ${isUser ? "!text-white" : "!text-[var(--app-text)]"}`}>
                              {msg.file.name}
                            </Text>
                            <Text className={`text-[9px] uppercase tracking-wider font-extrabold opacity-60 ${isUser ? "!text-white/80" : "!text-[var(--app-text-soft)]"}`}>
                              Document Log
                            </Text>
                          </Flex>
                        </Flex>
                      )}

                      {msg.content &&                  
                      <div 
                        className={`text-xs md:text-sm leading-relaxed font-medium ${!isUser ? "text-[var(--app-text)]" : ""}`}
                        style={isUser ? { color: "#ffffff", WebkitTextFillColor: "#ffffff", fontWeight: "bold" } : undefined}
                      >
                        {/* Inline Editing Mode checking */}
                        {editingMessageIndex === i ? (
                        <div className="flex flex-col gap-3 my-2 w-full animate-in fade-in duration-200">
                          <Input.TextArea
                            value={tempEditText}
                            onChange={(e) => setTempEditText(e.target.value)}
                            autoSize={{ minRows: 2, maxRows: 6 }}
                            className="!bg-[var(--app-surface)] !text-[var(--app-text)] !border-[var(--app-border)] focus:!border-[#285d91] focus:!ring-1 focus:!ring-[#285d91] rounded-2xl p-4 shadow-sm transition-all resize-none placeholder-[var(--app-text-muted)]"
                            placeholder="Edit your message..."
                          />
                          
                          <div className="flex gap-2 justify-end">
                            <Button 
                              className="rounded-full border border-[var(--app-border)] text-[var(--app-text-soft)] bg-transparent hover:!bg-slate-100/10 hover:!text-[var(--app-text)] px-4 h-9 font-medium transition-all"
                              onClick={() => setEditingMessageIndex(null)}
                            >
                              Cancel
                            </Button>
                            <Button 
                              type="primary" 
                              className="rounded-full !bg-[#10a37f] hover:!bg-[#0d8567] !border-none text-white px-5 h-9 font-semibold shadow-sm transition-all"
                              onClick={() => handleSaveEdit(i)}
                            >
                              Save & Send
                            </Button>
                          </div>
                        </div>
                      ) : (
                        // Normal Display Mode
                        <span className="whitespace-pre-wrap mr-2 leading-7">{msg.content}</span>
                      )}

                        {!isUser && msg.sources && msg.sources.length > 0 && isEnabled && (
                          <div className="flex justify-end">
                          <span className="inline-flex items-center gap-1.5 bg-neutral-800 hover:bg-neutral-700 text-neutral-300 px-2.5 py-0.5 rounded-full border border-neutral-700/50 shadow-sm transition-colors align-middle select-none cursor-pointer">
                            <LuFileText size={11} className="text-[#3a7cb3]" />
                            <span className="text-[11px] font-bold tracking-tight">
                              {/* {msg.sources[0].fileName} */}
                              {msg.sources[0].fileName.startsWith("http") ? (
                                      <a
                                        href={msg.sources[0].fileName}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="text-[11px] font-bold tracking-tight text-blue-400 hover:underline"
                                        onClick={(e) => e.stopPropagation()}
                                      >
                                        {msg.sources[0].fileName}
                                      </a>
                                    ) : (
                                      <span className="text-[11px] font-bold tracking-tight">
                                        {msg.sources[0].fileName}
                                      </span>
                                    )}
                            </span>

                            {msg.sources.length > 1 && (
                              <Tooltip
                                title={
                                  <div className="flex flex-col gap-1 p-1">
                                    <span className="text-[10px] font-extrabold uppercase tracking-wider text-blue-300 block mb-1">Additional Sources:</span>
                                    
                                    {msg.sources.slice(1).map((src: any, idx: number) => (
                                              <div
                                                key={idx}
                                                className="text-xs border-b border-white/10 pb-1 last:border-0"
                                              >
                                                {src.fileName.startsWith("http") ? (
                                                  <a
                                                    href={src.fileName}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    className="text-blue-400 hover:underline"
                                                  >
                                                    {src.fileName}
                                                  </a>
                                                ) : (
                                                  src.fileName
                                                )}
                                              </div>
                                            ))}
                                  </div>
                                }
                                placement="top"
                              >
                                <span className="text-[10px] font-black text-neutral-400 pl-0.5">
                                  +{msg.sources.length - 1}
                                </span>
                              </Tooltip>
                            )}
                          </span>
                          </div>
                        )}

                      </div>}


                      {!isUser && (msg.confidence || msg.nodes) && (
                        <div className="mt-4 pt-3 border-t border-[var(--app-border)]/60 flex flex-wrap gap-2">
                          {msg.confidence && (
                            <span className="flex items-center gap-1.5 text-[9px] font-extrabold text-emerald-600 uppercase tracking-wider bg-emerald-500/10 px-2 py-0.5 rounded-md">
                              <MdBarChartIcon className="text-xs" /> {msg.confidence}% Confidence
                            </span>
                          )}
                          {msg.nodes && (
                            <span className="flex items-center gap-1.5 text-[9px] font-extrabold text-blue-600 uppercase tracking-wider bg-blue-500/10 px-2 py-0.5 rounded-md">
                              <PiGraphLight className="text-xs" /> {msg.nodes} Paths
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  </div>

                </div>
              </div>
            );
          })} 

          {isTyping && (
            <div className="flex w-full justify-start animate-in fade-in duration-300">
              <div className="flex gap-3 max-w-[80%] items-start">
                <Avatar size={32} icon={<LuBot />} className="bg-[#285d91]/10 !text-[#285d91] shrink-0 border border-[#285d91]/10" />
                <div className="flex flex-col space-y-1">
                  <span className="text-[9px] font-bold text-[var(--app-text-soft)] italic px-1">Processing...</span>
                  <div className="p-4 bg-[var(--app-surface-muted)]/60 border border-[var(--app-border)]/40 text-[var(--app-text)] rounded-2xl rounded-tl-none shadow-sm">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-[var(--app-text-soft)] font-medium">
                        {streamingText || "Assembling pipeline graphs..."}
                      </span>
                      <span className="w-1.5 h-1.5 rounded-full bg-[#285d91] animate-ping" />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Floating Input Dock Footer */}
        <div className="px-4 md:px-12 pb-6 pt-2 bg-gradient-to-t from-[var(--app-surface)] via-[var(--app-surface)] to-transparent border-t-0 z-30">
          <div className="bg-[var(--app-surface-muted)] border border-[var(--app-border)]/80 rounded-2xl p-2 shadow-lg transition-all focus-within:border-[#285d91]/50 focus-within:ring-4 focus-within:ring-[#285d91]/5 flex flex-col gap-2">
            
            {/* Real-time Dynamic Upload Preview Attachment Frame */}
            {attachedFile && (
              <div className="px-3 pt-2 pb-1 animate-in fade-in duration-200">
                <div className="inline-flex align-center gap-3 bg-[var(--app-surface)] border border-[var(--app-border)]/80 p-2.5 rounded-xl relative group shadow-sm max-w-xs">
                  {attachedFile.type?.startsWith("image/") ? (
                    <div className="w-10 h-10 rounded-lg overflow-hidden bg-black/5 shrink-0 border border-[var(--app-border)]/40">
                      <img src={attachedFile.url} alt="preview" className="w-full h-full object-cover" />
                    </div>
                  ) : (
                    <div className="w-10 h-10 rounded-lg bg-[#285d91]/10 text-[#285d91] flex items-center justify-center shrink-0">
                      <LuFileText size={20} />
                    </div>
                  )}
                  <Flex vertical className="min-w-0 pr-6 justify-center">
                    <Text className="text-xs font-bold truncate text-[var(--app-text)]">{attachedFile.name}</Text>
                    <Text className="text-[9px] font-bold text-[var(--app-text-soft)] uppercase tracking-wider">Ready to upload</Text>
                  </Flex>
                  <button 
                    onClick={() => setAttachedFile(null)} 
                    className="absolute -top-1.5 -right-1.5 w-5 h-5 bg-red-500 text-white rounded-full flex items-center justify-center hover:bg-red-600 transition-colors shadow-sm cursor-pointer"
                  >
                    <FiX size={11} />
                  </button>
                </div>
              </div>
            )}

            <Flex align="center" justify="space-between" className="gap-1">
              
              {/* Media Upload Node Trigger Trigger */}
              <Upload
                beforeUpload={handleBeforeUpload}
                showUploadList={false}
                accept="image/*,.pdf,.doc,.docx,.xls,.xlsx,.txt"
                disabled={!agent || wsStatus !== "open"}
              >
                <Tooltip title="Share media logs" placement="topLeft">
                  <Button
                    type="text"
                    disabled={!agent || wsStatus !== "open"}
                    icon={<LuPaperclip className="text-base text-[var(--app-text-soft)]" />}
                    className="hover:bg-[var(--app-hover)] !rounded-xl w-9 h-9 flex items-center justify-center transition-colors"
                  />
                </Tooltip>
              </Upload>

              <Input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={agent ? `Message ${agent.name}...` : "Choose an operational agent node..."}
                disabled={!agent || wsStatus !== "open"}
                bordered={false}
                className="w-full !py-2.5 !px-2 !bg-transparent !font-semibold !text-xs md:!text-sm !text-[var(--app-text)] !placeholder:text-[var(--app-text-soft)]/70 focus:outline-none"
              />
              
              <Tooltip title="Press Enter to send" placement="topRight">
                <button
                  onClick={handleSend}
                  disabled={!agent || (!input.trim() && !attachedFile) || wsStatus !== "open"}
                  className="w-9 h-9 bg-[#285d91] text-white rounded-xl flex items-center justify-center hover:bg-[#1e4873] active:scale-95 disabled:opacity-20 disabled:hover:scale-100 disabled:bg-[var(--app-text-soft)]/20 transition-all shrink-0 shadow-md shadow-blue-900/10"
                >
                  <FiSend size={15} />
                </button>
              </Tooltip>
            </Flex>
          </div>
        </div> 
      </Flex>

      {/* Drawer Thread History Component */}
      <Drawer
        title={
          <Flex align="center" justify="space-between" className="w-full">
            <Title level={5} className="!m-0 !text-[#285d91] !font-black uppercase tracking-wider text-[11px]">Thread Terminal</Title>
            <Button 
              type="text" 
              icon={<LuPlus />} 
              onClick={() => { setAgent(null); setCurrentSessionId(null); setMessages([]); setHistoryDrawerOpen(false); }} 
              className="text-[#285d91] hover:bg-[var(--app-active-bg)] !rounded-xl w-8 h-8 flex items-center justify-center"
            />
          </Flex>
        }
        placement="right"
        onClose={() => setHistoryDrawerOpen(false)}
        open={historyDrawerOpen}
        width={340}
        closeIcon={null}
        styles={{
          body: { padding: '16px', background: 'var(--app-surface)' },
          header: { borderBottom: '1px solid var(--app-border)/40', padding: '18px 16px' }
        }}
      >
        <div className="space-y-4 h-full flex flex-col">
          <Input 
            prefix={<LuSearch className="text-[var(--app-text-soft)]" />}
            placeholder="Search operational logs..."
            className="!rounded-xl !bg-[var(--app-surface-muted)] !border-none !h-9 font-semibold text-xs text-[var(--app-text)] placeholder:text-[var(--app-text-soft)]"
          />

          <div className="flex-1 overflow-y-auto space-y-2.5 custom-scrollbar pr-1">
            {sessions.length > 0 ? (
              sessions.map((s) => {
                const isActiveSession = currentSessionId === s.id; 
                return (
                  <div 
                    key={s.id} 
                    onClick={() => loadSession(s)}
                    className={`group relative p-3.5 rounded-xl cursor-pointer transition-all border ${
                      isActiveSession 
                        ? "bg-[#285d91] text-white shadow-md border-transparent" 
                        : "bg-[var(--app-surface-muted)] hover:bg-[var(--app-hover)] text-[var(--app-text)] border-[var(--app-border)]/40"
                    }`}
                  >
                    <div className="flex justify-between items-start gap-2 mb-1">
                      <Text className={`font-bold text-xs block truncate flex-1 ${isActiveSession ? "text-white font-extrabold" : "text-[var(--app-text)]"}`}>
                        {s.title}
                      </Text>
                      <FiTrash2 
                        onClick={(e) => deleteSession(e, s.id)}
                        className={`opacity-0 group-hover:opacity-100 transition-opacity text-xs shrink-0 ${isActiveSession ? "text-white/60 hover:text-white" : "text-[var(--app-text-soft)] hover:text-red-500"}`} 
                      />
                    </div>
                    <div className="flex justify-between items-center mt-3">
                      <span className={`text-[10px] font-semibold opacity-60 ${isActiveSession ? "text-white/80" : "text-[var(--app-text-muted)]"}`}>
                        {new Date(s.created_at).toLocaleDateString()}
                      </span>
                      <div className={`px-2 py-0.5 rounded text-[8px] font-extrabold uppercase tracking-widest ${
                        isActiveSession ? "bg-white/20 text-white" : "bg-[var(--app-active-bg)] text-[var(--app-text-soft)]"
                      }`}>
                        {s.message_count} frames
                      </div>
                    </div>
                  </div>
                );
              })
            ) : (
              <Flex vertical align="center" justify="center" className="h-full py-10 opacity-30 text-center">
                <LuHistory size={24} className="text-[#285d91] mb-2" />
                <Text className="font-bold text-[9px] uppercase tracking-widest text-[var(--app-text-muted)]">No active threads</Text>
              </Flex>
            )}
          </div>
        </div>
      </Drawer>

      <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar {
          width: 4px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: var(--app-border);
          border-radius: 10px;
        }
        .bg-dots-pattern {
          background-image: radial-gradient(var(--app-border) 1px, transparent 1px);
          background-size: 24px 24px;
          background-repeat: repeat;
        }
        .dynamic-img-render {
          transition: transform 0.2s ease-in-out;
        }
        .dynamic-img-render:hover {
          transform: scale(1.02);
        }
      `}</style>
    </div>
  );
}