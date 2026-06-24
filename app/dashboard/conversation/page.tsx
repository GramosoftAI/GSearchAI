"use client";

import { Flex, Typography, Button, Input, Tooltip, Avatar, Drawer, Grid, Upload, message, Spin, Table, Dropdown } from "antd";
import React, { useState, useRef, useEffect, useCallback } from "react";
import { LuBot, LuHistory, LuSearch, LuPlus, LuPaperclip, LuFileText, LuDownload, LuBookOpen, LuBell, LuSettings } from "react-icons/lu";
import { FaBrain } from "react-icons/fa";
import {
  FiUser,
  FiSend,
  FiMoreVertical,
  FiTrash2,
  FiX,
  FiCopy,
  FiEdit2,
  FiThumbsUp,
  FiThumbsDown,
  FiUpload,
  FiRotateCw,
  FiMoreHorizontal,
  FiMic,
  FiMenu,
} from "react-icons/fi";
import { MdBarChart as MdBarChartIcon } from "react-icons/md";
import { PiGraphLight } from "react-icons/pi";
import { useSession } from "next-auth/react";
import { getCookie } from "../../config/cookies";
import { AUTH_COOKIE_KEY, API_BASE_URL } from "../../config/config";
import AgentList from "../../components/ui/AgentList";
import useAxios from "../../hooks/useAxios";
import { useStore } from "../../hooks/useStore";
import type { Agent } from "../../components/ui/type";
import type { UploadFile } from "antd";
import { Switch } from "antd";
import { marked } from "marked";

const { Text, Title } = Typography;

// ─── Types ───────────────────────────────────────────────────────────────────
type SourceMetadata = {
  id: string;
  chunk_id?: string;
  score?: number;
  position?: number;
  reason?: string;
  source: string;
  kb_id: string;
  content_type?: 'parsed' | 'original';
  s3_path?: string;
  parsed_path?: string;
  text?: string;
};

