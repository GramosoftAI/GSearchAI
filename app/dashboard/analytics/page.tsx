"use client";

import { useEffect, useState, useMemo } from 'react';
import { Card, Col, Row, Typography,Flex, Spin, Empty,List } from 'antd';
import { MessageSquare, Target, HelpCircle, TrendingUp, PlusCircle, ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer } from "recharts";
import useAxios from '../../hooks/useAxios';

const { Title, Text } = Typography;

interface AnalyticsData {
  metrics: {
    total_queries: { value: string; change: string; is_positive: boolean };
    accuracy: { value: string; change: string; is_positive: boolean };
    unanswered: { value: string; change: string; is_positive: boolean };
    avg_confidence: { value: string; change: string; is_positive: boolean };
  };
  query_volume: { day: string; value: number }[];
  unanswered_questions: string[];
}

function MetricCard({ change, icon: Icon, isPositive, value, label }: {
  change: string;
  icon: any;
  isPositive: boolean;
  value: string;
  label: string;
}) {
  return (
    <Card 
      bordered
      className="relative overflow-hidden transition-all duration-300 hover:-translate-y-1 hover:shadow-md bg-[var(--app-surface)] border-[var(--app-border)]"
      bodyStyle={{ padding: '24px' }}
    >
      {/* Decorative Subtle Radial Glow */}
      <div 
        className={`absolute -top-12 -right-12 w-32 h-32 rounded-full blur-3xl opacity-5 pointer-events-none transition-opacity duration-500 group-hover:opacity-10 ${
          isPositive ? 'bg-emerald-500' : 'bg-rose-500'
        }`} 
      />
      
      <Flex vertical gap={16}>
        <Flex justify="space-between" align="start">
          <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-[#0fb5a1]/5 text-[#0fb5a1]">
            <Icon size={22} strokeWidth={1.75} />
          </div>
          <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold ${
            isPositive ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'
          }`}>
            {isPositive ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
            {change}
          </span>
        </Flex>
        
        <div>
          <Text className="block text-xs font-bold tracking-wider uppercase text-[var(--app-text-soft)] mb-1">
            {label}
          </Text>
          <Title level={2} className="!m-0 !font-extrabold tracking-tight text-[var(--app-text)]">
            {value}
          </Title>
        </div>
      </Flex>
    </Card>
  );
}

function QueryVolumeChart({ data }: { data: { day: string; value: number }[] }) {
  return (
    <Card bordered className="bg-[var(--app-surface)] border-[var(--app-border)] shadow-sm">
      <Flex vertical gap={24}>
        <Flex justify="space-between" align="center" wrap="wrap" className="gap-4">
          <div>
            <Title level={4} className="!m-0 !font-bold tracking-tight text-[var(--app-text)]">
              Intelligence Flow
            </Title>
            <Text className="block mt-0.5 text-xs text-[var(--app-text-soft)]">
              Daily query distribution and network interactions over time
            </Text>
          </div>
          <div className="px-3 py-1.5 text-xs font-bold text-[#0fb5a1] bg-[#0fb5a1]/5 rounded-lg border border-[#0fb5a1]/10 whitespace-nowrap">
            Last 30 Days
          </div>
        </Flex>

        <div className="w-full h-[360px] min-h-[300px]">
          {data && data.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data} margin={{ top: 10, right: 5, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#0fb5a1" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="#0fb5a1" stopOpacity={0.00} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--app-border)" opacity={0.6} />
                <XAxis 
                  dataKey="day" 
                  axisLine={false} 
                  tickLine={false} 
                  tick={{ fill: "var(--app-text-soft)", fontSize: 11, fontWeight: 500 }} 
                  dy={10}
                />
                <YAxis 
                  axisLine={false} 
                  tickLine={false} 
                  tick={{ fill: "var(--app-text-soft)", fontSize: 11, fontWeight: 500 }} 
                  dx={-5}
                />
                <RechartsTooltip
                  cursor={{ stroke: '#0fb5a1', strokeWidth: 1, strokeDasharray: '4 4' }}
                  contentStyle={{ 
                    backgroundColor: "var(--app-surface)", 
                    border: "1px solid var(--app-border)", 
                    borderRadius: "12px",
                    boxShadow: "0 4px 20px rgba(0,0,0,0.05)",
                    padding: "10px 14px"
                  }}
                  itemStyle={{ color: "var(--app-text)", fontWeight: 600, fontSize: "14px" }}
                  labelStyle={{ color: "var(--app-text-soft)", fontWeight: 500, fontSize: "11px", marginBottom: "4px" }}
                />
                <Area 
                  type="monotone" 
                  dataKey="value" 
                  stroke="#0fb5a1" 
                  strokeWidth={2.5} 
                  fillOpacity={1} 
                  fill="url(#chartGradient)" 
                  animationDuration={1000} 
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <Flex vertical align="center" justify="center" className="h-full py-12">
              <TrendingUp size={40} className="text-[var(--app-text-soft)] opacity-40 mb-3" />
              <Text className="text-sm font-medium text-[var(--app-text-soft)]">No telemetry data available</Text>
            </Flex>
          )}
        </div>
      </Flex>
    </Card>
  );
}

function UnansweredQuestions({ questions }: { questions: string[] }) {
  return (
    <Card bordered className="bg-[var(--app-surface)] border-[var(--app-border)] shadow-sm">
      <Flex vertical gap={24}>
        <Flex align="center" gap={16}>
          <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-[#0fb5a1]/5 text-[#0fb5a1]">
            <HelpCircle size={22} strokeWidth={1.75} />
          </div>
          <div>
            <Title level={4} className="!m-0 !font-bold tracking-tight text-[var(--app-text)]">
              Knowledge Gaps
            </Title>
            <Text className="block mt-0.5 text-xs text-[var(--app-text-soft)]">
              Review and resolve conversational strings that missed context matches
            </Text>
          </div>
        </Flex>

        {questions.length > 0 ? (
          <List
            className="border-none"
            dataSource={questions}
            renderItem={(q, i) => (
              <div
                key={i}
                className="group flex items-center justify-between p-4 mb-2.5 last:mb-0 rounded-xl bg-[var(--app-surface-muted)] hover:bg-[#0fb5a1] border border-[var(--app-border)] hover:border-[#0fb5a1] transition-all duration-200 cursor-pointer"
              >
                <Text className="text-sm font-medium text-[var(--app-text)] group-hover:text-white transition-colors duration-200 pr-4 truncate">
                  {q}
                </Text>
                <Flex align="center" gap={6} className="text-xs font-semibold text-[#0fb5a1] group-hover:text-white shrink-0 opacity-80 group-hover:opacity-100 transition-all duration-200">
                  <span className="hidden sm:inline">Sync Knowledge</span>
                  <PlusCircle size={16} />
                </Flex>
              </div>
            )}
          />
        ) : (
          <Flex vertical align="center" justify="center" className="py-10">
            <Empty 
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={<Text className="text-sm text-[var(--app-text-soft)] font-medium">Cognitive alignment complete. No gaps found.</Text>} 
            />
          </Flex>
        )}
      </Flex>
    </Card>
  );
}

export default function AnalyticsPage() {
  const [isClient, setIsClient] = useState(false);
  const [getAnalytics, response, loading] = useAxios<AnalyticsData>({ endpoint: "ANALYTICS_DASHBOARD" });
  const [userName, setUserName] = useState("");

  useEffect(() => {
    setIsClient(true);
    getAnalytics();
    const storedName = localStorage.getItem("userName");
    if (storedName) {
      setUserName(storedName.split(' ')[0]);
    }
     // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stats = useMemo(() => {
    if (!response) return [];
    const root = (response as any).data || response;
    
    return [
      { label: "Total Volume", value: String(root.total_queries ?? 0), change: "12%", icon: MessageSquare, isPositive: true },
      { label: "Precision Score", value: `${root.accuracy_percent ?? 0}%`, change: "4%", icon: Target, isPositive: true },
      { label: "Cognitive Gaps", value: String(root.unanswered_count ?? 0), change: "2%", icon: HelpCircle, isPositive: false },
      { label: "Neural Confidence", value: `${Math.round((root.avg_confidence ?? 0) * 100)}%`, change: "1.2%", icon: TrendingUp, isPositive: true },
    ];
  }, [response]);

  const rootData = response ? ((response as any).data || response) : null;
  const chartData = (rootData?.trend_queries || []).map((item: any) => ({
    day: item.date || item.day || "Today",
    value: item.count || item.value || 0
  }));

  return (
    <div className="w-full max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8 pb-24 relative min-h-screen">
      <Flex vertical gap={40}>
        {/* Header Block */}
        <div>
          <Title level={1} className="!m-0 !font-extrabold !text-3xl sm:!text-4xl tracking-tight text-[var(--app-text)]">
            {userName ? `${userName}'s` : "Intelligence"} Analytics
          </Title>
          <Text className="block mt-2 text-sm sm:text-base text-[var(--app-text-soft)] font-medium">
            Monitor real-time system executions, structural processing precision, and vector engine alignment.
          </Text>
        </div>

        {/* Responsive Performance Metrics Grid */}
        <Row gutter={[20, 20]}>
          {(stats.length > 0 ? stats : [1, 2, 3, 4]).map((stat: any, i) => (
            <Col key={i} xs={24} sm={12} lg={6}>
              {stats.length > 0 ? (
                <MetricCard {...stat} />
              ) : (
                <Card loading className="h-36 rounded-2xl bg-[var(--var-surface-muted)]" />
              )}
            </Col>
          ))}
        </Row>

        {/* Content Layout Modules */}
        {isClient && (
          <Row gutter={[24, 24]}>
            <Col xs={24} xl={24}>
              {response ? (
                <QueryVolumeChart data={chartData} />
              ) : (
                <Card loading className="h-[440px] rounded-2xl" />
              )}
            </Col>
            <Col xs={24} xl={24}>
              {response ? (
                <UnansweredQuestions questions={rootData?.unanswered_questions || []} />
              ) : (
                <Card loading className="h-[440px] rounded-2xl" />
              )}
            </Col>
          </Row>
        )}
      </Flex>

      {/* Modern Blur Loading Overlay */}
      {loading && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-[var(--app-surface)]/60 backdrop-blur-md transition-all duration-300">
          <Flex vertical align="center" gap={16} className="p-8 rounded-2xl bg-[var(--app-surface)] border border-[var(--app-border)] shadow-xl max-w-xs text-center">
            <Spin size="large" className="text-[#0fb5a1]" />
            <Text className="text-xs font-bold uppercase tracking-widest text-[#0fb5a1]">
              Syncing Telemetry System...
            </Text>
          </Flex>
        </div>
      )}
    </div>
  );
}
