import { useWorkbenchStore } from "../stores/workbench";
import {
  Badge,
  Collapsible,
  EmptyState,
  InlineCode,
} from "../components/common";
import type { AgentResult, ToolCallResult } from "../types";
import { IconAlert, IconBolt, IconShield } from "../components/Icon";

/**
 * Turn Inspector — shows the latest AgentResult in detail.
 *  - identity (turn_id, trace_id, status)
 *  - selected skills / visible tools
 *  - tool calls with status + duration
 *  - artifacts / knowledge sources
 *  - warnings / errors / events
 */
export function Inspector() {
  const { latestResult } = useWorkbenchStore();

  if (!latestResult) {
    return (
      <div style={{ padding: 24 }}>
        <EmptyState
          text="尚无 turn 结果"
          hint="在中间栏发送一条消息以查看本 turn 的执行细节"
        />
      </div>
    );
  }

  return <InspectorBody result={latestResult} />;
}

function InspectorBody({ result }: { result: AgentResult }) {
  return (
    <div data-testid="inspector-body" style={{ paddingBottom: 24 }}>
      {/* 身份 */}
      <div className="inspector-section">
        <div className="inspector-section-title" style={{ cursor: "default" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <IconShield size={11} />
            身份
          </span>
        </div>
        <div className="inspector-row">
          <span className="label">turn</span>
          <span className="value" data-testid="inspector-turn-id">
            {result.turn_id || "—"}
          </span>
        </div>
        <div className="inspector-row">
          <span className="label">trace</span>
          <span className="value" data-testid="inspector-trace-id">
            {result.trace_id || "—"}
          </span>
        </div>
        <div className="inspector-row">
          <span className="label">session</span>
          <span className="value">{result.session_id || "—"}</span>
        </div>
        <div className="inspector-row">
          <span className="label">status</span>
          <span className="value">
            {result.ok ? (
              <Badge kind="ok" withDot>
                ok
              </Badge>
            ) : (
              <Badge kind="err" withDot>
                failed
              </Badge>
            )}
          </span>
        </div>
      </div>

      <Collapsible
        title="已选技能"
        count={result.metadata?.selected_skills?.length ?? 0}
        testid="inspector-skills-section"
      >
        <div className="col-flex" data-testid="inspector-skills" style={{ gap: 4 }}>
          {(result.metadata?.selected_skills ?? []).length === 0 ? (
            <span className="text-sm muted">无</span>
          ) : (
            <div className="row-flex" style={{ flexWrap: "wrap", gap: 4 }}>
              {(result.metadata?.selected_skills ?? []).map((s) => (
                <Badge key={s} kind="accent">
                  {s}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </Collapsible>

      <Collapsible
        title="可见工具"
        count={result.metadata?.visible_tools?.length ?? 0}
        testid="inspector-tools-section"
      >
        <div data-testid="inspector-visible-tools">
          {(result.metadata?.visible_tools ?? []).length === 0 ? (
            <span className="text-sm muted">无</span>
          ) : (
            <div className="row-flex" style={{ flexWrap: "wrap", gap: 4 }}>
              {(result.metadata?.visible_tools ?? []).map((t) => (
                <Badge key={t} kind="muted">
                  {t}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </Collapsible>

      <Collapsible
        title="工具调用"
        count={result.tool_calls?.length ?? 0}
        testid="inspector-toolcalls-section"
      >
        {(result.tool_calls ?? []).length === 0 ? (
          <div className="text-sm muted">无 tool call</div>
        ) : (
          <div className="col-flex" style={{ gap: 8 }}>
            <div
              className="card"
              data-testid="inspector-tool-summary"
              style={{ padding: 10, marginBottom: 0, background: "var(--bg-soft)" }}
            >
              <strong>{toolCallSummary(result.tool_calls ?? [])}</strong>
              <div className="text-xs muted mt-2">
                原始工具记录已收起，供排查时核对。
              </div>
            </div>
            <details>
              <summary className="text-sm muted" style={{ cursor: "pointer" }}>
                技术详情
              </summary>
              <div className="col-flex mt-2" data-testid="inspector-tool-calls" style={{ gap: 6 }}>
                {(result.tool_calls ?? []).map((tc) => (
                  <ToolCallCard key={tc.call_id} tc={tc} />
                ))}
              </div>
            </details>
          </div>
        )}
      </Collapsible>

      <Collapsible title="制品" count={countArtifacts(result)}>
        <ArtifactsList result={result} />
      </Collapsible>

      <Collapsible title="知识源" count={result.metadata?.source_count ?? 0}>
        {result.metadata?.source_count ? (
          <div data-testid="inspector-sources">
            <div className="inspector-row">
              <span className="label">count</span>
              <span className="value">{String(result.metadata?.source_count)}</span>
            </div>
            <div className="inspector-row">
              <span className="label">backend</span>
              <span className="value">
                {String(result.metadata?.retrieval_backend ?? "—")}
              </span>
            </div>
            <div className="inspector-row">
              <span className="label">scope</span>
              <span className="value">{String(result.metadata?.scope ?? "—")}</span>
            </div>
            <div className="col-flex mt-2" style={{ gap: 6 }}>
              {((result.metadata?.context_sources as any[]) ?? []).slice(0, 8).map((s, idx) => (
                <div className="card" key={`${s.chunk_id || s.source_id || idx}`} style={{ padding: 8, marginBottom: 0 }}>
                  <div className="row-flex" style={{ justifyContent: "space-between", gap: 8 }}>
                    <strong className="text-sm">{s.citation_id || `S${idx + 1}`} · {s.title || s.source_id}</strong>
                    <Badge kind={s.evidence_type === "memory" ? "accent" : "muted"}>
                      {s.evidence_type === "memory" ? "记忆" : "知识"}
                    </Badge>
                  </div>
                  {s.snippet && <div className="text-xs muted mt-1">{s.snippet}</div>}
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="text-sm muted">本 turn 未命中 knowledge</div>
        )}
      </Collapsible>

      <Collapsible title="警告" count={result.warnings?.length ?? 0}>
        {(result.warnings ?? []).length === 0 ? (
          <div className="text-sm muted">无</div>
        ) : (
          <ul className="col-flex" data-testid="inspector-warnings" style={{ gap: 4 }}>
            {result.warnings.map((w, i) => (
              <li key={i} className="row-flex text-sm">
                <Badge kind="warn">warn</Badge>
                <span>{w}</span>
              </li>
            ))}
          </ul>
        )}
      </Collapsible>

      <Collapsible title="错误" count={result.errors?.length ?? 0}>
        {(result.errors ?? []).length === 0 ? (
          <div className="text-sm muted">无</div>
        ) : (
          <ul className="col-flex" data-testid="inspector-errors" style={{ gap: 4 }}>
            {result.errors.map((e, i) => (
              <li key={i} className="row-flex text-sm">
                <Badge kind="err">
                  <IconAlert size={10} /> err
                </Badge>
                <span>{e}</span>
              </li>
            ))}
          </ul>
        )}
      </Collapsible>

      <Collapsible title="事件流" count={result.events?.length ?? 0}>
        {(result.events ?? []).length === 0 ? (
          <div className="text-sm muted">无</div>
        ) : (
          <div className="col-flex" data-testid="inspector-events" style={{ gap: 0 }}>
            {(result.events ?? []).slice(0, 50).map((ev) => (
              <div className="inspector-event" key={ev.event_id}>
                <span
                  className={
                    "ev-dot " +
                    (ev.event_type?.includes("error")
                      ? "err"
                      : ev.event_type?.includes("warn")
                        ? "warn"
                        : "info")
                  }
                />
                <span className="ev-text text-sm">
                  <IconBolt size={10} /> {ev.event_type}
                </span>
                <span className="ev-time">{ev.occurred_at}</span>
              </div>
            ))}
          </div>
        )}
      </Collapsible>
    </div>
  );
}

function ToolCallCard({ tc }: { tc: ToolCallResult }) {
  return (
    <div
      className="card"
      style={{ padding: 10, marginBottom: 0, background: "var(--bg-soft)" }}
    >
      <div className="row-flex" style={{ justifyContent: "space-between" }}>
        <span className="row-flex" style={{ minWidth: 0 }}>
          <strong className="text-sm">{toolLabel(tc.tool_id)}</strong>
          <InlineCode>{tc.tool_id}</InlineCode>
          {tc.ok ? (
            <Badge kind="ok" withDot>
              已完成
            </Badge>
          ) : (
            <Badge kind="err" withDot>
              需要关注
            </Badge>
          )}
        </span>
      </div>
      {tc.errors && tc.errors.length > 0 && (
        <div
          className="text-sm"
          style={{ color: "var(--danger)", marginTop: 6 }}
        >
          {tc.errors.join("; ")}
        </div>
      )}
      {tc.warnings && tc.warnings.length > 0 && (
        <div className="text-xs muted mt-2">
          提醒: {tc.warnings.length}
        </div>
      )}
    </div>
  );
}

function toolLabel(toolId: string): string {
  if (toolId.startsWith("config_translation.")) return "配置翻译";
  if (toolId.startsWith("knowledge.")) return "知识检索";
  if (toolId.startsWith("artifact.")) return "制品操作";
  if (toolId.startsWith("review.")) return "评审流转";
  if (toolId.startsWith("runtime.")) return "运行诊断";
  return "工具调用";
}

function toolCallSummary(calls: ToolCallResult[]): string {
  const total = calls.length;
  const failed = calls.filter((tc) => !tc.ok).length;
  const recoveredByTool = new Set(
    calls
      .filter((tc) => !tc.ok && calls.some((other) => other.ok && other.tool_id === tc.tool_id))
      .map((tc) => tc.tool_id),
  );
  const primary = calls.find((tc) => tc.ok) ?? calls[0];
  const label = primary ? toolLabel(primary.tool_id) : "工具调用";
  if (failed > 0 && recoveredByTool.size > 0) {
    return `${label}已完成，${failed} 次内部重试已自动恢复`;
  }
  if (failed > 0) {
    return `${label}需要关注，${failed} 次调用未完成`;
  }
  return `${label}已完成，共 ${total} 次调用`;
}

function countArtifacts(result: AgentResult): number {
  // v1.0.3: artifacts come from tool_calls[].artifacts, not metadata.artifacts.
  let total = 0;
  for (const tc of result.tool_calls ?? []) {
    total += (tc.artifacts?.length ?? 0);
  }
  return total;
}

function ArtifactsList({ result }: { result: AgentResult }) {
  // v1.0.3: collect artifacts from all tool calls.
  const allArts: Array<{ artifact_id: string; type: string }> = [];
  for (const tc of result.tool_calls ?? []) {
    for (const a of tc.artifacts ?? []) {
      allArts.push({
        artifact_id: a.artifact_id ?? "",
        type: a.artifact_type ?? a.title ?? "",
      });
    }
  }
  if (allArts.length === 0) {
    return <div className="text-sm muted">本 turn 无 artifact</div>;
  }
  return (
    <ul className="col-flex" data-testid="inspector-artifacts" style={{ gap: 4 }}>
      {allArts.map((a) => (
        <li key={a.artifact_id} className="row-flex text-sm">
          <InlineCode>{a.artifact_id}</InlineCode>
          <Badge kind="info">{a.type}</Badge>
        </li>
      ))}
    </ul>
  );
}
