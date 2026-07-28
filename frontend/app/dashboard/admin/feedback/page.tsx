"use client";

import { useEffect, useState, useMemo, useRef } from "react";
import { Typography, Button, Badge, Row, Col, Spin } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { ThumbsUp, ThumbsDown, BarChart3, HelpCircle, CheckCircle, AlertTriangle, XOctagon } from "lucide-react";
import useAxios from "@/app/hooks/useAxios";

const { Title, Text } = Typography;

// Exact mock data representing the user's expected payload
const MOCK_FEEDBACK_DATA = {
  success: true,
  data: [
    {
      feedback_type: "thumbs_up",
      reason: "Correct response",
      count: 7,
      percentage: 58.33,
    },
    {
      feedback_type: "thumbs_down",
      reason: "Irrelevant Answer",
      count: 2,
      percentage: 16.67,
    },
    {
      feedback_type: "thumbs_down",
      reason: "Missing Information",
      count: 2,
      percentage: 16.67,
    },
    {
      feedback_type: "thumbs_down",
      reason: "Hallucination",
      count: 1,
      percentage: 8.33,
    },
  ],
  meta: {
    total_feedback_count: 12,
  },
};

// Reusable Count-Up Animation Component triggered on scroll/view
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

// Reusable Circular Progress Ring component triggered on scroll/view
interface AnimatedProgressCircleProps {
  percentage: number;
  colorClass: string;
  glowClass: string;
  trailColorClass: string;
  icon: React.ReactNode;
}

function AnimatedProgressCircle({
  percentage,
  colorClass,
  glowClass,
  trailColorClass,
  icon,
}: AnimatedProgressCircleProps) {
  const [animatedVal, setAnimatedVal] = useState(0);
  const [isInView, setIsInView] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  
  const radius = 50;
  const strokeWidth = 9;
  const circumference = 2 * Math.PI * radius;
  const [offset, setOffset] = useState(circumference);

  useEffect(() => {
    const currentRef = containerRef.current;
    if (!currentRef) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsInView(true);
          observer.unobserve(currentRef);
        }
      },
      { threshold: 0.1 }
    );

    observer.observe(currentRef);

    return () => {
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    if (!isInView) return;

    // 1. Animate Circle Ring
    const targetOffset = circumference - (percentage / 100) * circumference;
    const ringTimer = setTimeout(() => {
      setOffset(targetOffset);
    }, 100);

    // 2. Animate Percentage text counting up using performance timestamp
    let startTimestamp: number | null = null;
    const duration = 1000; // 1s animation duration

    const step = (timestamp: number) => {
      if (!startTimestamp) startTimestamp = timestamp;
      const progress = timestamp - startTimestamp;
      const progressPercent = Math.min(progress / duration, 1);
      setAnimatedVal(progressPercent * percentage);

      if (progress < duration) {
        window.requestAnimationFrame(step);
      }
    };

    const animFrame = window.requestAnimationFrame(step);

    return () => {
      clearTimeout(ringTimer);
      window.cancelAnimationFrame(animFrame);
    };
  }, [percentage, circumference, isInView]);

  return (
    <div ref={containerRef} className="relative w-36 h-36 flex items-center justify-center select-none">
      {/* Background radial glow */}
      <div className={`absolute w-20 h-20 rounded-full blur-[25px] opacity-20 ${glowClass} transition-all duration-1000`} />
      
      <svg className="w-full h-full transform -rotate-90">
        {/* Background circle */}
        <circle
          cx="72"
          cy="72"
          r={radius}
          className={`${trailColorClass} fill-none`}
          strokeWidth={strokeWidth}
        />
        {/* Foreground animated circle */}
        <circle
          cx="72"
          cy="72"
          r={radius}
          className={`${colorClass} fill-none`}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{
            transition: "stroke-dashoffset 1.2s cubic-bezier(0.25, 1, 0.5, 1)",
          }}
        />
      </svg>
      
      {/* Absolute Center Content */}
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center mt-1">
        <div className="text-[var(--app-text-soft)] mb-0.5 transform scale-90 opacity-80">
          {icon}
        </div>
        <span className="text-xl font-black tracking-tight text-[var(--app-text)] leading-none">
          {animatedVal.toFixed(1)}%
        </span>
      </div>
    </div>
  );
}

