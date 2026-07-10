import { useEffect, useState, useCallback, useMemo } from "react";
import { memoryApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { Badge, StatusDot } from "../../components/common";
import { IconSearch, IconPlus, IconRefresh, IconClose, IconCheck, IconTrash } from "../../components/Icon";

interface MemEntry {
  memory_id?: string;
  title?: string;
  summary?: string;
  content?: string;
  value_preview?: string;
  status?: string;
  scope?: string;
  memory_type?: string;
  tags?: string[];
}

export function MemoryPage() {
  const currentWorkspaceId = useSessionStore((s) => s.currentWorkspaceId);
  const wsId = currentWorkspaceId;
  const [entries, setEntries] = useState<MemEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQ, setSearchQ] = useState("");
  const [searchRes, setSearchRes] = useState<MemEntry[] | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [sel, setSel] = useState<MemEntry | null>(null);
  const [err, setErr] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [toast, setToast] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const d = await memoryApi.list({ workspace_id: wsId, limit: 500 });
      if (d.ok) setEntries((d.records || []) as MemEntry[]);
    } catch (e: any) {
      setErr(e?.message || "加载失败");
    }
    setLoading(false);
  }, [wsId]);

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
    setErr("");
    try {
      const result = await memoryApi.create({
        title,
        content,
        workspace_id: wsId,
        memory_type: "knowledge_note",
        user_confirmed: true,
      });
      if (!result.ok) throw new Error("记忆门控拒绝了该内容");
      setTitle("");
      setContent("");
      setShowCreate(false);
      load();
    } catch (e: any) {
      setErr(e?.message || "创建记忆失败");
    }
  };

  const handleDeleteHard = async (memoryId: string) => {
    try {
      await memoryApi.deleteHard(memoryId, wsId);
      load();
      showToast("ok", "已永久删除");
    } catch (e: any) {
      showToast("err", "删除失败");
    }
    setDeleteConfirm(null);
  };

  const handleReview = async (memoryId: string, decision: "confirm" | "reject") => {
    try {
      const result = decision === "confirm"
        ? await memoryApi.confirm({ memory_id: memoryId, workspace_id: wsId })
        : await memoryApi.reject({ memory_id: memoryId, workspace_id: wsId });
      if (!result.ok) throw new Error("review_failed");
      showToast("ok", decision === "confirm" ? "记忆已确认并开始生效" : "记忆已拒绝");
      await load();
    } catch {
      showToast("err", decision === "confirm" ? "确认失败" : "拒绝失败");
    }
  };

  const handleBatchDelete = async () => {
    if (checked.size === 0) return;
    const ids = Array.from(checked);
    if (!confirm(`永久删除选中的 ${ids.length} 条记忆？此操作不可逆。`)) return;
    try {
      const res = await memoryApi.batchHardDelete(wsId, ids);
      showToast("ok", `已删除 ${res.deleted_count} 条`);
      setChecked(new Set());
      load();
    } catch {
      showToast("err", "批量删除失败");
    }
  };

  const showToast = (kind: "ok" | "err", msg: string) => {
    setToast({ kind, msg });
    setTimeout(() => setToast(null), 2000);
  };

  const allVisibleIds = useMemo(() => display.map(e => e.memory_id ?? "__").filter(Boolean), [display]);
  const allSelected = checked.size > 0 && allVisibleIds.every(id => checked.has(id));

  const toggleSelectAll = () => {
    if (allSelected) {
      setChecked(new Set());
    } else {
      setChecked(new Set(allVisibleIds));
    }
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
            <button className="btn primary" onClick={() => setShowCreate(true)} style={{ marginTop: 16 }}>
              <IconPlus size={14} /> 创建第一条记忆
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
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

      <div className="page-body">
        {/* Search + filter bar */}
        <div className="card" style={{ padding: "12px 16px", marginBottom: 16 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <div style={{ position: "relative", flex: 1 }}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--text-4)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", pointerEvents: "none" }}>
                <circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" />
              </svg>
              <input className="input" type="text" placeholder="搜索记忆..." value={searchQ}
                onChange={(e) => setSearchQ(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }}
                style={{ paddingLeft: 34, paddingRight: searchQ ? 32 : 11 }} />
              {searchQ && (
                <button onClick={() => { setSearchQ(""); setSearchRes(null); }}
                  style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", color: "var(--text-4)", padding: 2, lineHeight: 0 }}>
                  <IconClose size={12} />
                </button>
              )}
            </div>
            <button className="btn sm" onClick={handleSearch}><IconSearch size={14} /> 搜索</button>
            {searchRes && (
              <button className="btn sm ghost" onClick={() => { setSearchRes(null); setSearchQ(""); }}>清除结果</button>
            )}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 16, marginTop: 12, paddingTop: 10, borderTop: "1px solid var(--line-2)" }}>
            {display.length > 0 && (
              <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "var(--fs-12)", color: "var(--text-3)", cursor: "pointer", userSelect: "none" }}>
                <input type="checkbox" checked={allSelected} onChange={toggleSelectAll}
                  style={{ accentColor: "var(--accent)", width: 14, height: 14, cursor: "pointer" }} />
                全选 ({checked.size})
              </label>
            )}
            {checked.size > 0 && (
              <button className="btn sm danger" onClick={handleBatchDelete} style={{ backgroundColor: "var(--danger)", color: "#fff", border: "none" }}>
                <IconTrash size={12} /> 删除 {checked.size} 条
              </button>
            )}
            <span style={{ marginLeft: "auto", fontSize: "var(--fs-11)", color: "var(--text-4)" }}>
              {searchRes ? `搜索结果 ${display.length} 条` : `共 ${display.length} 条记忆`}
            </span>
          </div>
        </div>

        {showCreate && (
          <div className="card" style={{ marginBottom: 16, borderColor: "var(--accent)", borderWidth: 1, boxShadow: "0 0 0 1px var(--accent-soft)" }}>
            <div className="card-title" style={{ marginBottom: 10 }}>新建记忆</div>
            <input className="input" type="text" placeholder="标题" value={title} onChange={(e) => setTitle(e.target.value)} style={{ marginBottom: 8 }} />
            <textarea className="input" placeholder="记忆内容..." value={content} onChange={(e) => setContent(e.target.value)} rows={3} style={{ marginBottom: 10 }} />
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn primary sm" onClick={handleCreate} disabled={!title || !content}>保存</button>
              <button className="btn sm" onClick={() => setShowCreate(false)}>取消</button>
            </div>
          </div>
        )}

        {err && (
          <div className="card" style={{ borderLeft: "3px solid var(--danger)", marginBottom: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--danger)" }}>
              <span style={{ fontWeight: 720 }}>⚠</span>
              <span style={{ fontSize: "var(--fs-13)" }}>{err}</span>
            </div>
          </div>
        )}

        {loading && (
          <div className="empty">
            <div className="empty-icon"><span className="spinner" /></div>
            <div className="empty-text">加载中…</div>
          </div>
        )}

        {!loading && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {display.map((e, i) => {
              const isSelected = sel?.memory_id === e.memory_id;
              const isChecked = checked.has(e.memory_id ?? "");
              const isInactive = e.status === "rejected" || e.status === "expired";
              const dotColor = isInactive ? "err" : e.status === "pending" || e.status === "conflict" ? "warn" : "ok";

              return (
                <div key={e.memory_id || i} className="card" style={{ padding: 0, cursor: "pointer", opacity: isInactive ? 0.55 : 1, transition: "all var(--dur-2) var(--ease)", outline: isChecked ? "2px solid var(--accent)" : "none" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "14px 16px" }}
                    onClick={() => setSel(isSelected ? null : e)}>
                    {/* Checkbox */}
                    <input type="checkbox" checked={isChecked}
                      onChange={(ev) => {
                        const next = new Set(checked);
                        if (ev.target.checked) next.add(e.memory_id ?? "");
                        else next.delete(e.memory_id ?? "");
                        setChecked(next);
                      }}
                      onClick={(ev) => ev.stopPropagation()}
                      style={{ accentColor: "var(--accent)", width: 14, height: 14, cursor: "pointer", flexShrink: 0 }} />

                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 5 }}>
                        <StatusDot status={dotColor} />
                        <strong style={{ fontSize: "var(--fs-14)", lineHeight: 1.35, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {e.title || e.summary || e.content?.slice(0, 80) || "未命名记忆"}
                        </strong>
                        {e.status && e.status !== "active" && (
                          <Badge kind={isInactive ? "err" : "warn"}>{e.status}</Badge>
                        )}
                        {e.memory_type && <Badge kind="info">{e.memory_type}</Badge>}
                        {e.scope && <Badge kind="muted">{e.scope}</Badge>}
                      </div>
                      <div style={{ fontSize: "var(--fs-12)", color: "var(--text-3)", lineHeight: 1.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {e.value_preview || e.content?.substring(0, 150) || "(无内容)"}
                      </div>
                    </div>

                    <button className="btn sm ghost" title="永久删除"
                      onClick={(ev) => { ev.stopPropagation(); setDeleteConfirm(e.memory_id || null); }}
                      style={{ flexShrink: 0, padding: "2px 6px", color: "var(--text-4)" }}>
                      <IconTrash size={13} />
                    </button>
                    <span style={{ flexShrink: 0, color: "var(--text-4)", fontSize: "var(--fs-11)", paddingTop: 2 }}>
                      {isSelected ? "▾" : "▸"}
                    </span>
                  </div>

                  {deleteConfirm === e.memory_id && (
                    <div style={{ padding: "6px 16px 8px", borderTop: "1px solid var(--line-2)", background: "var(--danger-soft, #fde8e8)", display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontSize: "var(--fs-12)", color: "var(--danger)", flex: 1 }}>
                        永久删除这条记忆？此操作不可逆。
                      </span>
                      <button className="btn sm danger" onClick={() => handleDeleteHard(e.memory_id!)} style={{ background: "var(--danger)", color: "#fff", border: "none" }}>
                        <IconCheck size={11} /> 确认
                      </button>
                      <button className="btn sm ghost" onClick={(ev) => { ev.stopPropagation(); setDeleteConfirm(null); }}>
                        <IconClose size={11} /> 取消
                      </button>
                    </div>
                  )}

                  {isSelected && (
                    <div style={{ padding: "0 16px 14px", borderTop: "1px solid var(--line-2)" }}>
                      {e.content && (
                        <pre style={{ fontSize: "var(--fs-12)", lineHeight: 1.6, color: "var(--text-2)", background: "var(--surface-2)", padding: "12px 14px", borderRadius: "var(--r-6)", maxHeight: 260, overflow: "auto", marginTop: 10, whiteSpace: "pre-wrap", wordBreak: "break-word", border: "1px solid var(--line-2)", fontFamily: "var(--font-mono)" }}>
                          {e.content}
                        </pre>
                      )}
                      {e.tags && e.tags.length > 0 && (
                        <div style={{ display: "flex", gap: 4, marginTop: 10, flexWrap: "wrap" }}>
                          {e.tags.map((t: string) => <Badge key={t} kind="accent">{t}</Badge>)}
                        </div>
                      )}
                      {(e.status === "pending" || e.status === "conflict") && e.memory_id && (
                        <div style={{ display: "flex", gap: 8, marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--line-2)" }}>
                          <button className="btn primary sm" onClick={() => void handleReview(e.memory_id!, "confirm")}>
                            <IconCheck size={12} /> 确认并启用
                          </button>
                          <button className="btn sm" onClick={() => void handleReview(e.memory_id!, "reject")}>
                            <IconClose size={12} /> 拒绝
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Toast notification */}
      {toast && (
        <div style={{ position: "fixed", bottom: 24, right: 24, padding: "10px 16px", borderRadius: "var(--r-6)", color: "#fff", fontSize: "var(--fs-13)", zIndex: 9999, boxShadow: "0 4px 12px rgba(0,0,0,0.3)", background: toast.kind === "ok" ? "var(--ok)" : "var(--danger)" }}>
          {toast.msg}
        </div>
      )}
    </div>
  );
}
