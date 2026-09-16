"use client";

import React, { useEffect, useState } from "react";
import { Card, Typography, Button, Tag, Space, Progress } from "antd";
import {
  CheckCircleFilled,
  LoadingOutlined,
  CloseCircleFilled,
  StopOutlined,
  ThunderboltFilled,
  ClockCircleOutlined,
} from "@ant-design/icons";
import { DatabaseStreamEvent } from "../services/databaseStreamClient";

const { Text, Title } = Typography;

export type StageState = "pending" | "in_progress" | "completed" | "error" | "cancelled";

export interface StageInfo {
  id: string;
  label: string;
  description: string;
  state: StageState;
  latencyMs?: number;
  meta?: Record<string, any>;
}

interface DatabasePipelineProgressProps {
  events: DatabaseStreamEvent[];
  isStreaming: boolean;
  onCancel: () => void;
  error?: string | null;
  cancelled?: boolean;
}

const INITIAL_STAGES: StageInfo[] = [
  { id: "query", label: "Query Accepted", description: "Request validated and queued", state: "pending" },
  { id: "retrieval", label: "Schema Retrieval", description: "Semantic sub-schema and join discovery", state: "pending" },
  { id: "planning", label: "Query Planning", description: "QueryPlanIR intent and projection compilation", state: "pending" },
  { id: "sql_gen", label: "SQL Compilation", description: "Deterministic compiler or LLM repair", state: "pending" },
  { id: "validation", label: "AST Security Validation", description: "Read-only AST boundaries and policy check", state: "pending" },
  { id: "authorization", label: "Tenant Authorization", description: "Multi-tenant barrier verification", state: "pending" },
  { id: "execution", label: "Database Execution", description: "Isolated read-only transaction execution", state: "pending" },
  { id: "synthesis", label: "Answer Synthesis", description: "Grounded natural language formatting", state: "pending" },
  { id: "grounding", label: "Grounding Verification", description: "Anti-hallucination fact verification gate", state: "pending" },
];

