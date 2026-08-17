"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
import {
  Typography,
  Card,
  Input,
  Button,
  DatePicker,
  Table,
  Tag,
  Flex,
  Row,
  Col,
  Statistic,
  Spin,
  Empty,
  Tooltip,
  Tabs,
  Modal,
  Popover,
} from "antd";
import {
  SearchOutlined,
  ReloadOutlined,
  DollarOutlined,
  ThunderboltOutlined,
  UserOutlined,
  EllipsisOutlined,
  EyeOutlined,
  MessageOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import useAxios from "@/app/hooks/useAxios";

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

interface TokenUsageSummary {
  total_input_tokens?: number;
  total_output_tokens?: number;
  total_embedding_tokens?: number;
  total_tokens?: number;
  total_cost_usd?: number;
  total_queries?: number;
}

interface ModelUsageRecord {
  model_name?: string;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  total_cost_usd?: number;
  request_count?: number;
}

interface UserUsageRecord {
  user_id?: string;
  user_email?: string;
  input_tokens?: number;
  output_tokens?: number;
  embedding_tokens?: number;
  total_tokens?: number;
  total_cost_usd?: number;
  request_count?: number;
}

// Smooth Number CountUp Animation Component
function AnimatedCount({ value, precision = 0, isCurrency = false }: { value: number; precision?: number; isCurrency?: boolean }) {
  const [displayValue, setDisplayValue] = useState<number>(0);

  useEffect(() => {
    let startTimestamp: number | null = null;
    const duration = 1000; // 1 second smooth animation
    const startVal = 0;
    const endVal = value;

    const step = (timestamp: number) => {
      if (!startTimestamp) startTimestamp = timestamp;
      const progress = Math.min((timestamp - startTimestamp) / duration, 1);
      const easeOut = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress);
      const current = startVal + (endVal - startVal) * easeOut;
      setDisplayValue(current);
      if (progress < 1) {
        requestAnimationFrame(step);
      }
    };

    requestAnimationFrame(step);
  }, [value]);

  if (isCurrency) {
    return <span>${displayValue.toFixed(precision)}</span>;
  }

  if (precision > 0) {
    return <span>{displayValue.toFixed(precision)}</span>;
  }

  return <span>{Math.round(displayValue).toLocaleString()}</span>;
}

