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
import React from "react";
import type { AgentResult, RuntimeEvent, ToolCallResult } from "../types";

/* ── event type → display config ── */

interface EventConfig {
  icon: string;
  label: string;
  color: string;
  bg: string;
}

const EVENT_CONFIG: Record<string, EventConfig> = {
  turn_started:     { icon: "▶",  label: "轮次开始",  color: "#6366f1", bg: "#eef2ff" },
  context_built:    { icon: "📋", label: "上下文",    color: "#8b5cf6", bg: "#f5f3ff" },
  model_started:    { icon: "🧠", label: "模型推理",  color: "#0ea5e9", bg: "#f0f9ff" },
  model_completed:  { icon: "✅", label: "模型完成",  color: "#10b981", bg: "#ecfdf5" },
  tool_call:        { icon: "🔧", label: "工具调用",  color: "#f59e0b", bg: "#fffbeb" },
  tool_result:      { icon: "📊", label: "工具结果",  color: "#14b8a6", bg: "#f0fdfa" },
  approval_required:{ icon: "🛡️", label: "等待审批",  color: "#ef4444", bg: "#fef2f2" },
  approval_granted: { icon: "🔓", label: "审批通过",  color: "#10b981", bg: "#ecfdf5" },
  approval_denied:  { icon: "🚫", label: "审批拒绝",  color: "#ef4444", bg: "#fef2f2" },
  final_response:   { icon: "💬", label: "最终回复",  color: "#3b82f6", bg: "#eff6ff" },
  compact:          { icon: "🗜️", label: "上下文压缩", color: "#f59e0b", bg: "#fffbeb" },
  error:            { icon: "❌", label: "错误",      color: "#ef4444", bg: "#fef2f2" },
  warning:          { icon: "⚠️",  label: "警告",      color: "#f59e0b", bg: "#fffbeb" },
  checkpoint:       { icon: "💾", label: "检查点",    color: "#06b6d4", bg: "#ecfeff" },
};

