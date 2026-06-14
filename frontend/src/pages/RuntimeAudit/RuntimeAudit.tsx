import { useEffect, useState } from "react";
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
import { APP_EVENTS } from "../../utils/appEvents";

const STATUS_LABEL: Record<string, string> = {
  ok: "成功",
  failed: "失败",
  running: "运行中",
  timeout: "超时",
  cancelled: "取消",
};

function auditRunId(turn: RuntimeAuditTurn, index: number): string {
  return turn.run_id || turn.turn_id || turn.trace_id || `run-${index + 1}`;
}

function auditRunLabel(turn: RuntimeAuditTurn, index: number): string {
  const summary = turn.user_input_summary || turn.intent || "";
  if (summary) return summary.length > 34 ? `${summary.slice(0, 34)}…` : summary;
  return `运行 ${index + 1}`;
}

export function RuntimeAudit() {
  const { currentWorkspaceId } = useSessionStore();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

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
      currentWorkspaceId && selectedRunId
        ? runtimeAuditApi.trace(currentWorkspaceId, selectedRunId, s)
        : Promise.resolve({ events: [] }),
    [currentWorkspaceId, selectedRunId],
  );

  useEffect(() => {
    const onRunCompleted = () => turns.reload();
    window.addEventListener(APP_EVENTS.RUN_COMPLETED, onRunCompleted);
    return () => window.removeEventListener(APP_EVENTS.RUN_COMPLETED, onRunCompleted);
  }, [turns]);

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
        className="split-shell"
        style={{
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
                  {(d.runs ?? []).map((t, i) => {
                    const runId = auditRunId(t, i);
                    const label = auditRunLabel(t, i);

                    return (
                      <button
                        key={runId}
                        type="button"
                        className={
                          "list-item" +
                          (selectedRunId === runId ? " active" : "")
                        }
                        onClick={() => setSelectedRunId(runId)}
                        data-testid={`turn-${runId}`}
                        style={{
                          flexDirection: "column",
                          alignItems: "flex-start",
                          gap: 4,
                          height: "auto",
                          padding: "8px 10px",
                        }}
                      >
                        <span className="title text-sm" style={{ lineHeight: 1.3 }}>
                          问题摘要：{label}
                        </span>
                        <span className="row-flex" style={{ gap: 6, flexWrap: "wrap" }}>
                          <Badge
                            kind={
                              t.status === "ok"
                                ? "ok"
                                : t.status === "failed"
                                  ? "err"
                                  : "warn"
                            }
                          >
                            结果：{STATUS_LABEL[t.status] || t.status}
                          </Badge>
                          <span className="text-xs muted">时间：{auditTime(t)}</span>
                        </span>
                        <details className="collapse" style={{ width: "100%" }}>
                          <summary className="text-xs muted">技术详情</summary>
                          <div className="text-xs muted mono" style={{ marginTop: 2 }}>
                            {runId}
                          </div>
                        </details>
                      </button>
                    );
                  })}
                </div>
              )}
            </AsyncView>
          </div>
        </aside>
        <section
          className="split-detail"
          style={{ overflowY: "auto", minHeight: 0 }}
          data-testid="audit-detail"
        >
          {!selectedRunId ? (
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
                    <span className="text-sm" style={{ fontWeight: 600 }}>运行详情</span>
                    <span className="muted text-sm">
                      {trace.state.data.events.length} 个事件
                    </span>
                    <details className="collapse" style={{ marginLeft: "auto" }}>
                      <summary className="text-xs muted">技术详情</summary>
                      <InlineCode>{selectedRunId}</InlineCode>
                    </details>
                  </div>
                  {trace.state.data.events.length === 0 ? (
                    <div className="empty">
                      <div className="empty-icon">○</div>
                      <div className="empty-text">该 turn 无 event</div>
                    </div>
                  ) : (
                    <div data-testid="audit-events">
                      {(() => {
                        // Extract failure summary for failed turns
                        const failedEv = trace.state.data.events.find(
                          (ev: any) => ev.event_type === "turn_failed" || ev.type === "turn_failed",
                        );
                        const failedDetails = failedEv ? eventDetails(failedEv) : {};
                        const error = failedDetails.error || failedEv?.summary || failedDetails || "";
                        // Extract timeout duration if available
                        const timeoutSecs = (() => {
                          const modelReq = trace.state.data.events.find(
                            (ev: any) => ev.type === "model_request" || ev.event_type === "model_request",
                          );
                          const modelResp = trace.state.data.events.find(
                            (ev: any) => ev.type === "model_response" || ev.event_type === "model_response",
                          );
                          const reqTime = modelReq ? eventTime(modelReq) : "";
                          const respTime = modelResp ? eventTime(modelResp) : "";
                          if (reqTime && respTime) {
                            const t0 = new Date(reqTime).getTime();
                            const t1 = new Date(respTime).getTime();
                            if (t0 && t1) return Math.round((t1 - t0) / 1000);
                          }
                          return null;
                        })();
                        return failedEv ? (
                          <div
                            className="card mb-3"
                            style={{
                              borderColor: "var(--danger)",
                              padding: 10,
                              color: "var(--danger)",
                            }}
                            data-testid="audit-failure-summary"
                          >
                            <strong>失败原因</strong>
                            <span className="text-sm" style={{ marginLeft: 8 }}>
                              {String(error).slice(0, 200)}
                            </span>
                            {timeoutSecs != null && (
                              <span className="text-sm" style={{ marginLeft: 8 }}>
                                · 耗时 {timeoutSecs}s
                              </span>
                            )}
                          </div>
                        ) : null;
                      })()}
                      {trace.state.data.events.map((ev) => {
                        const eventType = ev.event_type || ev.type || "unknown";
                        const details = eventDetails(ev);
                        const label = _eventLabel(eventType, details, ev);
                        const isOk = eventType !== "turn_failed";
                        return (
                        <div
                          key={ev.event_id}
                          className="card"
                          style={{ padding: 12, marginBottom: 8 }}
                        >
                          <div className="row-flex" style={{ justifyContent: "space-between" }}>
                            <span className="row-flex" style={{ minWidth: 0, gap: 8 }}>
                              <span className={"status-dot " + (isOk ? "ok" : "err")} style={{ width: 8, height: 8 }} />
                              <span className="text-sm">{label}</span>
                            </span>
                            <span className="muted text-xs mono">{eventTime(ev)}</span>
                          </div>
                          <details className="collapse mt-2">
                            <summary style={{ fontSize: 11, color: "var(--ink-mute)" }}>开发诊断 · {eventType}</summary>
                            <CodeBlock language="json">
                              {JSON.stringify(details, null, 2)}
                            </CodeBlock>
                          </details>
                        </div>
                        );
                      })}
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

function auditTime(turn: RuntimeAuditTurn): string {
  const value = turn.created_at || turn.started_at || turn.finished_at;
  if (!value) return "—";
  try {
    return new Date(value).toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

function eventTime(ev: RuntimeAuditTurn["events"][number]): string {
  return ev.occurred_at || ev.timestamp || "—";
}

function eventDetails(ev: RuntimeAuditTurn["events"][number]): Record<string, unknown> {
  return ev.payload || ev.metadata || {};
}

function _eventLabel(
  type: string,
  payload: Record<string, unknown>,
  ev?: RuntimeAuditTurn["events"][number],
): string {
  const toolId = typeof payload?.canonical_tool_id === "string"
    ? payload.canonical_tool_id
    : (typeof payload?.tool_id === "string" ? payload.tool_id : "?");
  const map: Record<string, string> = {
    turn_started: "开始处理请求",
    context_built: "构建上下文",
    model_request_started: "发起模型请求",
    model_response_received: "模型返回响应",
    tool_call_started: `调用工具：${toolId}`,
    tool_call_finished: `工具完成：${toolId}`,
    tool_call_failed: `工具失败：${toolId}`,
    assistant_message: "生成回复",
    turn_finished: "处理完成",
    turn_failed: `处理失败：${String(payload?.error || payload || "").slice(0, 60)}`,
    agent_start: ev?.summary || "开始处理请求",
    agent_end: ev?.summary || "处理完成",
    node_start: `开始节点：${ev?.name || "?"}`,
    node_end: `完成节点：${ev?.name || "?"}`,
    intent_routed: ev?.summary || "完成意图路由",
    skill_call_start: `开始技能：${ev?.name || "?"}`,
    skill_call_end: `完成技能：${ev?.name || "?"}`,
    module_call_start: `开始模块：${ev?.name || "?"}`,
    module_call_end: `完成模块：${ev?.name || "?"}`,
  };
  return map[type] || ev?.summary || ev?.name || type;
}
