/**
 * RuntimeEventTimeline — collapsible run cards.
 *
 * Each run = one card. Collapsed shows run_id + snippet.
 * Expand to see the full event timeline inside.
 */
import React, { useState } from "react";
import type { AgentResult, RuntimeEvent, ToolCallResult } from "../types";

/* ── helpers ── */

function formatMs(ms?: number | null): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
function toolLabel(s: string): string {
  const p = s.split(".");
  return p.length > 1 ? p[p.length - 1] : s;
}
function timeStr(evt: RuntimeEvent): string {
  const s = evt.occurred_at || evt.started_at || "";
  return s.slice(11, 19) || s.slice(0, 10);
}

/* ── step label & colour ── */

function stepLabel(evt: RuntimeEvent): string {
  return evt.name || evt.event_type || evt.type || "步骤";
}
function stepColor(evt: RuntimeEvent): string {
  const t = (evt.event_type || evt.type || "").toLowerCase();
  if (t.includes("error")) return "var(--danger)";
  if (t.includes("warn"))  return "var(--warn)";
  if (t.includes("tool"))  return "var(--warn)";
  if (t.includes("model")) return "var(--accent)";
  if (t.includes("final") || t.includes("response")) return "var(--accent)";
  if (t.includes("complete") || t.includes("ok")) return "var(--ok)";
  return "var(--text-4)";
}

/* ── tiny tool chip ── */

const ToolChip: React.FC<{ tc: ToolCallResult }> = React.memo(({ tc }) => {
  const [open, setOpen] = useState(false);
  const hasBody = !!(tc.summary || tc.errors?.length || tc.artifacts?.length);
  return (
    <div className="rt-step rt-step-tool">
      <span className="rt-dot" style={{ background: "var(--warn)" }} />
      <div className="rt-step-body">
        <div className="rt-step-head" onClick={() => hasBody && setOpen(!open)} style={{ cursor: hasBody ? "pointer" : "default" }}>
          <span className="rt-step-ok">{tc.ok ? "✓" : "✗"}</span>
          <code className="rt-step-name">{toolLabel(tc.tool_id)}</code>
          <span className="rt-tag">{tc.ok ? "完成" : "失败"}</span>
          {tc.duration_ms != null && <span className="rt-dur">{formatMs(tc.duration_ms)}</span>}
          {hasBody && <span className="rt-chev">{open ? "▲" : "▼"}</span>}
        </div>
        {open && tc.summary && <div className="rt-step-detail">{tc.summary}</div>}
        {open && tc.errors?.map((e, i) => <div key={i} className="rt-step-err">{e}</div>)}
        {open && tc.artifacts?.length ? (
          <div className="rt-chips">
            {tc.artifacts.map((a) => <span key={a.artifact_id} className="rt-chip">{a.title || a.artifact_id.slice(0, 8)}</span>)}
          </div>
        ) : null}
      </div>
    </div>
  );
});

/* ── step row ── */

const StepRow: React.FC<{ evt: RuntimeEvent }> = React.memo(({ evt }) => {
  const color = stepColor(evt);
  const label = stepLabel(evt);
  const msg = evt.summary || evt.message || evt.error || "";
  return (
    <div className="rt-step">
      <span className="rt-dot" style={{ background: color }} />
      <div className="rt-step-body">
        <div className="rt-step-line">
          <span className="rt-step-label">{label}</span>
          <span className="rt-step-ts">{timeStr(evt)}</span>
        </div>
        {msg && <div className="rt-step-msg">{msg}</div>}
      </div>
    </div>
  );
});

/* ── run card ── */

const RunCard: React.FC<{ result: AgentResult; runIdx: number }> = React.memo(({ result, runIdx }) => {
  const [open, setOpen] = useState(false);
  const events = result.events ?? [];
  const tools = result.tool_calls ?? [];
  const meta = result.metadata ?? {};
  const hasDiag = !!(result.errors?.length) || !!(result.warnings?.length);
  const allArtifacts = tools.flatMap((t) => t.artifacts ?? []);

  // Merge tool calls into events
  const toolMap = new Map<string, ToolCallResult>();
  for (const tc of tools) { if (tc.call_id) toolMap.set(tc.call_id, tc); }

  return (
    <div className="rt-card">
      {/* ── collapsed header ── */}
      <div className="rt-card-bar" onClick={() => setOpen(!open)}>
        <span className={`rt-card-dot ${result.ok ? "ok" : "err"}`} />
        <span className="rt-card-id">{result.turn_id?.slice(0, 8) || `#${runIdx + 1}`}</span>
        {meta.workspace_id && <span className="rt-card-ws">{meta.workspace_id}</span>}
        <span className="rt-card-snippet">{result.final_response?.slice(0, 50) || ""}{result.final_response && result.final_response.length > 50 ? "…" : ""}</span>
        <span className="rt-card-chev">{open ? "▲ 收起" : "▼ 展开"}</span>
      </div>

      {/* ── expanded body ── */}
      {open && (
        <div className="rt-card-body">

          {/* diagnostics */}
          {hasDiag && (
            <div className="rt-diag">
              {result.errors?.map((e, i) => <div key={`e-${i}`} className="rt-diag-e">{e}</div>)}
              {result.warnings?.map((w, i) => <div key={`w-${i}`} className="rt-diag-w">{w}</div>)}
            </div>
          )}

          {/* steps */}
          <div className="rt-timeline">
            {events.map((evt, i) => {
              const t = (evt.event_type || evt.type || "").toLowerCase();
              const isTool = t.startsWith("tool_call") || evt.tool_id;
              if (isTool) {
                const match = toolMap.get(evt.tool_id || "") || toolMap.get(evt.event_id || "");
                if (match) return <ToolChip key={`tc-${i}`} tc={match} />;
              }
              return <StepRow key={`ev-${i}`} evt={evt} />;
            })}
            {/* tools without matching events */}
            {tools.filter((tc) => !events.some((e) => e.event_id === tc.call_id || e.tool_id === tc.call_id)).map((tc) => (
              <ToolChip key={`tc-orphan-${tc.call_id}`} tc={tc} />
            ))}
          </div>

          {/* artifacts */}
          {allArtifacts.length > 0 && (
            <div className="rt-artifacts">
              <span className="rt-art-label">产物 · {allArtifacts.length}</span>
              <div className="rt-chips">
                {allArtifacts.slice(0, 8).map((a) => (
                  <span key={a.artifact_id} className="rt-chip">{a.title || a.artifact_id.slice(0, 12)}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
});

/* ── main ── */

export const RuntimeEventTimeline: React.FC<{ results: AgentResult[] }> = React.memo(
  function RuntimeEventTimeline({ results }) {
    if (!results || results.length === 0) {
      return (
        <div className="rt-empty" data-testid="timeline-empty">
          <p>准备就绪</p>
          <p className="rt-empty-hint">发送消息后，执行记录将在此展示</p>
        </div>
      );
    }
    return (
      <div className="rt-list" data-testid="runtime-timeline">
        {results.map((r, i) => <RunCard key={r.turn_id || `run-${i}`} result={r} runIdx={i} />)}
      </div>
    );
  },
);

export default RuntimeEventTimeline;
