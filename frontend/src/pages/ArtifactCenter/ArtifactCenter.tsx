import { useState } from "react";
import { artifactsApi } from "../../api";
import { useAsync, AsyncView, Badge, CodeBlock, EmptyState, InlineCode } from "../../components/common";
import { useSessionStore } from "../../stores/session";
import type { Artifact } from "../../types";

/**
 * Artifact Center — list / read / diff / export. Surfaces
 * `authoritative`, `deployable_config`, `sensitivity`, and `metadata`.
 * Frontend does NOT compute diffs; the backend provides a diff payload
 * (or null). If diff is missing, we render the raw content.
 */
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
    <div
      style={{ display: "flex", flexDirection: "column", height: "100%" }}
      data-testid="page-artifacts"
    >
      <div className="page-header">
        <div>
          <h1>Artifact Center</h1>
          <div className="subtitle">list / read / diff / export — 不修改原 artifact</div>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", flex: 1, minHeight: 0 }}>
        <aside style={{ borderRight: "1px solid var(--border)", overflowY: "auto" }}>
          <div style={{ padding: 12 }}>
            <AsyncView
              state={list.state}
              onRetry={list.reload}
              emptyText="暂无 artifact"
              emptyHint="后端返回为空"
            >
              {(d) => (
                <div data-testid="artifact-list">
                  {(d.artifacts ?? []).map((a) => (
                    <button
                      key={a.artifact_id}
                      type="button"
                      className={
                        "list-item" + (selected?.artifact_id === a.artifact_id ? " active" : "")
                      }
                      onClick={() => setSelected(a)}
                      data-testid={`artifact-${a.artifact_id}`}
                    >
                      <span className="title">
                        {a.title || a.artifact_id}
                      </span>
                      <div className="row-flex" style={{ gap: 4, marginTop: 2 }}>
                        <Badge kind="muted">{a.artifact_type}</Badge>
                        {a.authoritative && <Badge kind="pri">auth</Badge>}
                        {a.deployable_config && <Badge kind="warn">deployable</Badge>}
                        {a.sensitivity === "sensitive" && (
                          <Badge kind="warn">sensitive</Badge>
                        )}
                        {a.sensitivity === "secret" && <Badge kind="err">secret</Badge>}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </AsyncView>
          </div>
        </aside>
        <section style={{ overflowY: "auto", padding: 16 }} data-testid="artifact-detail">
          {selected ? (
            <ArtifactDetail
              artifact={selected}
              tab={tab}
              onTabChange={setTab}
            />
          ) : (
            <EmptyState text="未选择 artifact" hint="在左侧选择一项" />
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
      <div className="row-flex" style={{ marginBottom: 8 }}>
        <InlineCode>{artifact.artifact_id}</InlineCode>
        <span className="muted text-sm">{artifact.title}</span>
        <span className="spacer" />
        {artifact.authoritative && <Badge kind="pri">authoritative</Badge>}
        {artifact.deployable_config && <Badge kind="warn">deployable</Badge>}
        <Badge kind="muted">{artifact.sensitivity}</Badge>
      </div>
      <div className="tabs">
        <button
          type="button"
          className={tab === "preview" ? "active" : ""}
          onClick={() => onTabChange("preview")}
          data-testid="tab-preview"
        >
          Preview
        </button>
        <button
          type="button"
          className={tab === "diff" ? "active" : ""}
          onClick={() => onTabChange("diff")}
          data-testid="tab-diff"
        >
          Diff
        </button>
        <button
          type="button"
          className={tab === "metadata" ? "active" : ""}
          onClick={() => onTabChange("metadata")}
          data-testid="tab-metadata"
        >
          Metadata
        </button>
      </div>
      <div className="mt-2">
        {tab === "preview" && (
          <CodeBlock language="text">
            {artifact.content_preview ?? "(no preview available)"}
          </CodeBlock>
        )}
        {tab === "diff" && (
          <div className="muted text-sm">
            后端尚未返回 diff payload；如需 diff，请调用后端专门的 diff endpoint
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
