import { useEffect } from "react";
import { useAsync, AsyncView } from "../components/common";
import { sessionsApi, workspacesApi } from "../api";
import { useSessionStore } from "../stores/session";
import { useToastStore } from "../stores/toast";
import { isApiError } from "../types";
import type { Session, Workspace } from "../types";

/**
 * Sidebar — Workspace / Sessions / Recent Runs.
 * Real backend endpoints (v1.0.1):
 *   GET   /api/workspaces
 *   GET   /api/sessions?workspace_id=&status=active
 *   POST  /api/sessions  (create)
 *   POST  /api/sessions/<id>/archive
 *   PUT   /api/sessions/<id>?workspace_id= (rename)
 *   DELETE /api/sessions/<id>?workspace_id=&confirm=true
 *   GET   /api/runs/recent?workspace_id=
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
  const recentRuns = useAsync<{ runs: Array<{ run_id?: string; status?: string }> }>(
    (s) =>
      currentWorkspaceId
        ? workspacesApi.recentRuns(currentWorkspaceId, s)
        : Promise.resolve({ runs: [] }),
    [currentWorkspaceId],
    (d) => (d.runs ?? []).length === 0,
  );

  useEffect(() => {
    if (wsList.state.kind === "success") {
      setWorkspacesIntoStore(wsList.state.data.workspaces);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsList.state.kind]);

  function setWorkspacesIntoStore(list: Workspace[]) {
    setWorkspaces(list);
    const cur = useSessionStore.getState().currentWorkspaceId;
    if (!cur && list.length > 0) {
      setCurrentWorkspace(list[0].workspace_id);
    }
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
        toast({ kind: "success", title: "新 session 已创建", body: res.session.session_id });
      }
    } catch (e: unknown) {
      toast({
        kind: "error",
        title: "创建 session 失败",
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
    <div data-testid="sidebar">
      <div className="card">
        <div className="card-title">Workspaces</div>
        <AsyncView
          state={wsList.state}
          onRetry={wsList.reload}
          emptyText="暂无 workspace"
          emptyHint="后端返回 workspaces 为空"
        >
          {(d) => (
            <div data-testid="ws-list">
              {(d.workspaces ?? []).map((w) => (
                <button
                  key={w.workspace_id}
                  className={
                    "list-item" +
                    (currentWorkspaceId === w.workspace_id ? " active" : "")
                  }
                  onClick={() => setCurrentWorkspace(w.workspace_id)}
                  data-testid={`ws-${w.workspace_id}`}
                  type="button"
                >
                  <span className="status-dot ok" />
                  <span className="title">{w.name || w.workspace_id}</span>
                  {w.is_default && <span className="badge muted">default</span>}
                </button>
              ))}
            </div>
          )}
        </AsyncView>
      </div>

      <div className="card">
        <div className="row-flex" style={{ marginBottom: 4 }}>
          <div className="card-title" style={{ margin: 0 }}>Sessions</div>
          <span className="spacer" />
          <button
            className="btn ghost sm"
            onClick={onNewSession}
            disabled={!currentWorkspaceId}
            data-testid="btn-new-session"
            type="button"
            title="新 session"
          >
            +
          </button>
        </div>
        <AsyncView
          state={sessList.state}
          onRetry={sessList.reload}
          emptyText="暂无活跃 session"
          emptyHint="点击 + 新建"
        >
          {(d) => (
            <div data-testid="sess-list">
              {(d.sessions ?? []).map((sess) => (
                <div
                  key={sess.session_id}
                  className={
                    "list-item" +
                    (currentSessionId === sess.session_id ? " active" : "")
                  }
                  data-testid={`sess-${sess.session_id}`}
                >
                  <button
                    onClick={() => setCurrentSession(sess.session_id)}
                    data-testid={`sess-btn-${sess.session_id}`}
                    type="button"
                    style={{
                      flex: 1,
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      textAlign: "left",
                      padding: 0,
                    }}
                  >
                    <span className="title">{sess.title || sess.session_id}</span>
                    <span className="meta">{sess.message_count}</span>
                  </button>
                  <button
                    className="btn ghost sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      void onArchive(sess);
                    }}
                    data-testid={`btn-archive-${sess.session_id}`}
                    type="button"
                    title="归档"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}
        </AsyncView>
      </div>

      <div className="card">
        <div className="card-title">Recent Runs</div>
        <AsyncView
          state={recentRuns.state}
          onRetry={recentRuns.reload}
          emptyText="暂无运行记录"
        >
          {(d) => (
            <div data-testid="runs-list">
              {(d.runs ?? []).slice(0, 10).map((r, i) => {
                const runId = r.run_id ?? `run-${i}`;
                return (
                  <div className="list-item" key={runId}>
                    <span
                      className={
                        "status-dot " +
                        (r.status === "ok" ? "ok" : r.status === "failed" ? "err" : "idle")
                      }
                    />
                    <span className="title mono text-sm">{runId}</span>
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
