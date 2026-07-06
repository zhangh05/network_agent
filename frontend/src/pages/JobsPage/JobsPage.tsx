/**
 * JobsPage — 作业管理 (v3.3.2 重构)
 *
 * 每个会话 = 一个 Job，Job 下累积多个 Run。
 * 三 Tab 详情：概要（Run 列表）| 产出（制品）| 统计（聚合数据）
 *
 * 定位：任务管理视角 —— "这个会话做了什么、产出什么、效率如何"
 * 与 RunsPage 的区分：RunsPage 聚焦单次执行的 trace/decision 调试
 */
import { useEffect, useState, useCallback, useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { jobsApi, workspacesApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { useToastStore } from "../../stores/toast";
import { Badge, StatusDot, EmptyState, LoadingState } from "../../components/common";
import { IconRefresh, IconDocument, IconHistory, IconBolt, IconLayers } from "../../components/Icon";
import { isApiError } from "../../types";
import { formatCompactDate } from "../../utils/displayText";

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
  payload?: Record<string, unknown>;   // session_id lives here
  run_ids?: string[];
  progress?: { current: number; total: number; percent: number; message: string };
  error?: string;
};

/** Extract session_id from nested payload */
function getSessionId(job: JobItem): string {
  return String(job.payload?.session_id ?? "");
}

type RunSummary = {
  run_id?: string;
  turn_id?: string;
  session_id?: string;
  status?: string;
  user_input_summary?: string;
  intent?: string;
  created_at?: string;
  tool_call_count?: number;
  error_count?: number;
  warning_count?: number;
  trace_id?: string;
};

type ArtifactGroup = {
  input: string[];
  output: string[];
  report: string[];
};

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

const RUN_STATUS_LABELS: Record<string, string> = {
  ok: "成功", completed: "完成", success: "成功",
  failed: "失败", error: "失败", running: "运行中",
  pending: "等待", timeout: "超时", cancelled: "取消",
};

/* ── Helpers ── */

function sMeta(s: string) { return STATUS_META[s] || { kind: "muted" as const, label: s || "未知", dot: "idle" as const }; }
function rLabel(s: string) { return RUN_STATUS_LABELS[s] || s || "未知"; }

function calcDuration(start?: string, end?: string): string | null {
  if (!start) return null;
  const t0 = new Date(start).getTime();
  const t1 = end ? new Date(end).getTime() : Date.now();
  const secs = Math.round((t1 - t0) / 1000);
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

/* ── Component ── */

export function JobsPage() {
  const navigate = useNavigate();
  const { currentWorkspaceId } = useSessionStore();
  const wsId = currentWorkspaceId;
  const toast = useToastStore((s) => s.show);

  const [jobs, setJobs] = useState<JobItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedJob, setSelectedJob] = useState<JobItem | null>(null);
  const [tab, setTab] = useState<"overview" | "stats">("overview");

  // Per-tab loading states
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [runsLoading, setRunsLoading] = useState(false);

  const loadJobs = useCallback(async () => {
    if (!wsId) {
      setJobs([]);
      setLoading(false);
      return;
    }
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

  /* ── Select job → load runs & artifacts ── */
  const selectJob = useCallback(async (job: JobItem) => {
    if (selectedJob?.job_id === job.job_id) {
      setSelectedJob(null); setRuns(null); return;
    }
    setSelectedJob(job);
    setTab("overview"); setRuns(null);

    // Load runs for this session (session_id in payload)
    const sid = getSessionId(job);
    if (sid) {
      setRunsLoading(true);
      try {
        const d = await workspacesApi.recentRuns(wsId, sid);
        setRuns((d?.runs ?? []) as RunSummary[]);
      } catch { setRuns([]); }
      finally { setRunsLoading(false); }
    } else {
      setRuns([]);
    }
  }, [selectedJob, wsId]);

  /* ── Aggregated stats ── */
  const stats = useMemo(() => {
    const runList = runs ?? [];
    const totalTools = runList.reduce((s, r) => s + (r.tool_call_count ?? 0), 0);
    const totalErrors = runList.reduce((s, r) => s + (r.error_count ?? 0), 0);
    return { runCount: runList.length, totalTools, totalErrors };
  }, [runs]);

  const duration = useMemo(
    () => calcDuration(selectedJob?.started_at, selectedJob?.finished_at),
    [selectedJob],
  );

  // ── Cancel / Retry ──
  const handleCancel = async (job_id: string) => {
    try { await jobsApi.cancel(job_id, wsId); toast({ kind: "success", title: "已取消" }); loadJobs(); }
    catch (e: unknown) { toast({ kind: "error", title: "取消失败", body: isApiError(e) ? e.message : String(e) }); }
  };
  const handleRetry = async (job_id: string) => {
    try { await jobsApi.retry(job_id, wsId); toast({ kind: "success", title: "已重试" }); loadJobs(); }
    catch (e: unknown) { toast({ kind: "error", title: "重试失败", body: isApiError(e) ? e.message : String(e) }); }
  };

  // Navigate to Runs page with a specific run
  const openRun = useCallback((run: RunSummary) => {
    const rid = run.run_id || run.turn_id;
    if (rid) navigate(`/runs?focus=${rid}`);
    else navigate("/runs");
  }, [navigate]);

  /* ════════════════════════════════════════════════════
     RENDER
     ════════════════════════════════════════════════════ */

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
                <line x1="8" y1="21" x2="16" y2="21" />
                <line x1="12" y1="17" x2="12" y2="21" />
              </svg>
            </div>
            <h2 className="hero-title">暂无作业</h2>
            <p className="hero-sub">在工作台发起对话后，每个会话将自动生成一个作业，在此追踪任务全貌。</p>
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
          <aside style={{ padding: 12, overflow: "auto" }}>
            {jobs.map((job) => {
              const meta = sMeta(job.status);
              const active = selectedJob?.job_id === job.job_id;
              const TypeIcon = JOB_TYPE_ICONS[job.job_type] || IconBolt;
              return (
                <button
                  key={job.job_id}
                  type="button"
                  className="job-card"
                  onClick={() => selectJob(job)}
                  style={{
                    width: "100%", textAlign: "left", cursor: "pointer",
                    background: active ? "var(--accent-soft)" : "var(--surface)",
                    border: active ? "1px solid var(--accent)" : "1px solid var(--line)",
                  }}
                >
                  {/* Title row */}
                  <div className="job-card-head">
                    <StatusDot status={meta.dot} />
                    <span className="job-card-title">{job.title || job.job_id?.slice(0, 12)}</span>
                    <Badge kind={meta.kind}>{meta.label}</Badge>
                  </div>

                  {/* Type + time */}
                  <div className="job-card-meta">
                    <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <TypeIcon size={11} style={{ opacity: 0.6 }} />
                      {JOB_TYPE_LABELS[job.job_type] || job.job_type}
                    </span>
                    {job.created_at && <span>{formatCompactDate(job.created_at)}</span>}
                    {duration && <span>{duration}</span>}
                  </div>

                  {/* Run count */}
                  {job.run_ids && job.run_ids.length > 0 && (
                    <div className="job-card-meta">
                      <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                        <IconHistory size={11} style={{ opacity: 0.6 }} />
                        {job.run_ids.length} 轮对话
                      </span>
                    </div>
                  )}

                  {/* Error */}
                  {job.error && (
                    <div className="job-card-meta">
                      <span style={{ color: "var(--danger)", fontSize: "var(--fs-11)" }}>{job.error.slice(0, 60)}</span>
                    </div>
                  )}

                  {/* Actions */}
                  <div className="job-card-actions">
                    {(job.status === "running" || job.status === "pending" || job.status === "queued") && (
                      <button className="btn sm danger-ghost" onClick={(e) => { e.stopPropagation(); handleCancel(job.job_id); }} type="button">取消</button>
                    )}
                    {(job.status === "failed" || job.status === "error") && (
                      <button className="btn sm" onClick={(e) => { e.stopPropagation(); handleRetry(job.job_id); }} type="button">重试</button>
                    )}
                  </div>
                </button>
              );
            })}
          </aside>

          {/* ══════ 右侧 详情面板 ══════ */}
          <DetailPanel
            job={selectedJob}
            tab={tab}
            setTab={setTab}
            runs={runs}
            runsLoading={runsLoading}
            stats={stats}
            duration={duration}
            onOpenRun={openRun}
            onCancel={handleCancel}
            onRetry={handleRetry}
          />
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
        <h1>作业管理<span style={{ color: "var(--ink-mute)", fontWeight: 400, fontSize: 14, marginLeft: 6 }}>· Jobs</span></h1>
        <p className="subtitle">任务全貌：每个会话一个作业，追踪对话轮次、产出与统计</p>
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

/* ── Detail Panel ── */

function DetailPanel({
  job, tab, setTab, runs, runsLoading, artifacts, artsLoading, stats, duration,
  onOpenRun, onCancel, onRetry,
}: {
  job: JobItem | null;
  tab: "overview" | "stats";
  setTab: (t: "overview" | "stats") => void;
  runs: RunSummary[] | null;
  runsLoading: boolean;
  stats: { runCount: number; totalTools: number; totalErrors: number };
  duration: string | null;
  onOpenRun: (r: RunSummary) => void;
  onCancel: (id: string) => void;
  onRetry: (id: string) => void;
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
          <p className="empty-hint" style={{ maxWidth: 280 }}>
            点击左侧列表中的作业，查看会话内的运行记录和数据统计。
          </p>
        </div>
      </div>
    );
  }

  const meta = sMeta(job.status);

  return (
    <div className="split-detail" style={{ padding: "24px", overflow: "auto", animation: "surface-in var(--dur-4) var(--ease-out) both" }}>
      {/* ── Status bar ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
        <StatusDot status={meta.dot} />
        <h3 style={{ fontSize: "var(--fs-18)", fontWeight: 720, margin: 0, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {job.title || job.job_id?.slice(0, 12)}
        </h3>
        <Badge kind={meta.kind}>{meta.label}</Badge>
        <Badge kind="muted">{JOB_TYPE_LABELS[job.job_type] || job.job_type}</Badge>
      </div>

      {/* ── Quick stats bar ── */}
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

      {/* ── Actions ── */}
      {(job.status === "running" || job.status === "pending" || job.status === "queued") && (
        <div style={{ marginBottom: 14 }}>
          <button className="btn sm danger-ghost" onClick={() => onCancel(job.job_id)}>取消作业</button>
        </div>
      )}
      {(job.status === "failed" || job.status === "error") && (
        <div style={{ marginBottom: 14 }}>
          <button className="btn sm" onClick={() => onRetry(job.job_id)}>重试作业</button>
        </div>
      )}

      {/* ── Tabs ── */}
      <div className="tabs" style={{ marginBottom: 16 }}>
        <button className={"tab" + (tab === "overview" ? " active" : "")} onClick={() => setTab("overview")}>
          运行记录 {stats.runCount > 0 && <span style={{ opacity: 0.5, marginLeft: 4 }}>{stats.runCount}</span>}
        </button>
        <button className={"tab" + (tab === "stats" ? " active" : "")} onClick={() => setTab("stats")}>
          统计
        </button>
      </div>

      {/* ── Tab: 运行记录 ── */}
      {tab === "overview" && (
        <TabOverview
          job={job}
          runs={runs}
          runsLoading={runsLoading}
          onOpenRun={onOpenRun}
        />
      )}

      {/* ── Tab: 统计 ── */}
      {tab === "stats" && (
        <TabStats
          job={job}
          runs={runs}
          runsLoading={runsLoading}
          stats={stats}
          duration={duration}
        />
      )}
    </div>
  );
}

/* ── QuickStat ── */

function QuickStat({ label, value, mono, danger }: { label: string; value: string; mono?: boolean; danger?: boolean }) {
  return (
    <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
      <span style={{ color: "var(--text-4)", fontSize: "var(--fs-10)" }}>{label}</span>
      <span style={{ fontWeight: 680, color: danger ? "var(--danger)" : "var(--text-2)", fontFamily: mono ? "var(--font-mono)" : undefined }}>{value}</span>
    </span>
  );
}

/* ── Tab: 运行记录 ── */

function TabOverview({
  job, runs, runsLoading, onOpenRun,
}: {
  job: JobItem;
  runs: RunSummary[] | null;
  runsLoading: boolean;
  onOpenRun: (r: RunSummary) => void;
}) {
  if (runsLoading) return <LoadingState text="加载运行记录…" />;
  if (!runs || runs.length === 0) {
    return (
      <EmptyState
        text={getSessionId(job) ? "该会话暂无运行记录" : "非会话作业（如报告导出），无运行记录"}
      />
    );
  }

  return (
    <div>
      <div className="section-head" style={{ marginBottom: 10 }}>
        共 {runs.length} 轮对话
      </div>
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
          {/* Round number */}
          <span style={{
            width: 24, height: 24, borderRadius: "50%",
            background: "var(--surface-2)", display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: "var(--fs-10)", fontWeight: 700, color: "var(--text-4)", flexShrink: 0,
          }}>
            {runs.length - i}
          </span>

          {/* Summary */}
          <span style={{ flex: 1, fontSize: "var(--fs-13)", fontWeight: 620, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 }}>
            {r.user_input_summary || r.intent || "(无摘要)"}
          </span>

          {/* Status */}
          <Badge kind={r.status === "failed" || r.status === "error" ? "err" : "ok"}>
            {rLabel(r.status || "")}
          </Badge>

          {/* Tool count */}
          {(r.tool_call_count ?? 0) > 0 && (
            <span style={{ fontSize: "var(--fs-11)", color: "var(--text-4)", whiteSpace: "nowrap" }}>
              {r.tool_call_count} 工具
            </span>
          )}

          {/* Time */}
          {r.created_at && (
            <span style={{ fontSize: "var(--fs-11)", color: "var(--text-4)", whiteSpace: "nowrap" }}>
              {formatCompactDate(r.created_at)}
            </span>
          )}

          {/* Arrow */}
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--text-4)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </button>
      ))}
    </div>
  );
}

