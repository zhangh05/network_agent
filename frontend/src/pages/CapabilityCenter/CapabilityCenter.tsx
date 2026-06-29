/**
 * CapabilityCenter — business capabilities + canonical tool catalog.
 *
 * 展示可用能力、风险边界；工具目录索引。
 */
import { useMemo, useState } from "react";
import { capabilitiesApi, registryApi, toolsApi } from "../../api";
import { useAsync, AsyncView, Badge, InlineCode } from "../../components/common";
import type { BusinessCapability, CapabilityStatus, RiskLevel, ToolCatalogCategory, ToolCatalogItem, ToolGovernanceStatus } from "../../types";
import { IconBolt, IconShield } from "../../components/Icon";

const S_KIND: Record<CapabilityStatus, "ok" | "muted" | "warn"> = { enabled: "ok", planned: "warn", disabled: "muted" };
const S_LABEL: Record<CapabilityStatus, string> = { enabled: "已启用", planned: "规划中", disabled: "已停用" };
const R_KIND: Record<RiskLevel, "ok" | "info" | "warn" | "err"> = { low: "ok", medium: "info", high: "warn", critical: "err", forbidden: "err" };
const R_LABEL: Record<RiskLevel, string> = { low: "低", medium: "中", high: "高", critical: "严重", forbidden: "禁止" };
const G_KIND: Record<ToolGovernanceStatus, "ok" | "info" | "warn" | "muted"> = { active: "ok", disabled: "info", internal: "info", forbidden: "warn" };

type ToolFilter = "all" | "planner" | "active" | "disabled" | "internal" | "forbidden" | "high" | "host" | "workspace" | "network" | "knowledge";
const T_FILTERS: { id: ToolFilter; label: string }[] = [
  { id: "all", label: "全部" }, { id: "planner", label: "可见" }, { id: "active", label: "活跃" },
  { id: "disabled", label: "停用" }, { id: "internal", label: "内部" }, { id: "forbidden", label: "禁止" },
  { id: "high", label: "高风险" }, { id: "host", label: "Host" }, { id: "workspace", label: "空间" },
  { id: "network", label: "网络" }, { id: "knowledge", label: "知识" },
];

const CAP_TITLES: Record<string, string> = { config_translation: "配置翻译", "config.translate": "配置翻译", knowledge: "知识问答", review: "人工评审", topology: "拓扑分析", inspection: "配置巡检", cmdb: "配置台账", artifact: "制品管理" };

export function CapabilityCenter() {
  const [tq, setTq] = useState("");
  const [tf, setTf] = useState<ToolFilter>("all");
  const list = useAsync<{ capabilities: BusinessCapability[]; enabled: string[] }>((s) => capabilitiesApi.manifest(s));
  const catalog = useAsync((s) => toolsApi.catalog(s));
  const registry = useAsync<{ moduleCount: number; skillCount: number }>(async (s) => {
    const [m, sk] = await Promise.all([registryApi.modules(s), registryApi.skills(s)]) as any;
    return { moduleCount: Array.isArray(m?.modules) ? m.modules.length : 0, skillCount: Array.isArray(sk?.skills) ? sk.skills.length : 0 };
  });

  const counts = useMemo(() => {
    if (list.state.kind !== "success") return { en: 0, pl: 0, tot: 0, hi: 0, dep: 0 };
    const c = list.state.data.capabilities ?? [];
    return { en: c.filter((x) => x.status === "enabled").length, pl: c.filter((x) => x.status === "planned").length, tot: c.length, hi: c.filter((x) => x.risk_level === "high" || x.risk_level === "forbidden").length, dep: c.filter((x) => x.can_generate_deployable).length };
  }, [list.state]);

  return (
    <div className="page" data-testid="page-capabilities">
      <div className="page-header" style={{ background: "var(--surface)" }}>
        <div>
          <h1>能力矩阵<span style={{ color: "var(--ink-mute)", fontWeight: 400, fontSize: 14, marginLeft: 6 }}>· Capabilities</span></h1>
          <p className="subtitle">查看当前可用能力、风险边界和人工复核要求；规划中能力不提供调用入口</p>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
          <span className="status-pill"><span className="dot" style={{ background: "var(--accent)" }} />{counts.tot} 项</span>
          <span className="status-pill"><span className="dot ok" />{counts.en} 启用</span>
          <span className="status-pill"><span className="dot warn" />{counts.pl} 规划中</span>
          {counts.dep > 0 && <span className="status-pill"><IconBolt size={10} />{counts.dep} 涉及产物</span>}
          {registry.state.kind === "success" && (
            <span className="status-pill">{registry.state.data.moduleCount} 模块 · {registry.state.data.skillCount} 能力</span>
          )}
        </div>
      </div>

      <div className="page-body">
        {/* Tool Catalog */}
        <div className="card" style={{ marginBottom: 18 }}>
          <div className="card-title">
            工具目录
            {catalog.state.kind === "success" && <span className="count">{catalog.state.data.count ?? 0}</span>}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
            <span style={{ fontSize: "var(--fs-12)", color: "var(--text-3)", flex: 1, minWidth: 0 }}>
              {catalog.state.kind === "success" && <>Planner 可见 {catalog.state.data.planner_visible_count ?? 0} 个工具</>}
            </span>
            <input className="input" value={tq} onChange={(e) => setTq(e.target.value)} placeholder="搜索 canonical / action…" style={{ maxWidth: 240, height: 30, fontSize: "var(--fs-12)" }} />
          </div>
          <div className="segmented" style={{ marginBottom: 12, flexWrap: "wrap" }}>
            {T_FILTERS.map((f) => (
              <button key={f.id} className={tf === f.id ? "active" : ""} onClick={() => setTf(f.id)} type="button">{f.label}</button>
            ))}
          </div>
          <AsyncView state={catalog.state} onRetry={catalog.reload} emptyText="无工具目录" emptyHint="/api/tools/catalog 未返回数据">
            {(d) => <ToolTree cats={d.categories ?? []} tools={d.tools ?? []} query={tq} filter={tf} />}
          </AsyncView>
        </div>

        {/* Capability cards */}
        <AsyncView state={list.state} onRetry={list.reload} emptyText="无业务能力" emptyHint="agent.capabilities.catalog 未返回能力">
          {(d) => (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 340px), 1fr))", gap: 14 }} data-testid="capability-list">
              {(d.capabilities ?? []).map((cap) => <CapCard key={cap.capability_id} cap={cap} />)}
            </div>
          )}
        </AsyncView>
      </div>
    </div>
  );
}

