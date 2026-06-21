/**
 * MemoryPage — 记忆管理页面 (v3.2.0 美化)
 *
 * 使用设计系统的 .page / .card / .btn / .input 类，
 * 替代原始 inline styles，提供统一的视觉体验。
 */
import { useEffect, useState, useCallback } from "react";
import { memoryApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { Badge, StatusDot } from "../../components/common";
import { IconSearch, IconPlus, IconRefresh, IconClose, IconCheck, IconTrash } from "../../components/Icon";

interface MemEntry {
  memory_id?: string;
  title: string;
  content?: string;
  value_preview?: string;
  status?: string;
  scope?: string;
  memory_type?: string;
  tags?: string[];
}

export function MemoryPage() {
  const store = useSessionStore();
  const wsId = store.currentWorkspaceId || "default";
  const [entries, setEntries] = useState<MemEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQ, setSearchQ] = useState("");
  const [searchRes, setSearchRes] = useState<MemEntry[] | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showDel, setShowDel] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [sel, setSel] = useState<MemEntry | null>(null);
  const [err, setErr] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const d = await memoryApi.list({ workspace_id: wsId, include_deleted: showDel, limit: 50 });
      if (d.ok) setEntries((d.records || []) as MemEntry[]);
    } catch (e: any) {
      setErr(e?.message || "加载失败");
    }
    setLoading(false);
  }, [wsId, showDel]);

  useEffect(() => { load(); }, [load]);

  const display = searchRes ?? entries;

  const handleSearch = () => {
    if (!searchQ.trim()) {
      setSearchRes(null);
      return;
    }
    memoryApi.search({ query: searchQ, workspace_id: wsId }).then((d) => setSearchRes((d.results || []) as MemEntry[]));
  };

  const handleCreate = async () => {
    if (!title || !content) return;
    await memoryApi.create({ title, content, workspace_id: wsId });
    setTitle("");
    setContent("");
    setShowCreate(false);
    load();
  };

  const handleDelete = async (e: MemEntry) => {
    if (!e.memory_id) return;
    try {
      await memoryApi.deleteSoft(e.memory_id, wsId);
      load();
    } catch (err: any) {
      setErr(err?.message || "删除失败");
    }
    setDeleteConfirm(null);
  };

  // ── Empty state ──
  if (!loading && !err && display.length === 0) {
    return (
      <div className="page">
        <div className="page-header" style={{ background: "var(--surface)" }}>
          <div>
            <h1>记忆管理</h1>
            <p className="subtitle">管理 Agent 的长期记忆和知识笔记</p>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn sm" onClick={() => setShowCreate(!showCreate)}>
              <IconPlus size={14} /> 新建记忆
            </button>
          </div>
        </div>
        <div className="page-body">
          {/* Create panel — shown inline in empty state */}
          {showCreate && (
            <div className="card" style={{ marginBottom: 16, borderColor: "var(--accent)", boxShadow: "0 0 0 1px var(--accent-soft)" }}>
              <div className="card-title" style={{ marginBottom: 10 }}>新建记忆</div>
              <input className="input" type="text" placeholder="标题" value={title} onChange={(e) => setTitle(e.target.value)} style={{ marginBottom: 8 }} />
              <textarea className="input" placeholder="记忆内容..." value={content} onChange={(e) => setContent(e.target.value)} rows={3} style={{ marginBottom: 10 }} />
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn primary sm" onClick={handleCreate} disabled={!title || !content}>保存</button>
                <button className="btn sm" onClick={() => { setShowCreate(false); setTitle(""); setContent(""); }}>取消</button>
              </div>
            </div>
          )}

          <div className="hero">
            <div className="hero-mark" style={{ fontSize: 22, fontWeight: 700, letterSpacing: -0.5 }}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2L2 7l10 5 10-5-10-5z" />
                <path d="M2 17l10 5 10-5" />
                <path d="M2 12l10 5 10-5" />
              </svg>
            </div>
            <h2 className="hero-title">暂无记忆数据</h2>
            <p className="hero-sub">Agent 在处理任务时会自动记录重要的决策、偏好和知识。你也可以手动创建新的记忆条目。</p>
            <button className="btn primary mt-2" onClick={() => setShowCreate(true)} style={{ marginTop: 16 }}>
              <IconPlus size={14} /> 创建第一条记忆
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── Main content ──
  return (
    <div className="page">
      {/* Header */}
      <div className="page-header" style={{ background: "var(--surface)" }}>
        <div>
          <h1>记忆管理</h1>
          <p className="subtitle">管理 Agent 的长期记忆和知识笔记</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn sm" onClick={() => setShowCreate(!showCreate)}>
            <IconPlus size={14} /> 新建
          </button>
          <button className="btn sm ghost" onClick={load} title="刷新">
            <IconRefresh size={14} />
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="page-body">
        {/* Search bar */}
        <div className="card" style={{ padding: "12px 16px", marginBottom: 16 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <div style={{ position: "relative", flex: 1 }}>
              <svg
                width="15"
                height="15"
                viewBox="0 0 24 24"
                fill="none"
                stroke="var(--text-4)"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", pointerEvents: "none" }}
              >
                <circle cx="11" cy="11" r="8" />
                <path d="m21 21-4.3-4.3" />
              </svg>
              <input
                className="input"
                type="text"
                placeholder="搜索记忆..."
                value={searchQ}
                onChange={(e) => setSearchQ(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }}
                style={{ paddingLeft: 34, paddingRight: searchQ ? 32 : 11 }}
              />
              {searchQ && (
                <button
                  onClick={() => { setSearchQ(""); setSearchRes(null); }}
                  style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", color: "var(--text-4)", padding: 2, lineHeight: 0 }}
                  title="清除"
                >
                  <IconClose size={12} />
                </button>
              )}
            </div>
            <button className="btn sm" onClick={handleSearch}>
              <IconSearch size={14} /> 搜索
            </button>
            {searchRes && (
              <button className="btn sm ghost" onClick={() => { setSearchRes(null); setSearchQ(""); }}>
                清除结果
              </button>
            )}
          </div>

          {/* Filter row */}
          <div style={{ display: "flex", alignItems: "center", gap: 16, marginTop: 12, paddingTop: 10, borderTop: "1px solid var(--line-2)" }}>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "var(--fs-12)", color: "var(--text-3)", cursor: "pointer", userSelect: "none" }}>
              <input
                type="checkbox"
                checked={showDel}
                onChange={(e) => setShowDel(e.target.checked)}
                style={{ accentColor: "var(--accent)", width: 14, height: 14, cursor: "pointer" }}
              />
              包含已删除
            </label>
            <span style={{ marginLeft: "auto", fontSize: "var(--fs-11)", color: "var(--text-4)" }}>
              {searchRes ? `搜索结果 ${display.length} 条` : `共 ${display.length} 条记忆`}
            </span>
          </div>
        </div>

        {/* Create panel */}
        {showCreate && (
          <div className="card" style={{ marginBottom: 16, borderColor: "var(--accent)", borderWidth: 1, boxShadow: "0 0 0 1px var(--accent-soft)" }}>
            <div className="card-title" style={{ marginBottom: 10 }}>新建记忆</div>
            <input
              className="input"
              type="text"
              placeholder="标题"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              style={{ marginBottom: 8 }}
            />
            <textarea
              className="input"
              placeholder="记忆内容..."
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={3}
              style={{ marginBottom: 10 }}
            />
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn primary sm" onClick={handleCreate} disabled={!title || !content}>保存</button>
              <button className="btn sm" onClick={() => setShowCreate(false)}>取消</button>
            </div>
          </div>
        )}

        {/* Error state */}
        {err && (
          <div className="card" style={{ borderLeft: "3px solid var(--danger)", marginBottom: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--danger)" }}>
              <span style={{ fontWeight: 720 }}>⚠</span>
              <span style={{ fontSize: "var(--fs-13)" }}>{err}</span>
            </div>
          </div>
        )}

        {/* Loading state */}
        {loading && (
          <div className="empty">
            <div className="empty-icon"><span className="spinner" /></div>
            <div className="empty-text">加载中…</div>
          </div>
        )}

        {/* Memory list */}
        {!loading && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {display.map((e, i) => {
              const isSelected = sel?.memory_id === e.memory_id;
              const isDeleted = e.status === "deleted";
              const isPending = e.status === "pending_confirmation";
              const dotColor = isDeleted ? "err" : e.status === "confirmed" ? "ok" : "warn";

              return (
                <div key={e.memory_id || i} className="card" style={{ padding: 0, cursor: "pointer", opacity: isDeleted ? 0.55 : 1, transition: "all var(--dur-2) var(--ease)" }}>
                  {/* Card header */}
                  <div
                    style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "14px 16px" }}
                    onClick={() => setSel(isSelected ? null : e)}
                  >
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 5 }}>
                        <StatusDot status={dotColor} />
                        <strong style={{ fontSize: "var(--fs-14)", lineHeight: 1.35, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {e.title || "(无标题)"}
                        </strong>
                        {e.status && e.status !== "confirmed" && (
                          <Badge kind={isDeleted ? "err" : isPending ? "warn" : "muted"}>
                            {isDeleted ? "已删除" : isPending ? "待确认" : e.status}
                          </Badge>
                        )}
                        {e.memory_type && (
                          <Badge kind="info">{e.memory_type}</Badge>
                        )}
                        {e.scope && (
                          <Badge kind="muted">{e.scope}</Badge>
                        )}
                      </div>
                      <div style={{ fontSize: "var(--fs-12)", color: "var(--text-3)", lineHeight: 1.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {e.value_preview || e.content?.substring(0, 150) || "(无内容)"}
                      </div>
                    </div>
                    {/* Delete button — always visible on header */}
                    <button
                      className="btn sm ghost"
                      title={isDeleted ? "永久删除" : "删除"}
                      onClick={(ev) => { ev.stopPropagation(); setDeleteConfirm(e.memory_id || null); }}
                      style={{ flexShrink: 0, padding: "2px 6px", color: "var(--text-4)" }}
                    >
                      <IconTrash size={13} />
                    </button>
                    <span style={{ flexShrink: 0, color: "var(--text-4)", fontSize: "var(--fs-11)", paddingTop: 2 }}>
                      {isSelected ? "▾" : "▸"}
                    </span>
                  </div>

                  {/* Delete confirmation bar */}
                  {deleteConfirm === e.memory_id && (
                    <div style={{
                      padding: "6px 16px 8px", borderTop: "1px solid var(--line-2)",
                      background: "var(--danger-soft, #fde8e8)", display: "flex", alignItems: "center", gap: 8,
                    }}>
                      <span style={{ fontSize: "var(--fs-12)", color: "var(--danger)", flex: 1 }}>
                        {isDeleted ? "永久删除这条记忆？此操作不可逆。" : "确定删除这条记忆？"}
                      </span>
                      <button className="btn sm danger" onClick={() => handleDelete(e)} style={{ background: "var(--danger)", color: "#fff", border: "none" }}>
                        <IconCheck size={11} /> 确认
                      </button>
                      <button className="btn sm ghost" onClick={(ev) => { ev.stopPropagation(); setDeleteConfirm(null); }}>
                        <IconClose size={11} /> 取消
                      </button>
                    </div>
                  )}

                  {/* Expanded detail */}
                  {isSelected && (
                    <div style={{ padding: "0 16px 14px", borderTop: "1px solid var(--line-2)" }}>
                      {e.content && (
                        <pre style={{
                          fontSize: "var(--fs-12)", lineHeight: 1.6, color: "var(--text-2)",
                          background: "var(--surface-2)", padding: "12px 14px", borderRadius: "var(--r-6)",
                          maxHeight: 260, overflow: "auto", marginTop: 10, whiteSpace: "pre-wrap", wordBreak: "break-word",
                          border: "1px solid var(--line-2)", fontFamily: "var(--font-mono)",
                        }}>
                          {e.content}
                        </pre>
                      )}
                      {e.tags && e.tags.length > 0 && (
                        <div style={{ display: "flex", gap: 4, marginTop: 10, flexWrap: "wrap" }}>
                          {e.tags.map((t: string) => <Badge key={t} kind="accent">{t}</Badge>)}
                        </div>
                      )}
                      <div style={{ display: "flex", gap: 6, marginTop: 12 }}>
                        {isPending && (
                          <button
                            className="btn primary sm"
                            onClick={() => memoryApi.confirm({ title: e.title, content: e.content || "", memory_type: e.memory_type || "knowledge_note", tags: e.tags || [] }).then(() => load())}
                          >
                            确认记忆
                          </button>
                        )}
                        {e.memory_id && (
                          <button
                            className="btn sm danger-ghost"
                            onClick={() => memoryApi.deleteSoft(e.memory_id!, wsId).then(() => load())}
                          >
                            {isDeleted ? "永久删除" : "删除"}
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
