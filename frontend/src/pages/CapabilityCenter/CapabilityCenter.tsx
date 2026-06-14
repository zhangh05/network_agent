import { useMemo, useState } from "react";
import { capabilitiesApi, registryApi, toolsApi } from "../../api";
import { useAsync, AsyncView, Badge, InlineCode } from "../../components/common";
import type {
  CapabilityManifest,
  CapabilityStatus,
  RiskLevel,
  ToolCatalogCategory,
  ToolCatalogItem,
  ToolGovernanceStatus,
} from "../../types";
import { IconBolt, IconShield } from "../../components/Icon";

const STATUS_KIND: Record<CapabilityStatus, "ok" | "muted" | "warn"> = {
  enabled: "ok",
  planned: "warn",
  disabled: "muted",
};

const STATUS_LABEL: Record<CapabilityStatus, string> = {
  enabled: "已启用",
  planned: "规划中",
  disabled: "已停用",
};

const RISK_KIND: Record<RiskLevel, "ok" | "info" | "warn" | "err"> = {
  low: "ok",
  medium: "info",
  high: "warn",
  forbidden: "err",
};

const RISK_LABEL: Record<RiskLevel, string> = {
  low: "低",
  medium: "中",
  high: "高",
  forbidden: "禁止",
};

type ToolFilter = "all" | "planner" | "deprecated" | "alias" | "high" | "host" | "workspace" | "network" | "knowledge";

const TOOL_FILTERS: Array<{ id: ToolFilter; label: string }> = [
  { id: "all", label: "All" },
  { id: "planner", label: "Planner-visible" },
  { id: "deprecated", label: "Deprecated" },
  { id: "alias", label: "Alias/Merged" },
  { id: "high", label: "High risk" },
  { id: "host", label: "Host" },
  { id: "workspace", label: "Workspace" },
  { id: "network", label: "Network" },
  { id: "knowledge", label: "Knowledge" },
];

const GOVERNANCE_KIND: Record<ToolGovernanceStatus, "ok" | "info" | "warn" | "muted"> = {
  keep: "ok",
  alias: "info",
  merged: "info",
  deprecated: "warn",
  removed_candidate: "muted",
};

interface RegistrySummary {
  moduleCount: number;
  skillCount: number;
}