export const DatabasePipelineProgress: React.FC<DatabasePipelineProgressProps> = ({
  events,
  isStreaming,
  onCancel,
  error,
  cancelled,
}) => {
  const [stages, setStages] = useState<StageInfo[]>(INITIAL_STAGES);
  const [isDeterministic, setIsDeterministic] = useState<boolean>(false);
  const [elapsedMs, setElapsedMs] = useState<number>(0);

  // Update stages based on incoming stream events
  useEffect(() => {
    const updated = INITIAL_STAGES.map((st) => ({ ...st }));
    let deterministicMode = false;

    for (const ev of events) {
      const { event, stage, status, elapsed_stage_ms, data } = ev;

      if (event === "query.accepted") {
        updated[0].state = "completed";
        updated[0].latencyMs = elapsed_stage_ms;
        updated[1].state = "in_progress";
      } else if (event === "retrieval.started") {
        updated[1].state = "in_progress";
      } else if (event === "retrieval.completed") {
        updated[1].state = "completed";
        updated[1].latencyMs = elapsed_stage_ms || data?.latency_ms;
        updated[2].state = "in_progress";
      } else if (event === "planning.started") {
        updated[2].state = "in_progress";
      } else if (event === "planning.completed") {
        updated[2].state = "completed";
        updated[2].latencyMs = elapsed_stage_ms || data?.latency_ms;
        updated[3].state = "in_progress";
      } else if (event === "sql_generation.started") {
        updated[3].state = "in_progress";
      } else if (event === "sql_generation.completed") {
        updated[3].state = "completed";
        updated[3].latencyMs = elapsed_stage_ms || data?.latency_ms;
        if (data?.deterministic_sql_compilation || data?.sql_generation_mode === "deterministic") {
          deterministicMode = true;
        }
        updated[4].state = "in_progress";
      } else if (event === "validation.started") {
        updated[4].state = "in_progress";
      } else if (event === "validation.completed") {
        updated[4].state = "completed";
        updated[4].latencyMs = elapsed_stage_ms;
        updated[5].state = "in_progress";
      } else if (event === "authorization.started") {
        updated[5].state = "in_progress";
      } else if (event === "authorization.completed") {
        updated[5].state = "completed";
        updated[5].latencyMs = elapsed_stage_ms;
        updated[6].state = "in_progress";
      } else if (event === "execution.started") {
        updated[6].state = "in_progress";
      } else if (event === "execution.completed") {
        updated[6].state = "completed";
        updated[6].latencyMs = elapsed_stage_ms || data?.execution_time_ms;
        updated[7].state = "in_progress";
      } else if (event === "synthesis.started") {
        updated[7].state = "in_progress";
      } else if (event === "synthesis.completed") {
        updated[7].state = "completed";
        updated[7].latencyMs = elapsed_stage_ms || data?.latency_ms;
        updated[8].state = "in_progress";
      } else if (event === "grounding.started") {
        updated[8].state = "in_progress";
      } else if (event === "grounding.completed" || event === "answer.completed") {
        updated[8].state = "completed";
        updated[8].latencyMs = elapsed_stage_ms;
      } else if (event === "query.error") {
        // Mark currently in_progress stage as error
        for (const s of updated) {
          if (s.state === "in_progress") {
            s.state = "error";
          }
        }
      } else if (event === "query.cancelled") {
        // Mark currently in_progress stage as cancelled
        for (const s of updated) {
          if (s.state === "in_progress") {
            s.state = "cancelled";
          }
        }
      }
    }

    if (cancelled) {
      for (const s of updated) {
        if (s.state === "in_progress") {
          s.state = "cancelled";
        }
      }
    }

    setStages(updated);
    setIsDeterministic(deterministicMode);

    if (events.length > 0) {
      setElapsedMs(events[events.length - 1].elapsed_total_ms);
    }
  }, [events, cancelled]);

  // Live timer tick while streaming
  useEffect(() => {
    if (!isStreaming) return;
    const start = Date.now();
    const timer = setInterval(() => {
      setElapsedMs(Date.now() - start);
    }, 50);
    return () => clearInterval(timer);
  }, [isStreaming]);

  const completedCount = stages.filter((s) => s.state === "completed").length;
  const progressPercent = Math.round((completedCount / stages.length) * 100);

  return (
    <Card
      style={{
        background: "rgba(15, 23, 42, 0.75)",
        backdropFilter: "blur(12px)",
        borderColor: "rgba(56, 189, 248, 0.2)",
        borderRadius: 14,
        boxShadow: "0 10px 30px -10px rgba(0,0,0,0.5)",
      }}
      styles={{ body: { padding: "20px 24px" } }}
    >
      {/* Header with Title, Timer, and Cancel Button */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-gray-800 pb-3">
        <div className="flex items-center gap-3">
          <Title level={5} style={{ margin: 0, color: "#f8fafc" }}>
            Real-Time Pipeline Execution
          </Title>
          {isDeterministic && (
            <Tag
              color="cyan"
              icon={<ThunderboltFilled />}
              style={{ borderRadius: 12, padding: "2px 10px", fontWeight: 600 }}
            >
              Deterministic Fast-Path (0 SQL LLM Calls)
            </Tag>
          )}
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1 text-xs text-gray-400 font-mono">
            <ClockCircleOutlined />
            <span>{elapsedMs.toFixed(0)} ms</span>
          </div>

          {isStreaming && (
            <Button
              danger
              size="small"
              icon={<StopOutlined />}
              onClick={onCancel}
              style={{
                borderRadius: 6,
                fontWeight: 600,
                fontSize: 12,
              }}
            >
              Cancel Query
            </Button>
          )}
        </div>
      </div>

      {/* Progress Bar */}
      <div className="mt-3">
        <Progress
          percent={progressPercent}
          showInfo={false}
          strokeColor={{
            "0%": "#06b6d4",
            "100%": isDeterministic ? "#10b981" : "#8b5cf6",
          }}
          size="small"
        />
      </div>

      {/* Pipeline Stages Vertical Stepper */}
      <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3">
        {stages.map((stage) => {
          let statusIcon = <div className="w-3.5 h-3.5 rounded-full border border-gray-600 bg-gray-900" />;
          let textColor = "text-gray-400";
          let badgeBorder = "border-gray-800 bg-gray-900/40";

          if (stage.state === "in_progress") {
            statusIcon = <LoadingOutlined style={{ color: "#38bdf8", fontSize: 14 }} />;
            textColor = "text-cyan-300 font-medium";
            badgeBorder = "border-cyan-500/40 bg-cyan-950/20";
          } else if (stage.state === "completed") {
            statusIcon = <CheckCircleFilled style={{ color: "#10b981", fontSize: 14 }} />;
            textColor = "text-gray-200";
            badgeBorder = "border-emerald-500/20 bg-emerald-950/10";
          } else if (stage.state === "error") {
            statusIcon = <CloseCircleFilled style={{ color: "#ef4444", fontSize: 14 }} />;
            textColor = "text-red-300";
            badgeBorder = "border-red-500/30 bg-red-950/20";
          } else if (stage.state === "cancelled") {
            statusIcon = <StopOutlined style={{ color: "#f59e0b", fontSize: 14 }} />;
            textColor = "text-amber-300";
            badgeBorder = "border-amber-500/30 bg-amber-950/20";
          }

          return (
            <div
              key={stage.id}
              className={`flex items-start gap-2.5 p-2.5 rounded-lg border transition-all ${badgeBorder}`}
            >
              <div className="mt-0.5">{statusIcon}</div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between">
                  <span className={`text-xs truncate ${textColor}`}>{stage.label}</span>
                  {stage.latencyMs !== undefined && (
                    <span className="text-[10px] text-gray-500 font-mono ml-1">
                      {stage.latencyMs.toFixed(1)}ms
                    </span>
                  )}
                </div>
                <div className="text-[11px] text-gray-400 truncate mt-0.5">
                  {stage.description}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Terminal Error Message Notice if any */}
      {error && (
        <div className="mt-4 p-3 rounded-lg bg-red-950/40 border border-red-800 text-red-300 text-xs flex items-center justify-between">
          <span>{error}</span>
          <Tag color="error">
            {error.includes("VALIDATION") || error.includes("SECURITY")
              ? "SECURITY / VALIDATION REJECTION"
              : error.includes("EXECUTION")
              ? "DATABASE EXECUTION ERROR"
              : error.includes("TIMEOUT")
              ? "TIMEOUT ERROR"
              : "PIPELINE EXECUTION ERROR"}
          </Tag>
        </div>
      )}

      {/* Cancellation Notice if any */}
      {cancelled && (
        <div className="mt-4 p-3 rounded-lg bg-amber-950/30 border border-amber-800 text-amber-300 text-xs flex items-center justify-between">
          <span>Query was safely cancelled. All underlying operations and connections were immediately aborted.</span>
          <Tag color="warning">CANCELLED</Tag>
        </div>
      )}
    </Card>
  );
};
