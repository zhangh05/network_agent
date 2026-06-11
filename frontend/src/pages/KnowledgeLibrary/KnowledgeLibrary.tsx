import { useState } from "react";
import { useAsync, AsyncView, Badge, CodeBlock, EmptyState, InlineCode } from "../../components/common";
import { knowledgeApi, artifactsApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { useToastStore } from "../../stores/toast";
import { isApiError } from "../../types";
import type { KnowledgeSource } from "../../types";

/**
 * Knowledge Library — list/read/search/reindex + import-from-artifact.
 * Real backend endpoints (v1.0.1 fix):
 *   GET   /api/knowledge/sources?workspace_id=
 *   POST  /api/knowledge/sources/from-artifact  (JSON, not multipart)
 *   POST  /api/knowledge/sources/<id>/reindex
 *   GET   /api/knowledge/search?q=&workspace_id=
 *   GET   /api/knowledge/chunks/<id>?workspace_id=
 */
export function KnowledgeLibrary() {
  const { currentWorkspaceId } = useSessionStore();
  const toast = useToastStore((s) => s.show);
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<"workspace" | "global" | "session">("workspace");
  const [importArtifactId, setImportArtifactId] = useState("");
  const [importing, setImporting] = useState(false);

  const sources = useAsync<{ sources: KnowledgeSource[]; counts?: Record<string, number> }>(
    (s) =>
      currentWorkspaceId
        ? knowledgeApi.listSources(currentWorkspaceId, s)
        : Promise.resolve({ sources: [] }),
    [currentWorkspaceId],
    (d) => (d.sources ?? []).length === 0,
  );

  const search = useAsync<Awaited<ReturnType<typeof knowledgeApi.search>> | null>(
    (s) =>
      currentWorkspaceId && query.trim()
        ? knowledgeApi.search(query, currentWorkspaceId, undefined, s)
        : Promise.resolve(null),
    [query, currentWorkspaceId],
  );

  const artifacts = useAsync<{ artifacts: { artifact_id: string; title?: string }[] }>(
    (s) =>
      currentWorkspaceId
        ? artifactsApi.list(currentWorkspaceId, s)
        : Promise.resolve({ artifacts: [] }),
    [currentWorkspaceId],
    (d) => (d.artifacts ?? []).length === 0,
  );

  async function onReindex(source_id: string) {
    if (!currentWorkspaceId) return;
    try {
      await knowledgeApi.reindex(source_id, currentWorkspaceId);
      toast({ kind: "success", title: "reindex 已提交", body: source_id });
      sources.reload();
    } catch (e: unknown) {
      toast({
        kind: "error",
        title: "reindex 失败",
        body: isApiError(e) ? e.message : String(e),
        request_id: isApiError(e) ? e.request_id : undefined,
      });
    }
  }

  async function onImport() {
    if (!currentWorkspaceId || !importArtifactId.trim()) return;
    setImporting(true);
    try {
      const res = await knowledgeApi.importFromArtifact(
        currentWorkspaceId,
        importArtifactId.trim(),
      );
      toast({
        kind: "success",
        title: "已导入",
        body: res.source?.title || res.source?.source_id || importArtifactId,
      });
      setImportArtifactId("");
      sources.reload();
    } catch (e: unknown) {
      toast({
        kind: "error",
        title: "导入失败",
        body: isApiError(e) ? e.message : String(e),
        request_id: isApiError(e) ? e.request_id : undefined,
      });
    } finally {
      setImporting(false);
    }
  }

  return (
    <div
      style={{ display: "flex", flexDirection: "column", height: "100%" }}
      data-testid="page-knowledge"
    >
      <div className="page-header">
        <div>
          <h1>Knowledge Library</h1>
          <div className="subtitle">
            source list / search / reindex / import-from-artifact · scope: {scope}
          </div>
        </div>
        <div className="row-flex">
          <select
            className="input"
            value={scope}
            onChange={(e) => setScope(e.target.value as "workspace" | "global" | "session")}
            style={{ width: 140 }}
            data-testid="knowledge-scope"
            disabled
            title="scope 由当前 workspace 决定；UI 暂未提供 multi-scope 切换"
          >
            <option value="workspace">workspace</option>
            <option value="global">global</option>
            <option value="session">session</option>
          </select>
        </div>
      </div>

      <div style={{ padding: 16, overflowY: "auto", flex: 1 }}>
        <div className="card" data-testid="knowledge-import-card">
          <div className="card-title">Import from artifact</div>
          <div className="text-xs muted mb-2">
            后端从 <InlineCode>/api/workspaces/&lt;ws&gt;/artifacts/&lt;art&gt;</InlineCode> 读取内容并建立 knowledge source。
            真实上传走 <InlineCode>POST /api/workspaces/&lt;ws&gt;/artifacts</InlineCode>（后端 artifact pipeline）。
          </div>
          <div className="row-flex">
            <select
              className="input"
              value={importArtifactId}
              onChange={(e) => setImportArtifactId(e.target.value)}
              data-testid="knowledge-import-select"
              style={{ flex: 1 }}
              disabled={artifacts.state.kind === "loading"}
            >
              <option value="">选择 artifact…</option>
              {(artifacts.state.kind === "success" ? artifacts.state.data.artifacts : []).map(
                (a) => (
                  <option key={a.artifact_id} value={a.artifact_id}>
                    {a.title || a.artifact_id}
                  </option>
                ),
              )}
            </select>
            <button
              className="btn primary"
              onClick={onImport}
              disabled={importing || !importArtifactId.trim()}
              data-testid="btn-knowledge-import"
              type="button"
            >
              {importing ? "导入中…" : "导入"}
            </button>
          </div>
          {artifacts.state.kind === "empty" && (
            <div className="text-xs muted mt-2">
              当前 workspace 无 artifact。先到 Artifacts 页创建/上传。
            </div>
          )}
        </div>

        <div className="card">
          <div className="card-title">Sources</div>
          <AsyncView
            state={sources.state}
            onRetry={sources.reload}
            emptyText="暂无 source"
            emptyHint="调用 import-from-artifact 导入"
          >
            {(d) => (
              <table className="tbl" data-testid="knowledge-source-tbl">
                <thead>
                  <tr>
                    <th>title</th>
                    <th>type</th>
                    <th>artifact</th>
                    <th>tags</th>
                    <th>chunks</th>
                    <th>status</th>
                    <th>actions</th>
                  </tr>
                </thead>
                <tbody>
                  {(d.sources ?? []).map((s) => (
                    <tr key={s.source_id} data-testid={`src-${s.source_id}`}>
                      <td><InlineCode>{s.title || s.source_id}</InlineCode></td>
                      <td><Badge kind="muted">{s.source_type || "—"}</Badge></td>
                      <td className="text-xs">
                        {s.artifact_id ? <InlineCode>{s.artifact_id}</InlineCode> : "—"}
                      </td>
                      <td className="text-xs">
                        {(s.tags ?? []).map((t) => <Badge key={t} kind="muted">{t}</Badge>)}
                      </td>
                      <td className="mono">{s.chunk_count}</td>
                      <td>
                        {s.status ? <Badge kind="info">{s.status}</Badge> : <Badge kind="muted">—</Badge>}
                      </td>
                      <td>
                        <button
                          className="btn sm"
                          onClick={() => void onReindex(s.source_id)}
                          data-testid={`btn-reindex-${s.source_id}`}
                          type="button"
                        >
                          reindex
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </AsyncView>
        </div>

        <div className="card">
          <div className="card-title">Search</div>
          <div className="row-flex mb-2">
            <input
              className="input"
              placeholder="输入查询 (CJK / English)"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              data-testid="knowledge-search-input"
            />
            <button
              className="btn primary"
              onClick={search.reload}
              disabled={!query.trim()}
              data-testid="btn-knowledge-search"
              type="button"
            >
              检索
            </button>
          </div>
          {search.state.kind === "loading" && (
            <div className="text-sm muted">搜索中…</div>
          )}
          {search.state.kind === "error" && (
            <div className="text-sm" style={{ color: "var(--danger)" }} data-testid="knowledge-search-error">
              {search.state.error.message}
              {search.state.error.request_id && (
                <span className="text-xs muted" style={{ marginLeft: 8 }}>
                  req_id: {search.state.error.request_id}
                </span>
              )}
            </div>
          )}
          {search.state.kind === "success" && search.state.data && (
            <SearchResults data={search.state.data} />
          )}
        </div>
      </div>
    </div>
  );
}

function SearchResults({
  data,
}: {
  data: Awaited<ReturnType<typeof knowledgeApi.search>>;
}) {
  const results = data.results ?? [];
  if (results.length === 0) {
    return <EmptyState text="无命中" hint="尝试调整 scope 或关键词" />;
  }
  return (
    <div data-testid="knowledge-search-results">
      <div className="text-sm muted mb-2">
        count: {results.length} · {data.note ?? "搜索结果为安全摘录"}
      </div>
      {results.slice(0, 10).map((r, i) => (
        <div className="card" key={r.chunk_id} style={{ padding: 10, marginBottom: 8 }} data-testid={`search-result-${i}`}>
          <div className="row-flex" style={{ justifyContent: "space-between" }}>
            <InlineCode>{r.title || r.source_id}</InlineCode>
            <Badge kind="pri">score {r.score.toFixed(2)}</Badge>
          </div>
          <div className="text-sm mt-2">
            {r.safe_excerpt || r.summary || "(no excerpt)"}
          </div>
          {r.artifact_id && (
            <div className="text-xs muted mt-2">
              artifact: <InlineCode>{r.artifact_id}</InlineCode>
            </div>
          )}
        </div>
      ))}
      <details>
        <summary className="text-xs muted">raw results</summary>
        <CodeBlock language="json">
          {JSON.stringify(results.slice(0, 5), null, 2)}
        </CodeBlock>
      </details>
    </div>
  );
}