export function CapabilityCenter() {
  const [toolQuery, setToolQuery] = useState("");
  const [toolFilter, setToolFilter] = useState<ToolFilter>("all");
  const list = useAsync<{ capabilities: CapabilityManifest[]; enabled: string[] }>((s) =>
    capabilitiesApi.manifest(s),
  );
  const catalog = useAsync((s) => toolsApi.catalog(s));
  const registry = useAsync<RegistrySummary>(async (s) => {
    const [modules, skills] = await Promise.all([
      registryApi.modules(s),
      registryApi.skills(s),
      registryApi.status(s),
    ]);
    return {
      moduleCount: Array.isArray(modules.modules) ? modules.modules.length : 0,
      skillCount: Array.isArray(skills.skills) ? skills.skills.length : 0,
    };
  });

  const counts = useMemo(() => {
    if (list.state.kind !== "success") {
      return { enabled: 0, planned: 0, total: 0, high: 0, deployable: 0 };
    }
    const caps = list.state.data.capabilities ?? [];
    return {
      enabled: caps.filter((c) => c.status === "enabled").length,
      planned: caps.filter((c) => c.status === "planned").length,
      total: caps.length,
      high: caps.filter((c) => c.risk_level === "high" || c.risk_level === "forbidden").length,
      deployable: caps.filter((c) => c.can_generate_deployable).length,
    };
  }, [list.state]);

  return (
    <div className="page" data-testid="page-capabilities">
      <div className="page-header">
        <div>
          <h1>
            能力矩阵{" "}
            <span style={{ color: "var(--ink-mute)", fontWeight: 400, fontSize: 14 }}>
              · Capability Manifest
            </span>
          </h1>
          <div className="subtitle">
            查看当前可用能力、风险边界和人工复核要求；规划中能力仅展示状态，<strong>不</strong>提供调用入口
          </div>
        </div>
        <div className="row-flex" style={{ gap: 6, flexWrap: "wrap" }}>
          <span className="status-pill" data-testid="cap-count-total">
            <span className="dot" />
            全部 {counts.total}
          </span>
          <span className="status-pill" data-testid="cap-count-enabled">
            <span className="dot" style={{ background: "var(--success)" }} />
            已启用 {counts.enabled}
          </span>
          <span className="status-pill" data-testid="cap-count-planned">
            <span className="dot warn" />
            规划中 {counts.planned}
          </span>
          <span className="status-pill" data-testid="cap-count-deployable">
            <IconBolt size={10} /> 涉及配置产物 {counts.deployable}
          </span>
          {registry.state.kind === "success" && (
            <span className="status-pill" data-testid="registry-counts">
              Registry {registry.state.data.moduleCount} / {registry.state.data.skillCount}
            </span>
          )}
        </div>
      </div>
      <div className="page-body">
        <div className="card" data-testid="tool-catalog-tree">
          <div className="card-title">
            工具目录
            {catalog.state.kind === "success" && (
              <span className="count">{catalog.state.data.count ?? 0}</span>
            )}
          </div>
          <div className="row-flex" style={{ justifyContent: "space-between", gap: 10 }}>
            <div className="text-sm muted">
              Canonical 工具按大类和小类展示，execution id 继续保持兼容。
              {catalog.state.kind === "success" && (
                <> Planner-visible {catalog.state.data.planner_visible_count ?? 0}</>
              )}
            </div>
            <input
              className="input"
              value={toolQuery}
              onChange={(e) => setToolQuery(e.target.value)}
              placeholder="搜索 canonical / alias / hint"
              aria-label="搜索工具目录"
              style={{ maxWidth: 280 }}
            />
          </div>
          <div className="row-flex mt-2" style={{ gap: 6, flexWrap: "wrap" }}>
            {TOOL_FILTERS.map((filter) => (
              <button
                key={filter.id}
                className="btn-sm"
                onClick={() => setToolFilter(filter.id)}
                style={{
                  background: toolFilter === filter.id ? "var(--accent)" : "var(--bg-secondary)",
                  color: toolFilter === filter.id ? "#fff" : "var(--text-primary)",
                }}
              >
                {filter.label}
              </button>
            ))}
          </div>
          <AsyncView
            state={catalog.state}
            onRetry={catalog.reload}
            emptyText="后端无工具目录"
            emptyHint="/api/tools/catalog 未返回 categories"
          >
            {(d) => (
              <ToolCatalogTree
                categories={d.categories ?? []}
                tools={d.tools ?? []}
                query={toolQuery}
                filter={toolFilter}
              />
            )}
          </AsyncView>
        </div>

        <AsyncView
          state={list.state}
          onRetry={list.reload}
          emptyText="后端无 capabilities"
          emptyHint="CapabilityRegistry 未注册任何 capability"
        >
          {(d) => (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 320px), 1fr))",
                gap: 14,
              }}
              data-testid="capability-list"
            >
              {(d.capabilities ?? []).map((cap) => (
                <CapabilityCard key={cap.capability_id} cap={cap} />
              ))}
            </div>
          )}
        </AsyncView>
      </div>
    </div>
  );
}

function ToolCatalogTree({
  categories,
  tools,
  query,
  filter,
}: {
  categories: ToolCatalogCategory[];
  tools: ToolCatalogItem[];
  query: string;
  filter: ToolFilter;
}) {
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return categories
      .map((category) => ({
        ...category,
        groups: category.groups
          .map((group) => ({
            ...group,
            tools: group.tools.filter((tool) => matchesTool(tool, q) && matchesFilter(tool, filter)),
            count: group.tools.filter((tool) => matchesTool(tool, q) && matchesFilter(tool, filter)).length,
          }))
          .filter((group) => group.tools.length > 0),
      }))
      .filter((category) => category.groups.length > 0);
  }, [categories, query, filter]);

  if (!categories.length) {
    return <div className="empty compact">暂无目录数据</div>;
  }

  return (
    <div className="tool-tree">
      {filtered.map((category) => (
        <details key={category.id} className="tool-category" open={!query}>
          <summary>
            <span>{category.name}</span>
            <span className="tool-count">{category.count}</span>
          </summary>
          {category.description && <div className="text-xs muted">{category.description}</div>}
          <div className="tool-groups">
            {category.groups.map((group) => (
              <details key={group.id} className="tool-group" open={Boolean(query)}>
                <summary>
                  <span>{group.name}</span>
                  <span className="tool-count">{group.count}</span>
                </summary>
                <div className="tool-list">
                  {group.tools.map((tool) => (
                    <ToolCatalogRow key={tool.canonical_tool_id} tool={tool} />
                  ))}
                </div>
              </details>
            ))}
          </div>
        </details>
      ))}
      <details className="collapse">
        <summary>Flat debug view</summary>
        <div className="row-flex mt-2" style={{ gap: 6, flexWrap: "wrap" }}>
          {tools.slice(0, 88).map((tool) => (
            <InlineCode key={tool.canonical_tool_id}>{tool.canonical_tool_id}</InlineCode>
          ))}
        </div>
      </details>
    </div>
  );
}

