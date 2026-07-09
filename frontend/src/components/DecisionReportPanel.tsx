import { Badge, EmptyState } from "./common";
import type { DecisionReport } from "../types";

interface Props {
  report: DecisionReport | null;
  loading?: boolean;
  error?: string;
}

export function DecisionReportPanel({ report, loading = false, error = "" }: Props) {
  if (loading) {
    return <div className="text-sm muted">正在加载决策报告…</div>;
  }
  if (!report) {
    return error
      ? <EmptyState text="决策报告不可用" hint={error} />
      : <EmptyState text="该运行没有决策报告" />;
  }

  const businessCapabilities = report.business_capabilities || [];
  const planning = report.tool_planning_decision || {};
  const blockedTools = planning.blocked_tools ?? [];
  const retrieval = report.retrieval_decision || {};
  const execution = report.tool_execution_summary || { called: [], blocked: [], failed: [], succeeded: [] };
  const trace = report.trace_summary || { real_event_count: 0, synthetic_event_count: 0, missing_event_count: 0 };
  const capabilityIds = businessCapabilities
    .map((cap) => String(cap.capability_id || cap.intent || ""))
    .filter(Boolean);

  return (
    <div data-testid="decision-report" className="col-flex" style={{ gap: 10 }}>

      {/* Status row */}
      <div className="row-flex" style={{ gap: 6, flexWrap: "wrap" }}>
        <Badge kind={report.decision_status === "complete" ? "ok" : "warn"}>
          {report.decision_status === "complete" ? "决策完整" : "决策降级"}
        </Badge>
        {trace.missing_event_count > 0 && <Badge kind="err">缺失 {trace.missing_event_count}</Badge>}
      </div>

      {/* Business capabilities */}
      <CompactRow label="能力">
        <div className="row-flex" style={{ gap: 4, flexWrap: "wrap" }}>
          {capabilityIds.length > 0
            ? capabilityIds.map((id) => <Badge key={id} kind="accent">{id}</Badge>)
            : <span className="text-xs muted">未命中</span>}
        </div>
      </CompactRow>

      {/* Tool Boundary — summary only, no full list */}
      <CompactRow label="工具边界">
        <div className="row-flex" style={{ gap: 6 }}>
          <span className="text-xs" style={{ color: "var(--ink-soft)" }}>可见 {planning.visible_tools?.length ?? 0}</span>
          <span className="text-xs" style={{ color: "var(--ink-soft)" }}>必需 {planning.required_tools?.length ?? 0}</span>
          <span className="text-xs" style={{ color: "var(--ink-soft)" }}>调用 {execution.called?.length ?? 0}</span>
        </div>
        {(planning.required_tools ?? planning.visible_tools ?? []).length > 0 && (
          <div className="row-flex mt-1" style={{ gap: 4, flexWrap: "wrap" }}>
            {(planning.required_tools ?? planning.visible_tools ?? []).map((tool) => (
              <Badge key={tool} kind="muted">{tool}</Badge>
            ))}
          </div>
        )}
        {blockedTools.length > 0 && (
          <div className="text-xs mt-1" style={{ color: "var(--warning)" }}>
            阻止：{blockedTools.map((item) => item.tool_id || "unknown").join("、")}
          </div>
        )}
      </CompactRow>

      {/* Context Retrieval */}
      {Object.keys(retrieval).length > 0 && (
        <CompactRow label="检索">
          <div className="row-flex" style={{ gap: 4, flexWrap: "wrap" }}>
            {Object.entries(retrieval).map(([name, value]) => (
              <Badge key={name} kind={retrievalKind(String(value.status || ""))}>
                {retrievalLabel(name)}：{statusLabel(String(value.status || "unknown"))}
              </Badge>
            ))}
          </div>
        </CompactRow>
      )}

      {/* Trace integrity — compact */}
      <CompactRow label="Trace">
        <div className="row-flex" style={{ gap: 8 }}>
          <span className="text-xs" style={{ color: "var(--ok)" }}>真实 {trace.real_event_count}</span>
          <span className="text-xs" style={{ color: trace.synthetic_event_count ? "var(--warn)" : "var(--ink-mute)" }}>合成 {trace.synthetic_event_count}</span>
          <span className="text-xs" style={{ color: trace.missing_event_count ? "var(--danger)" : "var(--ink-mute)" }}>缺失 {trace.missing_event_count}</span>
        </div>
      </CompactRow>

      {/* Raw JSON collapsed */}
      <details>
        <summary className="text-xs muted" style={{ cursor: "pointer" }}>原始数据</summary>
        <pre className="text-xs" style={{ maxHeight: 280, overflow: "auto", marginTop: 4 }}>
          {JSON.stringify(report, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function CompactRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ borderTop: "1px solid var(--line-2)", paddingTop: 6 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: "var(--ink-mute)", textTransform: "uppercase", marginBottom: 4 }}>{label}</div>
      {children}
    </div>
  );
}

function retrievalLabel(name: string): string {
  return ({ memory: "记忆", knowledge: "知识", file_evidence: "文件证据" } as Record<string, string>)[name] || name;
}

function statusLabel(status: string): string {
  return ({
    hit: "命中", miss: "未命中", skipped: "跳过",
    not_applicable: "不适用", required: "需要", optional: "可选", error: "错误",
  } as Record<string, string>)[status] || status;
}

function retrievalKind(status: string): "ok" | "warn" | "err" | "muted" {
  if (status === "hit") return "ok";
  if (status === "miss") return "warn";
  if (status === "error") return "err";
  return "muted";
}
