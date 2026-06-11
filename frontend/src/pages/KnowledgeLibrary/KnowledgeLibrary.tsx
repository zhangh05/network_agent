import { useState } from "react";
import { useAsync, AsyncView, Badge, CodeBlock, EmptyState, InlineCode, LoadingState } from "../../components/common";
import { knowledgeApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { useToastStore } from "../../stores/toast";
import { isApiError } from "../../types";
import type { KnowledgeSource } from "../../types";

/**
 * Knowledge Library — list/read/disable/delete sources, search chunks,
 * read chunk / parent, reindex, retrieval metadata.
 */
export function KnowledgeLibrary() {
  const { currentWorkspaceId } = useSessionStore();
  const toast = useToastStore((s) => s.show);
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<"workspace" | "global" | "session">("workspace");

  const sources = useAsync<{ sources: KnowledgeSource[] }>(
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
        ? knowledgeApi.search(query, currentWorkspaceId, s)
        : Promise.resolve(null),
    [query, currentWorkspaceId],
  );

  async function onReindex(source_id: string) {
    try {
      await knowledgeApi.reindex(source_id);
      toast({ kind: "success", title: "reindex 已提交", body: source_id });
      sources.reload();
    } catch (e: unknown) {
      toast({
        kind: "error",
        title: "reindex 失败",
        body: isApiError(e) ? e.message : String(e),
      });
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
            source list / search / read / reindex；scope: {scope}
          </div>
        </div>
        <div className="row-flex">
          <select
            className="input"
            value={scope}
            onChange={(e) => setScope(e.target.value as "workspace" | "global" | "session")}
            style={{ width: 140 }}
            data-testid="knowledge-scope"
          >
            <option value="workspace">workspace</option>
            <option value="global">global</option>
            <option value="session">session</option>
          </select>
        </div>
      </div>

      <div style={{ padding: 16, overflowY: "auto", flex: 1 }}>
        <div className="card">
          <div className="card-title">Sources</div>
          <AsyncView
            state={sources.state}
            onRetry={sources.reload}
            emptyText="暂无 source"
            emptyHint="调用 POST /api/knowledge/sources/from-artifact 导入文件"
          >
            {(d) => (
              <table className="tbl" data-testid="knowledge-source-tbl">
                <thead>
                  <tr>
                    <th>title</th>
                    <th>type</th>
                    <th>scope</th>
                    <th>tags</th>
                    <th>chunks</th>
                    <th>enabled</th>
                    <th>actions</th>
                  </tr>
                </thead>
                <tbody>
                  {(d.sources ?? []).map((s) => (
                    <tr key={s.source_id} data-testid={`src-${s.source_id}`}>
                      <td><InlineCode>{s.title || s.source_id}</InlineCode></td>
                      <td><Badge kind="muted">{s.source_type}</Badge></td>
                      <td><Badge kind="pri">{s.scope}</Badge></td>
                      <td className="text-xs">
                        {(s.tags ?? []).map((t) => <Badge key={t} kind="muted">{t}</Badge>)}
                      </td>
                      <td className="mono">{s.chunk_count}</td>
                      <td>
                        {s.enabled
                          ? <Badge kind="ok" withDot>on</Badge>
                          : <Badge kind="muted" withDot>off</Badge>}
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
          {search.state.kind === "loading" && <LoadingState />}
          {search.state.kind === "error" && (
            <div className="text-sm" style={{ color: "var(--danger)" }}>
              {search.state.error.message}
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
  if (data.source_count === 0) {
    return <EmptyState text="无命中" hint="尝试调整 scope 或关键词" />;
  }
  return (
    <div data-testid="knowledge-search-results">
      <div className="text-sm muted mb-2">
        source_count: {data.source_count} · backend:{" "}
        {String(data.metadata?.retrieval_backend ?? "—")} · scoring:{" "}
        {String(data.metadata?.scoring_version ?? "—")}
      </div>
      {data.source_summary.slice(0, 5).map((s, i) => (
        <div className="card" key={i} style={{ padding: 10, marginBottom: 8 }}>
          <div className="row-flex" style={{ justifyContent: "space-between" }}>
            <InlineCode>{s.title || s.source_id}</InlineCode>
            <Badge kind="pri">score {s.score.toFixed(2)}</Badge>
          </div>
          <div className="muted text-xs">
            {s.chapter} {s.section && `/ ${s.section}`}
          </div>
          <div className="text-sm mt-2">{s.snippet}</div>
        </div>
      ))}
      <details>
        <summary className="text-xs muted">raw hits</summary>
        <CodeBlock language="json">
          {JSON.stringify(data.hits?.slice(0, 5) ?? [], null, 2)}
        </CodeBlock>
      </details>
    </div>
  );
}
