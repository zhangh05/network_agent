import { useEffect, useRef, useState } from "react";
import { useAsync, AsyncView } from "../components/common";
import { sessionsApi, workspacesApi } from "../api";
import { useSessionStore } from "../stores/session";
import { useToastStore } from "../stores/toast";
import { isApiError } from "../types";
import type { Session, Workspace } from "../types";
import { IconArchive, IconBolt, IconChat, IconPlus, IconWorkspace } from "../components/Icon";
import { pickInitialWorkspaceId, shouldReplacePersistedWorkspace } from "../utils/workspace";
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
    setCurrentWorkspace,
    setCurrentSession,
    setWorkspaces,
  } = useSessionStore();
  const toast = useToastStore((s) => s.show);
  const [editingWsId, setEditingWsId] = useState<string | null>(null);
  const [editingWsName, setEditingWsName] = useState("");

  const wsList = useAsync<{ workspaces: Workspace[] }>(
    (s) => workspacesApi.list(s),
    [],
    (d) => (d.workspaces ?? []).length === 0,
  );
  const sessList = useAsync<{ sessions: Session[] }>(
    (s) =>
      currentWorkspaceId
        ? sessionsApi.list(currentWorkspaceId, "active", s)
        : Promise.resolve({ sessions: [] }),
    [currentWorkspaceId],
    (d) => (d.sessions ?? []).length === 0,
  );
  const recentRuns = useAsync<{ runs: RecentRunSummary[] }>(
    (s) =>
      currentWorkspaceId
        ? workspacesApi.recentRuns(currentWorkspaceId, s)
        : Promise.resolve({ runs: [] }),
    [currentWorkspaceId],
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
    if (wsList.state.kind === "success") {
      setWorkspacesIntoStore(wsList.state.data.workspaces);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsList.state.kind]);

  function setWorkspacesIntoStore(list: Workspace[]) {
    setWorkspaces(list);
    const cur = useSessionStore.getState().currentWorkspaceId;
    if (list.length > 0 && shouldReplacePersistedWorkspace(cur, list)) {
      setCurrentWorkspace(pickInitialWorkspaceId(list));
    }
  }

  async function onRenameWs(ws_id: string) {
    if (!editingWsName.trim()) { cancelEditWs(); return; }
    try {
      await workspacesApi.rename(ws_id, editingWsName.trim());
      wsList.reload();
      toast({ kind: "success", title: "已重命名" });
      cancelEditWs();
    } catch (e: unknown) {
      toast({ kind: "error", title: "重命名失败", body: isApiError(e) ? e.message : String(e) });
    }
  }

  async function onDeleteWs(ws_id: string, name: string) {
    if (!confirm(`确认删除工作区「${name}」？此操作不可撤销。`)) return;
    try {
      await workspacesApi.delete(ws_id);
      wsList.reload();
      toast({ kind: "success", title: "已删除", body: name });
    } catch (e: unknown) {
      toast({ kind: "error", title: "删除失败", body: isApiError(e) ? e.message : String(e) });
    }
  }

  function startEditWs(ws: Workspace) {
    setEditingWsId(ws.workspace_id);
    setEditingWsName(ws.name || ws.workspace_id);
  }

  function cancelEditWs() {
    setEditingWsId(null);
    setEditingWsName("");
  }

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

  return (
    <div data-testid="sidebar" className="sidebar-content">
      {/* 工作区 */}
      <div className="sidebar-panel">
        <div className="sidebar-panel-title">
          <IconWorkspace size={12} />
          <span>工作区</span>
        </div>
        <AsyncView
          state={wsList.state}
          onRetry={wsList.reload}
          emptyText="暂无工作区"
          emptyHint="请检查后端 8010"
        >
          {(d) => (
            <div className="list" data-testid="ws-list">
              {(d.workspaces ?? []).map((w) => (
                <div key={w.workspace_id} className="row-flex" style={{ gap: 0, alignItems: "stretch" }}>
                  <button
                    className={
                      "list-item" +
                      (currentWorkspaceId === w.workspace_id ? " active" : "")
                    }
                    onClick={() => { cancelEditWs(); setCurrentWorkspace(w.workspace_id); }}
                    data-testid={`ws-${w.workspace_id}`}
                    type="button"
                    style={{ flex: 1 }}
                  >
                    <span className="status-dot ok" />
                    {editingWsId === w.workspace_id ? (
                      <input
                        className="input"
                        style={{ height: 22, fontSize: 12, marginLeft: 4 }}
                        value={editingWsName}
                        onChange={(e) => setEditingWsName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") { e.stopPropagation(); void onRenameWs(w.workspace_id); }
                          if (e.key === "Escape") { e.stopPropagation(); cancelEditWs(); }
                        }}
                        onClick={(e) => e.stopPropagation()}
                        autoFocus
                      />
                    ) : (
                      <span className="title">{w.name || w.workspace_id}</span>
                    )}
                    {w.is_default && <span className="meta">默认</span>}
                  </button>
                  {!w.is_default && editingWsId === w.workspace_id ? (
                    <div style={{ display: "flex", gap: 2, padding: "4px 2px" }}>
                      <button className="btn sm" style={{ height: 22, padding: "0 6px", fontSize: 10 }} onClick={(e) => { e.stopPropagation(); void onRenameWs(w.workspace_id); }} type="button">保存</button>
                      <button className="btn sm ghost" style={{ height: 22, padding: "0 4px", fontSize: 10 }} onClick={(e) => { e.stopPropagation(); cancelEditWs(); }} type="button">×</button>
                    </div>
                  ) : !w.is_default ? (
                    <div style={{ display: "flex", gap: 2, padding: "4px 2px", opacity: editingWsId ? 0.3 : 1 }}>
                      <button className="btn sm ghost" style={{ height: 22, padding: "0 4px", fontSize: 10 }} onClick={(e) => { e.stopPropagation(); startEditWs(w); }} type="button" title="重命名">✎</button>
                      <button className="btn sm ghost" style={{ height: 22, padding: "0 4px", fontSize: 10, color: "var(--danger)" }} onClick={(e) => { e.stopPropagation(); void onDeleteWs(w.workspace_id, w.name || w.workspace_id); }} type="button" title="删除">×</button>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </AsyncView>
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
                    onClick={() => setCurrentSession(sess.session_id)}
                    data-testid={`sess-btn-${sess.session_id}`}
                    aria-label={`会话：${sess.title || sess.session_id}`}
                    type="button"
                    className="session-item-main"
                  >
                    <span className="title">
                      {sess.title || sess.session_id}
                    </span>
                    {sess.message_count > 0 && (
                      <span className="meta">{sess.message_count}</span>
                    )}
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      void onArchive(sess);
                    }}
                    className="btn ghost sm"
                    data-compact="true"
                    data-testid={`btn-archive-${sess.session_id}`}
                    type="button"
                    aria-label="归档"
                    title="归档"
                  >
                    <IconArchive size={12} />
                  </button>
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
