/**
 * RuntimeEventTimeline — unified task execution timeline.
 *
 * Renders the event stream from AgentResult.events as a vertical
 * timeline with type-specific cards.  Integrates tool calls, approvals,
 * diagnostics inline — no separate page views needed.
 *
 * v3.9: Single source of truth — only reads from the unified
 * workbench store (AgentResult.events / tool_calls / metadata).
 */
import React, { useState } from "react";
import type { AgentResult, RuntimeEvent, ToolCallResult } from "../types";

/* ── event type → semantic colour (border only) ── */

interface EventConfig {
  icon: string;
  label: string;
  border: string;
}

const EVENT_CONFIG: Record<string, EventConfig> = {
  turn_started:     { icon: "▶",  label: "轮次开始",  border: "var(--text-4)" },
  context_built:    { icon: "📋", label: "上下文",    border: "var(--text-4)" },
  model_started:    { icon: "🧠", label: "模型推理",  border: "var(--accent)" },
  model_completed:  { icon: "✅", label: "模型完成",  border: "var(--ok)" },
  tool_call:        { icon: "🔧", label: "工具调用",  border: "var(--warn)" },
  tool_result:      { icon: "📊", label: "工具结果",  border: "var(--info)" },
  approval_required:{ icon: "🛡️", label: "等待审批",  border: "var(--danger)" },
  approval_granted: { icon: "🔓", label: "审批通过",  border: "var(--ok)" },
  approval_denied:  { icon: "🚫", label: "审批拒绝",  border: "var(--danger)" },
  final_response:   { icon: "💬", label: "最终回复",  border: "var(--accent)" },
  compact:          { icon: "🗜️", label: "上下文压缩", border: "var(--warn)" },
  error:            { icon: "❌", label: "错误",      border: "var(--danger)" },
  warning:          { icon: "⚠️",  label: "警告",      border: "var(--warn)" },
  checkpoint:       { icon: "💾", label: "检查点",    border: "var(--info)" },
};

function getEventConfig(evt: RuntimeEvent): EventConfig {
  const type = evt.event_type?.toLowerCase() || "";
  if (type.startsWith("tool_call") || evt.tool_id) return EVENT_CONFIG.tool_call;
  if (type.includes("approval") && (type.includes("required") || type.includes("pending"))) return EVENT_CONFIG.approval_required;
  if (type.includes("approval") && type.includes("grant")) return EVENT_CONFIG.approval_granted;
  if (type.includes("approval") && type.includes("den")) return EVENT_CONFIG.approval_denied;
  if (type.includes("final") || type.includes("response")) return EVENT_CONFIG.final_response;
  if (type.includes("checkpoint")) return EVENT_CONFIG.checkpoint;
  return EVENT_CONFIG[type] ?? EVENT_CONFIG.turn_started;
}

function toolLabel(toolId: string): string {
  const parts = toolId.split(".");
  return parts.length > 1 ? parts[parts.length - 1] : toolId;
}

function formatMs(ms?: number | null): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/* ── Tool Call Card (expandable) ── */

