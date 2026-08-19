"use client";

import { useEffect, useState, useMemo, useRef } from "react";
import { Typography, Button, Badge, Row, Col, Spin, Table, Input, Space, Card, Modal, Tag, Tooltip, Progress, Popover } from "antd";
import { ReloadOutlined, SearchOutlined, EyeOutlined, DatabaseOutlined, LinkOutlined } from "@ant-design/icons";
import { ThumbsUp, ThumbsDown, BarChart3, HelpCircle, CheckCircle, AlertTriangle, XOctagon, Clock, User, Bot, FileText, ExternalLink, Sparkles, AlertCircle } from "lucide-react";
import useAxios from "@/app/hooks/useAxios";
import { API_BASE_URL, AUTH_COOKIE_KEY } from "@/app/config/config";
import { getCookie } from "@/app/config/cookies";

const { Title, Text, Paragraph } = Typography;


const getCleanCitationName = (citation: string): string => {
  if (!citation) return "Unknown Source";

  if (citation.startsWith("http://") || citation.startsWith("https://")) {
    try {
      const decoded = decodeURIComponent(citation);
      const parts = decoded.split("/");
      return parts[parts.length - 1] || citation;
    } catch (e) {
      const parts = citation.split("/");
      return parts[parts.length - 1] || citation;
    }
  }

  const prefixMatch = citation.match(/^[a-zA-Z0-9\s]+:\s*(.*)$/);
  if (prefixMatch && prefixMatch[1]) {
    return prefixMatch[1].trim();
  }

  return citation;
};

const getCitationUrl = (citation: string, allCitations: string[]): string | null => {
  if (!citation) return null;
  if (citation.startsWith("http://") || citation.startsWith("https://")) {
    return citation;
  }

  const cleanName = getCleanCitationName(citation).toLowerCase();
  const matchingUrl = allCitations.find(c => {
    if (c.startsWith("http://") || c.startsWith("https://")) {
      const nameInUrl = getCleanCitationName(c).toLowerCase();
      return nameInUrl === cleanName || nameInUrl.includes(cleanName) || cleanName.includes(nameInUrl);
    }
    return false;
  });

  return matchingUrl || null;
};

interface CitationInfo {
  name: string;      
  rawSource: string;
  kbId?: string;     
}

const getRecordCitations = (record: any): CitationInfo[] => {
  const list: CitationInfo[] = [];
  const addedNames = new Set<string>();

  
  const addCitation = (rawSource: string, kbId?: string) => {
    if (!rawSource || typeof rawSource !== 'string') return;
    const cleanName = getCleanCitationName(rawSource);

   
    if (addedNames.has(cleanName.toLowerCase())) {
      const existing = list.find(c => c.name.toLowerCase() === cleanName.toLowerCase());
      if (existing && !existing.kbId && kbId) {
        existing.kbId = kbId;
      }
      return;
    }

    addedNames.add(cleanName.toLowerCase());
    list.push({
      name: cleanName,
      rawSource: rawSource.trim(),
      kbId: kbId || undefined
    });
  };

  
  const chunkMap = new Map<string, string>(); 
  if (Array.isArray(record.view?.retrieved_chunks)) {
    record.view.retrieved_chunks.forEach((chunk: any) => {
      if (chunk && chunk.kb_id && chunk.source) {
        const name = getCleanCitationName(chunk.source).toLowerCase();
        chunkMap.set(name, chunk.kb_id);
      }
    });
  }

  if (Array.isArray(record.citations)) {
    record.citations.forEach((c: any) => {
      if (typeof c === 'string') {
        const clean = getCleanCitationName(c).toLowerCase();
        addCitation(c, chunkMap.get(clean));
      }
    });
  }

  if (Array.isArray(record.view?.citations)) {
    record.view.citations.forEach((c: any) => {
      if (typeof c === 'string') {
        const clean = getCleanCitationName(c).toLowerCase();
        addCitation(c, chunkMap.get(clean));
      }
    });
  }

  if (Array.isArray(record.view?.retrieved_chunks)) {
    record.view.retrieved_chunks.forEach((chunk: any) => {
      if (chunk && chunk.source) {
        const clean = getCleanCitationName(chunk.source).toLowerCase();
        addCitation(chunk.source, chunk.kb_id);
      }
    });
  }

  return list;
};

const getIconForFile = (filename: string) => {
  const lower = filename.toLowerCase();
  if (lower.endsWith(".xlsx") || lower.endsWith(".xls") || lower.endsWith(".csv")) {
    return <span className="text-emerald-600 font-bold text-sm">📊</span>;
  }
  if (lower.endsWith(".pdf")) {
    return <span className="text-rose-600 font-bold text-sm">📄</span>;
  }
  return <span className="text-blue-600 font-bold text-sm">📝</span>;
};


