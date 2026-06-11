import { useEffect } from "react";
import { useAsync, AsyncView } from "../components/common";
import { sessionsApi, workspacesApi } from "../api";
import { useSessionStore } from "../stores/session";
import type { Session, Workspace } from "../types";

/**
 * Sidebar — Workspace / Sessions / Recent Runs.
 *  - Workspace list: from `/api/workspaces`
 *  - Sessions: from `/api/sessions?workspace_id=X`
 *  - Recent Runs: from `/api/runs/recent?workspace_id=X`
 */
export function Sidebar() {
  const { currentWorkspaceId, currentSessionId, setCurrentWorkspace, setCurrentSession } =
    useSessionStore();

  const wsList = useAsync<{ workspaces: Workspace[] }>(
    (s) => workspacesApi.list(s),
    [],
    (d) => (d.workspaces ?? []).length === 0,
  );
  const sessList = useAsync<{ sessions: Session[] }>(
    (s) =>
      currentWorkspaceId
        ? sessionsApi.list(currentWorkspaceId, s)
        : Promise.resolve({ sessions: [] }),
    [currentWorkspaceId],
    (d) => (d.sessions ?? []).length === 0,
  );
  const recentRuns = useAsync<{ runs: unknown[] }>(
    (s) =>
      currentWorkspaceId
        ? workspacesApi.recentRuns(currentWorkspaceId, s)
        : Promise.resolve({ runs: [] }),
    [currentWorkspaceId],
    (d) => (d.runs ?? []).length === 0,
  );

  // Hydrate store from API result.
  useEffect(() => {
    if (wsList.state.kind === "success") {
      setWorkspacesIntoStore(wsList.state.data.workspaces);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsList.state.kind]);

  function setWorkspacesIntoStore(list: Workspace[]) {
    const set = useSessionStore.getState().setWorkspaces;
    set(list);
    const cur = useSessionStore.getState().currentWorkspaceId;
    if (!cur && list.length > 0) {
      setCurrentWorkspace(list[0].workspace_id);
    }
  }

  return (
    <div>
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
        <div className="card-title">Sessions</div>
        <AsyncView
          state={sessList.state}
          onRetry={sessList.reload}
          emptyText="暂无活跃 session"
          emptyHint="点击新建开始一次会话"
        >
          {(d) => (
            <div data-testid="sess-list">
              {(d.sessions ?? []).map((sess) => (
                <button
                  key={sess.session_id}
                  className={
                    "list-item" +
                    (currentSessionId === sess.session_id ? " active" : "")
                  }
                  onClick={() => setCurrentSession(sess.session_id)}
                  data-testid={`sess-${sess.session_id}`}
                  type="button"
                >
                  <span className="title">{sess.title || sess.session_id}</span>
                  <span className="meta">{sess.message_count}</span>
                </button>
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
                const runId =
                  (r as { run_id?: string }).run_id ?? `run-${i}`;
                return (
                  <div className="list-item" key={runId}>
                    <span className="status-dot idle" />
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