export default function AdminFeedbackPage() {
  // Call API using base axios wrapper hooks
  const [getFeedback, rawFeedbackData, loadingFeedback] = useAxios({
    endpoint: "FEEDBACK_REASONS",
    initialLoading: true,
  });

  const [refreshKey, setRefreshKey] = useState(0);

  // Load feedback reasons on mount or refresh
  useEffect(() => {
    getFeedback();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  // Use API response or fallback to Mock Data if API fails/is empty
  const feedbackPayload = useMemo(() => {
    if (rawFeedbackData && rawFeedbackData.success && Array.isArray(rawFeedbackData.data) && rawFeedbackData.data.length > 0) {
      return rawFeedbackData;
    }
    return MOCK_FEEDBACK_DATA;
  }, [rawFeedbackData]);

  // Derive list items and grouped components
  const items = useMemo(() => feedbackPayload.data || [], [feedbackPayload]);
  
  const totalFeedbackCount = useMemo(() => {
    return feedbackPayload.meta?.total_feedback_count ?? items.reduce((acc: number, curr: any) => acc + curr.count, 0);
  }, [feedbackPayload, items]);

  const thumbsUpItems = useMemo(() => {
    return items.filter((item: any) => item.feedback_type === "thumbs_up");
  }, [items]);

  const thumbsDownItems = useMemo(() => {
    return items.filter((item: any) => item.feedback_type === "thumbs_down");
  }, [items]);

  // Compute aggregated stats
  const totalThumbsUpCount = useMemo(() => {
    return thumbsUpItems.reduce((acc: number, curr: any) => acc + curr.count, 0);
  }, [thumbsUpItems]);

  const totalThumbsDownCount = useMemo(() => {
    return thumbsDownItems.reduce((acc: number, curr: any) => acc + curr.count, 0);
  }, [thumbsDownItems]);

  const thumbsUpOverallPercentage = useMemo(() => {
    return totalFeedbackCount > 0 ? (totalThumbsUpCount / totalFeedbackCount) * 100 : 0;
  }, [totalThumbsUpCount, totalFeedbackCount]);

  const thumbsDownOverallPercentage = useMemo(() => {
    return totalFeedbackCount > 0 ? (totalThumbsDownCount / totalFeedbackCount) * 100 : 0;
  }, [totalThumbsDownCount, totalFeedbackCount]);

  const handleRefresh = () => {
    setRefreshKey((prev) => prev + 1);
  };

  // Maps reason to appropriate Lucide Icon
  const getReasonIcon = (reason: string, feedbackType: string) => {
    const text = reason.toLowerCase();
    if (feedbackType === "thumbs_up") {
      return <CheckCircle size={18} className="text-emerald-500" />;
    }
    if (text.includes("irrelevant")) {
      return <HelpCircle size={18} className="text-violet-500" />;
    }
    if (text.includes("missing")) {
      return <AlertTriangle size={18} className="text-orange-500" />;
    }
    if (text.includes("hallucination") || text.includes("wrong")) {
      return <XOctagon size={18} className="text-rose-500" />;
    }
    return <AlertTriangle size={18} className="text-amber-500" />;
  };

  return (
    <div className="w-full max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8 pb-24 relative min-h-screen">
      {/* 1. Header Block */}
      <div className="mb-10">
        <Row justify="space-between" align="middle" gutter={[16, 24]}>
          <Col xs={24} md={18}>
            <div className="flex items-center gap-4">
              <Title level={1} className="!m-0 !font-extrabold !text-3xl sm:!text-4xl tracking-tight text-[var(--app-text)]">
                Feedback Analytics
              </Title>
              <Badge
                count={<span className="px-2 text-xs font-black text-[#0fb5a1]"><AnimatedCounter value={totalFeedbackCount} /> responses</span>}
                style={{
                  backgroundColor: "var(--app-active-bg)",
                  borderColor: "transparent",
                  height: 28,
                  lineHeight: "28px",
                  borderRadius: 14,
                }}
                className="mt-1"
              />
            </div>
            <Text className="block mt-2 text-sm sm:text-base text-[var(--app-text-soft)] font-medium">
              Analyze chatbot feedback reasons, user satisfaction rates, and error patterns.
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
          {/* 2. Top Aggregated Summary Row */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* Card 1: Total Feedbacks */}
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

            {/* Card 2: Thumbs Up Overall */}
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

            {/* Card 3: Thumbs Down Overall */}
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

          {/* 3. Detailed Reasons Columns */}
          <div className="space-y-12">
            {/* Thumbs Up Reasons Section */}
            {thumbsUpItems.length > 0 && (
              <div className="space-y-6">
                <div className="flex items-center gap-3 border-b border-[var(--app-border)]/40 pb-3">
                  <div className="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-500 flex items-center justify-center">
                    <ThumbsUp size={16} />
                  </div>
                  <h2 className="text-lg font-black text-[var(--app-text)] uppercase tracking-wider">
                    Positive Feedbacks (Thumbs Up)
                  </h2>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-6">
                  {thumbsUpItems.map((item: any, idx: number) => (
                    <div
                      key={`up-${idx}`}
                      className="bg-[var(--app-surface)] border border-[var(--app-border)]/60 rounded-3xl p-6 flex flex-col items-center shadow-sm hover:shadow-lg hover:-translate-y-1 transition-all duration-300 group"
                    >
                      {/* Animated circular progress using Emerald Theme */}
                      <AnimatedProgressCircle
                        percentage={item.percentage}
                        colorClass="text-emerald-500 stroke-emerald-500"
                        glowClass="bg-emerald-500"
                        trailColorClass="stroke-emerald-100 dark:stroke-emerald-950/40"
                        icon={getReasonIcon(item.reason, "thumbs_up")}
                      />
                      {/* Label & Details below */}
                      <div className="text-center mt-6 w-full">
                        <h4 className="text-[var(--app-text)] font-extrabold text-sm sm:text-base leading-tight truncate px-1" title={item.reason}>
                          {item.reason}
                        </h4>
                        <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 dark:text-emerald-400 text-xs font-bold rounded-full border border-emerald-100 dark:border-emerald-900/30 mt-2">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                          <span>Count: <AnimatedCounter value={item.count} /></span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Thumbs Down Reasons Section */}
            {thumbsDownItems.length > 0 && (
              <div className="space-y-6">
                <div className="flex items-center gap-3 border-b border-[var(--app-border)]/40 pb-3">
                  <div className="w-8 h-8 rounded-lg bg-violet-500/10 text-violet-50 flex items-center justify-center">
                    <ThumbsDown size={16} />
                  </div>
                  <h2 className="text-lg font-black text-[var(--app-text)] uppercase tracking-wider">
                    Issue Details (Thumbs Down)
                  </h2>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-6">
                  {thumbsDownItems.map((item: any, idx: number) => (
                    <div
                      key={`down-${idx}`}
                      className="bg-[var(--app-surface)] border border-[var(--app-border)]/60 rounded-3xl p-6 flex flex-col items-center shadow-sm hover:shadow-lg hover:-translate-y-1 transition-all duration-300 group"
                    >
                      {/* Animated circular progress using user's image-style Violet/Purple Theme */}
                      <AnimatedProgressCircle
                        percentage={item.percentage}
                        colorClass="text-violet-500 stroke-violet-500"
                        glowClass="bg-violet-500"
                        trailColorClass="stroke-violet-100 dark:stroke-violet-950/40"
                        icon={getReasonIcon(item.reason, "thumbs_down")}
                      />
                      {/* Label & Details below */}
                      <div className="text-center mt-6 w-full">
                        <h4 className="text-[var(--app-text)] font-extrabold text-sm sm:text-base leading-tight truncate px-1" title={item.reason}>
                          {item.reason}
                        </h4>
                        <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-violet-50 dark:bg-violet-950/20 text-violet-600 dark:text-violet-400 text-xs font-bold rounded-full border border-violet-100 dark:border-violet-900/30 mt-2">
                          <span className="w-1.5 h-1.5 rounded-full bg-violet-500" />
                          <span>Count: <AnimatedCounter value={item.count} /></span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
