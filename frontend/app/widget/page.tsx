"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState, Suspense, useMemo } from "react";
import { FaBrain } from "react-icons/fa";
import { SiCrowdsource } from "react-icons/si";

const CHAT_FONT_FAMILY = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";

type SourceItem = {
  id?: string;
  kb_id?: string;
  source?: string;
  name?: string;
  text?: string;
  url?: string;
  s3_path?: string;
  file_name?: string;
  content?: string;
  page_content?: string;
  snippet?: string;
  file_path?: string;
};

type Message = {
  id?: string;
  role: "user" | "assistant";
  content: string;
  sources?: SourceItem[];
  feedback?: "thumbs_up" | "thumbs_down";
  escalation_detected?: boolean;
};

function stripThinking(content: string): string {
  if (!content) return "";
  let cleaned = content.replace(/<think>[\s\S]*?<\/think>/g, "");
  const openThinkIndex = cleaned.indexOf("<think>");
  if (openThinkIndex !== -1) {
    cleaned = cleaned.substring(0, openThinkIndex);
  }
  return cleaned;
}

function getCitedFilenames(text: string): string[] {
  const regex = /(?:\[Source:\s*|\(Source:\s*)([^\]\)]+)[\]\)]/gi;
  const filenames: string[] = [];
  let match;
  while ((match = regex.exec(text)) !== null) {
    const rawCitation = match[1];
    const parts = rawCitation.split(",");
    parts.forEach(p => {
      let partClean = p.trim();
      if (partClean.includes(" - Position")) {
        partClean = partClean.split(" - Position")[0].trim();
      }
      if (partClean) {
        filenames.push(partClean.toLowerCase());
      }
    });
  }
  return filenames;
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

function getCleanSourceName(rawName: string): string {
  if (!rawName) return "";
  let cleaned = rawName;
  cleaned = cleaned.replace(/^text source:\s*/i, "").trim();
  cleaned = cleaned.replace(/\s*\(Selected Links\)\s*/i, "").trim();

  if (cleaned.startsWith("http://") || cleaned.startsWith("https://")) {
    try {
      const urlObj = new URL(cleaned);
      let pathname = urlObj.pathname;
      if (pathname === "/" || !pathname) {
        return urlObj.hostname.replace(/^www\./i, "");
      }
      if (pathname.endsWith("/")) {
        pathname = pathname.slice(0, -1);
      }
      const segments = pathname.split("/");
      const lastSegment = segments[segments.length - 1];
      if (lastSegment) {
        return decodeURIComponent(lastSegment);
      }
      return urlObj.hostname.replace(/^www\./i, "");
    } catch (e) {
      let stripped = cleaned.replace(/^https?:\/\/(www\.)?/, "");
      if (stripped.endsWith("/")) {
        stripped = stripped.slice(0, -1);
      }
      return stripped;
    }
  }

  if (cleaned.includes("/") || cleaned.includes("\\")) {
    const parts = cleaned.split(/[/\\]/);
    cleaned = parts[parts.length - 1] || cleaned;
  }
  return cleaned.replace(/^(pdf|doc|docx|csv|xlsx|image|img|txt):\s*/i, "").trim();
}

