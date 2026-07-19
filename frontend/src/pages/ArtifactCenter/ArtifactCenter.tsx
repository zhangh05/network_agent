/**
 * ArtifactCenter — 制品中心
 */
import { useEffect, useState, useCallback } from "react";
import { artifactsApi, reportsApi, storageApi } from "../../api";
import type { ArtifactGovernanceSummary } from "../../api";
import { useAsync, AsyncView, Badge, CodeBlock, InlineCode, LoadingState, ErrorState } from "../../components/common";
import { PageHeader, FilterBar, Button, Input, Textarea } from "../../components/ui";
import { useSessionStore } from "../../stores/session";
import { useToastStore } from "../../stores/toast";
import { isApiError } from "../../types";
import type { Artifact } from "../../types";
import { IconDocument, IconPlus } from "../../components/Icon";
import { formatCompactDate, shortId } from "../../utils/displayText";
import { formatFileSize } from "../../utils/format";

const SENS_LABEL: Record<string, string> = { public: "公开", internal: "内部", sensitive: "敏感", secret: "机密" };
const LC_KIND: Record<string, "ok" | "warn" | "muted"> = { active: "ok", archived: "warn", deleted: "muted" };
const LC_LABEL: Record<string, string> = { active: "活跃", archived: "归档", deleted: "已删" };
const SRC_LABEL: Record<string, string> = { user_upload: "用户上传", module_output: "模块产出", agent_run: "智能体任务", inspection_runner: "设备巡检" };

