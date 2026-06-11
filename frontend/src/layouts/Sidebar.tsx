import { useEffect } from "react";
import { useAsync, AsyncView } from "../components/common";
import { sessionsApi, workspacesApi } from "../api";
import { useSessionStore } from "../stores/session";
import { useToastStore } from "../stores/toast";
import { isApiError } from "../types";
import type { Session, Workspace } from "../types";
import { IconArchive, IconBolt, IconChat, IconPlus, IconWorkspace } from "../components/Icon";

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
    <div data-testid="sidebar" className="col-flex" style={{ gap: 16 }}>
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
                  {w.is_default && <span className="meta">默认</span>}
                </button>
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
              {(d.sessions ?? []).map((sess) => (
                <div
                  key={sess.session_id}
                  className={
                    "list-item" +
                    (currentSessionId === sess.session_id ? " active" : "")
                  }
                  data-testid={`sess-${sess.session_id}`}
                  style={{ paddingRight: 4 }}
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
                      background: "none",
                      border: "none",
                      color: "inherit",
                      fontFamily: "inherit",
                      cursor: "pointer",
                      minWidth: 0,
                    }}
                  >
                    <span className="title" style={{ minWidth: 0 }}>
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
                    style={{ padding: "0 4px", height: 22 }}
                    data-testid={`btn-archive-${sess.session_id}`}
                    type="button"
                    aria-label="归档"
                    title="归档"
                  >
                    <IconArchive size={12} />
                  </button>
                </div>
              ))}
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
                return (
                  <div className="list-item" key={runId} style={{ cursor: "default" }}>
                    <span
                      className={
                        "status-dot " +
                        (r.status === "ok"
                          ? "ok"
                          : r.status === "failed"
                            ? "err"
                            : "idle")
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
