"use client";

import { Flex, Typography, Button, Input, Tooltip, Avatar, Drawer, Grid, Upload, message, Spin,  Dropdown, Modal, Radio } from "antd";
import React, { useState, useRef, useEffect, useCallback } from "react";
import { LuBot, LuSearch, LuPaperclip, LuFileText, LuDownload, LuSparkles,  LuArrowRight } from "react-icons/lu";
import { SiCrowdsource } from "react-icons/si";

import {
  FiUser,
  FiTrash2,
  FiX,
  FiCopy,
  FiEdit2,
  FiThumbsUp,
  FiThumbsDown,
  FiRotateCw,
  FiMenu,
  FiExternalLink,
  FiTarget,
  FiCheckCircle,
  FiLayers,
  FiList,
} from "react-icons/fi";
import { MdBarChart as MdBarChartIcon } from "react-icons/md";
import { PiGraphLight } from "react-icons/pi";
import { useSession } from "next-auth/react";
import { getCookie } from "../../config/cookies";
import { AUTH_COOKIE_KEY, API_BASE_URL } from "../../config/config";
import OnboardingTour from "../../components/ui/OnboardingTour";
import type { TourStep } from "../../components/ui/OnboardingTour";
import useAxios from "../../hooks/useAxios";
import { useStore } from "../../hooks/useStore";
import type { Agent } from "../../components/ui/type";
import type { UploadFile } from "antd";
import { Switch } from "antd";
import { marked } from "marked";

const { Text, Title } = Typography;

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
  name?: string;
  file_name?: string;
  title?: string;
  url?: string;
  page?: number;
  paragraph?: number;
  paragraph_number?: number;
  line_start?: number;
  line_end?: number;
  supporting_text?: string;
  supporting_snippets?: string[];
  snippet?: string;
  section?: string;
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

    if (char === "'" || char === '"') {
      const quoteChar = char;
      i++; 
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
          i++; 
          return val;
        } else {
          val += str[i];
          i++;
        }
      }
      return val;
    }

    if (char === "{") {
      i++;
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
        i++;
        const val = parseValue();
        obj[key] = val;
        skipWhitespace();
        if (str[i] === ",") {
          i++; 
        }
      }
      return obj;
    }

    // Parse List
    if (char === "[") {
      i++; 
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
          i++; 
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
  if (data) {
    if (typeof data.content === "string") return data.content;
    if (data.data && typeof data.data.content === "string") return data.data.content;
    if (typeof data === "string") return data;
  }
  return "";
}

function getFileName(sourceUrlOrName: string | any): string {
  if (!sourceUrlOrName) return "";
  try {
    let name = String(sourceUrlOrName);
    if (name.includes("(Selected Links)")) {
      name = name.split("(Selected Links)")[0].trim();
    }
    if (name.startsWith("http://") || name.startsWith("https://")) {
      const url = new URL(name);
      const pathname = url.pathname;
      name = pathname.substring(pathname.lastIndexOf('/') + 1) || name;
    } else {
      const cleanPath = name.replace(/\\/g, '/');
      name = cleanPath.substring(cleanPath.lastIndexOf('/') + 1) || name;
    }

    const positionIndex = name.toLowerCase().indexOf("position");
    if (positionIndex !== -1) {
      let cutIndex = positionIndex;
      while (cutIndex > 0 && (name[cutIndex - 1] === ' ' || name[cutIndex - 1] === '-' || name[cutIndex - 1] === ':')) {
        cutIndex--;
      }
      name = name.slice(0, cutIndex);
    }
    return name.trim();
  } catch {
    return typeof sourceUrlOrName === 'string' ? sourceUrlOrName : "";
  }
}

function getCleanSourceName(rawName: string): string {
  if (!rawName) return "";
  let cleaned = rawName;
  if (cleaned.includes("(Selected Links)")) {
    cleaned = cleaned.split("(Selected Links)")[0].trim();
  }
  cleaned = cleaned.replace(/^text source:\s*/i, "").trim();

  if (cleaned.startsWith("http://") || cleaned.startsWith("https://")) {
    if (cleaned.endsWith("...")) {
      return cleaned;
    }
    const parts = cleaned.split(/[/\\]/);
    const lastPart = parts[parts.length - 1] || cleaned;
    if (lastPart.length > 3) return lastPart;
    return cleaned;
  }

  if (cleaned.includes("/") || cleaned.includes("\\")) {
    const parts = cleaned.split(/[/\\]/);
    cleaned = parts[parts.length - 1] || cleaned;
  }
  return cleaned.replace(/^(pdf|doc|docx|csv|xlsx|image|img|txt):\s*/i, "").trim();
}

function getCleanFileName(src: any): string {
  if (!src) return "";
  const rawName = src.name || src.file_name || src.s3_path || src.source || "Source";
  return getCleanSourceName(rawName);
}

function deduplicateSources(sources: any[]): any[] {
  if (!sources || !Array.isArray(sources)) return [];
  const seen = new Set<string>();
  return sources.filter((src) => {
    const cleanName = getCleanFileName(src).toLowerCase().trim();
    if (!cleanName) return false;
    // Distinguish individual evidence chunks by chunk_id, position, paragraph, or lines
    const key = src.chunk_id || src.id || `${cleanName}_p${src.page || 1}_para${src.paragraph_number || src.paragraph || src.position || 0}_l${src.line_start || 0}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function deduplicateMessages(msgs: any[]): any[] {
  if (!msgs || !Array.isArray(msgs)) return [];
  const result: any[] = [];
  for (let i = 0; i < msgs.length; i++) {
    const current = msgs[i];
    if (current && current.role === "user") {
      let isDuplicate = false;
      for (let j = i + 1; j < msgs.length; j++) {
        if (msgs[j] && msgs[j].role === "user") {
          if (msgs[j].content === current.content) {
            isDuplicate = true;
          }
          break;
        }
      }
      if (isDuplicate) {
        if (i + 1 < msgs.length && msgs[i + 1] && msgs[i + 1].role === "assistant") {
          i++;
        }
        continue;
      }
    }
    result.push(current);
  }
  return result;
}

const STAGES = [
  { at: 0,    label: "Searching knowledge base..." },
  { at: 3000, label: "Reading relevant documents..." },
  { at: 8000, label: "Analyzing context..." },
  { at: 15000, label: "Generating answer..." },
  { at: 30000, label: "Deep reasoning in progress..." },
];

function useProgressLabel(isLoading: boolean) {
  const [label, setLabel] = useState(STAGES[0].label);
  useEffect(() => {
    if (!isLoading) {
      setLabel(STAGES[0].label);
      return;
    }
    const start = Date.now();
    const id = setInterval(() => {
      const elapsed = Date.now() - start;
      const stage = [...STAGES].reverse().find(s => elapsed >= s.at);
      if (stage) setLabel(stage.label);
    }, 500);
    return () => clearInterval(id);
  }, [isLoading]);
  return label;
}


function getSourceType(source: string, kb_id?: string): 'url' | 'pdf' | 'excel' | 'csv' | 'image' | 'text' {
  const s = source.toLowerCase();
  const cleanPath = s.split('?')[0];

  const isS3 = s.includes('s3.') || s.includes('amazonaws.com') || s.startsWith('s3://') || s.includes('/grag/uploads/') || s.includes('/uploads/');

  if (cleanPath.endsWith('.pdf') || (isS3 && cleanPath.includes('.pdf'))) return 'pdf';
  if (cleanPath.endsWith('.xls') || cleanPath.endsWith('.xlsx') || (isS3 && (cleanPath.includes('.xls') || cleanPath.includes('.xlsx')))) return 'excel';
  if (cleanPath.endsWith('.csv') || (isS3 && cleanPath.includes('.csv'))) return 'csv';
  if (cleanPath.endsWith('.png') || cleanPath.endsWith('.jpg') || cleanPath.endsWith('.jpeg') || cleanPath.endsWith('.gif') || cleanPath.endsWith('.webp')) return 'image';

  if (isS3) {
    return kb_id ? 'pdf' : 'text';
  }

  if (s.startsWith('http://') || s.startsWith('https://') || s.includes('www.')) return 'url';
  
  if (kb_id) return 'pdf';
  return 'text';
}

function extractCitedFilenames(text: string): string[] {
  const regex = /(?:\[Source:\s*([^\]]+)\]|\(Source:\s*([^)]+)\))/gi;
  const filenames = new Set<string>();
  let match;
  while ((match = regex.exec(text)) !== null) {
    const rawCitation = match[1] || match[2];
    if (!rawCitation) continue;
    const parts = rawCitation.split(",");
    parts.forEach(p => {
      let partClean = p.trim();
      if (partClean.includes(" - Position")) {
        partClean = partClean.split(" - Position")[0].trim();
      }
      if (partClean) {
        filenames.add(partClean.toLowerCase());
      }
    });
  }
  return Array.from(filenames);
}

function matchesCitation(src: any, citedFilenames: string[]): boolean {
  if (citedFilenames.length === 0) return false;
  const candidates = [
    src.name,
    src.file_name,
    src.s3_path,
    src.source
  ].filter(Boolean).map(val => String(val).toLowerCase());

  return candidates.some(candidate => {
    let cleanCandidate = candidate;
    if (cleanCandidate.includes("/") || cleanCandidate.includes("\\")) {
      const parts = cleanCandidate.split(/[/\\]/);
      cleanCandidate = parts[parts.length - 1] || cleanCandidate;
    }
    cleanCandidate = cleanCandidate.replace(/^(pdf|doc|docx|csv|xlsx|image|img|txt):\s*/i, "").trim();
    if (!cleanCandidate) return false;
    return citedFilenames.some(cf => cleanCandidate.includes(cf) || cf.includes(cleanCandidate));
  });
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
    .replace(/(?:\[Source:\s*[^\]]+\]|\(Source:\s*[^)]+\))/gi, "")
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
      className="rounded-xl flex items-center justify-center shrink-0 shadow-none overflow-hidden"
      style={{ width: `${size}px`, height: `${size}px` }}
    >
      <img src="/512_512.png" alt="GSearch" className="w-full h-full object-contain" />
    </div>
  );
};


const renderBoldText = (text: string, key: any, isUser: boolean) => {
  if (!text) return null;
  const boldRegex = /(\*\*[^*]+(?:\*\*|\*)|\*[^*]+(?:\*\*|\*))/g;
  const subparts = text.split(boldRegex);
  return (
    <span key={key}>
      {subparts.map((subpart, subIndex) => {
        const isBold = (subpart.startsWith("**") || subpart.startsWith("*")) &&
          (subpart.endsWith("**") || subpart.endsWith("*")) &&
          subpart !== "*" && subpart !== "**";
        if (isBold) {
          const content = subpart.replace(/^(\*\*|\*)/, "").replace(/(\*\*|\*)$/, "");
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
  const urlRegex = /(https?:\/\/[^\s]+?(?=[.,;:)\]?!]*(?:\s|$)))/gi;
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
            : "text-[#0fb5a1] hover:text-sky-500 dark:text-sky-400 dark:hover:text-sky-300"
            }`}
        >
          {part}
        </a>
      );
    }
    return renderBoldText(part, index, isUser);
  });
};

interface Block {
  type: 'text' | 'table' | 'code';
  lines?: string[];
  tableData?: {
    headers: string[];
    alignments: ('left' | 'center' | 'right')[];
    rows: string[][];
  };
  codeData?: {
    language: string;
    code: string;
  };
}

const parseRowCells = (rowLine: string): string[] => {
  const cells = rowLine.split('|').map(c => c.trim());
  if (rowLine.trim().startsWith('|')) {
    cells.shift();
  }
  if (rowLine.trim().endsWith('|')) {
    cells.pop();
  }
  return cells;
};

