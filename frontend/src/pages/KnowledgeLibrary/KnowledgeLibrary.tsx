import { useState } from "react";
import {
  useAsync,
  AsyncView,
  Badge,
  CodeBlock,
  InlineCode,
} from "../../components/common";
import { knowledgeApi, artifactsApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { useToastStore } from "../../stores/toast";
import { isApiError } from "../../types";
import type { KnowledgeSource } from "../../types";
import { IconBook, IconRefresh, IconSearch, IconSparkle } from "../../components/Icon";
import { shortId } from "../../utils/displayText";

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
    <div className="page" data-testid="page-knowledge">
      <div className="page-header">
        <div>
          <h1>
            知识库{" "}
            <span style={{ color: "var(--ink-mute)", fontWeight: 400, fontSize: 14 }}>
              · Knowledge Library
            </span>
          </h1>
          <div className="subtitle">
            source 列表 / 检索 / 重新索引 / 从 artifact 导入 · 当前 scope: {scope}
          </div>
        </div>
        <div className="row-flex">
          <div className="segmented">
            {(["workspace", "global", "session"] as const).map((s) => (
              <button
                key={s}
                type="button"
                className={scope === s ? "active" : ""}
                onClick={() => setScope(s)}
              >
                {s === "workspace" ? "工作区" : s === "global" ? "全局" : "会话"}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="page-body">
        <div className="card mb-3" data-testid="knowledge-suggestions" style={{ background: "var(--bg-elev)", borderColor: "var(--accent)" }}>
          <div className="text-xs" style={{ color: "var(--ink-mute)", marginBottom: 8 }}>
            可以试试这些问题：
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {["OSPF 邻居异常排查", "配置翻译规范", "出口策略相关文档"].map((q) => (
              <span
                key={q}
                className="status-pill"
                style={{ cursor: "pointer" }}
                onClick={() => { setQuery(q); }}
              >
                <IconSearch size={10} style={{ marginRight: 4 }} />
                {q}
              </span>
            ))}
          </div>
        </div>

        <div className="card" data-testid="knowledge-import-card">
          <div className="card-title">
            <IconBook size={12} />
            从 artifact 导入
            <span className="count">{artifacts.state.kind === "success" ? (artifacts.state.data.artifacts ?? []).length : "—"}</span>
          </div>
          <div className="text-xs muted mb-3">
            选择一个制品建立可检索知识源。只索引安全摘录，机密内容不会进入搜索结果。
          </div>
          <div className="row-flex" style={{ gap: 8 }}>
            <select
              className="input"
              value={importArtifactId}
              onChange={(e) => setImportArtifactId(e.target.value)}
              data-testid="knowledge-import-select"
              disabled={artifacts.state.kind === "loading"}
              style={{ flex: 1 }}
            >
              <option value="">选择 artifact…</option>
              {(artifacts.state.kind === "success" ? artifacts.state.data.artifacts : []).map(
                (a) => (
                  <option key={a.artifact_id} value={a.artifact_id}>
                    {a.title || a.artifact_id} · {shortId(a.artifact_id)}
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
              <IconSparkle size={12} /> {importing ? "导入中…" : "导入"}
            </button>
          </div>
          {artifacts.state.kind === "empty" && (
            <div className="text-xs muted mt-2">
              当前工作区无 artifact。请先到「制品中心」页创建/上传。
            </div>
          )}
        </div>

        <div className="card">
          <div className="card-title">
            <IconBook size={12} />
            知识源列表
            <span className="count">
              {sources.state.kind === "success"
                ? (sources.state.data.sources ?? []).length
                : sources.state.kind === "loading"
                  ? "—"
                  : "0"}
            </span>
            <button
              className="card-actions btn ghost sm"
              onClick={sources.reload}
              type="button"
              aria-label="刷新"
            >
              <IconRefresh size={11} />
            </button>
          </div>
          <AsyncView
            state={sources.state}
            onRetry={sources.reload}
            emptyText="暂无知识源"
            emptyHint="点击「导入」从 artifact 创建"
          >
            {(d) => (
              <table className="tbl" data-testid="knowledge-source-tbl">
                <thead>
                  <tr>
                    <th>标题</th>
                    <th>类型</th>
                    <th>来源 artifact</th>
                    <th>标签</th>
                    <th style={{ width: 70, textAlign: "right" }}>chunks</th>
                    <th>状态</th>
                    <th style={{ width: 80 }}>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {(d.sources ?? []).map((s) => (
                    <tr key={s.source_id} data-testid={`src-${s.source_id}`}>
                      <td><InlineCode>{s.title || s.source_id}</InlineCode></td>
                      <td>
                        <Badge kind="muted">{s.source_type || "—"}</Badge>
                      </td>
                      <td className="text-xs">
                        {s.artifact_id ? <InlineCode>{s.artifact_id}</InlineCode> : <span className="muted">—</span>}
                      </td>
                      <td>
                        <div className="row-flex" style={{ flexWrap: "wrap", gap: 2 }}>
                          {(s.tags ?? []).length === 0 ? (
                            <span className="muted text-xs">—</span>
                          ) : (
                            (s.tags ?? []).map((t) => <span className="tag" key={t}>{t}</span>)
                          )}
                        </div>
                      </td>
                      <td className="mono" style={{ textAlign: "right" }}>{s.chunk_count}</td>
                      <td>
                        {s.status ? (
                          <Badge kind="info">{s.status}</Badge>
                        ) : (
                          <Badge kind="muted">—</Badge>
                        )}
                      </td>
                      <td>
                        <button
                          className="btn sm"
                          onClick={() => void onReindex(s.source_id)}
                          data-testid={`btn-reindex-${s.source_id}`}
                          type="button"
                        >
                          <IconRefresh size={11} /> reindex
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
          <div className="card-title">
            <IconSearch size={12} />
            检索
          </div>
          <div className="row-flex mb-3" style={{ gap: 8 }}>
            <input
              className="input"
              placeholder="输入关键词（CJK / 英文）"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") search.reload();
              }}
              data-testid="knowledge-search-input"
            />
            <button
              className="btn primary"
              onClick={search.reload}
              disabled={!query.trim()}
              data-testid="btn-knowledge-search"
              type="button"
            >
              <IconSearch size={12} /> 检索
            </button>
          </div>

          {search.state.kind === "loading" && (
            <div className="text-sm muted row-flex" style={{ gap: 8 }}>
              <span className="spinner" /> 搜索中…
            </div>
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
    return (
      <div className="empty">
        <div className="empty-icon"><span style={{ fontSize: 18, color: "var(--ink-faint)" }}>○</span></div>
        <div className="empty-text">无命中</div>
        <div className="empty-hint">尝试调整 scope 或关键词</div>
      </div>
    );
  }
  return (
    <div data-testid="knowledge-search-results">
      <div className="text-sm muted mb-2 row-flex" style={{ gap: 8 }}>
        <span>命中 {results.length} 个</span>
        {data.note && <span>· {data.note}</span>}
      </div>
      {results.slice(0, 10).map((r, i) => (
        <div
          className="card"
          key={r.chunk_id}
          style={{ padding: 12, marginBottom: 8, boxShadow: "none" }}
          data-testid={`search-result-${i}`}
        >
          <div className="row-flex" style={{ justifyContent: "space-between" }}>
            <InlineCode>{r.title || r.source_id}</InlineCode>
            <Badge kind="accent">score {r.score.toFixed(2)}</Badge>
          </div>
          <div className="text-sm mt-2" style={{ color: "var(--ink-soft)" }}>
            {r.safe_excerpt || r.summary || <span className="muted">(无摘录)</span>}
          </div>
          {r.artifact_id && (
            <div className="text-xs muted mt-2">
              artifact: <InlineCode>{r.artifact_id}</InlineCode>
            </div>
          )}
        </div>
      ))}
      <details className="collapse">
        <summary>开发诊断 JSON</summary>
        <CodeBlock language="json">
          {JSON.stringify(results.slice(0, 5), null, 2)}
        </CodeBlock>
      </details>
    </div>
  );
}
