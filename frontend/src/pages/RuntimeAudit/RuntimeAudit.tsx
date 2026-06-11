import { useState } from "react";
import { runtimeAuditApi } from "../../api";
import { useAsync, AsyncView, Badge, CodeBlock, EmptyState, InlineCode, LoadingState } from "../../components/common";
import { useSessionStore } from "../../stores/session";
import type { RuntimeAuditTurn } from "../../types";

/**
 * Runtime Audit — turn timeline / trace.
 *  - Lists recent turns (from /api/runs/recent)
 *  - Click to see full trace (events, tool calls, model I/O)
 */
export function RuntimeAudit() {
  const { currentWorkspaceId } = useSessionStore();
  const [selectedTurnId, setSelectedTurnId] = useState<string | null>(null);

  const turns = useAsync<{ turns: RuntimeAuditTurn[] }>(
    (s) =>
      currentWorkspaceId
        ? runtimeAuditApi.recent(currentWorkspaceId, s)
        : Promise.resolve({ turns: [] }),
    [currentWorkspaceId],
    (d) => (d.turns ?? []).length === 0,
  );

  const trace = useAsync<{ events: RuntimeAuditTurn["events"] }>(
    (s) =>
      currentWorkspaceId && selectedTurnId
        ? runtimeAuditApi.trace(currentWorkspaceId, selectedTurnId, s)
        : Promise.resolve({ events: [] }),
    [currentWorkspaceId, selectedTurnId],
  );

  return (
    <div
      style={{ display: "flex", flexDirection: "column", height: "100%" }}
      data-testid="page-audit"
    >
      <div className="page-header">
        <div>
          <h1>Runtime Audit</h1>
          <div className="subtitle">turn timeline · model I/O · tool calls · provider errors</div>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", flex: 1, minHeight: 0 }}>
        <aside style={{ borderRight: "1px solid var(--border)", overflowY: "auto" }}>
          <div style={{ padding: 12 }}>
            <AsyncView
              state={turns.state}
              onRetry={turns.reload}
              emptyText="无 turn 记录"
              emptyHint="等待 agent run 出现"
            >
              {(d) => (
                <div data-testid="audit-turn-list">
                  {(d.turns ?? []).map((t) => (
                    <button
                      key={t.turn_id}
                      type="button"
                      className={
                        "list-item" + (selectedTurnId === t.turn_id ? " active" : "")
                      }
                      onClick={() => setSelectedTurnId(t.turn_id)}
                      data-testid={`turn-${t.turn_id}`}
                    >
                      <span className="title mono text-sm">{t.turn_id}</span>
                      <Badge
                        kind={
                          t.status === "ok"
                            ? "ok"
                            : t.status === "failed"
                              ? "err"
                              : "warn"
                        }
                      >
                        {t.status}
                      </Badge>
                    </button>
                  ))}
                </div>
              )}
            </AsyncView>
          </div>
        </aside>
        <section style={{ overflowY: "auto", padding: 16 }} data-testid="audit-detail">
          {!selectedTurnId ? (
            <EmptyState text="未选择 turn" hint="在左侧选择一项以查看 trace" />
          ) : (
            <>
              {trace.state.kind === "loading" && <LoadingState />}
              {trace.state.kind === "error" && (
                <div className="text-sm" style={{ color: "var(--danger)" }}>
                  {trace.state.error.message}
                </div>
              )}
              {trace.state.kind === "success" && (
                <>
                  <div className="row-flex mb-2">
                    <InlineCode>{selectedTurnId}</InlineCode>
                    <span className="muted text-sm">
                      {trace.state.data.events.length} events
                    </span>
                  </div>
                  {trace.state.data.events.length === 0 ? (
                    <EmptyState text="无 event" />
                  ) : (
                    <div data-testid="audit-events">
                      {trace.state.data.events.map((ev) => (
                        <div
                          key={ev.event_id}
                          className="card"
                          style={{ padding: 10, marginBottom: 6 }}
                        >
                          <div className="row-flex" style={{ justifyContent: "space-between" }}>
                            <span className="row-flex">
                              <Badge kind="info">{ev.event_type}</Badge>
                            </span>
                            <span className="muted text-xs mono">{ev.occurred_at}</span>
                          </div>
                          <CodeBlock language="json">
                            {JSON.stringify(ev.payload ?? {}, null, 2)}
                          </CodeBlock>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
