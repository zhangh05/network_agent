import { useWorkbenchStore } from "../stores/workbench";
import { Badge, Collapsible, EmptyState, InlineCode } from "../components/common";
import type { AgentResult, ToolCallResult } from "../types";

/**
 * Turn Inspector — shows the latest AgentResult in detail.
 *  - selected_skills, visible_tools, tool_calls
 *  - artifacts, knowledge sources
 *  - warnings / errors, events
 *  - trace_id / turn_id
 */
export function Inspector() {
  const { latestResult } = useWorkbenchStore();

  if (!latestResult) {
    return (
      <EmptyState
        text="尚无 turn 结果"
        hint="在中间栏发送一条消息以查看本 turn 的执行细节"
      />
    );
  }

  return <InspectorBody result={latestResult} />;
}

function InspectorBody({ result }: { result: AgentResult }) {
  return (
    <div data-testid="inspector-body">
      <div className="inspector-section">
        <h4>Identity</h4>
        <div className="row">
          <span className="k">turn_id</span>
          <span className="v" data-testid="inspector-turn-id">{result.turn_id || "—"}</span>
        </div>
        <div className="row">
          <span className="k">trace_id</span>
          <span className="v" data-testid="inspector-trace-id">{result.trace_id || "—"}</span>
        </div>
        <div className="row">
          <span className="k">status</span>
          <span className="v">
            {result.ok ? <Badge kind="ok" withDot>ok</Badge> : <Badge kind="err" withDot>failed</Badge>}
          </span>
        </div>
      </div>

      <Collapsible title="Selected Skills" count={result.metadata?.selected_skills?.length ?? 0}>
        <div className="chip-row" data-testid="inspector-skills">
          {(result.metadata?.selected_skills ?? []).length === 0 ? (
            <span className="muted text-sm">none</span>
          ) : (
            (result.metadata?.selected_skills ?? []).map((s) => (
              <Badge key={s} kind="pri">{s}</Badge>
            ))
          )}
        </div>
      </Collapsible>

      <Collapsible title="Visible Tools" count={result.metadata?.visible_tools?.length ?? 0}>
        <div className="chip-row" data-testid="inspector-visible-tools">
          {(result.metadata?.visible_tools ?? []).length === 0 ? (
            <span className="muted text-sm">none</span>
          ) : (
            (result.metadata?.visible_tools ?? []).map((t) => (
              <Badge key={t} kind="muted">{t}</Badge>
            ))
          )}
        </div>
      </Collapsible>

      <Collapsible title="Tool Calls" count={result.tool_calls?.length ?? 0}>
        {(result.tool_calls ?? []).length === 0 ? (
          <div className="muted text-sm">无 tool call</div>
        ) : (
          <div data-testid="inspector-tool-calls">
            {(result.tool_calls ?? []).map((tc) => (
              <ToolCallCard key={tc.call_id} tc={tc} />
            ))}
          </div>
        )}
      </Collapsible>

      <Collapsible title="Artifacts" count={countArtifacts(result)}>
        <ArtifactsList result={result} />
      </Collapsible>

      <Collapsible title="Knowledge Sources" count={result.metadata?.source_count ?? 0}>
        {result.metadata?.source_count ? (
          <div data-testid="inspector-sources">
            <div className="row">
              <span className="k">source_count</span>
              <span className="v">{String(result.metadata?.source_count)}</span>
            </div>
            <div className="row">
              <span className="k">backend</span>
              <span className="v">{String(result.metadata?.retrieval_backend ?? "—")}</span>
            </div>
            <div className="row">
              <span className="k">scope</span>
              <span className="v">{String(result.metadata?.scope ?? "—")}</span>
            </div>
          </div>
        ) : (
          <div className="muted text-sm">本 turn 未命中 knowledge</div>
        )}
      </Collapsible>

      <Collapsible title="Warnings" count={result.warnings?.length ?? 0}>
        {(result.warnings ?? []).length === 0 ? (
          <div className="muted text-sm">无 warning</div>
        ) : (
          <ul className="text-sm" data-testid="inspector-warnings">
            {result.warnings.map((w, i) => (
              <li key={i}><Badge kind="warn">warn</Badge> {w}</li>
            ))}
          </ul>
        )}
      </Collapsible>

      <Collapsible title="Errors" count={result.errors?.length ?? 0}>
        {(result.errors ?? []).length === 0 ? (
          <div className="muted text-sm">无 error</div>
        ) : (
          <ul className="text-sm" data-testid="inspector-errors">
            {result.errors.map((e, i) => (
              <li key={i}><Badge kind="err">err</Badge> {e}</li>
            ))}
          </ul>
        )}
      </Collapsible>

      <Collapsible title="Events" count={result.events?.length ?? 0}>
        {(result.events ?? []).length === 0 ? (
          <div className="muted text-sm">无 event</div>
        ) : (
          <div data-testid="inspector-events">
            {(result.events ?? []).slice(0, 50).map((ev) => (
              <div className="row" key={ev.event_id}>
                <span className="k">{ev.event_type}</span>
                <span className="v mono text-xs">{ev.occurred_at}</span>
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
    <div className="card" style={{ padding: 10, marginBottom: 8 }}>
      <div className="row-flex" style={{ justifyContent: "space-between" }}>
        <span className="row-flex">
          <InlineCode>{tc.tool_id}</InlineCode>
          {tc.ok ? <Badge kind="ok" withDot>ok</Badge> : <Badge kind="err" withDot>failed</Badge>}
        </span>
        {typeof tc.duration_ms === "number" && (
          <span className="muted text-xs">{tc.duration_ms}ms</span>
        )}
      </div>
      {tc.error && (
        <div className="text-sm" style={{ color: "var(--danger)", marginTop: 4 }}>
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
  // We don't have a separate artifacts array on AgentResult, but tool calls
  // may produce them via metadata. We display the count from metadata.
  const fromMeta = (result.metadata as { artifacts?: unknown[] })?.artifacts?.length;
  if (typeof fromMeta === "number") return fromMeta;
  return 0;
}

function ArtifactsList({ result }: { result: AgentResult }) {
  const arr = (result.metadata as { artifacts?: Array<{ artifact_id: string; type: string }> })
    ?.artifacts;
  if (!arr || arr.length === 0) {
    return <div className="muted text-sm">本 turn 无 artifact</div>;
  }
  return (
    <ul className="text-sm" data-testid="inspector-artifacts">
      {arr.map((a) => (
        <li key={a.artifact_id}>
          <InlineCode>{a.artifact_id}</InlineCode> <Badge kind="info">{a.type}</Badge>
        </li>
      ))}
    </ul>
  );
}
