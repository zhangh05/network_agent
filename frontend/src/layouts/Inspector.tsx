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
          <div className="text-sm muted">
            无 tool call
            {result.no_tool_reason ? (
              <div className="text-xs muted mt-1" style={{ color: "var(--ink-muted)" }}>
                {(() => {
                  const reason = result.no_tool_reason || '';
                  const labelMap: Record<string, string> = {
                    'no_model_visible_tools': '当前 turn 没有可见工具',
                    'tools_not_called': 'LLM 未选择工具调用（可能需要调整 prompt）',
                    'tools_not_needed': '当前问题可直接回答，无需工具',
                    'blocked_by_hook': 'Turn 被 hook 阻止',
                    'token_limit_exceeded': '上下文超限',
                    'provider_error': 'LLM 服务不可用',
                  };
                  const label = Object.entries(labelMap).find(([key]) => reason.includes(key))?.[1] || reason;
                  return label;
                })()}
              </div>
            ) : null}
          </div>
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
                {(result.tool_calls ?? []).map((tc, idx) => (
                  <ToolCallCard key={tc.call_id || `${tc.tool_id}-${idx}`} tc={tc} />
                ))}
              </div>
            </details>
          </div>
        )}
      </Collapsible>

      {/* v2.1.2: Tool decision transparency */}
      {result.tool_decision && Object.keys(result.tool_decision).length > 0 && (
        <Collapsible
          title="工具决策"
          count={result.tool_decision?.needed ? (result.tool_decision?.selected_tools?.length ?? 0) : 0}
          testid="inspector-tool-decision"
        >
          <div className="col-flex" style={{ gap: 8 }}>
            <div className="text-sm">
              {result.tool_decision.needed ? (
                <Badge kind="accent">需要工具</Badge>
              ) : (
                <Badge kind="muted">无需工具</Badge>
              )}
            </div>
            {result.tool_decision.reason && (
              <div className="text-xs muted">{result.tool_decision.reason}</div>
            )}
            {result.tool_decision.selected_tools && result.tool_decision.selected_tools.length > 0 && (
              <div className="row-flex" style={{ flexWrap: "wrap", gap: 4 }}>
                <span className="text-xs muted">已选工具：</span>
                {result.tool_decision.selected_tools.map((t: string) => (
                  <Badge key={t} kind="accent">{t}</Badge>
                ))}
              </div>
            )}
            {result.tool_decision.blocked_by && result.tool_decision.blocked_by.length > 0 && (
              <div className="text-xs" style={{ color: "var(--ink-warning)" }}>
                被阻止：{result.tool_decision.blocked_by.join(', ')}
              </div>
            )}
            {result.tool_decision.approval_required && (
              <div className="text-xs" style={{ color: "var(--ink-warning)" }}>
                ⚠ 需要审批才能执行
              </div>
            )}
          </div>
        </Collapsible>
      )}

      {Boolean(result.metadata?.tool_scene) && (
        <Collapsible
          title="Tool Plan"
          count={toolPlanSteps(result.metadata.tool_scene).length}
          testid="inspector-tool-plan"
        >
          <div className="col-flex" style={{ gap: 8 }}>
            <div className="row-flex" style={{ gap: 6, flexWrap: "wrap" }}>
              <Badge kind="accent">
                {metaPath(result.metadata.tool_scene, "primary_category") || "planned"}
              </Badge>
              <Badge kind="muted">
                {metaPath(result.metadata.tool_scene, "mode") || "deterministic"}
              </Badge>
              {metaPath(result.metadata.tool_planner, "fallback_used") === "true" && (
                <Badge kind="warn">fallback</Badge>
              )}
            </div>
            {toolPlanSteps(result.metadata.tool_scene).map((step, idx) => (
              <div key={idx} className="card" style={{ padding: 8, marginBottom: 0 }}>
                <div className="text-sm"><strong>{String(step.step ?? idx + 1)}.</strong> {String(step.goal ?? step.purpose ?? "")}</div>
                <div className="row-flex mt-2" style={{ gap: 4, flexWrap: "wrap" }}>
                  {((step.tool_candidates ?? step.preferred_tools ?? []) as unknown[]).map((tool) => (
                    <InlineCode key={String(tool)}>{String(tool)}</InlineCode>
                  ))}
                </div>
              </div>
            ))}
            <details className="collapse">
              <summary>JSON</summary>
              <pre className="text-xs">{JSON.stringify({
                tool_planner: result.metadata.tool_planner,
                tool_scene: result.metadata.tool_scene,
                rule_tool_scene: result.metadata.rule_tool_scene,
              }, null, 2)}</pre>
            </details>
          </div>
        </Collapsible>
      )}

      <Collapsible title="制品" count={countArtifacts(result)}>
        <ArtifactsList result={result} />
      </Collapsible>

      {(() => {
        const sourceInfo = knowledgeSourceInfo(result);
        return (
      <Collapsible title="知识源" count={sourceInfo.count}>
        {sourceInfo.count > 0 ? (
          <div data-testid="inspector-sources">
            <div className="inspector-row">
              <span className="label">count</span>
              <span className="value">{String(sourceInfo.count)}</span>
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
              {sourceInfo.sources.length === 0 ? (
                <div className="text-sm muted">知识检索已执行，但本 turn 未返回来源明细。</div>
              ) : sourceInfo.sources.slice(0, 8).map((s, idx) => (
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
        );
      })()}

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
            {(result.events ?? []).slice(0, 50).map((ev) => {
              const evType = (ev as any).type || ev.event_type || "";
              const ts = (ev as any).timestamp || ev.occurred_at || "";
              return (
              <div className="inspector-event" key={ev.event_id}>
                <span
                  className={
                    "ev-dot " +
                    (evType.includes("error")
                      ? "err"
                      : evType.includes("warn")
                        ? "warn"
                        : "info")
                  }
                />
                <span className="ev-text text-sm">
                  <IconBolt size={10} /> {evType}
                </span>
                <span className="ev-time">{ts}</span>
              </div>
              );
            })}
          </div>
        )}
      </Collapsible>
    </div>
  );
}

function ToolCallCard({ tc }: { tc: ToolCallResult }) {
  const canonicalId = metaString(tc.metadata, "canonical_tool_id") || tc.tool_id;
  const resultKeys = tc.result && typeof tc.result === "object" ? Object.keys(tc.result as Record<string, unknown>) : [];
  return (
    <div
      className="card"
      style={{ padding: 10, marginBottom: 6, background: "var(--bg-soft)" }}
    >
      <div className="row-flex" style={{ justifyContent: "space-between" }}>
        <span className="row-flex" style={{ minWidth: 0 }}>
          <strong className="text-sm">{toolLabel(canonicalId)}</strong>
          <InlineCode>{canonicalId}</InlineCode>
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
      {tc.summary && (
        <div className="text-sm muted mt-1">{tc.summary}</div>
      )}
      {resultKeys.length > 0 && (
        <details className="text-xs mt-2" style={{ color: "var(--muted)" }}>
          <summary>结果 ({resultKeys.length} 项)</summary>
          <pre style={{ maxHeight: 120, overflow: "auto", marginTop: 4, fontSize: 11, whiteSpace: "pre-wrap" }}>
            {safeStringify(tc.result)}
          </pre>
        </details>
      )}
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
  if (toolId.startsWith("host.")) return "本机工具";
  if (toolId.startsWith("workspace.file.")) return "工作区文件";
  if (toolId.startsWith("workspace.artifact.")) return "工作区制品";
  if (toolId.startsWith("network.")) return "网络分析";
  if (toolId.startsWith("web.")) return "外部资料";
  if (toolId.startsWith("memory.")) return "记忆";
  if (toolId.startsWith("report.") || toolId.startsWith("data.") || toolId.startsWith("text.")) return "输出处理";
  if (toolId.startsWith("agent.")) return "多 Agent";
  if (toolId.startsWith("config_translation.")) return "配置翻译";
  if (toolId.startsWith("knowledge.")) return "知识检索";
  if (toolId.startsWith("artifact.")) return "制品操作";
  if (toolId.startsWith("review.")) return "评审流转";
  if (toolId.startsWith("runtime.")) return "运行诊断";
  return "工具调用";
}

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

function metaPath(value: unknown, key: string): string {
  if (!value || typeof value !== "object") return "";
  const item = (value as Record<string, unknown>)[key];
  return typeof item === "string" || typeof item === "boolean" ? String(item) : "";
}

function toolPlanSteps(scene: unknown): Array<Record<string, unknown>> {
  if (!scene || typeof scene !== "object") return [];
  const plan = (scene as Record<string, unknown>).tool_plan;
  const chain = (scene as Record<string, unknown>).tool_chain;
  if (Array.isArray(plan)) return plan as Array<Record<string, unknown>>;
  if (Array.isArray(chain)) return chain as Array<Record<string, unknown>>;
  return [];
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

function knowledgeSourceInfo(result: AgentResult): { count: number; sources: any[] } {
  const metadata = result.metadata ?? {};
  const metaSources = ((metadata.context_sources as any[]) ?? (metadata.source_summary as any[]) ?? []) as any[];
  const toolSources: any[] = [];
  let toolSourceCount = 0;

  for (const tc of result.tool_calls ?? []) {
    if (!tc.tool_id?.startsWith("knowledge.")) continue;
    if (typeof tc.source_count === "number") toolSourceCount += tc.source_count;
    const toolResult = tc.result as any;
    const fromResult =
      (Array.isArray(toolResult?.context_sources) && toolResult.context_sources) ||
      (Array.isArray(toolResult?.source_summary) && toolResult.source_summary) ||
      (Array.isArray(toolResult?.results) && toolResult.results) ||
      [];
    toolSources.push(...fromResult);
    if (!tc.source_count && typeof toolResult?.source_count === "number") toolSourceCount += toolResult.source_count;
    if (!tc.source_count && typeof toolResult?.count === "number") toolSourceCount += toolResult.count;
  }

  const sources = metaSources.length ? metaSources : toolSources;
  const metaCount = typeof metadata.source_count === "number" ? metadata.source_count : 0;
  const count = Math.max(metaCount, sources.length, toolSourceCount);
  return { count, sources };
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
