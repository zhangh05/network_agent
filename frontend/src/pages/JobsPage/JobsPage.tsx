/**
 * JobsPage — 作业管理 (v3.2.0 美化)
 *
 * 分栏布局：左侧作业列表，右侧详情面板。
 * 使用设计系统组件，SVG 图标替代文字占位符。
 */
import { useEffect, useState, useCallback } from "react";
import { jobsApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { useToastStore } from "../../stores/toast";
import { Badge, StatusDot, EmptyState, LoadingState } from "../../components/common";
import { IconRefresh, IconDocument } from "../../components/Icon";
import { isApiError } from "../../types";
import { formatCompactDate } from "../../utils/displayText";

type JobItem = {
  job_id: string;
  status: string;
  intent?: string;
  created_at?: string;
  workspace_id?: string;
  session_id?: string;
  summary?: string;
};

type JobEvent = {
  event: string;
  timestamp?: string;
  data?: Record<string, unknown>;
};

const STATUS_META: Record<string, { kind: "ok" | "err" | "warn" | "muted"; label: string; dot: "ok" | "err" | "warn" | "idle" }> = {
  completed: { kind: "ok", label: "完成", dot: "ok" },
  success: { kind: "ok", label: "成功", dot: "ok" },
  ok: { kind: "ok", label: "正常", dot: "ok" },
  failed: { kind: "err", label: "失败", dot: "err" },
  error: { kind: "err", label: "错误", dot: "err" },
  running: { kind: "warn", label: "运行中", dot: "warn" },
  pending: { kind: "warn", label: "等待中", dot: "warn" },
  queued: { kind: "warn", label: "排队中", dot: "warn" },
  cancelled: { kind: "muted", label: "已取消", dot: "idle" },
  archived: { kind: "muted", label: "已归档", dot: "idle" },
};

function statusMeta(status: string) {
  return STATUS_META[status] || { kind: "muted" as const, label: status, dot: "idle" as const };
}

export function JobsPage() {
  const { currentWorkspaceId } = useSessionStore();
  const wsId = currentWorkspaceId || "default";
  const toast = useToastStore((s) => s.show);

  const [jobs, setJobs] = useState<JobItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<JobItem | null>(null);
  const [jobEvents, setJobEvents] = useState<JobEvent[] | null>(null);
  const [jobLogs, setJobLogs] = useState<string | null>(null);
  const [jobArtifacts, setJobArtifacts] = useState<unknown[] | null>(null);
  const [tab, setTab] = useState<"events" | "logs" | "artifacts">("events");

  const loadJobs = useCallback(async () => {
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

  const loadJobDetail = async (job: JobItem) => {
    setSelectedId(job.job_id);
    setSelectedJob(job);
    setJobEvents(null); setJobLogs(null); setJobArtifacts(null);
    try {
      const [eventsData, logsData, artsData] = await Promise.allSettled([
        jobsApi.events(job.job_id),
        jobsApi.logs(job.job_id),
        jobsApi.artifacts(job.job_id),
      ]);
      if (eventsData.status === "fulfilled") setJobEvents(((eventsData.value as { events?: unknown[] })?.events ?? []) as JobEvent[]);
      if (logsData.status === "fulfilled") setJobLogs((logsData.value as { logs?: string })?.logs ?? "");
      if (artsData.status === "fulfilled") {
        const av = artsData.value as { input_artifacts?: string[]; output_artifacts?: string[]; report_artifacts?: string[] };
        setJobArtifacts([...(av.input_artifacts ?? []), ...(av.output_artifacts ?? []), ...(av.report_artifacts ?? [])]);
      }
    } catch { /* partial load ok */ }
  };

  const handleCancel = async (job_id: string) => {
    try {
      await jobsApi.cancel(job_id, wsId);
      toast({ kind: "success", title: "已取消" });
      loadJobs();
    } catch (e: unknown) {
      toast({ kind: "error", title: "取消失败", body: isApiError(e) ? e.message : String(e) });
    }
  };

  const handleRetry = async (job_id: string) => {
    try {
      await jobsApi.retry(job_id, wsId);
      toast({ kind: "success", title: "已重试" });
      loadJobs();
    } catch (e: unknown) {
      toast({ kind: "error", title: "重试失败", body: isApiError(e) ? e.message : String(e) });
    }
  };

  // ── Empty state ──
  if (!loading && !error && jobs.length === 0) {
    return (
      <div className="page">
        <div className="page-header" style={{ background: "var(--surface)" }}>
          <div>
            <h1>作业管理</h1>
            <p className="subtitle">后台异步任务：翻译、巡检、报告生成</p>
          </div>
          <button className="btn sm ghost" onClick={loadJobs} title="刷新">
            <IconRefresh size={14} />
          </button>
        </div>
        <div className="page-body">
          <div className="hero">
            <div className="hero-mark" style={{ fontSize: 22, fontWeight: 700 }}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
                <line x1="8" y1="21" x2="16" y2="21" />
                <line x1="12" y1="17" x2="12" y2="21" />
              </svg>
            </div>
            <h2 className="hero-title">暂无作业</h2>
            <p className="hero-sub">在 Workbench 中发起翻译、巡检或报告生成任务后，可在此查看进度与结果。</p>
          </div>
        </div>
      </div>
    );
  }

  // ── Main content ──
  return (
    <div className="page">
      <div className="page-header" style={{ background: "var(--surface)" }}>
        <div>
          <h1>作业管理</h1>
          <p className="subtitle">后台异步任务：翻译、巡检、报告生成</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
          <div className="status-pill">
            <span className="dot" style={{ background: "var(--accent)" }} />
            共 {jobs.length} 项
          </div>
          <button className="btn sm ghost" onClick={loadJobs} title="刷新">
            <IconRefresh size={14} />
          </button>
        </div>
      </div>

      {error && (
        <div style={{ margin: "12px 24px 0", padding: "10px 14px", color: "var(--danger)", background: "var(--danger-soft)", borderRadius: "var(--r-6)", fontSize: "var(--fs-13)", fontWeight: 650 }}>
          ⚠ {error}
        </div>
      )}

      {loading && (
        <div className="page-body"><LoadingState text="加载作业列表…" /></div>
      )}

      {!loading && jobs.length > 0 && (
        <div className="split-shell" style={{ flex: 1 }}>
          {/* ── 左侧列表 ── */}
          <aside style={{ padding: 12, overflow: "auto" }}>
            {jobs.map((job) => {
              const meta = statusMeta(job.status);
              const isActive = selectedId === job.job_id;
              return (
                <button
                  key={job.job_id}
                  type="button"
                  className={`job-card${isActive ? " selected" : ""}`}
                  style={{
                    width: "100%", textAlign: "left", cursor: "pointer",
                    background: isActive ? "var(--accent-soft)" : "var(--surface)",
                    border: isActive ? "1px solid var(--accent)" : "1px solid var(--line)",
                  }}
                  onClick={() => loadJobDetail(job)}
                >
                  <div className="job-card-head">
                    <StatusDot status={meta.dot} />
                    <span className="job-card-title">{job.summary || job.intent || job.job_id?.slice(0, 12)}</span>
                    <Badge kind={meta.kind}>{meta.label}</Badge>
                  </div>
                  <div className="job-card-meta">
                    <span>{job.job_id?.slice(0, 12)}…</span>
                    {job.created_at && <span>{formatCompactDate(job.created_at)}</span>}
                    {job.workspace_id && <span>{job.workspace_id}</span>}
                  </div>
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

          {/* ── 右侧详情 ── */}
          <div className="split-detail" style={{ padding: "24px" }}>
            {selectedJob ? (
              <div style={{ animation: "surface-in var(--dur-4) var(--ease-out) both" }}>
                {/* Status bar */}
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
                  <StatusDot status={statusMeta(selectedJob.status).dot} />
                  <h3 style={{ fontSize: "var(--fs-18)", fontWeight: 720, margin: 0 }}>
                    {selectedJob.summary || selectedJob.intent || selectedJob.job_id?.slice(0, 12)}
                  </h3>
                  <Badge kind={statusMeta(selectedJob.status).kind}>{statusMeta(selectedJob.status).label}</Badge>
                </div>

                {/* Info grid */}
                <div style={{
                  display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
                  gap: "10px 16px", padding: "16px", background: "var(--surface-2)",
                  borderRadius: "var(--r-8)", border: "1px solid var(--line-2)", marginBottom: 20,
                }}>
                  <InfoField label="作业 ID" value={selectedJob.job_id} mono />
                  <InfoField label="意图" value={selectedJob.intent} />
                  <InfoField label="创建时间" value={selectedJob.created_at ? formatCompactDate(selectedJob.created_at) : undefined} />
                  {selectedJob.workspace_id && <InfoField label="工作区" value={selectedJob.workspace_id} />}
                  {selectedJob.session_id && <InfoField label="会话 ID" value={selectedJob.session_id} mono />}
                </div>

                {/* Tabs */}
                <div className="tabs" style={{ marginBottom: 16 }}>
                  {(["events", "logs", "artifacts"] as const).map((t) => (
                    <button
                      key={t}
                      type="button"
                      className={"tab" + (tab === t ? " active" : "")}
                      onClick={() => setTab(t)}
                    >
                      {t === "events" ? "事件" : t === "logs" ? "日志" : "制品"}
                    </button>
                  ))}
                </div>

                {/* Tab content */}
                <div className="job-detail-content">
                  {tab === "events" && (
                    jobEvents === null ? <LoadingState text="加载事件…" /> :
                    jobEvents.length === 0 ? <EmptyState text="无事件记录" /> :
                    jobEvents.map((ev, i) => (
                      <div key={i} className="card job-event">
                        <div className="job-event-head">
                          <strong>{ev.event}</strong>
                          {ev.timestamp && <span className="muted">{formatCompactDate(ev.timestamp)}</span>}
                        </div>
                        {ev.data && (
                          <pre className="code-block">{JSON.stringify(ev.data, null, 2)}</pre>
                        )}
                      </div>
                    ))
                  )}

                  {tab === "logs" && (
                    jobLogs === null ? <LoadingState text="加载日志…" /> :
                    !jobLogs || jobLogs === "" ? <EmptyState text="无日志" /> :
                    <pre className="code-block">{jobLogs}</pre>
                  )}

                  {tab === "artifacts" && (
                    jobArtifacts === null ? <LoadingState text="加载制品…" /> :
                    jobArtifacts.length === 0 ? <EmptyState text="无关联制品" /> :
                    jobArtifacts.map((a: any, i: number) => (
                      <div key={a.artifact_id || i} className="card" style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", marginBottom: 6 }}>
                        <IconDocument size={14} style={{ color: "var(--accent)", flexShrink: 0 }} />
                        <span style={{ flex: 1, fontSize: "var(--fs-13)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {a.title || a.artifact_id || `#${i + 1}`}
                        </span>
                        {a.artifact_type && <Badge kind="muted">{a.artifact_type}</Badge>}
                      </div>
                    ))
                  )}
                </div>
              </div>
            ) : (
              <div className="empty" style={{ minHeight: "100%" }}>
                <div className="empty-icon" style={{ background: "var(--surface-2)" }}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--text-4)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
                    <line x1="8" y1="21" x2="16" y2="21" />
                    <line x1="12" y1="17" x2="12" y2="21" />
                  </svg>
                </div>
                <div className="empty-text" style={{ fontSize: "var(--fs-13)" }}>选择一项作业</div>
                <p className="empty-hint">点击左侧列表中的作业查看详情与执行日志</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** 信息字段辅助组件 */
function InfoField({ label, value, mono }: { label: string; value?: string | null; mono?: boolean }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: "var(--fs-10)", color: "var(--text-4)", textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 680, marginBottom: 3 }}>
        {label}
      </div>
      <div style={{
        fontSize: "var(--fs-12)", color: "var(--text-2)", fontWeight: 620,
        fontFamily: mono ? "var(--font-mono)" : undefined,
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
      }}>
        {value || "-"}
      </div>
    </div>
  );
}
