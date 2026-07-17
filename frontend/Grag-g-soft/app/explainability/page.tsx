"use client";

import React, { useEffect, useState } from 'react';
import styles from './explainability.module.css';

interface TraceMetrics {
  planner_latency_sec: number;
  engine_latency_sec: number;
  coverage_score: number;
  conflict_found: boolean;
  token_usage: number;
  evidence_count: number;
}

interface Trace {
  timestamp: number;
  query: string;
  intent: string;
  metrics: TraceMetrics;
}

export default function ExplainabilityDashboard() {
  const [traces, setTraces] = useState<Trace[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchTraces = async () => {
      try {
        const response = await fetch('/api/v1/rag/telemetry/traces');
        const data = await response.json();
        setTraces(data.traces || []);
      } catch (error) {
        console.error("Failed to fetch telemetry traces", error);
      } finally {
        setLoading(false);
      }
    };
    fetchTraces();
  }, []);

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <h1 className={styles.title}>Explainability Dashboard</h1>
        <p className={styles.subtitle}>Retrieval Graph Visualization & Telemetry</p>
      </header>

      {loading ? (
        <div className={styles.loader}>Loading Traces...</div>
      ) : (
        <div className={styles.dashboard}>
          {traces.length === 0 ? (
            <p className={styles.noData}>No telemetry data found.</p>
          ) : (
            traces.map((trace, index) => (
              <div key={index} className={styles.traceCard}>
                <div className={styles.traceHeader}>
                  <div className={styles.queryRow}>
                    <span className={styles.label}>Query</span>
                    <span className={styles.value}>"{trace.query}"</span>
                  </div>
                  <div className={styles.timestamp}>
                    {new Date(trace.timestamp * 1000).toLocaleString()}
                  </div>
                </div>

                <div className={styles.graphVisualization}>
                  {/* Visual Trace Graph */}
                  <div className={styles.node}>
                    <div className={styles.nodeIcon}>🔍</div>
                    <div className={styles.nodeLabel}>Input</div>
                  </div>
                  <div className={styles.edge}></div>
                  
                  <div className={styles.node}>
                    <div className={styles.nodeIcon}>🧠</div>
                    <div className={styles.nodeLabel}>
                      Intent:<br/><strong>{trace.intent}</strong>
                    </div>
                  </div>
                  <div className={styles.edge}></div>

                  <div className={styles.node}>
                    <div className={styles.nodeIcon}>⚙️</div>
                    <div className={styles.nodeLabel}>
                      Latency:<br/><strong>{trace.metrics.engine_latency_sec}s</strong>
                    </div>
                  </div>
                  <div className={styles.edge}></div>

                  <div className={`${styles.node} ${trace.metrics.conflict_found ? styles.nodeConflict : styles.nodeSuccess}`}>
                    <div className={styles.nodeIcon}>📄</div>
                    <div className={styles.nodeLabel}>
                      Evidence:<br/><strong>{trace.metrics.evidence_count} chunks</strong>
                    </div>
                  </div>
                </div>

                <div className={styles.metricsGrid}>
                  <div className={styles.metricItem}>
                    <span className={styles.metricLabel}>Tokens Used</span>
                    <span className={styles.metricValue}>{trace.metrics.token_usage}</span>
                  </div>
                  <div className={styles.metricItem}>
                    <span className={styles.metricLabel}>Coverage</span>
                    <span className={styles.metricValue}>
                      {trace.metrics.coverage_score ? trace.metrics.coverage_score.toFixed(2) : "N/A"}
                    </span>
                  </div>
                  <div className={styles.metricItem}>
                    <span className={styles.metricLabel}>Conflict</span>
                    <span className={`${styles.metricValue} ${trace.metrics.conflict_found ? styles.conflictAlert : ""}`}>
                      {trace.metrics.conflict_found ? "Detected" : "None"}
                    </span>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