/* ── Tool tree ── */

function ToolTree({ cats, tools, query, filter }: { cats: ToolCatalogCategory[]; tools: ToolCatalogItem[]; query: string; filter: ToolFilter }) {
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return cats.map((c) => ({
      ...c, groups: c.groups.map((g) => ({
        ...g, tools: g.tools.filter((t) => matchT(t, q) && matchF(t, filter)),
        count: g.tools.filter((t) => matchT(t, q) && matchF(t, filter)).length,
      })).filter((g) => g.tools.length > 0),
    })).filter((c) => c.groups.length > 0);
  }, [cats, query, filter]);

  if (!cats.length) return <div style={{ padding: 20, textAlign: "center", color: "var(--text-3)", fontSize: "var(--fs-12)" }}>暂无目录数据</div>;

  return (
    <div className="tool-tree">
      {filtered.map((c) => (
        <details key={c.id} className="tool-category" open={!query}>
          <summary><span style={{ fontWeight: 720 }}>{c.name}</span><span className="tool-count">{c.count}</span></summary>
          {c.description && <div style={{ fontSize: "var(--fs-11)", color: "var(--text-3)", marginBottom: 6 }}>{c.description}</div>}
          <div className="tool-groups">
            {c.groups.map((g) => (
              <details key={g.id} className="tool-group" open={Boolean(query)}>
                <summary><span>{g.name}</span><span className="tool-count">{g.count}</span></summary>
                <div className="tool-list">
                  {g.tools.map((t) => <TRow key={t.canonical_tool_id} tool={t} />)}
                </div>
              </details>
            ))}
          </div>
        </details>
      ))}
      <details className="collapse">
        <summary style={{ fontSize: "var(--fs-11)", color: "var(--text-4)" }}>Flat debug view</summary>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
          {tools.slice(0, 88).map((t) => <InlineCode key={t.canonical_tool_id}>{t.canonical_tool_id}</InlineCode>)}
        </div>
      </details>
    </div>
  );
}

function TRow({ tool }: { tool: ToolCatalogItem }) {
  const canonicalRefs = tool.capability_actions ?? [];
  return (
    <details className="tool-row">
      <summary>
        <span style={{ fontWeight: 680, fontSize: "var(--fs-12)" }}>{tool.display_name}</span>
        <InlineCode>{tool.canonical_tool_id}</InlineCode>
        {tool.governance_status && <Badge kind={G_KIND[tool.governance_status] ?? "muted"}>{tool.governance_status}</Badge>}
        <Badge kind={R_KIND[tool.risk_level] ?? "muted"}>{R_LABEL[tool.risk_level] ?? tool.risk_level}</Badge>
      </summary>
      <div className="tool-detail-grid">
        <D label="namespace"><InlineCode>{tool.category}/{tool.group}/{tool.action}</InlineCode></D>
        <D label="审批">{tool.requires_approval ? <Badge kind="warn">需要</Badge> : <Badge kind="ok">无需</Badge>}{tool.permission_action && <InlineCode>{tool.permission_action}</InlineCode>}</D>
        <D label="Planner"><Badge kind={tool.planner_visible ? "ok" : "muted"}>{tool.planner_visible ? "visible" : "hidden"}</Badge></D>
        {tool.actions?.length ? <D label="actions">{tool.actions.map((a) => <InlineCode key={a}>{a}</InlineCode>)}</D> : null}
        {tool.allowed_callers?.length ? <D label="callers">{tool.allowed_callers.map((c) => <InlineCode key={c}>{c}</InlineCode>)}</D> : null}
        {canonicalRefs.length > 0 && <D label="canonical refs">{canonicalRefs.map((a) => <InlineCode key={a}>{a}</InlineCode>)}</D>}
        {tool.usage_hint && <D label="使用"><span>{tool.usage_hint}</span></D>}
        {tool.not_for && <D label="禁用"><span>{tool.not_for}</span></D>}
        {tool.description && <D label="描述"><span>{tool.description}</span></D>}
      </div>
    </details>
  );
}