function ToolCatalogRow({ tool }: { tool: ToolCatalogItem }) {
  return (
    <details className="tool-row">
      <summary>
        <span className="tool-label">{tool.short_label || tool.display_name}</span>
        <InlineCode>{tool.canonical_tool_id}</InlineCode>
        {tool.governance_status && (
          <Badge kind={GOVERNANCE_KIND[tool.governance_status] ?? "muted"}>
            {tool.governance_status}
          </Badge>
        )}
        <Badge kind={RISK_KIND[tool.risk_level] ?? "muted"}>{RISK_LABEL[tool.risk_level] ?? tool.risk_level}</Badge>
      </summary>
      <div className="tool-detail-grid">
        <Detail label="execution">
          <InlineCode>{tool.execution_tool_id}</InlineCode>
        </Detail>
        <Detail label="aliases">
          {(tool.legacy_tool_ids ?? []).map((id) => (
            <InlineCode key={id}>{id}</InlineCode>
          ))}
        </Detail>
        <Detail label="namespace">
          <InlineCode>{tool.category}/{tool.group}/{tool.action}</InlineCode>
        </Detail>
        <Detail label="approval">
          {tool.requires_approval ? <Badge kind="warn">需要</Badge> : <Badge kind="ok">无需</Badge>}
          {tool.permission_action && <InlineCode>{tool.permission_action}</InlineCode>}
        </Detail>
        <Detail label="planner">
          <Badge kind={tool.planner_visible ? "ok" : "muted"}>
            {tool.planner_visible ? "visible" : "hidden"}
          </Badge>
        </Detail>
        {tool.replacement && (
          <Detail label="replacement">
            <InlineCode>{tool.replacement}</InlineCode>
          </Detail>
        )}
        {tool.overlap_group && (
          <Detail label="overlap">
            <InlineCode>{tool.overlap_group}</InlineCode>
          </Detail>
        )}
        <Detail label="usage">
          <span>{tool.usage_hint}</span>
        </Detail>
        <Detail label="not for">
          <span>{tool.not_for}</span>
        </Detail>
      </div>
    </details>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="tool-detail">
      <span className="muted">{label}</span>
      <div className="row-flex" style={{ gap: 6, flexWrap: "wrap" }}>{children}</div>
    </div>
  );
}

function matchesTool(tool: ToolCatalogItem, q: string): boolean {
  if (!q) return true;
  return [
    tool.display_name,
    tool.short_label,
    tool.canonical_tool_id,
    tool.execution_tool_id,
    ...(tool.legacy_tool_ids ?? []),
    tool.usage_hint,
    tool.governance_status ?? "",
    tool.replacement ?? "",
    tool.overlap_group ?? "",
  ].some((value) => String(value ?? "").toLowerCase().includes(q));
}

function matchesFilter(tool: ToolCatalogItem, filter: ToolFilter): boolean {
  switch (filter) {
    case "planner":
      return Boolean(tool.planner_visible);
    case "deprecated":
      return tool.governance_status === "deprecated" || tool.governance_status === "removed_candidate";
    case "alias":
      return tool.governance_status === "alias" || tool.governance_status === "merged";
    case "high":
      return tool.risk_level === "high" || tool.requires_approval;
    case "host":
    case "workspace":
    case "network":
    case "knowledge":
      return tool.category === filter;
    default:
      return true;
  }
}

