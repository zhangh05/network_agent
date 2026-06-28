/**
 * RunsPage — 运行记录 (v3.3.2 去重)
 *
 * 定位：单次 Agent 执行的 trace/debug 视图。
 * 与 JobsPage 的分工：Jobs = 任务全貌（做了什么），Runs = 执行细节（怎么做的）。
 *
 * 支持 ?focus=run_id 从作业页面跳转过来直接选中目标 run。
 */
import { useEffect, useState, useCallback, useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { workspacesApi, runtimeAuditApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { useWorkbenchStore } from "../../stores/workbench";
import { Badge, StatusDot, EmptyState, LoadingState, CodeBlock } from "../../components/common";
import { IconRefresh, IconAlert } from "../../components/Icon";
import { TraceDetailPanel } from "../../components/TraceDetailPanel";
import { DecisionReportPanel } from "../../components/DecisionReportPanel";
import { APP_EVENTS } from "../../utils/appEvents";
import { deriveRunTraceStats } from "../../utils/runTraceStats";
import { formatEventTime, formatEventDetail, formatEventLabel } from "../../utils/runEvent";
import type { DecisionReport, RuntimeAuditTurn, AgentResult } from "../../types";

/* ── Status helpers ── */

const STATUS_LABEL: Record<string, string> = {
  ok: "成功", completed: "已完成", success: "成功",
  failed: "失败", error: "失败", running: "运行中",
  pending: "等待中", timeout: "超时", cancelled: "已取消",
};

/**
 * v3.9.1 fix: previously the list rendered `r.status` only, while the detail
 * rendered `r.ok`. They could disagree on legacy disk records (status was
 * stuck at "ok" because the write path read the wrong dict; see
 * workspace/run_store.py::_safe_status). Now we prefer the boolean truth —
 * `r.ok === false` is a hard "error" regardless of the legacy `status` string,
 * and `r.status` only supplements when `r.ok` is missing.
 *
 * For new runs (post-fix) `r.ok` and `r.status` agree; for old runs this
 * keeps the list honest.
 */
function effectiveStatus(run: RuntimeAuditTurn): string {
  // v3.9.1: r.ok is the runtime truth. If it's explicitly false, ignore the
  // legacy `status` string entirely (legacy records can have status="ok"
  // even when ok=false). If it's explicitly true, also return "ok" — we
  // don't trust the status string either way once the boolean is set.
  if (run.ok === false) return "error";
  if (run.ok === true) return "ok";
  // r.ok undefined (truly old records or non-AI jobs): fall back to status.
  return run.status || "ok";
}

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

/* ── Component ── */

export function RunsPage() {
  const { currentWorkspaceId, currentSessionId } = useSessionStore();
  const setLatestResult = useWorkbenchStore((s) => s.setLatestResult);
  const wsId = currentWorkspaceId;
  const [searchParams] = useSearchParams();
  const focusRunId = searchParams.get("focus") || null;
  const [runs, setRuns] = useState<RuntimeAuditTurn[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<RuntimeAuditTurn | null>(null);
  const [trace, setTrace] = useState<any[] | null>(null);
  const [decision, setDecision] = useState<DecisionReport | null>(null);
  const [decisionLoading, setDecisionLoading] = useState(false);
  const [decisionError, setDecisionError] = useState("");
  const [tab, setTab] = useState<"overview" | "events" | "decision">("overview");

  const load = useCallback(async () => {
    if (!wsId) {
      setRuns([]);
      setLoading(false);
      return;
    }
    setLoading(true); setError(null);
    try {
      const d = await workspacesApi.recentRuns(wsId, currentSessionId);
      setRuns(d.runs || []);
    }
    catch (e: any) { setError(e?.message || "加载失败"); }
    setLoading(false);
  }, [wsId, currentSessionId]);

  const loadTrace = async (run: RuntimeAuditTurn) => {
    const rid = run.run_id || run.turn_id;
    if (!rid) return;
    try { const d = await runtimeAuditApi.trace(wsId, rid); setTrace(d.events || []); }
    catch { setTrace(null); }
  };

  const loadDecision = async (run: RuntimeAuditTurn) => {
    const rid = run.run_id || run.turn_id;
    if (!rid) return;
    setDecisionLoading(true);
    setDecisionError("");
    try {
      const response = await runtimeAuditApi.decision(wsId, rid);
      setDecision(response.item || null);
    } catch (error: any) {
      setDecision(null);
      setDecisionError(error?.message || "该运行没有可读取的决策报告");
    } finally {
      setDecisionLoading(false);
    }
  };

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const h = () => load();
    window.addEventListener(APP_EVENTS.RUN_COMPLETED, h);
    return () => window.removeEventListener(APP_EVENTS.RUN_COMPLETED, h);
  }, [load]);

  // Auto-select run when navigated from Jobs page with ?focus=run_id
  //     or when F5 restores ?focus=<run_id>
  useEffect(() => {
    const targetId = focusRunId;
    if (!targetId || runs.length === 0) return;
    if (sel?.run_id === targetId) return; // already selected
    const target = runs.find((r) => (r.run_id || r.turn_id) === targetId);
    if (target) {
      setSel(target);
      setTrace(null);
      setDecision(null);
      setDecisionError("");
      setTab("overview");
      void loadTrace(target);
      void loadDecision(target);
      setLatestResult(buildAgentResult(target, wsId));
    }
  }, [focusRunId, runs]);

  // Clear selection when session changes
  useEffect(() => {
    setSel(null); setTrace(null); setDecision(null); setDecisionError("");
  }, [currentSessionId]);

  const pick = (run: RuntimeAuditTurn) => {
    if (sel?.run_id === run.run_id) {
      setSel(null);
      setTrace(null);
      setDecision(null);
      setDecisionError("");
    } else {
      setSel(run);
      setTrace(null);
      setDecision(null);
      setDecisionError("");
      setTab("overview");
      void loadTrace(run);
      void loadDecision(run);
      setLatestResult(buildAgentResult(run, wsId));
      // Persist via URL for F5 survival
      const url = new URL(window.location.href);
      url.searchParams.set("focus", run.run_id || run.turn_id || "");
      window.history.replaceState(null, "", url.toString());
    }
  };

  const failInfo = useMemo(() => {
    if (!trace) return null;
    const fv = trace.find((e: any) => e.event_type === "turn_failed" || e.type === "turn_failed");
    if (!fv) return null;
    const d = formatEventDetail(fv);
    const err = d.error || fv?.summary || String(d);
    let secs: number | null = null;
    const mr = trace.find((e: any) => /model.req/i.test(e.type || e.event_type || ""));
    const mp = trace.find((e: any) => /model.resp/i.test(e.type || e.event_type || ""));
    if (mr && mp) {
      const t0 = new Date(formatEventTime(mr)).getTime();
      const t1 = new Date(formatEventTime(mp)).getTime();
      if (t0 && t1) secs = Math.round((t1 - t0) / 1000);
    }
    return { error: String(err).slice(0, 200), timeoutSecs: secs };
  }, [trace]);

  const selectedStats = useMemo(
    () => deriveRunTraceStats(sel, trace),
    [sel, trace],
  );

  // ── No session selected ──
  if (!currentSessionId) {
    return (
      <div className="page">
        <div className="page-header" style={{ background: "var(--surface)" }}>
          <div>
            <h1>运行记录<span style={{ color: "var(--ink-mute)", fontWeight: 400, fontSize: 14, marginLeft: 6 }}>· Runs</span></h1>
            <p className="subtitle">请先在左侧选择一个会话</p>
          </div>
        </div>
        <div className="page-body">
          <div className="hero">
            <div className="hero-mark">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
              </svg>
            </div>
            <h2 className="hero-title">未选择会话</h2>
            <p className="hero-sub">请在左侧会话列表中选择一个会话，即可查看该会话内的 Agent 运行记录。</p>
          </div>
        </div>
      </div>
    );
  }

  // ── Empty ──
  if (!loading && !error && runs.length === 0) {
    return (
      <div className="page">
        <div className="page-header" style={{ background: "var(--surface)" }}>
          <div>
            <h1>运行记录<span style={{ color: "var(--ink-mute)", fontWeight: 400, fontSize: 14, marginLeft: 6 }}>· Runs</span></h1>
            <p className="subtitle">
              会话 {currentSessionId.slice(0, 12)} — 暂无运行记录
            </p>
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
            <p className="hero-sub">在该会话中发起对话后，运行记录将在这里展示。</p>
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
          <p className="subtitle">
            {currentSessionId
              ? `会话 ${currentSessionId.slice(0, 12)} · 运行详情 · Trace 时间线 · 决策报告`
              : "请先在左侧选择一个会话"}
          </p>
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
                  <StatusDot status={sDot(effectiveStatus(r))} />
                  <span style={{ flex: 1, fontSize: "var(--fs-13)", fontWeight: 680, lineHeight: 1.35, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {r.user_input_summary || r.intent || "(无摘要)"}
                  </span>
                  <Badge kind={sBadge(effectiveStatus(r))}>{sLabel(effectiveStatus(r))}</Badge>
                </div>
                <div style={{ display: "flex", gap: 8, marginLeft: 16, fontSize: "var(--fs-10)", color: "var(--text-4)" }}>
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
              <p className="empty-hint">点击左侧列表中的记录查看 trace 事件时间线与决策报告</p>
              <p style={{ fontSize: "var(--fs-11)", color: "var(--text-4)", marginTop: 16 }}>
                想看任务全貌？去 <Link to="/jobs" style={{ color: "var(--accent)" }}>作业管理 →</Link>
              </p>
            </div>
          ) : (
            <div style={{ animation: "surface-in var(--dur-4) var(--ease-out) both" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
                <StatusDot status={sDot(effectiveStatus(sel))} />
                <h3 style={{ fontSize: "var(--fs-18)", fontWeight: 720, margin: 0 }}>运行详情</h3>
                <Badge kind={sBadge(effectiveStatus(sel))}>{sLabel(effectiveStatus(sel))}</Badge>
              </div>

              <div className="tabs" style={{ marginBottom: 16 }}>
                <button className={"tab" + (tab === "overview" ? " active" : "")} onClick={() => setTab("overview")}>概览</button>
                <button className={"tab" + (tab === "events" ? " active" : "")} onClick={() => setTab("events")}>事件时间线</button>
                <button className={"tab" + (tab === "decision" ? " active" : "")} onClick={() => setTab("decision")}>决策</button>
              </div>

              {tab === "overview" && (
                <>
                  <div className="card" style={{ padding: "16px 18px", marginBottom: 20 }}>
                    <div style={{ display: "grid", gridTemplateColumns: "120px 1fr 120px 1fr", gap: "6px 20px", alignItems: "center" }}>
                      <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 680 }}>运行 ID</span>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sel.turn_id || sel.run_id || "—"}</span>
                      <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 680 }}>追踪 ID</span>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sel.trace_id || "—"}</span>
                      <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 680 }}>意图</span>
                      <span style={{ fontSize: 13, overflow: "hidden", textOverflow: "ellipsis" }}>{sel.intent || "—"}</span>
                      <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 680 }}>能力</span>
                      <span style={{ fontSize: 13 }}>{sel.capability || "—"}</span>
                      <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 680 }}>开始</span>
                      <span style={{ fontSize: 13 }}>{selectedStats.startedAt || "—"}</span>
                      <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 680 }}>结束</span>
                      <span style={{ fontSize: 13 }}>{selectedStats.finishedAt || "—"}</span>
                      <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 680 }}>工具调用</span>
                      <span style={{ fontSize: 13 }}>{selectedStats.toolCallCount || 0}</span>
                      <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 680 }}>状态</span>
                      <span>{sel.ok ? <Badge kind="ok" withDot>ok</Badge> : <Badge kind="err" withDot>failed</Badge>}</span>
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
                          const dt = formatEventDetail(ev);
                          const lb = formatEventLabel(ev);
                          const isFail = et === "turn_failed";
                          return (
                            <div key={ev.event_id || i} className="card" style={{ padding: "10px 14px", marginBottom: 8 }}>
                              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0, flex: 1 }}>
                                  <span style={{ width: 7, height: 7, borderRadius: "50%", background: isFail ? "var(--danger)" : "var(--ok)", flexShrink: 0 }} />
                                  <span style={{ fontSize: "var(--fs-13)", fontWeight: 650, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{lb}</span>
                                </div>
                                <span style={{ color: "var(--text-4)", fontSize: "var(--fs-11)", fontFamily: "var(--font-mono)", flexShrink: 0 }}>{formatEventTime(ev)}</span>
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

              {tab === "decision" && (
                <DecisionReportPanel
                  report={decision}
                  loading={decisionLoading}
                  error={decisionError}
                />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** Convert RuntimeAuditTurn → AgentResult so Inspector can display it. */
function buildAgentResult(run: RuntimeAuditTurn, workspaceId: string): AgentResult {
  // v3.9.1: prefer `run.ok` over the legacy status string. The disk record
  // may have status="ok" but ok=false (legacy bug); we want the truth here.
  const truthyOk =
    typeof run.ok === "boolean"
      ? run.ok
      : /ok|completed|success/i.test(run.status || "");
  return {
    ok: truthyOk,
    final_response: "",
    events: (run.events || []) as any[],
    trace_id: run.trace_id || "",
    session_id: run.session_id || "",
    turn_id: run.turn_id || "",
    tool_calls: [],
    warnings: [],
    errors: [],
    tool_decision: run.tool_decision,
    no_tool_reason: run.no_tool_reason,
    metadata: {
      selected_capabilities: run.selected_capabilities,
      selected_skills: run.selected_skills,
      visible_tools: run.visible_tools,
      source_count: 0,
      workspace_id: workspaceId,
    },
  };
}
