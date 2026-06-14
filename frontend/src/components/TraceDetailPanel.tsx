/**
 * TraceDetailPanel — v2.1.3: Full trace detail with timeline, filters, search, expandable JSON.
 *
 * Replaces the old "preview first 5 events" approach with a complete interactive trace viewer.
 * Shared by RunsPage and RuntimeAudit.
 */

import { useState, useMemo } from "react";
import { Badge } from "./common";
import type { RuntimeEvent, RuntimeAuditTurn } from "../types";

interface Props {
  traceEvents: RuntimeEvent[] | null;
  selectedRun: RuntimeAuditTurn | null;
}

type EventFilter = "all" | "tool" | "warning" | "error" | "llm" | "node";

export function TraceDetailPanel({ traceEvents, selectedRun }: Props) {
  const [filter, setFilter] = useState<EventFilter>("all");
  const [search, setSearch] = useState("");
  const [expandedEvents, setExpandedEvents] = useState<Set<number>>(new Set());
  const [showMetadata, setShowMetadata] = useState(false);

  const toggleExpand = (idx: number) => {
    setExpandedEvents(prev => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx); else next.add(idx);
      return next;
    });
  };

  const filteredEvents = useMemo(() => {
    if (!traceEvents) return [];
    let result = traceEvents;

    // Apply filter
    if (filter !== "all") {
      result = result.filter(e => {
        const et = (e.event_type || "").toLowerCase();
        if (filter === "tool") return et.includes("tool");
        if (filter === "warning") return et === "warning" || e.level === "warn";
        if (filter === "error") return et === "error" || e.level === "err";
        if (filter === "llm") return et.includes("model") || et.includes("llm") || et.includes("assistant");
        if (filter === "node") return et.includes("node") || et.includes("agent");
        return true;
      });
    }

    // Apply search
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(e =>
        (e.event_type || "").toLowerCase().includes(q) ||
        (e.tool_id || "").toLowerCase().includes(q) ||
        eventToolId(e).toLowerCase().includes(q) ||
        (e.summary || "").toLowerCase().includes(q) ||
        (e.name || "").toLowerCase().includes(q) ||
        (e.message || "").toLowerCase().includes(q)
      );
    }
    return result;
  }, [traceEvents, filter, search]);

  const eventCounts = useMemo(() => {
    if (!traceEvents) return {};
    const counts: Record<string, number> = { all: traceEvents.length };
    for (const e of traceEvents) {
      const et = (e.event_type || "").toLowerCase();
      if (et.includes("tool")) counts.tool = (counts.tool || 0) + 1;
      if (et === "warning" || e.level === "warn") counts.warning = (counts.warning || 0) + 1;
      if (et === "error" || e.level === "err") counts.error = (counts.error || 0) + 1;
      if (et.includes("model") || et.includes("llm") || et.includes("assistant")) counts.llm = (counts.llm || 0) + 1;
      if (et.includes("node") || et.includes("agent")) counts.node = (counts.node || 0) + 1;
    }
    return counts;
  }, [traceEvents]);

  if (!selectedRun) return null;

  // Loading / not-found
  if (traceEvents === null && selectedRun.trace_id) {
    return (
      <div style={{ marginTop: 12 }}>
        <h4>Trace</h4>
        <div style={{ fontSize: 12, color: "var(--text-muted)", padding: 16, textAlign: "center" }}>
          正在加载 trace...
        </div>
      </div>
    );
  }

  return (
    <div style={{ marginTop: 12 }}>
      {/* ── Summary header ── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <h4 style={{ margin: 0 }}>Trace · {traceEvents?.length ?? 0} events</h4>
        <button
          className="btn-sm"
          onClick={() => {
            const text = JSON.stringify(traceEvents, null, 2);
            navigator.clipboard?.writeText(text).catch(() => {});
          }}
          title="复制全部事件 JSON"
        >
          📋 复制
        </button>
      </div>

      {/* ── Summary fields ── */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px", fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>
        <span>run: <code>{String(selectedRun.run_id || selectedRun.turn_id || "-")}</code></span>
        <span>trace: <code>{String(selectedRun.trace_id || "-")}</code></span>
        <span>session: <code>{String(selectedRun.session_id || "-").substring(0, 12)}</code></span>
        <span>tools: <Badge kind="info">{Number(selectedRun.tool_call_count ?? 0)}</Badge></span>
        <span>warns: <Badge kind="warn">{Number(selectedRun.warning_count ?? 0)}</Badge></span>
        <span>errs: <Badge kind="err">{Number(selectedRun.error_count ?? 0)}</Badge></span>
        {selectedRun.started_at && <span>{String(selectedRun.started_at)}</span>}
      </div>

      {/* ── Tool_decision (v2.1.2) ── */}
      {selectedRun.tool_decision && (
        <details style={{ marginBottom: 8, fontSize: 12 }}>
          <summary style={{ cursor: "pointer", color: "var(--text-muted)" }}>
            tool_decision
          </summary>
          <pre style={{
            fontSize: 11, maxHeight: 120, overflow: "auto",
            background: "var(--bg-secondary)", padding: 8, borderRadius: 4,
          }}>
            {JSON.stringify(selectedRun.tool_decision, null, 2)}
          </pre>
        </details>
      )}

      {Boolean((selectedRun as { metadata?: Record<string, unknown> }).metadata?.tool_scene) && (
        <details style={{ marginBottom: 8, fontSize: 12 }}>
          <summary style={{ cursor: "pointer", color: "var(--text-muted)" }}>
            tool_plan
          </summary>
          <pre style={{
            fontSize: 11, maxHeight: 180, overflow: "auto",
            background: "var(--bg-secondary)", padding: 8, borderRadius: 4,
          }}>
            {JSON.stringify({
              tool_planner: (selectedRun as { metadata?: Record<string, unknown> }).metadata?.tool_planner,
              tool_scene: (selectedRun as { metadata?: Record<string, unknown> }).metadata?.tool_scene,
              rule_tool_scene: (selectedRun as { metadata?: Record<string, unknown> }).metadata?.rule_tool_scene,
            }, null, 2)}
          </pre>
        </details>
      )}

      {/* ── Filter bar ── */}
      <div style={{ display: "flex", gap: 4, marginBottom: 8, flexWrap: "wrap", alignItems: "center" }}>
        {(["all", "tool", "warning", "error", "llm", "node"] as EventFilter[]).map(f => (
          <button
            key={f}
            className="btn-sm"
            style={{
              padding: "2px 8px", fontSize: 11,
              background: filter === f ? "var(--accent)" : "var(--bg-secondary)",
              color: filter === f ? "#fff" : "var(--text-primary)",
              border: "1px solid var(--border)",
              borderRadius: 4,
            }}
            onClick={() => setFilter(f)}
          >
            {f === "all" ? "全部" :
             f === "tool" ? "工具" :
             f === "warning" ? "警告" :
             f === "error" ? "错误" :
             f === "llm" ? "LLM" : "节点"}
            {eventCounts[f] ? ` (${eventCounts[f]})` : ""}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <input
          type="text"
          placeholder="搜索 event..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{
            padding: "2px 6px", fontSize: 12, border: "1px solid var(--border)",
            borderRadius: 4, width: 160, background: "var(--bg-input)", color: "var(--text-primary)",
          }}
        />
      </div>

      {/* ── Event timeline ── */}
      <div style={{ maxHeight: 400, overflow: "auto", border: "1px solid var(--border)", borderRadius: 6 }}>
        {filteredEvents.length === 0 ? (
          <div style={{ padding: 24, textAlign: "center", fontSize: 13, color: "var(--text-muted)" }}>
            {search ? "未找到匹配 event" : "该 turn 无 event"}
          </div>
        ) : (
          filteredEvents.map((e, idx) => {
            const isExpanded = expandedEvents.has(idx);
            const evType = e.event_type || "event";

            return (
              <div
                key={idx}
                style={{
                  borderBottom: "1px solid var(--border-light)",
                  fontSize: 12,
                }}
              >
                {/* Event header row */}
                <div
                  style={{
                    display: "flex", alignItems: "center", gap: 6,
                    padding: "4px 8px", cursor: "pointer",
                    background: isExpanded ? "var(--bg-soft)" : "transparent",
                  }}
                  onClick={() => toggleExpand(idx)}
                >
                  <span style={{ fontSize: 10, color: "var(--text-muted)", minWidth: 24 }}>
                    {idx + 1}
                  </span>
                  <span style={{ minWidth: 60, fontSize: 10 }}>
                    {e.occurred_at?.substring(11, 19) || e.timestamp?.substring(11, 19) || ""}
                  </span>
                  <Badge kind={evTypeBadge(e)}>{evType}</Badge>
                  {(e.tool_id || eventToolId(e)) && (
                    <code style={{ fontSize: 10, color: "var(--accent)" }}>{eventToolId(e) || e.tool_id}</code>
                  )}
                  {e.name && !e.tool_id && (
                    <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{e.name}</span>
                  )}
                  {e.status && (
                    <Badge kind={e.status === "error" || e.status === "failed" ? "err" : "ok"}>
                      {e.status}
                    </Badge>
                  )}
                  <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {e.summary || e.message || ""}
                  </span>
                  <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
                    {isExpanded ? "▲" : "▼"}
                  </span>
                </div>

                {/* Expanded detail */}
                {isExpanded && (
                  <div style={{ padding: "6px 8px 6px 38px", background: "var(--bg-secondary)", fontSize: 11 }}>
                    {e.summary && !e.message && <div style={{ marginBottom: 4 }}>{e.summary}</div>}
                    {e.message && <div style={{ marginBottom: 4, color: "var(--warn)" }}>{e.message}</div>}
                    {e.error && <div style={{ color: "var(--err)", marginBottom: 4 }}>{e.error}</div>}
                    {e.duration_ms && <div>耗时: {e.duration_ms}ms</div>}
                    {e.approval_id && (
                      <div style={{ color: "var(--warn)" }}>
                        审批: {e.approval_id} ({e.approval_status || e.blocked_by || "pending"})
                      </div>
                    )}
                    {e.input_preview && (
                      <details style={{ marginTop: 4 }}>
                        <summary style={{ cursor: "pointer", color: "var(--text-muted)" }}>input</summary>
                        <pre style={{ maxHeight: 80, overflow: "auto", marginTop: 4, fontSize: 10 }}>
                          {typeof e.input_preview === "string" ? e.input_preview : JSON.stringify(e.input_preview, null, 2)}
                        </pre>
                      </details>
                    )}
                    {e.output_preview && (
                      <details style={{ marginTop: 4 }}>
                        <summary style={{ cursor: "pointer", color: "var(--text-muted)" }}>output</summary>
                        <pre style={{ maxHeight: 80, overflow: "auto", marginTop: 4, fontSize: 10 }}>
                          {typeof e.output_preview === "string" ? e.output_preview : JSON.stringify(e.output_preview, null, 2)}
                        </pre>
                      </details>
                    )}
                    <details style={{ marginTop: 4 }}>
                      <summary style={{ cursor: "pointer", color: "var(--text-muted)" }}>JSON</summary>
                      <pre style={{
                        maxHeight: 150, overflow: "auto", marginTop: 4, fontSize: 10,
                        background: "var(--bg-primary)", padding: 4, borderRadius: 4,
                      }}>
                        {JSON.stringify(e, null, 2)}
                      </pre>
                    </details>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* ── Full metadata (collapsed) ── */}
      <div style={{ marginTop: 8 }}>
        <button
          className="btn-sm"
          onClick={() => setShowMetadata(!showMetadata)}
          style={{ fontSize: 12 }}
        >
          {showMetadata ? "收起 metadata" : "展开完整 metadata"}
        </button>
        {showMetadata && (
          <div style={{ marginTop: 4, display: "flex", gap: 8 }}>
            <pre style={{
              flex: 1, fontSize: 10, maxHeight: 300, overflow: "auto",
              background: "var(--bg-secondary)", padding: 8, borderRadius: 4,
              position: "relative",
            }}>
              {JSON.stringify({
                run_id: selectedRun.run_id,
                turn_id: selectedRun.turn_id,
                trace_id: selectedRun.trace_id,
                session_id: selectedRun.session_id,
                status: selectedRun.status,
                intent: selectedRun.intent,
                started_at: selectedRun.started_at,
                finished_at: selectedRun.finished_at,
                tool_call_count: selectedRun.tool_call_count,
                warning_count: selectedRun.warning_count,
                error_count: selectedRun.error_count,
                selected_skills: selectedRun.selected_skills,
                visible_tools: selectedRun.visible_tools,
                tool_decision: selectedRun.tool_decision,
                tool_planner: (selectedRun as { metadata?: Record<string, unknown> }).metadata?.tool_planner,
                tool_scene: (selectedRun as { metadata?: Record<string, unknown> }).metadata?.tool_scene,
                rule_tool_scene: (selectedRun as { metadata?: Record<string, unknown> }).metadata?.rule_tool_scene,
                no_tool_reason: selectedRun.no_tool_reason,
                events_count: traceEvents?.length ?? 0,
              }, null, 2)}
            </pre>
            <button
              className="btn-sm"
              onClick={() => {
                const text = JSON.stringify(selectedRun, null, 2);
                navigator.clipboard?.writeText(text).catch(() => {});
              }}
              title="复制 metadata JSON"
              style={{ alignSelf: "flex-start" }}
            >
              📋
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function eventToolId(ev: RuntimeAuditTurn["events"][number]): string {
  const meta = ev.metadata || ev.payload || {};
  const canonical = meta.canonical_tool_id;
  if (typeof canonical === "string") return canonical;
  return ev.tool_id || "";
}

/** Determine badge kind for an event based on its type/level. */
function evTypeBadge(e: RuntimeEvent): "ok" | "err" | "warn" | "info" | "muted" {
  const et = (e.event_type || "").toLowerCase();
  const level = (e.level || "").toLowerCase();
  if (et.includes("error") || et === "tool_error" || et.includes("failed") || level === "err" || level === "error")
    return "err";
  if (et === "warning" || level === "warn")
    return "warn";
  if (et.includes("finish") || et.includes("completed") || et === "tool_end")
    return "ok";
  if (et.includes("tool") || et.includes("node") || et.includes("agent"))
    return "info";
  return "muted";
}
