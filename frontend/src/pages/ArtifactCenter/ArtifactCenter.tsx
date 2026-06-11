import { useEffect, useState } from "react";
import { artifactsApi } from "../../api";
import {
  useAsync,
  AsyncView,
  Badge,
  CodeBlock,
  InlineCode,
  LoadingState,
  ErrorState,
} from "../../components/common";
import { useSessionStore } from "../../stores/session";
import { useToastStore } from "../../stores/toast";
import { isApiError } from "../../types";
import type { Artifact } from "../../types";
import { IconBox, IconDocument, IconShield } from "../../components/Icon";

const SENSITIVITY_LABEL: Record<string, string> = {
  public: "公开",
  internal: "内部",
  sensitive: "敏感",
  secret: "机密",
};

const LIFECYCLE_KIND: Record<string, "ok" | "warn" | "muted"> = {
  active: "ok",
  archived: "warn",
  deleted: "muted",
};

const LIFECYCLE_LABEL: Record<string, string> = {
  active: "活跃",
  archived: "归档",
  deleted: "已删",
};

const SOURCE_LABEL: Record<string, string> = {
  user_upload: "用户上传",
  module_output: "模块产出",
  agent_run: "Agent run",
};

export function ArtifactCenter() {
  const { currentWorkspaceId } = useSessionStore();
  const [selected, setSelected] = useState<Artifact | null>(null);
  const [tab, setTab] = useState<"preview" | "summary" | "metadata">("preview");

  const list = useAsync<{ artifacts: Artifact[] }>(
    (s) =>
      currentWorkspaceId
        ? artifactsApi.list(currentWorkspaceId, s)
        : Promise.resolve({ artifacts: [] }),
    [currentWorkspaceId],
    (d) => (d.artifacts ?? []).length === 0,
  );

  return (
    <div className="page" data-testid="page-artifacts">
      <div className="page-header">
        <div>
          <h1>
            制品中心{" "}
            <span style={{ color: "var(--ink-mute)", fontWeight: 400, fontSize: 14 }}>
              · Artifact Center
            </span>
          </h1>
          <div className="subtitle">
            列出 / 预览 / 摘要 / 元数据 · <strong>不</strong>修改原 artifact · 不暴露 <code>config.push</code>
          </div>
        </div>
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "320px 1fr",
          flex: 1,
          minHeight: 0,
        }}
      >
        <aside
          style={{
            borderRight: "1px solid var(--line)",
            overflowY: "auto",
            background: "var(--bg-elev)",
          }}
        >
          <div style={{ padding: 12 }}>
            <div className="section-head" style={{ paddingLeft: 4, marginBottom: 8 }}>
              <IconBox size={11} /> 制品列表
              <span className="mono" style={{
                marginLeft: "auto",
                fontSize: 10,
                color: "var(--ink-mute)",
                textTransform: "none",
                letterSpacing: 0,
              }}>
                {list.state.kind === "success" ? (list.state.data.artifacts ?? []).length : "—"}
              </span>
            </div>
            <AsyncView
              state={list.state}
              onRetry={list.reload}
              emptyText="暂无 artifact"
              emptyHint="后端返回为空"
            >
              {(d) => (
                <div className="list" data-testid="artifact-list">
                  {(d.artifacts ?? []).map((a) => (
                    <button
                      key={a.artifact_id}
                      type="button"
                      className={
                        "list-item" +
                        (selected?.artifact_id === a.artifact_id ? " active" : "")
                      }
                      onClick={() => setSelected(a)}
                      data-testid={`artifact-${a.artifact_id}`}
                      style={{
                        flexDirection: "column",
                        alignItems: "flex-start",
                        height: "auto",
                        padding: "8px 10px",
                        gap: 4,
                      }}
                    >
                      <span className="title" style={{ minWidth: 0 }}>
                        {a.title || a.artifact_id}
                      </span>
                      <div className="row-flex" style={{ gap: 4, flexWrap: "wrap" }}>
                        <Badge kind="muted">{a.artifact_type}</Badge>
                        {/* 权威 = 由某个 capability / module / skill 产出 */}
                        {(a.capability_id || a.module || a.skill) && (
                          <Badge kind="pri">权威</Badge>
                        )}
                        {/* 风险 = redacted 或敏感 */}
                        {a.redaction_applied && <Badge kind="warn">已脱敏</Badge>}
                        {a.sensitivity === "sensitive" && <Badge kind="warn">敏感</Badge>}
                        {a.sensitivity === "secret" && <Badge kind="err">机密</Badge>}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </AsyncView>
          </div>
        </aside>
        <section
          style={{ overflowY: "auto", padding: 20, minHeight: 0 }}
          data-testid="artifact-detail"
        >
          {selected ? (
            <ArtifactDetail
              artifact={selected}
              tab={tab}
              onTabChange={setTab}
            />
          ) : (
            <div className="hero" style={{ minHeight: "auto", padding: 60 }}>
              <div className="hero-mark">制</div>
              <h1 className="hero-title">未选择 artifact</h1>
              <p className="hero-sub">在左侧列表中选择一项查看详情</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function ArtifactDetail({
  artifact,
  tab,
  onTabChange,
}: {
  artifact: Artifact;
  tab: "preview" | "summary" | "metadata";
  onTabChange: (t: "preview" | "summary" | "metadata") => void;
}) {
  return (
    <div>
      {/* Header */}
      <div
        className="row-flex"
        style={{
          marginBottom: 12,
          paddingBottom: 12,
          borderBottom: "1px solid var(--line-soft)",
        }}
      >
        <span className="row-flex" style={{ minWidth: 0 }}>
          <IconDocument size={14} style={{ color: "var(--accent)" }} />
          <InlineCode>{artifact.artifact_id}</InlineCode>
          {artifact.title && (
            <span className="muted text-sm">{artifact.title}</span>
          )}
        </span>
        <span className="spacer" />
        {(artifact.capability_id || artifact.module || artifact.skill) && (
          <Badge kind="pri" withDot>权威</Badge>
        )}
        {artifact.redaction_applied && <Badge kind="warn">已脱敏</Badge>}
        <Badge kind="muted">
          {SENSITIVITY_LABEL[artifact.sensitivity] ?? artifact.sensitivity}
        </Badge>
        <Badge kind={LIFECYCLE_KIND[artifact.lifecycle]}>
          {LIFECYCLE_LABEL[artifact.lifecycle] ?? artifact.lifecycle}
        </Badge>
        <span className="text-xs muted">
          {SOURCE_LABEL[artifact.source] ?? artifact.source}
        </span>
      </div>

      {/* File metadata strip */}
      <div
        className="row-flex"
        style={{
          gap: 16,
          padding: "10px 14px",
          background: "var(--bg-soft)",
          borderRadius: "var(--r-sm)",
          marginBottom: 16,
          fontSize: 11,
          color: "var(--ink-soft)",
          fontFamily: "var(--font-mono)",
          flexWrap: "wrap",
        }}
      >
        <span>
          类型: <strong>{artifact.mime_type || "(未知)"}</strong>
        </span>
        <span>
          大小: <strong>{formatBytes(artifact.size_bytes)}</strong>
        </span>
        {artifact.sha256_short && (
          <span title={artifact.sha256_short}>
            SHA-256: <strong>{artifact.sha256_short}…</strong>
          </span>
        )}
        {artifact.relative_path && (
          <span title={artifact.relative_path}>
            路径: <strong>{artifact.relative_path}</strong>
          </span>
        )}
        <span className="spacer" />
        {artifact.capability_id && (
          <span>
            来源能力: <strong>{artifact.capability_id}</strong>
          </span>
        )}
        {artifact.run_id && (
          <span>
            run: <strong>{artifact.run_id}</strong>
          </span>
        )}
      </div>

      {/* Tabs */}
      <div className="tabs">
        <button
          type="button"
          className={"tab" + (tab === "preview" ? " active" : "")}
          onClick={() => onTabChange("preview")}
          data-testid="tab-preview"
        >
          预览
        </button>
        <button
          type="button"
          className={"tab" + (tab === "summary" ? " active" : "")}
          onClick={() => onTabChange("summary")}
          data-testid="tab-summary"
        >
          摘要
        </button>
        <button
          type="button"
          className={"tab" + (tab === "metadata" ? " active" : "")}
          onClick={() => onTabChange("metadata")}
          data-testid="tab-metadata"
        >
          元数据
        </button>
      </div>

      <div className="mt-3">
        {tab === "preview" && <ContentTab artifact={artifact} />}
        {tab === "summary" && <SummaryTab artifact={artifact} />}
        {tab === "metadata" && (
          <CodeBlock language="json">
            {JSON.stringify(artifact.metadata ?? {}, null, 2)}
          </CodeBlock>
        )}
      </div>
    </div>
  );
}

function ContentTab({ artifact }: { artifact: Artifact }) {
  const { currentWorkspaceId } = useSessionStore();
  const toast = useToastStore((s) => s.show);
  const [data, setData] = useState<{ content: string; title?: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // 每次切换 artifact 重新拉取
    setData(null);
    setError(null);
    if (!currentWorkspaceId) return;
    setLoading(true);
    artifactsApi
      .content(currentWorkspaceId, artifact.artifact_id)
      .then((res) => {
        setData({ content: res.content, title: res.metadata?.title as string | undefined });
      })
      .catch((e: unknown) => {
        const msg = isApiError(e) ? e.message : String(e);
        setError(msg);
        toast({
          kind: "error",
          title: "加载内容失败",
          body: msg,
          request_id: isApiError(e) ? e.request_id : undefined,
        });
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifact.artifact_id, currentWorkspaceId]);

  async function onCopy() {
    if (!data) return;
    try {
      await navigator.clipboard?.writeText(data.content);
      toast({ kind: "success", title: "已复制到剪贴板" });
    } catch {
      toast({ kind: "warning", title: "复制失败", body: "浏览器拒绝访问剪贴板" });
    }
  }

  if (loading) return <LoadingState text="加载内容中…" />;
  if (error)
    return (
      <ErrorState
        error={{
          ok: false,
          status: 0,
          code: "network",
          message: error,
          timestamp: new Date().toISOString(),
        }}
      />
    );
  if (!data) return <LoadingState text="准备中…" />;
  if (!data.content) {
    return (
      <div
        className="empty"
        data-testid="empty-content"
        style={{ padding: 40, background: "var(--bg-soft)", borderRadius: "var(--r)" }}
      >
        <div className="empty-icon">
          <IconShield size={20} style={{ color: "var(--ink-faint)" }} />
        </div>
        <div className="empty-text">无可用内容</div>
        <div className="empty-hint">
          {artifact.redaction_applied
            ? "此 artifact 在持久化时已被脱敏，原始内容不可读。"
            : artifact.artifact_type
              ? `artifact_type=${artifact.artifact_type}，后端未提供可读内容。`
              : "后端未返回 content。"}
        </div>
        <div className="text-xs muted mt-3 mono">
          size: {formatBytes(artifact.size_bytes)} ·{" "}
          {artifact.relative_path || "(无路径)"}
        </div>
      </div>
    );
  }
  return (
    <div>
      <div className="row-flex mb-2" style={{ justifyContent: "flex-end" }}>
        <button className="btn sm" type="button" onClick={onCopy}>
          复制
        </button>
      </div>
      <CodeBlock language={artifact.mime_type || "text"}>{data.content}</CodeBlock>
    </div>
  );
}

function SummaryTab({ artifact }: { artifact: Artifact }) {
  const { currentWorkspaceId } = useSessionStore();
  const [data, setData] = useState<{
    ok: boolean;
    summary: { summary: string; sensitivity?: string; size_bytes?: number; sha256_short?: string };
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!currentWorkspaceId) return;
    setLoading(true);
    setError(null);
    artifactsApi
      .summarize(currentWorkspaceId, artifact.artifact_id)
      .then((res) => setData(res))
      .catch((e: unknown) => {
        setError(isApiError(e) ? e.message : String(e));
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifact.artifact_id, currentWorkspaceId]);

  if (loading) return <LoadingState text="拉取后端摘要…" />;
  if (error)
    return (
      <ErrorState
        error={{
          ok: false,
          status: 0,
          code: "network",
          message: error,
          timestamp: new Date().toISOString(),
        }}
      />
    );
  if (!data) return <LoadingState />;
  const inlineSummary = artifact.summary;
  const backendSummary = data.summary.summary;
  return (
    <div className="col-flex" style={{ gap: 12 }}>
      {inlineSummary ? (
        <div
          className="card"
          style={{ padding: 14, marginBottom: 0, boxShadow: "none" }}
        >
          <div className="card-title" style={{ marginBottom: 6 }}>
            内联摘要
          </div>
          <div className="text-sm">{inlineSummary}</div>
        </div>
      ) : null}
      <div className="card" style={{ padding: 14, marginBottom: 0, boxShadow: "none" }}>
        <div className="card-title" style={{ marginBottom: 6 }}>
          后端摘要
        </div>
        {backendSummary ? (
          <div className="text-sm">{backendSummary}</div>
        ) : (
          <div className="muted text-sm">
            后端未返回 summary。({data.summary.size_bytes ?? 0} 字节 ·{" "}
            {data.summary.sensitivity ?? artifact.sensitivity})
          </div>
        )}
      </div>
      {data.summary.sha256_short && (
        <div className="text-xs muted mono">
          sha256: {data.summary.sha256_short}
        </div>
      )}
    </div>
  );
}

function formatBytes(n: number): string {
  if (!n || n <= 0) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}
