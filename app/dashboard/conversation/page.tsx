"use client";

import { Flex, Typography, Button, Input, Tooltip, Avatar, Drawer, Grid, Upload, message, Spin, Table, Dropdown, Modal, Radio } from "antd";
import React, { useState, useRef, useEffect, useCallback } from "react";
import { LuBot, LuHistory, LuSearch, LuPlus, LuPaperclip, LuFileText, LuDownload, LuBookOpen, LuBell, LuSettings, LuSparkles, LuGlobe, LuArrowRight } from "react-icons/lu";
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
  id?: string;
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
  feedback?: "thumbs_up" | "thumbs_down";
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


// Fetch full session detail (with per-message message_id) from backend
// Endpoint: GET /chats/{agentId}/sessions/{sessionId}
async function fetchSessionMessages(agentId: string, sessionId: string): Promise<any[]> {
  try {
    const res = await fetch(`${API_BASE_URL}/chats/${agentId}/sessions/${sessionId}`, {
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(`${res.status}`);
    const result = await res.json();
    const payload = result.data ?? result;
    return Array.isArray(payload) ? payload : (payload?.messages ?? []);
  } catch (e) {
    console.error('fetchSessionMessages failed:', e);
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

function parsePythonDict(str: string): any {
  let i = 0;
  const len = str.length;

  function skipWhitespace() {
    while (i < len && /\s/.test(str[i])) {
      i++;
    }
  }

  function parseValue(): any {
    skipWhitespace();
    if (i >= len) return null;

    const char = str[i];

    // Parse String
    if (char === "'" || char === '"') {
      const quoteChar = char;
      i++; // skip quote
      let val = "";
      while (i < len) {
        if (str[i] === "\\") {
          i++;
          if (i < len) {
            const nextChar = str[i];
            if (nextChar === "n") val += "\n";
            else if (nextChar === "t") val += "\t";
            else if (nextChar === "r") val += "\r";
            else if (nextChar === "b") val += "\b";
            else if (nextChar === "f") val += "\f";
            else val += nextChar;
            i++;
          }
        } else if (str[i] === quoteChar) {
          i++; // skip close quote
          return val;
        } else {
          val += str[i];
          i++;
        }
      }
      return val;
    }

    // Parse Object / Dict
    if (char === "{") {
      i++; // skip '{'
      const obj: any = {};
      while (i < len) {
        skipWhitespace();
        if (str[i] === "}") {
          i++;
          return obj;
        }
        const key = parseValue();
        skipWhitespace();
        if (str[i] !== ":") {
          return obj;
        }
        i++; // skip ':'
        const val = parseValue();
        obj[key] = val;
        skipWhitespace();
        if (str[i] === ",") {
          i++; // skip ','
        }
      }
      return obj;
    }

    // Parse List
    if (char === "[") {
      i++; // skip '['
      const arr: any[] = [];
      while (i < len) {
        skipWhitespace();
        if (str[i] === "]") {
          i++;
          return arr;
        }
        const val = parseValue();
        arr.push(val);
        skipWhitespace();
        if (str[i] === ",") {
          i++; // skip ','
        }
      }
      return arr;
    }

    // Parse True, False, None, or numbers
    let word = "";
    while (i < len && /[a-zA-Z0-9_\.\+-]/.test(str[i])) {
      word += str[i];
      i++;
    }

    if (word === "True") return true;
    if (word === "False") return false;
    if (word === "None") return null;

    const num = Number(word);
    if (!isNaN(num)) return num;

    return word;
  }

  try {
    return parseValue();
  } catch (e) {
    console.error("Failed to parse Python dict:", e);
    return null;
  }
}

function cleanExtractedText(raw: string): string {
  if (!raw) return "";

  let processed = raw.trim();

  if (processed.startsWith("{") && processed.endsWith("}")) {
    try {
      const parsed = JSON.parse(processed);
      if (parsed) {
        processed = parsed.markdown || parsed.text || parsed.content || processed;
      }
    } catch (jsonErr) {
      try {
        const parsed = parsePythonDict(processed);
        if (parsed) {
          processed = parsed.markdown || parsed.text || parsed.content || processed;
        }
      } catch (pyErr) {
        console.error("Failed to parse as Python dict:", pyErr);
      }
    }
  }

  if (typeof processed !== "string") {
    processed = String(processed);
  }

  processed = processed
    .replace(/\\n/g, "\n")
    .replace(/\\t/g, "\t")
    .replace(/\\r/g, "\r")
    .replace(/\\'/g, "'")
    .replace(/\\"/g, '"');

  return processed;
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

// Classify a source by its extension / URL pattern
// If the source object has a kb_id it's always a downloadable file (clickable)
function getSourceType(source: string, kb_id?: string): 'url' | 'pdf' | 'excel' | 'csv' | 'image' | 'text' {
  const s = source.toLowerCase();
  if (s.startsWith('http://') || s.startsWith('https://') || s.includes('www.')) return 'url';
  if (s.endsWith('.pdf')) return 'pdf';
  if (s.endsWith('.xls') || s.endsWith('.xlsx')) return 'excel';
  if (s.endsWith('.csv')) return 'csv';
  if (s.endsWith('.png') || s.endsWith('.jpg') || s.endsWith('.jpeg') || s.endsWith('.gif') || s.endsWith('.webp')) return 'image';
  // If kb_id is present, this is a real file in the KB — default to pdf behavior (clickable)
  if (kb_id) return 'pdf';
  return 'text';
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

function stripThinking(content: string): string {
  if (!content) return "";
  let cleaned = content.replace(/<think>[\s\S]*?<\/think>/g, "");
  const openThinkIndex = cleaned.indexOf("<think>");
  if (openThinkIndex !== -1) {
    cleaned = cleaned.substring(0, openThinkIndex);
  }
  return cleaned;
}

function cleanAndExtractSources(content: string, existingSources?: SourceMetadata[]): { cleanedContent: string, sources: SourceMetadata[] } {
  const stripped = stripThinking(content);
  if (!stripped) return { cleanedContent: "", sources: [] };

  const citedFilenames = extractCitedFilenames(stripped);

  const cleanedContent = stripped
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

const GSearchLogoAvatar = ({ size = 32 }: { size?: number }) => {
  return (
    <div
      className="rounded-xl flex items-center justify-center bg-[#285d91] text-white shrink-0 border border-[#285d91]/20 shadow-none font-bold"
      style={{ width: `${size}px`, height: `${size}px` }}
    >
      <FaBrain size={size * 0.55} />
    </div>
  );
};

// Helper functions for parsing and rendering messages with custom styles for bold headings and clickable links
const renderBoldText = (text: string, key: any, isUser: boolean) => {
  if (!text) return null;
  const boldRegex = /(\*\*.*?\*\*)/g;
  const subparts = text.split(boldRegex);
  return (
    <span key={key}>
      {subparts.map((subpart, subIndex) => {
        if (subpart.startsWith("**") && subpart.endsWith("**")) {
          const content = subpart.slice(2, -2);
          return (
            <strong
              key={subIndex}
              className={`font-extrabold ${isUser ? "text-white" : "text-[var(--app-text)] font-black"}`}
            >
              {content}
            </strong>
          );
        }
        return subpart;
      })}
    </span>
  );
};

const renderTextWithLinks = (text: string, isUser: boolean) => {
  if (!text) return null;
  const urlRegex = /(https?:\/\/[^\s]+)/gi;
  const parts = text.split(urlRegex);
  return parts.map((part, index) => {
    if (part.match(urlRegex)) {
      return (
        <a
          key={index}
          href={part}
          target="_blank"
          rel="noopener noreferrer"
          className={`underline break-all transition-all font-bold ${isUser
            ? "text-sky-200 hover:text-white"
            : "text-[#285d91] hover:text-sky-500 dark:text-sky-400 dark:hover:text-sky-300"
            }`}
        >
          {part}
        </a>
      );
    }
    return renderBoldText(part, index, isUser);
  });
};

const renderFormattedContent = (content: string, isUser: boolean) => {
  const stripped = stripThinking(content).trim();
  if (!stripped) return null;
  const lines = stripped.split('\n');
  return lines.map((line, index) => {
    const headingWithColonRegex = /^\*\*(.*?)\*\*:\s*(.*)$/;
    const headingOnlyRegex = /^\*\*(.*?)\*\*\s*$/;
    const bulletRegex = /^(\s*[-*•]\s+)(.*)$/;
    const numberListRegex = /^(\s*\d+\.\s+)(.*)$/;

    let match = line.match(headingWithColonRegex);
    if (match) {
      const headingText = match[1];
      const restText = match[2];
      return (
        <div key={index} className="mb-3 mt-2">
          <div className={`font-extrabold text-sm md:text-base tracking-tight ${isUser ? "text-white" : "text-[#285d91] dark:text-sky-400"}`}>
            {headingText}
          </div>
          {restText && (
            <div className={`text-xs md:text-sm mt-1 leading-relaxed font-normal ${isUser ? "text-white/95" : "text-[var(--app-text)] opacity-95"}`}>
              {renderTextWithLinks(restText, isUser)}
            </div>
          )}
        </div>
      );
    }

    match = line.match(headingOnlyRegex);
    if (match) {
      const headingText = match[1];
      return (
        <div key={index} className={`font-extrabold text-sm md:text-base tracking-tight mb-2 mt-2 ${isUser ? "text-white" : "text-[#285d91] dark:text-sky-400"}`}>
          {headingText}
        </div>
      );
    }

    let bulletMatch = line.match(bulletRegex);
    if (bulletMatch) {
      return (
        <div key={index} className="flex items-start gap-2 pl-2 my-1">
          <span className={`shrink-0 ${isUser ? "text-white/80" : "text-[var(--app-text-soft)]"}`}>•</span>
          <span className="flex-1 text-xs md:text-sm leading-relaxed">
            {renderTextWithLinks(bulletMatch[2], isUser)}
          </span>
        </div>
      );
    }

    let numberMatch = line.match(numberListRegex);
    if (numberMatch) {
      const prefix = numberMatch[1].trim();
      return (
        <div key={index} className="flex items-start gap-2 pl-2 my-1">
          <span className={`shrink-0 font-bold text-xs md:text-sm ${isUser ? "text-white/80" : "text-[var(--app-text-soft)]"}`}>{prefix}</span>
          <span className="flex-1 text-xs md:text-sm leading-relaxed">
            {renderTextWithLinks(numberMatch[2], isUser)}
          </span>
        </div>
      );
    }

    return (
      <div key={index} className="min-h-[1.5rem] leading-relaxed text-xs md:text-sm">
        {renderTextWithLinks(line, isUser)}
      </div>
    );
  });
};

export default function ChatPlaygroundPage() {
  const [agent, setAgent] = useState<{ id: string; name: string } | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<any>([]);
  const [showSources, setShowSources] = useState(true);

  // Selector states
  const botsCache = useStore((state) => state.botsCache);
  const [activeMode, setActiveMode] = useState<'search' | 'agent'>('agent');
  const [selectedModel, setSelectedModel] = useState<'Flash' | 'Pro' | 'Ultra'>('Flash');
  const [searchQuery, setSearchQuery] = useState<string>("");
  const searchRef = useRef<HTMLInputElement>(null);

  // Feedback states
  const [feedbackModalOpen, setFeedbackModalOpen] = useState(false);
  const [feedbackMessageId, setFeedbackMessageId] = useState<string | null>(null);
  const [selectedReason, setSelectedReason] = useState<string>("Incorrect Answer");
  const [customReason, setCustomReason] = useState<string>("");
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

  useEffect(() => {
    const handleShortcut = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        const nextMode = activeMode === 'search' ? 'agent' : 'search';
        setActiveMode(nextMode);
        if (nextMode === 'search') {
          setTimeout(() => searchRef.current?.focus(), 50);
        }
      }
    };
    window.addEventListener('keydown', handleShortcut);
    return () => window.removeEventListener('keydown', handleShortcut);
  }, [activeMode]);

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
  const streamingMessageIdRef = useRef<string | null>(null);
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
                    id: msg.message_id || msg.id || msg.messageId || msg.msg_id || msg._id || msg.msgId,
                    role: msg.role,
                    content: cleanedContent,
                    file: msg.file,
                    sources: sources.length > 0 ? sources : undefined,
                    feedback: msg.feedback_type || msg.feedback,
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

        // Default path: if no agentId is specified in URL, start empty (as requested)
        setAgent(null);
        setSessions([]);
        setMessages([]);
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
    if (!initialLoadDone) return;

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
  }, [agent?.id, currentSessionId, initialLoadDone]);

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

        const parsedId = data.message_id || data.messageId || data.id ||
          (data.message && (data.message.id || data.message.message_id || data.message.messageId)) ||
          (data.data && (data.data.id || data.data.message_id || data.data.messageId));
        if (parsedId && typeof parsedId === "string") {
          streamingMessageIdRef.current = parsedId;
        }

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
                id: data.message_id || data.messageId || data.id || data.msg_id || data._id || streamingMessageIdRef.current,
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

              let finalSessionId = backendSessionId || currentSessionIdRef.current;
              if (!backendSessionId && currentSessionIdRef.current && currentSessionIdRef.current.startsWith("session_") && freshSessions.length > 0) {
                finalSessionId = freshSessions[0].id;
                setCurrentSessionId(finalSessionId);
                currentSessionIdRef.current = finalSessionId;
              }

              // Robust retry logic to fetch correct message IDs from detail endpoint
              let rawMsgs: any[] = [];
              let attempts = 0;
              while (attempts < 5) {
                rawMsgs = await fetchSessionMessages(agent.id, finalSessionId);
                const hasAssistantMsg = rawMsgs.some(m => m.role === "assistant");
                if (hasAssistantMsg) {
                  break;
                }
                attempts++;
                await new Promise((resolve) => setTimeout(resolve, 500));
              }

              if (rawMsgs.length > 0) {
                const mappedMessages = rawMsgs.map((msg: any) => {
                  const { cleanedContent, sources } = cleanAndExtractSources(msg.content, msg.sources);
                  return {
                    id: msg.id || msg.message_id || msg.messageId || msg.msg_id || msg._id || msg.msgId,
                    role: msg.role,
                    content: cleanedContent,
                    file: msg.file,
                    sources: sources.length > 0 ? sources : undefined,
                    feedback: msg.feedback_type || msg.feedback,
                    timestamp: msg.created_at
                      ? new Date(msg.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                      : new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
                  };
                });
                setMessages(mappedMessages);
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

  const loadSession = async (session: ChatSession) => {
    if (isTyping) {
      connectWs();
    }
    resetChatStates();

    setCurrentSessionId(session.id);
    currentSessionIdRef.current = session.id;

    // Fetch real message_id values from session detail endpoint
    const agentId = session.agent_id || session.agentId;
    let rawMessages: any[] = session.messages || [];
    if (agentId && !session.id.startsWith("session_")) {
      const fetched = await fetchSessionMessages(agentId, session.id);
      if (fetched.length > 0) rawMessages = fetched;
    }

    const mappedMessages = rawMessages.map((msg: any) => {
      const { cleanedContent, sources } = cleanAndExtractSources(msg.content, msg.sources);
      return {
        id: msg.message_id || msg.id || msg.messageId || msg.msg_id || msg._id || msg.msgId,
        role: msg.role,
        content: cleanedContent,
        file: msg.file,
        sources: sources.length > 0 ? sources : undefined,
        feedback: msg.feedback_type || msg.feedback,
        timestamp: msg.created_at
          ? new Date(msg.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
          : new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
    });

    setMessages(mappedMessages);
    if (agentId) {
      const matched = botsCache?.find(b => b.id === agentId);
      if (matched) {
        setAgent({ id: matched.id, name: matched.name });
      } else {
        setAgent({ id: agentId, name: session.agentName || "Select Agent" });
      }
    }
    setMobileSidebarOpen(false);
  };

  const deleteSession = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();

    // Optimistically update local session list
    setSessions(prev => prev.filter(s => s.id !== id));

    if (currentSessionId === id) {
      setCurrentSessionId(null);
      currentSessionIdRef.current = null;
      setMessages([]);
      // Keep the agent selected, DO NOT set it to null!
    }

    try {
      const token = getCookie(AUTH_COOKIE_KEY);
      // Attempt standard session deletion endpoint
      const res = await fetch(`${API_BASE_URL}/chats/sessions/${id}`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${token}`
        }
      });

      if (res.ok) {
        message.success("Session deleted successfully.");
      } else {
        console.warn("DELETE /chats/sessions failed, trying fallback...", res.status);
        if (agent?.id) {
          const resFallback = await fetch(`${API_BASE_URL}/chats/${agent.id}/sessions/${id}`, {
            method: "DELETE",
            headers: {
              Authorization: `Bearer ${token}`
            }
          });
          if (resFallback.ok) {
            message.success("Session deleted successfully.");
            return;
          }
        }
        message.error("Failed to delete session on server.");
      }
    } catch (err) {
      console.error("Delete session error:", err);
      message.error("Failed to delete session on server.");
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
    streamingMessageIdRef.current = null;
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
            const hasNoTitle = !s.title || s.title.toLowerCase().includes("untitled");
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
    streamingMessageIdRef.current = null;
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

  const handleOpenSource = async (src: SourceMetadata) => {
    let currentSources = agentSources;
    if (agent?.id && currentSources.length === 0) {
      currentSources = await fetchAgentSources(agent.id);
      setAgentSources(currentSources);
    }

    let kbId = src.kb_id;
    if (!kbId && currentSources.length > 0) {
      const fname = getFileName(src.source).toLowerCase();
      const matched = currentSources.find(as => {
        const asName = (as.name || as.source || as.filename || '').toLowerCase();
        return asName.includes(fname) || fname.includes(asName) || cleanCompare(asName, fname);
      });
      if (matched) {
        kbId = matched.id || matched.kb_id || matched.kbId || '';
      }
    }

    const stype = getSourceType(src.source, kbId);
    if (stype === 'url') {
      const rawSrc = src.source || '';
      const urlMatch = rawSrc.match(/(https?:\/\/[^\s]+)/i);
      const openUrl = urlMatch ? urlMatch[1] : (rawSrc.startsWith('http') ? rawSrc : `https://${rawSrc}`);
      window.open(openUrl, '_blank', 'noopener,noreferrer');
    } else if (kbId) {
      try {
        const blobUrl = await getFilePreview(kbId);
        const filename = getFileName(src.source);
        const nameLower = filename.toLowerCase();

        // 1. Fetch blob to determine content type and parse binary spreadsheets
        const blobRes = await fetch(blobUrl);
        const blob = await blobRes.blob();
        const contentType = blob.type.toLowerCase();

        const isPdf = contentType.includes('pdf') || nameLower.endsWith('.pdf');
        const isImage = contentType.includes('image/') || nameLower.endsWith('.png') || nameLower.endsWith('.jpg') || nameLower.endsWith('.jpeg') || nameLower.endsWith('.webp') || nameLower.endsWith('.gif');
        const isTxt = contentType.includes('text/plain') || nameLower.endsWith('.txt');
        const isCSV = contentType.includes('csv') || nameLower.endsWith('.csv');
        const isExcel = contentType.includes('excel') || contentType.includes('spreadsheet') ||
          contentType.includes('vnd.ms-excel') || contentType.includes('vnd.openxmlformats-officedocument.spreadsheetml.sheet') ||
          nameLower.endsWith('.xls') || nameLower.endsWith('.xlsx');

        if (isPdf || isImage || isTxt) {
          const viewBlobUrl = URL.createObjectURL(blob);
          const newWindow = window.open('', '_blank');
          if (newWindow) {
            newWindow.document.title = filename || 'Source Preview';
            newWindow.document.body.style.margin = '0';
            newWindow.document.body.style.padding = '0';
            newWindow.document.body.style.height = '100vh';
            newWindow.document.body.style.overflow = 'hidden';

            const iframe = newWindow.document.createElement('iframe');
            iframe.src = viewBlobUrl;
            iframe.style.width = '100%';
            iframe.style.height = '100%';
            iframe.style.border = 'none';
            newWindow.document.body.appendChild(iframe);
          } else {
            message.error('Popup blocked. Please allow popups for this site.');
          }
        } else if (isCSV || isExcel) {
          // Parse spreadsheet array buffer using xlsx
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
          const sheetNames = workbook.SheetNames;

          const viewBlobUrl = URL.createObjectURL(blob);
          const newWindow = window.open('', '_blank');
          if (newWindow) {
            newWindow.document.write(`
              <!DOCTYPE html>
              <html>
              <head>
                <meta charset="utf-8">
                <title>${filename || 'Spreadsheet Preview'}</title>
                <style>
                  body {
                    margin: 0;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                    background: #f9fafb;
                    color: #374151;
                    display: flex;
                    flex-direction: column;
                    height: 100vh;
                  }
                  header {
                    background: #ffffff;
                    border-bottom: 1px solid #e5e7eb;
                    padding: 16px 24px;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    flex-shrink: 0;
                  }
                  h1 {
                    margin: 0;
                    font-size: 18px;
                    font-weight: 600;
                    color: #111827;
                  }
                  .tabs-container {
                    background: #f3f4f6;
                    border-bottom: 1px solid #e5e7eb;
                    padding: 8px 16px;
                    display: flex;
                    gap: 8px;
                    overflow-x: auto;
                    flex-shrink: 0;
                  }
                  .tab-btn {
                    background: #ffffff;
                    border: 1px solid #d1d5db;
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-size: 13px;
                    font-weight: 500;
                    cursor: pointer;
                    color: #4b5563;
                    white-space: nowrap;
                    transition: all 0.2s;
                  }
                  .tab-btn:hover {
                    background: #f9fafb;
                    color: #111827;
                  }
                  .tab-btn.active {
                    background: #285d91;
                    color: #ffffff;
                    border-color: #285d91;
                  }
                  .table-wrapper {
                    flex-grow: 1;
                    overflow: auto;
                    padding: 16px;
                  }
                  table {
                    border-collapse: collapse;
                    width: 100%;
                    background: #ffffff;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                    border-radius: 8px;
                    overflow: hidden;
                    font-size: 13px;
                  }
                  th, td {
                    border: 1px solid #e5e7eb;
                    padding: 10px 14px;
                    text-align: left;
                  }
                  th {
                    background: #f9fafb;
                    font-weight: 600;
                    color: #374151;
                    position: sticky;
                    top: 0;
                    z-index: 10;
                  }
                  tr:nth-child(even) {
                    background: #f9fafb;
                  }
                  tr:hover {
                    background: #f3f4f6;
                  }
                </style>
              </head>
              <body>
                <header>
                  <h1>${filename}</h1>
                  <button id="download-btn" style="background: #285d91; color: white; border: none; padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 6px;">
                    <svg stroke="currentColor" fill="none" stroke-width="2" viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round" height="1em" width="1em" xmlns="http://www.w3.org/2000/svg"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                    Download File
                  </button>
                </header>
                <div class="tabs-container" id="tabs"></div>
                <div class="table-wrapper">
                  <table id="sheet-table"></table>
                </div>
                <script>
                  const sheetsData = ${JSON.stringify(sheetsData)};
                  const sheetNames = ${JSON.stringify(sheetNames)};
                  
                  function renderSheet(sheetName) {
                    const rows = sheetsData[sheetName] || [];
                    const table = document.getElementById('sheet-table');
                    table.innerHTML = '';
                    
                    if (rows.length === 0) {
                      table.innerHTML = '<tr><td style="text-align:center; padding: 20px; color: #9ca3af;">Empty Sheet</td></tr>';
                      return;
                    }
                    
                    // Render headers
                    const headerRow = rows[0];
                    const thead = document.createElement('thead');
                    const trHead = document.createElement('tr');
                    
                    // Let's draw row index as column 0
                    const thIdx = document.createElement('th');
                    thIdx.innerText = '#';
                    thIdx.style.width = '40px';
                    thIdx.style.textAlign = 'center';
                    trHead.appendChild(thIdx);

                    headerRow.forEach((cellText, idx) => {
                      const th = document.createElement('th');
                      th.innerText = cellText || ('Column ' + (idx + 1));
                      trHead.appendChild(th);
                    });
                    thead.appendChild(trHead);
                    table.appendChild(thead);
                    
                    // Render rows
                    const tbody = document.createElement('tbody');
                    for (let r = 1; r < rows.length; r++) {
                      const rowData = rows[r];
                      const tr = document.createElement('tr');
                      
                      const tdIdx = document.createElement('td');
                      tdIdx.innerText = r;
                      tdIdx.style.textAlign = 'center';
                      tdIdx.style.background = '#f9fafb';
                      tdIdx.style.color = '#9ca3af';
                      tdIdx.style.fontWeight = 'bold';
                      tr.appendChild(tdIdx);

                      headerRow.forEach((_, colIdx) => {
                        const td = document.createElement('td');
                        td.innerText = rowData[colIdx] !== undefined ? rowData[colIdx] : '';
                        tr.appendChild(td);
                      });
                      tbody.appendChild(tr);
                    }
                    table.appendChild(tbody);
                  }
                  
                  // Render tabs
                  const tabsContainer = document.getElementById('tabs');
                  if (sheetNames.length > 1) {
                    sheetNames.forEach((name, idx) => {
                      const btn = document.createElement('button');
                      btn.className = 'tab-btn' + (idx === 0 ? ' active' : '');
                      btn.innerText = name;
                      btn.onclick = () => {
                        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                        btn.classList.add('active');
                        renderSheet(name);
                      };
                      tabsContainer.appendChild(btn);
                    });
                  } else {
                    tabsContainer.style.display = 'none';
                  }
                  
                  // Initial render
                  if (sheetNames.length > 0) {
                    renderSheet(sheetNames[0]);
                  }

                  document.getElementById('download-btn').onclick = () => {
                    const link = document.createElement('a');
                    link.href = '${viewBlobUrl}';
                    link.download = '${filename}';
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                  };
                </script>
              </body>
              </html>
            `);
            newWindow.document.close();
          } else {
            message.error('Popup blocked. Please allow popups for this site.');
          }
        } else {
          // fallback direct download
          const link = document.createElement('a');
          link.href = blobUrl;
          link.download = filename;
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
        }
      } catch (err) {
        console.error(err);
        message.error('Unable to open file preview');
      }
    } else {
      // Text citation / other fallback
      const filename = getFileName(src.source);
      const citationText = src.text || src.source || 'No citation text available.';
      const newWindow = window.open('', '_blank');
      if (newWindow) {
        newWindow.document.title = filename || 'Source Text Citation';
        newWindow.document.body.style.margin = '0';
        newWindow.document.body.style.padding = '24px';
        newWindow.document.body.style.fontFamily = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
        newWindow.document.body.style.background = '#f9fafb';
        newWindow.document.body.style.color = '#111827';
        newWindow.document.body.style.lineHeight = '1.6';

        const container = newWindow.document.createElement('div');
        container.style.maxWidth = '800px';
        container.style.margin = '40px auto';
        container.style.background = '#ffffff';
        container.style.padding = '32px';
        container.style.borderRadius = '12px';
        container.style.boxShadow = '0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06)';
        container.style.border = '1px solid #e5e7eb';

        const heading = newWindow.document.createElement('h2');
        heading.innerText = `Citation: ${filename}`;
        heading.style.marginTop = '0';
        heading.style.borderBottom = '2px solid #285d91';
        heading.style.paddingBottom = '12px';
        heading.style.color = '#1f2937';
        container.appendChild(heading);

        const contentParagraph = newWindow.document.createElement('p');
        contentParagraph.innerText = citationText;
        contentParagraph.style.whiteSpace = 'pre-wrap';
        contentParagraph.style.fontSize = '15px';
        contentParagraph.style.color = '#374151';
        contentParagraph.style.marginTop = '20px';
        container.appendChild(contentParagraph);

        newWindow.document.body.appendChild(container);
      } else {
        message.error('Popup blocked. Please allow popups for this site.');
      }
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
    streamingMessageIdRef.current = null;
    activeQuerySessionIdRef.current = currentSessionId;
    setIsTyping(true);
  };

  const handleThumbsUp = async (msgId?: string) => {
    if (!msgId) {
      message.error("Message ID not available for feedback.");
      return;
    }

    try {
      const token = getCookie(AUTH_COOKIE_KEY);
      const res = await fetch(`${API_BASE_URL}/chats/messages/feedback`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          message_id: msgId,
          feedback_type: "thumbs_up",
          feedback_reason: "Correct response",
        }),
      });

      if (res.ok) {
        message.success("Thank you for your feedback!");
        setMessages((prev: any) =>
          prev.map((m: any) => {
            const isMatch = m.id === msgId;
            return isMatch ? { ...m, feedback: "thumbs_up" } : m;
          })
        );
      } else {
        message.error("Failed to submit feedback.");
      }
    } catch (err) {
      console.error(err);
      message.error("An error occurred while sending feedback.");
    }
  };

  const handleThumbsDown = (msgId?: string) => {
    if (!msgId) {
      message.error("Message ID not available for feedback.");
      return;
    }
    setFeedbackMessageId(msgId);
    setFeedbackModalOpen(true);
  };

  const submitThumbsDownFeedback = async () => {
    if (!feedbackMessageId) return;

    const finalReason = selectedReason === "Other" ? customReason.trim() || "Other" : selectedReason;

    try {
      const token = getCookie(AUTH_COOKIE_KEY);
      const res = await fetch(`${API_BASE_URL}/chats/messages/feedback`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          message_id: feedbackMessageId,
          feedback_type: "thumbs_down",
          feedback_reason: finalReason,
        }),
      });

      if (res.ok) {
        message.success("Thank you for your feedback!");
        setMessages((prev: any) =>
          prev.map((m: any) => {
            const isMatch = m.id === feedbackMessageId;
            return isMatch ? { ...m, feedback: "thumbs_down" } : m;
          })
        );
      } else {
        message.error("Failed to submit feedback.");
      }
    } catch (err) {
      console.error(err);
      message.error("An error occurred while sending feedback.");
    } finally {
      setFeedbackModalOpen(false);
      setFeedbackMessageId(null);
      setCustomReason("");
      setSelectedReason("Incorrect Answer");
    }
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
          setParsedTextContent(cleanExtractedText(cleanText));
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

  // Search query filters the messages within the active conversation instead of sidebar sessions
  const displayedMessages = React.useMemo(() => {
    if (!searchQuery) return messages;
    const query = searchQuery.toLowerCase();
    return messages.filter((msg: any) =>
      msg.content && msg.content.toLowerCase().includes(query)
    );
  }, [messages, searchQuery]);

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
            <span className="text-[10px] font-extrabold uppercase tracking-widest text-[var(--app-text-muted)] ">
              Chats
            </span>
            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-[var(--app-border)]/30 text-[var(--app-text-muted)]">
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
                    className={`group relative p-2.5 rounded-xl cursor-pointer transition-all border flex items-center justify-between ${isActiveSession
                      ? "bg-[#285d91]/20 text-[var(--app-text)] border-transparent font-extrabold"
                      : "bg-transparent hover:bg-[var(--app-hover)] text-[var(--app-text-soft)] border-transparent"
                      }`}
                  >
                    <div className="flex items-center gap-2.5 min-w-0 flex-1">
                      <span className="text-sm shrink-0">💬</span>
                      <span className="text-xs truncate block pr-2">
                        {(!s.title || s.title.toLowerCase().includes("untitled")) ? "New Chat" : s.title}
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

            {/* Right side: Show Sources Switch */}
            <Flex align="center" gap={8} className="shrink-0 select-none">
              <span className="text-xs font-semibold text-[var(--app-text-soft)]">
                Show Sources
              </span>
              <Switch
                size="small"
                checked={showSources}
                onChange={(checked) => setShowSources(checked)}
                className="shrink-0 text-emerald-500"
              />
            </Flex>

          </Flex>
        </div>

        {/* Conversation Stream */}
        <div className="flex-1 overflow-y-auto px-4 md:px-12 py-6 md:py-10 space-y-6 custom-scrollbar bg-dots-pattern">
          {messages.length === 0 && !isTyping && (
            <Flex vertical align="center" justify="center" className="h-full select-none my-auto space-y-4">
              <h1 className="m-0 text-[var(--app-text)] font-extrabold text-xl sm:text-2xl md:text-4xl tracking-tight text-center max-w-xl px-4 animate-in fade-in duration-500">
                Hello {userName}! What can I do for you?
              </h1>
              {/* {agent && (
                <p className="text-xs font-semibold text-[var(--app-text-soft)]/50 uppercase tracking-widest text-center animate-in fade-in duration-700">
                  Active Agent: <span className="text-[#285d91] font-bold">{agent.name}</span>
                  • Model: <span className="text-[#285d91] font-bold">{selectedModel}</span>
                </p>
              )} */}
            </Flex>
          )}

          {displayedMessages.map((msg: any, i: any) => {
            const isUser = msg.role === "user";
            const hasImage = msg.file?.type?.startsWith("image/");
            const hasDoc = msg.file && !hasImage;

            return (
              <div key={i} className={`flex w-full ${isUser ? "justify-end" : "justify-start"} animate-in fade-in slide-in-from-bottom-2 duration-300`}>
                <div className={`flex gap-3 transition-all duration-300 ${editingMessageIndex === i ? "w-full max-w-[95%] md:max-w-[85%]" : "max-w-[88%] md:max-w-[75%]"} ${isUser ? "flex-row-reverse" : "flex-row"}`}>
                  {isUser ? (
                    <div className="relative shrink-0">
                      <Avatar
                        size={32}
                        className="bg-gradient-to-br from-[#285d91] to-[#163a5f] text-white shadow-md font-extrabold flex items-center justify-center border border-white/10"
                      >
                        <span style={{ fontSize: "14px", fontWeight: 800, letterSpacing: "0.1em" }}>
                          {userName
                            ? userName.split(" ").map((n: string) => n[0]).join("").toUpperCase().slice(0, 2)
                            : <FiUser />}
                        </span>
                      </Avatar>
                    </div>
                  ) : (
                    <GSearchLogoAvatar size={32} />
                  )}

                  <div className={`flex flex-col space-y-1 ${editingMessageIndex === i ? "flex-1 min-w-0" : ""}`}>
                    <span className={`text-[9px] font-bold text-[var(--app-text-soft)] px-1 ${isUser ? "text-right" : "text-left"}`}>
                      {msg.timestamp}
                    </span>

                    <div
                      className={`group relative p-4 md:p-5 rounded-2xl transition-all duration-200 shadow-sm border mb-6 ${isUser
                        ? "bg-[#285d91] text-white rounded-tr-none border-[#285d91]/20 font-medium"
                        : "bg-[var(--app-surface-muted)] text-[var(--app-text)] rounded-tl-none border-[var(--app-border)]/40 font-normal"
                        }`}
                    >
                      {/* Dynamic File Rendering UI Framework */}
                      <div className={`absolute -bottom-10 left-0 right-0 pt-3 transition-all duration-200 flex gap-2 z-20 ${isUser ? "opacity-0 group-hover:opacity-100 pointer-events-none group-hover:pointer-events-auto" : "opacity-100 pointer-events-auto"}`}>
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
                              <button
                                onClick={() => handleThumbsUp(msg.id)}
                                className={`p-2 cursor-pointer transition-colors hover:opacity-80 ${msg.feedback === "thumbs_up" ? "text-emerald-500 font-bold" : "text-[var(--app-text)] font-bold"}`}
                              >
                                <FiThumbsUp size={16} strokeWidth={msg.feedback === "thumbs_up" ? 2.5 : 2} fill="none" />
                              </button>
                            </Tooltip>
                            <Tooltip title="Not helpful" placement="bottom">
                              <button
                                onClick={() => handleThumbsDown(msg.id)}
                                className={`p-2 cursor-pointer transition-colors hover:opacity-80 ${msg.feedback === "thumbs_down" ? "text-rose-500 font-bold" : "text-[var(--app-text)] font-bold"}`}
                              >
                                <FiThumbsDown size={16} strokeWidth={msg.feedback === "thumbs_down" ? 2.5 : 2} fill="none" />
                              </button>
                            </Tooltip>
                            <Tooltip title="Regenerate" placement="bottom">
                              <button
                                onClick={() => handleRegenerate(i)}
                                className="text-[var(--app-text)] font-bold p-2 cursor-pointer transition-colors hover:opacity-80"
                              >
                                <FiRotateCw size={16} strokeWidth={2} />
                              </button>
                            </Tooltip>
                            {showSources && msg.sources && msg.sources.length > 0 && (
                              <div className="ml-auto flex items-center">
                                {msg.sources.length === 1 ? (
                                  <button
                                    onClick={() => handleOpenSource(msg.sources![0])}
                                    className="text-[var(--app-text)] font-bold p-2 cursor-pointer transition-colors hover:opacity-80 hover:text-[#285d91] flex items-center gap-1 text-xs shrink-0"
                                  >
                                    <LuBookOpen size={16} strokeWidth={2} />
                                    <span>Source</span>
                                  </button>
                                ) : (
                                  <Dropdown
                                    menu={{
                                      items: msg.sources.map((src: any, idx: number) => ({
                                        key: idx.toString(),
                                        label: getFileName(src.source),
                                        onClick: () => handleOpenSource(src),
                                      })),
                                    }}
                                    placement="bottomLeft"
                                    trigger={['click']}
                                  >
                                    <button className="text-[var(--app-text)] font-bold p-2 cursor-pointer transition-colors hover:opacity-80 hover:text-[#285d91] flex items-center gap-1 text-xs shrink-0">
                                      <LuBookOpen size={16} strokeWidth={2} />
                                      <span>Sources</span>
                                    </button>
                                  </Dropdown>
                                )}
                              </div>
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
                                  style={{ WebkitTextFillColor: "rgba(255,255,255,0.8)", fontWeight: "normal", boxShadow: "none", borderRadius: "9999px" }}
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
                            <div className="mr-2 leading-7 flex flex-col gap-1.5">
                              {renderFormattedContent(msg.content, isUser)}
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
                <GSearchLogoAvatar size={32} />
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

          {/* Mode switch and search above input card */}
          <div className="flex justify-between items-center px-1 mb-2 w-full select-none gap-3">
            {/* Search & Agent Switcher unified container */}
            <div className="flex items-center gap-1 bg-[#eef6f8] dark:bg-[#131e31] p-1 rounded-full border border-[var(--app-border)]/40 shadow-sm">
              {/* Slot 1: Search Pill or Search Input */}
              {activeMode === 'search' ? (
                <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white dark:bg-[#0f172a] shadow-sm w-52 sm:w-64 transition-all duration-200">
                  <LuSearch size={12} className="shrink-0 text-[#285d91] dark:text-[#34d399]" />
                  <input
                    ref={searchRef}
                    type="text"
                    placeholder="Search sessions..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full bg-transparent border-none outline-none text-[11px] font-black tracking-tight text-[var(--app-text)] placeholder-[var(--app-text-soft)]/50"
                  />
                </div>
              ) : (
                <button
                  onClick={() => {
                    setActiveMode('search');
                    setTimeout(() => searchRef.current?.focus(), 50);
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] font-black tracking-tight transition-all duration-200 cursor-pointer border-none bg-transparent outline-none text-[var(--app-text-soft)]/70 hover:text-[var(--app-text)] font-extrabold"
                >
                  <LuSearch size={12} className="shrink-0" />
                  <span>Search</span>
                </button>
              )}

              {/* Slot 2: Agent Pill (stays as pill button, selector is rendered below inside the input card) */}
              <button
                onClick={() => setActiveMode('agent')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] font-black tracking-tight transition-all duration-200 cursor-pointer border-none bg-transparent outline-none ${activeMode === 'agent'
                    ? "bg-white dark:bg-[#0f172a] text-[#285d91] dark:text-[#34d399] shadow-sm font-black"
                    : "bg-transparent text-[var(--app-text-soft)]/70 hover:text-[var(--app-text)] font-extrabold"
                  }`}
              >
                <LuBot size={12} className="shrink-0" />
                <span>Agent</span>
              </button>
            </div>

            {/* Mode Shift Shortcut - hidden on mobile view */}
            <div className="hidden sm:flex items-center gap-1.5 text-[11px] text-[var(--app-text-soft)]/60 font-bold ml-auto">
              <span>Mode shift:</span>
              <kbd className="px-1.5 py-0.5 rounded bg-[var(--app-border)]/50 border border-[var(--app-border)] text-[9px] font-black">Ctrl</kbd>
              <kbd className="px-1.5 py-0.5 rounded bg-[var(--app-border)]/50 border border-[var(--app-border)] text-[9px] font-black">K</kbd>
            </div>
          </div>

          {/* Large Unified Input Card with dynamic purple borders */}
          <div className="bg-white dark:bg-[#0b0f19] border-2 border-purple-500/30 dark:border-purple-500/25 rounded-3xl p-3 shadow-lg transition-all focus-within:border-purple-500/70 focus-within:ring-4 focus-within:ring-purple-500/5 flex flex-col gap-2">

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

            {/* Input Text Area */}
            <div className="w-full">
              <Input.TextArea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask anything"
                disabled={!agent || wsStatus !== "open"}
                variant="borderless"
                autoSize={{ minRows: 2, maxRows: 6 }}
                className="w-full !p-1 !bg-transparent !font-semibold !text-xs md:!text-sm !text-[var(--app-text)] !placeholder:text-[var(--app-text-soft)]/50 focus:outline-none resize-none align-middle"
              />
            </div>

            {/* Input Row Actions Bottom Bar */}
            <Flex align="center" justify="space-between" className="w-full pt-1.5 border-t border-[var(--app-border)]/10">
              {/* Left actions */}
              <Flex align="center" gap={8} className="min-w-0">
                <Upload
                  beforeUpload={handleBeforeUpload}
                  showUploadList={false}
                  accept="image/*,.pdf,.doc,.docx,.xls,.xlsx,.txt"
                  disabled={!agent || wsStatus !== "open"}
                >
                  <Tooltip title="Share files" placement="topLeft">
                    <Button
                      type="text"
                      disabled={!agent || wsStatus !== "open"}
                      icon={<LuPaperclip className="text-base text-[var(--app-text-soft)]" />}
                      className="hover:bg-[var(--app-hover)] !rounded-xl w-8 h-8 flex items-center justify-center transition-colors border-none bg-transparent cursor-pointer"
                    />
                  </Tooltip>
                </Upload>

                {/* Conditionally show Styled Robot Capsule Dropdown trigger for Selecting Custom Agent inside input card when mode is agent */}
                {activeMode === 'agent' && (
                  <Dropdown
                    menu={{
                      items: botsCache?.map((bot) => ({
                        key: bot.id,
                        label: <span className="font-semibold text-xs">{bot.name}</span>
                      })),
                      onClick: (e) => {
                        const selected = botsCache?.find(b => b.id === e.key);
                        if (selected) {
                          handleAgentChange(selected.id, selected.name);
                        }
                      }
                    }}
                    trigger={["click"]}
                  >
                    <button className="flex items-center gap-1.5 px-3.5 py-1.5 bg-[#ffffff] hover:bg-gray-100 dark:bg-[#12352f]/30 dark:hover:bg-[#12352f]/50 border border-[#285d91]/30 dark:border-[#34d399]/40 rounded-full text-xs font-black text-[#285d91] dark:text-[#34d399] cursor-pointer select-none transition-all outline-none focus:outline-none ml-1 animate-in fade-in duration-200 shadow-sm">
                      <div className="w-5 h-5 rounded-full bg-[#e6f0fa] dark:bg-[#12352f] flex items-center justify-center text-[#285d91] dark:text-[#34d399] shrink-0">
                        <LuBot size={11} className="text-[#285d91] dark:text-[#34d399]" />
                      </div>
                      <span className="truncate max-w-[120px] text-[#285d91] dark:text-[#34d399] font-black">
                        {agent ? agent.name : "Select Agent"}
                      </span>
                      <span className="text-[9px] opacity-100 ml-0.5 text-[#285d91] dark:text-[#34d399] font-black">▼</span>
                    </button>
                  </Dropdown>
                )}
              </Flex>

              {/* Right actions */}
              <Flex align="center" gap={12} className="shrink-0">
                {/* Circular Send Arrow button */}
                <Tooltip title="Press Enter to send" placement="topRight">
                  <button
                    onClick={handleSend}
                    disabled={!agent || (!input.trim() && !attachedFile) || wsStatus !== "open"}
                    className="w-8 h-8 rounded-full flex items-center justify-center transition-all shrink-0 cursor-pointer border-none outline-none bg-gray-200 dark:bg-gray-800 text-[var(--app-text-soft)] hover:bg-[#285d91] hover:text-white disabled:opacity-40 disabled:hover:bg-gray-200 disabled:hover:text-[var(--app-text-soft)]"
                  >
                    <LuArrowRight size={16} strokeWidth={2.5} />
                  </button>
                </Tooltip>
              </Flex>
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
                      <div className="w-full h-full flex flex-col overflow-hidden bg-[var(--app-surface)]">
                        {/* Excel Multi-sheet Switcher */}
                        {sourcesDrawerPreviewType === "excel" && excelSheetNames.length > 1 && (
                          <div className="flex gap-2 p-2.5 bg-[var(--app-surface-muted)] border-b border-[var(--app-border)]/40 overflow-x-auto shrink-0 scrollbar-thin">
                            {excelSheetNames.map(sheetName => {
                              const isActive = activeExcelSheet === sheetName;
                              return (
                                <button
                                  key={sheetName}
                                  onClick={() => setActiveExcelSheet(sheetName)}
                                  className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer whitespace-nowrap ${isActive
                                    ? "bg-[#285d91] text-white shadow-sm"
                                    : "bg-[var(--app-surface)] hover:bg-[var(--app-surface-muted)] text-[var(--app-text-soft)] border border-[var(--app-border)]/40"
                                    }`}
                                >
                                  {sheetName}
                                </button>
                              );
                            })}
                          </div>
                        )}

                        {/* Spreadsheet Grid */}
                        <div className="flex-1 overflow-auto p-4 custom-scrollbar bg-[var(--app-surface)]">
                          {excelSheets[activeExcelSheet] && excelSheets[activeExcelSheet].length > 0 ? (
                            <div className="border border-[var(--app-border)]/40 rounded-xl overflow-hidden shadow-sm">
                              <table className="min-w-full divide-y divide-[var(--app-border)]/40 text-left text-xs bg-[var(--app-surface)]">
                                <thead className="bg-[var(--app-surface-muted)] font-bold text-[var(--app-text)] uppercase tracking-wider">
                                  <tr>
                                    {excelSheets[activeExcelSheet][0].map((cell, idx) => (
                                      <th key={idx} className="px-4 py-3 border-b border-r border-[var(--app-border)]/40 last:border-r-0 whitespace-nowrap bg-[var(--app-surface-muted)] text-[var(--app-text)] font-extrabold text-[10px] tracking-wider">
                                        {cell || `Column ${idx + 1}`}
                                      </th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody className="bg-[var(--app-surface)] divide-y divide-[var(--app-border)]/40 text-[var(--app-text-soft)] font-medium">
                                  {excelSheets[activeExcelSheet].slice(1).map((row, rowIdx) => (
                                    <tr key={rowIdx} className="hover:bg-[var(--app-surface-muted)]/50 transition-colors">
                                      {excelSheets[activeExcelSheet][0].map((_, colIdx) => (
                                        <td key={colIdx} className="px-4 py-3 border-r border-[var(--app-border)]/40 last:border-r-0 max-w-xs truncate whitespace-nowrap text-[var(--app-text-soft)]">
                                          {row[colIdx] || ""}
                                        </td>
                                      ))}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          ) : (
                            <Flex vertical align="center" justify="center" className="py-20 text-[var(--app-text-soft)] h-full">
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

      {/* Thumbs Down Feedback Modal */}
      <Modal
        title={<span className="text-[var(--app-text)] font-extrabold">Provide Feedback</span>}
        open={feedbackModalOpen}
        onCancel={() => {
          setFeedbackModalOpen(false);
          setFeedbackMessageId(null);
        }}
        footer={[
          <Button key="cancel" onClick={() => setFeedbackModalOpen(false)} className="hover:!border-[var(--app-border)] hover:!text-[var(--app-text)]">
            Cancel
          </Button>,
          <Button key="submit" type="primary" onClick={submitThumbsDownFeedback} className="bg-[#285d91] hover:bg-[#285d91]/80 border-none font-bold">
            Submit
          </Button>,
        ]}
        className="feedback-modal"
      >
        <div className="py-4 flex flex-col gap-4">
          <Text className="text-xs text-[var(--app-text-soft)] font-semibold">
            Why did you find this answer not helpful?
          </Text>
          <Radio.Group
            onChange={(e) => setSelectedReason(e.target.value)}
            value={selectedReason}
            className="w-full"
          >
            <div className="flex flex-col gap-2.5">
              {[
                "Incorrect Answer",
                "Missing Information",
                "Irrelevant Answer",
                "Hallucination",
                "Other"
              ].map((reason) => (
                <Radio key={reason} value={reason} className="text-[var(--app-text)] font-medium block !m-0">
                  {reason}
                </Radio>
              ))}
            </div>
          </Radio.Group>
          {selectedReason === "Other" && (
            <Input.TextArea
              placeholder="Please specify the reason..."
              value={customReason}
              onChange={(e) => setCustomReason(e.target.value)}
              rows={3}
              className="mt-2 text-[var(--app-text)] border-[var(--app-border)]/40 focus:border-[#285d91]/60"
            />
          )}
        </div>
      </Modal>

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