interface AnimatedCounterProps {
  value: number;
  duration?: number;
  decimals?: number;
  prefix?: string;
  suffix?: string;
}

function AnimatedCounter({
  value,
  duration = 1000,
  decimals = 0,
  prefix = "",
  suffix = "",
}: AnimatedCounterProps) {
  const [count, setCount] = useState(0);
  const [isInView, setIsInView] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const currentRef = ref.current;
    if (!currentRef) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsInView(true);
          observer.unobserve(currentRef);
        }
      },
      { threshold: 0.05 }
    );

    observer.observe(currentRef);

    return () => {
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    if (!isInView) return;

    let startTimestamp: number | null = null;

    const step = (timestamp: number) => {
      if (!startTimestamp) startTimestamp = timestamp;
      const progress = timestamp - startTimestamp;
      const progressPercent = Math.min(progress / duration, 1);

      const currentVal = progressPercent * value;
      setCount(currentVal);

      if (progress < duration) {
        window.requestAnimationFrame(step);
      } else {
        setCount(value);
      }
    };

    const animFrame = window.requestAnimationFrame(step);
    return () => window.cancelAnimationFrame(animFrame);
  }, [value, duration, isInView]);

  return (
    <span ref={ref}>
      {prefix}
      {count.toFixed(decimals)}
      {suffix}
    </span>
  );
}