function convertToCleanHtml(markdown: string): string {
  if (!markdown) return "";
  let html = markdown;

  // 1. Strip thinking blocks
  html = html.replace(/<think>[\s\S]*?<\/think>/g, "");

  // 2. Convert code blocks
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    return `<pre><code>${code.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</code></pre>`;
  });

  // 3. Convert headers
  html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>');
  html = html.replace(/^## (.*$)/gim, '<h2>$1</h2>');
  html = html.replace(/^# (.*$)/gim, '<h1>$1</h1>');

  // 4. Convert bold/italic
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');

  // 5. Convert lists & tables
  const lines = html.split("\n");
  let inList = false;
  let inNumList = false;
  let inTable = false;
  let tableRows: string[] = [];

  const parsedLines = lines.map(line => {
    const trimmed = line.trim();

    // Handle tables
    if (trimmed.startsWith("|")) {
      inTable = true;
      if (trimmed.includes("---")) {
        return "";
      }
      const cells = trimmed.split("|").map(c => c.trim()).filter((_, idx, arr) => idx > 0 && idx < arr.length - 1);
      const isHeader = tableRows.length === 0;
      const cellTag = isHeader ? "th" : "td";
      const row = `<tr>${cells.map(c => `<${cellTag}>${c}</${cellTag}>`).join("")}</tr>`;
      tableRows.push(row);
      return "";
    } else if (inTable) {
      inTable = false;
      const completeTable = `<table>${tableRows.join("")}</table>`;
      tableRows = [];
      return completeTable + "\n" + line;
    }

    // Handle bullet lists
    if (/^\s*[-*•]\s+(.*)$/.test(line)) {
      let content = line.replace(/^\s*[-*•]\s+/, "");
      let prefix = "";
      if (!inList) {
        inList = true;
        prefix = "<ul>";
      }
      return `${prefix}<li>${content}</li>`;
    } else if (inList) {
      inList = false;
      return "</ul>\n" + line;
    }

    // Handle numbered lists
    if (/^\s*\d+\.\s+(.*)$/.test(line)) {
      let content = line.replace(/^\s*\d+\.\s+/, "");
      let prefix = "";
      if (!inNumList) {
        inNumList = true;
        prefix = "<ol>";
      }
      return `${prefix}<li>${content}</li>`;
    } else if (inNumList) {
      inNumList = false;
      return "</ol>\n" + line;
    }

    if (trimmed === "") {
      return "<br/>";
    }

    return `<p>${line}</p>`;
  });

  let result = parsedLines.join("\n");
  if (inTable && tableRows.length > 0) {
    result += `\n<table>${tableRows.join("")}</table>`;
  }
  if (inList) {
    result += "\n</ul>";
  }
  if (inNumList) {
    result += "\n</ol>";
  }

  return result;
}

function convertToCleanPlainText(markdown: string): string {
  if (!markdown) return "";
  let text = markdown;

  // Strip thinking blocks
  text = text.replace(/<think>[\s\S]*?<\/think>/g, "");

  // Strip headers hashes
  text = text.replace(/^#+\s+(.*)$/gim, "$1");

  // Strip bold/italic markers
  text = text.replace(/\*\*(.*?)\*\*/g, "$1");
  text = text.replace(/\*(.*?)\*/g, "$1");

  // Strip links markdown syntax
  text = text.replace(/\[(.*?)\]\((.*?)\)/g, "$1 ($2)");

  // Clean tables into tabs (industry standard for spreadsheets)
  const lines = text.split("\n");
  const cleanedLines = lines.map(line => {
    const trimmed = line.trim();
    if (trimmed.startsWith("|")) {
      if (trimmed.includes("---")) return "";
      return trimmed
        .split("|")
        .map(c => c.trim())
        .filter((_, idx, arr) => idx > 0 && idx < arr.length - 1)
        .join("\t");
    }
    return line;
  }).filter(l => l !== "");

  return cleanedLines.join("\n");
}

function deduplicateSources(sources: SourceItem[]): SourceItem[] {
  if (!sources || !Array.isArray(sources)) return [];
  const seen = new Set<string>();
  return sources.filter((src) => {
    const rawName = src.name || src.source || src.file_name || src.s3_path || "";
    const cleanName = getCleanSourceName(rawName).toLowerCase().trim();
    if (!cleanName) return false;
    if (seen.has(cleanName)) return false;
    seen.add(cleanName);
    return true;
  });
}

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
              style={{ fontWeight: "800", color: "#18181b" }}
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

const renderTextWithLinks = (text: string, isUser: boolean, themeColor: string = "#0fb5a1", onLinkClick?: (url: string) => void) => {
  if (!text) return null;
  const urlRegex = /(https?:\/\/[^\s]+?(?=[.,;:)\]?!]*(?:\s|$)))/gi;
  const parts = text.split(urlRegex);
  return parts.map((part, index) => {
    if (part.match(urlRegex)) {
      return (
        <a
          key={index}
          href={part}
          onClick={(e) => {
            if (onLinkClick) {
              e.preventDefault();
              onLinkClick(part);
            }
          }}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            textDecoration: "underline",
            wordBreak: "break-all",
            fontWeight: "bold",
            color: themeColor,
            cursor: "pointer"
          }}
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
  const stripped = stripThinking(content).trim();
  if (!stripped) return [];

  const lines = stripped.split('\n');
  const blocks: Block[] = [];
  let currentLines: string[] = [];

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    // 1. Check for Code Block start
    if (trimmed.startsWith('```')) {
      if (currentLines.length > 0) {
        blocks.push({ type: 'text', lines: [...currentLines] });
        currentLines = [];
      }

      const lang = trimmed.slice(3).trim();
      const codeLines: string[] = [];
      i++; // move past the opening ```

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

      i++; // move past the closing ```
      continue;
    }

    // 2. Check for Table start
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
        i += 2; // skip header and delimiter

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
          break; // Non-table line ends the table block
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

const renderFormattedContent = (content: string, isUser: boolean, themeColor: string = "#0fb5a1", onLinkClick?: (url: string) => void) => {
  const blocks = parseBlocks(content);
  if (blocks.length === 0) return null;

  return blocks.map((block, bIdx) => {
    if (block.type === 'table' && block.tableData) {
      return (
        <div key={`table-${bIdx}`} style={{
          overflowX: "auto",
          marginTop: "12px",
          marginBottom: "12px",
          borderRadius: "8px",
          border: "1px solid #e4e4e7",
          maxWidth: "100%"
        }}>
          <table style={{
            minWidth: "100%",
            borderCollapse: "collapse",
            fontSize: "12px",
            lineHeight: "1.5"
          }}>
            <thead>
              <tr style={{
                background: "#f4f4f5",
                borderBottom: "1px solid #e4e4e7"
              }}>
                {block.tableData.headers.map((header, idx) => {
                  const align = block.tableData!.alignments[idx] || 'left';
                  return (
                    <th
                      key={idx}
                      style={{
                        padding: "8px 12px",
                        fontWeight: "bold",
                        textAlign: align as any,
                        color: "#71717a",
                        borderBottom: "1px solid #e4e4e7"
                      }}
                    >
                      {renderTextWithLinks(header, isUser, themeColor)}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {block.tableData.rows.map((row, rowIdx) => (
                <tr key={rowIdx} style={{
                  background: rowIdx % 2 === 0 ? "transparent" : "#fbfbfb",
                  borderBottom: rowIdx === block.tableData!.rows.length - 1 ? "none" : "1px solid #e4e4e7"
                }}>
                  {block.tableData!.headers.map((_, colIdx) => {
                    const cellValue = row[colIdx] || "";
                    const align = block.tableData!.alignments[colIdx] || 'left';
                    return (
                      <td
                        key={colIdx}
                        style={{
                          padding: "8px 12px",
                          textAlign: align as any,
                          color: "#3f3f46"
                        }}
                      >
                        {renderTextWithLinks(cellValue, isUser, themeColor)}
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
        <div key={`code-${bIdx}`} style={{
          marginTop: "12px",
          marginBottom: "12px",
          borderRadius: "8px",
          overflow: "hidden",
          border: "1px solid #e4e4e7",
          maxWidth: "100%"
        }}>
          {block.codeData.language && (
            <div style={{
              padding: "6px 12px",
              fontSize: "10px",
              fontWeight: "bold",
              textTransform: "uppercase",
              borderBottom: "1px solid #e4e4e7",
              background: "#f4f4f5",
              color: "#71717a"
            }}>
              {block.codeData.language}
            </div>
          )}
          <pre style={{
            margin: 0,
            padding: "12px",
            overflowX: "auto",
            maxHeight: "250px",
            overflowY: "auto",
            whiteSpace: "pre",
            fontSize: "12px",
            fontFamily: "monospace",
            background: "#18181b",
            color: "#f4f4f5",
            maxWidth: "100%"
          }}>
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
            <div key={`${bIdx}-${index}`} className="line-anim" style={{ marginBottom: "8px", marginTop: "8px" }}>
              <div style={{ fontWeight: "800", fontSize: "14px", color: themeColor }}>
                {headingText}
              </div>
              {restText && (
                <div style={{ fontSize: "13px", marginTop: "4px", lineHeight: "1.45" }}>
                  {renderTextWithLinks(restText, isUser, themeColor, onLinkClick)}
                </div>
              )}
            </div>
          );
        }

        match = line.match(headingOnlyRegex);
        if (match) {
          const headingText = match[1];
          return (
            <div key={`${bIdx}-${index}`} className="line-anim" style={{ fontWeight: "800", fontSize: "14px", color: themeColor, marginBottom: "8px", marginTop: "8px" }}>
              {headingText}
            </div>
          );
        }

        let bulletMatch = line.match(bulletRegex);
        if (bulletMatch) {
          return (
            <div key={`${bIdx}-${index}`} className="line-anim" style={{ display: "flex", alignItems: "flex-start", gap: "8px", paddingLeft: "8px", margin: "4px 0" }}>
              <span style={{ flexShrink: 0, color: "#71717a" }}>•</span>
              <span style={{ flex: 1, fontSize: "13px", lineHeight: "1.45" }}>
                {renderTextWithLinks(bulletMatch[2], isUser, themeColor, onLinkClick)}
              </span>
            </div>
          );
        }

        let numberMatch = line.match(numberListRegex);
        if (numberMatch) {
          const prefix = numberMatch[1].trim();
          return (
            <div key={`${bIdx}-${index}`} className="line-anim" style={{ display: "flex", alignItems: "flex-start", gap: "8px", paddingLeft: "8px", margin: "4px 0" }}>
              <span style={{ flexShrink: 0, fontWeight: "bold", fontSize: "13px", color: "#71717a" }}>{prefix}</span>
              <span style={{ flex: 1, fontSize: "13px", lineHeight: "1.45" }}>
                {renderTextWithLinks(numberMatch[2], isUser, themeColor, onLinkClick)}
              </span>
            </div>
          );
        }

        return (
          <div key={`${bIdx}-${index}`} className="line-anim" style={{ minHeight: "1.25rem", lineHeight: "1.45", fontSize: "13px", margin: "2px 0" }}>
            {renderTextWithLinks(line, isUser, themeColor, onLinkClick)}
          </div>
        );
      });
    }

    return null;
  });
};

const STAGES = [
  { at: 0,    label: "Searching knowledge base..." },
  { at: 3000, label: "Reading relevant documents..." },
  { at: 8000, label: "Analyzing context..." },
  { at: 15000, label: "Generating answer..." },
  { at: 30000, label: "Still working — complex query, almost there..." },
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

function WidgetContent() {
  const searchParams = useSearchParams();
  const agentId = searchParams.get("agentId");
  const tenantId = searchParams.get("tenantId");
  const themeColor = searchParams.get("themeColor") || "#0fb5a1";
  const headerLogo = searchParams.get("headerLogo") || "";
  const headerAlign = searchParams.get("headerAlign") || "center";
  const headerNameParam = searchParams.get("headerName");
  const headerName = headerNameParam !== null ? headerNameParam : "Gsearch AI";
  const agentLabelParam = searchParams.get("agentLabel");
  const agentLabel = agentLabelParam !== null ? agentLabelParam : "Agent";
  const botAvatar = searchParams.get("botAvatar") || "";
  const buttonIcon = searchParams.get("buttonIcon") || "";
  const initialMessageParam = searchParams.get("initialMessage") || "";
  const displaySources = searchParams.get("displaySources") !== "false";
  const displayCopy = searchParams.get("displayCopy") !== "false";
  const displayFeedback = searchParams.get("displayFeedback") !== "false";
  const allowDownloads = searchParams.get("allowDownloads") !== "false";
  const linkSafety = searchParams.get("linkSafety") !== "false";

  // Lead Collection Config
  const leadCollection = searchParams.get("leadCollection") === "true";
  const rawLeadFields = searchParams.get("leadFields");
  const leadTiming = searchParams.get("leadTiming") || "pre-chat";
  const leadFields = useMemo(() => {
    if (!rawLeadFields) return ["name", "email"];
    try {
      if (rawLeadFields.startsWith("[")) {
        return JSON.parse(rawLeadFields) as string[];
      }
      return rawLeadFields.split(",").map(f => f.trim()).filter(Boolean);
    } catch {
      return ["name", "email"];
    }
  }, [rawLeadFields]);

  // Human Support Escalation Config
  const escalationEnabled = searchParams.get("escalationEnabled") === "true";
  const escalationLink = searchParams.get("escalationLink") || "";

  const renderBotAvatar = (avatar: string, theme: string) => {
    if (!avatar || avatar === "none") return null;
    if (avatar.startsWith("http") || avatar.startsWith("blob:") || avatar.startsWith("data:")) {
      return <img src={avatar} alt="Bot Avatar" style={{ width: "100%", height: "100%", objectFit: "cover" }} />;
    }
    if (avatar === "robot") {
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="11" width="18" height="10" rx="2" fill="none" />
          <circle cx="8.5" cy="15.5" r="1.5" fill="#fff" />
          <circle cx="15.5" cy="15.5" r="1.5" fill="#fff" />
          <path d="M12 2v6M9 5h6" />
        </svg>
      );
    }
    if (avatar === "setting") {
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" />
        </svg>
      );
    }
    if (avatar === "info") {
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="16" x2="12" y2="12" />
          <circle cx="12" cy="8" r="1" fill="#fff" />
        </svg>
      );
    }
    if (avatar === "book") {
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
        </svg>
      );
    }
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M21 11.5C21 16.75 16.97 21 12 21C10.13 21 8.4 20.4 6.98 19.37L3 20.5L4.15 16.63C3.42 15.15 3 13.48 3 11.5C3 6.25 7.03 2 12 2C16.97 2 21 6.25 21 11.5Z" fill="#fff" stroke="#fff" strokeWidth="1.5" />
        <circle cx="8" cy="11.5" r="1.3" fill={theme} />
        <circle cx="12" cy="11.5" r="1.3" fill={theme} />
        <circle cx="16" cy="11.5" r="1.3" fill={theme} />
      </svg>
    );
  };
  const bufferRef = useRef("");
  const [messages, setMessages] = useState<Message[]>(() => {
    if (initialMessageParam) {
      return [{ role: "assistant", content: initialMessageParam }];
    }
    return [];
  });
  const [agentSources, setAgentSources] = useState<any[]>([]);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [safetyModalUrl, setSafetyModalUrl] = useState<string | null>(null);
  const [activeSourceModal, setActiveSourceModal] = useState<SourceItem | null>(null);
  const [sourceModalLoading, setSourceModalLoading] = useState(false);
  const [sourceModalPreviewUrl, setSourceModalPreviewUrl] = useState<string | null>(null);
  const [sourceModalPreviewType, setSourceModalPreviewType] = useState<"pdf" | "image" | "csv" | "excel" | "text">("text");
  const [sourceModalCsvRows, setSourceModalCsvRows] = useState<string[][]>([]);
  const [feedbackMap, setFeedbackMap] = useState<Record<number, "thumbs_up" | "thumbs_down">>({});
  const [feedbackModalOpen, setFeedbackModalOpen] = useState(false);
  const [feedbackMessageId, setFeedbackMessageId] = useState<string | null>(null);
  const [feedbackMessageIndex, setFeedbackMessageIndex] = useState<number | null>(null);
  const [selectedReason, setSelectedReason] = useState("Incorrect Answer");
  const [customReason, setCustomReason] = useState("");
  const [activeSourceMenuIndex, setActiveSourceMenuIndex] = useState<number | null>(null);
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [wsStatus, setWsStatus] = useState<"connecting" | "open" | "closed" | "error">("closed");
  const [isTyping, setIsTyping] = useState(false);
  const progressLabel = useProgressLabel(isTyping);
  const isTypingRef = useRef(false);

  // Lead Collection State
  const [leadSubmitted, setLeadSubmitted] = useState<boolean>(false);
  const [leadFormValues, setLeadFormValues] = useState<Record<string, string>>({});
  const [submittingLead, setSubmittingLead] = useState<boolean>(false);
  useEffect(() => {
    isTypingRef.current = isTyping;
  }, [isTyping]);

  const typingTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const resetTypingTimeout = useCallback(() => {
    if (typingTimeoutRef.current) {
      clearTimeout(typingTimeoutRef.current);
      typingTimeoutRef.current = null;
    }
  }, []);

  const startTypingTimeout = useCallback(() => {
    resetTypingTimeout();
    typingTimeoutRef.current = setTimeout(() => {
      if (isTypingRef.current) {
        setIsTyping(false);
        isTypingRef.current = false;
        // Only show error if we haven't received any content yet
        if (!bufferRef.current) {
          const friendlyError = "Something went wrong. Please try again later.";
          setMessages((prev) => {
            const lastMsg = prev[prev.length - 1];
            if (lastMsg && lastMsg.role === "assistant") {
              if (!lastMsg.content) {
                return [...prev.slice(0, -1), { ...lastMsg, content: friendlyError }];
              }
              return prev;
            }
            return [...prev, { role: "assistant", content: friendlyError }];
          });
        }
      }
    }, 90000); // 90 seconds timeout
  }, [resetTypingTimeout]);

  const getApiBaseUrl = (): string => {
    let raw = process.env.NEXT_PUBLIC_API_BASE_URL || process.env.NEXT_PUBLIC_API_BASES_URL || "http://192.168.31.62:4915/api/v1";
    let cleaned = raw.trim().replace(/\/+$/, "");
    if (!cleaned.endsWith("/api/v1")) {
      cleaned = `${cleaned}/api/v1`;
    }
    return cleaned;
  };

  const getS3Key = (s3Path?: string): string => {
    if (!s3Path) return "";
    return s3Path.replace(/^https?:\/\/[^\/]+\//, "").replace(/^s3:\/\/[^\/]+\//, "");
  };

  const getFullUrl = (urlStr?: string): string => {
    if (!urlStr) return "";
    if (urlStr.startsWith("http://") || urlStr.startsWith("https://") || urlStr.startsWith("blob:")) {
      return urlStr;
    }
    const baseUrl = getApiBaseUrl();
    const rootBase = baseUrl.replace(/\/api\/v1\/?$/, "");
    return `${rootBase}${urlStr.startsWith("/") ? "" : "/"}${urlStr}`;
  };

  const toProxyUrl = useCallback((url: string): string => {
    if (!url) return url;
    const cleanUrl = url.split("?")[0];
    const s3Match = cleanUrl.match(/amazonaws\.com\/grag\/logos\/(.+)/);
    if (s3Match) {
      const baseUrl = getApiBaseUrl();
      return `${baseUrl}/embed/logo/render/${s3Match[1]}`;
    }
    if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("blob:") || url.startsWith("data:")) {
      return url;
    }
    const proxyMatch = cleanUrl.match(/\/embed\/logo\/render\/(.+)/);
    if (proxyMatch) {
      const baseUrl = getApiBaseUrl();
      return `${baseUrl}/embed/logo/render/${proxyMatch[1]}`;
    }
    return url;
  }, []);

  const resolvedHeaderLogo = useMemo(() => toProxyUrl(headerLogo), [headerLogo, toProxyUrl]);
  const resolvedBotAvatar = useMemo(() => toProxyUrl(botAvatar), [botAvatar, toProxyUrl]);
  const resolvedButtonIcon = useMemo(() => toProxyUrl(buttonIcon), [buttonIcon, toProxyUrl]);

  const [customizationLogoUrl, setCustomizationLogoUrl] = useState<string>(resolvedHeaderLogo || "");
  const [showInHeader, setShowInHeader] = useState<boolean>(true);
  const [showInChat, setShowInChat] = useState<boolean>(true);
  const [showInEmbed, setShowInEmbed] = useState<boolean>(false);

  useEffect(() => {
    if (!tenantId) return;
    const fetchEmbedCustomization = async () => {
      try {
        const baseUrl = getApiBaseUrl();
        const res = await fetch(`${baseUrl}/embed/customization?tenant_id=${tenantId}`);
        if (res.ok) {
          const result = await res.json();
          const data = result.data ?? result;
          if (data) {
            if (data.logo_url) {
              setCustomizationLogoUrl(toProxyUrl(data.logo_url));
            }
            if (typeof data.show_in_header === "boolean") setShowInHeader(data.show_in_header);
            if (typeof data.show_in_chat === "boolean") setShowInChat(data.show_in_chat);
            if (typeof data.show_in_embed === "boolean") setShowInEmbed(data.show_in_embed);
          }
        }
      } catch (err) {
        console.warn("Failed to fetch embed customization:", err);
      }
    };
    fetchEmbedCustomization();
  }, [tenantId]);

  useEffect(() => {
    if (!agentId) return;
    const fetchKbSources = async () => {
      try {
        const baseUrl = getApiBaseUrl();
        const res = await fetch(`${baseUrl}/embed/agents/${agentId}/sources`);
        if (res.ok) {
          const result = await res.json();
          const data = result.data ?? result;
          const list = Array.isArray(data) ? data : (Array.isArray(data?.sources) ? data.sources : (Array.isArray(data?.kbs) ? data.kbs : []));
          setAgentSources(list);
        }
      } catch (err) {
        console.warn("Failed to fetch agent KB sources:", err);
      }
    };
    fetchKbSources();
  }, [agentId]);

  const handleOpenSource = async (src: SourceItem, allSources?: SourceItem[], activeIdx = 0) => {
    const targetSrc = { ...src };

    const getCleanUrl = (str?: string): string | null => {
      if (!str) return null;
      let cleaned = str.replace(/\s*\((Selected Links|Selected Link)\)\s*/i, "").trim();
      if (cleaned.startsWith("http://") || cleaned.startsWith("https://")) {
        return cleaned;
      }
      return null;
    };

    const directUrl = getCleanUrl(targetSrc.url) || getCleanUrl(targetSrc.name) || getCleanUrl(targetSrc.source);

    if (directUrl) {
      const isPDF = directUrl.toLowerCase().includes(".pdf");
      const isExcel = directUrl.toLowerCase().includes(".xlsx") || directUrl.toLowerCase().includes(".xls") || directUrl.toLowerCase().includes(".csv");

      if (!isPDF && !isExcel) {
        window.open(directUrl, "_blank", "noopener,noreferrer");
        setSourceModalLoading(false);
        return;
      }
    }

    const targetNameRaw = targetSrc.name || targetSrc.source || "";
    const isSelectedLink = targetNameRaw.includes("Selected Links") || targetNameRaw.includes("Selected Link");

    const baseUrl = getApiBaseUrl();
    let currentSources = agentSources;
    if (agentId && currentSources.length === 0) {
      try {
        const res = await fetch(`${baseUrl}/embed/agents/${agentId}/sources`);
        if (res.ok) {
          const result = await res.json();
          const data = result.data ?? result;
          currentSources = Array.isArray(data) ? data : (Array.isArray(data?.sources) ? data.sources : (Array.isArray(data?.kbs) ? data.kbs : []));
          setAgentSources(currentSources);
        }
      } catch (err) {
        console.warn("fetchAgentSources error:", err);
      }
    }

    if (isSelectedLink) {
      const coreKeyword = targetNameRaw.replace(/\s*\((Selected Links|Selected Link)\)\s*/i, "").trim().toLowerCase();
      
      const foundSource = currentSources.find(as => {
        const asName = String(as.name || "").toLowerCase();
        const asUrl = String(as.url || "").toLowerCase();
        const asSrc = String(as.source || "").toLowerCase();
        return (coreKeyword && (asName.includes(coreKeyword) || asUrl.includes(coreKeyword) || asSrc.includes(coreKeyword)));
      });

      if (foundSource) {
        const matchedUrl = foundSource.name || foundSource.url || foundSource.source || "";
        const cleanMatchedUrl = getCleanUrl(matchedUrl);
        if (cleanMatchedUrl) {
          window.open(cleanMatchedUrl, "_blank", "noopener,noreferrer");
          setSourceModalLoading(false);
          return;
        }
      }

      setSourceModalLoading(false);
      return;
    }

    if (sourceModalPreviewUrl && sourceModalPreviewUrl.startsWith("blob:")) {
      URL.revokeObjectURL(sourceModalPreviewUrl);
    }
    setSourceModalPreviewUrl(null);
    setSourceModalCsvRows([]);
    setSourceModalLoading(true);

    if (allSources && allSources.length > 0) {
      setActiveSourceList(allSources);
      setActiveSourceIndex(activeIdx);
    }

    const getFileNameStr = (urlOrName?: string): string => {
      if (!urlOrName) return "";
      const str = String(urlOrName);
      const parts = str.split(/[/\\]/);
      return parts[parts.length - 1] || str;
    };

    const cleanStr = (s?: string) => {
      if (!s) return "";
      return getFileNameStr(s).toLowerCase().replace(/[^a-z0-9]/g, "");
    };

    const getCleanDisplayName = (raw?: string): string => {
      if (!raw) return "";
      let str = getFileNameStr(raw);
      return str.replace(/^(pdf|doc|docx|csv|xlsx|image|img|txt):\s*/i, "").trim();
    };

    let displayTitle = getCleanDisplayName(targetSrc.name || targetSrc.source || targetSrc.file_name);
    if (displayTitle.includes(",")) {
      const parts = displayTitle.split(",");
      displayTitle = parts[activeIdx]?.trim() || parts[0].trim();
    }
    targetSrc.name = displayTitle || "Source Document";

    const targetClean = cleanStr(displayTitle || targetSrc.source || targetSrc.s3_path);
    let matched = currentSources.find(as => {
      const asNameClean = cleanStr(as.name);
      const asSourceClean = cleanStr(as.source);
      const asPathClean = cleanStr(as.s3_path);
      const asFileNameClean = cleanStr(as.file_name);
      const asIdClean = cleanStr(as.id || as.kb_id);

      return (
        (asNameClean && targetClean && (asNameClean.includes(targetClean) || targetClean.includes(asNameClean))) ||
        (asSourceClean && targetClean && (asSourceClean.includes(targetClean) || targetClean.includes(asSourceClean))) ||
        (asPathClean && targetClean && (asPathClean.includes(targetClean) || targetClean.includes(asPathClean))) ||
        (asFileNameClean && targetClean && (asFileNameClean.includes(targetClean) || targetClean.includes(asFileNameClean))) ||
        (asIdClean && targetClean && (asIdClean === targetClean))
      );
    });

    if (!matched && (targetSrc.kb_id || targetSrc.id)) {
      const idToMatch = targetSrc.kb_id || targetSrc.id;
      matched = currentSources.find(as => as.id === idToMatch || as.kb_id === idToMatch);
    }

    if (matched) {
      if (matched.id || matched.kb_id) targetSrc.kb_id = matched.id || matched.kb_id;
      if (matched.s3_path) targetSrc.s3_path = matched.s3_path;
      if (matched.url) targetSrc.url = matched.url;
      if (matched.content) targetSrc.content = matched.content;
      if (matched.text) targetSrc.text = matched.text;
      if (matched.name && !targetSrc.name) targetSrc.name = getCleanDisplayName(matched.name);
    }

    const matchedUrl = getCleanUrl(targetSrc.url) || getCleanUrl(targetSrc.name) || getCleanUrl(targetSrc.source);
    if (matchedUrl) {
      const isPDF = matchedUrl.toLowerCase().includes(".pdf");
      const isExcel = matchedUrl.toLowerCase().includes(".xlsx") || matchedUrl.toLowerCase().includes(".xls") || matchedUrl.toLowerCase().includes(".csv");

      if (!isPDF && !isExcel) {
        window.open(matchedUrl, "_blank", "noopener,noreferrer");
        setSourceModalLoading(false);
        return;
      }
    }

    setActiveSourceModal({ ...targetSrc });

    const kbId = targetSrc.kb_id || targetSrc.id;
    let previewBlobUrl: string | null = null;
    let blobContentType = "";

    // 1. Try targetSrc.url if present (e.g. /api/v1/embed/files/{id}/preview returned by backend)
    if (targetSrc.url) {
      try {
        const fullUrl = getFullUrl(targetSrc.url);
        const res = await fetch(fullUrl);
        if (res.ok) {
          const blob = await res.blob();
          blobContentType = blob.type.toLowerCase();
          previewBlobUrl = URL.createObjectURL(blob);
        }
      } catch (err) {
        console.warn("targetSrc.url fetch error:", err);
      }
    }

    // 2. Call public /embed/files/{kbId}/preview endpoint
    if (!previewBlobUrl && kbId) {
      try {
        const res = await fetch(`${baseUrl}/embed/files/${kbId}/preview`);
        if (res.ok) {
          const blob = await res.blob();
          blobContentType = blob.type.toLowerCase();
          previewBlobUrl = URL.createObjectURL(blob);
        }
      } catch (err) {
        console.warn("kb_id preview fetch error:", err);
      }
    }

    // 3. S3 key backend endpoint strategy
    if (!previewBlobUrl && (targetSrc.s3_path || targetSrc.file_path)) {
      const rawPath = targetSrc.s3_path || targetSrc.file_path || "";
      const s3Key = getS3Key(rawPath);
      if (s3Key) {
        try {
          const previewUrl = `${baseUrl}/embed/files/preview?key=${encodeURIComponent(s3Key)}`;
          const res = await fetch(previewUrl);
          if (res.ok) {
            const blob = await res.blob();
            blobContentType = blob.type.toLowerCase();
            previewBlobUrl = URL.createObjectURL(blob);
          }
        } catch (err) {
          console.warn("s3 key preview fetch error:", err);
        }
      }
    }

    const fullStr = `${targetSrc.name || ''} ${targetSrc.source || ''} ${targetSrc.file_name || ''} ${targetSrc.s3_path || ''} ${targetSrc.url || ''}`.toLowerCase();
    const isPDF = blobContentType.includes("pdf") || fullStr.includes(".pdf");
    const isImage = blobContentType.includes("image") || fullStr.includes(".png") || fullStr.includes(".jpg") || fullStr.includes(".jpeg") || fullStr.includes(".webp") || fullStr.includes(".gif");
    const isCSV = blobContentType.includes("csv") || fullStr.includes(".csv");
    const isExcel = blobContentType.includes("excel") || blobContentType.includes("spreadsheet") || fullStr.includes(".xlsx") || fullStr.includes(".xls");

    if (isPDF && previewBlobUrl) {
      setSourceModalPreviewType("pdf");
      setSourceModalPreviewUrl(previewBlobUrl);
    } else if (isImage && previewBlobUrl) {
      setSourceModalPreviewType("image");
      setSourceModalPreviewUrl(previewBlobUrl);
    } else if ((isCSV || isExcel) && previewBlobUrl) {
      setSourceModalPreviewType(isCSV ? "csv" : "excel");
      try {
        const res = await fetch(previewBlobUrl);
        const blob = await res.blob();
        const arrayBuffer = await blob.arrayBuffer();
        const XLSX = await import("xlsx");
        const workbook = XLSX.read(arrayBuffer, { type: "array" });
        const firstSheet = workbook.SheetNames[0];
        if (firstSheet) {
          const worksheet = workbook.Sheets[firstSheet];
          const jsonData = XLSX.utils.sheet_to_json<any[]>(worksheet, { header: 1 });
          const rows = jsonData.map((row: any) =>
            Array.isArray(row) ? row.map(c => (c !== null && c !== undefined ? String(c) : "")) : []
          );
          setSourceModalCsvRows(rows);
        }
      } catch (err) {
        console.warn("Excel/CSV parse error:", err);
      }
    } else if (previewBlobUrl) {
      setSourceModalPreviewType("text");
      setSourceModalPreviewUrl(previewBlobUrl);
      try {
        const res = await fetch(previewBlobUrl);
        const textData = await res.text();
        if (textData && textData.trim()) {
          setActiveSourceModal((prev) => prev ? { ...prev, text: textData } : prev);
        }
      } catch (e) {
        // keep text
      }
    } else {
      setSourceModalPreviewType("text");
    }

    setSourceModalLoading(false);
  };

  const downloadSourceFile = async (targetSrc: SourceItem) => {
    if (!allowDownloads) {
      setToastMsg("🔒 Source downloads restricted by site admin");
      setTimeout(() => setToastMsg(null), 3000);
      return;
    }

    const kbId = targetSrc.kb_id || targetSrc.id;
    const fileName = targetSrc.name || targetSrc.source || targetSrc.file_name || "knowledge_document";
    const baseUrl = getApiBaseUrl();

    // 1. Try fetching via public embed file preview endpoint
    if (kbId) {
      try {
        const res = await fetch(`${baseUrl}/embed/files/${kbId}/preview`);
        if (res.ok) {
          const blob = await res.blob();
          const blobUrl = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = blobUrl;
          a.download = fileName;
          a.click();
          URL.revokeObjectURL(blobUrl);
          return;
        }
      } catch (err) {
        console.warn("kb_id preview fetch error:", err);
      }
    }

    // 2. Direct S3 / HTTP link Strategy
    let fileUrl = targetSrc.s3_path || targetSrc.url || targetSrc.file_path;
    if (fileUrl && fileUrl.startsWith("s3://")) {
      const s3Key = fileUrl.replace(/^s3:\/\/[^\/]+\//, "");
      fileUrl = `${baseUrl}/files/preview?key=${encodeURIComponent(s3Key)}`;
    }

    if (fileUrl && (fileUrl.startsWith("http://") || fileUrl.startsWith("https://") || fileUrl.startsWith("blob:"))) {
      try {
        const res = await fetch(fileUrl);
        if (res.ok) {
          const blob = await res.blob();
          const blobUrl = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = blobUrl;
          a.download = fileName;
          a.click();
          URL.revokeObjectURL(blobUrl);
          return;
        }
      } catch (err) {
        window.open(fileUrl, "_blank", "noopener,noreferrer");
        return;
      }
    }

    // 3. Fallback text content blob download
    const textContent = targetSrc.text || targetSrc.content || targetSrc.page_content || targetSrc.snippet || `Knowledge Base Document: ${fileName}`;
    const blob = new Blob([textContent], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${fileName.replace(/\.[^/.]+$/, "")}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const [activeSourceList, setActiveSourceList] = useState<SourceItem[]>([]);
  const [activeSourceIndex, setActiveSourceIndex] = useState<number>(0);

  const closeSourceModal = () => {
    if (sourceModalPreviewUrl && sourceModalPreviewUrl.startsWith("blob:")) {
      URL.revokeObjectURL(sourceModalPreviewUrl);
    }
    setSourceModalPreviewUrl(null);
    setSourceModalCsvRows([]);
    setActiveSourceModal(null);
    setActiveSourceList([]);
    setActiveSourceIndex(0);
  };

  const handleFeedback = async (index: number, msgId?: string, type?: "thumbs_up" | "thumbs_down") => {
    if (!type) return;

    const targetMsgId = msgId || (messages[index] && (messages[index].id || (messages[index] as any).message_id)) || `widget_msg_${index}_${Date.now()}`;

    if (type === "thumbs_up") {
      const currentFb = feedbackMap[index];
      const newFb = currentFb === "thumbs_up" ? undefined : "thumbs_up";

      setFeedbackMap((prev) => {
        const next = { ...prev };
        if (newFb) next[index] = newFb;
        else delete next[index];
        return next;
      });

      if (newFb) {
        setToastMsg("Thank you for your feedback!");
        setTimeout(() => setToastMsg(null), 2500);

        try {
          const baseUrl = getApiBaseUrl();
          const payload = {
            message_id: targetMsgId,
            agent_id: agentId || "",
            tenant_id: tenantId || "",
            feedback_type: "thumbs_up",
            feedback_reason: "Correct response",
          };

          let res = await fetch(`${baseUrl}/embed/chats/messages/feedback`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });

          if (!res.ok) {
            await fetch(`${baseUrl}/chats/messages/feedback`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload),
            });
          }
        } catch (err) {
          console.warn("Feedback API call attempted:", err);
        }
      }
    } else {
      setFeedbackMessageId(targetMsgId);
      setFeedbackMessageIndex(index);
      setFeedbackModalOpen(true);
    }
  };

  const submitThumbsDownFeedback = async () => {
    if (feedbackMessageIndex === null || !feedbackMessageId) return;

    const index = feedbackMessageIndex;
    const finalReason = selectedReason === "Other" ? customReason.trim() || "Other" : selectedReason;

    setFeedbackMap((prev) => {
      const next = { ...prev };
      next[index] = "thumbs_down";
      return next;
    });

    setToastMsg("Thank you for your feedback!");
    setTimeout(() => setToastMsg(null), 2500);

    try {
      const baseUrl = getApiBaseUrl();
      const payload = {
        message_id: feedbackMessageId,
        agent_id: agentId || "",
        tenant_id: tenantId || "",
        feedback_type: "thumbs_down",
        feedback_reason: finalReason,
      };

      let res = await fetch(`${baseUrl}/embed/chats/messages/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        await fetch(`${baseUrl}/chats/messages/feedback`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      }
    } catch (err) {
      console.warn("Feedback API call attempted:", err);
    } finally {
      setFeedbackModalOpen(false);
      setFeedbackMessageId(null);
      setFeedbackMessageIndex(null);
      setCustomReason("");
      setSelectedReason("Incorrect Answer");
    }
  };

  const ws = useRef<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const initialQuerySentRef = useRef(false);
  const pendingQueryRef = useRef("");
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const typewriterQueueRef = useRef("");
  const typewriterIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const wsDoneRef = useRef(false);
  const currentMsgIdRef = useRef<string | null>(null);
  const currentSourcesRef = useRef<any[]>([]);
  const currentEscalationRef = useRef(false);

  const resetTypewriter = useCallback(() => {
    typewriterQueueRef.current = "";
    wsDoneRef.current = false;
    currentMsgIdRef.current = null;
    currentSourcesRef.current = [];
    currentEscalationRef.current = false;
    if (typewriterIntervalRef.current) {
      clearInterval(typewriterIntervalRef.current);
      typewriterIntervalRef.current = null;
    }
  }, []);

  const startTypewriter = useCallback(() => {
    if (typewriterIntervalRef.current) return;

    typewriterIntervalRef.current = setInterval(() => {
      if (typewriterQueueRef.current.length === 0) {
        if (wsDoneRef.current) {
          if (typewriterIntervalRef.current) {
            clearInterval(typewriterIntervalRef.current);
            typewriterIntervalRef.current = null;
          }
          setIsTyping(false);
          resetTypingTimeout();
        }
        return;
      }

      const queueLen = typewriterQueueRef.current.length;
      let takeCount = 1;
      if (queueLen > 120) takeCount = 8;
      else if (queueLen > 60) takeCount = 4;
      else if (queueLen > 20) takeCount = 2;

      const chunk = typewriterQueueRef.current.slice(0, takeCount);
      typewriterQueueRef.current = typewriterQueueRef.current.slice(takeCount);

      bufferRef.current += chunk;
      const rawStream = bufferRef.current;

      const citationRegex = /(?:\[Source:\s*|\(Source:\s*)([^\]\)]+)[\]\)]/gi;
      const extractedCitations: SourceItem[] = [];
      let citationMatch;
      while ((citationMatch = citationRegex.exec(rawStream)) !== null) {
        let srcName = citationMatch[1].trim();
        if (srcName.includes(" - Position")) srcName = srcName.split(" - Position")[0].trim();
        extractedCitations.push({
          name: srcName,
          source: srcName,
          text: `Citation reference: ${srcName}`
        });
      }

      const cleanedText = rawStream
        .replace(/<think>[\s\S]*?<\/think>/g, "")
        .replace(/(?:\[Source:[^\]]*\]?)/gi, "")
        .replace(/(?:\(Source:[^)]*\)?)/gi, "")
        .trim();

      setMessages((prev) => {
        const lastMsg = prev[prev.length - 1];
        
        let finalSources = (currentSourcesRef.current && currentSourcesRef.current.length > 0)
          ? currentSourcesRef.current
          : (lastMsg?.sources && lastMsg.sources.length > 0)
            ? lastMsg.sources
            : (extractedCitations.length > 0 ? extractedCitations : undefined);

        if (finalSources && finalSources.length > 0) {
          const citedFilenames = getCitedFilenames(rawStream);
          if (citedFilenames.length > 0) {
            finalSources = finalSources.filter((src: any) => matchesCitation(src, citedFilenames));
          }
        }

        if (lastMsg && lastMsg.role === "assistant") {
          return [
            ...prev.slice(0, -1),
            {
              ...lastMsg,
              content: cleanedText,
              id: lastMsg.id || currentMsgIdRef.current || undefined,
              sources: finalSources,
              escalation_detected: lastMsg.escalation_detected || currentEscalationRef.current === true
            },
          ];
        } else {
          return [...prev, { role: "assistant", content: cleanedText, id: currentMsgIdRef.current || undefined, sources: finalSources, escalation_detected: currentEscalationRef.current === true }];
        }
      });
    }, 15);
  }, [resetTypingTimeout]);

  const handleClose = () => {
    window.parent.postMessage({ type: "close-chat" }, "*");
  };

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.data && event.data.type === "focus-input") {
        setTimeout(() => {
          inputRef.current?.focus();
        }, 150);
        return;
      }
      if (event.data && event.data.type === "send-query") {
        const query = event.data.query;
        if (query) {
          bufferRef.current = "";
          setMessages((prev) => [...prev, { role: "user", content: query }]);
          setIsTyping(true);
          startTypingTimeout();
          if (ws.current && ws.current.readyState === WebSocket.OPEN) {
            ws.current.send(JSON.stringify({ message: query, query: query, embed: true, is_embed: true }));
          } else {
            pendingQueryRef.current = query;
          }
        }
      }
    };
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, []);

  // Auto-grow textarea height on value change
  useEffect(() => {
    const textarea = inputRef.current;
    if (!textarea) return;
    textarea.style.height = "22px";
    const newHeight = Math.min(120, textarea.scrollHeight);
    textarea.style.height = `${newHeight}px`;
  }, [input]);

  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.classList.add("widget-page");
      const style = document.createElement("style");
      style.id = "force-transparent-bg";
      style.innerHTML = `
        html, body, #__next, [class^="ant-"], .ant-app, .ant-layout {
          background: transparent !important;
          background-color: transparent !important;
        }
        @keyframes lineFadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        .line-anim {
          animation: lineFadeIn 0.15s ease-out forwards;
        }
        @keyframes pulseGently {
          0%, 100% { opacity: 0.2; }
          50% { opacity: 1; }
        }
        .typing-cursor {
          display: inline-block;
          animation: pulseGently 0.8s infinite;
          vertical-align: middle;
          font-weight: 900;
          font-size: 16px;
          text-shadow: 0 0 4px ${themeColor};
        }
      `;
      document.head.appendChild(style);
      return () => {
        document.documentElement.classList.remove("widget-page");
        document.getElementById("force-transparent-bg")?.remove();
      };
    }
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  const connectWs = useCallback(() => {
    if (!agentId || !tenantId || tenantId === "null" || tenantId === "undefined") return;

    resetTypewriter();

    if (ws.current) {
      try {
        ws.current.onclose = null;
        ws.current.onerror = null;
        ws.current.close();
      } catch (e) {}
    }

    const wsHost = (process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:4915").replace(/\/$/, "");
    const wsBaseUrl = wsHost.includes("/api/v1") ? wsHost : `${wsHost}/api/v1`;
    const wsUrl = `${wsBaseUrl}/embed/chats/${agentId}/ws?tenant_id=${tenantId}`;
    const socket = new WebSocket(wsUrl);
    ws.current = socket;

    socket.onopen = () => {
      setWsStatus("open");
      const pendingQuery = pendingQueryRef.current;
      if (pendingQuery) {
        pendingQueryRef.current = "";
        initialQuerySentRef.current = true;
        startTypingTimeout();
        socket.send(JSON.stringify({ message: pendingQuery, query: pendingQuery, embed: true, is_embed: true }));
        return;
      }

      const initialQuery = searchParams.get("q");
      if (initialQuery && !initialQuerySentRef.current) {
        initialQuerySentRef.current = true;
        setMessages((prev) => [...prev, { role: "user", content: initialQuery }]);
        setIsTyping(true);
        startTypingTimeout();
        socket.send(JSON.stringify({ message: initialQuery, query: initialQuery, embed: true, is_embed: true }));
      }
    };

    socket.onmessage = (event) => {
      console.log("WebSocket Raw Message:", event.data);
      try {
        const data = JSON.parse(event.data);

        // Reset inactivity timer on every message chunk received
        startTypingTimeout();

        if (data.type === "start") {
          setIsTyping(true);
          if (data.message_id || data.id) {
            const msgId = data.message_id || data.id;
            setMessages((prev) => {
              const lastMsg = prev[prev.length - 1];
              if (lastMsg && lastMsg.role === "assistant") {
                return [...prev.slice(0, -1), { ...lastMsg, id: msgId }];
              }
              return prev;
            });
          }
          return;
        }

        if ((data.type === "sources" || data.sources || data.source_documents) && (data.sources || data.source_documents)) {
          // Handle nested formats: {sources: [...]}, {sources: {data: [...]}}, {source_documents: [...]}
          let rawSources = data.sources || data.source_documents;
          if (rawSources && !Array.isArray(rawSources)) {
            rawSources = Array.isArray(rawSources.data) ? rawSources.data : [];
          }
          if (Array.isArray(rawSources) && rawSources.length > 0) {
            setMessages((prev) => {
              const lastMsg = prev[prev.length - 1];
              if (lastMsg && lastMsg.role === "assistant") {
                return [...prev.slice(0, -1), { ...lastMsg, sources: rawSources }];
              }
              return prev;
            });
          }
        }

        if (data.type === "content" && data.delta) {
          if (data.delta.includes("LLM streaming failed") || data.delta.startsWith("Error:")) {
            resetTypewriter();
            setIsTyping(false);
            resetTypingTimeout();
            const friendlyError = "Sorry, I am having trouble connecting to the AI model right now. Please try again in a moment.";
            setMessages((prev) => {
              const lastMsg = prev[prev.length - 1];
              if (lastMsg && lastMsg.role === "assistant") {
                return [...prev.slice(0, -1), { ...lastMsg, content: friendlyError }];
              }
              return [...prev, { role: "assistant", content: friendlyError }];
            });
            return;
          }

          typewriterQueueRef.current += data.delta;
          if (data.message_id) currentMsgIdRef.current = data.message_id;
          if (data.escalation_detected === true) currentEscalationRef.current = true;

          const backendSources = data.sources || data.source_documents;
          if (backendSources && backendSources.length > 0) {
            let rawSources = backendSources;
            if (rawSources && !Array.isArray(rawSources)) {
              rawSources = Array.isArray(rawSources.data) ? rawSources.data : [];
            }
            currentSourcesRef.current = rawSources;
          }

          setIsTyping(true);
          startTypewriter();
        }

        if (data.type === "done" || data.type === "end") {
          wsDoneRef.current = true;
          if (data.message_id) currentMsgIdRef.current = data.message_id;
          if (data.escalation_detected === true) currentEscalationRef.current = true;
          startTypewriter();
        }
      } catch (err) {
        setIsTyping(false);
        resetTypingTimeout();
        const text = String(event.data);
        setMessages((prev) => [...prev, { role: "assistant", content: text }]);
      }
    };

    socket.onclose = () => {
      setWsStatus("closed");
      resetTypingTimeout();
      if (isTypingRef.current && !bufferRef.current) {
        const friendlyError = "Something went wrong. Please try again later.";
        setMessages((prev) => {
          const lastMsg = prev[prev.length - 1];
          if (lastMsg && lastMsg.role === "assistant") {
            return [...prev.slice(0, -1), { ...lastMsg, content: friendlyError }];
          }
          return [...prev, { role: "assistant", content: friendlyError }];
        });
      }
      setIsTyping(false);
    };

    socket.onerror = () => {
      setWsStatus("error");
      resetTypingTimeout();
      if (isTypingRef.current && !bufferRef.current) {
        const friendlyError = "Something went wrong. Please try again later.";
        setMessages((prev) => {
          const lastMsg = prev[prev.length - 1];
          if (lastMsg && lastMsg.role === "assistant") {
            return [...prev.slice(0, -1), { ...lastMsg, content: friendlyError }];
          }
          return [...prev, { role: "assistant", content: friendlyError }];
        });
      }
      setIsTyping(false);
    };
  }, [agentId, tenantId, searchParams]);

  useEffect(() => {
    connectWs();
    return () => {
      if (ws.current) {
        ws.current.onclose = null;
        ws.current.onerror = null;
        ws.current.close();
      }
    };
  }, [connectWs]);

  const handleSend = () => {
    const message = input.trim();
    if (!message) return;
    resetTypewriter();
    bufferRef.current = ""; // reset old response
    setMessages((prev) => [...prev, { role: "user", content: message }]);
    setIsTyping(true);
    startTypingTimeout();
    if (ws.current && ws.current.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify({ message: message, query: message, embed: true, is_embed: true }));
    } else if (ws.current && ws.current.readyState === WebSocket.CONNECTING) {
      pendingQueryRef.current = message;
    } else {
      pendingQueryRef.current = message;
      connectWs();
    }
    setInput("");
  };

  return (
    <div
      style={{
        margin: 0,
        padding: "8px",
        height: "100vh",
        width: "100%",
        display: "flex",
        flexDirection: "column",
        background: "transparent",
        fontFamily: CHAT_FONT_FAMILY,
        color: "#222",
        boxSizing: "border-box",
        overflow: "hidden",
      }}
    >
      <style>{`
        :root, :root[data-theme], :root[data-theme="dark"], :root[data-theme="light"] {
          --background: transparent !important;
        }
        html, body, body > div, body > div > div, #__next, #__next > div,
        div[data-nextjs-scroll-focus-boundary] {
          background: transparent !important;
          background-color: transparent !important;
        }
        [class*="ant-"] {
          background: transparent !important;
          background-color: transparent !important;
        }
        @keyframes pulse {
          0%, 100% { opacity: 0.3; transform: scale(0.8); }
          50% { opacity: 1; transform: scale(1.2); }
        }
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
        @keyframes borderShift {
          0% { background-position: 0% 50%; }
          100% { background-position: 100% 50%; }
        }
        .widget-send-btn {
          width: 36px;
          height: 36px;
        }
        @media (max-width: 640px) {
          .widget-send-btn {
            width: 30px !important;
            height: 30px !important;
          }
        }
        .typing-dot {
          width: 6px;
          height: 6px;
          background-color: ${themeColor};
          border-radius: 50%;
          display: inline-block;
          animation: pulse 1.4s infinite ease-in-out both;
        }
        .typing-dot:nth-child(2) { animation-delay: 0.2s; }
        .typing-dot:nth-child(3) { animation-delay: 0.4s; }
        
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #e5e5e5; border-radius: 10px; }
        ::-webkit-scrollbar-thumb:hover { background: #d4d4d4; }
        .close-btn {
          position: relative;
          width: 16px;
          height: 16px;
          cursor: pointer;
          opacity: 0.6;
          transition: opacity 0.2s;
        }
        .close-btn:hover { opacity: 1; }
        .close-btn::before, .close-btn::after {
          position: absolute;
          left: 7px;
          content: ' ';
          height: 16px;
          width: 1.5px;
          background-color: #555;
        }
        .close-btn::before { transform: rotate(45deg); }
        .close-btn::after { transform: rotate(-45deg); }
      `}</style>

      {/* Main Chat Feed Box (White Card) */}
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          background: "#ffffff",
          borderRadius: "24px",
          // boxShadow: "0 2px 8px rgba(0,0,0,0.06), 0 8px 24px rgba(0,0,0,0.08), 0 20px 48px rgba(0,0,0,0.06)",
          overflow: "hidden",
          border: "1px solid rgba(0,0,0,0.07)",
          marginBottom: "12px",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "16px 20px",
            background: "#ffffff",
            borderBottom: "1px solid #f0f0f0",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div style={{
            display: "flex",
            alignItems: "center",
            gap: "12px",
            width: "100%",
            justifyContent: headerAlign === "center" ? "center" : "flex-start"
          }}>
            {(showInHeader || resolvedHeaderLogo) && (resolvedHeaderLogo || customizationLogoUrl) ? (
              <div style={{ height: "36px", display: "flex", alignItems: "center" }}>
                <img src={resolvedHeaderLogo || customizationLogoUrl} alt="Header Logo" style={{ maxHeight: "36px", maxWidth: "120px", objectFit: "contain" }} />
              </div>
            ) : (
              <div style={{
                width: "36px", height: "36px", borderRadius: "10px",
                display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden"
              }}>
                <img src="/512_512.png" alt="Gsearch Logo" style={{ width: "36px", height: "36px", objectFit: "contain" }} />
              </div>
            )}

            <div>
              <div style={{ fontWeight: 600, fontSize: "15px", color: "#171717", display: "flex", alignItems: "center", gap: "6px" }}>
                {headerName}
                <span style={{ fontSize: "10px", color: wsStatus === "open" ? "#22c55e" : "#ef4444" }}>●</span>
              </div>
              <div style={{ fontSize: "12px", color: "#737373" }}>
                The team can also help
              </div>
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", paddingRight: "4px" }}>
            <div className="close-btn" onClick={handleClose} title="Close chat" />
          </div>
        </div>

        {/* Feedback Toast Notification */}
        {toastMsg && (
          <div style={{
            position: "absolute",
            top: "64px",
            left: "50%",
            transform: "translateX(-50%)",
            background: "#18181b",
            color: "#ffffff",
            padding: "6px 14px",
            borderRadius: "20px",
            fontSize: "11px",
            fontWeight: "600",
            boxShadow: "0 4px 14px rgba(0,0,0,0.18)",
            zIndex: 60,
            display: "flex",
            alignItems: "center",
            gap: "5px"
          }}>
            <span>✨ {toastMsg}</span>
          </div>
        )}

        {/* Lead Form or Chat Content */}
        {leadCollection && leadTiming === "pre-chat" && !leadSubmitted ? (
          <div style={{
            flex: 1,
            padding: "24px",
            background: "#f9f9f9",
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            alignItems: "stretch",
            overflowY: "auto"
          }}>
            <form onSubmit={async (e) => {
              e.preventDefault();
              for (const field of leadFields) {
                if (!leadFormValues[field]?.trim()) {
                  alert(`${field.charAt(0).toUpperCase() + field.slice(1)} is required.`);
                  return;
                }
                if (field === "email") {
                  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
                  if (!emailRegex.test(leadFormValues[field])) {
                    alert("Please enter a valid email address.");
                    return;
                  }
                }
              }
              setSubmittingLead(true);
              try {
                const baseUrl = getApiBaseUrl();
                const finalSessionId = `session_lead_${Date.now()}`;
                const res = await fetch(`${baseUrl}/leads`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    agent_id: agentId || "YOUR_AGENT_ID",
                    tenant_id: tenantId || "YOUR_TENANT_ID",
                    session_id: finalSessionId,
                    ...leadFormValues,
                    source: "pre-chat"
                  })
                });
                if (res.ok) {
                  setLeadSubmitted(true);
                } else {
                  console.warn("Failed to create lead, proceeding to chat as fallback.");
                  setLeadSubmitted(true);
                }
              } catch (err) {
                console.warn("Lead form submission error:", err);
                setLeadSubmitted(true);
              } finally {
                setSubmittingLead(false);
              }
            }} style={{
              background: "#ffffff",
              padding: "24px",
              borderRadius: "20px",
              border: "1px solid #e4e4e7",
              boxShadow: "0 4px 12px rgba(0,0,0,0.03)",
              display: "flex",
              flexDirection: "column",
              gap: "16px"
            }}>
              <div style={{ textAlign: "center", marginBottom: "8px" }}>
                <div style={{
                  width: "48px",
                  height: "48px",
                  borderRadius: "14px",
                  background: `${themeColor}10`,
                  color: themeColor,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  margin: "0 auto 12px auto"
                }}>
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>
                </div>
                <h3 style={{ margin: "0 0 6px 0", fontSize: "16px", fontWeight: "700", color: "#18181b" }}>Before we start</h3>
                <p style={{ margin: 0, fontSize: "12px", color: "#71717a", lineHeight: "1.4" }}>
                  Please introduce yourself to start chatting with the agent.
                </p>
              </div>

              {leadFields.map((field) => {
                const label = field.charAt(0).toUpperCase() + field.slice(1);
                const isEmail = field.toLowerCase() === "email";
                const isPhone = field.toLowerCase() === "phone" || field.toLowerCase() === "mobile";

                return (
                  <div key={field} style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                    <label style={{ fontSize: "11px", fontWeight: "700", color: "#4b5563", textTransform: "uppercase", letterSpacing: "0.02em" }}>
                      {label} <span style={{ color: "#ef4444" }}>*</span>
                    </label>
                    <input
                      type={isEmail ? "email" : isPhone ? "tel" : "text"}
                      required
                      placeholder={`Enter your ${field}`}
                      value={leadFormValues[field] || ""}
                      onChange={(e) => setLeadFormValues((prev) => ({ ...prev, [field]: e.target.value }))}
                      style={{
                        padding: "10px 14px",
                        borderRadius: "10px",
                        border: "1px solid #d1d5db",
                        fontSize: "13px",
                        outline: "none",
                        transition: "border-color 0.2s",
                        fontFamily: CHAT_FONT_FAMILY
                      }}
                    />
                  </div>
                );
              })}

              <button
                type="submit"
                disabled={submittingLead}
                style={{
                  marginTop: "8px",
                  padding: "12px",
                  borderRadius: "12px",
                  border: "none",
                  background: themeColor,
                  color: "#ffffff",
                  fontWeight: "700",
                  fontSize: "13px",
                  cursor: submittingLead ? "not-allowed" : "pointer",
                  transition: "opacity 0.2s",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "8px"
                }}
              >
                {submittingLead ? (
                  <span style={{
                    width: "14px",
                    height: "14px",
                    border: "2px solid #ffffff",
                    borderTop: "2px solid transparent",
                    borderRadius: "50%",
                    animation: "spin 1s linear infinite",
                    display: "inline-block"
                  }} />
                ) : (
                  <span>Start Chatting</span>
                )}
              </button>
            </form>
          </div>
        ) : (
          <div
            style={{
              flex: 1,
              overflowY: "auto",
              padding: "20px",
              background: "#f9f9f9",
              display: "flex",
              flexDirection: "column",
              gap: "16px",
            }}
          >
            {messages.map((msg, index) => {
              const isUser = msg.role === "user";
              return (
                <div
                  key={index}
                  onMouseEnter={() => setHoveredIndex(index)}
                  onMouseLeave={() => setHoveredIndex(null)}
                  style={{
                    display: "flex",
                    gap: "8px",
                    alignItems: "flex-start",
                    flexDirection: isUser ? "row-reverse" : "row",
                    width: "100%",
                  }}
                >
                  {!isUser && resolvedBotAvatar !== "none" && (
                    <div style={{
                      width: "28px", height: "28px", borderRadius: "50%", background: themeColor,
                      display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden",
                      flexShrink: 0, marginTop: "16px"
                    }}>
                      {showInChat && customizationLogoUrl && (resolvedBotAvatar === "chat" || !resolvedBotAvatar) ? (
                        <img src={customizationLogoUrl} alt="Bot Avatar" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                      ) : (
                        renderBotAvatar(resolvedBotAvatar, themeColor)
                      )}
                    </div>
                  )}
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      alignItems: isUser ? "flex-end" : "flex-start",
                      width: "100%",
                    }}
                  >
                    <div style={{ fontSize: "11px", color: "#a3a3a3", marginBottom: "4px" }}>
                      {isUser ? "You" : agentLabel}
                    </div>

                    <div
                      style={{
                        padding: "12px 16px",
                        borderRadius: "18px",
                        background: isUser ? "#f4f4f5" : "#ffffff",
                        border: "1px solid #e4e4e7",
                        color: "#18181b",
                        fontSize: "14px",
                        lineHeight: "1.45",
                        maxWidth: "85%",
                        width: isUser ? "auto" : "100%",
                        boxSizing: "border-box",
                        wordBreak: "break-word",
                      }}
                    >
                      {!isUser && msg.content === "" && isTyping ? (
                        <div style={{ display: "flex", gap: "4px" }}>
                          <span className="typing-dot"></span>
                          <span className="typing-dot"></span>
                          <span className="typing-dot"></span>
                        </div>
                      ) : (
                        <>
                          {renderFormattedContent(msg.content, isUser, themeColor, linkSafety ? (url) => setSafetyModalUrl(url) : undefined)}

                          {!isUser && escalationEnabled && msg.escalation_detected && (
                            <div style={{ marginTop: "12px" }}>
                              <button
                                onClick={() => {
                                  if (escalationLink) {
                                    window.open(escalationLink, "_blank", "noopener,noreferrer");
                                  }
                                }}
                                style={{
                                  background: themeColor,
                                  color: "#ffffff",
                                  border: "none",
                                  borderRadius: "10px",
                                  padding: "8px 16px",
                                  fontSize: "12px",
                                  fontWeight: "700",
                                  cursor: "pointer",
                                  display: "flex",
                                  alignItems: "center",
                                  gap: "6px",
                                  transition: "opacity 0.2s",
                                  fontFamily: CHAT_FONT_FAMILY
                                }}
                                onMouseEnter={(e) => e.currentTarget.style.opacity = "0.9"}
                                onMouseLeave={(e) => e.currentTarget.style.opacity = "1"}
                              >
                                <span>🧑💼</span> Talk to Human Agent
                              </button>
                            </div>
                          )}
                        </>
                      )}
                    </div>

                    {/* Action Toolbar: Copy, Thumbs Up, Thumbs Down, Regenerate, Source (Far Right) */}
                    {!isUser && (!isTyping || index < messages.length - 1) && index !== 0 && (
                      <div style={{ marginTop: "6px", display: "flex", alignItems: "center", gap: "6px", width: "100%", maxWidth: "85%", flexWrap: "wrap" }}>
                        {/* 1. Copy Button */}
                        {displayCopy && (
                          <button
                            onClick={async () => {
                              try {
                                const plainText = convertToCleanPlainText(msg.content);
                                const htmlText = convertToCleanHtml(msg.content);

                                if (navigator.clipboard && window.ClipboardItem) {
                                  const blobPlain = new Blob([plainText], { type: "text/plain" });
                                  const blobHtml = htmlText ? new Blob([htmlText], { type: "text/html" }) : null;
                                  
                                  const clipboardData: Record<string, Blob> = { "text/plain": blobPlain };
                                  if (blobHtml) {
                                    clipboardData["text/html"] = blobHtml;
                                  }

                                  const data = new ClipboardItem(clipboardData);
                                  await navigator.clipboard.write([data]);
                                } else {
                                  const textArea = document.createElement("textarea");
                                  textArea.value = plainText;
                                  textArea.style.position = "fixed";
                                  document.body.appendChild(textArea);
                                  textArea.focus();
                                  textArea.select();
                                  document.execCommand("copy");
                                  document.body.removeChild(textArea);
                                }
                                setCopiedIndex(index);
                                setTimeout(() => setCopiedIndex(null), 2000);
                              } catch (err) {
                                console.warn("Copy failed:", err);
                              }
                            }}
                            style={{
                              background: "transparent",
                              border: "none",
                              cursor: "pointer",
                              color: copiedIndex === index ? themeColor : "#71717a",
                              padding: "4px",
                              display: "flex",
                              alignItems: "center",
                              borderRadius: "6px",
                              transition: "color 0.2s"
                            }}
                            title="Copy answer"
                          >
                            {copiedIndex === index ? (
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={themeColor} strokeWidth="2.5"><polyline points="20 6 9 17 4 12" /></svg>
                            ) : (
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
                            )}
                          </button>
                        )}

                        {/* 2. Thumbs Up & 3. Thumbs Down (Helpful / Not helpful) */}
                        {displayFeedback && (
                          <>
                            <button
                              onClick={() => handleFeedback(index, msg.id, "thumbs_up")}
                              style={{
                                background: feedbackMap[index] === "thumbs_up" ? `${themeColor}12` : "transparent",
                                border: "none",
                                cursor: "pointer",
                                color: feedbackMap[index] === "thumbs_up" ? themeColor : "#a1a1aa",
                                padding: "6px",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                borderRadius: "50%",
                                transition: "all 0.2s ease"
                              }}
                              title="Helpful"
                            >
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={feedbackMap[index] === "thumbs_up" ? "2.5" : "2"} strokeLinecap="round" strokeLinejoin="round"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3" /></svg>
                            </button>

                            <button
                              onClick={() => handleFeedback(index, msg.id, "thumbs_down")}
                              style={{
                                background: feedbackMap[index] === "thumbs_down" ? "#f43f5e12" : "transparent",
                                border: "none",
                                cursor: "pointer",
                                color: feedbackMap[index] === "thumbs_down" ? "#f43f5e" : "#a1a1aa",
                                padding: "6px",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                borderRadius: "50%",
                                transition: "all 0.2s ease"
                              }}
                              title="Not helpful"
                            >
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={feedbackMap[index] === "thumbs_down" ? "2.5" : "2"} strokeLinecap="round" strokeLinejoin="round"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3" /></svg>
                            </button>
                          </>
                        )}

                        <button
                          onClick={() => {
                            let userMessageIndex = -1;
                            for (let j = index; j >= 0; j--) {
                              if (messages[j].role === "user") {
                                userMessageIndex = j;
                                break;
                              }
                            }
                            if (userMessageIndex !== -1) {
                              const prevUserMsg = messages[userMessageIndex];
                              resetTypewriter();
                              bufferRef.current = "";
                              setIsTyping(true);
                              startTypingTimeout();
                              setMessages(messages.slice(0, userMessageIndex + 1));
                              
                              if (ws.current && ws.current.readyState === WebSocket.OPEN) {
                                ws.current.send(JSON.stringify({ message: prevUserMsg.content, query: prevUserMsg.content, embed: true, is_embed: true }));
                              } else if (ws.current && ws.current.readyState === WebSocket.CONNECTING) {
                                pendingQueryRef.current = prevUserMsg.content;
                              } else {
                                pendingQueryRef.current = prevUserMsg.content;
                                connectWs();
                              }
                            }
                          }}
                          style={{
                            background: "transparent",
                            border: "none",
                            cursor: "pointer",
                            color: "#71717a",
                            padding: "4px",
                            display: "flex",
                            alignItems: "center",
                            borderRadius: "6px",
                            transition: "color 0.2s"
                          }}
                          title="Regenerate response"
                        >
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" /></svg>
                        </button>

                        {/* 5. Source Link Button (Only when msg.sources has items) */}
                        {displaySources && msg.sources && msg.sources.length > 0 && !msg.content.includes("Something went wrong") && !msg.content.includes("trouble connecting") && (
                          <div style={{ position: "relative", display: "flex", alignItems: "center", marginLeft: "auto" }}>
                            {(() => {
                              const effectiveSources = deduplicateSources(msg.sources);
                              const hasMultiple = effectiveSources.length > 1;

                              return (
                                <>
                                  <button
                                    onClick={() => {
                                      if (hasMultiple) {
                                        setActiveSourceMenuIndex(activeSourceMenuIndex === index ? null : index);
                                      } else if (effectiveSources.length === 1) {
                                        handleOpenSource(effectiveSources[0], effectiveSources, 0);
                                      } else {
                                        handleOpenSource({}, [], 0);
                                      }
                                    }}
                                    style={{
                                      background: "transparent",
                                      border: "none",
                                      cursor: "pointer",
                                      fontSize: "12px",
                                      fontWeight: "700",
                                      display: "flex",
                                      alignItems: "center",
                                      gap: "4px",
                                      padding: "4px"
                                    }}
                                    title={hasMultiple ? `${effectiveSources.length} Sources available` : "View Source"}
                                  >
                                    <SiCrowdsource size={14} style={{ color: "#1e293b" }} />
                                    <span style={{ color: "#000000", fontWeight: "700" }}>
                                      {hasMultiple ? `Sources (${effectiveSources.length})` : "Source"}
                                    </span>
                                    {hasMultiple && (
                                      <span style={{ fontSize: "9px", color: "#64748b", marginLeft: "1px" }}>▼</span>
                                    )}
                                  </button>

                                  {/* Dropdown menu for multiple sources */}
                                  {activeSourceMenuIndex === index && hasMultiple && (
                                    <div
                                      style={{
                                        position: "absolute",
                                        bottom: "100%",
                                        left: 0,
                                        marginBottom: "8px",
                                        background: "rgba(255, 255, 255, 0.95)",
                                        backdropFilter: "blur(12px)",
                                        WebkitBackdropFilter: "blur(12px)",
                                        border: "1px solid rgba(226, 232, 240, 0.8)",
                                        borderRadius: "14px",
                                        boxShadow: "0 12px 30px rgba(0, 0, 0, 0.08), 0 4px 12px rgba(0, 0, 0, 0.03)",
                                        padding: "6px 0",
                                        zIndex: 999,
                                        minWidth: "180px",
                                        maxWidth: "260px",
                                        maxHeight: "180px",
                                        overflowY: "auto",
                                        animation: "lineFadeIn 0.2s ease-out"
                                      }}
                                    >
                                      <div style={{
                                        padding: "6px 12px",
                                        fontSize: "9px",
                                        fontWeight: "800",
                                        color: "#94a3b8",
                                        letterSpacing: "0.05em",
                                        textTransform: "uppercase",
                                        borderBottom: "1px solid #f1f5f9",
                                        marginBottom: "4px"
                                      }}>
                                        Cited Sources ({effectiveSources.length})
                                      </div>
                                      {effectiveSources.map((src, sIdx) => {
                                        const rawName = src.name || src.source || src.file_name || src.s3_path || `Source ${sIdx + 1}`;
                                        const cleanName = getCleanSourceName(rawName);

                                        return (
                                          <div
                                            key={sIdx}
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              setActiveSourceMenuIndex(null);
                                              handleOpenSource(src, effectiveSources, sIdx);
                                            }}
                                            style={{
                                              padding: "6px 12px",
                                              fontSize: "11px",
                                              color: "#334155",
                                              fontWeight: "600",
                                              cursor: "pointer",
                                              display: "flex",
                                              alignItems: "center",
                                              gap: "8px",
                                              borderRadius: "8px",
                                              margin: "2px 6px",
                                              transition: "all 0.15s ease-in-out"
                                            }}
                                            onMouseEnter={(e) => {
                                              e.currentTarget.style.background = "#eff6ff";
                                              e.currentTarget.style.color = "#3b82f6";
                                            }}
                                            onMouseLeave={(e) => {
                                              e.currentTarget.style.background = "transparent";
                                              e.currentTarget.style.color = "#334155";
                                            }}
                                          >
                                            <div style={{
                                              width: "22px",
                                              height: "22px",
                                              borderRadius: "5px",
                                              background: "#eff6ff",
                                              display: "flex",
                                              alignItems: "center",
                                              justifyContent: "center",
                                              flexShrink: 0
                                            }}>
                                              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /></svg>
                                            </div>
                                            <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{cleanName}</span>
                                          </div>
                                        );
                                      })}
                                    </div>
                                  )}
                                </>
                              );
                            })()}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {/* Typing Indicator (Only when waiting for first token) */}
            {isTyping && (!messages.length || messages[messages.length - 1].role === "user") && (
              <div style={{ display: "flex", gap: "8px", alignItems: "flex-start", width: "100%" }}>
                {resolvedBotAvatar !== "none" && (
                  <div style={{
                    width: "28px", height: "28px", borderRadius: "50%", background: themeColor,
                    display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden",
                    flexShrink: 0, marginTop: "16px"
                  }}>
                    {showInChat && customizationLogoUrl && (resolvedBotAvatar === "chat" || !resolvedBotAvatar) ? (
                      <img src={customizationLogoUrl} alt="Bot Avatar" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                    ) : (
                      renderBotAvatar(resolvedBotAvatar, themeColor)
                    )}
                  </div>
                )}
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
                  <div style={{ fontSize: "11px", color: "#a3a3a3", marginBottom: "4px" }}>{agentLabel} is {progressLabel.toLowerCase()}</div>
                  <div style={{ padding: "12px 16px", borderRadius: "18px", background: "#ffffff", border: "1px solid #e4e4e7", display: "flex", gap: "4px" }}>
                    <span className="typing-dot"></span>
                    <span className="typing-dot"></span>
                    <span className="typing-dot"></span>
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input Bar */}
      {(!leadCollection || leadTiming !== "pre-chat" || leadSubmitted) && (
        <div
          style={{
            padding: "2px",
            borderRadius: "24px",
            background: `linear-gradient(90deg, ${themeColor}, ${themeColor}ee, #ffffff, ${themeColor}ee, ${themeColor})`,
            backgroundSize: "300% 100%",
            animation: "borderShift 3s ease infinite",
            boxShadow: isTyping ? `0 4px 18px ${themeColor}40` : `0 2px 12px ${themeColor}30`,
            flexShrink: 0,
          }}
        >
          {/* Inner Input Wrapper */}
          <div
            style={{
              display: "flex",
              alignItems: "flex-end",
              background: "#ffffff",
              borderRadius: "22px",
              padding: "6px 8px 6px 16px",
              gap: "10px",
            }}
          >
            {/* Left Clock/History Icon */}
            <span style={{ display: "flex", alignItems: "center", color: "#71717a", cursor: "default", paddingBottom: "8px" }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" />
                <polyline points="12 6 12 12 16 14" />
              </svg>
            </span>

            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  if (!isTyping && input.trim()) handleSend();
                }
              }}
              placeholder="Ask a question..."
              disabled={isTyping}
              rows={1}
              style={{
                flex: 1,
                padding: "8px 0",
                background: "transparent",
                border: "none",
                color: isTyping ? "#71717a" : "#18181b",
                fontSize: "14px",
                outline: "none",
                cursor: isTyping ? "not-allowed" : "text",
                resize: "none",
                height: "22px",
                fontFamily: "inherit",
                lineHeight: "1.5",
              }}
            />

            <button
              onClick={handleSend}
              disabled={!input.trim() || isTyping}
              className="widget-send-btn"
              style={{
                background: (input.trim() && !isTyping) ? themeColor : "#e4e4e7",
                color: (input.trim() && !isTyping) ? "#ffffff" : "#a3a3a3",
                border: "none",
                borderRadius: "50%",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                cursor: (input.trim() && !isTyping) ? "pointer" : "default",
                transition: "background 0.2s, transform 0.1s active",
                padding: 0,
                marginBottom: "2px",
              }}
            >
              {isTyping ? (
                <span style={{
                  width: "12px",
                  height: "12px",
                  border: "2px solid #a3a3a3",
                  borderTop: "2px solid transparent",
                  borderRadius: "50%",
                  animation: "spin 1s linear infinite",
                  display: "inline-block"
                }} />
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="12" y1="19" x2="12" y2="5" />
                  <polyline points="5 12 12 5 19 12" />
                </svg>
              )}
            </button>
          </div>
        </div>
      )}

      {/* Powered by Gramosoft */}
      <a
        href="https://gsearchai.com/"
        target="_blank"
        rel="noopener noreferrer"
        style={{
          display: "block",
          textAlign: "center",
          marginTop: "6px",
          fontSize: "12px",
          color: "#001c49",
          fontWeight: 700,
          letterSpacing: "0.2px",
          userSelect: "none",
          textDecoration: "none",
          cursor: "pointer",
        }}
      >
        Powered by <span style={{ fontWeight: 700, color: "#001c49" }}>Gsearch</span>
      </a>
      {/* Link Safety Modal */}
      {safetyModalUrl && (
        <div style={{
          position: "absolute",
          inset: 0,
          background: "transparent",
          borderRadius: "24px",
          zIndex: 99999,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "20px"
        }}>
          <div style={{
            background: "#ffffff",
            borderRadius: "20px",
            padding: "20px",
            maxWidth: "300px",
            width: "100%",
            boxShadow: "0 10px 25px rgba(0,0,0,0.2)",
            display: "flex",
            flexDirection: "column",
            gap: "12px",
            textAlign: "center"
          }}>
            <div style={{ width: "40px", height: "40px", borderRadius: "50%", background: "#fef3c7", color: "#d97706", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto" }}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 1 1.71-3L13.71 3.86a2 2 0 0 1-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg>
            </div>
            <div style={{ fontWeight: "700", fontSize: "14px", color: "#18181b" }}>External Link Warning</div>
            <div style={{ fontSize: "11px", color: "#71717a", wordBreak: "break-all" }}>
              You are leaving this site to visit:<br />
              <strong style={{ color: themeColor }}>{safetyModalUrl}</strong>
            </div>
            <div style={{ display: "flex", gap: "8px", marginTop: "4px" }}>
              <button
                onClick={() => setSafetyModalUrl(null)}
                style={{ flex: 1, padding: "8px", borderRadius: "10px", border: "1px solid #e4e4e7", background: "#ffffff", color: "#71717a", fontWeight: "600", fontSize: "12px", cursor: "pointer" }}
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  window.open(safetyModalUrl, "_blank", "noopener,noreferrer");
                  setSafetyModalUrl(null);
                }}
                style={{ flex: 1, padding: "8px", borderRadius: "10px", border: "none", background: themeColor, color: "#ffffff", fontWeight: "600", fontSize: "12px", cursor: "pointer" }}
              >
                Proceed
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Thumbs Down Feedback Modal */}
      {feedbackModalOpen && (
        <div style={{
          position: "absolute",
          inset: 0,
          background: "transparent",
          borderRadius: "24px",
          zIndex: 99999,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "20px"
        }}>
          <div style={{
            background: "#ffffff",
            borderRadius: "20px",
            padding: "20px",
            maxWidth: "320px",
            width: "100%",
            boxShadow: "0 10px 25px rgba(0,0,0,0.2)",
            display: "flex",
            flexDirection: "column",
            gap: "12px",
            textAlign: "left"
          }}>
            <div style={{ fontWeight: "700", fontSize: "14px", color: "#18181b", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span>Provide Feedback</span>
              <button 
                onClick={() => { setFeedbackModalOpen(false); setFeedbackMessageId(null); }}
                style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", fontSize: "16px", color: "#a1a1aa", fontWeight: "bold", padding: 0 }}
              >
                ✕
              </button>
            </div>
            
            <div style={{ fontSize: "11px", color: "#71717a", fontWeight: "600", marginBottom: "4px" }}>
              Why did you find this answer not helpful?
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {[
                "Incorrect Answer",
                "Missing Information",
                "Irrelevant Answer",
                "Hallucination",
                "Other"
              ].map((reason) => {
                const isSelected = selectedReason === reason;
                return (
                  <div 
                    key={reason} 
                    onClick={() => setSelectedReason(reason)}
                    style={{ display: "flex", alignItems: "center", gap: "10px", fontSize: "12px", color: isSelected ? "#18181b" : "#4b5563", cursor: "pointer", fontWeight: isSelected ? "600" : "500", userSelect: "none" }}
                  >
                    <div style={{
                      width: "16px",
                      height: "16px",
                      borderRadius: "50%",
                      border: `2px solid ${isSelected ? themeColor : "#d1d5db"}`,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      transition: "all 0.2s ease",
                      background: "#ffffff",
                      boxSizing: "border-box"
                    }}>
                      {isSelected && (
                        <div style={{
                          width: "8px",
                          height: "8px",
                          borderRadius: "50%",
                          background: themeColor
                        }} />
                      )}
                    </div>
                    <span>{reason}</span>
                  </div>
                );
              })}
            </div>

            {selectedReason === "Other" && (
              <textarea
                placeholder="Please specify the reason..."
                value={customReason}
                onChange={(e) => setCustomReason(e.target.value)}
                rows={3}
                style={{
                  width: "100%",
                  padding: "8px",
                  borderRadius: "8px",
                  border: "1px solid #e4e4e7",
                  fontSize: "11px",
                  outline: "none",
                  resize: "none",
                  fontFamily: CHAT_FONT_FAMILY,
                  boxSizing: "border-box"
                }}
              />
            )}

            <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
              <button
                onClick={() => {
                  setFeedbackModalOpen(false);
                  setFeedbackMessageId(null);
                }}
                style={{ flex: 1, padding: "8px", borderRadius: "10px", border: "1px solid #e4e4e7", background: "#ffffff", color: "#71717a", fontWeight: "600", fontSize: "12px", cursor: "pointer" }}
              >
                Cancel
              </button>
              <button
                onClick={submitThumbsDownFeedback}
                style={{ flex: 1, padding: "8px", borderRadius: "10px", border: "none", background: themeColor, color: "#ffffff", fontWeight: "600", fontSize: "12px", cursor: "pointer" }}
              >
                Submit
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Source Document Preview Modal */}
      {activeSourceModal && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: "transparent",
            borderRadius: "24px",
            zIndex: 99999,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "16px"
          }}
          onClick={closeSourceModal}
        >
          <div
            style={{
              background: "#ffffff",
              borderRadius: "20px",
              padding: "18px",
              maxWidth: "340px",
              width: "100%",
              maxHeight: "85%",
              boxShadow: "0 10px 25px rgba(0,0,0,0.2)",
              display: "flex",
              flexDirection: "column",
              gap: "12px"
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div style={{ borderBottom: "1px solid #f1f5f9", paddingBottom: "10px" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", overflow: "hidden" }}>
                  <div style={{ width: "28px", height: "28px", borderRadius: "8px", background: "#f0f9ff", color: "#0066cc", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                    <SiCrowdsource size={16} />
                  </div>
                  <span style={{ fontWeight: "700", fontSize: "13px", color: "#0f172a", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {(activeSourceModal.name || activeSourceModal.source || activeSourceModal.file_name || "Source Document").replace(/^(pdf|doc|docx|csv|xlsx|image|img|txt):\s*/i, "").trim()}
                  </span>
                </div>
                <button
                  onClick={closeSourceModal}
                  style={{ background: "transparent", border: "none", cursor: "pointer", color: "#94a3b8", fontSize: "16px", padding: "4px", lineHeight: 1 }}
                >
                  ✕
                </button>
              </div>

              {/* Source Document Tabs when multiple sources exist */}
              {activeSourceList.length > 1 && (
                <div style={{ display: "flex", gap: "6px", overflowX: "auto", paddingTop: "8px" }}>
                  {activeSourceList.map((item, idx) => {
                    const cleanName = (item.name || item.source || item.file_name || `Doc ${idx + 1}`)
                      .replace(/^(pdf|doc|docx|csv|xlsx|image|img|txt):\s*/i, "")
                      .replace(/^.*[/\\]/, "")
                      .trim();
                    const isActive = activeSourceIndex === idx;
                    return (
                      <button
                        key={idx}
                        onClick={() => handleOpenSource(item, activeSourceList, idx)}
                        style={{
                          padding: "4px 10px",
                          borderRadius: "8px",
                          border: isActive ? "1px solid #0066cc" : "1px solid #e2e8f0",
                          background: isActive ? "#f0f9ff" : "#f8fafc",
                          color: isActive ? "#0066cc" : "#64748b",
                          fontWeight: isActive ? "700" : "500",
                          fontSize: "11px",
                          cursor: "pointer",
                          whiteSpace: "nowrap",
                          transition: "all 0.2s"
                        }}
                      >
                        📄 {cleanName}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Body: PDF / Image / Excel / CSV / Text Viewer */}
            <div style={{ flex: 1, minHeight: "180px", maxHeight: "280px", overflow: "hidden", display: "flex", flexDirection: "column" }}>
              {sourceModalLoading ? (
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "180px", background: "#f8fafc", borderRadius: "12px", border: "1px solid #e2e8f0", gap: "8px", color: "#64748b", fontSize: "12px" }}>
                  <div style={{ width: "20px", height: "20px", border: "2px solid #0066cc", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
                  <span>Loading document preview...</span>
                </div>
              ) : sourceModalPreviewType === "pdf" && sourceModalPreviewUrl ? (
                <iframe
                  src={allowDownloads ? `${sourceModalPreviewUrl}#navpanes=0` : `${sourceModalPreviewUrl}#toolbar=0&navpanes=0&scrollbar=0`}
                  style={{ width: "100%", height: "260px", border: "none", borderRadius: "12px", background: "#f8fafc" }}
                  title="PDF Preview"
                />
              ) : sourceModalPreviewType === "image" && sourceModalPreviewUrl ? (
                <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "240px", overflow: "hidden", borderRadius: "12px", background: "#f8fafc", border: "1px solid #e2e8f0", padding: "8px" }}>
                  <img src={sourceModalPreviewUrl} alt="Source Preview" style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain", borderRadius: "6px" }} />
                </div>
              ) : (sourceModalPreviewType === "excel" || sourceModalPreviewType === "csv") && sourceModalCsvRows.length > 0 ? (
                <div style={{ overflow: "auto", maxHeight: "240px", border: "1px solid #e2e8f0", borderRadius: "12px", background: "#ffffff" }}>
                  <table style={{ borderCollapse: "collapse", width: "100%", fontSize: "11px", whiteSpace: "nowrap" }}>
                    <thead>
                      <tr style={{ background: "#f1f5f9" }}>
                        {sourceModalCsvRows[0]?.map((col, cIdx) => (
                          <th key={cIdx} style={{ border: "1px solid #e2e8f0", padding: "6px 10px", textAlign: "left", fontWeight: "700", color: "#334155" }}>{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {sourceModalCsvRows.slice(1, 100).map((row, rIdx) => (
                        <tr key={rIdx} style={{ background: rIdx % 2 === 0 ? "#ffffff" : "#f8fafc" }}>
                          {row.map((cell, cIdx) => (
                            <td key={cIdx} style={{ border: "1px solid #e2e8f0", padding: "4px 8px", color: "#475569" }}>{cell}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div
                  style={{
                    flex: 1,
                    overflowY: "auto",
                    background: "#f8fafc",
                    borderRadius: "12px",
                    padding: "12px",
                    border: "1px solid #e2e8f0",
                    fontSize: "12px",
                    color: "#334155",
                    lineHeight: "1.5",
                    whiteSpace: "pre-wrap",
                    maxHeight: "240px"
                  }}
                >
                  {activeSourceModal.text || activeSourceModal.content || activeSourceModal.page_content || activeSourceModal.snippet || "Cited knowledge base reference used to generate the answer."}
                </div>
              )}

            </div>

            {/* Footer: View (New Tab), Download, Close */}
            <div style={{ display: "flex", gap: "6px", marginTop: "4px" }}>
              <button
                onClick={closeSourceModal}
                style={{
                  padding: "8px 10px",
                  borderRadius: "10px",
                  border: "1px solid #e2e8f0",
                  background: "#ffffff",
                  color: "#64748b",
                  fontWeight: "600",
                  fontSize: "12px",
                  cursor: "pointer"
                }}
              >
                Close
              </button>

              <button
                onClick={() => {
                  const kbId = activeSourceModal?.kb_id || activeSourceModal?.id;
                  const baseUrl = getApiBaseUrl();
                  const rawPath = activeSourceModal?.s3_path || activeSourceModal?.file_path || "";
                  const s3Key = getS3Key(rawPath);
                  const suffix = allowDownloads ? "#navpanes=0" : "#toolbar=0&navpanes=0";

                  let targetUrl = "";
                  if (kbId) {
                    targetUrl = `${baseUrl}/embed/files/${kbId}/preview${suffix}`;
                  } else if (activeSourceModal?.url) {
                    targetUrl = `${getFullUrl(activeSourceModal.url)}${suffix}`;
                  } else if (s3Key) {
                    targetUrl = `${baseUrl}/embed/files/preview?key=${encodeURIComponent(s3Key)}${suffix}`;
                  } else if (sourceModalPreviewUrl) {
                    targetUrl = `${sourceModalPreviewUrl}${suffix}`;
                  }

                  if (targetUrl) {
                    window.open(targetUrl, "_blank", "noopener,noreferrer");
                  }
                }}
                style={{
                  flex: 1,
                  padding: "8px 10px",
                  borderRadius: "10px",
                  border: "1px solid #cbd5e1",
                  background: "#ffffff",
                  color: "#0f172a",
                  fontWeight: "600",
                  fontSize: "12px",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "4px"
                }}
                title="Open file in new tab"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" /></svg>
                View
              </button>

              {allowDownloads ? (
                <button
                  onClick={() => downloadSourceFile(activeSourceModal)}
                  style={{
                    flex: 1,
                    padding: "8px 10px",
                    borderRadius: "10px",
                    border: "none",
                    background: themeColor || "#0066cc",
                    color: "#ffffff",
                    fontWeight: "600",
                    fontSize: "12px",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "4px"
                  }}
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
                  Download
                </button>
              ) : (
                <div
                  title="Source downloads restricted by site admin"
                  style={{
                    flex: 1.1,
                    padding: "8px 4px",
                    borderRadius: "10px",
                    border: "1px dashed #cbd5e1",
                    background: "#f1f5f9",
                    color: "#64748b",
                    fontWeight: "600",
                    fontSize: "10px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "3px",
                    cursor: "not-allowed"
                  }}
                >
                  🔒 Download
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function WidgetPage() {
  return (
    <Suspense fallback={
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", background: "transparent" }}>
        <div style={{ width: "24px", height: "24px", border: "2px solid #0fb5a1", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
      </div>
    }>
      <WidgetContent />
    </Suspense>
  );
}

