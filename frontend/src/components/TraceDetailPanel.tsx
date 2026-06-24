/**
 * TraceDetailPanel — 追踪详情面板 (v3.3.1 美化)
 *
 * 交互式 trace 查看器：筛选、搜索、可展开 JSON。
 * Shared by RunsPage.
 */
import { useState, useMemo } from "react";
import { Badge } from "./common";
import {
  deriveRunTraceStats,
  eventToolId,
  isTraceErrorEvent,
  isTraceLlmEvent,
  isTraceNodeEvent,
  isTraceCapabilityEvent,
  isTraceToolEvent,
  isTraceWarningEvent,
  traceEventType,
} from "../utils/runTraceStats";
import type { RuntimeEvent, RuntimeAuditTurn } from "../types";

interface Props {
  traceEvents: RuntimeEvent[] | null;
  selectedRun: RuntimeAuditTurn | null;
}

type EventFilter = "all" | "tool" | "skill" | "warning" | "error" | "llm" | "node";

const FILTER_LABELS: Record<EventFilter, string> = {
  all: "全部", tool: "工具", skill: "能力", warning: "警告", error: "错误", llm: "LLM", node: "节点",
};

export function TraceDetailPanel({ traceEvents, selectedRun }: Props) {
  const [filter, setFilter] = useState<EventFilter>("all");
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [showMeta, setShowMeta] = useState(false);

  const toggle = (idx: number) => setExpanded((p) => { const n = new Set(p); n.has(idx) ? n.delete(idx) : n.add(idx); return n; });

  const filtered = useMemo(() => {
    if (!traceEvents) return [];
    let r = traceEvents;
    if (filter !== "all") {
      r = r.filter((e) => {
        if (filter === "tool") return isTraceToolEvent(e);
        if (filter === "skill") return isTraceCapabilityEvent(e);
        if (filter === "warning") return isTraceWarningEvent(e);
        if (filter === "error") return isTraceErrorEvent(e);
        if (filter === "llm") return isTraceLlmEvent(e);
        if (filter === "node") return isTraceNodeEvent(e);
        return true;
      });
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      r = r.filter((e) =>
        traceEventType(e).includes(q) ||
        (e.tool_id || "").toLowerCase().includes(q) ||
        (eventToolId(e) || "").toLowerCase().includes(q) ||
        (e.summary || "").toLowerCase().includes(q) ||
        (e.name || "").toLowerCase().includes(q) ||
        (e.message || "").toLowerCase().includes(q)
      );
    }
    return r;
  }, [traceEvents, filter, search]);

  const counts = useMemo(() => {
    if (!traceEvents) return {} as Record<string, number>;
    const c: Record<string, number> = { all: traceEvents.length };
    for (const e of traceEvents) {
      if (isTraceToolEvent(e)) c.tool = (c.tool || 0) + 1;
      if (isTraceCapabilityEvent(e)) c.skill = (c.skill || 0) + 1;
      if (isTraceWarningEvent(e)) c.warning = (c.warning || 0) + 1;
      if (isTraceErrorEvent(e)) c.error = (c.error || 0) + 1;
      if (isTraceLlmEvent(e)) c.llm = (c.llm || 0) + 1;
      if (isTraceNodeEvent(e)) c.node = (c.node || 0) + 1;
    }
    return c;
  }, [traceEvents]);

  const runStats = useMemo(
    () => deriveRunTraceStats(selectedRun, traceEvents),
    [selectedRun, traceEvents],
  );

  if (!selectedRun) return null;
  if (traceEvents === null && selectedRun.trace_id) {
    return (
      <div className="card" style={{ padding: "24px", textAlign: "center", color: "var(--text-3)", fontSize: "var(--fs-12)" }}>
        正在加载 trace…
      </div>
    );
  }

  return (
    <div style={{ marginTop: 0 }}>
      {/* ── Summary bar ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
        <span style={{ fontSize: "var(--fs-14)", fontWeight: 720 }}>Trace · {traceEvents?.length ?? 0} events</span>
        <span style={{ color: "var(--text-4)", fontSize: "var(--fs-11)", fontFamily: "var(--font-mono)" }}>
          {String(selectedRun.trace_id || "-").substring(0, 12)}
        </span>
        <div style={{ flex: 1 }} />
        <button className="btn sm" onClick={() => { const t = JSON.stringify(traceEvents, null, 2); navigator.clipboard?.writeText(t).catch(() => {}); }}>
          📋 复制
        </button>
      </div>

      {/* ── Quick stats ── */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 12 }}>
        <span className="badge info">{runStats.toolCallCount} 工具</span>
        <span className="badge warn">{runStats.warningCount} 警告</span>
        <span className="badge err">{runStats.errorCount} 错误</span>
        {runStats.startedAt && (
          <span style={{ color: "var(--text-4)", fontSize: "var(--fs-11)", padding: "2px 0" }}>
            {String(runStats.startedAt)}
          </span>
        )}
      </div>

      {/* ── Tool decision fold ── */}
      {selectedRun.tool_decision && (
        <details style={{ marginBottom: 10, fontSize: "var(--fs-12)" }}>
          <summary style={{ color: "var(--text-3)", cursor: "pointer" }}>tool_decision</summary>
          <pre style={{ marginTop: 4, fontSize: "var(--fs-11)", maxHeight: 120, overflow: "auto", background: "var(--surface-2)", padding: 8, borderRadius: "var(--r-4)" }}>
            {JSON.stringify(selectedRun.tool_decision, null, 2)}
          </pre>
        </details>
      )}

      {/* ── Filter bar ── */}
      <div className="segmented" style={{ marginBottom: 12 }}>
        {(Object.entries(FILTER_LABELS) as [EventFilter, string][]).map(([k, v]) => (
          <button key={k} className={filter === k ? "active" : ""} onClick={() => setFilter(k)} type="button">
            {v}{counts[k] ? ` ${counts[k]}` : ""}
          </button>
        ))}
      </div>

      <input
        className="input" type="text" placeholder="搜索 event…" value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={{ marginBottom: 12, height: 30, fontSize: "var(--fs-12)" }}
      />

      {/* ── Event list ── */}
      <div style={{ border: "1px solid var(--line)", borderRadius: "var(--r-8)", overflow: "hidden" }}>
        {filtered.length === 0 ? (
          <div style={{ padding: "32px 16px", textAlign: "center", color: "var(--text-3)", fontSize: "var(--fs-13)" }}>
            {search ? "无匹配事件" : "暂无事件"}
          </div>
        ) : (
          filtered.map((e, idx) => {
            const open = expanded.has(idx);
            const rawType = e.event_type || e.type || e.name || "";
            const et = evTypeLabel(rawType, e);
            const badge = evBadge(e);
            const tId = e.tool_id || eventToolId(e);
            return (
              <div key={idx} style={{ borderBottom: "1px solid var(--line-2)", fontSize: "var(--fs-12)" }}>
                <div
                  onClick={() => toggle(idx)}
                  style={{
                    display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", cursor: "pointer",
                    background: open ? "var(--surface-3)" : "var(--surface)",
                    transition: "background var(--dur-2) var(--ease)",
                  }}>
                  <span style={{ color: "var(--text-4)", fontSize: "var(--fs-10)", fontFamily: "var(--font-mono)", minWidth: 22 }}>{idx + 1}</span>
                  <Badge kind={badge} withDot>{et}</Badge>
                  {tId && <code style={{ fontSize: "var(--fs-10)", color: "var(--accent)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 140 }}>{tId}</code>}
                  {e.name && !tId && <span style={{ color: "var(--text-3)", fontSize: "var(--fs-11)" }}>{e.name}</span>}
                  {e.status && <Badge kind={e.status === "error" || e.status === "failed" ? "err" : "ok"}>{e.status}</Badge>}
                  <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text-2)" }}>
                    {e.summary || e.message || ""}
                  </span>
                  <span style={{ color: "var(--text-4)", fontSize: "var(--fs-10)", fontFamily: "var(--font-mono)", flexShrink: 0 }}>
                    {e.occurred_at ? String(e.occurred_at).substring(11, 19) : e.timestamp ? String(e.timestamp).substring(11, 19) : ""}
                  </span>
                  <span style={{ color: "var(--text-3)", fontSize: "var(--fs-10)" }}>{open ? "▲" : "▼"}</span>
                </div>
                {open && (
                  <div style={{ padding: "8px 12px 8px 48px", background: "var(--surface-2)" }}>
                    {e.summary && !e.message && <div style={{ marginBottom: 4, color: "var(--text)" }}>{e.summary}</div>}
                    {e.message && <div style={{ marginBottom: 4, color: "var(--warn)" }}>{e.message}</div>}
                    {e.error && <div style={{ marginBottom: 4, color: "var(--danger)" }}>{e.error}</div>}
                    {e.duration_ms && <div style={{ color: "var(--text-3)", fontSize: "var(--fs-11)" }}>耗时: {e.duration_ms}ms</div>}
                    {e.approval_id && <div style={{ color: "var(--warn)", fontSize: "var(--fs-11)" }}>审批: {e.approval_id} ({e.approval_status || "pending"})</div>}
                    {e.input_preview && (
                      <details style={{ marginTop: 4 }}>
                        <summary style={{ cursor: "pointer", color: "var(--text-3)", fontSize: "var(--fs-11)" }}>input</summary>
                        <pre style={{ maxHeight: 80, overflow: "auto", marginTop: 4, fontSize: "var(--fs-10)", background: "var(--surface)", padding: 6, borderRadius: "var(--r-4)" }}>
                          {typeof e.input_preview === "string" ? e.input_preview : JSON.stringify(e.input_preview, null, 2)}
                        </pre>
                      </details>
                    )}
                    {e.output_preview && (
                      <details style={{ marginTop: 4 }}>
                        <summary style={{ cursor: "pointer", color: "var(--text-3)", fontSize: "var(--fs-11)" }}>output</summary>
                        <pre style={{ maxHeight: 80, overflow: "auto", marginTop: 4, fontSize: "var(--fs-10)", background: "var(--surface)", padding: 6, borderRadius: "var(--r-4)" }}>
                          {typeof e.output_preview === "string" ? e.output_preview : JSON.stringify(e.output_preview, null, 2)}
                        </pre>
                      </details>
                    )}
                    <details style={{ marginTop: 4 }}>
                      <summary style={{ cursor: "pointer", color: "var(--text-3)", fontSize: "var(--fs-11)" }}>JSON</summary>
                      <pre style={{ maxHeight: 150, overflow: "auto", marginTop: 4, fontSize: "var(--fs-10)", background: "var(--surface)", padding: 6, borderRadius: "var(--r-4)" }}>
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

      {/* ── Full metadata ── */}
      <div style={{ marginTop: 12 }}>
        <button className="btn sm" onClick={() => setShowMeta(!showMeta)}>
          {showMeta ? "收起 metadata" : "完整 metadata"}
        </button>
        {showMeta && (
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <pre style={{ flex: 1, fontSize: "var(--fs-10)", maxHeight: 280, overflow: "auto", background: "var(--surface-2)", padding: 10, borderRadius: "var(--r-6)", border: "1px solid var(--line-2)" }}>
              {JSON.stringify({
                run_id: selectedRun.run_id, turn_id: selectedRun.turn_id, trace_id: selectedRun.trace_id,
                session_id: selectedRun.session_id, status: selectedRun.status, intent: selectedRun.intent,
                started_at: selectedRun.started_at, finished_at: selectedRun.finished_at,
                tool_call_count: runStats.toolCallCount, warning_count: runStats.warningCount,
                error_count: runStats.errorCount, events_count: traceEvents?.length ?? 0,
              }, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

function evBadge(e: RuntimeEvent): "ok" | "err" | "warn" | "info" | "muted" {
  const et = traceEventType(e);
  const lv = (e.level || "").toLowerCase();
  if (et.includes("error") || et.includes("failed") || lv === "err" || lv === "error") return "err";
  if (et === "warning" || lv === "warn") return "warn";
  if (et.includes("finish") || et.includes("completed") || et === "tool_end") return "ok";
  if (et.includes("skill")) return "info";
  if (et.includes("tool") || et.includes("node") || et.includes("agent")) return "info";
  return "muted";
}

/** Map raw event_type to a human-readable Chinese label. */
function evTypeLabel(rawType: string, ev: any): string {
  if (!rawType) return "event";
  const t = rawType.toLowerCase();
  // Tool call events
  if (t.includes("tool_call_start")) return "工具开始";
  if (t.includes("tool_call_end") || t.includes("tool_call_finish")) return "工具完成";
  if (t.includes("tool_call_fail")) return "工具失败";
  if (t.includes("tool_call")) return "工具调用";
  // Model/LLM events
  if (t.includes("model_request") || t.includes("llm_request")) return "模型请求";
  if (t.includes("model_response") || t.includes("llm_response")) return "模型响应";
  if (t.includes("model") || t.includes("llm")) return "LLM";
  // Turn lifecycle
  if (t.includes("turn_start")) return "开始处理";
  if (t.includes("turn_finish") || t.includes("turn_end")) return "处理完成";
  if (t.includes("turn_fail")) return "处理失败";
  // Context
  if (t.includes("context_built")) return "构建上下文";
  // Agent/node
  if (t.includes("agent_start")) return "Agent 启动";
  if (t.includes("agent_end")) return "Agent 结束";
  if (t.includes("node_start")) return "节点开始";
  if (t.includes("node_end")) return "节点完成";
  if (t.includes("agent") || t.includes("node")) return "Agent";
  // capability call
  if (t.includes("capability_call")) return "能力调用";
  if (t.includes("module_call")) return "模块调用";
  // Warning/error
  if (t.includes("warning")) return "警告";
  if (t.includes("error")) return "错误";
  // Intent
  if (t.includes("intent")) return "意图路由";
  if (t.includes("approval")) return "审批";
  // Fallback: use event name or summary
  if (ev?.name) return ev.name.length > 10 ? ev.name.slice(0, 10) + "…" : ev.name;
  if (ev?.summary) return ev.summary.length > 10 ? ev.summary.slice(0, 10) + "…" : ev.summary;
  // Last resort: show original type truncated
  return rawType.length > 14 ? rawType.slice(0, 14) + "…" : rawType;
}
