import { useState } from "react";
import { runtimeAuditApi } from "../../api";
import {
  useAsync,
  AsyncView,
  Badge,
  CodeBlock,
  InlineCode,
} from "../../components/common";
import { useSessionStore } from "../../stores/session";
import type { RuntimeAuditTurn } from "../../types";
import { IconAlert, IconClock } from "../../components/Icon";

const STATUS_LABEL: Record<string, string> = {
  ok: "成功",
  failed: "失败",
  running: "运行中",
  timeout: "超时",
  cancelled: "取消",
};

export function RuntimeAudit() {
  const { currentWorkspaceId } = useSessionStore();
  const [selectedTurnId, setSelectedTurnId] = useState<string | null>(null);

  const turns = useAsync<{ runs: RuntimeAuditTurn[] }>(
    (s) =>
      currentWorkspaceId
        ? runtimeAuditApi.recent(currentWorkspaceId, s)
        : Promise.resolve({ runs: [] }),
    [currentWorkspaceId],
    (d) => (d.runs ?? []).length === 0,
  );

  const trace = useAsync<{ events: RuntimeAuditTurn["events"] }>(
    (s) =>
      currentWorkspaceId && selectedTurnId
        ? runtimeAuditApi.trace(currentWorkspaceId, selectedTurnId, s)
        : Promise.resolve({ events: [] }),
    [currentWorkspaceId, selectedTurnId],
  );

  return (
    <div className="page" data-testid="page-audit">
      <div className="page-header">
        <div>
          <h1>
            运行审计{" "}
            <span style={{ color: "var(--ink-mute)", fontWeight: 400, fontSize: 14 }}>
              · Runtime Audit
            </span>
          </h1>
          <div className="subtitle">
            turn 时间线 · 模型 I/O · 工具调用 · provider 错误
          </div>
        </div>
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "320px 1fr",
          flex: 1,
          minHeight: 0,
        }}
      >
        <aside
          style={{
            borderRight: "1px solid var(--line)",
            overflowY: "auto",
            background: "var(--bg-elev)",
          }}
        >
          <div style={{ padding: 12 }}>
            <div className="section-head" style={{ paddingLeft: 4, marginBottom: 8 }}>
              <IconClock size={11} /> 最近 turn
            </div>
            <AsyncView
              state={turns.state}
              onRetry={turns.reload}
              emptyText="无 turn 记录"
              emptyHint="等待 agent run 出现"
            >
              {(d) => (
                <div className="list" data-testid="audit-turn-list">
                  {(d.runs ?? []).map((t, i) => (
                    <button
                      key={`${t.turn_id || "turn"}-${t.trace_id || i}`}
                      type="button"
                      className={
                        "list-item" +
                        (selectedTurnId === t.turn_id ? " active" : "")
                      }
                      onClick={() => setSelectedTurnId(t.turn_id)}
                      data-testid={`turn-${t.turn_id}`}
                    >
                      <span
                        className={
                          "status-dot " +
                          (t.status === "ok"
                            ? "ok"
                            : t.status === "failed"
                              ? "err"
                              : "warn")
                        }
                      />
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
                        {STATUS_LABEL[t.status] || t.status}
                      </Badge>
                    </button>
                  ))}
                </div>
              )}
            </AsyncView>
          </div>
        </aside>
        <section
          style={{ overflowY: "auto", padding: 20, minHeight: 0 }}
          data-testid="audit-detail"
        >
          {!selectedTurnId ? (
            <div className="hero" style={{ minHeight: "auto", padding: 60 }}>
              <div className="hero-mark">审</div>
              <h1 className="hero-title">未选择 turn</h1>
              <p className="hero-sub">在左侧选择一个 turn，查看 trace 事件流</p>
            </div>
          ) : (
            <>
              {trace.state.kind === "loading" && (
                <div className="row-flex" style={{ gap: 8 }}>
                  <span className="spinner" /> 加载 trace…
                </div>
              )}
              {trace.state.kind === "error" && (
                <div
                  className="text-sm row-flex"
                  style={{ color: "var(--danger)", gap: 6 }}
                >
                  <IconAlert size={11} /> {trace.state.error.message}
                </div>
              )}
              {trace.state.kind === "success" && (
                <>
                  <div className="row-flex mb-3">
                    <InlineCode>{selectedTurnId}</InlineCode>
                    <span className="muted text-sm">
                      {trace.state.data.events.length} 个事件
                    </span>
                  </div>
                  {trace.state.data.events.length === 0 ? (
                    <div className="empty">
                      <div className="empty-icon">○</div>
                      <div className="empty-text">该 turn 无 event</div>
                    </div>
                  ) : (
                    <div data-testid="audit-events">
                      {trace.state.data.events.map((ev) => (
                        <div
                          key={ev.event_id}
                          className="card"
                          style={{ padding: 12, marginBottom: 8 }}
                        >
                          <div className="row-flex" style={{ justifyContent: "space-between" }}>
                            <span className="row-flex" style={{ minWidth: 0 }}>
                              <Badge kind="info">{ev.event_type}</Badge>
                            </span>
                            <span className="muted text-xs mono">{ev.occurred_at}</span>
                          </div>
                          <details className="collapse mt-2">
                            <summary>查看 payload</summary>
                            <CodeBlock language="json">
                              {JSON.stringify(ev.payload ?? {}, null, 2)}
                            </CodeBlock>
                          </details>
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