function getEventConfig(evt: RuntimeEvent): EventConfig {
  const type = evt.event_type?.toLowerCase() || "";
  // Map known type variations
  if (type.startsWith("tool_call") || evt.tool_id)
    return EVENT_CONFIG.tool_call;
  if (type.includes("approval") && (type.includes("required") || type.includes("pending")))
    return EVENT_CONFIG.approval_required;
  if (type.includes("approval") && type.includes("grant"))
    return EVENT_CONFIG.approval_granted;
  if (type.includes("approval") && type.includes("den"))
    return EVENT_CONFIG.approval_denied;
  if (type.includes("final") || type.includes("response"))
    return EVENT_CONFIG.final_response;
  if (type.includes("checkpoint"))
    return EVENT_CONFIG.checkpoint;
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

/* ── Tool Call Card ── */

const ToolCallCard: React.FC<{ tc: ToolCallResult }> = React.memo(({ tc }) => (
  <div className="ret-tool-card" data-testid={`tool-call-${tc.call_id}`}>
    <div className="ret-tool-header">
      <span className="ret-tool-icon">{tc.ok ? "✓" : "✗"}</span>
      <code className="ret-tool-id">{toolLabel(tc.tool_id)}</code>
      <span className={`ret-tool-status ${tc.ok ? "ok" : "err"}`}>
        {tc.ok ? "完成" : "失败"}
      </span>
      {tc.duration_ms != null && (
        <span className="ret-tool-duration">{formatMs(tc.duration_ms)}</span>
      )}
    </div>
    {tc.summary && <div className="ret-tool-summary">{tc.summary.slice(0, 120)}</div>}
    {tc.errors && tc.errors.length > 0 && (
      <div className="ret-tool-errors">
        {tc.errors.slice(0, 3).map((e, i) => (
          <span key={i} className="ret-tool-err">{e.slice(0, 100)}</span>
        ))}
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
));

/* ── Event Card ── */

const EventCard: React.FC<{ evt: RuntimeEvent; idx: number }> = React.memo(({ evt, idx }) => {
  const cfg = getEventConfig(evt);
  const ts = evt.occurred_at || evt.started_at || "";

  return (
    <div
      className="ret-event-card"
      style={{ borderLeftColor: cfg.color, backgroundColor: cfg.bg }}
      data-testid={`event-${idx}`}
    >
      <div className="ret-event-header">
        <span className="ret-event-icon">{cfg.icon}</span>
        <span className="ret-event-type" style={{ color: cfg.color }}>{cfg.label}</span>
        {evt.duration_ms != null && (
          <span className="ret-event-duration">{formatMs(evt.duration_ms)}</span>
        )}
        {ts && <span className="ret-event-time">{ts.slice(11, 19) || ts.slice(0, 10)}</span>}
      </div>
      {evt.summary && <div className="ret-event-summary">{evt.summary.slice(0, 200)}</div>}
      {evt.message && !evt.summary && <div className="ret-event-summary">{evt.message.slice(0, 200)}</div>}
      {evt.error && <div className="ret-event-error">{evt.error.slice(0, 200)}</div>}
      {evt.tool_id && (
        <div className="ret-event-tool-ref">
          <code>{evt.tool_id}</code>
          {evt.approval_id && <span className="ret-approval-chip">审批 {evt.approval_id.slice(0, 10)}</span>}
        </div>
      )}
    </div>
  );
});

/* ── Timeline ── */

export const RuntimeEventTimeline: React.FC<{
  result: AgentResult | undefined;
}> = React.memo(function RuntimeEventTimeline({ result }) {
  if (!result) {
    return (
      <div className="ret-empty" data-testid="timeline-empty">
        <div className="ret-empty-icon">📋</div>
        <p>等待任务执行…</p>
        <p className="ret-empty-hint">发送消息后，这里会展示运行时事件时间线</p>
      </div>
    );
  }

  const events = result.events ?? [];
  const toolCalls = result.tool_calls ?? [];
  const metadata = result.metadata ?? {};
  const hasDiagnostics = result.errors?.length || result.warnings?.length;

  return (
    <div className="ret-timeline" data-testid="runtime-timeline">
      {/* Turn header */}
      <div className="ret-turn-header">
        <div className="ret-turn-title">
          <span className={`ret-turn-ok ${result.ok ? "ok" : "err"}`}>
            {result.ok ? "✓" : "✗"}
          </span>
          <span>运行 {result.turn_id?.slice(0, 8) || ""}</span>
        </div>
        <div className="ret-turn-meta">
          {metadata.workspace_id && <span className="ret-meta-chip">📁 {metadata.workspace_id}</span>}
          {metadata.planner_mode && <span className="ret-meta-chip">🎯 {metadata.planner_mode}</span>}
          {result.tool_decision?.selected_tools?.length && (
            <span className="ret-meta-chip" title={result.tool_decision.selected_tools.join(", ")}>
              🔧 {result.tool_decision.selected_tools.length} 工具
            </span>
          )}
        </div>
      </div>

      {/* Diagnostics banner */}
      {hasDiagnostics && (
        <div className="ret-diag-banner" data-testid="diag-banner">
          {result.errors?.map((e, i) => (
            <div key={`err-${i}`} className="ret-diag-item err">❌ {e.slice(0, 150)}</div>
          ))}
          {result.warnings?.map((w, i) => (
            <div key={`warn-${i}`} className="ret-diag-item warn">⚠️ {w.slice(0, 150)}</div>
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
        <div className="ret-no-events" data-testid="no-events">
          <span>无运行时事件 — 使用文本回复</span>
        </div>
      )}

      {/* Tool calls panel */}
      {toolCalls.length > 0 && (
        <div className="ret-tool-panel" data-testid="tool-panel">
          <div className="ret-section-title">🔧 工具调用 ({toolCalls.length})</div>
          <div className="ret-tool-list">
            {toolCalls.map((tc) => (
              <ToolCallCard key={tc.call_id} tc={tc} />
            ))}
          </div>
        </div>
      )}

      {/* Source summary */}
      {metadata.source_count ? (
        <div className="ret-source-panel" data-testid="source-panel">
          <div className="ret-section-title">
            📚 参考来源 · {metadata.source_count} 个
            {metadata.retrieval_backend && (
              <span className="ret-meta-chip ml-1">{metadata.retrieval_backend}</span>
            )}
          </div>
        </div>
      ) : null}

      {/* Artifacts summary (from tool calls) */}
      {(() => {
        const artifacts = toolCalls.flatMap((tc) => tc.artifacts ?? []);
        if (artifacts.length === 0) return null;
        return (
          <div className="ret-artifact-panel" data-testid="artifact-panel">
            <div className="ret-section-title">📦 产物 ({artifacts.length})</div>
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
});

export default RuntimeEventTimeline;
