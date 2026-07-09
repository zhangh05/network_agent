/**
 * OperationsPage — 运行与作业（合并页, v3.4）
 *
 * 合并原 RunsPage（运行记录）与 JobsPage（作业管理）为一个界面：
 *   - 左栏：作业列表（工作区维度，含所有 job 类型 + 重试/恢复动作）
 *   - 右栏：选中作业 → 概要 / 运行记录 / 统计 三 tab
 *          运行记录中点击某 run → 内联展开 trace / 事件时间线 / 失败原因
 *
 * 这样消除了原来的跨页跳转（Jobs → /runs?focus=）和重复的 run 列表。
 * 与旧版的分工保持不变：Jobs = 任务全貌（做了什么），Runs = 执行细节（怎么做的）。
 */
import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { jobsApi, workspacesApi, sessionExtApi, runtimeAuditApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { APP_EVENTS } from "../../utils/appEvents";
import { useToastStore } from "../../stores/toast";
import { Badge, StatusDot, EmptyState, LoadingState, CodeBlock } from "../../components/common";
import { IconRefresh, IconDocument, IconHistory, IconBolt, IconAlert } from "../../components/Icon";
import { TraceDetailPanel } from "../../components/TraceDetailPanel";
import { deriveRunTraceStats } from "../../utils/runTraceStats";
import { formatEventTime, formatEventDetail, formatEventLabel } from "../../utils/runEvent";
import { formatDate } from "../../utils/format";
import { formatCompactDate } from "../../utils/displayText";
import { isApiError } from "../../types";
import type { RuntimeAuditTurn } from "../../types";

/* ── Types ── */

type JobItem = {
  job_id: string;
  job_type: string;
  status: string;
  title?: string;
  description?: string;
  created_at?: string;
  updated_at?: string;
  started_at?: string;
  finished_at?: string;
  workspace_id?: string;
  payload?: Record<string, unknown>;
  run_ids?: string[];
  progress?: { current: number; total: number; percent: number; message: string };
  error?: string;
};

/** Extract session_id from nested payload */
function getSessionId(job: JobItem): string {
  return String(job.payload?.session_id ?? "");
}

/* ── Labels ── */

const JOB_TYPE_LABELS: Record<string, string> = {
  agent_run: "Agent 对话",
  translate_config: "配置翻译",
  export_report: "报告导出",
  batch_translate_config: "批量翻译",
  topology_build: "拓扑构建",
  inspection_analyze: "巡检分析",
  knowledge_index: "知识索引",
};

const JOB_TYPE_ICONS: Record<string, typeof IconHistory> = {
  agent_run: IconHistory,
  translate_config: IconDocument,
  export_report: IconBolt,
};

const STATUS_META: Record<string, { kind: "ok" | "err" | "warn" | "muted"; label: string; dot: "ok" | "err" | "warn" | "idle" }> = {
  succeeded: { kind: "ok", label: "已完成", dot: "ok" },
  completed: { kind: "ok", label: "已完成", dot: "ok" },
  success: { kind: "ok", label: "成功", dot: "ok" },
  ok: { kind: "ok", label: "正常", dot: "ok" },
  failed: { kind: "err", label: "失败", dot: "err" },
  error: { kind: "err", label: "错误", dot: "err" },
  running: { kind: "warn", label: "进行中", dot: "warn" },
  pending: { kind: "warn", label: "等待中", dot: "warn" },
  queued: { kind: "warn", label: "排队中", dot: "warn" },
  created: { kind: "muted", label: "待启动", dot: "idle" },
  cancelled: { kind: "muted", label: "已取消", dot: "idle" },
  archived: { kind: "muted", label: "已归档", dot: "idle" },
};

/* ── Helpers ── */

function sMeta(s: string) { return STATUS_META[s] || { kind: "muted" as const, label: s || "未知", dot: "idle" as const }; }

function calcDuration(start?: string, end?: string): string | null {
  if (!start) return null;
  const t0 = new Date(start).getTime();
  const t1 = end ? new Date(end).getTime() : Date.now();
  const secs = Math.round((t1 - t0) / 1000);
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

/** Run-level status (ported from RunsPage: prefer r.ok truth). */
function effectiveStatus(run: RuntimeAuditTurn): string {
  if (run.ok === false) return "error";
  if (run.ok === true) return "ok";
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
function sLabel(s: string): string {
  const M: Record<string, string> = { ok: "成功", completed: "已完成", success: "成功", failed: "失败", error: "失败", running: "运行中", pending: "等待中", timeout: "超时", cancelled: "已取消" };
  return M[s] || s || "未知";
}

/* ── Component ── */

export function OperationsPage() {
  const { currentWorkspaceId } = useSessionStore();
  const toast = useToastStore((s) => s.show);
  const wsId = currentWorkspaceId;
  const [searchParams] = useSearchParams();

  const [jobs, setJobs] = useState<JobItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedJob, setSelectedJob] = useState<JobItem | null>(null);
  const [jobTab, setJobTab] = useState<"overview" | "stats" | "summary">("overview");

  const [runs, setRuns] = useState<RuntimeAuditTurn[] | null>(null);
  const [runsLoading, setRunsLoading] = useState(false);

  // Drilled-in run (inline trace replaces job detail in the right pane)
  const [selRun, setSelRun] = useState<RuntimeAuditTurn | null>(null);
  const [trace, setTrace] = useState<any[] | null>(null);
  const [runTab, setRunTab] = useState<"overview" | "events">("overview");

  const loadJobs = useCallback(async () => {
    if (!wsId) { setJobs([]); setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const data = await jobsApi.list(wsId);
      setJobs((data?.jobs ?? []) as JobItem[]);
    } catch (e: unknown) {
      setError(isApiError(e) ? e.message : String(e));
    }
    setLoading(false);
  }, [wsId]);

  useEffect(() => { loadJobs(); }, [loadJobs]);

  // Cross-page linkage: any session lifecycle change (archive / restore / delete / rename)
  // bumps sessionListVersion; refresh the jobs list so it stays in sync with the sidebar.
  const loadJobsRef = useRef(loadJobs);
  loadJobsRef.current = loadJobs;
  const sessionListVersion = useSessionStore((s) => s.sessionListVersion);
  const firstSessionBump = useRef(true);
  useEffect(() => {
    if (firstSessionBump.current) { firstSessionBump.current = false; return; }
    loadJobsRef.current();
  }, [sessionListVersion]);

  // Reload the selected job's runs WITHOUT collapsing the panel (selectJob toggles off
  // when called with the same job and no focusRunId). Kept in a ref so the run-completed
  // listener below always sees the latest selection.
  const selectedJobRef = useRef(selectedJob);
  selectedJobRef.current = selectedJob;
  const reloadJobRuns = useCallback(async () => {
    const job = selectedJobRef.current;
    if (!job) return;
    const sid = getSessionId(job);
    if (!sid) return;
    setRunsLoading(true);
    try {
      const d = await workspacesApi.recentRuns(wsId, sid);
      setRuns((d?.runs ?? []) as RuntimeAuditTurn[]);
    } catch { /* keep last known runs */ }
    finally { setRunsLoading(false); }
  }, [wsId]);
  const reloadJobRunsRef = useRef(reloadJobRuns);
  reloadJobRunsRef.current = reloadJobRuns;

  // Live linkage: when an agent run completes anywhere, refresh the jobs list and the
  // open job's runs so statuses stay current — mirrors what Sidebar + RuntimeAudit already do.
  useEffect(() => {
    const onRunCompleted = () => {
      loadJobsRef.current();
      reloadJobRunsRef.current();
    };
    window.addEventListener(APP_EVENTS.RUN_COMPLETED, onRunCompleted);
    return () => window.removeEventListener(APP_EVENTS.RUN_COMPLETED, onRunCompleted);
  }, []);

  // Self-healing reactivity for jobs that complete OUTSIDE the conversation flow
  // (export_report / translate_config / topology_build / knowledge_index and
  // backend-scheduled runs). These never emit RUN_COMPLETED, so we poll the job
  // list only while at least one job is in a transient state, then stop.
  const TRANSIENT_JOB_STATUS = new Set([
    "running", "pending", "queued", "in_progress",
    "executing", "scheduled", "dispatching", "waiting",
  ]);
  const hasTransientJob = useMemo(
    () => jobs.some((j) =>
      TRANSIENT_JOB_STATUS.has(String(j.status || "").toLowerCase())),
    [jobs],
  );
  useEffect(() => {
    if (!hasTransientJob || !wsId) return;
    const id = window.setInterval(() => loadJobsRef.current(), 3000);
    return () => window.clearInterval(id);
  }, [hasTransientJob, wsId]);

  /** Select a job and load its runs (if it backs a session). */
  const selectJob = useCallback(async (job: JobItem, focusRunId?: string | null) => {
    if (selectedJob?.job_id === job.job_id && !focusRunId) {
      setSelectedJob(null); setRuns(null); setSelRun(null); setTrace(null);
      return;
    }
    setSelectedJob(job);
    setJobTab("overview"); setRuns(null); setSelRun(null); setTrace(null);

    const sid = getSessionId(job);
    if (sid) {
      setRunsLoading(true);
      try {
        const d = await workspacesApi.recentRuns(wsId, sid);
        // 加载 session 全部 runs，不做过滤
        const list = (d?.runs ?? []) as RuntimeAuditTurn[];
        setRuns(list);
        if (focusRunId) {
          const target = list.find((r) => (r.run_id || r.turn_id) === focusRunId);
          if (target) openRun(target);
        }
      } catch { setRuns([]); }
      finally { setRunsLoading(false); }
    } else {
      setRuns([]);
    }
  }, [selectedJob, wsId]);

  const openRun = useCallback(async (run: RuntimeAuditTurn) => {
    const rid = run.run_id || run.turn_id;
    if (!rid) return;
    setSelRun(run); setTrace(null); setRunTab("overview");
    try { const d = await runtimeAuditApi.trace(wsId, rid); setTrace(d.events || []); }
    catch { setTrace(null); }
  }, [wsId]);

  const backToJob = useCallback(() => { setSelRun(null); setTrace(null); }, []);

  // Deep-link: ?job=<id> and/or ?focus=<run_id>
  useEffect(() => {
    if (jobs.length === 0) return;
    const jobId = searchParams.get("job");
    const focus = searchParams.get("focus");
    if (jobId) {
      const j = jobs.find((x) => x.job_id === jobId);
      if (j) void selectJob(j, focus);
      return;
    }
    if (focus) {
      // Best-effort: scan agent_run jobs' sessions for the run.
      const candidates = jobs.filter((j) => j.job_type === "agent_run").slice(0, 12);
      (async () => {
        for (const j of candidates) {
          const sid = getSessionId(j);
          if (!sid) continue;
          try {
            const d = await workspacesApi.recentRuns(wsId, sid);
            const list = (d?.runs ?? []) as RuntimeAuditTurn[];
            const target = list.find((r) => (r.run_id || r.turn_id) === focus);
            if (target) { setSelectedJob(j); setJobTab("overview"); setRuns(list); await openRun(target); return; }
          } catch { /* keep scanning */ }
        }
      })();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs]);

  // Aggregated stats — runCount 用实际加载的 runs 数量
  const stats = useMemo(() => {
    const runList = runs ?? [];
    const totalTools = runList.reduce((s, r) => s + (r.tool_call_count ?? 0), 0);
    const totalErrors = runList.reduce((s, r) => s + (r.error_count ?? 0), 0);
    return { runCount: runList.length, totalTools, totalErrors };
  }, [runs]);

  const duration = useMemo(
    () => selectedJob ? calcDuration(selectedJob.started_at, selectedJob.finished_at) : null,
    [selectedJob],
  );

  // ── Cancel / Retry / Restore ──
  const handleRetry = async (job_id: string) => {
    try { await jobsApi.retry(job_id, wsId); toast({ kind: "success", title: "已重试" }); loadJobs(); }
    catch (e: unknown) { toast({ kind: "error", title: "重试失败", body: isApiError(e) ? e.message : String(e) }); }
  };
  const handleRestore = async (job: JobItem) => {
    const sid = getSessionId(job);
    if (!sid) return;
    try { await sessionExtApi.restore(sid, wsId); useSessionStore.getState().bumpSessionList(); toast({ kind: "success", title: "会话已恢复" }); }
    catch (e: unknown) { toast({ kind: "error", title: "恢复失败", body: isApiError(e) ? e.message : String(e) }); }
  };
  const canRestore = (job: JobItem): boolean => {
    const sid = getSessionId(job);
    if (!sid) return false;
    return ["succeeded", "completed", "failed", "cancelled"].includes(job.status);
  };

  // ── Empty state ──
  if (!loading && !error && jobs.length === 0) {
    return (
      <div className="page">
        <PageHeader count={0} onRefresh={loadJobs} />
        <div className="page-body">
          <div className="hero">
            <div className="hero-mark" style={{ fontSize: 22, fontWeight: 700 }}>
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
                <line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" />
              </svg>
            </div>
            <h2 className="hero-title">暂无作业</h2>
            <p className="hero-sub">在工作台发起对话或执行任务后，每个会话/任务将自动生成作业，在此追踪运行与产出。</p>
          </div>
        </div>
      </div>
    );
  }

  // ── Main ──
  return (
    <div className="page">
      <PageHeader count={jobs.length} onRefresh={loadJobs} />

      {error && (
        <div style={{ margin: "12px 24px 0", padding: "10px 14px", color: "var(--danger)", background: "var(--danger-soft)", borderRadius: "var(--r-6)", fontSize: "var(--fs-13)", fontWeight: 650 }}>
          ⚠ {error}
        </div>
      )}

      {loading ? (
        <div className="page-body"><LoadingState text="加载作业列表…" /></div>
      ) : (
        <div className="split-shell" style={{ flex: 1 }}>
          {/* ══════ 左侧 作业列表 ══════ */}
          <aside className="list-scroll jobs-list" style={{ padding: 12, overflow: "auto" }}>
            {jobs.map((job) => {
              const meta = sMeta(job.status);
              const active = selectedJob?.job_id === job.job_id;
              const TypeIcon = JOB_TYPE_ICONS[job.job_type] || IconBolt;
              return (
                <button
                  key={job.job_id}
                  type="button"
                  className="job-card"
                  onClick={() => void selectJob(job)}
                  style={{
                    width: "100%", textAlign: "left", cursor: "pointer",
                    background: active ? "var(--accent-soft)" : "var(--surface)",
                    border: active ? "1px solid var(--accent)" : "1px solid var(--line)",
                  }}
                >
                  <div className="job-card-head">
                    <StatusDot status={meta.dot} />
                    <span className="job-card-title">{job.title || job.job_id?.slice(0, 12)}</span>
                    <Badge kind={meta.kind}>{meta.label}</Badge>
                  </div>
                  <div className="job-card-meta">
                    <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <TypeIcon size={11} style={{ opacity: 0.6 }} />
                      {JOB_TYPE_LABELS[job.job_type] || job.job_type}
                    </span>
                    {job.created_at && <span>{formatCompactDate(job.created_at)}</span>}
                    {duration && job.job_id === selectedJob?.job_id && <span>{duration}</span>}
                  </div>
                  {job.run_ids && job.run_ids.length > 0 && (
                    <div className="job-card-meta">
                      <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                        <IconHistory size={11} style={{ opacity: 0.6 }} />
                        {job.run_ids.length} 轮对话
                      </span>
                    </div>
                  )}
                  {job.error && (
                    <div className="job-card-meta">
                      <span style={{ color: "var(--danger)", fontSize: "var(--fs-11)" }}>{job.error.slice(0, 60)}</span>
                    </div>
                  )}
                  <div className="job-card-actions">
                    {(job.status === "failed" || job.status === "error") && (
                      <button className="btn sm" onClick={(e) => { e.stopPropagation(); handleRetry(job.job_id); }} type="button">重试</button>
                    )}
                    {canRestore(job) && (
                      <button className="btn sm ghost" onClick={(e) => { e.stopPropagation(); handleRestore(job); }} type="button">恢复</button>
                    )}
                  </div>
                </button>
              );
            })}
          </aside>

          {/* ══════ 右侧 详情 / run trace ══════ */}
          {selRun ? (
            <RunTraceView
              run={selRun}
              trace={trace}
              tab={runTab}
              setTab={setRunTab}
              onBack={backToJob}
            />
          ) : (
            <JobDetail
              job={selectedJob}
              jobTab={jobTab}
              setJobTab={setJobTab}
              runs={runs}
              runsLoading={runsLoading}
              stats={stats}
              duration={duration}
              onOpenRun={openRun}
              onRetry={handleRetry}
              onRestore={handleRestore}
            />
          )}
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════
   Sub-components
   ═══════════════════════════════════════════════════════ */

function PageHeader({ count, onRefresh }: { count: number; onRefresh: () => void }) {
  return (
    <div className="page-header" style={{ background: "var(--surface)" }}>
      <div>
        <h1>运行与作业<span style={{ color: "var(--ink-mute)", fontWeight: 400, fontSize: 14, marginLeft: 6 }}>· Operations</span></h1>
        <p className="subtitle">任务全貌与执行细节：作业追踪、运行记录、Trace 调试</p>
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
        {count > 0 && (
          <div className="status-pill"><span className="dot" style={{ background: "var(--accent)" }} />{count} 项</div>
        )}
        <button className="btn sm ghost" onClick={onRefresh} title="刷新"><IconRefresh size={14} /></button>
      </div>
    </div>
  );
}

/* ── Job detail (right pane) ── */

function JobDetail({
  job, jobTab, setJobTab, runs, runsLoading, stats, duration,
  onOpenRun, onRetry, onRestore,
}: {
  job: JobItem | null;
  jobTab: "overview" | "stats" | "summary";
  setJobTab: (t: "overview" | "stats" | "summary") => void;
  runs: RuntimeAuditTurn[] | null;
  runsLoading: boolean;
  stats: { runCount: number; totalTools: number; totalErrors: number };
  duration: string | null;
  onOpenRun: (r: RuntimeAuditTurn) => void;
  onRetry: (id: string) => void;
  onRestore: (job: JobItem) => void;
}) {
  if (!job) {
    return (
      <div className="split-detail" style={{ padding: "24px", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div className="empty" style={{ textAlign: "center" }}>
          <div className="empty-icon" style={{ background: "var(--surface-2)" }}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--text-4)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2" /><line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" />
            </svg>
          </div>
          <div className="empty-text" style={{ fontSize: "var(--fs-14)", fontWeight: 680 }}>选择一个作业</div>
          <p className="empty-hint" style={{ maxWidth: 280 }}>点击左侧列表中的作业，查看运行记录、统计与任务概要。</p>
        </div>
      </div>
    );
  }

  const meta = sMeta(job.status);

  return (
    <div className="split-detail" style={{ padding: "24px", overflow: "auto", animation: "surface-in var(--dur-4) var(--ease-out) both" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
        <StatusDot status={meta.dot} />
        <h3 style={{ fontSize: "var(--fs-18)", fontWeight: 720, margin: 0, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {job.title || job.job_id?.slice(0, 12)}
        </h3>
        <Badge kind={meta.kind}>{meta.label}</Badge>
        <Badge kind="muted">{JOB_TYPE_LABELS[job.job_type] || job.job_type}</Badge>
      </div>

      {(stats.runCount > 0 || duration || getSessionId(job)) && (
        <div style={{
          display: "flex", gap: 14, flexWrap: "wrap", padding: "10px 14px",
          background: "var(--surface-2)", borderRadius: "var(--r-8)", marginBottom: 16,
          fontSize: "var(--fs-12)", color: "var(--text-3)", border: "1px solid var(--line-2)",
        }}>
          {getSessionId(job) && <QuickStat label="会话" value={getSessionId(job).slice(0, 12)} mono />}
          {stats.runCount > 0 && <QuickStat label="对话轮数" value={String(stats.runCount)} />}
          {duration && <QuickStat label="耗时" value={duration} />}
          {stats.totalTools > 0 && <QuickStat label="工具调用" value={String(stats.totalTools)} />}
          {stats.totalErrors > 0 && <QuickStat label="错误" value={String(stats.totalErrors)} danger />}
        </div>
      )}

      {((job.status === "failed" || job.status === "error") || (getSessionId(job) && ["succeeded", "completed", "cancelled"].includes(job.status))) && (
        <div style={{ marginBottom: 14, display: "flex", gap: 8 }}>
          {(job.status === "failed" || job.status === "error") && (
            <button className="btn sm" onClick={() => onRetry(job.job_id)}>重试</button>
          )}
          {getSessionId(job) && ["succeeded", "completed", "cancelled"].includes(job.status) && (
            <button className="btn sm ghost" onClick={() => onRestore(job)}>恢复</button>
          )}
        </div>
      )}

      <div className="tabs" style={{ marginBottom: 16 }}>
        <button className={"tab" + (jobTab === "overview" ? " active" : "")} onClick={() => setJobTab("overview")}>
          运行记录 {stats.runCount > 0 && <span style={{ opacity: 0.5, marginLeft: 4 }}>{stats.runCount}</span>}
        </button>
        <button className={"tab" + (jobTab === "stats" ? " active" : "")} onClick={() => setJobTab("stats")}>统计</button>
        <button className={"tab" + (jobTab === "summary" ? " active" : "")} onClick={() => setJobTab("summary")}>概要</button>
      </div>

      {jobTab === "overview" && (
        <TabRuns runs={runs} runsLoading={runsLoading} onOpenRun={onOpenRun} job={job} />
      )}
      {jobTab === "stats" && (
        <TabStats job={job} runs={runs} runsLoading={runsLoading} stats={stats} duration={duration} />
      )}
      {jobTab === "summary" && <TabSummary job={job} />}
    </div>
  );
}

function QuickStat({ label, value, mono, danger }: { label: string; value: string; mono?: boolean; danger?: boolean }) {
  return (
    <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
      <span style={{ color: "var(--text-4)", fontSize: "var(--fs-10)" }}>{label}</span>
      <span style={{ fontWeight: 680, color: danger ? "var(--danger)" : "var(--text-2)", fontFamily: mono ? "var(--font-mono)" : undefined }}>{value}</span>
    </span>
  );
}

/* ── Tab: 运行记录 ── */

function TabRuns({ job, runs, runsLoading, onOpenRun }: { job: JobItem; runs: RuntimeAuditTurn[] | null; runsLoading: boolean; onOpenRun: (r: RuntimeAuditTurn) => void; }) {
  if (runsLoading) return <LoadingState text="加载运行记录…" />;
  if (!runs || runs.length === 0) {
    return <EmptyState text={getSessionId(job) ? "该会话暂无运行记录" : "非会话作业（如报告导出），无运行记录"} />;
  }
  return (
    <div>
      <div className="section-head" style={{ marginBottom: 10 }}>共 {runs.length} 轮对话</div>
      {runs.map((r, i) => (
        <button
          key={r.run_id || r.turn_id || i}
          type="button"
          onClick={() => onOpenRun(r)}
          className="card"
          style={{
            width: "100%", textAlign: "left", padding: "12px 14px", marginBottom: 6,
            cursor: "pointer", display: "flex", alignItems: "center", gap: 10,
            background: "var(--surface)", border: "1px solid var(--line)",
          }}
        >
          <span style={{
            width: 24, height: 24, borderRadius: "50%",
            background: "var(--surface-2)", display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: "var(--fs-10)", fontWeight: 700, color: "var(--text-4)", flexShrink: 0,
          }}>{runs.length - i}</span>
          <span style={{ flex: 1, fontSize: "var(--fs-13)", fontWeight: 620, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 }}>
            {r.user_input_summary || r.intent || "(无摘要)"}
          </span>
          <Badge kind={sBadge(effectiveStatus(r))}>{sLabel(effectiveStatus(r))}</Badge>
          {(r.tool_call_count ?? 0) > 0 && (
            <span style={{ fontSize: "var(--fs-11)", color: "var(--text-4)", whiteSpace: "nowrap" }}>{r.tool_call_count} 工具</span>
          )}
          {r.created_at && (
            <span style={{ fontSize: "var(--fs-11)", color: "var(--text-4)", whiteSpace: "nowrap" }}>{formatCompactDate(r.created_at)}</span>
          )}
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--text-4)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </button>
      ))}
    </div>
  );
}

/* ── Tab: 统计 ── */

function TabStats({ job, runs, runsLoading, stats, duration }: {
  job: JobItem; runs: RuntimeAuditTurn[] | null; runsLoading: boolean;
  stats: { runCount: number; totalTools: number; totalErrors: number }; duration: string | null;
}) {
  const runList = runs ?? [];
  const succeededRuns = runList.filter((r) => /ok|completed|success/i.test(r.status || "")).length;
  const failedRuns = runList.filter((r) => /fail|error/i.test(r.status || "")).length;
  const toolDist = runList.map((r) => r.tool_call_count ?? 0).filter((c) => c > 0);
  const maxTools = toolDist.length > 0 ? Math.max(...toolDist) : 0;
  const avgTools = toolDist.length > 0 ? (toolDist.reduce((a, b) => a + b, 0) / toolDist.length).toFixed(1) : "0";

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "10px", marginBottom: 20 }}>
        <StatCard label="会话 ID" value={getSessionId(job).slice(0, 16) || "-"} mono />
        <StatCard label="作业 ID" value={job.job_id.slice(0, 12)} mono />
        <StatCard label="类型" value={JOB_TYPE_LABELS[job.job_type] || job.job_type} />
        <StatCard label="状态" value={sMeta(job.status).label} />
        <StatCard label="耗时" value={duration || "-"} />
      </div>

      <div className="section-head" style={{ marginBottom: 10 }}>执行统计</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))", gap: "8px", marginBottom: 20 }}>
        <StatCard label="总轮数" value={String(stats.runCount)} highlight />
        <StatCard label="成功" value={String(succeededRuns)} highlight ok />
        <StatCard label="失败" value={String(failedRuns)} highlight danger={failedRuns > 0} />
        <StatCard label="工具调用" value={String(stats.totalTools)} />
        <StatCard label="单轮最多" value={String(maxTools)} />
        <StatCard label="单轮平均" value={avgTools} />
      </div>

      <div className="section-head" style={{ marginBottom: 10 }}>时间线</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: "8px", fontSize: "var(--fs-12)", color: "var(--text-3)", marginBottom: 20 }}>
        <div>创建：{formatCompactDate(job.created_at) || "-"}</div>
        <div>开始：{formatCompactDate(job.started_at) || "-"}</div>
        <div>结束：{formatCompactDate(job.finished_at) || "-"}</div>
        <div>更新：{formatCompactDate(job.updated_at) || "-"}</div>
      </div>

      {runList.length > 0 && (
        <>
          <div className="section-head" style={{ marginBottom: 10 }}>各轮耗时</div>
          {runList.map((r, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", background: "var(--surface-2)", borderRadius: "var(--r-4)", marginBottom: 4, fontSize: "var(--fs-11)", color: "var(--text-3)" }}>
              <span style={{ fontWeight: 680, width: 30 }}>#{runList.length - i}</span>
              <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.user_input_summary || r.intent || "(无摘要)"}</span>
              <Badge kind={sBadge(effectiveStatus(r))}>{sLabel(effectiveStatus(r))}</Badge>
              {r.tool_call_count ? <span>{r.tool_call_count} 工具</span> : null}
              <span>{r.created_at ? formatCompactDate(r.created_at) : "-"}</span>
            </div>
          ))}
        </>
      )}
      {runsLoading && <LoadingState text="加载运行数据…" />}
    </div>
  );
}

/* ── Tab: 概要 ── */

function TabSummary({ job }: { job: JobItem }) {
  const rows: Array<[string, string]> = [
    ["作业 ID", job.job_id],
    ["类型", JOB_TYPE_LABELS[job.job_type] || job.job_type],
    ["状态", sMeta(job.status).label],
    ["会话 ID", getSessionId(job) || "—"],
    ["工作区", job.workspace_id || "—"],
    ["创建", formatCompactDate(job.created_at) || "—"],
    ["开始", formatCompactDate(job.started_at) || "—"],
    ["结束", formatCompactDate(job.finished_at) || "—"],
    ["更新", formatCompactDate(job.updated_at) || "—"],
  ];
  if (job.progress) rows.push(["进度", `${job.progress.current}/${job.progress.total} (${job.progress.percent}%) · ${job.progress.message || ""}`]);
  if (job.error) rows.push(["错误", job.error]);

  return (
    <div className="card" style={{ padding: "16px 18px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: "8px 16px", alignItems: "center" }}>
        {rows.map(([k, v]) => (
          <FragmentRow key={k} label={k} value={v} danger={k === "错误"} />
        ))}
      </div>
    </div>
  );
}

function FragmentRow({ label, value, danger }: { label: string; value: string; danger?: boolean }) {
  return (
    <>
      <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 680 }}>{label}</span>
      <span style={{ fontSize: 13, color: danger ? "var(--danger)" : "var(--text-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{value}</span>
    </>
  );
}

function StatCard({ label, value, mono, highlight, ok, danger }: {
  label: string; value: string; mono?: boolean; highlight?: boolean; ok?: boolean; danger?: boolean;
}) {
  let color = "var(--text-2)";
  if (ok) color = "var(--ok)";
  if (danger) color = "var(--danger)";
  return (
    <div style={{ padding: "10px 14px", background: "var(--surface-2)", borderRadius: "var(--r-8)", border: "1px solid var(--line-2)" }}>
      <div style={{ fontSize: "var(--fs-10)", color: "var(--text-4)", textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: 680, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: highlight ? "var(--fs-16)" : "var(--fs-13)", fontWeight: 720, color, fontFamily: mono ? "var(--font-mono)" : undefined, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{value}</div>
    </div>
  );
}

/* ── Run trace (right pane, drilled in) ── */

function RunTraceView({ run, trace, tab, setTab, onBack }: {
  run: RuntimeAuditTurn;
  trace: any[] | null;
  tab: "overview" | "events";
  setTab: (t: "overview" | "events") => void;
  onBack: () => void;
}) {
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

  const selectedStats = useMemo(() => deriveRunTraceStats(run, trace), [run, trace]);

  return (
    <div className="split-detail" style={{ padding: "24px", overflow: "auto", animation: "surface-in var(--dur-4) var(--ease-out) both" }}>
      <button className="btn sm ghost" onClick={onBack} style={{ marginBottom: 14 }}>
        ← 返回作业
      </button>

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
        <StatusDot status={sDot(effectiveStatus(run))} />
        <h3 style={{ fontSize: "var(--fs-18)", fontWeight: 720, margin: 0, flex: 1 }}>运行详情</h3>
        <Badge kind={sBadge(effectiveStatus(run))}>{sLabel(effectiveStatus(run))}</Badge>
      </div>

      <div className="tabs" style={{ marginBottom: 16 }}>
        <button className={"tab" + (tab === "overview" ? " active" : "")} onClick={() => setTab("overview")}>概览</button>
        <button className={"tab" + (tab === "events" ? " active" : "")} onClick={() => setTab("events")}>事件时间线</button>
      </div>

      {tab === "overview" && (
        <>
          <div className="card" style={{ padding: "16px 18px", marginBottom: 20 }}>
            <div style={{ display: "grid", gridTemplateColumns: "120px 1fr 120px 1fr", gap: "6px 20px", alignItems: "center" }}>
              <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 680 }}>运行 ID</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{run.turn_id || run.run_id || "—"}</span>
              <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 680 }}>追踪 ID</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{run.trace_id || "—"}</span>
              <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 680 }}>意图</span>
              <span style={{ fontSize: 13, overflow: "hidden", textOverflow: "ellipsis" }}>{run.intent || "—"}</span>
              <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 680 }}>能力</span>
              <span style={{ fontSize: 13 }}>{run.capability || "—"}</span>
              <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 680 }}>开始</span>
              <span style={{ fontSize: 13 }}>{formatDate(selectedStats.startedAt, "compact") || "—"}</span>
              <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 680 }}>结束</span>
              <span style={{ fontSize: 13 }}>{formatDate(selectedStats.finishedAt, "compact") || "—"}</span>
              <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 680 }}>工具调用</span>
              <span style={{ fontSize: 13 }}>{selectedStats.toolCallCount || 0}</span>
              <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 680 }}>状态</span>
              <span>{run.ok ? <Badge kind="ok" withDot>ok</Badge> : <Badge kind="err" withDot>failed</Badge>}</span>
            </div>
          </div>

          <TraceDetailPanel traceEvents={trace} selectedRun={run} />

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
    </div>
  );
}
