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
} from "antd";
import { Eye, FileText } from "lucide-react";
import dayjs from "dayjs";
import { marked } from "marked";
import useAxios from "../../hooks/useAxios";
import { useAgents } from "../../hooks/useAgents";
import { useStore } from "../../hooks/useStore";
import { toast } from "react-hot-toast";

const { Title, Text } = Typography;
const { Option } = Select;

export default function KnowledgeBaseFilesPage() {
  const { userId } = useStore();
  const activeUserId = userId || (typeof window !== "undefined" ? localStorage.getItem("userId") : null);

  const { agents, isLoading: isLoadingAgents } = useAgents();

  // Filters State
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  // Pagination State
  const [limit, setLimit] = useState<number>(50);
  const [offset, setOffset] = useState<number>(0);

  // Knowledge base list
  const [kbs, setKbs] = useState<any[]>([]);
  const [total, setTotal] = useState<number>(0);

  // Parsed Content Preview Modal State
  const [parsedModalOpen, setParsedModalOpen] = useState(false);
  const [selectedFileName, setSelectedFileName] = useState("");
  const [loadingParsedContent, setLoadingParsedContent] = useState(false);
  const [parsedContent, setParsedContent] = useState("");
  const [parsedPath, setParsedPath] = useState("");

  const [request, , loading] = useAxios({
    endpoint: "GET_USER_KBS",
    hideErrorMsg: false,
  });

  const fetchKbs = useCallback(async () => {
    if (!activeUserId) return;

    let path = `/${activeUserId}?limit=${limit}&offset=${offset}`;

    if (selectedDate) {
      path += `&date=${selectedDate}`;
    }
    if (selectedAgent) {
      path += `&agent_id=${selectedAgent}`;
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
  }, [activeUserId, limit, offset, selectedDate, selectedAgent, request]);

  useEffect(() => {
    fetchKbs();
  }, [fetchKbs]);

  const handleDateChange = (date: any, dateString: string | string[] | null) => {
    setSelectedDate(dateString ? (Array.isArray(dateString) ? dateString[0] : dateString) : null);
    setOffset(0);
  };

  const handleAgentChange = (value: string) => {
    setSelectedAgent(value || null);
    setOffset(0);
  };

  const handleReset = () => {
    setSelectedDate(null);
    setSelectedAgent(null);
    setOffset(0);
  };

  const handleViewParsedContent = async (path: string, fileName: string) => {
    setSelectedFileName(fileName);
    setParsedPath(path);
    setParsedModalOpen(true);
    setLoadingParsedContent(true);
    setParsedContent("");

    try {
      const res = await fetch(path);
      if (!res.ok) {
        throw new Error(`Failed to fetch parsed content (status ${res.status})`);
      }
      const text = await res.text();
      setParsedContent(text);
    } catch (err: any) {
      console.error("Failed to load parsed content directly:", err);
      toast.error("Could not load parsed content directly. Opening in new tab instead...");
      window.open(path, "_blank");
      setParsedModalOpen(false);
    } finally {
      setLoadingParsedContent(false);
    }
  };

  const columns = [
    {
      title: "File Name",
      dataIndex: "name",
      key: "name",
      render: (text: string) => (
        <Text className="font-semibold text-[var(--app-text)]">{text || "Unnamed File"}</Text>
      ),
    },
    {
      title: "Agent",
      dataIndex: "agent_id",
      key: "agent_id",
      render: (agentId: string) => {
        const agent = agents.find((a: any) => a.id === agentId);
        return (
          <Text className="text-[var(--app-text-soft)]">
            {agent ? agent.name : agentId || "N/A"}
          </Text>
        );
      },
    },
    {
      title: "Created At",
      dataIndex: "created_at",
      key: "created_at",
      render: (date: string) => (
        <Text className="text-[var(--app-text-soft)]">
          {date ? dayjs(date).format("YYYY-MM-DD HH:mm:ss") : "N/A"}
        </Text>
      ),
    },
    {
      title: "Actions",
      key: "actions",
      render: (_: any, record: any) => (
        <Space size="middle">
          {record.s3_path && (
            <Tooltip title="View Original File">
              <Button
                type="text"
                className="flex items-center justify-center p-2 rounded-lg hover:bg-teal-50 dark:hover:bg-teal-950/20"
                icon={<Eye size={18} className="text-[#0fb5a1]" />}
                onClick={() => window.open(record.s3_path, "_blank")}
              />
            </Tooltip>
          )}
          {record.parsed_path && (
            <Tooltip title="View Parsed Text">
              <Button
                type="text"
                className="flex items-center justify-center p-2 rounded-lg hover:bg-amber-50 dark:hover:bg-amber-950/20"
                icon={<FileText size={18} className="text-[#f59e0b]" />}
                onClick={() => handleViewParsedContent(record.parsed_path, record.name)}
              />
            </Tooltip>
          )}
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
            <Col xs={24} sm={10}>
              <Flex vertical gap={8}>
                <Text className="text-xs font-bold text-[var(--app-text-soft)] uppercase tracking-wider">
                  Filter by Date
                </Text>
                <DatePicker
                  size="large"
                  className="w-full"
                  value={selectedDate ? dayjs(selectedDate) : null}
                  onChange={handleDateChange}
                />
              </Flex>
            </Col>
            <Col xs={24} sm={10}>
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
                disabled={!selectedDate && !selectedAgent}
              >
                Clear Filters
              </Button>
            </Col>
          </Row>
        </Card>

        {/* Table Content Section */}
        <Card className="bg-[var(--app-surface)] border-[var(--app-border)] shadow-sm rounded-2xl overflow-hidden">
          <Table
            columns={columns}
            dataSource={kbs}
            rowKey="id"
            loading={loading}
            pagination={paginationConfig}
            className="custom-table"
          />
        </Card>
      </Flex>

      {/* Parsed Content Preview Modal */}
      <Modal
        title={
          <Title level={4} className="!m-0 text-[var(--app-text)] font-extrabold truncate pr-8">
            Parsed Content Preview: {selectedFileName}
          </Title>
        }
        open={parsedModalOpen}
        onCancel={() => setParsedModalOpen(false)}
        footer={[
          <Button key="close" size="large" onClick={() => setParsedModalOpen(false)}>
            Close
          </Button>,
          <Button
            key="newTab"
            size="large"
            type="primary"
            onClick={() => window.open(parsedPath, "_blank")}
          >
            Open in New Tab
          </Button>,
        ]}
        width={800}
        centered
        className="parsed-preview-modal"
      >
        {loadingParsedContent ? (
          <div className="flex flex-col items-center justify-center py-20 gap-4">
            <Spin size="large" className="text-[#0fb5a1]" />
            <Text className="text-xs font-bold uppercase tracking-wider text-[var(--app-text-soft)]">
              Fetching Extracted Content...
            </Text>
          </div>
        ) : (
          <div
            className="p-6 max-h-[500px] overflow-y-auto bg-[var(--app-surface-muted)] rounded-xl border border-[var(--app-border)]"
            style={{
              fontSize: "14px",
              lineHeight: "1.6",
            }}
          >
            <div
              className="prose dark:prose-invert max-w-none text-[var(--app-text)]"
              dangerouslySetInnerHTML={{
                __html: renderMarkdown(parsedContent),
              }}
            />
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
        }
        .custom-table :global(.ant-table-tbody > tr > td) {
          border-bottom: 1px solid var(--app-border) !important;
          color: var(--app-text) !important;
          background: var(--app-surface) !important;
          padding: 16px 24px !important;
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
      `}</style>
    </div>
  );
}