function CapabilityCard({ cap }: { cap: CapabilityManifest }) {
  const isPlanned = cap.status === "planned";
  return (
    <div
      className="card"
      data-testid={`cap-${cap.capability_id}`}
      data-status={cap.status}
      style={{ marginBottom: 0, position: "relative" }}
    >
      {/* 标题区 */}
      <div
        className="row-flex"
        style={{ justifyContent: "space-between", alignItems: "flex-start" }}
      >
        <div style={{ minWidth: 0 }}>
          <h3
            style={{
              fontFamily: "var(--font-display)",
              fontSize: 15,
              margin: 0,
              marginBottom: 2,
            }}
          >
            {capabilityTitle(cap)}
          </h3>
          <div className="text-xs muted">{capabilityOutcome(cap)}</div>
        </div>
        <div
          className="row-flex"
          data-testid={`cap-status-${cap.capability_id}`}
          style={{ flexShrink: 0 }}
        >
          <Badge kind={STATUS_KIND[cap.status]} withDot>
            {STATUS_LABEL[cap.status] || cap.status}
          </Badge>
          {isPlanned && (
            <span
              className="text-xs muted"
              data-testid={`cap-planned-tag-${cap.capability_id}`}
            >
              (不可调用)
            </span>
          )}
        </div>
      </div>

      {cap.description && (
        <div
          className="text-sm"
          style={{ marginTop: 10, color: "var(--ink-soft)", lineHeight: 1.6 }}
        >
          {cap.description}
        </div>
      )}

      {/* Safety / risk */}
      <div className="card-title" style={{ marginTop: 14 }}>
        <IconShield size={11} /> 使用边界
      </div>
      <div
        data-testid={`cap-safety-${cap.capability_id}`}
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: "4px 16px",
        }}
      >
        <SafetyRow label="风险等级">
          <Badge kind={RISK_KIND[cap.risk_level]}>
            {RISK_LABEL[cap.risk_level]}
          </Badge>
        </SafetyRow>
        <SafetyRow label="配置产物">
          {cap.can_generate_deployable ? (
            <Badge kind="warn">需复核</Badge>
          ) : (
            <Badge kind="ok" withDot>不产生命令</Badge>
          )}
        </SafetyRow>
        <SafetyRow label="需要评审">
          {cap.requires_verification ? (
            <Badge kind="warn">需要</Badge>
          ) : (
            <Badge kind="ok" withDot>无需</Badge>
          )}
        </SafetyRow>
        <SafetyRow label="LLM 可调用">
          {cap.enabled ? (
            <Badge kind="ok" withDot>可</Badge>
          ) : (
            <Badge kind="muted">否</Badge>
          )}
        </SafetyRow>
      </div>

      <details className="collapse mt-3">
        <summary className="text-xs muted">技术详情</summary>
        <div className="row-flex mt-2" style={{ gap: 6, flexWrap: "wrap" }}>
          <InlineCode>{cap.capability_id}</InlineCode>
          <InlineCode>{cap.intent}</InlineCode>
          <InlineCode>{cap.module}</InlineCode>
          <InlineCode>{cap.skill}</InlineCode>
          {cap.category && <Badge kind="muted">{cap.category}</Badge>}
        </div>
      </details>

    </div>
  );
}

function SafetyRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div
      className="row-flex"
      style={{ gap: 6, fontSize: 12, alignItems: "center" }}
    >
      <span className="muted" style={{ flexShrink: 0 }}>{label}</span>
      {children}
    </div>
  );
}

function capabilityTitle(cap: CapabilityManifest): string {
  const labels: Record<string, string> = {
    config_translation: "配置翻译",
    "config.translate": "配置翻译",
    knowledge: "知识问答",
    review: "人工评审",
    topology: "拓扑分析",
    inspection: "配置巡检",
    cmdb: "配置台账",
  };
  return labels[cap.capability_id] ?? cap.description?.split(/[.。]/)[0] ?? cap.capability_id;
}

function capabilityOutcome(cap: CapabilityManifest): string {
  if (cap.status === "planned") return "规划中，当前不可调用";
  if (cap.can_generate_deployable) return "会产出配置材料，必须人工复核";
  if (cap.requires_verification) return "结果需要人工确认后使用";
  return "可用于当前工作区的辅助分析";
}
