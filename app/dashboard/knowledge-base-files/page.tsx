"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Typography,
  Card,
  Row,
  Col,
  DatePicker,
  Select,
  Button,
  Table,
  Space,
  Tooltip,
  Modal,
  Spin,
  Flex,
  Input,
  Segmented,
  Tag,
} from "antd";
import { Eye, Search } from "lucide-react";
import dayjs from "dayjs";
import { marked } from "marked";
import useAxios from "../../hooks/useAxios";
import { useAgents } from "../../hooks/useAgents";
import { useStore } from "../../hooks/useStore";
import { toast } from "react-hot-toast";
import { getCookie } from "../../config/cookies";

const { Title, Text } = Typography;
const { Option } = Select;

// Helper to parse Python Dict strings (copied from knowledge-base/page.tsx)
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

// Helper to clean extracted text formatting (copied from knowledge-base/page.tsx)
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

export default function KnowledgeBaseFilesPage() {
  const { userId } = useStore();
  const activeUserId = userId || (typeof window !== "undefined" ? localStorage.getItem("userId") : null);

  const { agents, isLoading: isLoadingAgents } = useAgents();

  // Filters State
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [dateRange, setDateRange] = useState<[string, string] | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  // Pagination State
  const [limit, setLimit] = useState<number>(50);
  const [offset, setOffset] = useState<number>(0);

  // Knowledge base list
  const [kbs, setKbs] = useState<any[]>([]);
  const [total, setTotal] = useState<number>(0);

  // Integrated Preview Modal State
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewTab, setPreviewTab] = useState<"original" | "parsed">("original");
  const [previewItem, setPreviewItem] = useState<any>(null);
  const [previewUrl, setPreviewUrl] = useState<string>("");
  const [parsedText, setParsedText] = useState<string>("");
  const [previewType, setPreviewType] = useState<string>("other");
  const [spreadsheetData, setSpreadsheetData] = useState<{ [sheetName: string]: string[][] } | null>(null);
  const [spreadsheetSheets, setSpreadsheetSheets] = useState<string[]>([]);
  const [activeSheet, setActiveSheet] = useState<string>("");

  const [request, , loading] = useAxios({
    endpoint: "GET_USER_KBS",
    hideErrorMsg: false,
  });

  const fetchKbs = useCallback(async () => {
    if (!activeUserId) return;

    let path = `/${activeUserId}?limit=${limit}&offset=${offset}`;

    if (dateRange && dateRange[0] && dateRange[1]) {
      path += `&start_date=${dateRange[0]}&end_date=${dateRange[1]}`;
    }
    if (selectedAgent) {
      path += `&agent_id=${selectedAgent}`;
    }
    if (searchQuery) {
      path += `&search=${encodeURIComponent(searchQuery)}`;
    }

    try {
      await request({ path }, (res) => {
        const kbsList = res?.data?.kbs ?? [];
        const totalCount = res?.data?.total ?? 0;
        setKbs(kbsList);
        setTotal(totalCount);
      });
    } catch (err) {
      console.error("Failed to fetch knowledge base files:", err);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeUserId, limit, offset, dateRange, selectedAgent, searchQuery]);

  // Debounce API calls for search query, and trigger on other filter updates immediately
  useEffect(() => {
    const delayDebounceFn = setTimeout(
      () => {
        fetchKbs();
      },
      searchQuery ? 300 : 0
    );

    return () => clearTimeout(delayDebounceFn);
  }, [fetchKbs, searchQuery]);

  const handleDateRangeChange = (dates: any, dateStrings: [string, string]) => {
    if (dates && dateStrings[0] && dateStrings[1]) {
      setDateRange([dateStrings[0], dateStrings[1]]);
    } else {
      setDateRange(null);
    }
    setOffset(0);
  };

  const handleAgentChange = (value: string) => {
    setSelectedAgent(value || null);
    setOffset(0);
  };

  const handleReset = () => {
    setSearchQuery("");
    setDateRange(null);
    setSelectedAgent(null);
    setOffset(0);
  };

  const handlePreview = async (item: any) => {
    const nameStr = (item.name || item.source || "").toLowerCase();
    const isUrl = nameStr.includes("url") || nameStr.includes("http") || nameStr.includes("www.");

    if (isUrl) {
      const rawSource = item.name || item.source || "";
      let extractedUrl = "";
      const urlMatch = rawSource.match(/(https?:\/\/[^\s]+)/i);
      if (urlMatch) {
        extractedUrl = urlMatch[1];
      } else {
        const domainMatch = rawSource.match(/([a-zA-Z0-9-]+\.[a-zA-Z]{2,}[^\s]*)/);
        if (domainMatch) {
          extractedUrl = "https://" + domainMatch[1];
        } else {
          extractedUrl = rawSource;
        }
      }

      if (extractedUrl) {
        window.open(extractedUrl, '_blank');
      }
      return;
    }

    setPreviewItem(item);
    setPreviewOpen(true);
    setPreviewLoading(true);
    setPreviewUrl("");
    setParsedText("");

    // Set initial tab: parsed content first if it's text or pdf without original
    const isText = nameStr.includes("text");
    const isPdf = nameStr.endsWith(".pdf");
    if (isPdf && (isText || (item.parsed_path && !item.s3_path))) {
      setPreviewTab("parsed");
    } else {
      setPreviewTab("original");
    }

    try {
      const token = getCookie("AUTH_TOKEN");
      const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;

      // 1. Fetch Original Document as blob via proxy endpoint
      if (item.s3_path && item.id) {
        const fetchUrl = `${API_BASE_URL}/files/${item.id}/preview`;
        const res = await fetch(fetchUrl, {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });
        if (res.ok) {
          const blob = await res.blob();
          const bUrl = URL.createObjectURL(blob);
          setPreviewUrl(bUrl);

          const contentType = blob.type.toLowerCase();
          const isPDF = contentType.includes("pdf") || nameStr.endsWith(".pdf");
          const isImage =
            contentType.includes("image/") ||
            nameStr.endsWith(".png") ||
            nameStr.endsWith(".jpg") ||
            nameStr.endsWith(".jpeg") ||
            nameStr.endsWith(".webp") ||
            nameStr.endsWith(".gif");
          const isCSV = contentType.includes("csv") || nameStr.endsWith(".csv");
          const isExcel =
            contentType.includes("excel") ||
            contentType.includes("spreadsheet") ||
            contentType.includes("vnd.ms-excel") ||
            contentType.includes("vnd.openxmlformats-officedocument.spreadsheetml.sheet") ||
            nameStr.endsWith(".xls") ||
            nameStr.endsWith(".xlsx");

          if (isPDF) {
            setPreviewType("pdf");
          } else if (isImage) {
            setPreviewType("image");
          } else if (isCSV || isExcel) {
            try {
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
              setSpreadsheetData(sheetsData);
              setSpreadsheetSheets(workbook.SheetNames);
              setActiveSheet(workbook.SheetNames[0] || "");
              setPreviewType("excel");
            } catch (err) {
              console.error("Failed to parse spreadsheet:", err);
              setPreviewType("other");
            }
          } else {
            setPreviewType("other");
          }
        }
      }

      // 2. Fetch Parsed Content text representation (with direct fetch fallback)
      if (item.parsed_path && item.id) {
        const fetchUrl = `${API_BASE_URL}/files/${item.id}/content`;
        try {
          const res = await fetch(fetchUrl, {
            headers: {
              Authorization: `Bearer ${token}`,
            },
          });
          if (res.ok) {
            const data = await res.json();
            const rawText = data?.content || data?.text || (typeof data === "string" ? data : "");
            const cleanedText = cleanExtractedText(rawText);
            setParsedText(cleanedText);
          } else {
            throw new Error("Backend file content endpoint failed");
          }
        } catch (err) {
          console.warn("API parsed content failed. Trying direct parsed_path load:", err);
          const directRes = await fetch(item.parsed_path);
          if (directRes.ok) {
            const rawText = await directRes.text();
            const cleanedText = cleanExtractedText(rawText);
            setParsedText(cleanedText);
          }
        }
      }
    } catch (err) {
      console.error("Preview loading error:", err);
      toast.error("Failed to load document preview.");
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleClosePreview = () => {
    setPreviewOpen(false);
    if (previewUrl && previewUrl.startsWith("blob:")) {
      URL.revokeObjectURL(previewUrl);
    }
    setPreviewUrl("");
    setParsedText("");
    setPreviewItem(null);
    setSpreadsheetData(null);
    setSpreadsheetSheets([]);
    setActiveSheet("");
  };

  // Perform client-side filter on top of server data
  const filteredKbs = kbs.filter((kb) => {
    // 1. Search filter
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const nameStr = (kb.name || kb.source || "").toLowerCase();
      if (!nameStr.includes(q)) return false;
    }

    // 2. Date range filter (inclusive check)
    if (dateRange && dateRange[0] && dateRange[1]) {
      if (kb.created_at) {
        const itemDate = dayjs(kb.created_at);
        const start = dayjs(dateRange[0]).startOf("day");
        const end = dayjs(dateRange[1]).endOf("day");
        if (itemDate.isBefore(start) || itemDate.isAfter(end)) {
          return false;
        }
      }
    }

    return true;
  });

  const columns = [
    {
      title: "File Name",
      dataIndex: "name",
      key: "name",
      minWidth: 200,
      render: (text: string) => {
        const cleaned = text ? text.replace(/^(pdf|spreadsheet|text|url|file|csv|excel):\s*/i, "") : "Unnamed File";
        return (
          <Text className="font-semibold text-[var(--app-text)] block break-words max-w-sm">{cleaned}</Text>
        );
      },
    },
    {
      title: "Agent",
      dataIndex: "agent_id",
      key: "agent_id",
      minWidth: 120,
      render: (agentId: string) => {
        const agent = agents.find((a: any) => a.id === agentId);
        return (
          <Text className="text-[var(--app-text-soft)] whitespace-nowrap">
            {agent ? agent.name : agentId || "N/A"}
          </Text>
        );
      },
    },
    {
      title: "Created At",
      dataIndex: "created_at",
      key: "created_at",
      minWidth: 160,
      render: (date: string) => (
        <Text className="text-[var(--app-text-soft)] whitespace-nowrap">
          {date ? dayjs(date).format("DD MMM YYYY hh:mm A") : "N/A"}
        </Text>
      ),
    },
    {
      title: "Actions",
      key: "actions",
      minWidth: 80,
      render: (_: any, record: any) => (
        <Space size="middle">
          <Tooltip title="View Document Preview">
            <Button
              type="text"
              className="flex items-center justify-center p-2 rounded-lg hover:bg-teal-50 dark:hover:bg-teal-950/20"
              icon={<Eye size={18} className="text-[#0fb5a1]" />}
              onClick={() => handlePreview(record)}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  const paginationConfig = {
    current: Math.floor(offset / limit) + 1,
    pageSize: limit,
    total: total,
    showSizeChanger: true,
    pageSizeOptions: ["10", "20", "50", "100"],
    onChange: (page: number, pageSize: number) => {
      setLimit(pageSize);
      setOffset((page - 1) * pageSize);
    },
  };

  const markedObj = marked as any;
  const renderMarkdown = (content: string) => {
    return typeof markedObj === "function" ? markedObj(content) : markedObj.parse(content || "");
  };

  const modalTabs = [];
  if (previewItem?.s3_path) {
    modalTabs.push({ value: "original", label: "Original Document" });
  }
  if (previewItem?.parsed_path) {
    modalTabs.push({ value: "parsed", label: "Extracted Text" });
  }

  return (
    <div className="w-full max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8 pb-24 relative min-h-screen">
      <Flex vertical gap={40}>
        {/* Header Block */}
        <div>
          <Title level={1} className="!m-0 !font-extrabold !text-3xl sm:!text-4xl tracking-tight text-[var(--app-text)]">
            Knowledge Files
          </Title>
          <Text className="block mt-2 text-sm sm:text-base text-[var(--app-text-soft)] font-medium">
            Browse and view ingested knowledge base sources, original files, and extracted text representations.
          </Text>
        </div>

        {/* Filter Section */}
        <Card className="bg-[var(--app-surface)] border-[var(--app-border)] shadow-sm rounded-2xl">
          <Row gutter={[20, 20]} align="bottom">
            <Col xs={24} sm={8}>
              <Flex vertical gap={8}>
                <Text className="text-xs font-bold text-[var(--app-text-soft)] uppercase tracking-wider">
                  Search Files
                </Text>
                <Input
                  size="large"
                  placeholder="Search file name..."
                  prefix={<Search size={18} className="text-[var(--app-text-soft)] mr-1" />}
                  value={searchQuery}
                  onChange={(e) => {
                    setSearchQuery(e.target.value);
                    setOffset(0);
                  }}
                  allowClear
                />
              </Flex>
            </Col>
            <Col xs={24} sm={6}>
              <Flex vertical gap={8}>
                <Text className="text-xs font-bold text-[var(--app-text-soft)] uppercase tracking-wider">
                  Filter by Date Range
                </Text>
                <DatePicker.RangePicker
                  size="large"
                  className="w-full"
                  popupClassName="single-month-rangepicker"
                  value={dateRange ? [dayjs(dateRange[0]), dayjs(dateRange[1])] : null}
                  onChange={handleDateRangeChange}
                  format="YYYY-MM-DD"
                  allowClear
                />
              </Flex>
            </Col>
            <Col xs={24} sm={6}>
              <Flex vertical gap={8}>
                <Text className="text-xs font-bold text-[var(--app-text-soft)] uppercase tracking-wider">
                  Filter by Agent
                </Text>
                <Select
                  showSearch
                  size="large"
                  placeholder="Select Agent"
                  optionFilterProp="children"
                  value={selectedAgent}
                  onChange={handleAgentChange}
                  allowClear
                  className="w-full"
                  loading={isLoadingAgents}
                >
                  {agents.map((agent: any) => (
                    <Option key={agent.id} value={agent.id}>
                      {agent.name}
                    </Option>
                  ))}
                </Select>
              </Flex>
            </Col>
            <Col xs={24} sm={4}>
              <Button
                size="large"
                type="default"
                className="w-full"
                onClick={handleReset}
                disabled={!dateRange && !selectedAgent && !searchQuery}
              >
                Clear Filters
              </Button>
            </Col>
          </Row>
        </Card>

        {/* Table Content Section */}
        <Card className="bg-[var(--app-surface)] border-[var(--app-border)] shadow-sm rounded-2xl overflow-hidden" styles={{ body: { padding: 0 } }}>
          <Table
            columns={columns}
            dataSource={filteredKbs}
            rowKey="id"
            loading={loading}
            pagination={paginationConfig}
            className="custom-table"
            scroll={{ x: 'max-content' }}
          />
        </Card>
      </Flex>

      {/* Integrated Unified Document Preview Modal */}
      <Modal
        title={
          <span className="font-extrabold text-lg text-[var(--app-text)] truncate block" style={{ maxWidth: "85%" }}>
            {previewItem?.name ? previewItem.name.replace(/^(pdf|spreadsheet|text|url|file|csv|excel):\s*/i, "") : "Document Preview"}
          </span>
        }
        open={previewOpen}
        onCancel={handleClosePreview}
        footer={[
          <Button key="close" size="large" onClick={handleClosePreview}>
            Close
          </Button>,
        ]}
        width={1100}
        style={{ top: 20 }}
        centered
        styles={{
          body: {
            padding: "20px 12px 12px 12px",
            height: "80vh",
            display: "flex",
            flexDirection: "column",
            background: "var(--app-surface-muted)",
            gap: 12,
          },
        }}
        className="parsed-preview-modal"
      >
        {modalTabs.length > 1 && !previewLoading && (
          <div className="flex bg-[var(--app-surface)] p-1.5 rounded-xl border border-[var(--app-border)]/40 self-start shrink-0 select-none">
            <Segmented
              options={modalTabs}
              value={previewTab}
              onChange={(val) => setPreviewTab(val as "original" | "parsed")}
              size="small"
            />
          </div>
        )}

        {previewLoading ? (
          <div className="flex flex-col items-center justify-center flex-1 gap-4">
            <Spin size="large" className="text-[#0fb5a1]" />
            <Text className="text-xs font-bold text-[var(--app-text-soft)] uppercase tracking-wider">
              Loading preview content...
            </Text>
          </div>
        ) : (
          <div className="flex-1 w-full bg-[var(--app-surface)] rounded-xl border border-[var(--app-border)]/40 overflow-hidden relative shadow-sm h-full">
            {previewTab === "parsed" ? (
              <div className="w-full h-full overflow-auto p-6">
                {previewItem?.created_at && (
                  <div className="mb-4 pb-4 border-b border-[var(--app-border)]/40 flex items-center justify-between flex-wrap gap-2 text-xs text-[var(--app-text-soft)] font-medium">
                    <span>
                      Agent: <strong className="text-[var(--app-text)]">{agents.find((a: any) => a.id === previewItem.agent_id)?.name || previewItem.agent_id || "N/A"}</strong>
                    </span>
                    <span>
                      Extracted: <strong className="text-[var(--app-text)]">{dayjs(previewItem.created_at).format("DD MMM YYYY hh:mm A")}</strong>
                    </span>
                  </div>
                )}
                <div
                  className="prose dark:prose-invert max-w-none text-[var(--app-text)]"
                  dangerouslySetInnerHTML={{
                    __html: parsedText
                      ? renderMarkdown(parsedText)
                      : "<p style='color: var(--app-text-soft)'>No extracted text content available.</p>",
                  }}
                />
              </div>
            ) : (
              <div className="w-full h-full flex flex-col justify-start overflow-hidden">
                {previewType === "image" && previewUrl ? (
                  <div className="w-full h-full flex items-center justify-center p-4 bg-neutral-900/5 overflow-auto">
                    <img
                      src={previewUrl}
                      alt={previewItem?.name || "Preview"}
                      style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain", borderRadius: "8px" }}
                    />
                  </div>
                ) : previewType === "pdf" && previewUrl ? (
                  <iframe
                    src={`${previewUrl}#navpanes=0`}
                    width="100%"
                    height="100%"
                    style={{ border: "none" }}
                  />
                ) : previewType === "excel" && spreadsheetData && activeSheet ? (
                  <div className="w-full h-full flex flex-col overflow-hidden">
                    {/* Sheet Tabs */}
                    {spreadsheetSheets.length > 1 && (
                      <div className="flex gap-2 p-3 bg-[var(--app-surface-muted)] border-b border-[var(--app-border)]/40 overflow-x-auto shrink-0 select-none">
                        {spreadsheetSheets.map((sheet) => (
                          <button
                            key={sheet}
                            onClick={() => setActiveSheet(sheet)}
                            className={`px-3 py-1.5 text-xs font-semibold rounded-lg border transition-all \${
                              activeSheet === sheet
                                ? "bg-[#0fb5a1] text-white border-[#0fb5a1]"
                                : "bg-[var(--app-surface)] text-[var(--app-text-soft)] border-[var(--app-border)] hover:bg-[var(--app-hover)]"
                            }`}
                          >
                            {sheet}
                          </button>
                        ))}
                      </div>
                    )}
                    {/* Sheet Table */}
                    <div className="flex-1 overflow-auto p-4">
                      <table className="w-full border-collapse bg-[var(--app-surface)] text-xs text-[var(--app-text)] border border-[var(--app-border)]">
                        <thead>
                          <tr className="bg-[var(--app-surface-muted)]">
                            <th className="border border-[var(--app-border)] p-2 text-center font-bold w-10 bg-[var(--app-surface-muted)] text-[var(--app-text-soft)]">#</th>
                            {spreadsheetData[activeSheet]?.[0]?.map((colHeader, idx) => (
                              <th key={idx} className="border border-[var(--app-border)] p-2 text-left font-bold bg-[var(--app-surface-muted)] text-[var(--app-text-soft)]">
                                {colHeader || `Column \${idx + 1}`}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {spreadsheetData[activeSheet]?.slice(1).map((row, rIdx) => (
                            <tr key={rIdx} className="hover:bg-[var(--app-hover)]">
                              <td className="border border-[var(--app-border)] p-2 text-center text-[var(--app-text-soft)] font-medium bg-[var(--app-surface-muted)]/30">
                                {rIdx + 1}
                              </td>
                              {row.map((cell, cIdx) => (
                                <td key={cIdx} className="border border-[var(--app-border)] p-2 text-left">
                                  {cell}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ) : previewUrl ? (
                  <iframe
                    src={previewUrl}
                    width="100%"
                    height="100%"
                    style={{ border: "none" }}
                  />
                ) : (
                  <div className="flex items-center justify-center h-full">
                    <Text className="text-[var(--app-text-soft)]">
                      No original file preview available.
                    </Text>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* Style Overrides for Dark Mode and Antd elements */}
      <style jsx global>{`
        .custom-table :global(.ant-table) {
          background: var(--app-surface) !important;
          color: var(--app-text) !important;
        }
        .custom-table :global(.ant-table-thead > tr > th) {
          background: var(--app-surface-muted) !important;
          color: var(--app-text) !important;
          border-bottom: 1px solid var(--app-border) !important;
          font-weight: 700 !important;
          font-size: 13px !important;
          text-transform: uppercase !important;
          letter-spacing: 0.05em !important;
          padding: 16px 24px !important;
        }
        .custom-table :global(.ant-table-tbody > tr > td) {
          border-bottom: 1px solid var(--app-border) !important;
          color: var(--app-text) !important;
          background: var(--app-surface) !important;
          padding: 16px 24px !important;
        }
        @media (max-width: 640px) {
          .custom-table :global(.ant-table-thead > tr > th) {
            padding: 12px 14px !important;
            white-space: nowrap !important;
            font-size: 11px !important;
          }
          .custom-table :global(.ant-table-tbody > tr > td) {
            padding: 12px 14px !important;
            font-size: 13px !important;
          }
        }
        .custom-table :global(.ant-table-tbody > tr:hover > td) {
          background: var(--app-hover) !important;
        }
        .custom-table :global(.ant-pagination-item) {
          background: var(--app-surface) !important;
          border-color: var(--app-border) !important;
        }
        .custom-table :global(.ant-pagination-item-active) {
          border-color: var(--app-primary) !important;
          background: var(--app-active-bg) !important;
        }
        .custom-table :global(.ant-pagination-item-active a) {
          color: var(--app-primary) !important;
        }
        .custom-table :global(.ant-pagination-item a) {
          color: var(--app-text) !important;
        }
        .custom-table :global(.ant-pagination-prev .ant-pagination-item-link, .ant-pagination-next .ant-pagination-item-link) {
          background: var(--app-surface) !important;
          border-color: var(--app-border) !important;
          color: var(--app-text) !important;
        }
        
        .parsed-preview-modal :global(.ant-modal-content) {
          background: var(--app-surface) !important;
          border: 1px solid var(--app-border) !important;
          box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04) !important;
          border-radius: 24px !important;
        }
        .parsed-preview-modal :global(.ant-modal-header) {
          background: transparent !important;
          border-bottom: 1px solid var(--app-border) !important;
          padding-bottom: 16px !important;
        }

        /* Basic Markdown rendering styles for the modal preview */
        .prose h1, .prose h2, .prose h3, .prose h4 {
          color: var(--app-text) !important;
          font-weight: 700;
          margin-top: 1.5em;
          margin-bottom: 0.5em;
        }
        .prose h1 { font-size: 1.8em; }
        .prose h2 { font-size: 1.5em; }
        .prose h3 { font-size: 1.3em; }
        .prose p {
          margin-bottom: 1em;
          color: var(--app-text-muted);
        }
        .prose pre {
          background-color: var(--app-surface) !important;
          border: 1px solid var(--app-border);
          padding: 12px;
          border-radius: 8px;
          overflow-x: auto;
          margin: 1.5em 0;
        }
        .prose code {
          font-family: monospace;
          background-color: var(--app-surface);
          padding: 2px 4px;
          border-radius: 4px;
          font-size: 0.9em;
        }
        .prose ul, .prose ol {
          margin-left: 20px;
          margin-bottom: 1em;
          list-style-type: disc;
        }
        .prose li {
          margin-bottom: 0.5em;
          color: var(--app-text-muted);
        }

        /* Markdown Table Styling */
        .prose table {
          min-width: 100%;
          width: max-content;
          max-width: 100%;
          border-collapse: collapse;
          margin: 1.5em 0;
          font-size: 0.9em;
          color: var(--app-text);
          background-color: var(--app-surface) !important;
          border: 1px solid var(--app-border) !important;
          border-radius: 8px;
          overflow: hidden;
        }
        .prose th {
          background-color: var(--app-surface-muted) !important;
          color: var(--app-text) !important;
          font-weight: 700;
          text-transform: uppercase;
          font-size: 0.8rem;
          letter-spacing: 0.05em;
          padding: 10px 14px;
          border-bottom: 2px solid var(--app-border) !important;
          border-right: 1px solid var(--app-border) !important;
          text-align: left;
        }
        .prose td {
          padding: 10px 14px;
          border-bottom: 1px solid var(--app-border) !important;
          border-right: 1px solid var(--app-border) !important;
          color: var(--app-text-soft) !important;
          vertical-align: top;
        }
        .prose th:last-child, .prose td:last-child {
          border-right: none !important;
        }
        .prose tr:last-child td {
          border-bottom: none !important;
        }
        .prose tr:hover td {
          background-color: var(--app-hover) !important;
        }
      `}</style>
    </div>
  );
}
