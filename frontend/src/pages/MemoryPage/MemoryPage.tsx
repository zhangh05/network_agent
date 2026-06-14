/**
 * MemoryPage — v2.1.1: Memory list/search/create/delete.
 */
import { useEffect, useState, useCallback } from "react";
import { memoryApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { Badge, EmptyState, LoadingState, StatusDot } from "../../components/common";
import { IconSearch, IconPlus, IconRefresh } from "../../components/Icon";

interface MemEntry { memory_id?: string; title: string; content?: string; value_preview?: string; status?: string; scope?: string; memory_type?: string; tags?: string[]; }

export function MemoryPage() {
  const store = useSessionStore();
  const wsId = store.currentWorkspaceId || "default";
  const [entries, setEntries] = useState<MemEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const [searchRes, setSearchRes] = useState<MemEntry[] | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showDel, setShowDel] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [sel, setSel] = useState<MemEntry | null>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try { const d = await memoryApi.list({ workspace_id: wsId, include_deleted: showDel, limit: 50 }); if (d.ok) setEntries((d.records || []) as MemEntry[]); }
    catch (e: any) { setErr(e?.message || "Failed"); }
    setLoading(false);
  }, [wsId, showDel]);

  useEffect(() => { load(); }, [load]);

  const display = searchRes ?? entries;

  return (
    <div className="page-memory" style={{ padding: 16 }}>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <h2>记忆管理</h2>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn-sm" onClick={() => setShowCreate(!showCreate)}><IconPlus size={14} /> 新建</button>
          <button className="btn-sm" onClick={load}><IconRefresh size={14} /></button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <input type="text" placeholder="搜索..." value={searchQ} onChange={e => setSearchQ(e.target.value)} onKeyDown={e => { if (e.key === "Enter") { memoryApi.search({ query: searchQ, workspace_id: wsId }).then(d => setSearchRes((d.results || []) as MemEntry[])); } }} />
        <button onClick={() => memoryApi.search({ query: searchQ, workspace_id: wsId }).then(d => setSearchRes((d.results || []) as MemEntry[]))}><IconSearch size={14} /></button>
        {searchRes && <button className="btn-sm" onClick={() => { setSearchRes(null); setSearchQ(""); }}>清除</button>}
      </div>

      {showCreate && (
        <div style={{ marginBottom: 12, padding: 12, border: "1px solid var(--border)", borderRadius: 8 }}>
          <input type="text" placeholder="标题" value={title} onChange={e => setTitle(e.target.value)} style={{ width: "100%", marginBottom: 8 }} />
          <textarea placeholder="内容" value={content} onChange={e => setContent(e.target.value)} rows={3} style={{ width: "100%", marginBottom: 8 }} />
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={async () => { if (title && content) { await memoryApi.create({ title, content, workspace_id: wsId }); setTitle(""); setContent(""); setShowCreate(false); load(); } }} disabled={!title || !content}>保存</button>
            <button onClick={() => setShowCreate(false)}>取消</button>
          </div>
        </div>
      )}

      <label style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 12 }}>
        <input type="checkbox" checked={showDel} onChange={e => setShowDel(e.target.checked)} /> 包含已删除
      </label>

      {err && <div style={{ color: "var(--err)", padding: 8 }}>{err}</div>}
      {loading && <LoadingState />}
      {!loading && !err && display.length === 0 && <EmptyState text={searchRes ? "无搜索结果" : "暂无记忆"} />}

      {display.map((e, i) => (
        <div key={e.memory_id || i} style={{ padding: 10, marginBottom: 6, border: sel?.memory_id === e.memory_id ? "1px solid var(--accent)" : "1px solid var(--border)", borderRadius: 6, cursor: "pointer" }}
          onClick={() => setSel(sel?.memory_id === e.memory_id ? null : e)}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <StatusDot status={e.status === "deleted" ? "err" : e.status === "confirmed" ? "ok" : "warn"} />
            <strong>{e.title}</strong>
            {e.scope && <Badge kind="muted">{e.scope}</Badge>}
          </div>
          <div style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 4 }}>{e.value_preview || e.content?.substring(0, 200) || "(无内容)"}</div>
          {sel?.memory_id === e.memory_id && (
            <div style={{ marginTop: 8 }}>
              {e.content && <pre style={{ fontSize: 12, maxHeight: 200, overflow: "auto", background: "var(--bg-secondary)", padding: 8, borderRadius: 4 }}>{e.content}</pre>}
              {e.tags && e.tags.length > 0 && <div style={{ display: "flex", gap: 4, marginTop: 6 }}>{e.tags.map((t: string) => <Badge key={t} kind="muted">{t}</Badge>)}</div>}
              <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                {e.status === "pending_confirmation" && <button onClick={() => memoryApi.confirm({ title: e.title, content: e.content || "", memory_type: e.memory_type || "knowledge_note", tags: e.tags || [] }).then(() => load())}>确认</button>}
                {e.memory_id && <button style={{ color: "var(--err)" }} onClick={() => memoryApi.deleteSoft(e.memory_id!, wsId).then(() => load())}>删除</button>}
              </div>
            </div>
          )}
        </div>
      ))}
      <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 8 }}>共 {display.length} 条</div>
    </div>
  );
}