function D({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="tool-detail"><span style={{ fontSize: "var(--fs-10)", color: "var(--text-4)" }}>{label}</span><div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>{children}</div></div>;
}

/* ── Capability card ── */

function CapCard({ cap }: { cap: BusinessCapability }) {
  const isPlanned = cap.status === "planned";
  const title = CAP_TITLES[cap.capability_id] || cap.description?.split(/[.。]/)[0] || cap.capability_id;
  const outcome = isPlanned ? "规划中，当前不可调用" : cap.can_generate_deployable ? "会产出配置材料，必须人工复核" : cap.requires_verification ? "结果需要人工确认后使用" : "可用于当前工作区的辅助分析";

  return (
    <div className="card" data-testid={`cap-${cap.capability_id}`} data-status={cap.status}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
        <div style={{ minWidth: 0 }}>
          <h4 style={{ fontSize: "var(--fs-15)", fontWeight: 740, margin: 0 }}>{title}</h4>
          <div style={{ fontSize: "var(--fs-11)", color: "var(--text-4)", marginTop: 3 }}>{outcome}</div>
        </div>
        <Badge kind={S_KIND[cap.status]} withDot>{S_LABEL[cap.status] || cap.status}</Badge>
        {isPlanned && <span data-testid={`cap-planned-tag-${cap.capability_id}`} style={{ display: "none" }}>不可调用</span>}
      </div>

      {cap.description && <div style={{ marginTop: 12, fontSize: "var(--fs-13)", color: "var(--text-2)", lineHeight: 1.6 }}>{cap.description}</div>}

      {/* Safety */}
      <div className="card-title" style={{ marginTop: 14 }}><IconShield size={11} /> 使用边界</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 20px" }}>
        <SR label="风险等级">{<Badge kind={R_KIND[cap.risk_level]}>{R_LABEL[cap.risk_level]}</Badge>}</SR>
        <SR label="配置产物">{cap.can_generate_deployable ? <Badge kind="warn">需复核</Badge> : <Badge kind="ok" withDot>不产生</Badge>}</SR>
        <SR label="评审要求">{cap.requires_verification ? <Badge kind="warn">需要</Badge> : <Badge kind="ok" withDot>无需</Badge>}</SR>
        <SR label="LLM 调用">{cap.enabled ? <Badge kind="ok" withDot>可</Badge> : <Badge kind="muted">否</Badge>}</SR>
      </div>

      <details className="collapse" style={{ marginTop: 10 }}>
        <summary style={{ fontSize: "var(--fs-11)", color: "var(--text-4)", cursor: "pointer" }}>技术详情</summary>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
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

function SR({ label, children }: { label: string; children: React.ReactNode }) {
  return <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "var(--fs-12)" }}><span style={{ color: "var(--text-3)", flexShrink: 0, minWidth: 56 }}>{label}</span>{children}</div>;
}

/* ── Tool filter/matcher ── */

function matchT(t: ToolCatalogItem, q: string): boolean {
  if (!q) return true;
  return [
    t.display_name,
    t.canonical_tool_id,
    t.category,
    t.group,
    t.action,
    t.governance_status ?? "",
    ...(t.actions ?? []),
    ...(t.capability_actions ?? []),
    t.usage_hint ?? "",
    t.not_for ?? "",
    t.description ?? "",
  ].some((v) => String(v ?? "").toLowerCase().includes(q));
}

function matchF(t: ToolCatalogItem, f: ToolFilter): boolean {
  if (f === "planner") return Boolean(t.planner_visible);
  if (f === "active") return t.governance_status === "active";
  if (f === "disabled") return t.governance_status === "disabled";
  if (f === "internal") return t.governance_status === "internal";
  if (f === "forbidden") return t.governance_status === "forbidden";
  if (f === "high") return t.risk_level === "high" || t.requires_approval;
  if (f === "host" || f === "workspace" || f === "network" || f === "knowledge") return t.category === f;
  return true;
}
