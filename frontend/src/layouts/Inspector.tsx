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
          <div className="col-flex" data-testid="inspector-tool-calls" style={{ gap: 6 }}>
            {(result.tool_calls ?? []).map((tc) => (
              <ToolCallCard key={tc.call_id} tc={tc} />
            ))}
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
          <InlineCode>{tc.tool_id}</InlineCode>
          {tc.ok ? (
            <Badge kind="ok" withDot>
              ok
            </Badge>
          ) : (
            <Badge kind="err" withDot>
              failed
            </Badge>
          )}
        </span>
        {typeof tc.duration_ms === "number" && (
          <span className="muted text-xs mono">{tc.duration_ms}ms</span>
        )}
      </div>
      {tc.error && (
        <div
          className="text-sm"
          style={{ color: "var(--danger)", marginTop: 6 }}
        >
          {tc.error}
        </div>
      )}
      {tc.warnings && tc.warnings.length > 0 && (
        <div className="text-xs muted mt-2">
          warnings: {tc.warnings.length}
        </div>
      )}
    </div>
  );
}

function countArtifacts(result: AgentResult): number {
  const fromMeta = (result.metadata as { artifacts?: unknown[] })?.artifacts?.length;
  if (typeof fromMeta === "number") return fromMeta;
  return 0;
}

function ArtifactsList({ result }: { result: AgentResult }) {
  const arr = (result.metadata as {
    artifacts?: Array<{ artifact_id: string; type: string }>;
  })?.artifacts;
  if (!arr || arr.length === 0) {
    return <div className="text-sm muted">本 turn 无 artifact</div>;
  }
  return (
    <ul className="col-flex" data-testid="inspector-artifacts" style={{ gap: 4 }}>
      {arr.map((a) => (
        <li key={a.artifact_id} className="row-flex text-sm">
          <InlineCode>{a.artifact_id}</InlineCode>
          <Badge kind="info">{a.type}</Badge>
        </li>
      ))}
    </ul>
  );
}
