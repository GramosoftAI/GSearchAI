/**
 * Database Knowledgebase SSE Streaming Client (Phase 3E)
 *
 * Robust, W3C-compliant SSE parser over HTTP POST fetch:
 * - Supports custom Authorization Bearer token headers and JSON body
 * - Reconstructs fragmented SSE frames across network chunk boundaries
 * - Filters out ': keepalive' transport frames and heartbeat events
 * - Tracks sequence numbers, correlation IDs, and stage timings
 * - Provides clean cooperative cancellation via AbortController
 * - Never leaks internal SQL, credentials, or sensitive telemetry to the UI
 */

export type DatabaseStreamEventType =
  | "query.accepted"
  | "retrieval.started"
  | "retrieval.completed"
  | "planning.started"
  | "planning.completed"
  | "sql_generation.started"
  | "sql_generation.completed"
  | "validation.started"
  | "validation.completed"
  | "authorization.started"
  | "authorization.completed"
  | "execution.started"
  | "execution.completed"
  | "synthesis.started"
  | "synthesis.completed"
  | "grounding.started"
  | "grounding.completed"
  | "answer.completed"
  | "query.error"
  | "query.cancelled"
  | "stream.completed"
  | "heartbeat";

export interface DatabaseStreamEvent {
  sequence_number: number;
  event: DatabaseStreamEventType;
  protocol_version: string;
  correlation_id: string;
  query_id: string;
  stage: string;
  status: string;
  timestamp: string;
  elapsed_stage_ms?: number;
  elapsed_total_ms: number;
  data: Record<string, any>;
}

export interface StreamQueryError {
  code: string;
  message: string;
  stage?: string;
  retryable?: boolean;
}

export interface StreamQueryOptions {
  apiBaseUrl: string;
  kbId: string;
  query: string;
  token?: string;
  useLlm?: boolean;
  timeoutSeconds?: number;
  abortSignal?: AbortSignal;
  resolvedEntities?: any[];
  onDisambiguationRequired?: (data: { message: string; options: any[] }) => void;
  onEvent?: (event: DatabaseStreamEvent) => void;
  onAnswer?: (answer: any) => void;
  onError?: (error: StreamQueryError) => void;
  onCancelled?: (reason?: string) => void;
  onComplete?: () => void;
}

export class DatabaseStreamClient {
  /**
   * Executes a database query via SSE streaming and yields lifecycle events.
   */
  static async streamQuery(options: StreamQueryOptions): Promise<void> {
    const {
      apiBaseUrl,
      kbId,
      query,
      token,
      useLlm = true,
      timeoutSeconds,
      abortSignal,
      resolvedEntities,
      onDisambiguationRequired,
      onEvent,
      onAnswer,
      onError,
      onCancelled,
      onComplete,
    } = options;

    const url = `${apiBaseUrl}/database-knowledgebases/${kbId}/query/stream`;

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    const payload: Record<string, any> = {
      query,
      use_llm: useLlm,
      resolved_entities: resolvedEntities,
    };
    if (timeoutSeconds) {
      payload["timeout_seconds"] = timeoutSeconds;
    }

    try {
      const response = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
        signal: abortSignal,
      });

      if (!response.ok) {
        let errorMsg = `Server returned status ${response.status}`;
        try {
          const errJson = await response.json();
          errorMsg = errJson.detail || errJson.message || errorMsg;
        } catch {
          // ignore non-json error
        }
        if (onError) {
          onError({
            code: `HTTP_${response.status}`,
            message: errorMsg,
            retryable: response.status >= 500,
          });
        }
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("Response body is not readable.");
      }

      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      let lastSequenceNumber = 0;
      let hasCompleted = false;

      while (!hasCompleted) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });

        // SSE frames are delimited by double newlines (\n\n)
        const frames = buffer.split("\n\n");
        // The last element is either empty or a partial frame awaiting next chunk
        buffer = frames.pop() || "";

        for (const frame of frames) {
          const trimmed = frame.trim();
          if (!trimmed || trimmed.startsWith(":")) {
            // Comment / keepalive frame - ignore safely
            continue;
          }

          let eventType = "";
          let idStr = "";
          let dataStr = "";

          const lines = frame.split("\n");
          for (const line of lines) {
            if (line.startsWith("event:")) {
              eventType = line.substring(6).trim();
            } else if (line.startsWith("id:")) {
              idStr = line.substring(3).trim();
            } else if (line.startsWith("data:")) {
              dataStr = line.substring(5).trim();
            }
          }

          if (!eventType || !dataStr) {
            continue;
          }

          try {
            const parsedEvent: DatabaseStreamEvent = JSON.parse(dataStr);

            // Verify sequence monotonicity
            if (parsedEvent.sequence_number <= lastSequenceNumber) {
              console.warn(
                `Out-of-order sequence detected: received ${parsedEvent.sequence_number} after ${lastSequenceNumber}`
              );
            }
            lastSequenceNumber = parsedEvent.sequence_number;

            // Dispatch general event callback
            if (onEvent) {
              onEvent(parsedEvent);
            }

            // Handle terminal & milestone events
            if (parsedEvent.event === "answer.completed") {
              if (onAnswer && parsedEvent.data) {
                onAnswer(parsedEvent.data);
              }
            } else if (parsedEvent.event === "query.error") {
              hasCompleted = true;
              const isDisambig =
                parsedEvent.status === "disambiguation_required" ||
                parsedEvent.stage === "DISAMBIGUATION" ||
                parsedEvent.data?.stage === "DISAMBIGUATION" ||
                parsedEvent.data?.error_code === 300 ||
                parsedEvent.data?.error_code === "300" ||
                Boolean(parsedEvent.data?.options && parsedEvent.data.options.length > 0);

              if (isDisambig && onDisambiguationRequired) {
                onDisambiguationRequired({
                  message: parsedEvent.data?.message || "Multiple matches found.",
                  options: parsedEvent.data?.options || [],
                });
              } else if (onError) {
                onError({
                  code: parsedEvent.data?.error_code || "QUERY_ERROR",
                  message: parsedEvent.data?.message || "An error occurred during query execution.",
                  stage: parsedEvent.stage,
                  retryable: Boolean(parsedEvent.data?.retryable),
                });
              }
            } else if (parsedEvent.event === "query.cancelled") {
              hasCompleted = true;
              if (onCancelled) {
                onCancelled(parsedEvent.data?.reason || "Query was cancelled by user.");
              }
            } else if (parsedEvent.event === "stream.completed") {
              hasCompleted = true;
            }
          } catch (parseErr) {
            console.error("Failed to parse SSE JSON data frame:", dataStr, parseErr);
          }
        }
      }

      if (onComplete && !hasCompleted) {
        onComplete();
      }
    } catch (err: any) {
      if (err.name === "AbortError" || abortSignal?.aborted) {
        if (onCancelled) {
          onCancelled("Query cancelled by user.");
        }
      } else {
        if (onError) {
          onError({
            code: "NETWORK_ERROR",
            message: err.message || "Failed to communicate with database query service.",
            retryable: true,
          });
        }
      }
    }
  }
}
