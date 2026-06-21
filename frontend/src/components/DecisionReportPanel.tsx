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

  const route = report.capability_route || {};
  const planning = report.tool_planning_decision || {};
  const retrieval = report.retrieval_decision || {};
  const execution = report.tool_execution_summary || {
    called: [], blocked: [], failed: [], succeeded: [],
  };
  const trace = report.trace_summary || {
    real_event_count: 0, synthetic_event_count: 0, missing_event_count: 0,
  };
  const capabilityIds = route.capability_ids || [];
  const visibleTools = planning.visible_tools || [];
  const requiredTools = planning.required_tools || [];
  const blockedTools = planning.blocked_tools || [];

  return (
    <div data-testid="decision-report" className="col-flex" style={{ gap: 16 }}>
      <div className="row-flex" style={{ gap: 6, flexWrap: "wrap" }}>
        <Badge kind={report.decision_status === "complete" ? "ok" : "warn"}>
          {report.decision_status === "complete" ? "决策完整" : "决策降级"}
        </Badge>
        {route.ambiguous && <Badge kind="warn">意图模糊</Badge>}
        {route.fallback_used && <Badge kind="warn">使用安全回退</Badge>}
        <Badge kind="muted">{report.schema_version}</Badge>
      </div>

      <DecisionSection title="能力路由">
        <ChipList values={capabilityIds} empty="未选择业务能力" kind="accent" />
        <div className="text-xs muted mt-2">
          {route.route_version ? `路由 ${route.route_version}` : "路由版本未知"}
          {typeof route.latency_ms === "number" ? ` · ${route.latency_ms.toFixed(2)} ms` : ""}
        </div>
      </DecisionSection>

      <DecisionSection title="工具边界">
        <div className="text-xs muted">可见 {visibleTools.length} · 必需 {requiredTools.length} · 调用 {execution.called?.length ?? 0}</div>
        <ChipList values={visibleTools} empty="本 turn 无可见工具" />
        {blockedTools.length > 0 && (
          <div className="text-xs mt-2" style={{ color: "var(--ink-warning)" }}>
            阻止：{blockedTools.map((item) => item.tool_id || "unknown").join("、")}
          </div>
        )}
      </DecisionSection>

      <DecisionSection title="上下文检索">
        <div className="row-flex" style={{ gap: 6, flexWrap: "wrap" }}>
          {Object.entries(retrieval).map(([name, value]) => (
            <Badge key={name} kind={retrievalKind(String(value?.status || ""))}>
              {retrievalLabel(name)}：{statusLabel(String(value?.status || "unknown"))}
            </Badge>
          ))}
          {Object.keys(retrieval).length === 0 && <span className="text-sm muted">无检索决策</span>}
        </div>
      </DecisionSection>

      <DecisionSection title="Trace 真实性">
        <div className="row-flex" style={{ gap: 6, flexWrap: "wrap" }}>
          <Badge kind="ok">真实 {trace.real_event_count}</Badge>
          <Badge kind={trace.synthetic_event_count ? "warn" : "muted"}>合成 {trace.synthetic_event_count}</Badge>
          <Badge kind={trace.missing_event_count ? "err" : "muted"}>缺失 {trace.missing_event_count}</Badge>
        </div>
      </DecisionSection>

      {(report.catalog_expansions?.length ?? 0) > 0 && (
        <DecisionSection title="目录扩展">
          {report.catalog_expansions.map((entry, index) => (
            <div key={index} className="text-xs">
              第 {String(entry.step || index + 1)} 步追加 {String(entry.added_count ?? 0)} 个工具
              {entry.truncated ? "（已截断）" : ""}
            </div>
          ))}
        </DecisionSection>
      )}

      <details>
        <summary className="text-xs muted" style={{ cursor: "pointer" }}>技术详情</summary>
        <pre className="text-xs" style={{ maxHeight: 320, overflow: "auto" }}>
          {JSON.stringify(report, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function DecisionSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ borderTop: "1px solid var(--line-2)", paddingTop: 10 }}>
      <div className="text-sm" style={{ fontWeight: 700, marginBottom: 8 }}>{title}</div>
      {children}
    </section>
  );
}

function ChipList({
  values,
  empty,
  kind = "muted",
}: {
  values: string[];
  empty: string;
  kind?: "accent" | "muted";
}) {
  if (!values.length) return <span className="text-sm muted">{empty}</span>;
  return (
    <div className="row-flex" style={{ gap: 4, flexWrap: "wrap" }}>
      {values.map((value) => <Badge key={value} kind={kind}>{value}</Badge>)}
    </div>
  );
}

function retrievalLabel(name: string): string {
  return ({ memory: "记忆", knowledge: "知识", file_evidence: "文件证据" } as Record<string, string>)[name] || name;
}

function statusLabel(status: string): string {
  return ({
    hit: "命中",
    miss: "未命中",
    skipped: "跳过",
    not_applicable: "不适用",
    required: "需要",
    optional: "可选",
    error: "错误",
  } as Record<string, string>)[status] || status;
}

function retrievalKind(status: string): "ok" | "warn" | "err" | "muted" {
  if (status === "hit") return "ok";
  if (status === "miss") return "warn";
  if (status === "error") return "err";
  return "muted";
}
