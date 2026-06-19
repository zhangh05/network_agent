/**
 * RunsPage — 运行记录 (v3.3.1 美化)
 *
 * 合并运行记录 + 运行审计，双标签：概览 | 事件时间线。
 */
import { useEffect, useState, useCallback, useMemo } from "react";
import { workspacesApi, runtimeAuditApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { Badge, StatusDot, EmptyState, LoadingState, CodeBlock } from "../../components/common";
import { IconRefresh, IconAlert } from "../../components/Icon";
import { TraceDetailPanel } from "../../components/TraceDetailPanel";
import { APP_EVENTS } from "../../utils/appEvents";
import { deriveRunTraceStats } from "../../utils/runTraceStats";
import type { RuntimeAuditTurn } from "../../types";

/* ── Status helpers ── */

const STATUS_LABEL: Record<string, string> = {
  ok: "成功", completed: "已完成", success: "成功",
  failed: "失败", error: "失败", running: "运行中",
  pending: "等待中", timeout: "超时", cancelled: "已取消",
};

function sBadge(s: string): "ok" | "err" | "warn" | "muted" {
  if (/ok|completed|success/i.test(s)) return "ok";
  if (/fail|error/i.test(s)) return "err";
  if (/run|pending/i.test(s)) return "warn";
  return "muted";
}

function sDot(s: string): "ok" | "err" | "warn" | "idle" {
  if (/ok|completed|success/i.test(s)) return "ok";
  if (/fail|error/i.test(s)) return "err";
  if (/run|pending/i.test(s)) return "warn";
  return "idle";
}

function sLabel(s: string): string { return STATUS_LABEL[s] || s || "未知"; }

/* ── Event helpers ── */

function evTime(ev: any): string {
  const v = ev.occurred_at || ev.timestamp;
  return v == null ? "—" : String(v);
}

function evDetail(ev: any): Record<string, unknown> {
  return ev.payload || ev.metadata || {};
}

function evLabel(type: string, payload: Record<string, unknown>, ev?: any): string {
  const tId = typeof payload?.canonical_tool_id === "string"
    ? payload.canonical_tool_id : (typeof payload?.tool_id === "string" ? payload.tool_id : "?");
  const map: Record<string, string> = {
    turn_started: "开始处理请求", context_built: "构建上下文",
    model_request_started: "发起模型请求", model_response_received: "模型返回响应",
    tool_call_started: `调用工具：${tId}`, tool_call_finished: `工具完成：${tId}`,
    tool_call_failed: `工具失败：${tId}`, assistant_message: "生成回复",
    turn_finished: "处理完成",
    turn_failed: `失败：${String(payload?.error || "").slice(0, 50)}`,
    agent_start: ev?.summary || "开始", agent_end: ev?.summary || "完成",
    node_start: `节点：${ev?.name || "?"}`, node_end: `完成：${ev?.name || "?"}`,
    intent_routed: ev?.summary || "意图路由",
    skill_call_start: `技能：${ev?.name || "?"}`, skill_call_end: `完成：${ev?.name || "?"}`,
    module_call_start: `模块：${ev?.name || "?"}`, module_call_end: `完成：${ev?.name || "?"}`,
  };
  return map[type] || ev?.summary || ev?.name || type;
}

/* ── Component ── */

export function RunsPage() {
  const { currentWorkspaceId } = useSessionStore();
  const wsId = currentWorkspaceId || "default";
  const [runs, setRuns] = useState<RuntimeAuditTurn[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<RuntimeAuditTurn | null>(null);
  const [trace, setTrace] = useState<any[] | null>(null);
  const [tab, setTab] = useState<"overview" | "events">("overview");

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try { const d = await workspacesApi.recentRuns(wsId); setRuns(d.runs || []); }
    catch (e: any) { setError(e?.message || "加载失败"); }
    setLoading(false);
  }, [wsId]);

  const loadTrace = async (run: RuntimeAuditTurn) => {
    const rid = run.run_id || run.turn_id;
    if (!rid) return;
    try { const d = await runtimeAuditApi.trace(wsId, rid); setTrace(d.events || []); }
    catch { setTrace(null); }
  };

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const h = () => load();
    window.addEventListener(APP_EVENTS.RUN_COMPLETED, h);
    return () => window.removeEventListener(APP_EVENTS.RUN_COMPLETED, h);
  }, [load]);

  const pick = (run: RuntimeAuditTurn) => {
    if (sel?.run_id === run.run_id) { setSel(null); setTrace(null); }
    else { setSel(run); setTrace(null); setTab("overview"); loadTrace(run); }
  };

  const failInfo = useMemo(() => {
    if (!trace) return null;
    const fv = trace.find((e: any) => e.event_type === "turn_failed" || e.type === "turn_failed");
    if (!fv) return null;
    const d = evDetail(fv);
    const err = d.error || fv?.summary || String(d);
    let secs: number | null = null;
    const mr = trace.find((e: any) => /model.req/i.test(e.type || e.event_type || ""));
    const mp = trace.find((e: any) => /model.resp/i.test(e.type || e.event_type || ""));
    if (mr && mp) {
      const t0 = new Date(evTime(mr)).getTime();
      const t1 = new Date(evTime(mp)).getTime();
      if (t0 && t1) secs = Math.round((t1 - t0) / 1000);
    }
    return { error: String(err).slice(0, 200), timeoutSecs: secs };
  }, [trace]);

  const selectedStats = useMemo(
    () => deriveRunTraceStats(sel, trace),
    [sel, trace],
  );

  // ── Empty ──
  if (!loading && !error && runs.length === 0) {
    return (
      <div className="page">
        <div className="page-header" style={{ background: "var(--surface)" }}>
          <div>
            <h1>运行记录</h1>
            <p className="subtitle">查看 Agent 运行状态、详情与事件时间线</p>
          </div>
          <button className="btn sm ghost" onClick={load}><IconRefresh size={14} /></button>
        </div>
        <div className="page-body">
          <div className="hero">
            <div className="hero-mark">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
              </svg>
            </div>
            <h2 className="hero-title">暂无运行记录</h2>
            <p className="hero-sub">在对话区发起一次 Agent 交互后，运行记录将在这里展示。</p>
          </div>
        </div>
      </div>
    );
  }

  // ── Main ──
  return (
    <div className="page">
      <div className="page-header" style={{ background: "var(--surface)" }}>
        <div>
          <h1>运行记录<span style={{ color: "var(--ink-mute)", fontWeight: 400, fontSize: 14, marginLeft: 6 }}>· Runs</span></h1>
          <p className="subtitle">运行详情 · Trace 时间线 · 事件诊断</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
          <div className="status-pill"><span className="dot" style={{ background: "var(--accent)" }} />{runs.length} 条</div>
          <button className="btn sm ghost" onClick={load}><IconRefresh size={14} /></button>
        </div>
      </div>

      <div className="split-shell" style={{ flex: 1 }}>
        {/* Left list */}
        <aside style={{ padding: 12, overflow: "auto" }}>
          {error && <div style={{ padding: "8px 12px", margin: "0 4px 8px", color: "var(--danger)", background: "var(--danger-soft)", borderRadius: "var(--r-6)", fontSize: "var(--fs-12)", fontWeight: 650 }}>⚠ {error}</div>}
          {loading && <LoadingState text="加载中…" />}
          {!loading && runs.map((r) => {
            const active = sel?.run_id === r.run_id;
            return (
              <button key={r.run_id || r.turn_id} type="button"
                className="card" onClick={() => pick(r)}
                style={{
                  width: "100%", textAlign: "left", padding: "12px 14px", marginBottom: 6,
                  cursor: "pointer", borderColor: active ? "var(--accent)" : "var(--line)",
                  background: active ? "var(--accent-soft)" : "var(--surface)",
                }}>
                <div style={{ display: "flex", alignItems: "flex-start", gap: 8, marginBottom: 5 }}>
                  <StatusDot status={sDot(r.status || "")} />
                  <span style={{ flex: 1, fontSize: "var(--fs-13)", fontWeight: 680, lineHeight: 1.35, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {r.user_input_summary || r.intent || "(无摘要)"}
                  </span>
                  <Badge kind={sBadge(r.status || "")}>{sLabel(r.status || "")}</Badge>
                </div>
                <div style={{ display: "flex", gap: 8, marginLeft: 16, fontSize: "var(--fs-10)", color: "var(--text-4)" }}>
                  <span>{r.session_id?.substring(0, 8) || "-"}</span>
                  <span>{r.created_at ? new Date(r.created_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "-"}</span>
                  {Number(r.tool_call_count || 0) > 0 && <span>{r.tool_call_count} 工具</span>}
                  {Number(r.warning_count || 0) > 0 && <span>{r.warning_count} 警告</span>}
                  {Number(r.error_count || 0) > 0 && <span>{r.error_count} 错误</span>}
                </div>
              </button>
            );
          })}
        </aside>

        {/* Right detail */}
        <div className="split-detail" style={{ padding: "24px", overflow: "auto" }}>
          {!sel ? (
            <div className="empty" style={{ minHeight: "100%" }}>
              <div className="empty-icon" style={{ background: "var(--surface-2)" }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--text-4)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
                </svg>
              </div>
              <div className="empty-text" style={{ fontSize: "var(--fs-13)" }}>选择一条运行记录</div>
              <p className="empty-hint">点击左侧列表中的记录查看运行详情与事件时间线</p>
            </div>
          ) : (
            <div style={{ animation: "surface-in var(--dur-4) var(--ease-out) both" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
                <StatusDot status={sDot(sel.status || "")} />
                <h3 style={{ fontSize: "var(--fs-18)", fontWeight: 720, margin: 0 }}>运行详情</h3>
                <Badge kind={sBadge(sel.status || "")}>{sLabel(sel.status || "")}</Badge>
              </div>

              <div className="tabs" style={{ marginBottom: 16 }}>
                <button className={"tab" + (tab === "overview" ? " active" : "")} onClick={() => setTab("overview")}>概览</button>
                <button className={"tab" + (tab === "events" ? " active" : "")} onClick={() => setTab("events")}>事件时间线</button>
              </div>

              {tab === "overview" && (
                <>
                  <div className="card" style={{ padding: "16px 18px", marginBottom: 20 }}>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "12px 20px" }}>
                      <Info label="会话 ID" value={sel.session_id} mono />
                      <Info label="运行 ID" value={sel.turn_id || sel.run_id} mono />
                      <Info label="追踪 ID" value={sel.trace_id} mono />
                      <Info label="意图" value={sel.intent} />
                      <Info label="开始" value={selectedStats.startedAt} />
                      <Info label="结束" value={selectedStats.finishedAt} />
                      <Info label="工具调用" value={selectedStats.toolCallCount ? String(selectedStats.toolCallCount) : "-"} />
                      <Info label="错误" value={String(selectedStats.errorCount)} />
                      <Info label="警告" value={String(selectedStats.warningCount)} />
                    </div>
                  </div>

                  <TraceDetailPanel traceEvents={trace} selectedRun={sel} />

                  {(!trace || trace.length === 0) && !selectedStats.toolCallCount && (
                    <div style={{ padding: "40px 0", textAlign: "center", color: "var(--text-3)", fontSize: "var(--fs-12)" }}>暂无更多详情</div>
                  )}
                </>
              )}

              {tab === "events" && (
                <>
                  {!trace ? <LoadingState text="加载事件…" /> : (
                    <>
                      {failInfo && (
                        <div className="card" style={{ borderLeft: "3px solid var(--danger)", padding: "12px 14px", marginBottom: 16 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--danger)", fontWeight: 680, marginBottom: 4 }}>
                            <IconAlert size={14} /> 失败原因
                            {failInfo.timeoutSecs != null && <span style={{ color: "var(--text-3)", fontWeight: 400, fontSize: "var(--fs-12)" }}>· 耗时 {failInfo.timeoutSecs}s</span>}
                          </div>
                          <div style={{ color: "var(--text-2)", fontSize: "var(--fs-13)" }}>{failInfo.error}</div>
                        </div>
                      )}

                      <div className="section-head" style={{ justifyContent: "flex-start" }}>事件时间线 · {trace.length} 个事件</div>

                      {trace.length === 0 ? <EmptyState text="该运行无事件记录" /> : (
                        trace.map((ev: any, i: number) => {
                          const et = ev.event_type || ev.type || "unknown";
                          const dt = evDetail(ev);
                          const lb = evLabel(et, dt, ev);
                          const isFail = et === "turn_failed";
                          return (
                            <div key={ev.event_id || i} className="card" style={{ padding: "10px 14px", marginBottom: 8 }}>
                              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0, flex: 1 }}>
                                  <span style={{ width: 7, height: 7, borderRadius: "50%", background: isFail ? "var(--danger)" : "var(--ok)", flexShrink: 0 }} />
                                  <span style={{ fontSize: "var(--fs-13)", fontWeight: 650, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{lb}</span>
                                </div>
                                <span style={{ color: "var(--text-4)", fontSize: "var(--fs-11)", fontFamily: "var(--font-mono)", flexShrink: 0 }}>{evTime(ev)}</span>
                              </div>
                              <details style={{ marginTop: 6 }}>
                                <summary style={{ fontSize: "var(--fs-11)", color: "var(--text-3)", cursor: "pointer" }}>开发诊断 · {et}</summary>
                                <CodeBlock language="json">{JSON.stringify(dt, null, 2)}</CodeBlock>
                              </details>
                            </div>
                          );
                        })
                      )}
                    </>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Info({ label, value, mono }: { label: string; value?: string | null; mono?: boolean }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: "var(--fs-10)", color: "var(--text-4)", textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 680, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: "var(--fs-13)", color: "var(--text)", fontWeight: 620, fontFamily: mono ? "var(--font-mono)" : undefined, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{value || "—"}</div>
    </div>
  );
}
