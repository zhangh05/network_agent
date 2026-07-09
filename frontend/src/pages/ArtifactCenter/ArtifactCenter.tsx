/**
 * ArtifactCenter — 制品中心 (v3.3.1 美化)
 */
import { useEffect, useState, useCallback } from "react";
import { artifactsApi, reportsApi } from "../../api";
import { useAsync, AsyncView, Badge, CodeBlock, InlineCode, LoadingState, ErrorState } from "../../components/common";
import { useSessionStore } from "../../stores/session";
import { useToastStore } from "../../stores/toast";
import { isApiError } from "../../types";
import type { Artifact } from "../../types";
import { IconDocument, IconPlus } from "../../components/Icon";
import { formatCompactDate } from "../../utils/displayText";
import { formatFileSize } from "../../utils/format";

const SENS_LABEL: Record<string, string> = { public: "公开", internal: "内部", sensitive: "敏感", secret: "机密" };
const LC_KIND: Record<string, "ok" | "warn" | "muted"> = { active: "ok", archived: "warn", deleted: "muted" };
const LC_LABEL: Record<string, string> = { active: "活跃", archived: "归档", deleted: "已删" };
const SRC_LABEL: Record<string, string> = { user_upload: "用户上传", module_output: "模块产出", agent_run: "Agent run" };

