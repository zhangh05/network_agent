import { useEffect, useRef, useState } from "react";
import { useAsync, AsyncView } from "../components/common";
import { sessionsApi, workspacesApi } from "../api";
import { useSessionStore } from "../stores/session";
import { useToastStore } from "../stores/toast";
import { isApiError } from "../types";
import type { Session } from "../types";
import { IconArchive, IconBolt, IconChat, IconEdit, IconPlus, IconTrash, IconWorkspace } from "../components/Icon";
import { APP_EVENTS } from "../utils/appEvents";

const SESSION_PREVIEW_LIMIT = 12;

interface RecentRunSummary {
  run_id?: string;
  status?: string;
  user_input_summary?: string;
  intent?: string;
  created_at?: string;
  session_id?: string;
  session_title?: string;
}

/**
 * Sidebar — Workspace / Sessions / Recent Runs. All data is fetched
 * from the real backend; no mocks, no fallback.
 */
export function Sidebar() {
  const {
    currentWorkspaceId,
    currentSessionId,
    setCurrentSession,
    setSessions,
  } = useSessionStore();
  const toast = useToastStore((s) => s.show);
  const [editingSessId, setEditingSessId] = useState<string | null>(null);
  const [editingSessName, setEditingSessName] = useState("");

  const sessList = useAsync<{ sessions: Session[] }>(
    (s) => sessionsApi.list(currentWorkspaceId, "active", s),
    [currentWorkspaceId],
    (d) => (d.sessions ?? []).length === 0,
  );
  const recentRuns = useAsync<{ runs: RecentRunSummary[] }>(
    (s) =>
      currentWorkspaceId && currentSessionId
        ? workspacesApi.recentRuns(currentWorkspaceId, currentSessionId, s)
        : Promise.resolve({ runs: [] }),
    [currentWorkspaceId, currentSessionId],
    (d) => (d.runs ?? []).length === 0,
  );

  // Re-register event listener once — use refs to avoid dependency churn
  const recentRunsRef = useRef(recentRuns.reload);
  recentRunsRef.current = recentRuns.reload;
  const sessListRef = useRef(sessList.reload);
  sessListRef.current = sessList.reload;

  useEffect(() => {
    const onRunCompleted = () => {
      recentRunsRef.current();
      sessListRef.current();
    };
    window.addEventListener(APP_EVENTS.RUN_COMPLETED, onRunCompleted);
    return () => window.removeEventListener(APP_EVENTS.RUN_COMPLETED, onRunCompleted);
  }, []);

  useEffect(() => {
    if (sessList.state.kind !== "success") return;
    const sessions = sessList.state.data.sessions ?? [];
    setSessions(sessions);
    const cur = useSessionStore.getState().currentSessionId;
    if (!cur || !sessions.some((s) => s.session_id === cur)) {
      setCurrentSession(sessions[0]?.session_id ?? null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessList.state, currentWorkspaceId]);

  async function onNewSession() {
    if (!currentWorkspaceId) {
      toast({ kind: "warning", title: "未选择 workspace" });
      return;
    }
    try {
      const res = await sessionsApi.create(currentWorkspaceId, "");
      if (res?.session) {
        setCurrentSession(res.session.session_id);
        sessList.reload();
        toast({ kind: "success", title: "新会话已创建", body: res.session.session_id });
      }
    } catch (e: unknown) {
      toast({
        kind: "error",
        title: "创建会话失败",
        body: isApiError(e) ? e.message : String(e),
        request_id: isApiError(e) ? e.request_id : undefined,
      });
    }
  }

  async function onArchive(sess: Session) {
    if (!currentWorkspaceId) return;
    try {
      await sessionsApi.archive(sess.session_id, currentWorkspaceId);
      if (currentSessionId === sess.session_id) {
        setCurrentSession(null);
      }
      sessList.reload();
      recentRuns.reload();
      toast({ kind: "success", title: "已归档", body: sess.session_id });
    } catch (e: unknown) {
      toast({
        kind: "error",
        title: "归档失败",
        body: isApiError(e) ? e.message : String(e),
        request_id: isApiError(e) ? e.request_id : undefined,
      });
    }
  }

  async function onRenameSession(sess_id: string) {
    if (!editingSessName.trim() || !currentWorkspaceId) { cancelEditSession(); return; }
    try {
      await sessionsApi.rename(sess_id, currentWorkspaceId!, editingSessName.trim());
      sessList.reload();
      toast({ kind: "success", title: "会话已重命名" });
      cancelEditSession();
    } catch (e: unknown) {
      toast({ kind: "error", title: "重命名失败", body: isApiError(e) ? e.message : String(e) });
    }
  }

  async function onDeleteSession(sess: Session) {
    if (!confirm(`⚠️ 永久删除会话「${sess.title || sess.session_id}」？\n\n此操作不可撤销！消息和记录将被彻底清除。`)) return;
    try {
      const { apiClient } = await import("../api/client");
      await apiClient.request({
        method: "DELETE",
        url: `/sessions/${sess.session_id}`,
        params: { workspace_id: currentWorkspaceId!, confirm: "true" },
      });
      if (currentSessionId === sess.session_id) setCurrentSession(null);
      sessList.reload();
      recentRuns.reload();
      toast({ kind: "success", title: "已永久删除", body: sess.session_id });
    } catch (e: unknown) {
      toast({ kind: "error", title: "删除失败", body: isApiError(e) ? e.message : String(e) });
    }
  }

  function startEditSession(sess: Session) {
    setEditingSessId(sess.session_id);
    setEditingSessName(sess.title || "");
  }

  function cancelEditSession() {
    setEditingSessId(null);
    setEditingSessName("");
  }

  return (
    <div data-testid="sidebar" className="sidebar-content">
      {/* 工作区 — 固定 default */}
      <div className="sidebar-panel">
        <div className="sidebar-panel-title">
          <IconWorkspace size={12} />
          <span>工作区</span>
        </div>
        <div className="list" data-testid="ws-list">
          <div className="list-item active" style={{ cursor: "default" }}>
            <span className="status-dot ok" />
            <span className="title">默认工作区</span>
            <span className="meta">default</span>
          </div>
        </div>
      </div>

      {/* 会话 */}
      <div className="sidebar-panel">
        <div className="sidebar-panel-title">
          <IconChat size={12} />
          <span>会话</span>
          <button
            className="panel-action"
            onClick={onNewSession}
            disabled={!currentWorkspaceId}
            data-testid="btn-new-session"
            type="button"
            aria-label="新建会话"
          >
            <IconPlus size={11} />
          </button>
        </div>
        <AsyncView
          state={sessList.state}
          onRetry={sessList.reload}
          emptyText="暂无活跃会话"
          emptyHint="点击 + 新建"
        >
          {(d) => (
            <div className="list" data-testid="sess-list">
              {previewSessions(d.sessions ?? [], currentSessionId).map((sess) => (
                <div
                  key={sess.session_id}
                  className={
                    "list-item session-item" +
                    (currentSessionId === sess.session_id ? " active" : "")
                  }
                  data-testid={`sess-${sess.session_id}`}
                >
                  <button
                    onClick={() => { cancelEditSession(); setCurrentSession(sess.session_id); }}
                    data-testid={`sess-btn-${sess.session_id}`}
                    aria-label={`会话：${sess.title || sess.session_id}`}
                    type="button"
                    className="session-item-main"
                  >
                    {editingSessId === sess.session_id ? (
                      <input
                        className="input"
                        style={{ height: 22, fontSize: 12, width: "100%" }}
                        value={editingSessName}
                        onChange={(e) => setEditingSessName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") { e.stopPropagation(); void onRenameSession(sess.session_id); }
                          if (e.key === "Escape") { e.stopPropagation(); cancelEditSession(); }
                        }}
                        onBlur={cancelEditSession}
                        onClick={(e) => e.stopPropagation()}
                        autoFocus
                      />
                    ) : (
                      <span className="title">
                        {sess.title || sess.session_id}
                      </span>
                    )}
                    {sess.message_count > 0 && (
                      <span className="meta">{sess.message_count}</span>
                    )}
                  </button>
                  {editingSessId === sess.session_id ? (
                    <div style={{ display: "flex", gap: 2, padding: "4px 2px" }}>
                      <button className="btn sm" style={{ height: 22, padding: "0 6px", fontSize: 10 }} onClick={(e) => { e.stopPropagation(); void onRenameSession(sess.session_id); }} type="button">保存</button>
                      <button className="btn sm ghost" style={{ height: 22, padding: "0 4px", fontSize: 10 }} onClick={(e) => { e.stopPropagation(); cancelEditSession(); }} type="button">×</button>
                    </div>
                  ) : (
                    <div className="row-actions">
                      <button
                        onClick={(e) => { e.stopPropagation(); startEditSession(sess); }}
                        className="btn ghost sm icon-only"
                        type="button" title="重命名"
                      >
                        <IconEdit size={12} />
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); void onDeleteSession(sess); }}
                        className="btn ghost sm icon-only"
                        type="button" title="删除"
                        style={{ color: "var(--danger)" }}
                      >
                        <IconTrash size={12} />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          void onArchive(sess);
                        }}
                        className="btn ghost sm icon-only"
                        data-testid={`btn-archive-${sess.session_id}`}
                        type="button"
                        aria-label="归档"
                        title="归档"
                      >
                        <IconArchive size={12} />
                      </button>
                    </div>
                  )}
                </div>
              ))}
              {hiddenSessionCount(d.sessions ?? [], currentSessionId) > 0 && (
                <div className="list-item muted-row">
                  <span className="meta">
                    另有 {hiddenSessionCount(d.sessions ?? [], currentSessionId)} 个活跃会话
                  </span>
                </div>
              )}
            </div>
          )}
        </AsyncView>
      </div>

      {/* 最近运行 */}
      <div className="sidebar-panel">
        <div className="sidebar-panel-title">
          <IconBolt size={12} />
          <span>最近运行</span>
        </div>
        <AsyncView
          state={recentRuns.state}
          onRetry={recentRuns.reload}
          emptyText="暂无运行记录"
        >
          {(d) => (
            <div className="list" data-testid="runs-list">
              {(d.runs ?? []).slice(0, 8).map((r, i) => {
                const runId = r.run_id ?? `run-${i}`;
                const summary = r.user_input_summary || r.intent || "";
                const label = summary ? (summary.length > 24 ? summary.slice(0, 24) + "…" : summary) : runId;
                const intentBadge = r.intent ? (
                  <span className="run-intent">
                    {r.intent}
                  </span>
                ) : null;
                return (
                  <div
                    className="list-item run-item"
                    key={runId}
                    title={`${summary || runId}\nstatus: ${r.status || "?"}\ntime: ${r.created_at || "?"}`}
                  >
                    <div className="run-title-row">
                      <span
                        className={
                          "status-dot " +
                          (r.status === "ok" ? "ok" : r.status === "failed" ? "err" : "idle")
                        }
                      />
                      <span className="title text-sm">{label}</span>
                    </div>
                    <div className="run-meta-row">
                      {r.session_title && (
                        <span className="text-xs run-session-label" title={`会话: ${r.session_title}`}>
                          {r.session_title}
                        </span>
                      )}
                      {intentBadge}
                      {r.created_at && (
                        <span className="text-xs faint">
                          {new Date(r.created_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </AsyncView>
      </div>
    </div>
  );
}

function previewSessions(sessions: Session[], currentSessionId: string | null): Session[] {
  const preview = sessions.slice(0, SESSION_PREVIEW_LIMIT);
  if (!currentSessionId || preview.some((s) => s.session_id === currentSessionId)) {
    return preview;
  }
  const selected = sessions.find((s) => s.session_id === currentSessionId);
  return selected ? [...preview, selected] : preview;
}

function hiddenSessionCount(sessions: Session[], currentSessionId: string | null): number {
  return Math.max(0, sessions.length - previewSessions(sessions, currentSessionId).length);
}