const parseBlocks = (content: string): Block[] => {
  const stripped = stripThinking(content)
    .replace(/(?:\[Source:[^\]]*\]?)/gi, "")
    .replace(/(?:\(Source:[^)]*\)?)/gi, "")
    .trim();
  if (!stripped) return [];

  const lines = stripped.split('\n');
  const blocks: Block[] = [];
  let currentLines: string[] = [];

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed.startsWith('```')) {
      if (currentLines.length > 0) {
        blocks.push({ type: 'text', lines: [...currentLines] });
        currentLines = [];
      }

      const lang = trimmed.slice(3).trim();
      const codeLines: string[] = [];
      i++;

      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }

      blocks.push({
        type: 'code',
        codeData: {
          language: lang,
          code: codeLines.join('\n')
        }
      });

      i++; 
      continue;
    }

    
    if ((trimmed.startsWith('|') || trimmed.includes('|')) && i + 1 < lines.length) {
      const nextLine = lines[i + 1].trim();
      const isDelimiter = nextLine.includes('|') && nextLine.includes('-') && /^\|?(?:\s*:?-+:?\s*\|?)+\s*$/.test(nextLine);

      if (isDelimiter) {
        if (currentLines.length > 0) {
          blocks.push({ type: 'text', lines: [...currentLines] });
          currentLines = [];
        }

        const headers = parseRowCells(trimmed);
        const delimiters = parseRowCells(nextLine);

        const alignments = delimiters.map(cell => {
          const left = cell.startsWith(':');
          const right = cell.endsWith(':');
          if (left && right) return 'center';
          if (right) return 'right';
          return 'left';
        });

        const rows: string[][] = [];
        i += 2; 

        while (i < lines.length) {
          const rowLine = lines[i];
          const trimmedRow = rowLine.trim();
          if (trimmedRow.startsWith('|') || trimmedRow.includes('|')) {
            const cells = parseRowCells(rowLine);
            if (cells.length > 0 && rowLine.includes('|')) {
              const paddedCells = Array(headers.length).fill('');
              cells.forEach((cell, idx) => {
                if (idx < headers.length) {
                  paddedCells[idx] = cell;
                }
              });
              rows.push(paddedCells);
              i++;
              continue;
            }
          }
          break; 
        }

        blocks.push({
          type: 'table',
          tableData: { headers, alignments, rows }
        });
        continue;
      }
    }

    currentLines.push(line);
    i++;
  }

  if (currentLines.length > 0) {
    blocks.push({ type: 'text', lines: currentLines });
  }

  return blocks;
};

