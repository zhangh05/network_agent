import { capabilitiesApi } from "../../api";
import { useAsync, AsyncView, Badge, InlineCode } from "../../components/common";
import type { CapabilityManifest, CapabilityStatus, RiskLevel } from "../../types";
import { IconBolt, IconLayers, IconShield } from "../../components/Icon";

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

const SAFETY_LABEL: Record<keyof CapabilityManifest["safety"], string> = {
  real_device_access: "真实设备访问",
  allows_config_push: "允许 config.push",
  produces_deployable_config: "产生可下发配置",
  may_fabricate_sources: "可能伪造来源",
  requires_human_review: "需要人工评审",
  notes: "备注",
};

export function CapabilityCenter() {
  const list = useAsync<{ capabilities: CapabilityManifest[] }>((s) =>
    capabilitiesApi.manifest(s),
  );

  const caps = list.state.kind === "success" ? list.state.data.capabilities ?? [] : [];
  const enabledCount = caps.filter((c) => c.status === "enabled").length;
  const plannedCount = caps.filter((c) => c.status === "planned").length;
  const toolCount = caps.reduce((s, c) => s + (c.tools?.length ?? 0), 0);

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
            从后端 CapabilityRegistry 动态读取 · 规划中 capability 仅展示状态，<strong>不</strong>提供调用入口
          </div>
        </div>
        <div className="row-flex" style={{ gap: 6 }}>
          <span className="status-pill" data-testid="cap-count-enabled">
            <span className="dot" />
            已启用 {enabledCount}
          </span>
          <span className="status-pill" data-testid="cap-count-planned">
            <span className="dot warn" />
            规划中 {plannedCount}
          </span>
          <span className="status-pill" data-testid="cap-count-tools">
            <IconBolt size={10} /> 工具 {toolCount}
          </span>
        </div>
      </div>
      <div className="page-body">
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
                gridTemplateColumns: "repeat(auto-fill, minmax(380px, 1fr))",
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

function CapabilityCard({ cap }: { cap: CapabilityManifest }) {
  const isPlanned = cap.status === "planned";
  return (
    <div
      className="card"
      data-testid={`cap-${cap.capability_id}`}
      data-status={cap.status}
      style={{ marginBottom: 0 }}
    >
      <div className="row-flex" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ minWidth: 0 }}>
          <h3
            style={{
              fontFamily: "var(--font-display)",
              fontSize: 15,
              margin: 0,
            }}
          >
            {cap.name || cap.capability_id}
          </h3>
          <div className="mono text-xs muted" style={{ marginTop: 2 }}>
            {cap.capability_id}
          </div>
        </div>
        <div
          className="row-flex"
          data-testid={`cap-status-${cap.capability_id}`}
          style={{ flexShrink: 0 }}
        >
          <Badge kind={STATUS_KIND[cap.status]} withDot>
            {STATUS_LABEL[cap.status]}
          </Badge>
          {isPlanned && (
            <span className="text-xs muted" data-testid={`cap-planned-tag-${cap.capability_id}`}>
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

      <div className="card-title" style={{ marginTop: 14 }}>
        <IconLayers size={11} />
        Module
      </div>
      <div className="text-sm row-flex" style={{ gap: 6 }}>
        <InlineCode>{cap.module.module_id || "(none)"}</InlineCode>
        <Badge kind={STATUS_KIND[cap.module.status]}>
          {STATUS_LABEL[cap.module.status] || cap.module.status}
        </Badge>
      </div>
      {cap.module.service_path && (
        <div className="text-xs muted" style={{ marginTop: 4 }}>
          {cap.module.service_path}
        </div>
      )}

      <div className="card-title" style={{ marginTop: 14 }}>
        Skills · {cap.skills.length}
      </div>
      {cap.skills.length === 0 ? (
        <div className="muted text-sm">无 skill</div>
      ) : (
        <div className="row-flex" style={{ flexWrap: "wrap", gap: 4 }}>
          {cap.skills.map((s) => (
            <Badge key={s.skill_id} kind={STATUS_KIND[s.status]}>
              {s.skill_id}
            </Badge>
          ))}
        </div>
      )}

      <div className="card-title" style={{ marginTop: 14 }}>
        <IconBolt size={11} />
        Tools · {cap.tools.length}
      </div>
      {cap.tools.length === 0 ? (
        <div className="muted text-sm">无 tool</div>
      ) : (
        <table
          className="tbl"
          data-testid={`cap-tools-${cap.capability_id}`}
          style={{ fontSize: 12 }}
        >
          <thead>
            <tr>
              <th>tool</th>
              <th>状态</th>
              <th>LLM 可调用</th>
              <th>风险</th>
            </tr>
          </thead>
          <tbody>
            {cap.tools.map((t) => (
              <tr key={t.tool_id} data-testid={`cap-tool-${cap.capability_id}-${t.tool_id}`}>
                <td><InlineCode>{t.tool_id}</InlineCode></td>
                <td>
                  <Badge kind={STATUS_KIND[t.status as CapabilityStatus]}>
                    {STATUS_LABEL[t.status as CapabilityStatus] || t.status}
                  </Badge>
                </td>
                <td>
                  {t.callable_by_llm ? (
                    <Badge kind="ok">是</Badge>
                  ) : (
                    <Badge kind="muted">否</Badge>
                  )}
                </td>
                <td>
                  <Badge kind={RISK_KIND[t.risk_level]}>
                    {RISK_LABEL[t.risk_level]}
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="card-title" style={{ marginTop: 14 }}>
        <IconShield size={11} />
        Safety
      </div>
      <div
        className="text-sm"
        data-testid={`cap-safety-${cap.capability_id}`}
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: "4px 16px",
        }}
      >
        {(
          [
            ["real_device_access", cap.safety.real_device_access],
            ["allows_config_push", cap.safety.allows_config_push],
            ["produces_deployable_config", cap.safety.produces_deployable_config],
            ["may_fabricate_sources", cap.safety.may_fabricate_sources],
            ["requires_human_review", cap.safety.requires_human_review],
          ] as Array<[keyof CapabilityManifest["safety"], boolean]>
        ).map(([key, val]) => (
          <div key={key} className="row-flex" style={{ gap: 6, fontSize: 12 }}>
            {renderBool(val)}
            <span className="muted">{SAFETY_LABEL[key]}</span>
          </div>
        ))}
      </div>
      {cap.safety.notes && (
        <div
          className="text-xs muted mt-2"
          style={{
            padding: "6px 10px",
            background: "var(--bg-soft)",
            borderRadius: "var(--r-sm)",
            fontStyle: "italic",
          }}
        >
          备注：{cap.safety.notes}
        </div>
      )}
    </div>
  );
}

function renderBool(b: boolean) {
  return b ? (
    <Badge kind="warn">true</Badge>
  ) : (
    <Badge kind="ok" withDot>
      false
    </Badge>
  );
}