const ToolCallCard: React.FC<{ tc: ToolCallResult }> = React.memo(({ tc }) => {
  const [expanded, setExpanded] = useState(false);
  const hasDetails = (tc.errors?.length ?? 0) > 0 || (tc.artifacts?.length ?? 0) > 0;

  return (
    <div className="ret-tool-card" data-testid={`tool-call-${tc.call_id}`}>
      <div
        className="ret-tool-header"
        onClick={() => hasDetails && setExpanded(!expanded)}
        style={{ cursor: hasDetails ? "pointer" : "default" }}
      >
        <span className={`ret-tool-ok ${tc.ok ? "" : "err"}`}>{tc.ok ? "✓" : "✗"}</span>
        <code className="ret-tool-id">{toolLabel(tc.tool_id)}</code>
        <span className={`ret-tool-status ${tc.ok ? "ok" : "err"}`}>
          {tc.ok ? "完成" : "失败"}
        </span>
        {tc.duration_ms != null && <span className="ret-tool-dur">{formatMs(tc.duration_ms)}</span>}
        {hasDetails && <span className="ret-tool-toggle">{expanded ? "▲" : "▼"}</span>}
      </div>
      {tc.summary && <div className="ret-tool-summary">{tc.summary}"</div>}
      {expanded && (
        <div className="ret-tool-detail">
          {tc.errors && tc.errors.length > 0 && (
            <div className="ret-tool-errors">
              {tc.errors.map((e, i) => <span key={i} className="ret-tool-err">{e}</span>)}
            </div>
          )}
          {tc.artifacts && tc.artifacts.length > 0 && (
            <div className="ret-tool-artifacts">
              {tc.artifacts.map((a) => (
                <span key={a.artifact_id} className="ret-artifact-chip">
                  📄 {a.title || a.artifact_id.slice(0, 8)}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
});

/* ── Event Card (expandable) ── */

const EventCard: React.FC<{ evt: RuntimeEvent; idx: number }> = React.memo(({ evt, idx }) => {
  const [expanded, setExpanded] = useState(false);
  const cfg = getEventConfig(evt);
  const ts = evt.occurred_at || evt.started_at || "";
  const hasDetail = !!(evt.error || evt.tool_id);

  return (
    <div
      className="ret-event-card"
      style={{ borderLeftColor: cfg.border }}
      data-testid={`event-${idx}`}
    >
      <div
        className="ret-event-header"
        onClick={() => hasDetail && setExpanded(!expanded)}
        style={{ cursor: hasDetail ? "pointer" : "default" }}
      >
        <span className="ret-event-icon">{cfg.icon}</span>
        <span className="ret-event-type">{cfg.label}</span>
        {evt.duration_ms != null && <span className="ret-event-dur">{formatMs(evt.duration_ms)}</span>}
        {ts && <span className="ret-event-time">{ts.slice(11, 19) || ts.slice(0, 10)}</span>}
        {hasDetail && <span className="ret-event-toggle">{expanded ? "▲" : "▼"}</span>}
      </div>
      {evt.summary && <div className="ret-event-summary">{evt.summary}</div>}
      {evt.message && !evt.summary && <div className="ret-event-summary">{evt.message}</div>}
      {expanded && (
        <div className="ret-event-detail">
          {evt.error && <div className="ret-event-error">{evt.error}</div>}
          {evt.tool_id && (
            <div className="ret-event-meta">
              <code>{evt.tool_id}</code>
              {evt.approval_id && <span className="ret-approval-chip">{evt.approval_id.slice(0, 10)}</span>}
            </div>
          )}
        </div>
      )}
    </div>
  );
});

/* ── Timeline ── */

export const RuntimeEventTimeline: React.FC<{
  results: AgentResult[];
}> = React.memo(function RuntimeEventTimeline({ results }) {
  if (!results || results.length === 0) {
    return (
      <div className="ret-empty" data-testid="timeline-empty">
        <div className="ret-empty-icon">⚡</div>
        <p>准备就绪</p>
        <p className="ret-empty-hint">发送消息后，执行事件将在此展示</p>
      </div>
    );
  }

  return (
    <div className="ret-timeline" data-testid="runtime-timeline">
      {results.map((result, runIdx) => {
        const events = result.events ?? [];
        const toolCalls = result.tool_calls ?? [];
        const metadata = result.metadata ?? {};
        const hasDiagnostics = !!(result.errors?.length) || !!(result.warnings?.length);

        return (
          <div key={result.turn_id || `run-${runIdx}`} className="ret-run-block">
            {/* Turn header */}
            <div className="ret-turn-header">
              <div className="ret-turn-title">
                <span className={`ret-turn-ok ${result.ok ? "ok" : "err"}`}>
                  {result.ok ? "✓" : "✗"}
                </span>
                <span className="ret-turn-label">运行 {result.turn_id?.slice(0, 8) || `#${runIdx + 1}`}</span>
              </div>
              <div className="ret-turn-meta">
                {metadata.workspace_id && <span className="ret-meta-chip">{metadata.workspace_id}</span>}
                {metadata.planner_mode && <span className="ret-meta-chip">{metadata.planner_mode}</span>}
                {result.tool_decision?.selected_tools?.length ? (
                  <span className="ret-meta-chip">{result.tool_decision.selected_tools.length} 工具</span>
                ) : null}
              </div>
            </div>

            {/* Diagnostics */}
            {hasDiagnostics && (
              <div className="ret-diag-banner" data-testid="diag-banner">
                {result.errors?.map((e, i) => (
                  <div key={`err-${i}`} className="ret-diag-item err">{e}</div>
                ))}
                {result.warnings?.map((w, i) => (
                  <div key={`warn-${i}`} className="ret-diag-item warn">{w}</div>
                ))}
              </div>
            )}

            {/* Event stream */}
            {events.length > 0 ? (
              <div className="ret-events" data-testid="event-list">
                {events.map((evt, idx) => (
                  <EventCard key={evt.event_id || `${idx}`} evt={evt} idx={idx} />
                ))}
              </div>
            ) : (
              <div className="ret-no-events">无运行时事件</div>
            )}

            {/* Tool calls */}
            {toolCalls.length > 0 && (
              <div className="ret-tool-panel" data-testid="tool-panel">
                <div className="ret-section-title">工具调用 ({toolCalls.length})</div>
                <div className="ret-tool-list">
                  {toolCalls.map((tc) => <ToolCallCard key={tc.call_id} tc={tc} />)}
                </div>
              </div>
            )}

            {/* Sources */}
            {metadata.source_count ? (
              <div className="ret-source-panel" data-testid="source-panel">
                <div className="ret-section-title">
                  参考来源 · {metadata.source_count} 个
                  {metadata.retrieval_backend && (
                    <span className="ret-meta-chip">{metadata.retrieval_backend}</span>
                  )}
                </div>
              </div>
            ) : null}

            {/* Artifacts */}
            {(() => {
              const artifacts = toolCalls.flatMap((tc) => tc.artifacts ?? []);
              if (artifacts.length === 0) return null;
              return (
                <div className="ret-artifact-panel" data-testid="artifact-panel">
                  <div className="ret-section-title">产物 ({artifacts.length})</div>
                  <div className="ret-artifact-list">
                    {artifacts.slice(0, 8).map((a) => (
                      <span key={a.artifact_id} className="ret-artifact-chip" title={a.artifact_id}>
                        {a.artifact_type ? `${a.artifact_type}: ` : ""}{a.title || a.artifact_id.slice(0, 12)}
                      </span>
                    ))}
                  </div>
                </div>
              );
            })()}
          </div>
        );
      })}
    </div>
  );
});

export default RuntimeEventTimeline;