export function ArtifactCenter() {
  const { currentWorkspaceId } = useSessionStore();
  const [sel, setSel] = useState<Artifact | null>(null);
  const [tab, setTab] = useState<"preview" | "summary" | "metadata">("preview");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [batch, setBatch] = useState(false);
  const [view, setView] = useState<"" | "current" | "history" | "deliverables">("");
  const [producerId, setProducerId] = useState(() => new URLSearchParams(window.location.search).get("producer_id") || "");
  const toast = useToastStore((s) => s.show);

  const list = useAsync<{ artifacts: Artifact[]; governance?: ArtifactGovernanceSummary }>(
    (s) => currentWorkspaceId ? artifactsApi.list(currentWorkspaceId, s, view, producerId) : Promise.resolve({ artifacts: [] }),
    [currentWorkspaceId, view, producerId], (d) => (d.artifacts ?? []).length === 0,
  );

  useEffect(() => {
    if (!currentWorkspaceId || typeof EventSource === "undefined") return;
    const stream = storageApi.events(currentWorkspaceId);
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;
    const refresh = (event: Event) => {
      try {
        if (JSON.parse((event as MessageEvent).data).domain !== "artifact") return;
      } catch {
        return;
      }
      if (refreshTimer) clearTimeout(refreshTimer);
      refreshTimer = setTimeout(() => list.reload(), 100);
    };
    stream.addEventListener("storage_changed", refresh);
    return () => {
      if (refreshTimer) clearTimeout(refreshTimer);
      stream.removeEventListener("storage_changed", refresh);
      stream.close();
    };
  }, [currentWorkspaceId, list.reload]);

  const delOne = async (id: string, t: string) => {
    if (!currentWorkspaceId || !confirm(`删除「${t || id}」？`)) return;
    try {
      await artifactsApi.batchDelete(currentWorkspaceId, [id]);
      toast({ kind: "success", title: "已删除" }); setSel(null);
      setChecked((p) => { const n = new Set(p); n.delete(id); return n; }); list.reload();
    } catch (e: any) { toast({ kind: "error", title: "删除失败", body: isApiError(e) ? e.message : String(e) }); }
  };

  const delBatch = async () => {
    if (!currentWorkspaceId || checked.size === 0 || !confirm(`删除 ${checked.size} 个制品？`)) return;
    try { await artifactsApi.batchDelete(currentWorkspaceId, [...checked]); toast({ kind: "success", title: `已删除 ${checked.size} 个` }); setChecked(new Set()); list.reload(); }
    catch (e: any) { toast({ kind: "error", title: "批量删除失败", body: isApiError(e) ? e.message : String(e) }); }
  };

  const total = list.state.kind === "success" ? (list.state.data.artifacts ?? []).length : 0;
  const governance = list.state.kind === "success" ? list.state.data.governance : undefined;

  return (
    <div className="page" data-testid="page-artifacts">
      <PageHeader
        title={
          <>
            制品中心
          </>
        }
        subtitle="统一管理巡检证据、历史版本与业务交付物"
      >
        <div className="status-pill"><span className="dot accent" />{total} 个</div>
      </PageHeader>

      <FilterBar>
        {producerId && <div className="status-pill" title={producerId}>任务 {shortId(producerId)}<Button size="sm" iconOnly className="btn-xs-compact" title="清除任务筛选" onClick={() => { window.history.replaceState({}, "", window.location.pathname); setProducerId(""); }}>×</Button></div>}
        {([
          ["", "全部制品"], ["current", "当前证据"], ["history", "历史与不完整"], ["deliverables", "业务交付物"],
        ] as const).map(([key, label]) => (
          <Button key={key || "all"} size="sm" variant={view === key ? "primary" : "default"} onClick={() => { setView(key); setSel(null); }}>
            {label}
          </Button>
        ))}
        <div className="spacer" />
        {governance && <div className="row-flex-sm artifact-governance-badges">
          <Badge kind="ok">状态权威 {governance.current_state_authoritative || 0}</Badge>
          {governance.inspection_current > 0 && <Badge kind="info">最新资产巡检 {governance.inspection_current}</Badge>}
          {governance.contextual > 0 && <Badge kind="muted">专项证据 {governance.contextual}</Badge>}
          {governance.provisional > 0 && <Badge kind="warn">临时 {governance.provisional}</Badge>}
          {governance.incomplete > 0 && <Badge kind="err">不完整 {governance.incomplete}</Badge>}
          <Badge kind="muted">证据流 {governance.evidence_streams}</Badge>
        </div>}
      </FilterBar>

      <details className="artifact-governance-help">
        <summary>证据状态如何判定？</summary>
        <div>
          <span><b>当前状态权威</b>：同一设备、同一巡检脚本最近一次完整的权威基线采集。只有基线采集可以建立或更新该权威。</span>
          <span><b>最新资产巡检</b>：普通资产巡检的最新完整结果；与状态权威相互独立。</span>
          <span><b>专项任务证据</b>：故障传播、故障排查、依赖刷新与变更验证采集；只服务于对应任务，不参与状态权威选择。</span>
          <span><b>临时证据</b>：该证据流还没有完整成功采集，暂用最近一次部分采集或缺少完整性证明的记录。</span>
          <span><b>不完整</b>：采集中断、超时、取消或未完整返回；不会覆盖已有权威证据。</span>
          <span><b>历史版本</b>：曾完整成功，但已被同一证据流中更新的完整采集替代。</span>
        </div>
      </details>

      <div className="split-shell">
        {/* Left list */}
        <aside className="artifact-aside">
          <div className="row-flex artifact-list-header">
            <span className="text-sm artifact-list-title">制品列表</span>
            <div className="spacer" />
            <Button size="sm" variant={batch ? "danger" : "default"} onClick={() => { setBatch(!batch); if (batch) setChecked(new Set()); }}>
              {batch ? "取消" : "批量删除"}
            </Button>
          </div>
          {batch && (
            <div className={"artifact-batch-bar" + (checked.size > 0 ? " active" : "")}>
              <label className="artifact-batch-label">
                <input type="checkbox"
                  className="artifact-checkbox"
                  checked={list.state.kind === "success" && checked.size === (list.state.data.artifacts ?? []).length && (list.state.data.artifacts ?? []).length > 0}
                  onChange={(e) => {
                    if (e.target.checked && list.state.kind === "success") {
                      setChecked(new Set((list.state.data.artifacts ?? []).map((a) => a.artifact_id)));
                    } else {
                      setChecked(new Set());
                    }
                  }} />
                <span className="text-sm artifact-batch-select">
                  全选 {checked.size > 0 && `(已选 ${checked.size})`}
                </span>
              </label>
              <Button size="sm" variant="danger" disabled={checked.size === 0} onClick={delBatch}>
                删除 {checked.size || ""} 项
              </Button>
            </div>
          )}
          <AsyncView state={list.state} onRetry={list.reload} emptyText="暂无制品" emptyHint="后端返回为空">
            {(d) => {
              const groups = groupArtifactsByTask(d.artifacts ?? []);
              return <div data-testid="artifact-list" className="artifact-list">
                {groups.map((group, index) => (
                  <ArtifactTaskGroup key={group.key} groupKey={group.key} initialOpen={Boolean(producerId) || index === 0}>
                    <summary className="artifact-task-summary">
                      <span aria-hidden="true" className="artifact-arrow">▶</span>
                      <span className="flex-1">
                        <b className="artifact-card-title">{group.label}</b>
                        <span className="artifact-card-date artifact-card-date-block" title={group.taskId}>{group.taskId ? `任务 ${shortId(group.taskId)}` : "未归属任务"}</span>
                      </span>
                      <Badge kind={group.taskId ? "info" : "muted"}>{group.artifacts.length} 个</Badge>
                    </summary>
                    <div className="artifact-task-body">
                      {group.artifacts.map((a) => {
                        const active = sel?.artifact_id === a.artifact_id;
                        return (
                          <div key={a.artifact_id} className="artifact-item">
                            {batch && (
                              <input type="checkbox" className="artifact-checkbox" checked={checked.has(a.artifact_id)} onChange={(e) => { const n = new Set(checked); e.target.checked ? n.add(a.artifact_id) : n.delete(a.artifact_id); setChecked(n); }} />
                            )}
                            <button type="button"
                              className={`artifact-card ${active ? "selected" : ""}`}
                              onClick={() => { setSel(a); setTab("preview"); }}
                              data-testid={`artifact-${a.artifact_id}`}>
                              <div className="artifact-card-title">{a.title || a.artifact_id}</div>
                              <div className="artifact-card-badges">
                                <Badge kind="muted">{typeLabel(a)}</Badge>
                                <AuthorityBadge artifact={a} />
                                {a.sensitivity === "sensitive" && <Badge kind="warn">敏感</Badge>}
                                {a.sensitivity === "secret" && <Badge kind="err">机密</Badge>}
                                {a.redaction_applied && <Badge kind="warn">脱敏</Badge>}
                                {a.created_at && <span className="artifact-card-date">{formatCompactDate(a.created_at)}</span>}
                              </div>
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  </ArtifactTaskGroup>
                ))}
              </div>;
            }}
          </AsyncView>
        </aside>

        {/* Right detail */}
        <div className="split-detail">
          {sel ? (
            <Detail artifact={sel} tab={tab} onTab={setTab} onDel={() => delOne(sel.artifact_id, sel.title || "")} />
          ) : (
            <div className="empty h-full">
              <div className="empty-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--text-4)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
                </svg>
              </div>
              <div className="empty-text">选择一件制品</div>
              <p className="empty-hint">点击左侧列表中的制品查看预览、摘要与元数据</p>
            </div>
          )}
        </div>
      </div>
      <ReportSection />
    </div>
  );
}

/* ── Detail ── */

function Detail({ artifact: a, tab, onTab, onDel }: { artifact: Artifact; tab: string; onTab: (t: "preview" | "summary" | "metadata") => void; onDel: () => void }) {
  return (
    <div data-testid="artifact-detail">
      {/* Title bar */}
      <div className="row-flex artifact-detail-header">
        <IconDocument size={16} className="accent-text flex-0" />
        <h3 className="text-lg artifact-detail-title">{a.title || a.artifact_id}</h3>
        <Badge kind="muted">{SENS_LABEL[a.sensitivity] || a.sensitivity}</Badge>
        <Badge kind={LC_KIND[a.lifecycle]}>{LC_LABEL[a.lifecycle] || a.lifecycle}</Badge>
        <AuthorityBadge artifact={a} />
        {a.redaction_applied && <Badge kind="warn">脱敏</Badge>}
        <div className="spacer" />
        <Button size="sm" variant="danger-ghost" onClick={onDel}>删除</Button>
      </div>

      {/* Facts card */}
      <div className="card mb-3">
        <div className="info-grid-3">
          <Info label="类型">{typeLabel(a)}</Info>
          <Info label="来源">{SRC_LABEL[a.source] || a.source}</Info>
          <Info label="MIME">{a.mime_type || "—"}</Info>
          <Info label="大小">{formatFileSize(a.size_bytes)}</Info>
          {a.sha256_short && <Info label="SHA-256" mono>{a.sha256_short}</Info>}
          {a.capability_id && <Info label="能力">{a.capability_id}</Info>}
          {a.run_id && <Info label="关联任务" mono>{shortId(a.run_id)}</Info>}
          <Info label="证据地位">{authorityLabel(a)}</Info>
          {typeof a.metadata?.asset_name === "string" && <Info label="设备">{a.metadata.asset_name}</Info>}
          {typeof a.metadata?.producer_id === "string" && <Info label="巡检任务" mono>{shortId(a.metadata.producer_id)}</Info>}
          {typeof a.metadata?.producer_trigger === "string" && <Info label="触发场景">{triggerLabel(a.metadata.producer_trigger)}</Info>}
          {a.governance?.version_count && <Info label="证据版本">第 {a.governance.version} / {a.governance.version_count} 版</Info>}
        </div>
        {a.governance?.authority_reason && <div className="authority-reason">{a.governance.authority_reason}</div>}
        <details className="collapse artifact-collapse-stacked">
          <summary className="artifact-collapse-summary">技术详情</summary>
          <div className="artifact-collapse-body">
            <InlineCode>{a.artifact_id}</InlineCode>
            {a.artifact_type && <> · <InlineCode>{a.artifact_type}</InlineCode></>}
            {a.relative_path && <> · path: <InlineCode>{a.relative_path}</InlineCode></>}
          </div>
        </details>
      </div>

      {/* Tabs */}
      <div className="tabs operations-tabs">
        {(["preview", "summary", "metadata"] as const).map((t) => (
          <button key={t} className={"tab" + (tab === t ? " active" : "")} onClick={() => onTab(t)} data-testid={`tab-${t}`}>
            {t === "preview" ? "预览" : t === "summary" ? "摘要" : "元数据"}
          </button>
        ))}
      </div>

      {tab === "preview" && <ContentTab artifact={a} />}
      {tab === "summary" && <SummaryTab artifact={a} />}
      {tab === "metadata" && <CodeBlock language="json">{JSON.stringify(a.metadata ?? {}, null, 2)}</CodeBlock>}
    </div>
  );
}

function Info({ label, children, mono }: { label: string; children: React.ReactNode; mono?: boolean }) {
  return <div className="artifact-info-cell"><div className="stat-card-box-label">{label}</div><div className={"stat-card-box-value" + (mono ? " mono" : "")}>{children}</div></div>;
}

/* ── Content tab ── */

function ContentTab({ artifact: a }: { artifact: Artifact }) {
  const ws = useSessionStore((s) => s.currentWorkspaceId);
  const toast = useToastStore((s) => s.show);
  const [d, setD] = useState<{ content: string } | null>(null);
  const [loading, setL] = useState(false);
  const [err, setE] = useState<string | null>(null);

  useEffect(() => {
    if (!ws) return; const c = new AbortController(); setD(null); setE(null); setL(true);
    artifactsApi.content(ws, a.artifact_id, c.signal)
      .then((r) => { if (!c.signal.aborted) setD(r); })
      .catch((e: any) => { if (!c.signal.aborted) { setE(isApiError(e) ? e.message : String(e)); toast({ kind: "error", title: "加载失败", body: isApiError(e) ? e.message : String(e) }); } })
      .finally(() => { if (!c.signal.aborted) setL(false); });
    return () => c.abort();
  }, [a.artifact_id, ws]);

  if (loading) return <LoadingState text="加载中…" />;
  if (err) return <ErrorState error={{ ok: false, status: 0, code: "network", message: err, timestamp: new Date().toISOString() }} />;
  if (!d) return <LoadingState />;
  if (!d.content) return (
    <div className="card artifact-empty-content">
      <div className="muted mb-1">无可用内容</div>
      <div className="faint text-sm">
        {a.redaction_applied ? "已脱敏，原始内容不可读" : a.artifact_type ? `${typeLabel(a)}暂无可预览内容` : "服务端未返回可预览内容"}
      </div>
    </div>
  );
  return (
    <div>
      <div className="artifact-copy-wrap mb-2">
        <Button size="sm" onClick={() => { navigator.clipboard?.writeText(d.content); toast({ kind: "success", title: "已复制" }); }}>复制</Button>
      </div>
      <CodeBlock language={a.mime_type || "text"}>{d.content}</CodeBlock>
    </div>
  );
}

/* ── Summary tab ── */

function SummaryTab({ artifact: a }: { artifact: Artifact }) {
  const ws = useSessionStore((s) => s.currentWorkspaceId);
  const [d, setD] = useState<any>(null);
  const [l, setL] = useState(false);
  const [e, setE] = useState<string | null>(null);

  useEffect(() => {
    if (!ws) return; const c = new AbortController(); setL(true); setE(null);
    artifactsApi.summarize(ws, a.artifact_id, c.signal)
      .then((r) => { if (!c.signal.aborted) setD(r); })
      .catch((er: any) => { if (!c.signal.aborted) setE(isApiError(er) ? er.message : String(er)); })
      .finally(() => { if (!c.signal.aborted) setL(false); });
    return () => c.abort();
  }, [a.artifact_id, ws]);

  if (l) return <LoadingState text="拉取摘要…" />;
  if (e) return <ErrorState error={{ ok: false, status: 0, code: "network", message: e, timestamp: new Date().toISOString() }} />;
  if (!d) return <LoadingState />;

  const inline = a.summary;
  const backend = d.summary?.summary;
  return (
    <div className="col-flex">
      {inline && <div className="card"><div className="card-title mb-1">内联摘要</div><div className="text-base">{inline}</div></div>}
      <div className="card">
        <div className="card-title mb-1">后端摘要</div>
        {backend ? <div className="text-base">{backend}</div> : <div className="muted text-sm">后端未返回 summary</div>}
      </div>
      {d.summary?.sha256_short && <div className="mono text-xs faint">SHA-256: {d.summary.sha256_short}</div>}
    </div>
  );
}

/* ── Helpers ── */

function typeLabel(a: Artifact): string {
  const m: Record<string, string> = { output_config: "配置产物", translated_config: "翻译配置", knowledge_doc: "知识文档", report: "报告", manual_review: "评审材料", topology: "拓扑材料", inspection_raw: "巡检原始证据" };
  return m[a.artifact_type || ""] || (a.artifact_type || "").replace(/_/g, " ") || "制品";
}

function artifactTaskId(a: Artifact): string {
  for (const value of [a.metadata?.producer_id, a.metadata?.task_id, a.metadata?.inspection_task_id]) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function ArtifactTaskGroup({ groupKey, initialOpen, children }: { groupKey: string; initialOpen: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(initialOpen);
  return <details
    data-testid={`artifact-group-${groupKey}`}
    open={open}
    onToggle={(event) => setOpen(event.currentTarget.open)}
    className="card artifact-task-group"
  >{children}</details>;
}

function groupArtifactsByTask(artifacts: Artifact[]) {
  const groups = new Map<string, { key: string; taskId: string; label: string; artifacts: Artifact[] }>();
  for (const artifact of artifacts) {
    const taskId = artifactTaskId(artifact);
    const key = taskId || "other";
    const trigger = typeof artifact.metadata?.producer_trigger === "string" ? triggerLabel(artifact.metadata.producer_trigger) : "";
    const group = groups.get(key) || {
      key,
      taskId,
      label: taskId ? (trigger || "任务制品") : "非任务制品",
      artifacts: [],
    };
    group.artifacts.push(artifact);
    groups.set(key, group);
  }
  return [...groups.values()];
}

function authorityLabel(a: Artifact): string {
  const domain = a.governance?.authority_domain || "";
  const status = a.governance?.authority_status || "not_applicable";
  if (status === "contextual") return "专项任务证据";
  if (status === "authoritative" && domain === "current_state") return "当前状态权威";
  if (status === "authoritative" && domain === "inspection") return "最新资产巡检";
  if (status === "historical" && domain === "current_state") return "权威基线历史";
  if (status === "historical" && domain === "inspection") return "资产巡检历史";
  const labels: Record<string, string> = {
    authoritative: "当前权威证据", provisional: "临时证据", historical: "历史版本",
    incomplete: "不完整采集", not_applicable: "业务交付物",
  };
  return labels[a.governance?.authority_status || "not_applicable"] || "业务交付物";
}

function AuthorityBadge({ artifact: a }: { artifact: Artifact }) {
  const status = a.governance?.authority_status || "not_applicable";
  const domain = a.governance?.authority_domain || "";
  if (status === "contextual") return <Badge kind="muted">专项证据</Badge>;
  if (status === "authoritative" && domain === "current_state") return <Badge kind="ok">当前状态权威</Badge>;
  if (status === "authoritative" && domain === "inspection") return <Badge kind="info">最新资产巡检</Badge>;
  if (status === "authoritative") return <Badge kind="ok">当前权威</Badge>;
  if (status === "provisional") return <Badge kind="warn">临时证据</Badge>;
  if (status === "incomplete") return <Badge kind="err">不完整</Badge>;
  if (status === "historical" && domain === "current_state") return <Badge kind="muted">权威基线历史</Badge>;
  if (status === "historical" && domain === "inspection") return <Badge kind="muted">资产巡检历史</Badge>;
  if (status === "historical") return <Badge kind="muted">历史版本</Badge>;
  return <Badge kind="muted">交付物</Badge>;
}

function triggerLabel(value: string): string {
  const parts = value.split(":", 3);
  if (parts[0] !== "assurance") return value || "直接巡检";
  const labels: Record<string, string> = {
    baseline_capture: "权威基线采集", topology_refresh: "关系证据刷新", fault_propagation: "故障传播分析",
    incident: "故障排查", change_pre: "变更前检查", change_post: "变更后验证", schedule: "定期检查",
  };
  return labels[parts[1]] || parts[1];
}

/* ── Report section ── */

function ReportSection() {
  const { currentWorkspaceId: wsId } = useSessionStore();
  const toast = useToastStore((s) => s.show);
  const [reports, setReports] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [show, setShow] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");

  const load = useCallback(async () => {
    if (!wsId) return; setLoading(true);
    try { const d = await reportsApi.list(wsId); setReports(d.reports ?? []); }
    catch (e: unknown) { toast({ kind: "error", title: "报告列表加载失败", body: isApiError(e) ? e.message : String(e) }); }
    setLoading(false);
  }, [wsId]);

  useEffect(() => { load(); }, [load]);

  const create = async () => {
    if (!wsId || !title.trim()) return;
    try {
      await reportsApi.create({ workspace_id: wsId, title: title.trim(), content: content.trim() || undefined });
      toast({ kind: "success", title: "报告已创建" }); setTitle(""); setContent(""); setShow(false); load();
    } catch (e: any) { toast({ kind: "error", title: "创建失败", body: isApiError(e) ? e.message : String(e) }); }
  };

  return (
    <div className="card artifact-report-section">
      <div className="row-flex artifact-report-header">
        <h3 className="text-md artifact-report-title">报告</h3>
        <Button size="sm" onClick={() => setShow(!show)}><IconPlus size={12} /> 新建</Button>
      </div>

      {show && (
        <div className="card card-accent-border artifact-report-form">
          <Input className="mb-2" placeholder="报告标题" value={title} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") create(); }} />
          <Textarea className="mb-2 artifact-report-textarea" placeholder="报告内容（可选）" value={content} onChange={(e) => setContent(e.target.value)} />
          <div className="row-flex-sm">
            <Button size="sm" variant="primary" onClick={create}>创建</Button>
            <Button size="sm" onClick={() => setShow(false)}>取消</Button>
          </div>
        </div>
      )}

      {loading ? <LoadingState text="加载报告…" /> :
        reports.length === 0 ? <div className="muted text-sm">暂无报告</div> :
          reports.map((r: any, i: number) => (
            <div key={r.artifact_id || i}
              className="report-row"
              onClick={() => { if (!wsId) return; reportsApi.content(wsId, r.artifact_id).then((d) => toast({ kind: "success", title: "报告内容", body: (d.content ?? "").slice(0, 200) + "…" })).catch(() => {}); }}>
              <span className="text-sm artifact-report-row-title">{r.title || r.artifact_id || `#${i + 1}`}</span>
              <span className="faint text-xs">{r.created_at ? formatCompactDate(r.created_at) : ""}</span>
            </div>
          ))}
    </div>
  );
}