export default function AdminBillingPage() {
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [dateRange, setDateRange] = useState<[string, string] | null>(null);
  const [pickerValue, setPickerValue] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [activeTab, setActiveTab] = useState<string>("users");

  // Detail Modal States
  const [userModalVisible, setUserModalVisible] = useState<boolean>(false);
  const [selectedUser, setSelectedUser] = useState<UserUsageRecord | null>(null);
  const [modelModalVisible, setModelModalVisible] = useState<boolean>(false);
  const [selectedModel, setSelectedModel] = useState<ModelUsageRecord | null>(null);

  // useAxios hook targeting USER_COSTS endpoint
  const [request, rawData, loading] = useAxios({
    endpoint: "USER_COSTS",
    hideErrorMsg: false,
  });

  // Fetch token & cost data from API
  const fetchCostsData = useCallback(async (start?: string, end?: string) => {
    let path = "";
    if (start && end) {
      path = `?start_date=${start}&end_date=${end}`;
    }
    try {
      await request({ path });
    } catch (err) {
      console.error("Failed to fetch user costs:", err);
    }
  }, [request]);

  // Initial fetch on page mount
  useEffect(() => {
    fetchCostsData();
  }, [fetchCostsData]);

  // Safe destructuring of rawData
  const summary = useMemo<TokenUsageSummary>(() => {
    if (!rawData) return {};
    return (rawData as any).summary || {};
  }, [rawData]);

  const userRecords = useMemo<UserUsageRecord[]>(() => {
    if (!rawData) return [];
    return (rawData as any).by_user || [];
  }, [rawData]);

  const modelRecords = useMemo<ModelUsageRecord[]>(() => {
    if (!rawData) return [];
    const allModels = (rawData as any).by_model || [];
    return allModels.filter((item: ModelUsageRecord) => (item.total_tokens || 0) > 0);
  }, [rawData]);

  // Apply client-side search query filter for users
  const filteredUsers = useMemo(() => {
    if (!searchQuery.trim()) return userRecords;
    const query = searchQuery.toLowerCase().trim();
    return userRecords.filter((item) => {
      const email = (item.user_email || "").toLowerCase();
      const id = (item.user_id || "").toLowerCase();
      return email.includes(query) || id.includes(query);
    });
  }, [userRecords, searchQuery]);

  // Apply client-side search query filter for models
  const filteredModels = useMemo(() => {
    if (!searchQuery.trim()) return modelRecords;
    const query = searchQuery.toLowerCase().trim();
    return modelRecords.filter((item) => {
      const name = (item.model_name || "").toLowerCase();
      return name.includes(query);
    });
  }, [modelRecords, searchQuery]);

  // Handlers
  const handleSearchClick = () => {
    if (dateRange && dateRange[0] && dateRange[1]) {
      fetchCostsData(dateRange[0], dateRange[1]);
    } else {
      fetchCostsData();
    }
  };

  const handleResetFilters = () => {
    setSearchQuery("");
    setDateRange(null);
    setPickerValue(null);
    fetchCostsData();
  };

  // Ant Design Table Columns for Users
  const userColumns = [
    {
      title: "S.No",
      key: "sno",
      width: 65,
      render: (_: any, __: any, index: number) => (
        <span className="font-bold text-[var(--app-text-soft)] text-xs">{index + 1}</span>
      ),
    },
    {
      title: "User Email",
      dataIndex: "user_email",
      key: "user_email",
      minWidth: 200,
      render: (email: string, record: UserUsageRecord) => (
        <Flex align="center" gap={10} className="min-w-0">
          <div className="w-8 h-8 rounded-full bg-[#0fb5a1]/10 text-[#0fb5a1] flex items-center justify-center font-extrabold text-xs shrink-0 border border-[#0fb5a1]/20">
            {email ? email[0].toUpperCase() : <UserOutlined />}
          </div>
          <Flex vertical gap={2} className="min-w-0">
            <Text strong className="text-[var(--app-text)] font-semibold text-sm truncate max-w-[180px] sm:max-w-none block">
              {email || "N/A"}
            </Text>
            {record.user_id && (
              <Text className="text-[11px] text-[var(--app-text-soft)] font-mono opacity-75 truncate max-w-[180px] sm:max-w-none block">
                ID: {record.user_id}
              </Text>
            )}
          </Flex>
        </Flex>
      ),
    },
    {
      title: "Total Tokens",
      dataIndex: "total_tokens",
      key: "total_tokens",
      width: 140,
      sorter: (a: UserUsageRecord, b: UserUsageRecord) => (a.total_tokens || 0) - (b.total_tokens || 0),
      render: (tokens?: number) => (
        <Flex align="center" gap={6}>
          <ThunderboltOutlined className="text-amber-500" />
          <Text className="font-extrabold text-sm text-[var(--app-text)]">
            {(tokens || 0).toLocaleString()}
          </Text>
        </Flex>
      ),
    },
    {
      title: "Total Cost (USD)",
      dataIndex: "total_cost_usd",
      key: "total_cost_usd",
      width: 150,
      sorter: (a: UserUsageRecord, b: UserUsageRecord) => (a.total_cost_usd || 0) - (b.total_cost_usd || 0),
      render: (cost?: number) => (
        <Tag
          color="emerald"
          className="px-3 py-1 text-xs font-bold rounded-lg border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 whitespace-nowrap"
        >
          ${(cost || 0).toFixed(6)}
        </Tag>
      ),
    },
    {
      title: "Action",
      key: "action",
      width: 80,
      render: (_: any, record: UserUsageRecord) => (
        <Tooltip title="View full details">
          <Button
            type="text"
            shape="circle"
            icon={<EyeOutlined className="text-[#0fb5a1]" />}
            onClick={() => {
              setSelectedUser(record);
              setUserModalVisible(true);
            }}
            className="hover:bg-[var(--app-surface-muted)] cursor-pointer"
          />
        </Tooltip>
      ),
    },
  ];

  // Ant Design Table Columns for Models
  const modelColumns = [
    {
      title: "S.No",
      key: "sno",
      width: 65,
      render: (_: any, __: any, index: number) => (
        <span className="font-bold text-[var(--app-text-soft)] text-xs">{index + 1}</span>
      ),
    },
    {
      title: "Model Name",
      dataIndex: "model_name",
      key: "model_name",
      minWidth: 200,
      render: (name: string) => (
        <Flex align="center" gap={10} className="min-w-0">
          <div className="w-8 h-8 rounded-full bg-amber-500/10 text-amber-600 flex items-center justify-center font-extrabold text-xs shrink-0 border border-amber-500/20">
            <ThunderboltOutlined />
          </div>
          <Text strong className="text-[var(--app-text)] font-semibold text-sm truncate max-w-[220px] sm:max-w-none block">
            {name || "default"}
          </Text>
        </Flex>
      ),
    },
    {
      title: "Total Tokens",
      dataIndex: "total_tokens",
      key: "total_tokens",
      width: 140,
      sorter: (a: ModelUsageRecord, b: ModelUsageRecord) => (a.total_tokens || 0) - (b.total_tokens || 0),
      render: (tokens?: number) => (
        <Flex align="center" gap={6}>
          <ThunderboltOutlined className="text-amber-500" />
          <Text className="font-extrabold text-sm text-[var(--app-text)]">
            {(tokens || 0).toLocaleString()}
          </Text>
        </Flex>
      ),
    },
    {
      title: "Total Cost (USD)",
      dataIndex: "total_cost_usd",
      key: "total_cost_usd",
      width: 150,
      sorter: (a: ModelUsageRecord, b: ModelUsageRecord) => (a.total_cost_usd || 0) - (b.total_cost_usd || 0),
      render: (cost?: number) => (
        <Tag
          color="emerald"
          className="px-3 py-1 text-xs font-bold rounded-lg border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 whitespace-nowrap"
        >
          ${(cost || 0).toFixed(6)}
        </Tag>
      ),
    },
    {
      title: "Action",
      key: "action",
      width: 80,
      render: (_: any, record: ModelUsageRecord) => (
        <Tooltip title="View full details">
          <Button
            type="text"
            shape="circle"
            icon={<EyeOutlined className="text-[#0fb5a1]" />}
            onClick={() => {
              setSelectedModel(record);
              setModelModalVisible(true);
            }}
            className="hover:bg-[var(--app-surface-muted)] cursor-pointer"
          />
        </Tooltip>
      ),
    },
  ];

  return (
    <div className="w-full max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8 pb-24 min-h-screen">
      <Flex vertical gap={24}>
        {/* Header Section */}
        <Flex justify="space-between" align="center" wrap gap={16}>
          <div>
            <Title level={1} className="!m-0 !font-extrabold !text-2xl sm:!text-3xl tracking-tight text-[var(--app-text)]">
              Token Usage & Costs
            </Title>
            <Text className="block mt-1 text-xs sm:text-sm text-[var(--app-text-soft)] font-medium">
              Track token consumption, query volume, and calculated USD expenses.
            </Text>
          </div>
          <Button
            type="primary"
            size="large"
            icon={<ReloadOutlined spin={loading} className="!text-white text-base mr-1.5" />}
            onClick={() => handleSearchClick()}
            loading={loading}
            className="!h-12 !px-8 !rounded-full !bg-[#0fb5a1] hover:!bg-[#0d9e8c] !text-white !border-none !font-black !text-sm !uppercase !tracking-widest !shadow-lg hover:!scale-[1.02] transition-all flex items-center justify-center cursor-pointer"
          >
            REFRESH
          </Button>
        </Flex>

        {/* Summary Metric Cards with CountUp Animations */}
        <Row gutter={[16, 16]} style={{ display: "flex", flexWrap: "wrap", alignItems: "stretch" }}>
          <Col xs={24} sm={12} md={8} className="flex flex-col">
            <Card
              className="bg-[var(--app-surface)] border-[var(--app-border)]/60 shadow-sm rounded-2xl w-full h-full flex flex-col justify-center"
              styles={{ body: { padding: "20px 24px", height: "100%", display: "flex", flexDirection: "column", justifyContent: "center" } }}
            >
              <Text className="text-xs font-bold text-[var(--app-text-soft)] uppercase tracking-wider block mb-2">Total Queries</Text>
              <Flex align="center" gap={8} className="w-full">
                <MessageOutlined className="text-[#0fb5a1] text-2xl shrink-0" />
                <span className="text-[var(--app-text)] font-extrabold text-2xl tracking-tight leading-none">
                  <AnimatedCount value={summary.total_queries || 0} />
                </span>
              </Flex>
            </Card>
          </Col>
          <Col xs={24} sm={12} md={8} className="flex flex-col">
            <Card
              className="bg-[var(--app-surface)] border-[var(--app-border)]/60 shadow-sm rounded-2xl w-full h-full flex flex-col justify-center relative"
              styles={{ body: { padding: "20px 24px", height: "100%", display: "flex", flexDirection: "column", justifyContent: "center" } }}
            >
              <div className="absolute top-4 right-4 z-10">
                <Popover
                  zIndex={40}
                  getPopupContainer={(triggerNode) => triggerNode.parentElement || document.body}
                  content={
                    <div className="p-2 min-w-[200px]">
                      <h4 className="text-xs font-black text-[var(--app-text-soft)] uppercase tracking-wider mb-2 border-b border-[var(--app-border)] pb-1">Token Breakdown</h4>
                      <Flex vertical gap={8}>
                        <Flex justify="space-between">
                          <Text className="text-xs font-medium text-[var(--app-text-soft)]">Input Tokens:</Text>
                          <Text className="text-xs font-bold text-[var(--app-text)]">{(summary.total_input_tokens || 0).toLocaleString()}</Text>
                        </Flex>
                        <Flex justify="space-between">
                          <Text className="text-xs font-medium text-[var(--app-text-soft)]">Output Tokens:</Text>
                          <Text className="text-xs font-bold text-[var(--app-text)]">{(summary.total_output_tokens || 0).toLocaleString()}</Text>
                        </Flex>
                        <Flex justify="space-between">
                          <Text className="text-xs font-medium text-[var(--app-text-soft)]">Embedding Tokens:</Text>
                          <Text className="text-xs font-bold text-[var(--app-text)]">{(summary.total_embedding_tokens || 0).toLocaleString()}</Text>
                        </Flex>
                      </Flex>
                    </div>
                  }
                  trigger="click"
                  placement="bottomRight"
                >
                  <Button
                    type="text"
                    shape="circle"
                    icon={<EllipsisOutlined className="text-lg text-[var(--app-text-soft)] hover:text-[var(--app-text)]" />}
                    className="flex items-center justify-center hover:bg-[var(--app-surface-muted)] cursor-pointer"
                  />
                </Popover>
              </div>
              <Text className="text-xs font-bold text-[var(--app-text-soft)] uppercase tracking-wider block mb-2 pr-6">Total Tokens Consumed</Text>
              <Flex align="center" gap={8} className="w-full">
                <ThunderboltOutlined className="text-amber-500 text-2xl shrink-0" />
                <span className="text-[var(--app-text)] font-extrabold text-2xl tracking-tight leading-none">
                  <AnimatedCount value={summary.total_tokens || 0} />
                </span>
              </Flex>
            </Card>
          </Col>
          <Col xs={24} sm={24} md={8} className="flex flex-col">
            <Card
              className="bg-[var(--app-surface)] border-[var(--app-border)]/60 shadow-sm rounded-2xl w-full h-full flex flex-col justify-center"
              styles={{ body: { padding: "20px 24px", height: "100%", display: "flex", flexDirection: "column", justifyContent: "center" } }}
            >
              <Text className="text-xs font-bold text-[var(--app-text-soft)] uppercase tracking-wider block mb-2">Total Expense (USD)</Text>
              <Flex align="center" gap={8} className="w-full min-w-0">
                <DollarOutlined className="text-emerald-500 text-2xl shrink-0" />
                <span className="text-[var(--app-text)] font-extrabold text-2xl tracking-tight leading-none">
                  <AnimatedCount value={summary.total_cost_usd || 0} precision={6} isCurrency />
                </span>
              </Flex>
            </Card>
          </Col>
        </Row>

        {/* Filter Controls Bar */}
        <Card className="bg-[var(--app-surface)] border-[var(--app-border)] shadow-sm rounded-2xl">
          <Row gutter={[16, 16]} align="bottom">
            <Col xs={24} md={8} lg={9}>
              <Flex vertical gap={6}>
                <Text className="text-xs font-bold text-[var(--app-text-soft)] uppercase tracking-wider">
                  Search
                </Text>
                <Input
                  size="large"
                  placeholder={activeTab === "users" ? "Search by user email / ID..." : "Search by model name..."}
                  prefix={<SearchOutlined className="text-[var(--app-text-soft)] mr-1" />}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  allowClear
                  className="rounded-xl border-[var(--app-border)]"
                />
              </Flex>
            </Col>

            <Col xs={24} md={8} lg={9}>
              <Flex vertical gap={6}>
                <Text className="text-xs font-bold text-[var(--app-text-soft)] uppercase tracking-wider">
                  Date
                </Text>
                <RangePicker
                  size="large"
                  value={pickerValue as any}
                  popupClassName="single-panel-range-picker"
                  className="w-full rounded-xl border-[var(--app-border)]"
                  onChange={(dates, dateStrings) => {
                    if (dates && dateStrings && dateStrings[0] && dateStrings[1]) {
                      setPickerValue(dates as any);
                      setDateRange([dateStrings[0], dateStrings[1]]);
                    } else {
                      setPickerValue(null);
                      setDateRange(null);
                    }
                  }}
                />
              </Flex>
            </Col>

            <Col xs={24} md={8} lg={6}>
              <Flex gap={10} className="w-full">
                <Button
                  type="primary"
                  size="large"
                  icon={<SearchOutlined />}
                  onClick={handleSearchClick}
                  className="flex-1 rounded-xl !bg-[#0fb5a1] hover:!bg-[#0d9e8c] font-bold shadow-md shadow-teal-900/10 border-0 cursor-pointer"
                >
                  Search
                </Button>
                <Tooltip title="Reset filters">
                  <Button
                    size="large"
                    onClick={handleResetFilters}
                    className="rounded-xl border-[var(--app-border)] text-[var(--app-text-soft)] hover:text-[var(--app-text)] font-semibold px-4 cursor-pointer"
                  >
                    Reset
                  </Button>
                </Tooltip>
              </Flex>
            </Col>
          </Row>
        </Card>

        {/* Tab Selection & Tables */}
        <div className="custom-tabs-container">
          <Tabs
            activeKey={activeTab}
            onChange={(key) => {
              setActiveTab(key);
              setSearchQuery(""); // Clear search query when tab changes
            }}
            items={[
              {
                key: "users",
                label: (
                  <span className="font-bold text-sm px-2 flex items-center gap-2">
                    <UserOutlined />
                    Users
                  </span>
                ),
                children: (
                  <Card
                    className="bg-[var(--app-surface)] border-[var(--app-border)] shadow-sm rounded-2xl overflow-hidden"
                    styles={{ body: { padding: 0 } }}
                  >
                    <Spin spinning={loading}>
                      <div className="w-full overflow-x-auto custom-scrollbar">
                        <Table
                          dataSource={filteredUsers}
                          columns={userColumns}
                          rowKey={(record, index) => record.user_id || record.user_email || String(index)}
                          scroll={{ x: 550 }}
                          pagination={{
                            pageSize: 10,
                            showSizeChanger: true,
                            pageSizeOptions: ["10", "20", "50", "100"],
                            showTotal: (total, range) => `${range[0]}-${range[1]} of ${total} users`,
                            responsive: true,
                          }}
                          locale={{
                            emptyText: <Empty description="No User Token Usage Records Found" />,
                          }}
                          className="custom-table"
                        />
                      </div>
                    </Spin>
                  </Card>
                ),
              },
              {
                key: "models",
                label: (
                  <span className="font-bold text-sm px-2 flex items-center gap-2">
                    <ThunderboltOutlined />
                    Models
                  </span>
                ),
                children: (
                  <Card
                    className="bg-[var(--app-surface)] border-[var(--app-border)] shadow-sm rounded-2xl overflow-hidden"
                    styles={{ body: { padding: 0 } }}
                  >
                    <Spin spinning={loading}>
                      <div className="w-full overflow-x-auto custom-scrollbar">
                        <Table
                          dataSource={filteredModels}
                          columns={modelColumns}
                          rowKey={(record, index) => record.model_name || String(index)}
                          scroll={{ x: 550 }}
                          pagination={{
                            pageSize: 10,
                            showSizeChanger: true,
                            pageSizeOptions: ["10", "20", "50", "100"],
                            showTotal: (total, range) => `${range[0]}-${range[1]} of ${total} models`,
                            responsive: true,
                          }}
                          locale={{
                            emptyText: <Empty description="No Model Token Usage Records Found" />,
                          }}
                          className="custom-table"
                        />
                      </div>
                    </Spin>
                  </Card>
                ),
              },
            ]}
          />
        </div>
      </Flex>

      {/* User Details Modal */}
      <Modal
        title={
          <Title level={4} className="!m-0 !font-extrabold text-[var(--app-text)] border-b border-[var(--app-border)] pb-3">
            User Usage Details
          </Title>
        }
        open={userModalVisible}
        onCancel={() => {
          setUserModalVisible(false);
          setSelectedUser(null);
        }}
        footer={[
          <Button
            key="close"
            type="primary"
            onClick={() => {
              setUserModalVisible(false);
              setSelectedUser(null);
            }}
            className="!bg-[#0fb5a1] hover:!bg-[#0d9e8c] rounded-xl font-bold px-6 h-10 border-0 cursor-pointer"
          >
            Close
          </Button>
        ]}
        centered
        width={500}
      >
        {selectedUser && (
          <div className="py-4">
            <Flex vertical gap={16}>
              <div className="p-4 rounded-2xl bg-[var(--app-surface-muted)] border border-[var(--app-border)]/60">
                <Text className="block text-[11px] font-bold text-[var(--app-text-soft)] uppercase tracking-wider mb-1">User Email</Text>
                <Text className="text-sm font-semibold text-[var(--app-text)] break-all">{selectedUser.user_email || "N/A"}</Text>
                
                <Text className="block text-[11px] font-bold text-[var(--app-text-soft)] uppercase tracking-wider mt-3 mb-1">User ID</Text>
                <Text className="text-xs font-mono text-[var(--app-text-soft)] break-all">{selectedUser.user_id || "N/A"}</Text>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="p-4 rounded-xl border border-[var(--app-border)]/40 bg-[var(--app-surface)]">
                  <Text className="block text-[10px] font-bold text-[var(--app-text-soft)] uppercase tracking-wider mb-1">Input Tokens</Text>
                  <Text className="text-base font-extrabold text-[var(--app-text)]">{(selectedUser.input_tokens || 0).toLocaleString()}</Text>
                </div>
                <div className="p-4 rounded-xl border border-[var(--app-border)]/40 bg-[var(--app-surface)]">
                  <Text className="block text-[10px] font-bold text-[var(--app-text-soft)] uppercase tracking-wider mb-1">Output Tokens</Text>
                  <Text className="text-base font-extrabold text-[var(--app-text)]">{(selectedUser.output_tokens || 0).toLocaleString()}</Text>
                </div>
                <div className="p-4 rounded-xl border border-[var(--app-border)]/40 bg-[var(--app-surface)]">
                  <Text className="block text-[10px] font-bold text-[var(--app-text-soft)] uppercase tracking-wider mb-1">Embedding Tokens</Text>
                  <Text className="text-base font-extrabold text-[var(--app-text)]">{(selectedUser.embedding_tokens || 0).toLocaleString()}</Text>
                </div>
                <div className="p-4 rounded-xl border border-[var(--app-border)]/40 bg-[var(--app-surface)]">
                  <Text className="block text-[10px] font-bold text-[var(--app-text-soft)] uppercase tracking-wider mb-1">Total Queries</Text>
                  <Text className="text-base font-extrabold text-[var(--app-text)]">{(selectedUser.request_count || 0).toLocaleString()}</Text>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="p-4 rounded-xl border border-[var(--app-border)] bg-amber-500/5 dark:bg-amber-500/10">
                  <Text className="block text-[10px] font-bold text-amber-600 dark:text-amber-400 uppercase tracking-wider mb-1">Total Tokens</Text>
                  <Text className="text-lg font-black text-amber-600 dark:text-amber-400">{(selectedUser.total_tokens || 0).toLocaleString()}</Text>
                </div>
                <div className="p-4 rounded-xl border border-[var(--app-border)] bg-emerald-500/5 dark:bg-emerald-500/10">
                  <Text className="block text-[10px] font-bold text-emerald-600 dark:text-emerald-400 uppercase tracking-wider mb-1">Total Cost (USD)</Text>
                  <Text className="text-lg font-black text-emerald-600 dark:text-emerald-400">${(selectedUser.total_cost_usd || 0).toFixed(6)}</Text>
                </div>
              </div>
            </Flex>
          </div>
        )}
      </Modal>

      {/* Model Details Modal */}
      <Modal
        title={
          <Title level={4} className="!m-0 !font-extrabold text-[var(--app-text)] border-b border-[var(--app-border)] pb-3">
            Model Usage Details
          </Title>
        }
        open={modelModalVisible}
        onCancel={() => {
          setModelModalVisible(false);
          setSelectedModel(null);
        }}
        footer={[
          <Button
            key="close"
            type="primary"
            onClick={() => {
              setModelModalVisible(false);
              setSelectedModel(null);
            }}
            className="!bg-[#0fb5a1] hover:!bg-[#0d9e8c] rounded-xl font-bold px-6 h-10 border-0 cursor-pointer"
          >
            Close
          </Button>
        ]}
        centered
        width={500}
      >
        {selectedModel && (
          <div className="py-4">
            <Flex vertical gap={16}>
              <div className="p-4 rounded-2xl bg-[var(--app-surface-muted)] border border-[var(--app-border)]/60">
                <Text className="block text-[11px] font-bold text-[var(--app-text-soft)] uppercase tracking-wider mb-1">Model Name</Text>
                <Text className="text-sm font-semibold text-[var(--app-text)] break-all">{selectedModel.model_name || "default"}</Text>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="p-4 rounded-xl border border-[var(--app-border)]/40 bg-[var(--app-surface)]">
                  <Text className="block text-[10px] font-bold text-[var(--app-text-soft)] uppercase tracking-wider mb-1">Input Tokens</Text>
                  <Text className="text-base font-extrabold text-[var(--app-text)]">{(selectedModel.input_tokens || 0).toLocaleString()}</Text>
                </div>
                <div className="p-4 rounded-xl border border-[var(--app-border)]/40 bg-[var(--app-surface)]">
                  <Text className="block text-[10px] font-bold text-[var(--app-text-soft)] uppercase tracking-wider mb-1">Output Tokens</Text>
                  <Text className="text-base font-extrabold text-[var(--app-text)]">{(selectedModel.output_tokens || 0).toLocaleString()}</Text>
                </div>
                <div className="p-4 rounded-xl border border-[var(--app-border)]/40 bg-[var(--app-surface)]">
                  <Text className="block text-[10px] font-bold text-[var(--app-text-soft)] uppercase tracking-wider mb-1">Total Queries</Text>
                  <Text className="text-base font-extrabold text-[var(--app-text)]">{(selectedModel.request_count || 0).toLocaleString()}</Text>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="p-4 rounded-xl border border-[var(--app-border)] bg-amber-500/5 dark:bg-amber-500/10">
                  <Text className="block text-[10px] font-bold text-amber-600 dark:text-amber-400 uppercase tracking-wider mb-1">Total Tokens</Text>
                  <Text className="text-lg font-black text-amber-600 dark:text-amber-400">{(selectedModel.total_tokens || 0).toLocaleString()}</Text>
                </div>
                <div className="p-4 rounded-xl border border-[var(--app-border)] bg-emerald-500/5 dark:bg-emerald-500/10">
                  <Text className="block text-[10px] font-bold text-emerald-600 dark:text-emerald-400 uppercase tracking-wider mb-1">Total Cost (USD)</Text>
                  <Text className="text-lg font-black text-emerald-600 dark:text-emerald-400">${(selectedModel.total_cost_usd || 0).toFixed(6)}</Text>
                </div>
              </div>
            </Flex>
          </div>
        )}
      </Modal>

      <style jsx global>{`
        /* Hide 2nd month panel in RangePicker dropdown to show single month calendar */
        .single-panel-range-picker .ant-picker-panels > *:nth-child(2) {
          display: none !important;
        }
        .single-panel-range-picker .ant-picker-panels {
          flex-direction: column !important;
        }
        
        /* Custom tabs styling */
        .custom-tabs-container .ant-tabs-nav {
          margin-bottom: 16px !important;
          border-bottom: none !important;
        }
        .custom-tabs-container .ant-tabs-nav::before {
          border-bottom: none !important;
        }
        .custom-tabs-container .ant-tabs-tab {
          padding: 12px 16px !important;
          color: var(--app-text-soft) !important;
          transition: all 0.3s !important;
        }
        .custom-tabs-container .ant-tabs-tab-active .ant-tabs-tab-btn {
          color: #0fb5a1 !important;
        }
        .custom-tabs-container .ant-tabs-ink-bar {
          background: #0fb5a1 !important;
        }

        .custom-table .ant-table {
          background: transparent !important;
        }
        .custom-table .ant-table-thead > tr > th {
          background: var(--app-surface-muted) !important;
          color: var(--app-text) !important;
          font-weight: 800 !important;
          font-size: 11px !important;
          text-transform: uppercase !important;
          letter-spacing: 0.05em !important;
          border-bottom: 1px solid var(--app-border) !important;
          white-space: nowrap !important;
        }
        .custom-table .ant-table-tbody > tr > td {
          border-bottom: 1px solid var(--app-border) !important;
          padding: 14px 16px !important;
        }
        .custom-table .ant-table-tbody > tr:hover > td {
          background: var(--app-surface-muted) !important;
        }
        .custom-table .ant-table-pagination.ant-pagination {
          padding: 16px 24px !important;
          margin: 0 !important;
          border-top: 1px solid var(--app-border) !important;
        }
        @media (max-width: 640px) {
          .custom-table .ant-table-pagination.ant-pagination {
            padding: 12px 16px !important;
            justify-content: center !important;
            flex-wrap: wrap !important;
            gap: 12px !important;
          }
        }
      `}</style>
    </div>
  );
}