export function ArtifactCenter() {
  const { currentWorkspaceId } = useSessionStore();
  const [sel, setSel] = useState<Artifact | null>(null);
  const [tab, setTab] = useState<"preview" | "summary" | "metadata">("preview");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [batch, setBatch] = useState(false);
  const toast = useToastStore((s) => s.show);

  const list = useAsync<{ artifacts: Artifact[] }>(
    (s) => currentWorkspaceId ? artifactsApi.list(currentWorkspaceId, s) : Promise.resolve({ artifacts: [] }),
    [currentWorkspaceId], (d) => (d.artifacts ?? []).length === 0,
  );

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

  return (
    <div className="page" data-testid="page-artifacts">
      <div className="page-header" style={{ background: "var(--surface)" }}>
        <div>
          <h1>制品中心<span style={{ color: "var(--ink-mute)", fontWeight: 400, fontSize: 14, marginLeft: 6 }}>· Artifacts</span></h1>
          <p className="subtitle">列出 / 预览 / 摘要 / 元数据 · 不修改原 artifact</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
          <div className="status-pill"><span className="dot" style={{ background: "var(--accent)" }} />{total} 个</div>
        </div>
      </div>

      <div className="split-shell" style={{ flex: 1 }}>
        {/* Left list */}
        <aside style={{ padding: 12, overflow: "auto" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <span style={{ fontSize: "var(--fs-12)", fontWeight: 680, color: "var(--text-2)" }}>制品列表</span>
            <div style={{ flex: 1 }} />
            <button className={`btn sm ${batch ? "danger" : ""}`} onClick={() => { setBatch(!batch); if (batch) setChecked(new Set()); }}>
              {batch ? "取消" : "批量删除"}
            </button>
          </div>
          {batch && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, padding: "6px 10px", background: "var(--surface-2)", borderRadius: "var(--r-6)", border: `1px solid ${checked.size > 0 ? "var(--accent)" : "var(--line)"}` }}>
              <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", flex: 1 }}>
                <input type="checkbox"
                  checked={list.state.kind === "success" && checked.size === (list.state.data.artifacts ?? []).length && (list.state.data.artifacts ?? []).length > 0}
                  onChange={(e) => {
                    if (e.target.checked && list.state.kind === "success") {
                      setChecked(new Set((list.state.data.artifacts ?? []).map((a) => a.artifact_id)));
                    } else {
                      setChecked(new Set());
                    }
                  }}
                  style={{ width: 14, height: 14, cursor: "pointer", accentColor: "var(--accent)" }} />
                <span style={{ fontSize: "var(--fs-12)", fontWeight: 620, color: "var(--text-2)" }}>
                  全选 {checked.size > 0 && `(已选 ${checked.size})`}
                </span>
              </label>
              <button className="btn sm danger" disabled={checked.size === 0} onClick={delBatch}
                style={{ opacity: checked.size === 0 ? 0.5 : 1, cursor: checked.size === 0 ? "not-allowed" : "pointer" }}>
                删除 {checked.size || ""} 项
              </button>
            </div>
          )}
          <AsyncView state={list.state} onRetry={list.reload} emptyText="暂无制品" emptyHint="后端返回为空">
            {(d) => (
              <div data-testid="artifact-list">
                {(d.artifacts ?? []).map((a) => {
                  const active = sel?.artifact_id === a.artifact_id;
                  return (
                    <div key={a.artifact_id} style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 4 }}>
                      {batch && (
                        <input type="checkbox" checked={checked.has(a.artifact_id)} onChange={(e) => { const n = new Set(checked); e.target.checked ? n.add(a.artifact_id) : n.delete(a.artifact_id); setChecked(n); }}
                          style={{ width: 14, height: 14, cursor: "pointer", flexShrink: 0, accentColor: "var(--accent)" }} />
                      )}
                      <button type="button"
                        className={`card`}
                        onClick={() => { setSel(a); setTab("preview"); }}
                        data-testid={`artifact-${a.artifact_id}`}
                        style={{
                          flex: 1, textAlign: "left", padding: "10px 12px", cursor: "pointer",
                          borderColor: active ? "var(--accent)" : "var(--line)",
                          background: active ? "var(--accent-soft)" : "var(--surface)",
                        }}>
                        <div style={{ fontSize: "var(--fs-13)", fontWeight: 680, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginBottom: 3 }}>
                          {a.title || a.artifact_id}
                        </div>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
                          <Badge kind="muted">{typeLabel(a)}</Badge>
                          {isAuthoritative(a) && <Badge kind="ok">权威</Badge>}
                          {a.sensitivity === "sensitive" && <Badge kind="warn">敏感</Badge>}
                          {a.sensitivity === "secret" && <Badge kind="err">机密</Badge>}
                          {a.redaction_applied && <Badge kind="warn">脱敏</Badge>}
                          {a.created_at && <span style={{ fontSize: "var(--fs-10)", color: "var(--text-4)" }}>{formatCompactDate(a.created_at)}</span>}
                        </div>
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </AsyncView>
        </aside>

        {/* Right detail */}
        <div className="split-detail" style={{ padding: "24px", overflow: "auto" }}>
          {sel ? (
            <Detail artifact={sel} tab={tab} onTab={setTab} onDel={() => delOne(sel.artifact_id, sel.title || "")} />
          ) : (
            <div className="empty" style={{ minHeight: "100%" }}>
              <div className="empty-icon" style={{ background: "var(--surface-2)" }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--text-4)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
                </svg>
              </div>
              <div className="empty-text" style={{ fontSize: "var(--fs-13)" }}>选择一件制品</div>
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
    <div data-testid="artifact-detail" style={{ animation: "surface-in var(--dur-4) var(--ease-out) both" }}>
      {/* Title bar */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        <IconDocument size={16} style={{ color: "var(--accent)", flexShrink: 0 }} />
        <h3 style={{ fontSize: "var(--fs-16)", fontWeight: 720, margin: 0 }}>{a.title || a.artifact_id}</h3>
        <Badge kind="muted">{SENS_LABEL[a.sensitivity] || a.sensitivity}</Badge>
        <Badge kind={LC_KIND[a.lifecycle]}>{LC_LABEL[a.lifecycle] || a.lifecycle}</Badge>
        {isAuthoritative(a) && <Badge kind="ok">权威</Badge>}
        {a.redaction_applied && <Badge kind="warn">脱敏</Badge>}
        <div style={{ flex: 1 }} />
        <button className="btn sm danger-ghost" onClick={onDel}>删除</button>
      </div>

      {/* Facts card */}
      <div className="card" style={{ padding: "14px 16px", marginBottom: 16 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "10px 16px" }}>
          <Info label="类型">{typeLabel(a)}</Info>
          <Info label="来源">{SRC_LABEL[a.source] || a.source}</Info>
          <Info label="MIME">{a.mime_type || "—"}</Info>
          <Info label="大小">{formatFileSize(a.size_bytes)}</Info>
          {a.sha256_short && <Info label="SHA-256" mono>{a.sha256_short}</Info>}
          {a.capability_id && <Info label="能力">{a.capability_id}</Info>}
          {a.run_id && <Info label="Run" mono>{a.run_id}</Info>}
          <Info label="使用状态">否，需要人工复核</Info>
        </div>
        <details className="collapse" style={{ marginTop: 8 }}>
          <summary style={{ fontSize: "var(--fs-11)", color: "var(--text-4)", cursor: "pointer" }}>技术详情</summary>
          <div style={{ marginTop: 4, fontSize: "var(--fs-11)", color: "var(--text-3)" }}>
            <InlineCode>{a.artifact_id}</InlineCode>
            {a.artifact_type && <> · <InlineCode>{a.artifact_type}</InlineCode></>}
            {a.relative_path && <> · path: <InlineCode>{a.relative_path}</InlineCode></>}
          </div>
        </details>
      </div>

      {/* Tabs */}
      <div className="tabs" style={{ marginBottom: 16 }}>
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
  return <div style={{ minWidth: 0 }}><div style={{ fontSize: "var(--fs-10)", color: "var(--text-4)", textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 680, marginBottom: 3 }}>{label}</div><div style={{ fontSize: "var(--fs-12)", color: "var(--text-2)", fontWeight: 620, fontFamily: mono ? "var(--font-mono)" : undefined, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{children}</div></div>;
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
    <div className="card" style={{ padding: "32px 16px", textAlign: "center" }}>
      <div style={{ color: "var(--text-3)", fontSize: "var(--fs-13)", marginBottom: 6 }}>无可用内容</div>
      <div style={{ fontSize: "var(--fs-11)", color: "var(--text-4)" }}>
        {a.redaction_applied ? "已脱敏，原始内容不可读" : a.artifact_type ? `artifact_type=${a.artifact_type}，无内容` : "后端未返回 content"}
      </div>
    </div>
  );
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
        <button className="btn sm" onClick={() => { navigator.clipboard?.writeText(d.content); toast({ kind: "success", title: "已复制" }); }}>复制</button>
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
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {inline && <div className="card" style={{ padding: 14 }}><div className="card-title" style={{ marginBottom: 6 }}>内联摘要</div><div style={{ fontSize: "var(--fs-13)", color: "var(--text-2)" }}>{inline}</div></div>}
      <div className="card" style={{ padding: 14 }}>
        <div className="card-title" style={{ marginBottom: 6 }}>后端摘要</div>
        {backend ? <div style={{ fontSize: "var(--fs-13)", color: "var(--text-2)" }}>{backend}</div> : <div style={{ fontSize: "var(--fs-12)", color: "var(--text-3)" }}>后端未返回 summary</div>}
      </div>
      {d.summary?.sha256_short && <div style={{ fontSize: "var(--fs-11)", color: "var(--text-4)", fontFamily: "var(--font-mono)" }}>SHA-256: {d.summary.sha256_short}</div>}
    </div>
  );
}

/* ── Helpers ── */

function typeLabel(a: Artifact): string {
  const m: Record<string, string> = { output_config: "配置产物", translated_config: "翻译配置", knowledge_doc: "知识文档", report: "报告", manual_review: "评审材料", topology: "拓扑材料" };
  return m[a.artifact_type || ""] || (a.artifact_type || "").replace(/_/g, " ") || "制品";
}

function isAuthoritative(a: Artifact): boolean {
  return Boolean(a.capability_id || a.module || a.skill);
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
    <div className="card" style={{ marginTop: 20, padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <h3 style={{ fontSize: "var(--fs-15)", fontWeight: 720, margin: 0 }}>报告</h3>
        <button className="btn sm" onClick={() => setShow(!show)}><IconPlus size={12} /> 新建</button>
      </div>

      {show && (
        <div className="card" style={{ padding: 12, marginBottom: 12, borderColor: "var(--accent)" }}>
          <input className="input" style={{ marginBottom: 8 }} placeholder="报告标题" value={title} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") create(); }} />
          <textarea className="input" style={{ marginBottom: 8, minHeight: 72 }} placeholder="报告内容（可选）" value={content} onChange={(e) => setContent(e.target.value)} />
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn primary sm" onClick={create}>创建</button>
            <button className="btn sm" onClick={() => setShow(false)}>取消</button>
          </div>
        </div>
      )}

      {loading ? <LoadingState text="加载报告…" /> :
        reports.length === 0 ? <div style={{ fontSize: "var(--fs-12)", color: "var(--text-3)" }}>暂无报告</div> :
          reports.map((r: any, i: number) => (
            <div key={r.artifact_id || i}
              className="row-flex" style={{
                padding: "8px 12px", marginBottom: 4, border: "1px solid var(--line-2)", borderRadius: "var(--r-6)", cursor: "pointer",
                justifyContent: "space-between", transition: "background var(--dur-2) var(--ease)",
              }}
              onMouseOver={(e) => (e.currentTarget.style.background = "var(--surface-2)")}
              onMouseOut={(e) => (e.currentTarget.style.background = "")}
              onClick={() => { if (!wsId) return; reportsApi.content(wsId, r.artifact_id).then((d) => toast({ kind: "success", title: "报告内容", body: (d.content ?? "").slice(0, 200) + "…" })).catch(() => {}); }}>
              <span style={{ fontSize: "var(--fs-13)", fontWeight: 650 }}>{r.title || r.artifact_id || `#${i + 1}`}</span>
              <span style={{ fontSize: "var(--fs-11)", color: "var(--text-4)" }}>{r.created_at ? formatCompactDate(r.created_at) : ""}</span>
            </div>
          ))}
    </div>
  );
}