type Message = {
  role: "user" | "assistant";
  content: string;
  confidence?: number;
  nodes?: number;
  timestamp?: string;
  message_count?: number;
  sources?: SourceMetadata[];
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

async function fetchAgentSources(agentId: string): Promise<any[]> {
  try {
    const res = await fetch(`${API_BASE_URL}/knowledge-bases/agents/${agentId}?limit=100&offset=0`, {
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(`${res.status}`);
    const result = await res.json();
    const data = result.data ?? result;
    return Array.isArray(data)
      ? data
      : Array.isArray(data?.sources)
        ? data.sources
        : Array.isArray(data?.kbs)
          ? data.kbs
          : [];
  } catch (e) {
    console.error("fetchAgentSources failed:", e);
    return [];
  }
}


async function getFilePreview(kb_id: string): Promise<string> {
  const response = await fetch(
    `${API_BASE_URL}/files/${kb_id}/preview`,
    {
      headers: {
        Authorization: `Bearer ${getCookie(AUTH_COOKIE_KEY)}`,
      },
    }
  );

  if (!response.ok) {
    const error = new Error("File preview failed") as any;
    error.status = response.status;
    throw error;
  }

  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

async function getCleanTextContent(kb_id: string): Promise<string> {
  const response = await fetch(
    `${API_BASE_URL}/files/${kb_id}/content`,
    {
      headers: {
        Authorization: `Bearer ${getCookie(AUTH_COOKIE_KEY)}`,
      },
    }
  );

  if (!response.ok) {
    const error = new Error("Clean text content retrieval failed") as any;
    error.status = response.status;
    throw error;
  }

  const data = await response.json();
  if (data && data.success && typeof data.content === "string") {
    return data.content;
  }
  return "";
}

function getFileName(sourceUrlOrName: string): string {
  try {
    if (sourceUrlOrName.startsWith("http://") || sourceUrlOrName.startsWith("https://")) {
      const url = new URL(sourceUrlOrName);
      const pathname = url.pathname;
      return pathname.substring(pathname.lastIndexOf('/') + 1) || sourceUrlOrName;
    }
    const cleanPath = sourceUrlOrName.replace(/\\/g, '/');
    return cleanPath.substring(cleanPath.lastIndexOf('/') + 1) || sourceUrlOrName;
  } catch {
    return sourceUrlOrName;
  }
}

// Extract source references from answer text to filter backend sources
function extractCitedFilenames(text: string): string[] {
  const regex = /(?:\[Source:\s*|\(Source:\s*)([^\]\)]+)[\]\)]/gi;
  const filenames = new Set<string>();
  let match;
  while ((match = regex.exec(text)) !== null) {
    let sourceStr = match[1].trim();
    // Extract anything that looks like a filename (e.g. file.pdf, file name.docx)
    const fileMatches = sourceStr.match(/[a-zA-Z0-9_\\-\\s]+\\.[a-zA-Z0-9]+/g);
    if (fileMatches && fileMatches.length > 0) {
      fileMatches.forEach(f => filenames.add(getFileName(f.trim()).toLowerCase()));
    } else {
      if (sourceStr.includes(" - Position")) {
        sourceStr = sourceStr.split(" - Position")[0].trim();
      }
      filenames.add(getFileName(sourceStr).toLowerCase());
    }
  }
  return Array.from(filenames);
}

function cleanAndExtractSources(content: string, existingSources?: SourceMetadata[]): { cleanedContent: string, sources: SourceMetadata[] } {
  if (!content) return { cleanedContent: "", sources: [] };

  const citedFilenames = extractCitedFilenames(content);

  const cleanedContent = content
    .replace(/(?:\[Source:\s*.+?\]|\(Source:\s*.+?\))/g, "")
    .trim();

  let finalSources: SourceMetadata[] = existingSources && existingSources.length > 0 ? [...existingSources] : [];

  if (finalSources.length === 0 && citedFilenames.length > 0) {
    finalSources = citedFilenames.map(name => ({
      id: '',
      source: name,
      kb_id: '',
    } as SourceMetadata));
  }

  return { cleanedContent, sources: finalSources };
}

type AgentListResponse = {
  data?: {
    agents?: Agent[];
  };
};

const GragLogoAvatar = ({ size = 32 }: { size?: number }) => {
  return (
    <div 
      className="rounded-xl flex items-center justify-center bg-[#285d91] text-white shrink-0 border border-[#285d91]/20 shadow-none font-bold"
      style={{ width: `${size}px`, height: `${size}px` }}
    >
      <FaBrain size={size * 0.55} />
    </div>
  );
};

export default function ChatPlaygroundPage() {
  const [agent, setAgent] = useState<{ id: string; name: string } | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<any>([]);
  const { data: sessionData } = useSession();
  const [userName, setUserName] = useState("Srivishnus");

  useEffect(() => {
    const storedName = localStorage.getItem("userName");
    if (storedName) {
      setUserName(storedName);
    } else if (sessionData?.user?.name) {
      setUserName(sessionData.user.name);
    }
  }, [sessionData]);
  const [desktopSidebarOpen, setDesktopSidebarOpen] = useState(true);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
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
  const [isEnabled, setIsEnabled] = useState(true);
  const wsSourcesRef = useRef<SourceMetadata[]>([]);
  const currentSessionIdRef = useRef<string | null>(null);
  const activeQuerySessionIdRef = useRef<string | null>(null);
  const [initialLoadDone, setInitialLoadDone] = useState(false);
  const [shouldLoadLatestOnFetch, setShouldLoadLatestOnFetch] = useState(false);

  // ─── IPPO ADD PANNA VENDIYA STATES ───────────────────────────────────
  const [editingMessageIndex, setEditingMessageIndex] = useState<number | null>(null);
  const [tempEditText, setTempEditText] = useState("");
  // File Upload State Tracker
  const [attachedFile, setAttachedFile] = useState<UploadFile | null>(null);


  // Left Drawer Sources States
  const [isSourcesDrawerOpen, setIsSourcesDrawerOpen] = useState(false);
  const [activeSources, setActiveSources] = useState<SourceMetadata[]>([]);
  const [agentSources, setAgentSources] = useState<any[]>([]);
  const [selectedSourceForPreview, setSelectedSourceForPreview] = useState<SourceMetadata | null>(null);
  const [sourcesDrawerPreviewUrl, setSourcesDrawerPreviewUrl] = useState("");
  const [sourcesDrawerPreviewType, setSourcesDrawerPreviewType] = useState<"pdf" | "csv" | "excel" | "other" | "image">("other");
  const [sourcesDrawerCsvData, setSourcesDrawerCsvData] = useState<string[][]>([]);
  const [sourcesDrawerPreviewLoading, setSourcesDrawerPreviewLoading] = useState(false);

  // New states for parsed previews and Excel rendering
  const [sourcesDrawerPreviewTab, setSourcesDrawerPreviewTab] = useState<"parsed" | "original">("original");
  const [parsedTextContent, setParsedTextContent] = useState("");
  const [parsedTextLoading, setParsedTextLoading] = useState(false);
  const [excelSheets, setExcelSheets] = useState<{ [sheetName: string]: string[][] }>({});
  const [excelSheetNames, setExcelSheetNames] = useState<string[]>([]);
  const [activeExcelSheet, setActiveExcelSheet] = useState<string>("");

  const resetChatStates = () => {
    setIsTyping(false);
    setStreamingText("");
    streamingTextRef.current = "";
    setAttachedFile(null);
    setEditingMessageIndex(null);
    setTempEditText("");
    setIsSourcesDrawerOpen(false);
    setActiveSources([]);
    setSelectedSourceForPreview(null);
    activeQuerySessionIdRef.current = null;
  };

  useEffect(() => {
    currentSessionIdRef.current = currentSessionId;
  }, [currentSessionId]);

  function mapAgentsToList(agents: Agent[]) {
    return agents.map((agent) => ({
      id: agent.id,
      name: agent.name,
      status: agent.is_active ? "active" : "draft",
    }));
  }

  // ─── Persistence Logic ──────────────────────────────────────────────────────
  useEffect(() => {
    getAgents(undefined, async (payload) => {
      const agents = payload?.data?.agents ?? [];
      setBotsCache(agents);
      const list = mapAgentsToList(agents);
      setAgentList(list);

      // Parse URL parameters on load
      if (typeof window !== "undefined") {
        const params = new URLSearchParams(window.location.search);
        const urlAgentId = params.get("agentId") || params.get("agent_id");
        const urlSessionId = params.get("sessionId") || params.get("session_id");

        if (urlAgentId) {
          const matchedAgent = agents.find(a => a.id === urlAgentId);
          if (matchedAgent) {
            setAgent({ id: matchedAgent.id, name: matchedAgent.name });

            // Fetch sessions for this agent
            const data = await fetchSessions(matchedAgent);
            setSessions(data);

            if (urlSessionId) {
              const matchedSession = data.find(s => s.id === urlSessionId);
              if (matchedSession) {
                setCurrentSessionId(matchedSession.id);
                const mappedMessages = (matchedSession.messages || []).map((msg: any) => {
                  const { cleanedContent, sources } = cleanAndExtractSources(msg.content, msg.sources);
                  return {
                    role: msg.role,
                    content: cleanedContent,
                    file: msg.file,
                    sources: sources.length > 0 ? sources : undefined,
                    timestamp: msg.created_at
                      ? new Date(msg.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                      : new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
                  };
                });
                setMessages(mappedMessages);
              }
            } else {
              // Start a new session (show "New chat" by default on agent load)
              const newSessionId = `session_${Date.now()}`;
              const newSession: any = {
                id: newSessionId,
                agentId: matchedAgent.id,
                agentName: matchedAgent.name,
                messages: [],
                updatedAt: Date.now()
              };
              setSessions([newSession]);
              setCurrentSessionId(newSessionId);
              setMessages([]);
            }
            setInitialLoadDone(true);
            return;
          }
        }
      }
      setInitialLoadDone(true);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!agent?.id) return;
    if (!initialLoadDone) return;

    (async () => {
      const data = await fetchSessions(agent);
      setSessions(prev => {
        const tempSessions = prev.filter(s => s.id.startsWith("session_") && (s.agentId === agent.id || s.agent_id === agent.id));
        const filteredData = data.filter(s => !tempSessions.some(temp => temp.id === s.id));
        return [...tempSessions, ...filteredData];
      });

      if (shouldLoadLatestOnFetch) {
        setShouldLoadLatestOnFetch(false);
        // Always start with a new empty session when selecting/switching agent
        startNewChat(agent, data);
      }
    })();

    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    };
  }, [agent?.id, initialLoadDone, shouldLoadLatestOnFetch]);

  // Fetch agent sources whenever the agent changes
  useEffect(() => {
    if (!agent?.id) {
      setAgentSources([]);
      return;
    }
    (async () => {
      const sources = await fetchAgentSources(agent.id);
      setAgentSources(sources);
    })();
  }, [agent?.id]);

  // URL Search Parameters Syncer Effect
  useEffect(() => {
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      if (agent?.id) {
        url.searchParams.set("agentId", agent.id);
      } else {
        url.searchParams.delete("agentId");
      }

      if (currentSessionId) {
        url.searchParams.set("sessionId", currentSessionId);
      } else {
        url.searchParams.delete("sessionId");
      }

      window.history.replaceState({}, "", url.toString());
    }
  }, [agent?.id, currentSessionId]);

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
      if (ws.current !== socket) return;
      setWsStatus("open");
      console.log("opend");
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };

    socket.onmessage = (event) => {
      if (ws.current !== socket) return;
      if (activeQuerySessionIdRef.current !== currentSessionIdRef.current) return;
      const rawData = String(event.data);
      console.log("onmessage");
      if (!rawData.startsWith("{")) { //&& !rawData.startsWith("[")) rawData.length === 1 || (
        streamingTextRef.current += rawData;
        setStreamingText(streamingTextRef.current);
        setIsTyping(true);
        return;
      }

      try {
        const data = JSON.parse(rawData);

        // Accumulate sources from any WebSocket packet
        let incomingSources: SourceMetadata[] = [];
        if (Array.isArray(data.sources)) {
          incomingSources = data.sources;
        } else if (data.metadata && Array.isArray(data.metadata.sources)) {
          incomingSources = data.metadata.sources;
        } else if (data.type === "metadata" && Array.isArray(data.metadata)) {
          incomingSources = data.metadata;
        } else if (data.type === "metadata" && data.sources) {
          incomingSources = Array.isArray(data.sources) ? data.sources : [data.sources];
        }

        if (incomingSources.length > 0) {
          incomingSources.forEach((src) => {
            if (src && src.kb_id && !wsSourcesRef.current.some(s => s.kb_id === src.kb_id)) {
              wsSourcesRef.current.push(src);
            }
          });
        }

        if (data.type === "metadata") return;

        if (data.type === "done") {
          const accumulated = streamingTextRef.current;
          console.log("DELTA:", accumulated);
          const textContent = accumulated
            .replace(/<think>[\s\S]*?<\/think>/g, "")
            .replace(/(?:\[Source:\s*.+?\]|\(Source:\s*.+?\))/g, "")
            .trim();

          const citedFilenames = extractCitedFilenames(accumulated);
          let finalSources: SourceMetadata[] = [];
          if (wsSourcesRef.current.length > 0) {
            // Filter wsSourcesRef: keep it if the AI mentioned the filename ANYWHERE, or if it matched the extraction
            const matchedSources = wsSourcesRef.current.filter(src => {
              const srcName = getFileName(src.source).toLowerCase();
              const inText = accumulated.toLowerCase().includes(srcName);
              const inCitations = citedFilenames.some(cf => srcName.includes(cf) || cf.includes(srcName));
              return inText || inCitations;
            });
            
            // If we found specific matches, use them. Else, fallback to all backend sources.
            if (matchedSources.length > 0) {
              finalSources = matchedSources;
            } else {
              finalSources = [...wsSourcesRef.current];
            }
          } else if (citedFilenames.length > 0) {
            // Fallback: create mock sources from parsed names if backend didn't send metadata
            finalSources = citedFilenames.map(name => ({
              id: '',
              source: name,
              kb_id: '',
            } as SourceMetadata));
          }

          if (accumulated) {
            setMessages((prev: any) => [
              ...prev,
              {
                role: "assistant",
                content: textContent,
                sources: finalSources.length > 0 ? finalSources : undefined,
                timestamp: new Date().toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                }),
              },
            ]);
          }
          streamingTextRef.current = "";
          wsSourcesRef.current = [];
          setStreamingText("");
          setIsTyping(false);
          activeQuerySessionIdRef.current = null;

          const backendSessionId = data.session_id || data.sessionId;
          if (backendSessionId) {
            setCurrentSessionId(backendSessionId);
            currentSessionIdRef.current = backendSessionId;
          }

          if (agent) {
            (async () => {
              const freshSessions = await fetchSessions(agent);
              setSessions(freshSessions);
              if (!backendSessionId && currentSessionIdRef.current && currentSessionIdRef.current.startsWith("session_") && freshSessions.length > 0) {
                setCurrentSessionId(freshSessions[0].id);
                currentSessionIdRef.current = freshSessions[0].id;
              }
            })();
          }
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
      if (ws.current !== socket) return;
      setWsStatus("closed");
      console.log("conlose");
      reconnectTimeoutRef.current = setTimeout(() => {
        if (agent?.id) {
          connectSocket();
        }
      }, 3000);
    };

    socket.onerror = () => {
      if (ws.current !== socket) return;
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

  const startNewChat = (selectedAgent: { id: string; name: string }, currentSessionsList?: ChatSession[]) => {
    const listToSearch = currentSessionsList || sessions;
    const existingEmptySession = listToSearch.find(s => 
      (s.agentId === selectedAgent.id || s.agent_id === selectedAgent.id) &&
      s.id.startsWith("session_") &&
      (!s.messages || s.messages.length === 0)
    );

    if (existingEmptySession) {
      loadSession(existingEmptySession);
      return;
    }

    if (isTyping) {
      connectWs();
    }
    resetChatStates();

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
    currentSessionIdRef.current = newSessionId;
    setMessages([]);
    setAgent(selectedAgent);
  };

  const loadSession = (session: ChatSession) => {
    if (isTyping) {
      connectWs();
    }
    resetChatStates();

    setCurrentSessionId(session.id);
    currentSessionIdRef.current = session.id;

    const mappedMessages = (session.messages || []).map((msg: any) => {
      const { cleanedContent, sources } = cleanAndExtractSources(msg.content, msg.sources);
      return {
        role: msg.role,
        content: cleanedContent,
        file: msg.file,
        sources: sources.length > 0 ? sources : undefined,
        timestamp: msg.created_at
          ? new Date(msg.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
          : new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
    });

    setMessages(mappedMessages);
    setAgent({
      id: session.agent_id || session.agentId,
      name: session.title || session.agentName
    });
    setMobileSidebarOpen(false);
  };

  const deleteSession = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    setSessions(prev => prev.filter(s => s.id !== id));
    if (currentSessionId === id) {
      setCurrentSessionId(null);
      currentSessionIdRef.current = null;
      setMessages([]);
      setAgent(null);
    }
  };

  const handleAgentChange = (id: string, name: string) => {
    resetChatStates();
    setAgent({ id, name });
    setShouldLoadLatestOnFetch(true);
  };

  const handleRegenerate = (index: number) => {
    if (wsStatus !== "open") {
      message.error("WebSocket link is not stable. Please wait.");
      return;
    }

    let userMessageIndex = -1;
    for (let j = index; j >= 0; j--) {
      if (messages[j].role === "user") {
        userMessageIndex = j;
        break;
      }
    }
    
    if (userMessageIndex === -1 || !agent?.id) return;
    
    activeQuerySessionIdRef.current = currentSessionId;
    
    const userMsg = messages[userMessageIndex];
    
    const updatedMessages = messages.slice(0, userMessageIndex + 1);
    setMessages(updatedMessages);
    
    ws.current?.send(JSON.stringify({
      query: userMsg.content,
      file: userMsg.file ? { name: userMsg.file.name, type: userMsg.file.type } : null,
      session_id: currentSessionId && !currentSessionId.startsWith("session_") ? currentSessionId : null
    }));
    
    wsSourcesRef.current = [];
    setStreamingText("");
    setIsTyping(true);
  };

  const handleShareSession = () => {
    if (!agent?.id || !currentSessionId) {
      message.warning("No active session to share.");
      return;
    }
    
    const shareUrl = `${window.location.origin}${window.location.pathname}?agentId=${agent.id}&sessionId=${currentSessionId}`;
    
    navigator.clipboard.writeText(shareUrl)
      .then(() => {
        message.success("Share link copied to clipboard!");
      })
      .catch((err) => {
        console.error("Failed to copy share link:", err);
        message.error("Failed to copy share link.");
      });
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

    const titleText = trimmed || (attachedFile ? attachedFile.name : "New Chat");
    const displayTitle = titleText.length > 30 ? titleText.slice(0, 30) + "..." : titleText;

    let targetSessionId = currentSessionId;
    if (!targetSessionId) {
      targetSessionId = `session_${Date.now()}`;
      const newSession: any = {
        id: targetSessionId,
        agentId: agent.id,
        agentName: agent.name,
        title: displayTitle,
        messages: [],
        updatedAt: Date.now()
      };
      setSessions(prev => [newSession, ...prev]);
      setCurrentSessionId(targetSessionId);
      currentSessionIdRef.current = targetSessionId;
    } else {
      setSessions(prev => {
        const exists = prev.some(s => s.id === targetSessionId);
        if (!exists) {
          const newSession: any = {
            id: targetSessionId,
            agentId: agent.id,
            agentName: agent.name,
            title: displayTitle,
            messages: [],
            updatedAt: Date.now()
          };
          return [newSession, ...prev];
        }
        return prev.map(s => {
          if (s.id === targetSessionId) {
            const hasNoTitle = !s.title || s.title === "Untitled Session";
            return {
              ...s,
              title: hasNoTitle ? displayTitle : s.title,
              updatedAt: Date.now()
            };
          }
          return s;
        });
      });
    }

    // Build payload structure containing optional file metrics
    let payloadFile: any = undefined;
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
      file: payloadFile ? { name: payloadFile.name, type: payloadFile.type } : null,
      session_id: targetSessionId && !targetSessionId.startsWith("session_") ? targetSessionId : null
    }));

    setInput("");
    setAttachedFile(null); // Clear dock frame tracking parameters
    streamingTextRef.current = "";
    wsSourcesRef.current = [];
    setStreamingText("");
    activeQuerySessionIdRef.current = targetSessionId;
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
      file: null,
      session_id: currentSessionId && !currentSessionId.startsWith("session_") ? currentSessionId : null
    }));

    wsSourcesRef.current = [];
    activeQuerySessionIdRef.current = currentSessionId;
    setIsTyping(true);
  };

  const cleanCompare = (name1: string, name2: string) => {
    const n1 = getFileName(name1).toLowerCase().replace(/[^a-z0-9.]/g, '');
    const n2 = getFileName(name2).toLowerCase().replace(/[^a-z0-9.]/g, '');
    if (!n1 || !n2) return false;
    return n1 === n2 || n1.includes(n2) || n2.includes(n1);
  };

  const enhanceSources = useCallback((sourcesToEnhance: SourceMetadata[], currentAgentSources: any[]) => {
    if (!sourcesToEnhance || sourcesToEnhance.length === 0) return [];
    return sourcesToEnhance.map(src => {
      if (src.kb_id) {
        const matched = currentAgentSources.find(as => 
          (as.id === src.kb_id || as.kb_id === src.kb_id) ||
          cleanCompare(as.name || as.source || "", src.source)
        );
        if (matched) {
          return {
            ...src,
            kb_id: src.kb_id || matched.id || matched.kb_id || "",
            s3_path: src.s3_path || matched.s3_path || "",
            parsed_path: src.parsed_path || matched.parsed_path || "",
            content_type: src.content_type || matched.content_type || "",
          };
        }
        return src;
      }
      
      const matched = currentAgentSources.find(as => 
        cleanCompare(as.name || as.source || "", src.source)
      );

      if (matched) {
        return {
          ...src,
          id: matched.id || src.id,
          kb_id: matched.id || matched.kb_id || "",
          s3_path: matched.s3_path || "",
          parsed_path: matched.parsed_path || "",
          content_type: matched.content_type || "",
        };
      }
      return src;
    });
  }, []);

  const handleOpenSourcesDrawer = async (sources: SourceMetadata[]) => {
    let currentSources = agentSources;
    if (agent?.id && currentSources.length === 0) {
      currentSources = await fetchAgentSources(agent.id);
      setAgentSources(currentSources);
    }
    const enhanced = enhanceSources(sources, currentSources);
    setActiveSources(enhanced);
    setIsSourcesDrawerOpen(true);
    if (enhanced.length > 0) {
      handleSelectSourceForPreview(enhanced[0]);
    }
  };

  const handleSelectSourceForPreview = async (source: SourceMetadata) => {
    setSelectedSourceForPreview(source);
    if (!source.kb_id) {
      return;
    }

    const nameForFallback = getFileName(source.source).toLowerCase();
    const isParsedType = source.content_type === "parsed" ||
      source.parsed_path !== undefined ||
      nameForFallback.endsWith(".pdf") ||
      nameForFallback.endsWith(".docx") ||
      nameForFallback.endsWith(".doc") ||
      nameForFallback.endsWith(".txt");

    // Set active tab default based on parsed capability
    const defaultTab = isParsedType ? "original" : "parsed";
    setSourcesDrawerPreviewTab(defaultTab);
    setParsedTextContent("");

    try {
      setSourcesDrawerPreviewLoading(true);
      setSourcesDrawerPreviewType("other");
      setSourcesDrawerCsvData([]);
      setExcelSheets({});
      setExcelSheetNames([]);
      setActiveExcelSheet("");
      if (sourcesDrawerPreviewUrl) {
        URL.revokeObjectURL(sourcesDrawerPreviewUrl);
      }
      setSourcesDrawerPreviewUrl("");

      // 1. If it is a parsed type, fetch clean text content
      if (isParsedType) {
        try {
          setParsedTextLoading(true);
          const cleanText = await getCleanTextContent(source.kb_id);
          setParsedTextContent(cleanText);
        } catch (err) {
          console.error("Clean text fetch error:", err);
          setParsedTextContent("Unable to load extracted text content.");
        } finally {
          setParsedTextLoading(false);
        }
      }

      // 2. Fetch binary preview file using Blob URL Strategy
      const blobUrl = await getFilePreview(source.kb_id);
      setSourcesDrawerPreviewUrl(blobUrl);

      const name = getFileName(source.source).toLowerCase();

      // Fetch blob to determine content type and parse binary spreadsheets
      const blobRes = await fetch(blobUrl);
      const blob = await blobRes.blob();
      const contentType = blob.type.toLowerCase();

      const isPDF = contentType.includes("pdf") || name.endsWith(".pdf");
      const isImage = contentType.includes("image/") || name.endsWith(".png") || name.endsWith(".jpg") || name.endsWith(".jpeg") || name.endsWith(".webp") || name.endsWith(".gif");
      const isCSV = contentType.includes("csv") || name.endsWith(".csv");
      const isExcel = contentType.includes("excel") || contentType.includes("spreadsheet") ||
        contentType.includes("vnd.ms-excel") || contentType.includes("vnd.openxmlformats-officedocument.spreadsheetml.sheet") ||
        name.endsWith(".xls") || name.endsWith(".xlsx");

      if (isPDF) {
        setSourcesDrawerPreviewType("pdf");
      } else if (isImage) {
        setSourcesDrawerPreviewType("image");
      } else if (isCSV || isExcel) {
        setSourcesDrawerPreviewType(isCSV ? "csv" : "excel");
        const arrayBuffer = await blob.arrayBuffer();
        const XLSX = await import("xlsx");
        const workbook = XLSX.read(arrayBuffer, { type: "array" });

        const sheetsData: { [sheetName: string]: string[][] } = {};
        workbook.SheetNames.forEach((sheetName) => {
          const worksheet = workbook.Sheets[sheetName];
          const jsonData = XLSX.utils.sheet_to_json<any[]>(worksheet, { header: 1 });
          sheetsData[sheetName] = jsonData.map((row: any) =>
            Array.isArray(row)
              ? row.map((cell) => (cell !== null && cell !== undefined ? String(cell) : ""))
              : []
          );
        });

        setExcelSheets(sheetsData);
        setExcelSheetNames(workbook.SheetNames);
        setActiveExcelSheet(workbook.SheetNames[0] || "");
      } else {
        setSourcesDrawerPreviewType("other");
      }
    } catch (error: any) {
      console.error("Preview error:", error);
      let errorMsg = "Unable to load document";
      if (error.status === 403) {
        errorMsg = "Permission denied";
      } else if (error.status === 404) {
        errorMsg = "File not found";
      }
      message.error(errorMsg);
    } finally {
      setSourcesDrawerPreviewLoading(false);
    }
  };

  const htmlContent = React.useMemo(() => {
    if (!parsedTextContent) return "";
    try {
      const markedObj = marked as any;
      return typeof markedObj === "function" ? markedObj(parsedTextContent) : markedObj.parse(parsedTextContent);
    } catch (e) {
      console.error(e);
      return parsedTextContent;
    }
  }, [parsedTextContent]);

  const renderSidebar = () => {
    return (
      <div className="w-full h-full flex flex-col bg-[var(--app-surface-muted)]/80 backdrop-blur-md overflow-hidden">
        {/* Syncing Status Switch on the top-left of the sidebar */}
        <div className="p-4 border-b border-[var(--app-border)]/40 flex items-center justify-between shrink-0 select-none bg-[var(--app-surface-muted)]">
          <Flex align="center" gap={6} className="min-w-0">
            <span className={`w-2 h-2 rounded-full shrink-0 ${wsStatus === "open" ? "bg-emerald-500 animate-pulse" : "bg-amber-500"}`} />
            <span className="text-[10px] font-black uppercase tracking-wider text-[var(--app-text-soft)] truncate">
              {wsStatus === "open" ? "LINK STABILIZED" : "SYNCING LINK CORE..."}
            </span>
          </Flex>
          <Switch
            size="small"
            checked={isEnabled}
            onChange={(checked) => {
              setIsEnabled(checked);
              console.log(checked);
            }}
            className="shrink-0"
          />
        </div>

        {/* Sidebar Top: Operational Node / AgentList */}
        <div className="p-4 border-b border-[var(--app-border)]/40 bg-[var(--app-surface-muted)]/50">
          <span className="text-[10px] font-extrabold uppercase tracking-widest text-[var(--app-text-soft)] block mb-2 opacity-80">
            Select Agent
          </span>
          <div className="w-full">
            <AgentList
              selectedId={agent?.id}
              onChange={handleAgentChange}
            />
          </div>
        </div>

        {/* New Chat Button */}
        <div className="px-4 py-3 shrink-0">
          <button
            onClick={() => {
              if (agent) {
                startNewChat(agent);
              } else {
                message.warning("Please select an agent node first.");
              }
              setMobileSidebarOpen(false);
            }}
            className="w-full flex items-center justify-center gap-2 border border-[var(--app-border)] hover:bg-[var(--app-hover)] text-[var(--app-text)] font-semibold rounded-xl py-2.5 transition-all text-xs cursor-pointer shadow-sm bg-[var(--app-surface)]"
          >
            <FiEdit2 size={13} className="text-[var(--app-text-soft)]" />
            <span>New chat</span>
          </button>
        </div>

        {/* Chats History Section */}
        <div className="flex-1 flex flex-col min-h-0 px-2">
          <div className="px-3 py-2 flex items-center justify-between">
            <span className="text-[10px] font-extrabold uppercase tracking-widest text-[var(--app-text-soft)] opacity-80">
              Chats
            </span>
            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-[var(--app-border)]/30 text-[var(--app-text-soft)]">
              {sessions.length} sessions
            </span>
          </div>

          <div className="flex-1 overflow-y-auto space-y-1 custom-scrollbar pr-1">
            {sessions.length > 0 ? (
              sessions.map((s) => {
                const isActiveSession = currentSessionId === s.id;
                return (
                  <div
                    key={s.id}
                    onClick={() => {
                      loadSession(s);
                      setMobileSidebarOpen(false);
                    }}
                    className={`group relative p-2.5 rounded-xl cursor-pointer transition-all border flex items-center justify-between ${
                      isActiveSession
                        ? "bg-[#285d91]/15 text-[#285d91] border-transparent font-extrabold"
                        : "bg-transparent hover:bg-[var(--app-hover)] text-[var(--app-text-soft)] border-transparent"
                    }`}
                  >
                    <div className="flex items-center gap-2.5 min-w-0 flex-1">
                      <span className="text-sm shrink-0">💬</span>
                      <span className="text-xs truncate block pr-2">
                        {s.title || "Untitled Session"}
                      </span>
                    </div>

                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className="text-[9px] opacity-65 font-bold group-hover:hidden">
                        {s.message_count || 0}
                      </span>
                      <FiTrash2
                        onClick={(e) => {
                          e.stopPropagation();
                          deleteSession(e, s.id);
                        }}
                        className="opacity-0 group-hover:opacity-100 transition-opacity text-xs text-[var(--app-text-soft)] hover:text-red-500 cursor-pointer"
                      />
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="py-12 text-center opacity-40">
                <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--app-text-muted)]">No active chats</span>
              </div>
            )}
          </div>
        </div>


      </div>
    );
  };

  const handleKeyDown = (e: any) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    } else if (e.key === "ArrowUp" && !input) {
      e.preventDefault();
      const lastUserMsg = [...messages].reverse().find(m => m.role === "user");
      if (lastUserMsg) {
        setInput(lastUserMsg.content);
      }
    }
  };

  return (
    <div className="h-[calc(100vh-96px)] w-full flex bg-[var(--app-surface)] antialiased selection:bg-[#285d91]/20 overflow-hidden relative">
      {/* Desktop Left Sidebar */}
      {screen.md && (
        <div 
          className="h-full border-r border-[var(--app-border)]/40 flex flex-col bg-[var(--app-surface-muted)] shrink-0 transition-all duration-300 overflow-hidden"
          style={{ width: desktopSidebarOpen ? "260px" : "0px", borderRightWidth: desktopSidebarOpen ? "1px" : "0px" }}
        >
          {renderSidebar()}
        </div>
      )}

      {/* Mobile Left Sidebar Drawer */}
      {!screen.md && (
        <Drawer
          placement="left"
          onClose={() => setMobileSidebarOpen(false)}
          open={mobileSidebarOpen}
          style={{ width: 260 }}
          closeIcon={null}
          styles={{
            body: { padding: 0, background: 'var(--app-surface-muted)', height: '100%' }
          }}
        >
          {renderSidebar()}
        </Drawer>
      )}

      {/* Main Chat Container */}
      <Flex vertical className="flex-1 h-full overflow-hidden relative bg-transparent">

        {/* Top Header */}
        <div className="w-full px-4 md:px-8 py-3 border-b border-[var(--app-border)]/40 backdrop-blur-md bg-[var(--app-surface)]/50 sticky top-0 z-40 transition-all shrink-0">
          <Flex justify="space-between" align="center" className="gap-2 w-full">
            
            {/* Left side: Hamburger and Logo */}
            <Flex align="center" gap={4} className="min-w-0">
              <Button 
                type="text" 
                icon={<FiMenu className="text-lg text-[var(--app-text-soft)]" />} 
                onClick={() => {
                  if (screen.md) {
                    setDesktopSidebarOpen(!desktopSidebarOpen);
                  } else {
                    setMobileSidebarOpen(!mobileSidebarOpen);
                  }
                }}
                className="hover:bg-[var(--app-hover)] !rounded-xl w-9 h-9 flex items-center justify-center transition-colors"
              />
              
              <Flex align="center" gap={8} className="select-none ml-1 shrink-0">
                <span className="font-extrabold text-sm tracking-tight text-[var(--app-text)] hidden xs:inline shrink-0">
                  AI Assist
                </span>
                {agent && (
                  <span className="text-[10px] bg-[#285d91]/10 text-[#285d91] font-bold px-2 py-0.5 rounded-lg border border-[#285d91]/10 ml-2 hidden sm:inline-block max-w-[120px] truncate">
                    {agent.name}
                  </span>
                )}
              </Flex>
            </Flex>

          </Flex>
        </div>

        {/* Conversation Stream */}
        <div className="flex-1 overflow-y-auto px-4 md:px-12 py-6 md:py-10 space-y-6 custom-scrollbar bg-dots-pattern">
          {messages.length === 0 && !isTyping && (
            <Flex vertical align="center" justify="center" className="h-full select-none my-auto">
              <h1 className="m-0 text-[var(--app-text)] font-extrabold text-xl sm:text-2xl md:text-4xl tracking-tight text-center max-w-xl px-4 animate-in fade-in duration-500">
                Hello {userName}! What can I do for you?
              </h1>
            </Flex>
          )}

          {messages.map((msg: any, i: any) => {
            const isUser = msg.role === "user";
            const hasImage = msg.file?.type?.startsWith("image/");
            const hasDoc = msg.file && !hasImage;

            return (
              <div key={i} className={`flex w-full ${isUser ? "justify-end" : "justify-start"} animate-in fade-in slide-in-from-bottom-2 duration-300`}>
                <div className={`flex gap-3 transition-all duration-300 ${editingMessageIndex === i ? "w-full max-w-[95%] md:max-w-[85%]" : "max-w-[88%] md:max-w-[75%]"} ${isUser ? "flex-row-reverse" : "flex-row"}`}>
                  {isUser ? (
                    <Avatar
                      size={32}
                      icon={<FiUser />}
                      className="bg-emerald-500/10 !text-emerald-600 shadow-none shrink-0 border border-current/10 font-bold"
                    />
                  ) : (
                    <GragLogoAvatar size={32} />
                  )}

                  <div className={`flex flex-col space-y-1 ${editingMessageIndex === i ? "flex-1 min-w-0" : ""}`}>
                    <span className={`text-[9px] font-bold text-[var(--app-text-soft)] px-1 ${isUser ? "text-right" : "text-left"}`}>
                      {msg.timestamp}
                    </span>

                    {/* <div className={`p-4 md:p-5 rounded-2xl transition-all duration-200 shadow-sm border ${ */}
                    <div
                      className={`group relative p-4 md:p-5 rounded-2xl transition-all duration-200 shadow-sm border ${isUser
                          ? "bg-[#285d91] text-white rounded-tr-none border-[#285d91]/20 font-medium"
                          : "bg-[var(--app-surface-muted)] text-[var(--app-text)] rounded-tl-none border-[var(--app-border)]/40 font-normal"
                        }`}
                    >
                      {/* Dynamic File Rendering UI Framework */}
                      <div className={`absolute -bottom-10 ${isUser ? "right-0" : "left-0"} opacity-0 group-hover:opacity-100 transition-all duration-200 flex gap-2 z-20`}>
                          <Tooltip title="Copy message" placement="bottom">
                            <button
                              onClick={() => handleCopyMessage(msg.content)}
                              className="text-[var(--app-text)] p-2 cursor-pointer font-bold transition-colors hover:opacity-80"
                            >
                              <FiCopy size={16} strokeWidth={2} />
                            </button>
                          </Tooltip>

                          {isUser ? (
                            <Tooltip title="Edit message" placement="bottom">
                              <button
                                onClick={() => handleEditMessage(i, msg.content)}
                                className="text-[var(--app-text)] font-bold p-2 cursor-pointer transition-colors hover:opacity-80"
                              >
                                <FiEdit2 size={16} strokeWidth={2} />
                              </button>
                            </Tooltip>
                          ) : (
                            <>
                              <Tooltip title="Helpful" placement="bottom">
                                <button className="text-[var(--app-text)] font-bold p-2 cursor-pointer transition-colors hover:opacity-80">
                                  <FiThumbsUp size={16} strokeWidth={2} />
                                </button>
                              </Tooltip>
                              <Tooltip title="Not helpful" placement="bottom">
                                <button className="text-[var(--app-text)] font-bold p-2 cursor-pointer transition-colors hover:opacity-80">
                                  <FiThumbsDown size={16} strokeWidth={2} />
                                </button>
                              </Tooltip>
                              {/* <Tooltip title="Share" placement="bottom">
                                <button 
                                  onClick={handleShareSession}
                                  className="text-[var(--app-text)] font-bold p-2 cursor-pointer transition-colors hover:opacity-80"
                                >
                                  <FiUpload size={16} strokeWidth={2} />
                                </button>
                              </Tooltip> */}
                              <Tooltip title="Regenerate" placement="bottom">
                                <button 
                                  onClick={() => handleRegenerate(i)}
                                  className="text-[var(--app-text)] font-bold p-2 cursor-pointer transition-colors hover:opacity-80"
                                >
                                  <FiRotateCw size={16} strokeWidth={2} />
                                </button>
                              </Tooltip>
                              {msg.sources && msg.sources.length > 0 && (
                                <Tooltip title="View sources" placement="bottom">
                                  <button onClick={() => handleOpenSourcesDrawer(msg.sources)} className="text-[var(--app-text)] font-bold p-2 cursor-pointer transition-colors hover:opacity-80">
                                    <LuBookOpen size={16} strokeWidth={2} />
                                  </button>
                                </Tooltip>
                              )}
                            </>
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
                            <div className="flex flex-col gap-3 my-2 animate-in fade-in duration-200">
                              <Input.TextArea
                                value={tempEditText}
                                onChange={(e) => setTempEditText(e.target.value)}
                                autoSize={{ minRows: 2, maxRows: 6 }}
                                className="!bg-transparent !text-white !border-none !shadow-none focus:!shadow-none focus:!outline-none hover:!border-none transition-all resize-none"
                                placeholder="Edit your message..."
                                style={{ WebkitTextFillColor: "white", color: "white", fontWeight: "bold", boxShadow: "none" }}
                              />
                              <div className="flex gap-2 justify-end">
                                <Button
                                  className="!bg-transparent rounded-full !border-none hover:!bg-white/10 px-4 h-9 font-medium transition-all"
                                  style={{ WebkitTextFillColor: "rgba(255,255,255,0.8)", fontWeight: "normal" ,boxShadow: "none",borderRadius: "9999px"}}
                                  onClick={() => setEditingMessageIndex(null)}
                                >
                                  Cancel
                                </Button>
                                <Button 
                                  type="primary" 
                                  className="!rounded-full !bg-[var(--neutral)] hover:opacity-90 !border-none px-5 h-9 font-semibold shadow-sm transition-all"
                                  style={{ WebkitTextFillColor: "black", fontWeight: "bold", boxShadow: "none", borderRadius: "9999px" }}
                                  onClick={() => handleSaveEdit(i)}
                                >
                                  Send
                                </Button>
                              </div>
                            </div>
                          ) : (
                            // Normal Display Mode
                            <span className="whitespace-pre-wrap mr-2 leading-7">{msg.content}</span>
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
                <GragLogoAvatar size={32} />
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
        <div className="px-4 md:px-12 pb-4 pt-2 bg-gradient-to-t from-[var(--app-surface)] via-[var(--app-surface)] to-transparent border-t-0 z-30 shrink-0">
          <div className="bg-[var(--app-surface-muted)] border border-[var(--app-border)]/80 rounded-2xl p-3 shadow-lg transition-all focus-within:border-[#285d91]/50 focus-within:ring-4 focus-within:ring-[#285d91]/5 flex flex-col gap-2">
            
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

            {/* Input Row (Single line layout) */}
            <Flex align="center" gap={8} className="w-full">
              {/* Media Upload Node Trigger */}
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

              {/* Input Text Area */}
              <div className="flex-1 min-w-0">
                <Input.TextArea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Type a message..."
                  disabled={!agent || wsStatus !== "open"}
                  variant="borderless"
                  autoSize={{ minRows: 1, maxRows: 6 }}
                  className="w-full !p-1 !bg-transparent !font-semibold !text-xs md:!text-sm !text-[var(--app-text)] !placeholder:text-[var(--app-text-soft)]/50 focus:outline-none resize-none align-middle"
                />
              </div>

              {/* Send Button */}
              <Tooltip title="Press Enter to send" placement="topRight">
                <button
                  onClick={handleSend}
                  disabled={!agent || (!input.trim() && !attachedFile) || wsStatus !== "open"}
                  className="w-8 h-8 bg-[#285d91] text-white rounded-lg flex items-center justify-center hover:bg-[#1e4873] active:scale-95 disabled:opacity-20 disabled:hover:scale-100 disabled:bg-[var(--app-text-soft)]/20 transition-all shrink-0 shadow-md shadow-blue-900/10 cursor-pointer"
                >
                  <FiSend size={13} />
                </button>
              </Tooltip>
            </Flex>
          </div>
          
          {/* Powered by Leena AI */}
          {/* <div className="text-center mt-2.5">
            <Text className="text-[10px] text-[var(--app-text-soft)]/75 font-semibold select-none">
              Powered by Leena AI
            </Text>
          </div> */}
        </div>
      </Flex>

      <Drawer
        title={
          <Flex align="center" gap={8}>
            <LuBookOpen className="text-[#285d91]" size={18} />
            <span className="font-extrabold text-sm text-[var(--app-text)]">Source Documents</span>
          </Flex>
        }
        placement="top"
        onClose={() => {
          setIsSourcesDrawerOpen(false);
          setSelectedSourceForPreview(null);
          if (sourcesDrawerPreviewUrl) {
            URL.revokeObjectURL(sourcesDrawerPreviewUrl);
          }
          setSourcesDrawerPreviewUrl("");
        }}
        open={isSourcesDrawerOpen}
        style={{ width: 750, height: "100vh" }}
        styles={{
          body: { padding: 0, background: "var(--app-surface)", display: "flex", height: "100%" },
        }}
      >
        {/* Left List Pane */}
        <div style={{ width: "240px", borderRight: "1px solid var(--app-border)", height: "100%", overflowY: "auto", padding: "16px" }} className="space-y-2">
          <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--app-text-soft)] block mb-3">
            Citations
          </span>
          {activeSources.map((src, index) => {
            const fileName = getFileName(src.source);
            const isSelected = (selectedSourceForPreview?.id || selectedSourceForPreview?.chunk_id) === (src.id || src.chunk_id);
            return (
              <div
                key={(src.id || src.chunk_id) || index}
                onClick={() => handleSelectSourceForPreview(src)}
                className={`p-3 rounded-xl cursor-pointer border transition-all ${isSelected
                    ? "bg-[#285d91] text-white border-transparent shadow-sm"
                    : "bg-[var(--app-surface-muted)] hover:bg-[var(--app-hover)] text-[var(--app-text)] border-[var(--app-border)]/40"
                  }`}
              >
                <div className="flex align-center gap-2 mb-1 min-w-0">
                  <span className="text-xs">📄</span>
                  <Text className={`font-semibold text-xs block truncate ${isSelected ? "text-white" : "text-[var(--app-text)]"}`} style={{ maxWidth: "160px" }}>
                    {fileName}
                  </Text>
                </div>
                <div className={`text-[9px] ${isSelected ? "text-white/70" : "text-[var(--app-text-muted)]"}`}>
                  Score: {Math.round((src.score || 0) * 100)}%
                </div>
              </div>
            );
          })}
        </div>
        {activeSources.length === 0 && (
          <div className="p-3 text-sm text-[var(--app-text-muted)]">
            No source documents
          </div>
        )}

        {/* Right Preview Pane */}
        <div style={{ flex: 1, height: "100%", overflowY: "auto", padding: "20px", display: "flex", flexDirection: "column", background: "var(--app-surface-muted)" }}>
          {sourcesDrawerPreviewLoading ? (
            <Flex vertical align="center" justify="center" gap={12} className="h-full">
              <Spin size="large" />
              <Text className="text-xs text-[var(--app-text-soft)] font-semibold">
                Loading source preview...
              </Text>
            </Flex>
          ) : selectedSourceForPreview ? (
            <div className="w-full h-full flex flex-col justify-start">
              {/* Header and Toggle Controls */}
              <Flex vertical gap={12} className="mb-4 bg-[var(--app-surface)] p-4 rounded-xl border border-[var(--app-border)]/40 shadow-sm shrink-0">
                <Flex justify="space-between" align="center" className="min-w-0 gap-4">
                  <Text className="text-xs font-bold text-[var(--app-text)] truncate flex-1">
                    {getFileName(selectedSourceForPreview.source)}
                  </Text>
                  {selectedSourceForPreview.reason && (
                    <span className="text-[9px] font-extrabold uppercase tracking-wider text-emerald-600 bg-emerald-500/10 px-2 py-0.5 rounded-md shrink-0">
                      {selectedSourceForPreview.reason}
                    </span>
                  )}
                </Flex>

                {/* Tab Switcher for parsed contents */}
                {(selectedSourceForPreview.content_type === "parsed" ||
                  selectedSourceForPreview.parsed_path !== undefined ||
                  getFileName(selectedSourceForPreview.source).toLowerCase().endsWith(".pdf") ||
                  getFileName(selectedSourceForPreview.source).toLowerCase().endsWith(".docx") ||
                  getFileName(selectedSourceForPreview.source).toLowerCase().endsWith(".doc") ||
                  getFileName(selectedSourceForPreview.source).toLowerCase().endsWith(".txt")) && (
                    <div className="flex bg-[var(--app-surface-muted)] p-1 rounded-xl border border-[var(--app-border)]/40 self-start">
                      <button
                        onClick={() => setSourcesDrawerPreviewTab("original")}
                        className={`px-4 py-1.5 rounded-lg text-xs font-extrabold transition-all cursor-pointer ${sourcesDrawerPreviewTab === "original"
                            ? "bg-[#285d91] text-white shadow-sm"
                            : "text-[var(--app-text-soft)] hover:text-[var(--app-text)]"
                          }`}
                      >
                        Original Document
                      </button>
                      {/* <button
                        onClick={() => setSourcesDrawerPreviewTab("parsed")}
                        className={`px-4 py-1.5 rounded-lg text-xs font-extrabold transition-all cursor-pointer ${sourcesDrawerPreviewTab === "parsed"
                            ? "bg-[#285d91] text-white shadow-sm"
                            : "text-[var(--app-text-soft)] hover:text-[var(--app-text)]"
                          }`}
                      >
                        Extracted Text
                      </button> */}

                    </div>
                  )}
              </Flex>

              {/* Preview Body Container */}
              <div className="flex-1 w-full bg-[var(--app-surface)] rounded-xl border border-[var(--app-border)]/40 overflow-hidden relative shadow-sm" style={{ minHeight: "450px" }}>
                {sourcesDrawerPreviewTab === "parsed" ? (
                  /* Extracted Clean Text Tab */
                  <div className="w-full h-full flex flex-col justify-start">
                    {parsedTextLoading ? (
                      <Flex vertical align="center" justify="center" gap={12} className="h-full my-auto py-20">
                        <Spin size="large" />
                        <Text className="text-xs text-[var(--app-text-soft)] font-semibold">
                          Parsing document content...
                        </Text>
                      </Flex>
                    ) : (
                      <div
                        className="w-full h-full overflow-y-auto p-6 markdown-content custom-scrollbar"
                        dangerouslySetInnerHTML={{
                          __html: htmlContent || "<p style='color: var(--app-text-muted)'>No extracted text content available.</p>"
                        }}
                      />
                    )}
                  </div>
                ) : (
                  /* Original Document Tab */
                  <div className="w-full h-full flex flex-col justify-start overflow-hidden">
                    {sourcesDrawerPreviewType === "pdf" && sourcesDrawerPreviewUrl && (
                      <iframe
                        src={`${sourcesDrawerPreviewUrl}#navpanes=0`}
                        width="100%"
                        height="100%"
                        style={{ border: "none" }}
                      />
                    )}

                    {sourcesDrawerPreviewType === "image" && sourcesDrawerPreviewUrl && (
                      <div className="w-full h-full flex items-center justify-center p-4">
                        <img
                          src={sourcesDrawerPreviewUrl}
                          alt={getFileName(selectedSourceForPreview.source)}
                          style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain", borderRadius: "8px" }}
                        />
                      </div>
                    )}

                    {(sourcesDrawerPreviewType === "excel" || sourcesDrawerPreviewType === "csv") && excelSheetNames.length > 0 && (
                      <div className="w-full h-full flex flex-col overflow-hidden bg-white">
                        {/* Excel Multi-sheet Switcher */}
                        {sourcesDrawerPreviewType === "excel" && excelSheetNames.length > 1 && (
                          <div className="flex gap-2 p-2.5 bg-neutral-50 border-b border-neutral-200 overflow-x-auto shrink-0 scrollbar-thin">
                            {excelSheetNames.map(sheetName => {
                              const isActive = activeExcelSheet === sheetName;
                              return (
                                <button
                                  key={sheetName}
                                  onClick={() => setActiveExcelSheet(sheetName)}
                                  className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer whitespace-nowrap ${isActive
                                      ? "bg-[#285d91] text-white shadow-sm"
                                      : "bg-white hover:bg-neutral-100 text-neutral-600 border border-neutral-200"
                                    }`}
                                >
                                  {sheetName}
                                </button>
                              );
                            })}
                          </div>
                        )}

                        {/* Spreadsheet Grid */}
                        <div className="flex-1 overflow-auto p-4 custom-scrollbar bg-white">
                          {excelSheets[activeExcelSheet] && excelSheets[activeExcelSheet].length > 0 ? (
                            <div className="border border-neutral-200 rounded-xl overflow-hidden shadow-sm">
                              <table className="min-w-full divide-y divide-neutral-200 text-left text-xs bg-white">
                                <thead className="bg-neutral-50 font-bold text-neutral-700 uppercase tracking-wider">
                                  <tr>
                                    {excelSheets[activeExcelSheet][0].map((cell, idx) => (
                                      <th key={idx} className="px-4 py-3 border-b border-r border-neutral-200 last:border-r-0 whitespace-nowrap bg-neutral-100 text-neutral-800 font-extrabold text-[10px] tracking-wider">
                                        {cell || `Column ${idx + 1}`}
                                      </th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody className="bg-white divide-y divide-neutral-200 text-neutral-600 font-medium">
                                  {excelSheets[activeExcelSheet].slice(1).map((row, rowIdx) => (
                                    <tr key={rowIdx} className="hover:bg-neutral-50/80 transition-colors">
                                      {excelSheets[activeExcelSheet][0].map((_, colIdx) => (
                                        <td key={colIdx} className="px-4 py-3 border-r border-neutral-200 last:border-r-0 max-w-xs truncate whitespace-nowrap text-neutral-600">
                                          {row[colIdx] || ""}
                                        </td>
                                      ))}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          ) : (
                            <Flex vertical align="center" justify="center" className="py-20 text-neutral-400 h-full">
                              <LuFileText size={32} className="mb-2 opacity-55" />
                              <span className="text-xs">No data in this sheet</span>
                            </Flex>
                          )}
                        </div>
                      </div>
                    )}

                    {sourcesDrawerPreviewType === "other" && (
                      <Flex vertical align="center" justify="center" gap={20} className="py-20 w-full h-full">
                        <div className="w-16 h-16 rounded-2xl bg-[#285d91]/10 text-[#285d91] flex items-center justify-center">
                          <LuFileText size={32} />
                        </div>
                        <Flex vertical align="center" gap={4} className="text-center max-w-sm px-4">
                          <Title level={5} className="!m-0 !text-[var(--app-text)] !font-bold">
                            Inline Preview Not Available
                          </Title>
                          <Text className="text-xs text-[var(--app-text-muted)] font-medium">
                            This format ({getFileName(selectedSourceForPreview.source).split('.').pop()?.toUpperCase()}) cannot be rendered directly. You can download the file to view its contents.
                          </Text>
                        </Flex>
                        <Button
                          type="primary"
                          icon={<LuDownload />}
                          href={sourcesDrawerPreviewUrl}
                          download={getFileName(selectedSourceForPreview.source)}
                          className="rounded-xl !bg-[#285d91] hover:!bg-[#1e4873] !h-10 px-5 font-bold shadow-md shadow-blue-900/10 flex items-center gap-2"
                        >
                          Download File
                        </Button>
                      </Flex>
                    )}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <Flex vertical align="center" justify="center" className="h-full opacity-40">
              <LuBookOpen size={48} className="text-[#285d91] mb-3" />
              <Text className="font-bold text-xs uppercase tracking-widest text-[var(--app-text-muted)]">
                Select a document to preview
              </Text>
            </Flex>
          )}
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

        /* Premium Markdown content typography and layout */
        .markdown-content {
          font-family: 'Outfit', 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
          color: var(--app-text);
          line-height: 1.8;
          font-size: 14px;
        }
        .markdown-content h1, 
        .markdown-content h2, 
        .markdown-content h3, 
        .markdown-content h4 {
          color: var(--app-text);
          font-weight: 800;
          margin-top: 1.5em;
          margin-bottom: 0.6em;
          line-height: 1.35;
          letter-spacing: -0.02em;
        }
        .markdown-content h1 {
          font-size: 1.8rem;
          border-bottom: 1px solid rgba(255, 255, 255, 0.1);
          padding-bottom: 0.3em;
        }
        .markdown-content h2 {
          font-size: 1.4rem;
          border-bottom: 1px solid rgba(255, 255, 255, 0.08);
          padding-bottom: 0.2em;
        }
        .markdown-content h3 {
          font-size: 1.25rem;
        }
        .markdown-content h4 {
          font-size: 1.1rem;
        }
        .markdown-content p {
          margin-top: 0;
          margin-bottom: 1.2em;
        }
        .markdown-content ul, 
        .markdown-content ol {
          margin-top: 0;
          margin-bottom: 1.2em;
          padding-left: 1.5em;
        }
        .markdown-content li {
          margin-bottom: 0.4em;
        }
        .markdown-content pre {
          background: #0f141c;
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 12px;
          padding: 16px;
          overflow-x: auto;
          margin-top: 0;
          margin-bottom: 1.2em;
          font-family: 'Fira Code', 'Courier New', Courier, monospace;
        }
        .markdown-content code {
          background: rgba(0, 0, 0, 0.2);
          padding: 0.2em 0.4em;
          border-radius: 6px;
          font-size: 85%;
          font-family: 'Fira Code', 'Courier New', Courier, monospace;
        }
        .markdown-content pre code {
          background: transparent;
          padding: 0;
          border-radius: 0;
          font-size: inherit;
          color: #e5e9f0;
        }
        .markdown-content blockquote {
          border-left: 4px solid #285d91;
          background: rgba(40, 93, 145, 0.05);
          margin: 0 0 1.2em 0;
          padding: 12px 20px;
          border-radius: 0 8px 8px 0;
          color: var(--app-text-soft);
          font-style: italic;
        }
        .markdown-content table {
          width: 100%;
          border-collapse: collapse;
          margin-bottom: 1.2em;
        }
        .markdown-content th, 
        .markdown-content td {
          border: 1px solid var(--app-border);
          padding: 10px 14px;
          text-align: left;
        }
        .markdown-content th {
          background: var(--app-surface-muted);
          font-weight: bold;
        }
        .markdown-content img {
          max-width: 100%;
          border-radius: 8px;
          margin-bottom: 1.2em;
        }
      `}</style>
    </div>
  );
}