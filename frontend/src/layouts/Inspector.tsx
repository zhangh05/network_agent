import { useEffect, useState } from "react";
import { useWorkbenchStore } from "../stores/workbench";
import {
  Badge,
  Collapsible,
  EmptyState,
  InlineCode,
} from "../components/common";
import type { AgentResult, AgentGraphState, DecisionReport, SourceSummary, ToolCallResult, ToolSceneMeta } from "../types";
import { IconAlert } from "../components/Icon";
import { DecisionReportPanel } from "../components/DecisionReportPanel";
import { runtimeAuditApi, graphApi, breakpointApi } from "../api";
import { toolLabel, toolPlanSteps } from "../utils/displayText";

const CAT_COLORS: Record<string, string> = {
  exec: "#D85A30", device: "#378ADD", workspace: "#1D9E75",
  knowledge: "#534AB7", memory: "#993556", system: "#BA7517",
  web: "#0F6E56", browser: "#639922", git: "#D4537E",
  agent: "#888780", config: "#185FA5", code: "#0C447C", data: "#993C1D",
};

export function Inspector() {
  const latestResult = useWorkbenchStore((s) => s.latestResult);

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
  const [decision, setDecision] = useState<DecisionReport | null>(null);
  const [decisionLoading, setDecisionLoading] = useState(false);
  const [decisionError, setDecisionError] = useState("");
  const runId = result.turn_id || result.trace_id;
  const workspaceId = String(result.metadata?.workspace_id || "default");

  useEffect(() => {
    let active = true;
    setDecision(null);
    setDecisionError("");
    if (!runId) return () => { active = false; };
    setDecisionLoading(true);
    runtimeAuditApi.decision(workspaceId, runId)
      .then((response) => {
        if (active) setDecision(response.item || null);
      })
      .catch((error) => {
        if (active) setDecisionError(error?.message || "该 turn 没有决策报告");
      })
      .finally(() => {
        if (active) setDecisionLoading(false);
      });
    return () => { active = false; };
  }, [runId, workspaceId]);

  return (
    <div data-testid="inspector-body" style={{ paddingBottom: 16 }}>

      {/* ═══════════════ 顶部概览卡片 ═══════════════ */}
      <AgentSystemInfo />

      {/* ═══════════════ 身份摘要 ═══════════════ */}
      <div style={{
        margin: "0 16px 8px", padding: "10px 12px",
        background: "var(--bg-soft)", borderRadius: 6,
        border: "1px solid var(--line-2)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: "var(--ink-mute)", textTransform: "uppercase", letterSpacing: "0.5px" }}>Run</span>
          {result.ok ? <Badge kind="ok" withDot>ok</Badge> : <Badge kind="err" withDot>failed</Badge>}
          {result.tool_decision?.approval_required && <Badge kind="warn">需审批</Badge>}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "auto minmax(0, 1fr)", gap: "2px 10px", fontSize: 11, lineHeight: 1.6 }}>
          <span style={{ color: "var(--ink-mute)" }}>turn</span>
          <span data-testid="inspector-turn-id" style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--ink-soft)", overflow: "hidden", textOverflow: "ellipsis" }}>{result.turn_id || "—"}</span>
          <span style={{ color: "var(--ink-mute)" }}>session</span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--ink-soft)", overflow: "hidden", textOverflow: "ellipsis" }}>{result.session_id || "—"}</span>
          <span style={{ color: "var(--ink-mute)" }}>trace</span>
          <span data-testid="inspector-trace-id" style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--ink-soft)", overflow: "hidden", textOverflow: "ellipsis" }}>{result.trace_id || "—"}</span>
          {result.metadata?.planner_mode && (
            <>
              <span style={{ color: "var(--ink-mute)" }}>mode</span>
              <span style={{ color: "var(--ink-soft)" }}>{result.metadata.planner_mode}</span>
            </>
          )}
        </div>
      </div>

      {/* ═══════════════ 能力 & 工具（合并） ═══════════════ */}
      <Collapsible
        title="路由"
        count={
          (result.metadata?.selected_capabilities ?? result.metadata?.selected_skills ?? []).length +
          (result.metadata?.visible_tools?.length ?? 0)
        }
        testid="inspector-routing-section"
      >
        <CapRoutingCompact result={result} />
      </Collapsible>

      {/* ═══════════════ 决策报告 ═══════════════ */}
      <Collapsible
        title="决策报告"
        count={decision ? 1 : 0}
        testid="inspector-decision-report"
      >
        <DecisionReportPanel
          report={decision}
          loading={decisionLoading}
          error={decisionError}
        />
      </Collapsible>

      {/* ═══════════════ 工具调用 ═══════════════ */}
      <Collapsible
        title="工具调用"
        count={result.tool_calls?.length ?? 0}
        testid="inspector-toolcalls-section"
      >
        {(result.tool_calls ?? []).length === 0 ? (
          <div className="text-sm muted">无工具调用</div>
        ) : (
          <div className="col-flex" style={{ gap: 8 }}>
            <div
              className="card"
              data-testid="inspector-tool-summary"
              style={{ padding: 10, marginBottom: 0, background: "var(--bg-soft)" }}
            >
              <strong>{toolCallSummary(result.tool_calls ?? [])}</strong>
            </div>
            <details>
              <summary className="text-sm muted" style={{ cursor: "pointer" }}>
                技术详情
              </summary>
              <div className="col-flex mt-2" data-testid="inspector-tool-calls" style={{ gap: 6 }}>
                {(result.tool_calls ?? []).map((tc, idx) => (
                  <ToolCallCard key={tc.call_id || `${tc.tool_id}-${idx}`} tc={tc} />
                ))}
              </div>
            </details>
            {result.no_tool_reason && (
              <div className="text-xs muted mt-2" style={{ color: "var(--ink-muted)" }}>
                {notoolLabel(result.no_tool_reason)}
              </div>
            )}
          </div>
        )}
      </Collapsible>

      {/* ═══════════════ Tool Plan（合并工具决策） ═══════════════ */}
      {Boolean(result.metadata?.tool_scene) && (
        <Collapsible
          title="工具决策"
          count={toolPlanSteps(result.metadata.tool_scene).length}
          testid="inspector-tool-plan"
        >
          <div className="col-flex" style={{ gap: 6 }}>
            {result.tool_decision?.reason && (
              <div className="text-xs muted">{result.tool_decision.reason}</div>
            )}
            <div className="row-flex" style={{ gap: 6, flexWrap: "wrap" }}>
              <Badge kind="accent">
                {(result.metadata.tool_scene as ToolSceneMeta).primary_category || "planned"}
              </Badge>
              <Badge kind="muted">
                {(result.metadata.tool_scene as ToolSceneMeta).mode || "deterministic"}
              </Badge>
              {result.metadata.tool_planner?.fallback_used && <Badge kind="warn">fallback</Badge>}
            </div>
            {toolPlanSteps(result.metadata.tool_scene).map((step, idx) => (
              <div key={idx} className="card" style={{ padding: 8, marginBottom: 0 }}>
                <div className="text-sm"><strong>{String(step.step ?? idx + 1)}.</strong> {String(step.goal ?? step.purpose ?? "")}</div>
                <div className="row-flex mt-2" style={{ gap: 4, flexWrap: "wrap" }}>
                  {(step.tool_candidates ?? step.preferred_tools ?? []).map((tool) => (
                    <InlineCode key={String(tool)}>{String(tool)}</InlineCode>
                  ))}
                </div>
              </div>
            ))}
            {result.tool_decision?.blocked_by && result.tool_decision.blocked_by.length > 0 && (
              <div className="text-xs" style={{ color: "var(--ink-warning)" }}>
                阻止：{result.tool_decision.blocked_by.join(', ')}
              </div>
            )}
          </div>
        </Collapsible>
      )}

      {/* ═══════════════ 制品 ═══════════════ */}
      <Collapsible title="制品" count={countArtifacts(result)}>
        <ArtifactsList result={result} />
      </Collapsible>

      {/* ═══════════════ 知识源（简化） ═══════════════ */}
      {(() => {
        const sourceInfo = knowledgeSourceInfo(result);
        return (
          <Collapsible title="知识源" count={sourceInfo.count}>
            {sourceInfo.count > 0 ? (
              <div data-testid="inspector-sources" className="col-flex" style={{ gap: 6 }}>
                {sourceInfo.sources.length === 0 ? (
                  <div className="text-sm muted">知识检索已执行，但本 turn 未返回来源明细。</div>
                ) : sourceInfo.sources.slice(0, 6).map((s, idx) => (
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
            ) : (
              <div className="text-sm muted">本 turn 未命中 knowledge</div>
            )}
          </Collapsible>
        );
      })()}

      {/* ═══════════════ 警告 & 错误 ═══════════════ */}
      {(result.warnings?.length || result.errors?.length) ? (
        <div className="col-flex" style={{ gap: 0 }}>
          {result.warnings?.length ? (
            <Collapsible title="警告" count={result.warnings.length}>
              <ul className="col-flex" data-testid="inspector-warnings" style={{ gap: 4 }}>
                {result.warnings.map((w, i) => (
                  <li key={i} className="row-flex text-sm" style={{ gap: 6 }}>
                    <Badge kind="warn">warn</Badge>
                    <span>{w}</span>
                  </li>
                ))}
              </ul>
            </Collapsible>
          ) : null}
          {result.errors?.length ? (
            <Collapsible title="错误" count={result.errors.length}>
              <ul className="col-flex" data-testid="inspector-errors" style={{ gap: 4 }}>
                {result.errors.map((e, i) => (
                  <li key={i} className="row-flex text-sm" style={{ gap: 6 }}>
                    <Badge kind="err"><IconAlert size={10} /> err</Badge>
                    <span>{e}</span>
                  </li>
                ))}
              </ul>
            </Collapsible>
          ) : null}
        </div>
      ) : null}

      {/* ═══════════════ 事件流（默认折叠） ═══════════════ */}
      {(result.events?.length ?? 0) > 0 && (
        <Collapsible title="事件流" count={result.events?.length ?? 0} defaultOpen={false}>
          <div className="col-flex" data-testid="inspector-events" style={{ gap: 0 }}>
            {(result.events ?? []).slice(0, 20).map((ev) => {
              const evType = (ev as any).type || ev.event_type || "";
              return (
                <div className="inspector-event" key={ev.event_id}>
                  <span
                    className={
                      "ev-dot " +
                      (evType.includes("error") ? "err" : evType.includes("warn") ? "warn" : "info")
                    }
                  />
                  <span className="ev-text text-sm">{evType}</span>
                </div>
              );
            })}
          </div>
        </Collapsible>
      )}
    </div>
  );
}

/* ──────────────── 紧凑路由面板 ──────────────── */

function CapRoutingCompact({ result }: { result: AgentResult }) {
  const caps = (result.metadata?.selected_capabilities ?? result.metadata?.selected_skills ?? []) as string[];
  const tools = (result.metadata?.visible_tools ?? []) as string[];
  const decision = result.tool_decision;

  // Group tools by category prefix
  const grouped: Record<string, number> = {};
  for (const t of tools) {
    const prefix = t.split(".")[0] || "other";
    grouped[prefix] = (grouped[prefix] || 0) + 1;
  }

  return (
    <div className="col-flex" style={{ gap: 8 }}>
      {caps.length > 0 && (
        <div>
          <div className="text-xs muted mb-2" style={{ fontWeight: 600, textTransform: "uppercase" }}>Capabilities</div>
          <div className="row-flex" style={{ flexWrap: "wrap", gap: 4 }}>
            {caps.map((c) => <Badge key={c} kind="accent">{c}</Badge>)}
          </div>
        </div>
      )}
      <div>
        <div className="text-xs muted mb-2" style={{ fontWeight: 600, textTransform: "uppercase" }}>
          Tools ({tools.length})
          {decision?.needed ? <Badge kind="accent" style={{ marginLeft: 4 }}>需要</Badge> : <Badge kind="muted" style={{ marginLeft: 4 }}>无需</Badge>}
        </div>
        <div className="row-flex" style={{ flexWrap: "wrap", gap: 3 }}>
          {Object.entries(grouped).sort(([,a], [,b]) => b - a).map(([cat, n]) => {
            const color = CAT_COLORS[cat] || "#888";
            return (
              <span key={cat} style={{
                fontSize: 10, padding: "2px 7px", borderRadius: 3,
                border: `1px solid ${color}30`, color, background: `${color}10`,
                fontWeight: 600,
              }}>
                {cat} ({n})
              </span>
            );
          })}
        </div>
        {decision?.selected_tools && decision.selected_tools.length > 0 && decision.selected_tools.length !== tools.length && (
          <div className="row-flex mt-2" style={{ flexWrap: "wrap", gap: 4 }}>
            <span className="text-xs muted">已选：</span>
            {decision.selected_tools.map((t: string) => <InlineCode key={t}>{t}</InlineCode>)}
          </div>
        )}
      </div>
    </div>
  );
}

/* ──────────────── ToolCallCard ──────────────── */

function ToolCallCard({ tc }: { tc: ToolCallResult }) {
  const canonicalId = metaString(tc.metadata, "canonical_tool_id") || tc.tool_id;
  const resultKeys = tc.result && typeof tc.result === "object" ? Object.keys(tc.result as Record<string, unknown>) : [];
  return (
    <div className="card" style={{ padding: 10, marginBottom: 6, background: "var(--bg-soft)" }}>
      <div className="row-flex" style={{ justifyContent: "space-between" }}>
        <span className="row-flex" style={{ minWidth: 0 }}>
          <strong className="text-sm">{toolLabel(canonicalId)}</strong>
          <InlineCode>{canonicalId}</InlineCode>
          {tc.ok ? <Badge kind="ok" withDot>已完成</Badge> : <Badge kind="err" withDot>需要关注</Badge>}
        </span>
      </div>
      {tc.summary && <div className="text-sm muted mt-1">{tc.summary}</div>}
      {resultKeys.length > 0 && (
        <details className="text-xs mt-2" style={{ color: "var(--muted)" }}>
          <summary>结果 ({resultKeys.length} 项)</summary>
          <pre style={{ maxHeight: 120, overflow: "auto", marginTop: 4, fontSize: 11, whiteSpace: "pre-wrap" }}>
            {safeStringify(tc.result)}
          </pre>
        </details>
      )}
      {tc.errors && tc.errors.length > 0 && (
        <div className="text-sm" style={{ color: "var(--danger)", marginTop: 6 }}>
          {tc.errors.join("; ")}
        </div>
      )}
      {tc.warnings && tc.warnings.length > 0 && (
        <div className="text-xs muted mt-2">提醒: {tc.warnings.length}</div>
      )}
    </div>
  );
}

/* ──────────────── Helpers ──────────────── */

function safeStringify(value: unknown): string {
  try {
    const seen = new WeakSet();
    return JSON.stringify(value, (_key, val) => {
      if (typeof val === "object" && val !== null) {
        if (seen.has(val)) return "[circular]";
        seen.add(val);
      }
      return val;
    }, 2);
  } catch {
    return String(value);
  }
}

function metaString(metadata: Record<string, unknown> | undefined, key: string): string {
  const value = metadata?.[key];
  return typeof value === "string" ? value : "";
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

function notoolLabel(reason: string): string {
  const labelMap: Record<string, string> = {
    'no_model_visible_tools': '当前 turn 没有可见工具',
    'tools_not_called': 'LLM 未选择工具调用',
    'tools_not_needed': '问题可直接回答，无需工具',
    'blocked_by_hook': 'Turn 被 hook 阻止',
    'token_limit_exceeded': '上下文超限',
    'provider_error': 'LLM 服务不可用',
  };
  return Object.entries(labelMap).find(([key]) => reason.includes(key))?.[1] || reason;
}

function countArtifacts(result: AgentResult): number {
  let total = 0;
  for (const tc of result.tool_calls ?? []) {
    total += (tc.artifacts?.length ?? 0);
  }
  return total;
}

function knowledgeSourceInfo(result: AgentResult): { count: number; sources: SourceSummary[] } {
  const metadata = result.metadata ?? {};
  const metaSources = metadata.context_sources ?? metadata.source_summary ?? [];
  const toolSources: SourceSummary[] = [];
  let toolSourceCount = 0;

  for (const tc of result.tool_calls ?? []) {
    if (!tc.tool_id?.startsWith("knowledge.")) continue;
    if (typeof tc.source_count === "number") toolSourceCount += tc.source_count;
    const toolResult = tc.result as Record<string, unknown> | undefined;
    const fromResult =
      (Array.isArray(toolResult?.context_sources) && toolResult.context_sources as Array<Record<string, unknown>>) ||
      (Array.isArray(toolResult?.source_summary) && toolResult.source_summary as Array<Record<string, unknown>>) ||
      (Array.isArray(toolResult?.results) && toolResult.results as Array<Record<string, unknown>>) ||
      [];
    toolSources.push(...fromResult.map(sourceSummaryFromRecord));
    if (!tc.source_count && typeof toolResult?.source_count === "number") toolSourceCount += toolResult.source_count;
    if (!tc.source_count && typeof toolResult?.count === "number") toolSourceCount += toolResult.count;
  }

  const sources = metaSources.length ? metaSources : toolSources;
  const metaCount = typeof metadata.source_count === "number" ? metadata.source_count : 0;
  const count = Math.max(metaCount, sources.length, toolSourceCount);
  return { count, sources };
}

function sourceSummaryFromRecord(value: Record<string, unknown>): SourceSummary {
  return {
    source_id: String(value.source_id ?? value.id ?? ""),
    chunk_id: typeof value.chunk_id === "string" ? value.chunk_id : undefined,
    citation_id: typeof value.citation_id === "string" ? value.citation_id : undefined,
    source_type: typeof value.source_type === "string" ? value.source_type : undefined,
    evidence_type: typeof value.evidence_type === "string" ? value.evidence_type : undefined,
    title: String(value.title ?? value.source_id ?? ""),
    chapter: typeof value.chapter === "string" ? value.chapter : undefined,
    section: typeof value.section === "string" ? value.section : undefined,
    snippet: String(value.snippet ?? value.safe_excerpt ?? value.summary ?? ""),
    score: typeof value.score === "number" ? value.score : 0,
  };
}

function ArtifactsList({ result }: { result: AgentResult }) {
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

/* ──────────────── v3.8: Agent System Info ──────────────── */

function AgentSystemInfo() {
  const [state, setState] = useState<AgentGraphState | null>(null);
  const [bps, setBps] = useState<string[]>([]);
  const [bpInput, setBpInput] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all([graphApi.state().catch(() => null), breakpointApi.list().catch(() => ({ ok: true, breakpoints: [] }))])
      .then(([s, b]) => { if (active) { setState(s); setBps(b?.breakpoints || []); } })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const addBp = async () => {
    if (!bpInput.trim()) return;
    const next = [...bps, bpInput.trim()];
    await breakpointApi.set(next);
    setBps(next);
    setBpInput("");
  };

  const removeBp = (t: string) => { breakpointApi.set(bps.filter((b) => b !== t)); setBps((p) => p.filter((b) => b !== t)); };
  const clearBps = () => { breakpointApi.clear(); setBps([]); };

  if (loading && !state) return <div style={{ padding: "0 16px 8px", fontSize: 12, color: "var(--ink-mute)" }}>Loading...</div>;
  if (!state) return null;

  return (
    <div style={{ margin: "0 16px 12px" }}>
      {/* ── Title bar ── */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 8, padding: "6px 10px",
        background: "var(--bg-soft)", borderRadius: 6,
        border: "1px solid var(--line-2)",
      }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: "var(--ink-mute)", textTransform: "uppercase", letterSpacing: "0.5px" }}>
          Agent System
        </span>
        <span style={{ fontSize: 10, color: "var(--ink-mute)", fontFamily: "var(--font-mono)" }}>v3.8</span>
      </div>

      {/* ── Stat pills ── */}
      <div style={{ display: "flex", gap: 4, marginBottom: 10 }}>
        {[
          ["Tools", state.total_tools],
          ["Core", state.core_tools],
          ["Cats", state.categories?.length],
          ["CKPT", state.checkpoint_backend || "json"],
        ].map(([label, value]) => (
          <div key={label as string} style={{
            flex: 1, textAlign: "center", padding: "5px 2px",
            background: "var(--bg-soft)", borderRadius: 4,
            border: "1px solid var(--line-2)",
          }}>
            <div style={{ fontSize: 9, color: "var(--ink-mute)", textTransform: "uppercase" }}>{label}</div>
            <div style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>{String(value ?? "—")}</div>
          </div>
        ))}
      </div>

      {/* ── Category tags ── */}
      <div style={{ marginBottom: 10, display: "flex", flexWrap: "wrap", gap: 3 }}>
        {(state.categories || []).map((cat) => (
          <span key={cat} style={{
            fontSize: 9, padding: "1px 6px", borderRadius: 3,
            border: `1px solid ${(CAT_COLORS[cat] || "#888")}30`,
            color: CAT_COLORS[cat] || "#888", background: `${(CAT_COLORS[cat] || "#888")}0a`,
            fontWeight: 600, letterSpacing: "0.3px",
          }}>{cat}</span>
        ))}
      </div>

      {/* ── Breakpoints ── */}
      <div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
          <span style={{ fontSize: 10, fontWeight: 700, color: "var(--ink-mute)", textTransform: "uppercase" }}>
            Breakpoints {bps.length > 0 ? `(${bps.length})` : ""}
          </span>
          {bps.length > 0 && (
            <button onClick={clearBps} style={{
              fontSize: 9, padding: "1px 6px", border: "1px solid var(--line)", borderRadius: 3,
              cursor: "pointer", color: "var(--ink-mute)", background: "transparent",
            }}>clear</button>
          )}
        </div>
        <div style={{ display: "flex", gap: 3 }}>
          <input
            placeholder="tool_id"
            value={bpInput}
            onChange={(e) => setBpInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addBp()}
            style={{
              flex: 1, padding: "3px 6px", border: "1px solid var(--line)", borderRadius: 3,
              fontSize: 10, background: "var(--surface)", color: "var(--ink)",
            }}
          />
          <button onClick={addBp} style={{
            padding: "2px 8px", background: "var(--accent)", color: "#fff",
            border: "none", borderRadius: 3, cursor: "pointer", fontSize: 11, fontWeight: 600,
          }}>+</button>
        </div>
        {bps.map((bp) => (
          <div key={bp} style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
            padding: "2px 6px", marginTop: 3,
            background: "var(--danger-soft)", borderRadius: 3,
            fontSize: 10, fontFamily: "var(--font-mono)",
          }}>
            <code style={{ fontSize: 9, color: "var(--danger)" }}>{bp}</code>
            <span onClick={() => removeBp(bp)} style={{
              cursor: "pointer", color: "var(--danger)", fontSize: 12, lineHeight: 1, fontWeight: 700,
            }}>×</span>
          </div>
        ))}
      </div>
    </div>
  );
}