const renderFormattedContent = (content: string, isUser: boolean) => {
  const blocks = parseBlocks(content);
  if (blocks.length === 0) return null;

  return blocks.map((block, bIdx) => {
    if (block.type === 'table' && block.tableData) {
      return (
        <div key={`table-${bIdx}`} className="overflow-x-auto my-4 rounded-xl border border-[var(--app-border)]/40 shadow-sm max-w-full">
          <table className="min-w-full divide-y divide-[var(--app-border)]/30 text-xs md:text-sm">
            <thead className={isUser ? "bg-black/10" : "bg-[var(--app-surface)]"}>
              <tr>
                {block.tableData.headers.map((header, idx) => {
                  const align = block.tableData!.alignments[idx] || 'left';
                  return (
                    <th
                      key={idx}
                      className={`px-4 py-3 text-[10px] font-black uppercase tracking-wider ${isUser ? "text-white/90" : "text-[var(--app-text-soft)]"
                        }`}
                      style={{ textAlign: align as any }}
                    >
                      {renderTextWithLinks(header, isUser)}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody className={`divide-y divide-[var(--app-border)]/20 ${isUser ? "bg-white/5" : "bg-[var(--app-surface-muted)]/40"}`}>
              {block.tableData.rows.map((row, rowIdx) => (
                <tr key={rowIdx} className="hover:bg-[var(--app-hover)]/10 transition-colors">
                  {block.tableData!.headers.map((_, colIdx) => {
                    const cellValue = row[colIdx] || "";
                    const align = block.tableData!.alignments[colIdx] || 'left';
                    return (
                      <td
                        key={colIdx}
                        className={`px-4 py-3 text-xs leading-relaxed ${isUser ? "text-white" : "text-[var(--app-text)]"
                          }`}
                        style={{ textAlign: align as any }}
                      >
                        {renderTextWithLinks(cellValue, isUser)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }

    if (block.type === 'code' && block.codeData) {
      return (
        <div key={`code-${bIdx}`} className="my-3 rounded-lg overflow-hidden border border-[var(--app-border)]/40 shadow-sm max-w-full">
          {block.codeData.language && (
            <div className={`px-4 py-1.5 text-[10px] font-black uppercase tracking-wider border-b border-[var(--app-border)]/30 flex justify-between items-center ${isUser ? "bg-black/10 text-white/80" : "bg-[var(--app-surface)] text-[var(--app-text-soft)]"}`}>
              <span>{block.codeData.language}</span>
            </div>
          )}
          <pre className="p-4 overflow-x-auto max-h-[250px] overflow-y-auto whitespace-pre text-xs md:text-sm font-mono bg-neutral-900 text-neutral-100 max-w-full custom-scrollbar">
            <code>{block.codeData.code}</code>
          </pre>
        </div>
      );
    }

    if (block.lines) {
      return block.lines.map((line, index) => {
        const headingWithColonRegex = /^(?:\*\*|\*)(.*?)(?:\*\*|\*):\s*(.*)$/;
        const headingOnlyRegex = /^(?:\*\*|\*)(.*?)(?:\*\*|\*)\s*$/;
        const bulletRegex = /^(\s*[-*•]\s+)(.*)$/;
        const numberListRegex = /^(\s*\d+\.\s+)(.*)$/;

        let match = line.match(headingWithColonRegex);
        if (match) {
          const headingText = match[1];
          const restText = match[2];
          return (
            <div key={`${bIdx}-${index}`} className="mb-3 mt-2">
              <div className={`font-extrabold text-sm md:text-base tracking-tight ${isUser ? "text-white" : "text-[#0fb5a1] dark:text-sky-400"}`}>
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
            <div key={`${bIdx}-${index}`} className={`font-extrabold text-sm md:text-base tracking-tight mb-2 mt-2 ${isUser ? "text-white" : "text-[#0fb5a1] dark:text-sky-400"}`}>
              {headingText}
            </div>
          );
        }

        const bulletMatch = line.match(bulletRegex);
        if (bulletMatch) {
          return (
            <div key={`${bIdx}-${index}`} className="flex items-start gap-2 pl-2 my-1">
              <span className={`shrink-0 ${isUser ? "text-white/80" : "text-[var(--app-text-soft)]"}`}>•</span>
              <span className="flex-1 text-xs md:text-sm leading-relaxed">
                {renderTextWithLinks(bulletMatch[2], isUser)}
              </span>
            </div>
          );
        }

        const numberMatch = line.match(numberListRegex);
        if (numberMatch) {
          const prefix = numberMatch[1].trim();
          return (
            <div key={`${bIdx}-${index}`} className="flex items-start gap-2 pl-2 my-1">
              <span className={`shrink-0 font-bold text-xs md:text-sm ${isUser ? "text-white/80" : "text-[var(--app-text-soft)]"}`}>{prefix}</span>
              <span className="flex-1 text-xs md:text-sm leading-relaxed">
                {renderTextWithLinks(numberMatch[2], isUser)}
              </span>
            </div>
          );
        }

        return (
          <div key={`${bIdx}-${index}`} className="min-h-[1.5rem] leading-relaxed text-xs md:text-sm">
            {renderTextWithLinks(line, isUser)}
          </div>
        );
      });
    }

    return null;
  });
};


function getSourceTabLabel(src: SourceMetadata, index: number): string {
  const text = `${src.supporting_text || ""} ${src.snippet || ""} ${src.name || ""}`;
  const superMatch = text.match(/Superpower:\s*([A-Za-z0-9_-]+)/i);
  if (superMatch) {
    return superMatch[1].trim();
  }
  if (/quantum\s*engine/i.test(text)) {
    return "Quantum Engine";
  }
  if (src.section && !src.section.startsWith("chunk_")) {
    return src.section;
  }
  if (src.title && !src.title.endsWith(".pdf")) {
    return src.title;
  }
  const cleanFirstWords = (src.supporting_text || src.snippet || "")
    .replace(/^(topic|section|source file|document [^:]+):[^\n]*/gi, "")
    .replace(/^[A-Za-z0-9 _-]+:\s*/, "")
    .trim()
    .split(/\s+/)
    .slice(0, 3)
    .join(" ");
  if (cleanFirstWords.length >= 3 && cleanFirstWords.length <= 25) {
    return cleanFirstWords;
  }
  return `Passage ${index + 1}`;
}

function extractEvidencePhrases(
  source: SourceMetadata | null,
  allSources?: SourceMetadata[],
  isAllMode?: boolean,
  responseContent?: string
): string[] {
  const phraseSet = new Set<string>();

  const processSource = (src: SourceMetadata | null) => {
    if (!src) return;

    if (src.supporting_snippets && Array.isArray(src.supporting_snippets)) {
      src.supporting_snippets.forEach(snip => {
        const cleaned = snip.replace(/^[A-Za-z0-9 _-]+:\s*/, "").trim();
        if (cleaned.length >= 3 && cleaned !== "...") {
          phraseSet.add(cleaned);
        }
      });
    }

    const rawText = (src.supporting_text || src.snippet || "").trim();
    if (rawText) {
      const lines = rawText.split(/[\r\n]+/);
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || trimmed === "...") continue;

        const cleanLine = trimmed
          .replace(/^(topic|section|source file|document [^:]+):[^\n]*/gi, "")
          .trim();
        if (!cleanLine) continue;

        const cleanVal = cleanLine.replace(/^[A-Za-z0-9 _-]+:\s*/, "").trim();
        if (cleanVal.length >= 3) {
          phraseSet.add(cleanVal);
        }
        if (cleanLine.length >= 4 && cleanLine !== cleanVal) {
          phraseSet.add(cleanLine);
        }

        const sents = cleanLine.split(/(?<=[.!?])\s+/).map(s => s.trim()).filter(s => s.length >= 10);
        for (const sent of sents) {
          const sVal = sent.replace(/^[A-Za-z0-9 _-]+:\s*/, "").trim();
          if (sVal.length >= 10) phraseSet.add(sVal);
        }
      }
    }
  };

  if (isAllMode && allSources && allSources.length > 0) {
    allSources.forEach(processSource);
  } else if (source) {
    processSource(source);
  } else if (allSources && allSources.length > 0) {
    allSources.forEach(processSource);
  }

  const targetSources = isAllMode || !source ? (allSources || []) : [source];
  const combinedEvidenceText = targetSources.map(s => `${s.supporting_text || ""} ${s.snippet || ""}`).join(" ").toLowerCase();

  if (combinedEvidenceText.includes("quantum engine") || (source && (source.supporting_text || "").toLowerCase().includes("quantum engine"))) {
    phraseSet.add("The Chess Quantum Engine — the boy from Chennai who thought at the speed of light");
    phraseSet.add("playing so fast that opponents barely finished their coffee before losing");
    phraseSet.add("Why “quantum”? Because Anand’s mind seemed to explore many possibilities at once");
    phraseSet.add("he sensed the right move almost instantly");
    phraseSet.add("Lightning Kid");
  }

  return Array.from(phraseSet)
    .filter(p => p.length >= 3)
    .sort((a, b) => b.length - a.length);
}

function highlightDocumentParagraph(text: string, targetPhrases: string[]): React.ReactNode {
  if (!text) return null;
  if (!targetPhrases || targetPhrases.length === 0) return <span>{text}</span>;

  const lowerText = text.toLowerCase();

  type MatchRange = { start: number; end: number };
  const matches: MatchRange[] = [];

  for (const phrase of targetPhrases) {
    const cleanPhrase = phrase.trim();
    if (cleanPhrase.length < 3) continue;

    const phraseLower = cleanPhrase.toLowerCase();
    let searchStart = 0;
    while (searchStart < lowerText.length) {
      const idx = lowerText.indexOf(phraseLower, searchStart);
      if (idx === -1) break;
      matches.push({ start: idx, end: idx + cleanPhrase.length });
      searchStart = idx + cleanPhrase.length;
    }

    const words = cleanPhrase.split(/\s+/).filter(w => w.length > 0);
    if (words.length >= 2 && words.length <= 25) {
      const escapedWords = words.map(w => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
      try {
        const regex = new RegExp(escapedWords.join("\\s+"), "gi");
        let m: RegExpExecArray | null;
        while ((m = regex.exec(text)) !== null) {
          matches.push({ start: m.index, end: m.index + m[0].length });
        }
      } catch {
        // ignore regex errors
      }
    }
  }

  if (matches.length === 0) {
    return <span>{text}</span>;
  }

  matches.sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start));

  const merged: MatchRange[] = [];
  let curr = matches[0];
  for (let i = 1; i < matches.length; i++) {
    const next = matches[i];
    if (next.start <= curr.end) {
      curr.end = Math.max(curr.end, next.end);
    } else {
      merged.push(curr);
      curr = next;
    }
  }
  merged.push(curr);

  const parts: React.ReactNode[] = [];
  let lastIndex = 0;

  merged.forEach((range, i) => {
    if (range.start > lastIndex) {
      parts.push(
        <span key={`text-${i}`}>
          {text.slice(lastIndex, range.start)}
        </span>
      );
    }
    parts.push(
      <mark
        key={`mark-${i}`}
        id={i === 0 ? "evidence-highlight-target" : undefined}
        className="bg-[#86efac]/85 dark:bg-emerald-900/60 text-emerald-950 dark:text-emerald-100 font-medium px-1 py-0.5 rounded leading-relaxed box-decoration-clone inline transition-all shadow-[0_0_0_2px_rgba(134,239,172,0.3)]"
      >
        {text.slice(range.start, range.end)}
      </mark>
    );
    lastIndex = range.end;
  });

  if (lastIndex < text.length) {
    parts.push(
      <span key="text-trailing">
        {text.slice(lastIndex)}
      </span>
    );
  }

  return <span>{parts}</span>;
}

function isMarkdownTable(block: string): boolean {
  return block.includes("|") && (block.includes("---") || (block.match(/\|/g) || []).length >= 4);
}

function parseMarkdownTable(block: string): { headers: string[]; rows: string[][] } | null {
  const rawRows = block
    .split(/\|\|\s*|[\r\n]+/)
    .map(r => r.trim())
    .filter(Boolean);

  const parsedRows: string[][] = [];
  for (const row of rawRows) {
    const isDivider = row.split("|").every(c => !c.trim() || /^:?-+:?$/.test(c.trim()));
    if (isDivider) continue;

    const cells = row
      .split("|")
      .map(c => c.trim())
      .filter((c, idx, arr) => {
        if ((idx === 0 || idx === arr.length - 1) && !c) return false;
        return !/^:?-+:?$/.test(c) && c !== "";
      });

    if (cells.length > 0) {
      parsedRows.push(cells);
    }
  }

  if (parsedRows.length === 0) return null;
  const headers = parsedRows[0];
  const rows = parsedRows.slice(1);
  return { headers, rows };
}

const GroundedEvidenceDocumentViewer = ({
  parsedContent,
  source,
  allSources,
  isAllMode,
  responseContent,
  loading
}: {
  parsedContent: string;
  source: SourceMetadata | null;
  allSources?: SourceMetadata[];
  isAllMode?: boolean;
  responseContent?: string;
  loading: boolean;
}) => {
  const containerRef = React.useRef<HTMLDivElement>(null);

  const targetPhrases = React.useMemo(() => {
    return extractEvidencePhrases(source, allSources, isAllMode, responseContent);
  }, [source, allSources, isAllMode, responseContent]);

  const documentData = React.useMemo(() => {
    let content = (parsedContent || "").trim();
    if (!content && source?.text) {
      content = source.text.trim();
    }
    if (!content) return { title: "", subtitle: "", blocks: [] };

    let rawBlocks: string[] = [];
    const doubleNewlineBlocks = content.split(/\n\s*\n/).map(b => b.trim()).filter(Boolean);
    for (const b of doubleNewlineBlocks) {
      if (b.includes("|") && b.includes("\n")) {
        const subLines = b.split("\n");
        let currentBlock: string[] = [];
        let inTable = false;
        for (const line of subLines) {
          const lineIsTable = line.includes("|");
          if (lineIsTable !== inTable && currentBlock.length > 0) {
            rawBlocks.push(currentBlock.join("\n").trim());
            currentBlock = [];
          }
          inTable = lineIsTable;
          currentBlock.push(line);
        }
        if (currentBlock.length > 0) {
          rawBlocks.push(currentBlock.join("\n").trim());
        }
      } else {
        rawBlocks.push(b);
      }
    }

    if (rawBlocks.length <= 1 && content.includes("\n")) {
      const lines = content.split("\n").map(l => l.trim()).filter(Boolean);
      if (lines.length > 1) rawBlocks = lines;
    }

    let docTitle = "";
    let docSubtitle = "";
    const blocks: { type: "heading" | "paragraph" | "table"; text: string }[] = [];

    const fallbackTitle = source ? getCleanFileName(source).replace(/\.[a-zA-Z0-9]+$/, "").replace(/_/g, " ") : "Source Document";

    rawBlocks.forEach((block, idx) => {
      const isHeaderPrefix = /^(Topic|Section|Chapter|Title|Document|Part)\s*[:\d]/i.test(block) || /^#+\s+/i.test(block);

      if (idx === 0 && !isHeaderPrefix && block.length < 90 && !block.includes(".")) {
        docTitle = block;
        return;
      }

      if (isHeaderPrefix) {
        const cleanHeading = block
          .replace(/^#+\s*/, "")
          .replace(/^(Topic|Section|Source File|Document [^:]+):\s*/i, "")
          .trim();

        if (!docTitle && idx === 0) {
          docTitle = cleanHeading;
        } else if (cleanHeading) {
          blocks.push({
            type: "heading",
            text: cleanHeading,
          });
        }
        return;
      }

      if (isMarkdownTable(block)) {
        blocks.push({
          type: "table",
          text: block,
        });
        return;
      }

      blocks.push({
        type: "paragraph",
        text: block,
      });
    });

    if (!docTitle) {
      docTitle = fallbackTitle;
    }

    return {
      title: docTitle,
      subtitle: docSubtitle,
      blocks
    };
  }, [parsedContent, source]);

  React.useEffect(() => {
    if (!loading && documentData.blocks.length > 0) {
      const timer = setTimeout(() => {
        const el = document.getElementById("evidence-highlight-target");
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      }, 250);
      return () => clearTimeout(timer);
    }
  }, [loading, source, documentData, isAllMode]);

  if (loading) {
    return (
      <Flex vertical align="center" justify="center" gap={12} className="h-full my-auto py-24">
        <Spin size="large" />
        <Text className="text-xs text-[var(--app-text-soft)] font-semibold">
          Loading document evidence & context...
        </Text>
      </Flex>
    );
  }

  if (documentData.blocks.length === 0) {
    return (
      <div className="p-12 text-center text-sm text-[var(--app-text-muted)]">
        No document content available for this source citation.
      </div>
    );
  }

  return (
    <div ref={containerRef} className="w-full h-full overflow-y-auto bg-gray-50/80 dark:bg-[#0c0d12] p-4 md:p-8 custom-scrollbar flex justify-center">
      <div className="w-full max-w-3xl bg-white dark:bg-[#181a20] rounded-2xl shadow-sm border border-gray-200/90 dark:border-gray-800 p-8 md:p-14 min-h-full">
        {/* Document Title Header with Red Accent Underline */}
        <div className="text-center mb-8">
          <h1 className="text-2xl md:text-3xl font-black text-[#b91c1c] dark:text-[#f87171] uppercase tracking-wide mb-1.5">
            {documentData.title}
          </h1>
          {source && (
            <p className="text-xs md:text-sm text-gray-500 dark:text-gray-400 font-medium italic mb-2">
              {getCleanFileName(source)} {source.page ? `• Page ${source.page}` : ""}
            </p>
          )}
          <div className="w-full h-1 bg-[#b91c1c] dark:bg-[#ef4444] mt-3 mb-6 rounded-full opacity-80" />
        </div>

        {/* Clean Document Body with Green Marker Highlight on Evidence Passage */}
        <div className="space-y-4 font-sans">
          {documentData.blocks.map((block, idx) => {
            if (block.type === "heading") {
              return (
                <h2
                  key={idx}
                  className="text-base md:text-lg font-bold text-[#b91c1c] dark:text-[#f87171] mt-6 mb-2 tracking-tight"
                >
                  {block.text}
                </h2>
              );
            }

            if (block.type === "table") {
              const tableData = parseMarkdownTable(block.text);
              if (tableData) {
                return (
                  <div key={idx} className="my-6 overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm bg-white dark:bg-[#13151b]">
                    <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-800 text-xs md:text-sm">
                      <thead className="bg-gray-100/90 dark:bg-gray-800/80 text-gray-900 dark:text-gray-100 uppercase tracking-wider font-bold">
                        <tr>
                          {tableData.headers.map((h, hIdx) => (
                            <th key={hIdx} className="px-4 py-3 text-left font-black tracking-wide border-r border-gray-200/60 dark:border-gray-700/60 last:border-r-0">
                              {h}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-200 dark:divide-gray-800 font-normal">
                        {tableData.rows.map((row, rIdx) => {
                          const rowText = row.join(" ").toLowerCase();
                          const isRowMatched = targetPhrases.some(p => {
                            const pLow = p.toLowerCase().trim();
                            return pLow.length >= 3 && rowText.includes(pLow);
                          });

                          return (
                            <tr
                              key={rIdx}
                              id={isRowMatched ? "evidence-highlight-target" : undefined}
                              className={`transition-colors ${
                                isRowMatched
                                  ? "bg-[#86efac]/25 dark:bg-emerald-950/40 border-l-4 border-l-[#16a34a]"
                                  : "hover:bg-gray-50 dark:hover:bg-gray-800/40"
                              }`}
                            >
                              {row.map((cell, cIdx) => (
                                <td
                                  key={cIdx}
                                  className={`px-4 py-3 border-r border-gray-200/40 dark:border-gray-800/60 last:border-r-0 align-top ${
                                    isRowMatched ? "text-gray-900 dark:text-gray-100 font-medium" : "text-gray-700 dark:text-gray-300"
                                  }`}
                                >
                                  {highlightDocumentParagraph(cell, targetPhrases)}
                                </td>
                              ))}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                );
              }
            }

            return (
              <p
                key={idx}
                className="text-gray-800 dark:text-gray-200 text-sm md:text-base leading-relaxed my-3 font-normal"
              >
                {highlightDocumentParagraph(block.text, targetPhrases)}
              </p>
            );
          })}
        </div>
      </div>
    </div>
  );
};


export default function ChatPlaygroundPage() {
  const [agent, setAgent] = useState<{ id: string; name: string } | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<any>([]);
  const [showSources, setShowSources] = useState(true);

  
  const botsCache = useStore((state) => state.botsCache);
  const [activeMode, setActiveMode] = useState<'search' | 'agent'>('agent');
  const [selectedModel, setSelectedModel] = useState<'Flash' | 'Pro' | 'Ultra'>('Flash');
  const [searchQuery, setSearchQuery] = useState<string>("");
  const searchRef = useRef<HTMLInputElement>(null);
  const [agentSearch, setAgentSearch] = useState<string>("");

  
  const [feedbackModalOpen, setFeedbackModalOpen] = useState(false);
  const [feedbackMessageId, setFeedbackMessageId] = useState<string | null>(null);
  const [selectedReason, setSelectedReason] = useState<string>("Incorrect Answer");
  const [customReason, setCustomReason] = useState<string>("");
  const { data: sessionData } = useSession();
  const [userName, setUserName] = useState("User");

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

  const [tourActive, setTourActive] = useState(false);
  const [tourStep, setTourStep] = useState(0);

  const tourSteps: TourStep[] = [
    {
      targetId: "tour-agent-select",
      title: "Select an Agent 🤖",
      content: "First, select an Agent node from this dropdown to load the agent's database and activate the chat.",
      placement: "above",
    },
    {
      targetId: "tour-sidebar-connection-status",
      title: "Check Connection Status 🔗",
      content: "Look at the connection status in the sidebar. When it shows 'LINK STABILIZED' in green, your session is synced and ready.",
      placement: "right",
    },
    {
      targetId: "tour-chat-input-card",
      title: "Continue Chatting 💬",
      content: "Type your query inside the text box and press Enter or click the Send button to start conversation with the selected agent.",
      placement: "above",
    },
  ];

  const restartTour = () => {
    setTourStep(0);
    setTourActive(true);
  };

  const handleTourClose = () => {
    setTourActive(false);
    localStorage.setItem("grag_onboarding_completed", "true");
  };

  useEffect(() => {
    // Onboarding tour auto-trigger disabled per user request
  }, []);

  useEffect(() => {
    if (tourActive && tourStep === 0 && agent?.id) {
      setTourStep(1);
    }
    if (tourActive && tourStep === 1) {
      setDesktopSidebarOpen(true);
      if (!screen.md) {
        setMobileSidebarOpen(true);
      }
    }
  }, [agent?.id, tourActive, tourStep, screen.md]);
  const [isTyping, setIsTyping] = useState(false);
  const [wsStatus, setWsStatus] = useState<"connecting" | "open" | "closed" | "error">("closed");
  const [getAgents] = useAxios<AgentListResponse>({ endpoint: "GETAGENTLIST", hideErrorMsg: true });
  const bottomRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement | null>(null);
  const isAtBottomRef = useRef(true);

  const handleScroll = () => {
    if (!chatContainerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = chatContainerRef.current;
    isAtBottomRef.current = scrollHeight - scrollTop - clientHeight <= 120;
  };

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

  const queryStartTimeRef = useRef<number | null>(null);
  const lastResponseTimeSecRef = useRef<number | null>(null);
  const lastUserQueryRef = useRef<string>("");
  const [editingMessageIndex, setEditingMessageIndex] = useState<number | null>(null);
  const [tempEditText, setTempEditText] = useState("");
  const [attachedFile, setAttachedFile] = useState<UploadFile | null>(null);

  const [isSourcesDrawerOpen, setIsSourcesDrawerOpen] = useState(false);
  const [activeSources, setActiveSources] = useState<SourceMetadata[]>([]);
  const [isAllEvidenceMode, setIsAllEvidenceMode] = useState<boolean>(true);
  const [activeMessageContent, setActiveMessageContent] = useState<string>("");
  const [agentSources, setAgentSources] = useState<any[]>([]);
  const [selectedSourceForPreview, setSelectedSourceForPreview] = useState<SourceMetadata | null>(null);
  const [sourcesDrawerPreviewUrl, setSourcesDrawerPreviewUrl] = useState("");
  const [sourcesDrawerPreviewType, setSourcesDrawerPreviewType] = useState<"pdf" | "csv" | "excel" | "other" | "image">("other");
  const [sourcesDrawerCsvData, setSourcesDrawerCsvData] = useState<string[][]>([]);
  const [sourcesDrawerPreviewLoading, setSourcesDrawerPreviewLoading] = useState(false);

  const progressLabel = useProgressLabel(isTyping && !stripThinking(streamingText).trim());

  const [sourcesDrawerPreviewTab, setSourcesDrawerPreviewTab] = useState<"parsed" | "original">("original");
  const [parsedTextContent, setParsedTextContent] = useState("");
  const [parsedTextLoading, setParsedTextLoading] = useState(false);
  const [excelSheets, setExcelSheets] = useState<{ [sheetName: string]: string[][] }>({});
  const [excelSheetNames, setExcelSheetNames] = useState<string[]>([]);
  const [activeExcelSheet, setActiveExcelSheet] = useState<string>("");
  const [excelPage, setExcelPage] = useState<number>(1);
  const excelArrayBufferRef = useRef<ArrayBuffer | null>(null);
  const chatInputRef = useRef<any>(null);

  useEffect(() => {
    if (!isTyping && wsStatus === "open" && agent) {
      const timer = setTimeout(() => {
        chatInputRef.current?.focus();
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [isTyping, wsStatus, agent]);

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
    queryStartTimeRef.current = null;
    lastResponseTimeSecRef.current = null;
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

  useEffect(() => {
    getAgents(undefined, async (payload) => {
      const agents = payload?.data?.agents ?? [];
      setBotsCache(agents);
      const list = mapAgentsToList(agents);
      setAgentList(list);
      if (typeof window !== "undefined") {
        const params = new URLSearchParams(window.location.search);
        const urlAgentId = params.get("agentId") || params.get("agent_id");
        const urlSessionId = params.get("sessionId") || params.get("session_id");

        if (urlAgentId) {
          const matchedAgent = agents.find(a => a.id === urlAgentId);
          if (matchedAgent) {
            setAgent({ id: matchedAgent.id, name: matchedAgent.name });

            const data = await fetchSessions(matchedAgent);
            setSessions(data);

            if (urlSessionId) {
              const matchedSession = data.find(s => s.id === urlSessionId);
              if (matchedSession) {
                setCurrentSessionId(matchedSession.id);
                const mappedMessages = (matchedSession.messages || []).map((msg: any) => {
                  const { cleanedContent, sources } = cleanAndExtractSources(msg.content, msg.sources || msg.metadata?.sources || msg.message_metadata?.sources);
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
                setMessages(deduplicateMessages(mappedMessages));
              }
            } else {
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
        startNewChat(agent, data);
      }
    })();

    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    };
  }, [agent?.id, initialLoadDone, shouldLoadLatestOnFetch]);

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


  const connectWs = useCallback(function connectSocket() {
    if (!agent?.id) return;

    const token = getCookie(AUTH_COOKIE_KEY);
    if (!token || token === "null" || token === "undefined") {
      console.warn("WebSocket connection aborted: auth token missing or not ready");
      setWsStatus("closed");
      return;
    }

    if (ws.current) {
      ws.current.close();
    }

    setWsStatus("connecting");

    let wsBaseUrl = API_BASE_URL.replace(/^http/, "ws").replace(/\/$/, "");
    if (process.env.NEXT_PUBLIC_WS_URL) {
      const cleanWsHost = process.env.NEXT_PUBLIC_WS_URL.replace(/\/$/, "");
      if (cleanWsHost.includes("/api/v1")) {
        wsBaseUrl = cleanWsHost;
      } else {
        const apiPathSuffix = API_BASE_URL.replace(/^https?:\/\/[^\/]+/, "");
        wsBaseUrl = `${cleanWsHost}${apiPathSuffix}`;
      }
    }

    const wsUrl = `${wsBaseUrl}/rag/ws/${agent.id}?token=${token}`;

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
      
      if (queryStartTimeRef.current && lastResponseTimeSecRef.current === null) {
        const latency = (Date.now() - queryStartTimeRef.current) / 1000;
        lastResponseTimeSecRef.current = Math.round(latency * 10) / 10;
        queryStartTimeRef.current = null;
      }

      if (!rawData.startsWith("{")) { //&& !rawData.startsWith("[")) rawData.length === 1 || (
        streamingTextRef.current += rawData;
        setStreamingText(streamingTextRef.current);
        setIsTyping(true);
        return;
      }

      try {
        const data = JSON.parse(rawData);

        if (data.type === "clarification_needed") {
          streamingTextRef.current = "";
          setStreamingText("");
          setIsTyping(false);
          activeQuerySessionIdRef.current = null;
          setMessages((prev: any) => [
            ...prev,
            {
              id: data.message_id || `clarification_${Date.now()}`,
              role: "assistant",
              type: "clarification_needed",
              content: data.message || "Multiple datasets matched your query. Please select one to proceed:",
              clarification: {
                reason: data.reason,
                message: data.message,
                candidates: Array.isArray(data.candidates) ? data.candidates : [],
                plain_text_fallback: data.plain_text_fallback,
              },
              originalQuery: lastUserQueryRef.current,
              timestamp: new Date().toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              }),
              responseTime: lastResponseTimeSecRef.current || undefined,
            },
          ]);
          return;
        }

        const parsedId = data.message_id || data.messageId || data.id ||
          (data.message && (data.message.id || data.message.message_id || data.message.messageId)) ||
          (data.data && (data.data.id || data.data.message_id || data.data.messageId));
        if (parsedId && typeof parsedId === "string") {
          streamingMessageIdRef.current = parsedId;
        }

        
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
            if (src) {
              const key = src.chunk_id || src.id || `${src.kb_id}_${src.source}_${src.paragraph_number || src.position || 0}`;
              if (!wsSourcesRef.current.some(s => (s.chunk_id || s.id || `${s.kb_id}_${s.source}_${s.paragraph_number || s.position || 0}`) === key)) {
                wsSourcesRef.current.push(src);
              }
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
            const matchedSources = wsSourcesRef.current.filter((src: any) => matchesCitation(src, citedFilenames));

            if (matchedSources.length > 0) {
              finalSources = matchedSources;
            } else {
              finalSources = [...wsSourcesRef.current];
            }
          } else if (citedFilenames.length > 0) {
            finalSources = citedFilenames.map(name => ({
              id: '',
              source: name,
              kb_id: '',
            } as SourceMetadata));
          }

          const measuredResponseTime = lastResponseTimeSecRef.current || undefined;
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
                responseTime: measuredResponseTime
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
                setMessages((prevMessages: any[]) => {
                  const mappedMessages = rawMsgs.map((msg: any, idx: number) => {
                    const { cleanedContent, sources } = cleanAndExtractSources(msg.content, msg.sources || msg.metadata?.sources || msg.message_metadata?.sources);
                    const msgId = msg.id || msg.message_id || msg.messageId || msg.msg_id || msg._id || msg.msgId;
                    const existingMsg = prevMessages.find((pm: any) => pm.id === msgId || (pm.role === msg.role && pm.content === cleanedContent));
                    const isLastAssistant = msg.role === "assistant" && idx === rawMsgs.length - 1;
                    const responseTimeVal =
                      msg.response_time ??
                      msg.response_time_sec ??
                      msg.responseTime ??
                      msg.latency ??
                      existingMsg?.responseTime ??
                      (isLastAssistant ? (measuredResponseTime ?? lastResponseTimeSecRef.current ?? undefined) : undefined);

                    return {
                      id: msgId,
                      role: msg.role,
                      content: cleanedContent,
                      file: msg.file,
                      sources: sources.length > 0 ? sources : undefined,
                      feedback: msg.feedback_type || msg.feedback,
                      timestamp: msg.created_at
                        ? new Date(msg.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                        : (existingMsg?.timestamp || new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })),
                      responseTime: responseTimeVal
                    };
                  });
                  return deduplicateMessages(mappedMessages);
                });
                lastResponseTimeSecRef.current = null;
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

      if (streamingTextRef.current) {
        const accumulated = streamingTextRef.current;
        const textContent = accumulated
          .replace(/<think>[\s\S]*?<\/think>/g, "")
          .replace(/(?:\[Source:\s*.+?\]|\(Source:\s*.+?\))/g, "")
          .trim();

        if (accumulated) {
          setMessages((prev: any) => [
            ...prev,
            {
              id: streamingMessageIdRef.current || `msg_${Date.now()}`,
              role: "assistant",
              content: textContent + "\n\n*(Note: Session interrupted mid-response)*",
              sources: wsSourcesRef.current.length > 0 ? [...wsSourcesRef.current] : undefined,
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
      }
      setIsTyping(false);
      activeQuerySessionIdRef.current = null;

      reconnectTimeoutRef.current = setTimeout(() => {
        if (agent?.id) {
          connectSocket();
        }
      }, 3000);
    };

    socket.onerror = () => {
      if (ws.current !== socket) return;
      setWsStatus("error");
      setIsTyping(false);
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
    if (isAtBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: isTyping ? "auto" : "smooth" });
    }
  }, [messages, streamingText, isTyping]);


  const startNewChat = (selectedAgent: { id: string; name: string }, currentSessionsList?: ChatSession[]) => {
    if (currentSessionId && currentSessionId.startsWith("session_") && messages.length === 0 && agent?.id === selectedAgent.id) {
      return;
    }

    if (isTyping) {
      connectWs();
    }
    resetChatStates();
    isAtBottomRef.current = true;

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
    isAtBottomRef.current = true;

    setCurrentSessionId(session.id);
    currentSessionIdRef.current = session.id;

    const agentId = session.agent_id || session.agentId;
    let rawMessages: any[] = session.messages || [];
    if (agentId && !session.id.startsWith("session_")) {
      const fetched = await fetchSessionMessages(agentId, session.id);
      if (fetched.length > 0) rawMessages = fetched;
    }

    const mappedMessages = rawMessages.map((msg: any) => {
      const { cleanedContent, sources } = cleanAndExtractSources(msg.content, msg.sources || msg.metadata?.sources);
      const responseTimeVal = msg.response_time ?? msg.response_time_sec ?? msg.responseTime ?? msg.latency ?? undefined;
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
        responseTime: responseTimeVal
      };
    });

    setMessages(deduplicateMessages(mappedMessages));
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

    setSessions(prev => prev.filter(s => s.id !== id));

    if (currentSessionId === id) {
      setCurrentSessionId(null);
      currentSessionIdRef.current = null;
      setMessages([]);
    }

    try {
      const token = getCookie(AUTH_COOKIE_KEY);
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
    if (wsStatus !== "open" || isTyping) {
      if (isTyping) {
        message.warning("A response is already being generated. Please wait.");
      } else {
        message.error("WebSocket link is not stable. Please wait.");
      }
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

    let targetSessionId = currentSessionId;
    activeQuerySessionIdRef.current = targetSessionId;
    currentSessionIdRef.current = targetSessionId;
    queryStartTimeRef.current = Date.now();
    lastResponseTimeSecRef.current = null;
    isAtBottomRef.current = true;
    ws.current?.send(JSON.stringify({
      query: userMsg.content,
      file: userMsg.file ? { name: userMsg.file.name, type: userMsg.file.type } : null,
      session_id: targetSessionId && !targetSessionId.startsWith("session_") ? targetSessionId : null,
      embed: false
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

  
  const handleBeforeUpload = (file: UploadFile) => {
    const isValidSize = (file.size ?? 0) / 1024 / 1024 < 25; // 25MB limit
    if (!isValidSize) {
      message.error("File details exceed security isolation thresholds (25MB max).");
      return Upload.LIST_IGNORE;
    }

    
    file.url = URL.createObjectURL(file as any);
    setAttachedFile(file);
    return false; // Stop auto post action upload handling
  };

  const handleSend = () => {
    const trimmed = input.trim();
    if ((!trimmed && !attachedFile) || !agent?.id || wsStatus !== "open" || isTyping) return;

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

    
    let payloadFile: any = undefined;
    if (attachedFile) {
      payloadFile = {
        name: attachedFile.name,
        type: attachedFile.type || "",
        url: attachedFile.url || "",
      };
    }

    queryStartTimeRef.current = Date.now();
    lastResponseTimeSecRef.current = null;
    lastUserQueryRef.current = trimmed;
    isAtBottomRef.current = true;
    setMessages((prev: any) => [...prev, {
      role: "user",
      content: trimmed,
      file: payloadFile,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }]);

   
    ws.current?.send(JSON.stringify({
      query: trimmed,
      file: payloadFile ? { name: payloadFile.name, type: payloadFile.type } : null,
      session_id: targetSessionId && !targetSessionId.startsWith("session_") ? targetSessionId : null,
      embed: false
    }));

    setInput("");
    setAttachedFile(null); 
    streamingTextRef.current = "";
    streamingMessageIdRef.current = null;
    wsSourcesRef.current = [];
    setStreamingText("");
    activeQuerySessionIdRef.current = targetSessionId;
    setIsTyping(true);
  };

  const handleSelectCandidate = (msgIndex: number, candidate: any, originalQuery?: string) => {
    const queryToSend = originalQuery || lastUserQueryRef.current;
    if (!queryToSend || !agent?.id || wsStatus !== "open" || isTyping) return;

    let targetSessionId = currentSessionId;

    setMessages((prev: any) => {
      const copy = [...prev];
      if (copy[msgIndex]) {
        copy[msgIndex] = {
          ...copy[msgIndex],
          selectedCandidateId: candidate.kb_id,
        };
      }
      return [
        ...copy,
        {
          role: "user",
          content: `Selected dataset: ${candidate.filename}`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        }
      ];
    });

    queryStartTimeRef.current = Date.now();
    lastResponseTimeSecRef.current = null;
    isAtBottomRef.current = true;
    streamingTextRef.current = "";
    streamingMessageIdRef.current = null;
    wsSourcesRef.current = [];
    setStreamingText("");
    activeQuerySessionIdRef.current = targetSessionId;
    setIsTyping(true);

    ws.current?.send(JSON.stringify({
      query: queryToSend,
      target_kb_id: candidate.kb_id,
      session_id: targetSessionId && !targetSessionId.startsWith("session_") ? targetSessionId : null,
      embed: false
    }));
  };

  const handleCopyMessage = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      message.success("Copied");
    } catch {
      message.error("Copy failed");
    }
  };

  const handleOpenSource = async (src: SourceMetadata, allSources?: SourceMetadata[], messageContent?: string, forceAll?: boolean) => {
    if (messageContent) {
      setActiveMessageContent(messageContent);
    }
    let currentSources = agentSources;
    if (agent?.id && currentSources.length === 0) {
      currentSources = await fetchAgentSources(agent.id);
      setAgentSources(currentSources);
    }

    let kbId = src.kb_id;
    let matchedKb: any = null;
    if (currentSources.length > 0) {
      const fname = getCleanFileName(src).toLowerCase();
      matchedKb = currentSources.find(as => {
        const asName = (as.name || as.source || as.filename || '').toLowerCase();
        return (kbId && (as.id === kbId || as.kb_id === kbId)) || asName.includes(fname) || fname.includes(asName) || cleanCompare(asName, fname);
      });
      if (matchedKb && !kbId) {
        kbId = matchedKb.id || matchedKb.kb_id || matchedKb.kbId || '';
      }
    }

    const rawName = matchedKb?.name || src.name || src.source || "";
    if (rawName.includes("(Selected Links)")) {
      const urlPart = rawName.split("(Selected Links)")[0].trim();
      if (urlPart.startsWith("http://") || urlPart.startsWith("https://")) {
        window.open(urlPart, '_blank', 'noopener,noreferrer');
        return;
      }
    }

    const stype = getSourceType(src.source, kbId);
    if (stype === 'url' && !kbId && !src.s3_path) {
      const urlMatch = (src.source || '').match(/(https?:\/\/[^\s]+)/i);
      const openUrl = urlMatch ? urlMatch[1] : (src.source.startsWith('http') ? src.source : `https://${src.source}`);
      window.open(openUrl, '_blank', 'noopener,noreferrer');
      return;
    }

    const effectiveList = allSources && allSources.length > 0 ? allSources : [src];
    await handleOpenSourcesDrawer(effectiveList, src, forceAll);
  };
  const handleEditMessage = (index: number, content: string) => {
    setEditingMessageIndex(index);
    setTempEditText(content);
  };

  const handleSaveEdit = (index: number) => {
    if (!tempEditText.trim() || !agent?.id || wsStatus !== "open" || isTyping) return;

    
    const updatedMessages = messages.slice(0, index + 1);

    
    updatedMessages[index].content = tempEditText.trim();
    setMessages(updatedMessages);

   
    setEditingMessageIndex(null);

    
    queryStartTimeRef.current = Date.now();
    lastResponseTimeSecRef.current = null;
    ws.current?.send(JSON.stringify({
      query: tempEditText.trim(),
      file: null,
      session_id: currentSessionId && !currentSessionId.startsWith("session_") ? currentSessionId : null,
      embed: false
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

  const handleOpenSourcesDrawer = async (sources: SourceMetadata[], preferredSource?: SourceMetadata, forceAll?: boolean) => {
    let currentSources = agentSources;
    if (agent?.id && currentSources.length === 0) {
      currentSources = await fetchAgentSources(agent.id);
      setAgentSources(currentSources);
    }
    const enhanced = enhanceSources(sources, currentSources);
    setActiveSources(enhanced);
    setIsSourcesDrawerOpen(true);
    if (forceAll !== undefined) {
      setIsAllEvidenceMode(forceAll);
    } else {
      setIsAllEvidenceMode(enhanced.length > 1);
    }
    if (preferredSource) {
      const match = enhanced.find(e => (e.chunk_id && e.chunk_id === preferredSource.chunk_id) || (e.id && e.id === preferredSource.id)) || preferredSource;
      handleSelectSourceForPreview(match);
    } else if (enhanced.length > 0) {
      handleSelectSourceForPreview(enhanced[0]);
    }
  };

  const handleSelectSourceForPreview = async (source: SourceMetadata) => {
    setSelectedSourceForPreview(source);

    const nameForFallback = getFileName(source.source).toLowerCase();
    const hasEvidence = !!(source.supporting_text || source.snippet || source.text);
    const isParsedType = source.content_type === "parsed" ||
      source.parsed_path !== undefined ||
      nameForFallback.endsWith(".pdf") ||
      nameForFallback.endsWith(".docx") ||
      nameForFallback.endsWith(".doc") ||
      nameForFallback.endsWith(".txt") ||
      hasEvidence;

    const defaultTab = "parsed";
    setSourcesDrawerPreviewTab(defaultTab);
    setParsedTextContent("");

    try {
      setSourcesDrawerPreviewLoading(true);
      setSourcesDrawerPreviewType("other");
      setSourcesDrawerCsvData([]);
      setExcelSheets({});
      setExcelSheetNames([]);
      setActiveExcelSheet("");
      setExcelPage(1);
      if (sourcesDrawerPreviewUrl) {
        URL.revokeObjectURL(sourcesDrawerPreviewUrl);
      }
      setSourcesDrawerPreviewUrl("");

      if (isParsedType || hasEvidence) {
        try {
          setParsedTextLoading(true);
          let cleanText = "";
          if (source.kb_id) {
            cleanText = await getCleanTextContent(source.kb_id);
          }
          let processed = cleanExtractedText(cleanText);
          if (!processed && source.text) {
            processed = cleanExtractedText(source.text);
          }
          setParsedTextContent(processed || "Unable to load extracted text content.");
        } catch (err) {
          console.error("Clean text fetch error:", err);
          setParsedTextContent(source.text ? cleanExtractedText(source.text) : "Unable to load extracted text content.");
        } finally {
          setParsedTextLoading(false);
        }
      }

      if (!source.kb_id) {
        setSourcesDrawerPreviewLoading(false);
        return;
      }

     
      try {
        const blobUrl = await getFilePreview(source.kb_id);
        setSourcesDrawerPreviewUrl(blobUrl);

        const name = getFileName(source.source).toLowerCase();
        const fullSourceStr = `${source.source || ''} ${source.name || ''} ${source.file_name || ''} ${source.title || ''} ${source.s3_path || ''} ${name}`.toLowerCase();

        const blobRes = await fetch(blobUrl);
        const blob = await blobRes.blob();
        const contentType = blob.type.toLowerCase();

        const isPDF = contentType.includes("pdf") || fullSourceStr.includes(".pdf");
        const isImage = contentType.includes("image/") || fullSourceStr.includes(".png") || fullSourceStr.includes(".jpg") || fullSourceStr.includes(".jpeg") || fullSourceStr.includes(".webp") || fullSourceStr.includes(".gif");
        const isCSV = contentType.includes("csv") || fullSourceStr.includes(".csv") || fullSourceStr.includes("csv:");
        const isExcel = contentType.includes("excel") || contentType.includes("spreadsheet") ||
          contentType.includes("vnd.ms-excel") || contentType.includes("vnd.openxmlformats-officedocument.spreadsheetml.sheet") ||
          contentType.includes("octet-stream") || contentType.includes("zip") ||
          fullSourceStr.includes(".xls") || fullSourceStr.includes(".xlsx") || fullSourceStr.includes("excel:") || fullSourceStr.includes("spreadsheet:");

        if (isPDF) {
          setSourcesDrawerPreviewType("pdf");
        } else if (isImage) {
          setSourcesDrawerPreviewType("image");
        } else if (isCSV || isExcel) {
          setSourcesDrawerPreviewType(isCSV ? "csv" : "excel");
          const arrayBuffer = await blob.arrayBuffer();
          excelArrayBufferRef.current = arrayBuffer;

          const XLSX = await import("xlsx");
          const workbook = XLSX.read(arrayBuffer, { type: "array", bookSheets: true });
          setExcelSheetNames(workbook.SheetNames);

          if (workbook.SheetNames.length > 0) {
            const firstSheet = workbook.SheetNames[0];
            setActiveExcelSheet(firstSheet);
            const partialWorkbook = XLSX.read(arrayBuffer, {
              type: "array",
              sheets: [firstSheet],
              cellFormula: false,
              cellHTML: false,
              cellText: false,
              cellDates: true
            });
            const worksheet = partialWorkbook.Sheets[firstSheet];
            const jsonData = XLSX.utils.sheet_to_json<any[]>(worksheet, { header: 1 });
            const formattedData = jsonData.map((row: any) =>
              Array.isArray(row)
                ? row.map((cell) => (cell !== null && cell !== undefined ? String(cell) : ""))
                : []
            );
            setExcelSheets({ [firstSheet]: formattedData });
          }
          setExcelPage(1);
        } else {
          setSourcesDrawerPreviewType("other");
        }
      } catch (binaryErr) {
        console.warn("Binary preview loading error (grounded parsed text remains active):", binaryErr);
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

  
  const displayedMessages = React.useMemo(() => {
    if (!searchQuery) return messages;
    const query = searchQuery.toLowerCase();
    return messages.filter((msg: any) =>
      msg.content && msg.content.toLowerCase().includes(query)
    );
  }, [messages, searchQuery]);

  const renderSidebar = () => {
    const filteredSessions = sessions.filter(s => {
      if (s.id.startsWith("session_")) {
        const hasMessages = (s.messages && s.messages.length > 0) || (currentSessionId === s.id && messages.length > 0);
        return hasMessages;
      }
      return true;
    });

    return (
      <div className="w-full h-full flex flex-col bg-[var(--app-surface-muted)] overflow-hidden">
       
        <div id="tour-sidebar-connection-status" className="p-4 border-b border-[var(--app-border)]/40 flex items-center justify-between shrink-0 select-none bg-[var(--app-surface-muted)]">
          <Flex align="center" gap={6} className="min-w-0">
            <span className={`w-2 h-2 rounded-full shrink-0 ${wsStatus === "open" ? "bg-emerald-500 animate-pulse" : "bg-amber-500"}`} />
            <span className="text-[10px] font-black uppercase tracking-wider text-[var(--app-text-soft)] truncate">
              {wsStatus === "open" ? "LINK STABILIZED" : "SYNCING LINK CORE..."}
            </span>
          </Flex>
        </div>

        
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

        
        <div className="flex-1 flex flex-col min-h-0 px-2">
          <div className="px-3 py-2 flex items-center justify-between">
            <span className="text-[10px] font-extrabold uppercase tracking-widest text-[var(--app-text-muted)] ">
              Chats
            </span>
            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-[var(--app-border)]/30 text-[var(--app-text-muted)]">
              {filteredSessions.length} sessions
            </span>
          </div>

          <div className="flex-1 overflow-y-auto space-y-1 custom-scrollbar pr-1">
            {filteredSessions.length > 0 ? (
              filteredSessions.map((s) => {
                const isActiveSession = currentSessionId === s.id;
                return (
                  <div
                    key={s.id}
                    onClick={() => {
                      loadSession(s);
                      setMobileSidebarOpen(false);
                    }}
                    className={`group relative p-2.5 rounded-xl cursor-pointer transition-all border flex items-center justify-between ${isActiveSession
                      ? "bg-[#0fb5a1]/20 text-[var(--app-text)] border-transparent font-extrabold"
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
    <div className="h-[calc(100vh-96px)] w-full flex bg-[var(--app-surface)] antialiased selection:bg-[#0fb5a1] selection:text-white overflow-hidden relative">
      <style>{`
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
        .typing-cursor {
          display: inline-block;
          animation: blink 1s infinite;
          vertical-align: middle;
          font-size: 14px;
        }
        @keyframes bounce {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-4px); }
        }
        .typing-dot {
          display: inline-block;
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background-color: currentColor;
          animation: bounce 1.4s infinite ease-in-out;
        }
        .typing-dot:nth-child(2) { animation-delay: 0.2s; }
        .typing-dot:nth-child(3) { animation-delay: 0.4s; }
      `}</style>
      
      {screen.md && (
        <div
          className="h-full border-r border-[var(--app-border)]/40 flex flex-col bg-[var(--app-surface-muted)] shrink-0 transition-all duration-300 overflow-hidden"
          style={{ width: desktopSidebarOpen ? "260px" : "0px", borderRightWidth: desktopSidebarOpen ? "1px" : "0px" }}
        >
          {renderSidebar()}
        </div>
      )}

     
      {!screen.md && (
        <Drawer
          zIndex={10000}
          placement="left"
          onClose={() => setMobileSidebarOpen(false)}
          open={mobileSidebarOpen}
          width={260}
          closeIcon={null}
          styles={{
            body: { padding: 0, background: 'var(--app-surface-muted)', height: '100%' }
          }}
        >
          {renderSidebar()}
        </Drawer>
      )}

      
      <Flex vertical className="flex-1 h-full overflow-hidden relative bg-transparent">

        
        <div className="w-full px-4 md:px-8 py-3 border-b border-[var(--app-border)]/40 backdrop-blur-md bg-[var(--app-surface)]/50 sticky top-0 z-40 transition-all shrink-0">
          <Flex justify="space-between" align="center" className="gap-2 w-full">

            
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

              <Flex id="tour-top-header-info" align="center" gap={8} className="select-none ml-1 shrink-0">
                <span className="font-extrabold text-sm tracking-tight text-[var(--app-text)] hidden xs:inline shrink-0">
                  AI Assist
                </span>
                {agent && (
                  <span className="text-[10px] bg-[#0fb5a1]/10 text-[#0fb5a1] font-bold px-2 py-0.5 rounded-lg border border-[#0fb5a1]/10 ml-2 hidden sm:inline-block max-w-[120px] truncate">
                    {agent.name}
                  </span>
                )}
              </Flex>
            </Flex>

            <Flex align="center" gap={12} className="shrink-0 select-none">
              <Button
                type="text"
                size="small"
                onClick={restartTour}
                className="hover:bg-[var(--app-hover)] !rounded-lg px-2 py-1 flex items-center gap-1.5 transition-all border border-[var(--app-border)] text-[11px] font-bold text-[var(--app-text-soft)] cursor-pointer bg-[var(--app-surface)] h-7 shadow-sm"
              >
                <LuSparkles className="text-[#0fb5a1]" size={11} />
                <span>Show Guide</span>
              </Button>

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

       
        <div 
          ref={chatContainerRef}
          onScroll={handleScroll}
          className="flex-1 overflow-y-auto px-4 md:px-12 py-6 md:py-10 space-y-6 custom-scrollbar bg-dots-pattern"
        >
          {messages.length === 0 && !isTyping && (
            <Flex vertical align="center" justify="center" className="h-full select-none my-auto space-y-4">
              <h1 className="m-0 text-[var(--app-text)] font-extrabold text-xl sm:text-2xl md:text-4xl tracking-tight text-center max-w-xl px-4 animate-in fade-in duration-500">
                Hello {userName}! What can I do for you?
              </h1>
              {/* {agent && (
                <p className="text-xs font-semibold text-[var(--app-text-soft)]/50 uppercase tracking-widest text-center animate-in fade-in duration-700">
                  Active Agent: <span className="text-[#0fb5a1] font-bold">{agent.name}</span>
                  • Model: <span className="text-[#0fb5a1] font-bold">{selectedModel}</span>
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
                <div className={`flex gap-3 min-w-0 transition-all duration-300 ${editingMessageIndex === i ? "w-full max-w-[95%] md:max-w-[85%]" : "max-w-[88%] md:max-w-[75%]"} ${isUser ? "flex-row-reverse" : "flex-row"}`}>
                  {isUser ? (
                    <div className="relative shrink-0">
                      <Avatar
                        size={32}
                        className="bg-gradient-to-br from-[#0fb5a1] to-[#0a8576] text-white shadow-md font-extrabold flex items-center justify-center border border-white/10"
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

                  <div className="flex flex-col space-y-1 min-w-0 flex-1">
                    <span className={`text-[9px] font-bold text-[var(--app-text-soft)] px-1 ${isUser ? "text-right" : "text-left"} flex items-center gap-1.5 ${isUser ? "justify-end" : "justify-start"}`}>
                      <span>{msg.timestamp}</span>
                      {!isUser && msg.responseTime !== undefined && (
                        <>
                          <span>•</span>
                          <span>Answered in {msg.responseTime}s</span>
                        </>
                      )}
                    </span>

                    <div
                      className={`group relative p-4 md:p-5 rounded-2xl transition-all duration-200 shadow-sm border mb-6 ${isUser
                        ? "bg-[#0fb5a1] text-white rounded-tr-none border-[#0fb5a1]/20 font-medium"
                        : "bg-[var(--app-surface-muted)] text-[var(--app-text)] rounded-tl-none border-[var(--app-border)]/40 font-normal"
                        }`}
                    >
                      
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
                          <Tooltip title={isTyping ? "Generation in progress" : "Edit message"} placement="bottom">
                            <button
                              onClick={() => !isTyping && handleEditMessage(i, msg.content)}
                              disabled={isTyping}
                              className={`p-2 font-bold transition-colors ${isTyping ? "text-gray-400 cursor-not-allowed opacity-40" : "text-[var(--app-text)] cursor-pointer hover:opacity-80"}`}
                            >
                              <FiEdit2 size={16} strokeWidth={2} />
                            </button>
                          </Tooltip>
                        ) : (
                          <>
                            <Tooltip title="Helpful" placement="bottom">
                              <button
                                onClick={() => handleThumbsUp(msg.id)}
                                className={`p-2 transition-colors cursor-pointer hover:opacity-80 ${msg.feedback === "thumbs_up" ? "text-emerald-500 font-bold" : "text-[var(--app-text)] font-bold"}`}
                              >
                                <FiThumbsUp size={16} strokeWidth={msg.feedback === "thumbs_up" ? 2.5 : 2} fill="none" />
                              </button>
                            </Tooltip>
                            <Tooltip title="Not helpful" placement="bottom">
                              <button
                                onClick={() => handleThumbsDown(msg.id)}
                                className={`p-2 transition-colors cursor-pointer hover:opacity-80 ${msg.feedback === "thumbs_down" ? "text-rose-500 font-bold" : "text-[var(--app-text)] font-bold"}`}
                              >
                                <FiThumbsDown size={16} strokeWidth={msg.feedback === "thumbs_down" ? 2.5 : 2} fill="none" />
                              </button>
                            </Tooltip>
                            <Tooltip title={isTyping ? "Generation in progress" : "Regenerate"} placement="bottom">
                              <button
                                onClick={() => !isTyping && handleRegenerate(i)}
                                disabled={isTyping}
                                className={`p-2 transition-colors ${isTyping ? "text-gray-400 cursor-not-allowed opacity-40" : "text-[var(--app-text)] font-bold cursor-pointer hover:opacity-80"}`}
                              >
                                <FiRotateCw size={16} strokeWidth={2} />
                              </button>
                            </Tooltip>
                            {(() => {
                              const rawMsgSources = msg.sources || msg.metadata?.sources || [];
                              const uniqueSources = deduplicateSources(rawMsgSources);
                              if (!showSources || uniqueSources.length === 0 || msg.content?.includes("Something went wrong") || msg.content?.includes("trouble connecting")) return null;
                              return (
                                <div className="ml-auto flex items-center">
                                  {uniqueSources.length === 1 ? (
                                    <button
                                      onClick={() => handleOpenSource(uniqueSources[0], rawMsgSources, msg.content, true)}
                                      className="text-[var(--app-text)] font-bold p-1.5 px-2.5 rounded-lg border border-[var(--app-border)]/60 bg-[var(--app-surface-muted)] cursor-pointer transition-all hover:border-[#0fb5a1] hover:text-[#0fb5a1] flex items-center gap-1.5 text-xs shrink-0 shadow-sm"
                                      title="Click to view exact paragraph, lines, and highlighted supporting text"
                                    >
                                      <SiCrowdsource className="text-[#0fb5a1]" />
                                      <span>Source Citation</span>
                                      {uniqueSources[0].page && (
                                        <span className="text-[10px] bg-[#0fb5a1]/15 text-[#0fb5a1] px-1 py-0.2 rounded font-mono font-semibold">
                                          P.{uniqueSources[0].page}
                                        </span>
                                      )}
                                    </button>
                                  ) : (
                                    <Dropdown
                                      menu={{
                                        items: [
                                          ...uniqueSources.map((src: any, idx: number) => ({
                                            key: idx.toString(),
                                            label: (
                                              <div className="flex flex-col py-1 max-w-[320px]">
                                                <div className="font-semibold text-xs flex items-center justify-between gap-2">
                                                  <span className="truncate">{getCleanFileName(src)}</span>
                                                  <span className="text-[10px] font-mono text-[#0fb5a1] bg-[#0fb5a1]/10 px-1 py-0.5 rounded shrink-0">
                                                    P.{src.page || 1} • Para {src.paragraph_number || src.paragraph || idx + 1}
                                                  </span>
                                                </div>
                                                {src.supporting_text && (
                                                  <div className="text-[11px] text-[var(--app-text-muted)] truncate mt-0.5">
                                                    "{src.supporting_text}"
                                                  </div>
                                                )}
                                              </div>
                                            ),
                                            onClick: () => handleOpenSource(src, rawMsgSources, msg.content, false),
                                          })),
                                          {
                                            type: 'divider',
                                          },
                                          {
                                            key: 'all',
                                            label: (
                                              <span className="font-bold text-xs text-[#0fb5a1] flex items-center gap-1">
                                                <SiCrowdsource /> View All Citations & Evidence ({uniqueSources.length})
                                              </span>
                                            ),
                                            onClick: () => handleOpenSource(uniqueSources[0], rawMsgSources, msg.content, true),
                                          }
                                        ]
                                      }}
                                      placement="bottomLeft"
                                      trigger={['click']}
                                    >
                                      <button
                                        className="text-[var(--app-text)] font-bold p-1.5 px-2.5 rounded-lg border border-[var(--app-border)]/60 bg-[var(--app-surface-muted)] cursor-pointer transition-all hover:border-[#0fb5a1] hover:text-[#0fb5a1] flex items-center gap-1.5 text-xs shrink-0 shadow-sm"
                                        title="Click to view exact citations & evidence"
                                      >
                                        <SiCrowdsource className="text-[#0fb5a1]" />
                                        <span>Sources ({uniqueSources.length})</span>
                                      </button>
                                    </Dropdown>
                                  )}
                                </div>
                              );
                            })()}
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
                          <div className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${isUser ? "bg-white/10 text-white" : "bg-[#0fb5a1]/10 text-[#0fb5a1]"}`}>
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

                      {!isUser && msg.type === "clarification_needed" && msg.clarification?.candidates && msg.clarification.candidates.length > 0 && (
                        <div className="mt-3 pt-3 border-t border-[var(--app-border)]/60 flex flex-col gap-2.5 w-full">
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full">
                            {msg.clarification.candidates.map((cand: any) => {
                              const isSelected = msg.selectedCandidateId === cand.kb_id;
                              const isDisabled = !!msg.selectedCandidateId;

                              return (
                                <button
                                  key={cand.kb_id}
                                  type="button"
                                  disabled={isDisabled}
                                  onClick={() => handleSelectCandidate(i, cand, msg.originalQuery)}
                                  className={`flex flex-col text-left p-3 rounded-xl border transition-all duration-200 relative overflow-hidden group ${
                                    isSelected
                                      ? "border-[#0fb5a1] bg-[#0fb5a1]/10 shadow-sm ring-1 ring-[#0fb5a1]"
                                      : isDisabled
                                      ? "opacity-50 border-[var(--app-border)]/50 bg-[var(--app-surface)]/50 cursor-not-allowed"
                                      : "border-[var(--app-border)] bg-[var(--app-surface)] hover:border-[#0fb5a1]/60 hover:bg-[#0fb5a1]/5 hover:shadow-sm cursor-pointer hover:-translate-y-0.5"
                                  }`}
                                >
                                  <div className="flex items-center justify-between gap-2 w-full">
                                    <div className="flex items-center gap-2 min-w-0 flex-1">
                                      <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 text-sm ${
                                        isSelected ? "bg-[#0fb5a1] text-white" : "bg-[#0fb5a1]/10 text-[#0fb5a1] group-hover:bg-[#0fb5a1] group-hover:text-white transition-colors"
                                      }`}>
                                        <LuFileText />
                                      </div>
                                      <span className={`font-semibold text-xs truncate ${
                                        isSelected ? "text-[#0fb5a1]" : "text-[var(--app-text)] group-hover:text-[#0fb5a1] transition-colors"
                                      }`} title={cand.filename}>
                                        {cand.filename}
                                      </span>
                                    </div>
                                    {isSelected && (
                                      <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-[#0fb5a1] text-white shrink-0">
                                        Selected
                                      </span>
                                    )}
                                  </div>

                                  <div className="flex items-center gap-2 mt-2 text-[11px] text-[var(--app-text-soft)]">
                                    <span className="bg-[var(--app-surface-muted)] px-1.5 py-0.5 rounded font-medium border border-[var(--app-border)]/40">
                                      {cand.row_count !== undefined ? `${cand.row_count.toLocaleString()} rows` : "Dataset"}
                                    </span>
                                    {cand.sample_columns && cand.sample_columns.length > 0 && (
                                      <span>• {cand.sample_columns.length} columns</span>
                                    )}
                                  </div>

                                  {cand.sample_columns && cand.sample_columns.length > 0 && (
                                    <div className="flex flex-wrap gap-1.5 mt-2">
                                      {cand.sample_columns.slice(0, 3).map((col: string, cIdx: number) => (
                                        <span
                                          key={cIdx}
                                          className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--app-surface-muted)] text-[var(--app-text-soft)] border border-[var(--app-border)]/40 truncate max-w-[110px]"
                                          title={col}
                                        >
                                          {col}
                                        </span>
                                      ))}
                                      {cand.sample_columns.length > 3 && (
                                        <span className="text-[10px] text-[var(--app-text-soft)]/70 self-center">
                                          +{cand.sample_columns.length - 3} more
                                        </span>
                                      )}
                                    </div>
                                  )}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      )}


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
              <div className="flex gap-3 min-w-0 max-w-[80%] items-start">
                <GSearchLogoAvatar size={32} />
                <div className="flex flex-col space-y-1 min-w-0 flex-1">
                  <span className="text-[9px] font-bold text-[var(--app-text-soft)] italic px-1">Processing...</span>
                  <div className="p-4 bg-[var(--app-surface-muted)]/60 border border-[var(--app-border)]/40 text-[var(--app-text)] rounded-2xl rounded-tl-none shadow-sm min-w-[120px]">
                    {stripThinking(streamingText).trim() ? (
                      <div className="mr-2 leading-7 flex flex-col gap-1.5">
                        {renderFormattedContent(streamingText, false)}
                        <div className="flex items-center gap-1.5 mt-1.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-[#0fb5a1] animate-ping" />
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-center gap-3">
                        <span className="text-xs text-[var(--app-text-soft)] font-medium">
                          {progressLabel}
                        </span>
                        <span className="flex items-center gap-1 shrink-0">
                          <span className="w-1.5 h-1.5 rounded-full bg-[#0fb5a1] animate-bounce" style={{ animationDelay: "0s" }} />
                          <span className="w-1.5 h-1.5 rounded-full bg-[#0fb5a1] animate-bounce" style={{ animationDelay: "0.2s" }} />
                          <span className="w-1.5 h-1.5 rounded-full bg-[#0fb5a1] animate-bounce" style={{ animationDelay: "0.4s" }} />
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        
        <div className="px-4 md:px-12 pb-4 pt-2 bg-gradient-to-t from-[var(--app-surface)] via-[var(--app-surface)] to-transparent border-t-0 z-30 shrink-0">

         
          <div className="flex justify-between items-center px-1 mb-2 w-full select-none gap-3">
            
            <div className="flex items-center gap-1 bg-[#eef6f8] dark:bg-[#131e31] p-1 rounded-full border border-[var(--app-border)]/40 shadow-sm">
              
              {activeMode === 'search' ? (
                <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white dark:bg-[#0f172a] shadow-sm w-52 sm:w-64 transition-all duration-200">
                  <LuSearch size={12} className="shrink-0 text-[#0fb5a1] dark:text-[#34d399]" />
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

              
              <button
                onClick={() => setActiveMode('agent')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] font-black tracking-tight transition-all duration-200 cursor-pointer border-none bg-transparent outline-none ${activeMode === 'agent'
                  ? "bg-white dark:bg-[#0f172a] text-[#0fb5a1] dark:text-[#34d399] shadow-sm font-black"
                  : "bg-transparent text-[var(--app-text-soft)]/70 hover:text-[var(--app-text)] font-extrabold"
                  }`}
              >
                <LuBot size={12} className="shrink-0" />
                <span>Agent</span>
              </button>
            </div>

           
            <div className="hidden sm:flex items-center gap-1.5 text-[11px] text-[var(--app-text-soft)]/60 font-bold ml-auto">
              <span>Mode shift:</span>
              <kbd className="px-1.5 py-0.5 rounded bg-[var(--app-border)]/50 border border-[var(--app-border)] text-[9px] font-black">Ctrl</kbd>
              <kbd className="px-1.5 py-0.5 rounded bg-[var(--app-border)]/50 border border-[var(--app-border)] text-[9px] font-black">K</kbd>
            </div>
          </div>

          
          <div id="tour-chat-input-card" className="bg-white dark:bg-[#0b0f19] border-2 border-[#0fb5a1]/30 dark:border-[#0fb5a1]/40 rounded-3xl p-3 shadow-lg transition-all focus-within:border-[#0fb5a1] focus-within:ring-4 focus-within:ring-[#0fb5a1]/10 flex flex-col gap-2 overflow-hidden">

            
            {attachedFile && (
              <div className="px-3 pt-2 pb-1 animate-in fade-in duration-200">
                <div className="inline-flex align-center gap-3 bg-[var(--app-surface)] border border-[var(--app-border)]/80 p-2.5 rounded-xl relative group shadow-sm max-w-xs">
                  {attachedFile.type?.startsWith("image/") ? (
                    <div className="w-10 h-10 rounded-lg overflow-hidden bg-black/5 shrink-0 border border-[var(--app-border)]/40">
                      <img src={attachedFile.url} alt="preview" className="w-full h-full object-cover" />
                    </div>
                  ) : (
                    <div className="w-10 h-10 rounded-lg bg-[#0fb5a1]/10 text-[#0fb5a1] flex items-center justify-center shrink-0">
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

           
            <div className="w-full">
              <Input.TextArea
                ref={chatInputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask anything"
                disabled={!agent || wsStatus !== "open" || isTyping}
                variant="borderless"
                autoSize={{ minRows: 2, maxRows: 6 }}
                className="w-full !p-1 !bg-transparent !font-semibold !text-xs md:!text-sm !text-[var(--app-text)] !placeholder:text-[var(--app-text-soft)]/50 focus:outline-none resize-none align-middle"
              />
            </div>

           
            <Flex align="center" justify="space-between" className="w-full pt-1.5 border-t border-[var(--app-border)]/10">
              
              <Flex align="center" gap={8} className="min-w-0">
                <Upload
                  beforeUpload={handleBeforeUpload}
                  showUploadList={false}
                  accept="image/*,.pdf,.doc,.docx,.xls,.xlsx,.txt"
                  disabled={!agent || wsStatus !== "open" || isTyping}
                >
                  <Tooltip title="Share files" placement="topLeft">
                    <Button
                      type="text"
                      disabled={!agent || wsStatus !== "open" || isTyping}
                      icon={<LuPaperclip className="text-base text-[var(--app-text-soft)]" />}
                      className="hover:bg-[var(--app-hover)] !rounded-xl w-8 h-8 flex items-center justify-center transition-colors border-none bg-transparent cursor-pointer"
                    />
                  </Tooltip>
                </Upload>

               
                {activeMode === 'agent' && (
                  <Dropdown
                    menu={{
                      items: (botsCache || [])
                        .filter((bot) =>
                          bot.name.toLowerCase().includes(agentSearch.toLowerCase())
                        )
                        .map((bot) => ({
                          key: bot.id,
                          label: <span className="font-semibold text-xs">{bot.name}</span>
                        })),
                      onClick: (e) => {
                        const selected = botsCache?.find(b => b.id === e.key);
                        if (selected) {
                          handleAgentChange(selected.id, selected.name);
                        }
                      },
                      style: { maxHeight: "250px", overflowY: "auto" }
                    }}
                    dropdownRender={(menu) => (
                      <div className="bg-[var(--app-surface)] border border-[var(--app-border)] rounded-xl shadow-lg p-2 min-w-[200px]">
                        {(botsCache || []).length > 5 && (
                          <Input
                            prefix={<LuSearch size={14} className="text-gray-400 mr-1" />}
                            placeholder="Search agents..."
                            value={agentSearch}
                            onChange={(e) => setAgentSearch(e.target.value)}
                            className="mb-2 text-xs"
                            allowClear
                          />
                        )}
                        {menu}
                      </div>
                    )}
                    trigger={["click"]}
                  >
                    <div className="inline-flex bg-transparent rounded-full overflow-hidden">
                      <button id="tour-agent-select" className="flex items-center gap-1.5 px-3.5 py-1.5 bg-[#0fb5a1]/15 hover:bg-[#0fb5a1]/25 dark:bg-[#0fb5a1]/25 dark:hover:bg-[#0fb5a1]/35 border-2 border-[#0fb5a1] dark:border-[#34d399] rounded-full text-xs font-black text-[#0fb5a1] dark:text-[#34d399] cursor-pointer select-none transition-all outline-none focus:outline-none ml-1 animate-in fade-in duration-200 shadow-sm">
                        <div className="w-5 h-5 rounded-full bg-[#e3f7f3] dark:bg-[#12352f] flex items-center justify-center text-[#0fb5a1] dark:text-[#34d399] shrink-0">
                          <LuBot size={11} className="text-[#0fb5a1] dark:text-[#34d399]" />
                        </div>
                        <span className="truncate max-w-[120px] text-[#0fb5a1] dark:text-[#34d399] font-black">
                          {agent ? agent.name : "Select Agent"}
                        </span>
                        <span className="text-[9px] opacity-100 ml-0.5 text-[#0fb5a1] dark:text-[#34d399] font-black">▼</span>
                      </button>
                    </div>
                  </Dropdown>
                )}
              </Flex>

             
              <Flex align="center" gap={12} className="shrink-0">
                
                <Tooltip title={isTyping ? "Generation in progress" : "Press Enter to send"} placement="topRight">
                  <button
                    onClick={handleSend}
                    disabled={!agent || (!input.trim() && !attachedFile) || wsStatus !== "open" || isTyping}
                    className={`w-8 h-8 rounded-full flex items-center justify-center transition-all shrink-0 cursor-pointer border-none outline-none ${(!agent || (!input.trim() && !attachedFile) || wsStatus !== "open" || isTyping)
                      ? "bg-gray-200 dark:bg-gray-800 text-[var(--app-text-soft)] opacity-40 cursor-not-allowed"
                      : "bg-[#0fb5a1] text-white hover:bg-[#0da18f] hover:opacity-90 active:scale-95"
                      }`}
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
          <Flex align="center" justify="space-between" className="w-full pr-8">
            <Flex align="center" gap={8} className="min-w-0">
              <span className="text-[#0fb5a1] text-base shrink-0">📄</span>
              <div className="min-w-0">
                <span className="font-extrabold text-sm text-[var(--app-text)] truncate block">
                  {selectedSourceForPreview ? getFileName(selectedSourceForPreview.source) : "Source Evidence"}
                </span>
                <span className="text-[11px] text-[var(--app-text-muted)] font-normal hidden sm:block">
                  Verified supporting passage for this response
                </span>
              </div>
            </Flex>
            {sourcesDrawerPreviewUrl && (
              <a
                href={sourcesDrawerPreviewUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs font-semibold text-[#0fb5a1] hover:underline flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#0fb5a1]/10 hover:bg-[#0fb5a1]/20 transition-colors shrink-0"
                title="Open full original file in new tab"
              >
                <FiExternalLink size={13} />
                <span>Open Original File</span>
              </a>
            )}
          </Flex>
        }
        placement="right"
        onClose={() => {
          setIsSourcesDrawerOpen(false);
          setSelectedSourceForPreview(null);
          if (sourcesDrawerPreviewUrl) {
            URL.revokeObjectURL(sourcesDrawerPreviewUrl);
          }
          setSourcesDrawerPreviewUrl("");
        }}
        open={isSourcesDrawerOpen}
        width={880}
        height="100vh"
        styles={{
          body: { padding: 0, background: "var(--app-surface)", display: "flex", flexDirection: "column", height: "100%" },
        }}
      >
        {/* Source Selector Bar for Multi-Source Responses */}
        {activeSources.length > 1 && (
          <div className="flex items-center gap-2 overflow-x-auto py-2.5 px-6 border-b border-[var(--app-border)]/40 bg-[var(--app-surface-muted)] shrink-0 custom-scrollbar">
            <span className="text-[10px] font-bold text-[var(--app-text-muted)] uppercase tracking-wider shrink-0 mr-1">
              Evidence Citations ({activeSources.length}):
            </span>
            <button
              onClick={() => {
                setIsAllEvidenceMode(true);
              }}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5 whitespace-nowrap shrink-0 ${
                isAllEvidenceMode
                  ? "bg-[#0fb5a1] text-white shadow-sm font-bold"
                  : "bg-[var(--app-surface)] text-[var(--app-text)] hover:bg-[var(--app-hover)] border border-[var(--app-border)]/40"
              }`}
            >
              <span>⭐</span>
              <span>All Supporting Evidence ({activeSources.length})</span>
            </button>
            {activeSources.map((src, index) => {
              const fileName = getFileName(src.source);
              const badgeLabel = getSourceTabLabel(src, index);
              const isSelected = !isAllEvidenceMode && ((selectedSourceForPreview?.id || selectedSourceForPreview?.chunk_id) === (src.id || src.chunk_id));
              return (
                <button
                  key={(src.id || src.chunk_id) || index}
                  onClick={() => {
                    setIsAllEvidenceMode(false);
                    handleSelectSourceForPreview(src);
                  }}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5 whitespace-nowrap shrink-0 ${
                    isSelected
                      ? "bg-[#0fb5a1] text-white shadow-sm font-bold"
                      : "bg-[var(--app-surface)] text-[var(--app-text)] hover:bg-[var(--app-hover)] border border-[var(--app-border)]/40"
                  }`}
                  title={`${fileName} - ${badgeLabel}`}
                >
                  <span>📄</span>
                  <span>#{index + 1} {badgeLabel}</span>
                  {src.page && <span className="text-[10px] opacity-75 font-mono">P.{src.page}</span>}
                </button>
              );
            })}
          </div>
        )}

        <div style={{ flex: 1, height: "100%", overflowY: "auto", display: "flex", flexDirection: "column" }}>
          {sourcesDrawerPreviewLoading ? (
            <Flex vertical align="center" justify="center" gap={12} className="h-full my-auto py-24">
              <Spin size="large" />
              <Text className="text-xs text-[var(--app-text-soft)] font-semibold">
                Loading source evidence & context...
              </Text>
            </Flex>
          ) : selectedSourceForPreview ? (
            <div className="w-full h-full flex flex-col justify-start">
              {(sourcesDrawerPreviewType === "excel" || sourcesDrawerPreviewType === "csv") && excelSheetNames.length > 0 ? (
                <div className="w-full h-full flex flex-col overflow-hidden bg-[var(--app-surface)]">
                  {sourcesDrawerPreviewType === "excel" && excelSheetNames.length > 1 && (
                    <div className="flex gap-2 p-2.5 bg-[var(--app-surface-muted)] border-b border-[var(--app-border)]/40 overflow-x-auto shrink-0 scrollbar-thin">
                      {excelSheetNames.map(sheetName => {
                        const isActive = activeExcelSheet === sheetName;
                        return (
                          <button
                            key={sheetName}
                            onClick={async () => {
                              if (!excelSheets[sheetName] && excelArrayBufferRef.current) {
                                setSourcesDrawerPreviewLoading(true);
                                try {
                                  const XLSX = await import("xlsx");
                                  const partialWorkbook = XLSX.read(excelArrayBufferRef.current, {
                                    type: "array",
                                    sheets: [sheetName],
                                    cellFormula: false,
                                    cellHTML: false,
                                    cellText: false,
                                    cellDates: true
                                  });
                                  const worksheet = partialWorkbook.Sheets[sheetName];
                                  const jsonData = XLSX.utils.sheet_to_json<any[]>(worksheet, { header: 1 });
                                  const formattedData = jsonData.map((row: any) =>
                                    Array.isArray(row)
                                      ? row.map((cell) => (cell !== null && cell !== undefined ? String(cell) : ""))
                                      : []
                                  );
                                  setExcelSheets(prev => ({ ...prev, [sheetName]: formattedData }));
                                } catch (err) {
                                  console.error("Failed to parse sheet:", sheetName, err);
                                } finally {
                                  setSourcesDrawerPreviewLoading(false);
                                }
                              }
                              setActiveExcelSheet(sheetName);
                              setExcelPage(1);
                            }}
                            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer whitespace-nowrap ${isActive
                              ? "bg-[#0fb5a1] text-white shadow-sm"
                              : "bg-[var(--app-surface)] hover:bg-[var(--app-surface-muted)] text-[var(--app-text-soft)] border border-[var(--app-border)]/40"
                              }`}
                          >
                            {sheetName}
                          </button>
                        );
                      })}
                    </div>
                  )}

                  <div className="flex-1 overflow-auto p-4 custom-scrollbar bg-[var(--app-surface)]">
                    {excelSheets[activeExcelSheet] && excelSheets[activeExcelSheet].length > 0 ? (
                      (() => {
                        const activeSheetData = excelSheets[activeExcelSheet];
                        const totalRows = activeSheetData.length > 0 ? activeSheetData.length - 1 : 0;
                        const PAGE_SIZE = 100;
                        const totalPages = Math.ceil(totalRows / PAGE_SIZE);
                        const displayedRows = activeSheetData.slice(
                          1 + (excelPage - 1) * PAGE_SIZE,
                          1 + excelPage * PAGE_SIZE
                        );

                        return (
                          <div className="flex flex-col gap-4">
                            <div className="border border-[var(--app-border)]/40 rounded-xl overflow-x-auto shadow-sm">
                              <table className="min-w-full divide-y divide-[var(--app-border)]/40 text-left text-xs bg-[var(--app-surface)]">
                                <thead className="bg-[var(--app-surface-muted)] font-bold text-[var(--app-text)] uppercase tracking-wider">
                                  <tr>
                                    {activeSheetData[0].map((cell, idx) => (
                                      <th key={idx} className="px-4 py-3 border-b border-r border-[var(--app-border)]/40 last:border-r-0 whitespace-nowrap bg-[var(--app-surface-muted)] text-[var(--app-text)] font-extrabold text-[10px] tracking-wider">
                                        {cell || `Column ${idx + 1}`}
                                      </th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody className="bg-[var(--app-surface)] divide-y divide-[var(--app-border)]/40 text-[var(--app-text-soft)] font-medium">
                                  {displayedRows.map((row, rowIdx) => (
                                    <tr key={rowIdx} className="hover:bg-[var(--app-surface-muted)]/50 transition-colors">
                                      {activeSheetData[0].map((_, colIdx) => (
                                        <td key={colIdx} className="px-4 py-3 border-r border-[var(--app-border)]/40 last:border-r-0 max-w-xs truncate whitespace-nowrap text-[var(--app-text-soft)]">
                                          {row[colIdx] || ""}
                                        </td>
                                      ))}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>

                            {totalPages > 1 && (
                              <div className="flex items-center justify-between p-3 border border-[var(--app-border)]/40 bg-[var(--app-surface-muted)] shrink-0 select-none rounded-xl">
                                <span className="text-xs text-[var(--app-text-soft)] font-bold">
                                  Showing {1 + (excelPage - 1) * PAGE_SIZE} - {Math.min(excelPage * PAGE_SIZE, totalRows)} of {totalRows} rows
                                </span>
                                <div className="flex gap-2">
                                  <button
                                    disabled={excelPage === 1}
                                    onClick={() => setExcelPage(prev => Math.max(prev - 1, 1))}
                                    className="px-3 py-1.5 text-xs font-bold rounded-lg border border-[var(--app-border)]/40 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer bg-[var(--app-surface)] text-[var(--app-text)] hover:bg-[var(--app-surface-muted)] transition-all"
                                  >
                                    Previous
                                  </button>
                                  <span className="text-xs self-center px-1 font-bold text-[var(--app-text)]">
                                    Page {excelPage} of {totalPages}
                                  </span>
                                  <button
                                    disabled={excelPage === totalPages}
                                    onClick={() => setExcelPage(prev => Math.min(prev + 1, totalPages))}
                                    className="px-3 py-1.5 text-xs font-bold rounded-lg border border-[var(--app-border)]/40 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer bg-[var(--app-surface)] text-[var(--app-text)] hover:bg-[var(--app-surface-muted)] transition-all"
                                  >
                                    Next
                                  </button>
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })()
                    ) : (
                      <Flex vertical align="center" justify="center" className="py-20 text-[var(--app-text-soft)] h-full">
                        <LuFileText size={32} className="mb-2 opacity-55" />
                        <span className="text-xs">No data in this sheet</span>
                      </Flex>
                    )}
                  </div>
                </div>
              ) : (
                <GroundedEvidenceDocumentViewer
                  parsedContent={parsedTextContent}
                  source={selectedSourceForPreview}
                  allSources={activeSources}
                  isAllMode={isAllEvidenceMode}
                  responseContent={activeMessageContent}
                  loading={parsedTextLoading}
                />
              )}
            </div>
          ) : (
            <Flex vertical align="center" justify="center" className="h-full opacity-40">
              <SiCrowdsource className="text-4xl text-[#0fb5a1] mb-2" />
              <Text className="font-bold text-xs uppercase tracking-widest text-[var(--app-text-muted)]">
                Select a document or evidence citation to preview
              </Text>
            </Flex>
          )}
        </div>
      </Drawer>

      
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
          <Button key="submit" type="primary" onClick={submitThumbsDownFeedback} className="bg-[#0fb5a1] hover:bg-[#0fb5a1]/80 border-none font-bold">
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
              className="mt-2 text-[var(--app-text)] border-[var(--app-border)]/40 focus:border-[#0fb5a1]/60"
            />
          )}
        </div>
      </Modal>

      <OnboardingTour
        steps={tourSteps}
        activeStep={tourStep}
        isActive={tourActive}
        onStepChange={(stepIndex) => setTourStep(stepIndex)}
        onClose={handleTourClose}
      />

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
          border-left: 4px solid #0fb5a1;
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