export default function AdminFeedbackPage() {
  const [getFeedback, rawFeedbackData, loadingFeedback] = useAxios({
    endpoint: "FEEDBACK_MESSAGES",
    initialLoading: true,
  });

  const [refreshKey, setRefreshKey] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");

  const [detailModalOpen, setDetailModalOpen] = useState(false);
  const [selectedRecordForDetail, setSelectedRecordForDetail] = useState<any>(null);

  const [chunksModalOpen, setChunksModalOpen] = useState(false);
  const [selectedRecordForChunks, setSelectedRecordForChunks] = useState<any>(null);

  const handleCitationClick = async (citation: any, allCitations: any[]) => {
   
    let kbId = citation.kbId;
    const cleanName = getCleanCitationName(citation.rawSource);

    if (!kbId && selectedRecordForDetail?.view?.retrieved_chunks) {
      const match = selectedRecordForDetail.view.retrieved_chunks.find((chunk: any) => {
        if (chunk.kb_id && chunk.source) {
          return getCleanCitationName(chunk.source).toLowerCase() === cleanName.toLowerCase();
        }
        return false;
      });
      if (match) kbId = match.kb_id;
    }

    const targetUrl = getCitationUrl(citation.rawSource, allCitations.map(c => c.rawSource));

    if (kbId) {
      const newWindow = window.open("", "_blank");
      if (!newWindow) {
        Modal.error({
          title: "Popup Blocked",
          content: "Please allow popups for this site to view the preview.",
        });
        return;
      }
      newWindow.document.write(
        `<p style="font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 24px; color: #4b5563;">Loading preview...</p>`
      );
      newWindow.document.title = cleanName || "Source Preview";

      try {
        const token = getCookie(AUTH_COOKIE_KEY);
        const response = await fetch(`${API_BASE_URL}/files/${kbId}/preview`, {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });

        if (!response.ok) {
          throw new Error("File preview failed");
        }

        const blob = await response.blob();
        const contentType = blob.type.toLowerCase();
        const nameLower = cleanName.toLowerCase();

        const isPdf = contentType.includes("pdf") || nameLower.endsWith(".pdf");
        const isImage =
          contentType.includes("image/") ||
          nameLower.endsWith(".png") ||
          nameLower.endsWith(".jpg") ||
          nameLower.endsWith(".jpeg") ||
          nameLower.endsWith(".webp") ||
          nameLower.endsWith(".gif");
        const isTxt = contentType.includes("text/plain") || nameLower.endsWith(".txt");
        const isCSV = contentType.includes("csv") || nameLower.endsWith(".csv");
        const isExcel =
          contentType.includes("excel") ||
          contentType.includes("spreadsheet") ||
          contentType.includes("vnd.ms-excel") ||
          contentType.includes("vnd.openxmlformats-officedocument.spreadsheetml.sheet") ||
          nameLower.endsWith(".xls") ||
          nameLower.endsWith(".xlsx");

        if (isPdf || isImage || isTxt) {
          const viewBlobUrl = URL.createObjectURL(blob);
          newWindow.location.href = viewBlobUrl;
        } else if (isCSV || isExcel) {
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

          newWindow.document.open();
          newWindow.document.write(`
            <!DOCTYPE html>
            <html>
            <head>
              <meta charset="utf-8">
              <title>${cleanName || "Spreadsheet Preview"}</title>
              <style>
                body {
                  margin: 0;
                  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                  background: #f9fafb;
                  color: #374151;
                  display: flex;
                  flex-direction: column;
                  height: 100vh;
                  overflow: hidden;
                }
                .header {
                  background: white;
                  border-bottom: 1px solid #e5e7eb;
                  padding: 12px 24px;
                  display: flex;
                  align-items: center;
                  justify-content: space-between;
                  flex-shrink: 0;
                }
                .title-container {
                  display: flex;
                  align-items: center;
                  gap: 8px;
                }
                .title {
                  font-weight: 700;
                  font-size: 16px;
                  color: #111827;
                }
                .tabs {
                  display: flex;
                  gap: 8px;
                  background: #f3f4f6;
                  padding: 4px;
                  border-radius: 8px;
                }
                .tab {
                  padding: 6px 12px;
                  border-radius: 6px;
                  font-size: 12px;
                  font-weight: 600;
                  cursor: pointer;
                  border: none;
                  background: transparent;
                  color: #4b5563;
                  transition: all 0.2s;
                }
                .tab.active {
                  background: white;
                  color: #0fb5a1;
                  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                }
                .content {
                  flex-grow: 1;
                  overflow: auto;
                  position: relative;
                }
                .sheet-content {
                  display: none;
                  padding: 16px;
                }
                .sheet-content.active {
                  display: block;
                }
                table {
                  border-collapse: collapse;
                  background: white;
                  font-size: 13px;
                  min-width: 100%;
                  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
                  border-radius: 8px;
                  overflow: hidden;
                }
                th, td {
                  border: 1px solid #e5e7eb;
                  padding: 10px 14px;
                  text-align: left;
                }
                th {
                  background: #f9fafb;
                  font-weight: 700;
                  color: #374151;
                  position: sticky;
                  top: 0;
                  z-index: 10;
                }
                tr:hover td {
                  background: #f9fafb;
                }
              </style>
            </head>
            <body>
              <div class="header">
                <div class="title-container">
                  <span style="font-size: 20px;">📊</span>
                  <span class="title">${cleanName}</span>
                </div>
                <div class="tabs">
                  ${sheetNames
              .map(
                (name, idx) => `
                    <button class="tab ${idx === 0 ? "active" : ""
                  }" onclick="switchSheet('${name}', this)">
                      ${name}
                    </button>
                  `
              )
              .join("")}
                </div>
              </div>
              <div class="content">
                ${sheetNames
              .map((name, idx) => {
                const rows = sheetsData[name] || [];
                const hasData = rows.length > 0;
                return `
                    <div id="sheet-${name}" class="sheet-content ${idx === 0 ? "active" : ""}">
                      ${hasData
                    ? `
                        <table>
                          <thead>
                            <tr>
                              ${rows[0].map((cell) => `<th>${cell || ""}</th>`).join("")}
                            </tr>
                          </thead>
                          <tbody>
                            ${rows
                      .slice(1)
                      .map(
                        (row) => `
                              <tr>
                                ${row.map((cell) => `<td>${cell || ""}</td>`).join("")}
                              </tr>
                            `
                      )
                      .join("")}
                          </tbody>
                        </table>
                      `
                    : `<p style="padding: 24px; text-align: center; color: #9ca3af;">No data in this sheet</p>`
                  }
                    </div>
                  `;
              })
              .join("")}
              </div>
              <script>
                function switchSheet(name, btn) {
                  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                  btn.classList.add('active');
                  document.querySelectorAll('.sheet-content').forEach(c => c.classList.remove('active'));
                  document.getElementById('sheet-' + name).classList.add('active');
                }
              </script>
            </body>
            </html>
          `);
          newWindow.document.close();
        } else {
          const viewBlobUrl = URL.createObjectURL(blob);
          newWindow.location.href = viewBlobUrl;
        }
      } catch (err) {
        console.error("Preview load failed:", err);
        newWindow.document.open();
        newWindow.document.write(
          `<p style="font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 24px; color: #ef4444;">Failed to load file preview. Opening source link instead...</p>`
        );
        newWindow.document.close();
        if (targetUrl) {
          newWindow.location.href = targetUrl;
        } else {
          setTimeout(() => newWindow.close(), 3000);
        }
      }
    } else if (targetUrl) {
      window.open(targetUrl, "_blank", "noopener,noreferrer");
    } else {
      Modal.error({
        title: "Preview Unavailable",
        content: "This source cannot be opened directly because it is not indexed with a preview ID.",
      });
    }
  };

  useEffect(() => {
    getFeedback();
  }, [refreshKey]);

  const feedbackPayload = useMemo(() => {
    if (rawFeedbackData && rawFeedbackData.success && Array.isArray(rawFeedbackData.data) && rawFeedbackData.data.length > 0) {
      return rawFeedbackData;
    }
    return null;
  }, [rawFeedbackData]);

  const items = useMemo(() => feedbackPayload.data || [], [feedbackPayload]);

  const filteredItems = useMemo(() => {
    if (!searchQuery) return items;
    const query = searchQuery.toLowerCase();
    return items.filter((item: any) => {
      const fullName = `${item.user?.first_name || ""} ${item.user?.last_name || ""}`.toLowerCase();
      const email = (item.user?.email || "").toLowerCase();
      const agentName = (item.agent?.name || "").toLowerCase();
      const reason = (item.feedback_reason || "").toLowerCase();
      const feedbackType = (item.feedback_type || "").toLowerCase();
      const question = (item.question || "").toLowerCase();

      return (
        fullName.includes(query) ||
        email.includes(query) ||
        agentName.includes(query) ||
        reason.includes(query) ||
        feedbackType.includes(query) ||
        question.includes(query)
      );
    });
  }, [items, searchQuery]);

  const handleRefresh = () => {
    setRefreshKey((prev) => prev + 1);
  };

  const handleOpenDetails = (record: any) => {
    setSelectedRecordForDetail(record);
    setDetailModalOpen(true);
  };

  const handleOpenChunks = (record: any) => {
    setSelectedRecordForChunks(record);
    setChunksModalOpen(true);
  };

  const formatTime = (timeStr: string) => {
    if (!timeStr) return "N/A";
    try {
      const date = new Date(timeStr);
      return date.toLocaleDateString("en-US", {
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hour12: true
      });
    } catch (e) {
      return timeStr;
    }
  };

  const totalFeedbackCount = useMemo(() => {
    return feedbackPayload.meta?.total_feedback_count ?? items.length;
  }, [feedbackPayload, items]);

  const thumbsUpItems = useMemo(() => {
    return items.filter((item: any) => item.feedback_type === "thumbs_up");
  }, [items]);

  const thumbsDownItems = useMemo(() => {
    return items.filter((item: any) => item.feedback_type === "thumbs_down");
  }, [items]);

  const totalThumbsUpCount = useMemo(() => {
    return thumbsUpItems.length;
  }, [thumbsUpItems]);

  const totalThumbsDownCount = useMemo(() => {
    return thumbsDownItems.length;
  }, [thumbsDownItems]);

  const thumbsUpOverallPercentage = useMemo(() => {
    return totalFeedbackCount > 0 ? (totalThumbsUpCount / totalFeedbackCount) * 100 : 0;
  }, [totalThumbsUpCount, totalFeedbackCount]);

  const thumbsDownOverallPercentage = useMemo(() => {
    return totalFeedbackCount > 0 ? (totalThumbsDownCount / totalFeedbackCount) * 100 : 0;
  }, [totalThumbsDownCount, totalFeedbackCount]);

  const columns = [
    {
      title: "S.No",
      key: "sno",
      width: 70,
      render: (_: any, __: any, index: number) => (
        <span className="font-bold text-[var(--app-text-soft)]">{index + 1}</span>
      ),
    },
    {
      title: "User Details",
      key: "user",
      render: (record: any) => {
        const fullName = `${record.user?.first_name || ""} ${record.user?.last_name || ""}`.trim();
        return (
          <div className="flex flex-col">
            <span className="font-bold text-[var(--app-text)]">{fullName || "N/A"}</span>
            <span className="text-xs text-[var(--app-text-soft)]">{record.user?.email || "N/A"}</span>
          </div>
        );
      },
    },
    {
      title: "Agent",
      key: "agent",
      dataIndex: ["agent", "name"],
      render: (agentName: string) => (
        <span className="px-2.5 py-1 rounded-full text-xs font-black uppercase tracking-wider bg-[var(--app-active-bg)] text-[#0fb5a1]">
          {agentName || "N/A"}
        </span>
      ),
    },
    {
      title: "Feedback Type",
      dataIndex: "feedback_type",
      key: "feedback_type",
      width: 140,
      render: (type: string) => {
        const isUp = type === "thumbs_up";
        return (
          <Tag
            color={isUp ? "success" : "processing"}
            className={`font-extrabold uppercase text-[10px] tracking-wider rounded-lg px-2 py-0.5 border-none flex items-center gap-1.5 w-fit ${isUp
                ? "bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 dark:text-emerald-400"
                : "bg-violet-50 dark:bg-violet-950/20 text-violet-600 dark:text-violet-400"
              }`}
          >
            {isUp ? <ThumbsUp size={10} /> : <ThumbsDown size={10} />}
            {isUp ? "Thumbs Up" : "Thumbs Down"}
          </Tag>
        );
      },
    },
    {
      title: "Feedback Reason",
      dataIndex: "feedback_reason",
      key: "feedback_reason",
      render: (reason: string) => (
        <span className="text-[var(--app-text)] font-semibold">{reason || "N/A"}</span>
      ),
    },
    {
      title: "Submitted Time",
      dataIndex: "time",
      key: "time",
      render: (time: string) => (
        <div className="flex items-center gap-1.5 text-xs text-[var(--app-text-soft)] font-medium">
          <Clock size={13} className="opacity-60" />
          <span>{formatTime(time)}</span>
        </div>
      ),
    },
    {
      title: "Actions",
      key: "actions",
      width: 120,
      render: (record: any) => {
        return (
          <Space size="middle">
            <Tooltip title="View Message Details">
              <Button
                type="text"
                icon={<EyeOutlined className="text-[#0fb5a1] text-lg" />}
                onClick={() => handleOpenDetails(record)}
                className="hover:bg-[#0fb5a1]/10 rounded-xl flex items-center justify-center p-2 h-10 w-10 transition-colors"
              />
            </Tooltip>

            <Tooltip title="View Chunks">
              <Button
                type="text"
                icon={<DatabaseOutlined className="text-[#0fb5a1] text-lg" />}
                onClick={() => handleOpenChunks(record)}
                className="hover:bg-[#0fb5a1]/10 rounded-xl flex items-center justify-center p-2 h-10 w-10 transition-colors"
              />
            </Tooltip>
          </Space>
        );
      },
    },
  ];

  const chunkColumns = [
    {
      title: "S.No",
      key: "chunk_sno",
      width: 60,
      render: (_: any, __: any, index: number) => (
        <span className="font-bold text-[var(--app-text-soft)]">{index + 1}</span>
      ),
    },
    {
      title: "Source Document",
      dataIndex: "source",
      key: "source",
      render: (source: string) => {
        if (!source) return "N/A";
        const isUrl = source.startsWith("http://") || source.startsWith("https://");

        return (
          <div className="flex items-center gap-2 max-w-[280px]">
            <FileText size={16} className="text-[#0fb5a1] flex-shrink-0" />
            {isUrl ? (
              <a
                href={source}
                target="_blank"
                rel="noreferrer"
                className="text-[#0fb5a1] hover:underline font-semibold flex items-center gap-1 truncate text-xs"
              >
                <span>Link source</span>
                <ExternalLink size={12} />
              </a>
            ) : (
              <span className="font-semibold text-xs text-[var(--app-text)] truncate" title={source}>
                {source}
              </span>
            )}
          </div>
        );
      },
    },
    {
      title: "Match Score",
      dataIndex: "score",
      key: "score",
      width: 90,
      render: (score: number) => {
        const color = score > 1.2 ? "emerald" : score > 0.6 ? "amber" : "gray";
        return (
          <span
            className={`px-2 py-0.5 rounded-md text-xs font-black leading-none ${color === "emerald"
                ? "bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 dark:text-emerald-400"
                : color === "amber"
                  ? "bg-amber-50 dark:bg-amber-950/20 text-amber-600 dark:text-amber-400"
                  : "bg-gray-50 dark:bg-gray-900/20 text-gray-500"
              }`}
          >
            {score !== undefined ? score.toFixed(2) : "0.00"}
          </span>
        );
      },
    },
    {
      title: "Pos",
      dataIndex: "position",
      key: "position",
      width: 60,
      render: (pos: number) => (
        <span className="font-extrabold text-[var(--app-text)] text-xs bg-[var(--app-surface-muted)] px-1.5 py-0.5 rounded-md border border-[var(--app-border)]/40">{pos ?? 0}</span>
      ),
    },
    {
      title: "Reason",
      dataIndex: "reason",
      key: "reason",
      render: (reason: string) => (
        <span className="text-xs font-medium text-[var(--app-text-soft)]">{reason || "N/A"}</span>
      ),
    },
    {
      title: "KB ID",
      dataIndex: "kb_id",
      key: "kb_id",
      render: (kbId: string) => (
        <Tooltip title={kbId}>
          <span className="font-mono text-[10px] text-gray-400 block max-w-[120px] truncate">
            {kbId || "N/A"}
          </span>
        </Tooltip>
      ),
    },
    {
      title: "Format",
      dataIndex: "content_type",
      key: "content_type",
      width: 110,
      render: (contentType: string) => (
        <Tag color="cyan" className="font-bold text-[10px] uppercase border-none bg-cyan-50 dark:bg-cyan-950/20 text-cyan-600 dark:text-cyan-400 px-1.5 py-0.5 rounded-md">
          {contentType || "text"}
        </Tag>
      ),
    },
  ];

  return (
    <div className="w-full max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8 pb-24 relative min-h-screen">
      <div className="mb-10">
        <Row justify="space-between" align="middle" gutter={[16, 24]}>
          <Col xs={24} md={18}>
            <div className="flex items-center gap-4">
              <Title level={1} className="!m-0 !font-extrabold !text-3xl sm:!text-4xl tracking-tight text-[var(--app-text)]">
                Feedback Logs
              </Title>
              <Badge
                count={`${filteredItems.length} messages`}
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
              Review chat responses flagged with thumbs-up or thumbs-down feedback by users.
            </Text>
          </Col>
          <Col xs={24} md={6} className="text-right">
            <Button
              type="primary"
              size="large"
              icon={<ReloadOutlined />}
              onClick={handleRefresh}
              loading={loadingFeedback}
              className="!h-12 !px-6 !rounded-2xl !bg-[#0fb5a1] !border-none !font-black !text-sm !uppercase !tracking-widest !shadow-lg hover:!scale-[1.02] transition-all"
            >
              Refresh
            </Button>
          </Col>
        </Row>
      </div>

      {loadingFeedback ? (
        <div className="min-h-[40vh] flex items-center justify-center">
          <Spin size="large" />
        </div>
      ) : (
        <div className="space-y-12">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="bg-[var(--app-surface)] border border-[var(--app-border)]/60 rounded-3xl p-6 relative overflow-hidden shadow-sm hover:shadow-md transition-all duration-300 flex flex-col justify-between min-h-[140px] group">
              <div className="absolute top-[-20%] right-[-10%] w-[40%] h-[80%] bg-sky-500/5 rounded-full blur-[40px] transition-all group-hover:scale-110" />
              <div className="flex items-center justify-between">
                <span className="text-xs font-black uppercase tracking-wider text-[var(--app-text-soft)]">
                  Total Submissions
                </span>
                <div className="w-10 h-10 rounded-xl bg-sky-50 dark:bg-sky-950/20 text-sky-600 flex items-center justify-center">
                  <BarChart3 size={20} />
                </div>
              </div>
              <div>
                <h3 className="text-3xl font-black text-[var(--app-text)] tracking-tight">
                  <AnimatedCounter value={totalFeedbackCount} />
                </h3>
                <span className="text-xs text-[var(--app-text-soft)] font-semibold mt-1 block">
                  Aggregated conversational responses
                </span>
              </div>
            </div>

            <div className="bg-[var(--app-surface)] border border-[var(--app-border)]/60 rounded-3xl p-6 relative overflow-hidden shadow-sm hover:shadow-md transition-all duration-300 flex flex-col justify-between min-h-[140px] group">
              <div className="absolute top-[-20%] right-[-10%] w-[40%] h-[80%] bg-emerald-500/5 rounded-full blur-[40px] transition-all group-hover:scale-110" />
              <div className="flex items-center justify-between">
                <span className="text-xs font-black uppercase tracking-wider text-[var(--app-text-soft)]">
                  Positive Satisfaction
                </span>
                <div className="w-10 h-10 rounded-xl bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 flex items-center justify-center">
                  <ThumbsUp size={20} />
                </div>
              </div>
              <div>
                <h3 className="text-3xl font-black text-[var(--app-text)] tracking-tight flex items-baseline gap-2">
                  <AnimatedCounter value={thumbsUpOverallPercentage} decimals={1} suffix="%" />
                  <span className="text-sm text-emerald-500 font-extrabold">
                    (<AnimatedCounter value={totalThumbsUpCount} /> counts)
                  </span>
                </h3>
                <span className="text-xs text-[var(--app-text-soft)] font-semibold mt-1 block">
                  Thumbs up rating distribution
                </span>
              </div>
            </div>

            <div className="bg-[var(--app-surface)] border border-[var(--app-border)]/60 rounded-3xl p-6 relative overflow-hidden shadow-sm hover:shadow-md transition-all duration-300 flex flex-col justify-between min-h-[140px] group">
              <div className="absolute top-[-20%] right-[-10%] w-[40%] h-[80%] bg-violet-500/5 rounded-full blur-[40px] transition-all group-hover:scale-110" />
              <div className="flex items-center justify-between">
                <span className="text-xs font-black uppercase tracking-wider text-[var(--app-text-soft)]">
                  Issue Reports
                </span>
                <div className="w-10 h-10 rounded-xl bg-violet-50 dark:bg-violet-950/20 text-violet-600 flex items-center justify-center">
                  <ThumbsDown size={20} />
                </div>
              </div>
              <div>
                <h3 className="text-3xl font-black text-[var(--app-text)] tracking-tight flex items-baseline gap-2">
                  <AnimatedCounter value={thumbsDownOverallPercentage} decimals={1} suffix="%" />
                  <span className="text-sm text-violet-500 font-extrabold">
                    (<AnimatedCounter value={totalThumbsDownCount} /> counts)
                  </span>
                </h3>
                <span className="text-xs text-[var(--app-text-soft)] font-semibold mt-1 block">
                  Thumbs down issues distribution
                </span>
              </div>
            </div>
          </div>

          <Card className="bg-[var(--app-surface)] border border-[var(--app-border)]/60 shadow-xl rounded-3xl p-6 overflow-hidden">
            <Space direction="vertical" size={24} className="w-full">
              <div style={{ maxWidth: 400 }}>
                <Input
                  placeholder="Search feedback logs..."
                  prefix={<SearchOutlined className="text-[var(--app-text-soft)] mr-1" />}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="h-11 !rounded-2xl !bg-[var(--app-surface-muted)] !border-none font-bold text-[var(--app-text)] px-4"
                  allowClear
                />
              </div>

              <Table
                dataSource={filteredItems}
                columns={columns}
                loading={loadingFeedback}
                rowKey={(record: any) => record.time + record.user?.id}
                pagination={{
                  pageSize: 10,
                  showSizeChanger: true,
                  pageSizeOptions: ["10", "25", "50"],
                  className: "font-semibold",
                }}
                className="custom-feedback-table"
                scroll={{ x: true }}
              />
            </Space>
          </Card>
        </div>
      )}

      <Modal
        title={
          <div className="flex items-center gap-2 text-[var(--app-text)] font-extrabold text-lg pb-2 border-b border-[var(--app-border)]/40">
            <Sparkles size={20} className="text-[#0fb5a1]" />
            <span>Response Details</span>
          </div>
        }
        open={detailModalOpen}
        onCancel={() => {
          setDetailModalOpen(false);
          setSelectedRecordForDetail(null);
        }}
        footer={[
          <Button
            key="close"
            type="primary"
            onClick={() => {
              setDetailModalOpen(false);
              setSelectedRecordForDetail(null);
            }}
            className="!rounded-xl !bg-[#0fb5a1] !border-none !font-bold"
          >
            Close
          </Button>
        ]}
        centered
        width={700}
        className="feedback-detail-modal"
      >
        {selectedRecordForDetail && (
          <div className="mt-5 space-y-6">
            <div className="flex justify-between items-center text-xs bg-[var(--app-surface-muted)] border border-[var(--app-border)]/40 p-3.5 rounded-2xl">
              <div>
                <span className="font-extrabold text-[var(--app-text-soft)]">Flagged By: </span>
                <span className="font-extrabold text-[var(--app-text)]">
                  {`${selectedRecordForDetail.user?.first_name || ""} ${selectedRecordForDetail.user?.last_name || ""}`.trim() || "N/A"}
                </span>
                <span className="text-[var(--app-text-soft)] ml-1">({selectedRecordForDetail.user?.email || "N/A"})</span>
              </div>
              <div>
                <span className="font-extrabold text-[var(--app-text-soft)]">Agent: </span>
                <span className="font-extrabold text-[#0fb5a1] uppercase">{selectedRecordForDetail.agent?.name || "N/A"}</span>
              </div>
            </div>

           
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs font-black uppercase text-[var(--app-text-soft)] tracking-wider">
                <User size={14} className="text-[#0fb5a1]" />
                <span>User Question</span>
              </div>
              <div className="bg-[#0fb5a1]/5 dark:bg-[#0fb5a1]/10 border border-[#0fb5a1]/25 p-5 rounded-3xl text-sm font-semibold text-[var(--app-text)] leading-relaxed">
                {selectedRecordForDetail.question || "N/A"}
              </div>
            </div>

            
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs font-black uppercase text-[var(--app-text-soft)] tracking-wider">
                <Bot size={14} className="text-violet-500" />
                <span>AI Response</span>
              </div>
              <div className="bg-[var(--app-surface-muted)] border border-[var(--app-border)]/60 p-5 pr-3 rounded-3xl text-sm font-medium text-[var(--app-text)] leading-relaxed max-h-[250px] overflow-y-auto custom-dashboard-scroll">
                <Paragraph className="!mb-0 whitespace-pre-wrap leading-relaxed text-[var(--app-text)]">
                  {selectedRecordForDetail.ai_response || "N/A"}
                </Paragraph>
              </div>
            </div>

           
            {selectedRecordForDetail && (() => {
              const detailCitations = getRecordCitations(selectedRecordForDetail);
              if (detailCitations.length === 0) return null;
              return (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-xs font-black uppercase text-[var(--app-text-soft)] tracking-wider">
                    <LinkOutlined className="text-[#0fb5a1]" />
                    <span>Sources & Citations</span>
                  </div>
                  <div className="border border-[var(--app-border)]/60 rounded-3xl p-4 pr-2 bg-[var(--app-surface-muted)] max-h-[150px] overflow-y-auto custom-dashboard-scroll space-y-1.5">
                    {detailCitations.map((citation, index) => {
                      const cleanName = getCleanCitationName(citation.rawSource);
                      const fileIcon = getIconForFile(cleanName);

                      return (
                        <div
                          key={index}
                          onClick={() => handleCitationClick(citation, detailCitations)}
                          className="flex items-center gap-2.5 text-xs font-bold text-[#0fb5a1] hover:text-[#0c9584] hover:bg-[#0fb5a1]/5 p-2.5 rounded-2xl bg-[var(--app-surface)] border border-[var(--app-border)]/40 transition-all cursor-pointer"
                        >
                          {fileIcon}
                          <span className="truncate flex-1" title={cleanName}>{cleanName}</span>
                          <ExternalLink size={12} className="opacity-70 shrink-0" />
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })()}

           
            <div className="flex items-center justify-between border-t border-[var(--app-border)]/40 pt-4 text-xs font-semibold text-[var(--app-text-soft)]">
              <div>
                Feedback: {" "}
                <Tag color={selectedRecordForDetail.feedback_type === "thumbs_up" ? "green" : "red"} className="font-bold">
                  {selectedRecordForDetail.feedback_type === "thumbs_up" ? "Thumbs Up" : "Thumbs Down"}
                </Tag>
              </div>
              <div>
                Reason: <span className="text-[var(--app-text)] font-extrabold">{selectedRecordForDetail.feedback_reason || "None"}</span>
              </div>
            </div>
          </div>
        )}
      </Modal>

     
      <Modal
        title={
          <div className="flex items-center gap-2 text-[var(--app-text)] font-extrabold text-lg pb-2 border-b border-[var(--app-border)]/40">
            <DatabaseOutlined className="text-[#0fb5a1]" />
            <span>Retrieved Knowledge Chunks</span>
          </div>
        }
        open={chunksModalOpen}
        onCancel={() => {
          setChunksModalOpen(false);
          setSelectedRecordForChunks(null);
        }}
        footer={[
          <Button
            key="close"
            type="primary"
            onClick={() => {
              setChunksModalOpen(false);
              setSelectedRecordForChunks(null);
            }}
            className="!rounded-xl !bg-[#0fb5a1] !border-none !font-bold"
          >
            Close
          </Button>
        ]}
        centered
        width={900}
        className="feedback-chunks-modal"
      >
        {selectedRecordForChunks && (
          <div className="mt-5 space-y-6">
            <div className="flex justify-between items-center text-xs bg-[var(--app-surface-muted)] border border-[var(--app-border)]/40 p-3.5 rounded-2xl">
              <div>
                <span className="font-extrabold text-[var(--app-text-soft)]">Session ID: </span>
                <span className="font-mono text-gray-500 text-[11px]">{selectedRecordForChunks.view?.session_id || "N/A"}</span>
              </div>
              <div>
                <span className="font-extrabold text-[var(--app-text-soft)]">Message ID: </span>
                <span className="font-mono text-gray-500 text-[11px]">{selectedRecordForChunks.view?.message_id || "N/A"}</span>
              </div>
            </div>

            
            <div className="border border-[var(--app-border)]/60 rounded-2xl overflow-hidden shadow-inner bg-[var(--app-surface-muted)] p-1">
              <Table
                dataSource={selectedRecordForChunks.view?.retrieved_chunks || []}
                columns={chunkColumns}
                rowKey="chunk_id"
                pagination={false}
                locale={{
                  emptyText: (
                    <div className="py-8 flex flex-col items-center text-gray-400 gap-1.5 font-bold">
                      <AlertCircle size={20} />
                      <span>No document chunks were retrieved for this query.</span>
                    </div>
                  )
                }}
                className="nested-chunk-table"
                size="small"
                scroll={{ x: true }}
              />
            </div>
          </div>
        )}
      </Modal>

      
      <style jsx global>{`
        .custom-feedback-table .ant-table {
          background: transparent !important;
        }
        .custom-feedback-table .ant-table-thead > tr > th {
          background: var(--app-surface-muted) !important;
          color: var(--app-text-soft) !important;
          font-weight: 800 !important;
          text-transform: uppercase !important;
          font-size: 11px !important;
          letter-spacing: 0.05em !important;
          border-bottom: 1px solid rgba(0, 0, 0, 0.05) !important;
        }
        .custom-feedback-table .ant-table-tbody > tr > td {
          border-bottom: 1px solid rgba(0, 0, 0, 0.02) !important;
          padding: 16px 16px !important;
        }
        .custom-feedback-table .ant-table-tbody > tr:hover > td {
          background: rgba(15, 181, 161, 0.03) !important;
        }
        .nested-chunk-table .ant-table-thead > tr > th {
          background: var(--app-surface) !important;
          font-weight: 800 !important;
          font-size: 10px !important;
        }
        .citations-popover .ant-popover-inner {
          background-color: var(--app-surface) !important;
          border: 1px solid var(--app-border) !important;
          border-radius: 20px !important;
          padding: 12px 14px !important;
          box-shadow: 0 10px 30px rgba(0, 0, 0, 0.15) !important;
        }
        .citations-popover .ant-popover-arrow::after {
          background-color: var(--app-surface) !important;
        }
      `}</style>
    </div>
  );
}