/* ── Tab: 产出制品 ── */


/* ── Tab: 统计 ── */

function TabStats({
  job, runs, runsLoading, stats, duration,
}: {
  job: JobItem;
  runs: RunSummary[] | null;
  runsLoading: boolean;
  stats: { runCount: number; totalTools: number; totalErrors: number };
  duration: string | null;
}) {
  const runList = runs ?? [];
  const succeededRuns = runList.filter((r) => r.status === "ok" || r.status === "completed" || r.status === "success").length;
  const failedRuns = runList.filter((r) => r.status === "failed" || r.status === "error").length;

  // Per-run tool count distribution
  const toolDist = runList
    .map((r) => r.tool_call_count ?? 0)
    .filter((c) => c > 0);
  const maxTools = toolDist.length > 0 ? Math.max(...toolDist) : 0;
  const avgTools = toolDist.length > 0 ? (toolDist.reduce((a, b) => a + b, 0) / toolDist.length).toFixed(1) : "0";

  return (
    <div>
      {/* Stat cards */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
        gap: "10px", marginBottom: 20,
      }}>
        <StatCard label="会话 ID" value={getSessionId(job).slice(0, 16) || "-"} mono />
        <StatCard label="作业 ID" value={job.job_id.slice(0, 12)} mono />
        <StatCard label="类型" value={JOB_TYPE_LABELS[job.job_type] || job.job_type} />
        <StatCard label="状态" value={sMeta(job.status).label} />
        <StatCard label="耗时" value={duration || "-"} />
      </div>

      {/* Run-level stats */}
      <div className="section-head" style={{ marginBottom: 10 }}>执行统计</div>
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))",
        gap: "8px", marginBottom: 20,
      }}>
        <StatCard label="总轮数" value={String(stats.runCount)} highlight />
        <StatCard label="成功" value={String(succeededRuns)} highlight ok />
        <StatCard label="失败" value={String(failedRuns)} highlight danger={failedRuns > 0} />
        <StatCard label="工具调用" value={String(stats.totalTools)} />
        <StatCard label="单轮最多" value={String(maxTools)} />
        <StatCard label="单轮平均" value={avgTools} />
      </div>

      {/* Timeline info */}
      <div className="section-head" style={{ marginBottom: 10 }}>时间线</div>
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
        gap: "8px", fontSize: "var(--fs-12)", color: "var(--text-3)", marginBottom: 20,
      }}>
        <div>创建：{formatCompactDate(job.created_at) || "-"}</div>
        <div>开始：{formatCompactDate(job.started_at) || "-"}</div>
        <div>结束：{formatCompactDate(job.finished_at) || "-"}</div>
        <div>更新：{formatCompactDate(job.updated_at) || "-"}</div>
      </div>

      {/* Per-run breakdown */}
      {runList.length > 0 && (
        <>
          <div className="section-head" style={{ marginBottom: 10 }}>各轮耗时</div>
          {runList.map((r, i) => (
            <div key={i} style={{
              display: "flex", alignItems: "center", gap: 8, padding: "6px 10px",
              background: "var(--surface-2)", borderRadius: "var(--r-4)", marginBottom: 4,
              fontSize: "var(--fs-11)", color: "var(--text-3)",
            }}>
              <span style={{ fontWeight: 680, width: 30 }}>#{runList.length - i}</span>
              <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {r.user_input_summary || r.intent || "(无摘要)"}
              </span>
              <Badge kind={r.status === "failed" || r.status === "error" ? "err" : "ok"}>
                {rLabel(r.status || "")}
              </Badge>
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

function StatCard({
  label, value, mono, highlight, ok, danger,
}: {
  label: string; value: string; mono?: boolean; highlight?: boolean; ok?: boolean; danger?: boolean;
}) {
  let color = "var(--text-2)";
  if (ok) color = "var(--ok)";
  if (danger) color = "var(--danger)";
  return (
    <div style={{
      padding: "10px 14px", background: "var(--surface-2)",
      borderRadius: "var(--r-8)", border: "1px solid var(--line-2)",
    }}>
      <div style={{ fontSize: "var(--fs-10)", color: "var(--text-4)", textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: 680, marginBottom: 4 }}>
        {label}
      </div>
      <div style={{
        fontSize: highlight ? "var(--fs-16)" : "var(--fs-13)",
        fontWeight: 720, color,
        fontFamily: mono ? "var(--font-mono)" : undefined,
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
      }}>
        {value}
      </div>
    </div>
  );
}
