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
} from "antd";
import {
  SearchOutlined,
  ReloadOutlined,
  DollarOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import useAxios from "@/app/hooks/useAxios";

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

interface UserCostRecord {
  user_id?: string;
  user_email?: string;
  total_tokens?: number;
  total_cost_usd?: number;
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

  // Parse raw response safely (handles array, res.data, res.data.users, etc.)
  const costRecords = useMemo<UserCostRecord[]>(() => {
    if (!rawData) return [];
    if (Array.isArray(rawData)) return rawData;

    const payload = rawData as any;
    if (Array.isArray(payload?.data)) return payload.data;
    if (Array.isArray(payload?.users)) return payload.users;
    if (Array.isArray(payload?.results)) return payload.results;
    if (Array.isArray(payload?.costs)) return payload.costs;

    return [];
  }, [rawData]);

  // Apply client-side search query filter
  const filteredRecords = useMemo(() => {
    if (!searchQuery.trim()) return costRecords;
    const query = searchQuery.toLowerCase().trim();
    return costRecords.filter((item) => {
      const email = (item.user_email || "").toLowerCase();
      const id = (item.user_id || "").toLowerCase();
      return email.includes(query) || id.includes(query);
    });
  }, [costRecords, searchQuery]);

  // Calculated Summary Statistics
  const totalTokensSum = useMemo(() => {
    return filteredRecords.reduce((acc, curr) => acc + (curr.total_tokens || 0), 0);
  }, [filteredRecords]);

  const totalCostSum = useMemo(() => {
    return filteredRecords.reduce((acc, curr) => acc + (curr.total_cost_usd || 0), 0);
  }, [filteredRecords]);

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

  // Ant Design Table Columns with Mobile Responsiveness
  const columns = [
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
      render: (email: string, record: UserCostRecord) => (
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
      sorter: (a: UserCostRecord, b: UserCostRecord) => (a.total_tokens || 0) - (b.total_tokens || 0),
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
      sorter: (a: UserCostRecord, b: UserCostRecord) => (a.total_cost_usd || 0) - (b.total_cost_usd || 0),
      render: (cost?: number) => (
        <Tag
          color="emerald"
          className="px-3 py-1 text-xs font-bold rounded-lg border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 whitespace-nowrap"
        >
          ${(cost || 0).toFixed(4)}
        </Tag>
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
              Track token consumption, query volume, and calculated USD expenses per user.
            </Text>
          </div>
          {/* Custom Styled Refresh Button matching Feedback page design */}
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
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={8}>
            <Card className="bg-[var(--app-surface)] border-[var(--app-border)]/60 shadow-sm rounded-2xl">
              <Statistic
                title={<Text className="text-xs font-bold text-[var(--app-text-soft)] uppercase tracking-wider">Total Active Users</Text>}
                valueRender={() => <AnimatedCount value={filteredRecords.length} />}
                prefix={<UserOutlined className="text-[#0fb5a1] mr-2" />}
                valueStyle={{ color: "var(--app-text)", fontWeight: 800, fontSize: "1.5rem" }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={8}>
            <Card className="bg-[var(--app-surface)] border-[var(--app-border)]/60 shadow-sm rounded-2xl">
              <Statistic
                title={<Text className="text-xs font-bold text-[var(--app-text-soft)] uppercase tracking-wider">Total Tokens Consumed</Text>}
                valueRender={() => <AnimatedCount value={totalTokensSum} />}
                prefix={<ThunderboltOutlined className="text-amber-500 mr-2" />}
                valueStyle={{ color: "var(--app-text)", fontWeight: 800, fontSize: "1.5rem" }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={8}>
            <Card className="bg-[var(--app-surface)] border-[var(--app-border)]/60 shadow-sm rounded-2xl">
              <Statistic
                title={<Text className="text-xs font-bold text-[var(--app-text-soft)] uppercase tracking-wider">Total Expense (USD)</Text>}
                valueRender={() => <AnimatedCount value={totalCostSum} precision={4} isCurrency />}
                prefix={<DollarOutlined className="text-emerald-500 mr-2" />}
                valueStyle={{ color: "var(--app-text)", fontWeight: 800, fontSize: "1.5rem" }}
              />
            </Card>
          </Col>
        </Row>

        {/* Filter Controls Bar */}
        <Card className="bg-[var(--app-surface)] border-[var(--app-border)] shadow-sm rounded-2xl">
          <Row gutter={[16, 16]} align="bottom">
            <Col xs={24} md={9}>
              <Flex vertical gap={6}>
                <Text className="text-xs font-bold text-[var(--app-text-soft)] uppercase tracking-wider">
                  Search User Email / ID
                </Text>
                <Input
                  size="large"
                  placeholder="Search by user_email..."
                  prefix={<SearchOutlined className="text-[var(--app-text-soft)] mr-1" />}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  allowClear
                  className="rounded-xl border-[var(--app-border)]"
                />
              </Flex>
            </Col>

            <Col xs={24} md={9}>
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

            <Col xs={24} md={6}>
              <Flex gap={10} className="w-full">
                <Button
                  type="primary"
                  size="large"
                  icon={<SearchOutlined />}
                  onClick={handleSearchClick}
                  className="flex-1 rounded-xl !bg-[#0fb5a1] hover:!bg-[#0d9e8c] font-bold shadow-md shadow-teal-900/10 border-0"
                >
                  Search
                </Button>
                <Tooltip title="Reset filters">
                  <Button
                    size="large"
                    onClick={handleResetFilters}
                    className="rounded-xl border-[var(--app-border)] text-[var(--app-text-soft)] hover:text-[var(--app-text)] font-semibold px-4"
                  >
                    Reset
                  </Button>
                </Tooltip>
              </Flex>
            </Col>
          </Row>
        </Card>

        {/* Responsive Data Table */}
        <Card
          className="bg-[var(--app-surface)] border-[var(--app-border)] shadow-sm rounded-2xl overflow-hidden"
          styles={{ body: { padding: 0 } }}
        >
          <Spin spinning={loading}>
            <div className="w-full overflow-x-auto custom-scrollbar">
              <Table
                dataSource={filteredRecords}
                columns={columns}
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
                  emptyText: <Empty description="No Token Usage Records Found" />,
                }}
                className="custom-table"
              />
            </div>
          </Spin>
        </Card>
      </Flex>

      <style jsx global>{`
        /* Hide 2nd month panel in RangePicker dropdown to show single month calendar */
        .single-panel-range-picker .ant-picker-panels > *:nth-child(2) {
          display: none !important;
        }
        .single-panel-range-picker .ant-picker-panels {
          flex-direction: column !important;
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
        @media (max-width: 640px) {
          .custom-table .ant-pagination {
            flex-wrap: wrap !important;
            justify-content: center !important;
            gap: 8px !important;
            padding: 12px 8px !important;
          }
        }
      `}</style>
    </div>
  );
}
