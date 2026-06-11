import { useState } from "react";
import { artifactsApi } from "../../api";
import {
  useAsync,
  AsyncView,
  Badge,
  CodeBlock,
  InlineCode,
} from "../../components/common";
import { useSessionStore } from "../../stores/session";
import type { Artifact } from "../../types";
import { IconBox, IconDocument, IconExternal } from "../../components/Icon";

const SENSITIVITY_LABEL: Record<string, string> = {
  public: "公开",
  internal: "内部",
  sensitive: "敏感",
  secret: "机密",
};

export function ArtifactCenter() {
  const { currentWorkspaceId } = useSessionStore();
  const [selected, setSelected] = useState<Artifact | null>(null);
  const [tab, setTab] = useState<"preview" | "diff" | "metadata">("preview");

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
            列出 / 预览 / 对比 / 导出 · <strong>不</strong>修改原 artifact
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
                        {a.authoritative && <Badge kind="pri">权威</Badge>}
                        {a.deployable_config && <Badge kind="warn">可下发</Badge>}
                        {a.sensitivity === "sensitive" && (
                          <Badge kind="warn">敏感</Badge>
                        )}
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
  tab: "preview" | "diff" | "metadata";
  onTabChange: (t: "preview" | "diff" | "metadata") => void;
}) {
  return (
    <div>
      <div
        className="row-flex"
        style={{ marginBottom: 12, paddingBottom: 12, borderBottom: "1px solid var(--line-soft)" }}
      >
        <span className="row-flex" style={{ minWidth: 0 }}>
          <IconDocument size={14} style={{ color: "var(--accent)" }} />
          <InlineCode>{artifact.artifact_id}</InlineCode>
          {artifact.title && <span className="muted text-sm">{artifact.title}</span>}
        </span>
        <span className="spacer" />
        {artifact.authoritative && <Badge kind="pri">权威</Badge>}
        {artifact.deployable_config && <Badge kind="warn">可下发</Badge>}
        <Badge kind="muted">
          {SENSITIVITY_LABEL[artifact.sensitivity ?? "internal"] ?? "内部"}
        </Badge>
        <button
          className="btn sm"
          type="button"
          onClick={() => {
            const text = artifact.content_preview ?? "";
            void navigator.clipboard?.writeText(text);
          }}
        >
          <IconExternal size={11} /> 复制
        </button>
      </div>

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
          className={"tab" + (tab === "diff" ? " active" : "")}
          onClick={() => onTabChange("diff")}
          data-testid="tab-diff"
        >
          对比
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
        {tab === "preview" && (
          <CodeBlock language="text">
            {artifact.content_preview ?? "(无可用预览)"}
          </CodeBlock>
        )}
        {tab === "diff" && (
          <div className="empty">
            <div className="empty-icon">⇌</div>
            <div className="empty-text">diff payload 由后端提供</div>
            <div className="empty-hint">
              如需 diff，请调用后端专门 endpoint（前端不实现 diff 业务）
            </div>
          </div>
        )}
        {tab === "metadata" && (
          <CodeBlock language="json">
            {JSON.stringify(artifact.metadata ?? {}, null, 2)}
          </CodeBlock>
        )}
      </div>
    </div>
  );
}
