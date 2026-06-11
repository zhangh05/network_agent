import { useMemo } from "react";
import { capabilitiesApi } from "../../api";
import { useAsync, AsyncView, Badge, InlineCode } from "../../components/common";
import type { CapabilityManifest, CapabilityStatus, RiskLevel } from "../../types";
import { IconBolt, IconLayers, IconShield, IconSparkle } from "../../components/Icon";

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

export function CapabilityCenter() {
  const list = useAsync<{ capabilities: CapabilityManifest[]; enabled: string[] }>((s) =>
    capabilitiesApi.manifest(s),
  );

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
            从后端 CapabilityRegistry 动态读取 · 规划中 capability 仅展示状态，<strong>不</strong>提供调用入口
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
            <IconBolt size={10} /> 可下发 {counts.deployable}
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
                gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))",
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
            {cap.capability_id}
          </h3>
          {cap.intent && (
            <div className="mono text-xs muted">intent: {cap.intent}</div>
          )}
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

      {/* Module + Skill */}
      <div className="card-title" style={{ marginTop: 14 }}>
        <IconLayers size={11} /> Module &amp; Skill
      </div>
      <div className="row-flex" style={{ gap: 6, flexWrap: "wrap" }}>
        <InlineCode>{cap.module}</InlineCode>
        <span className="muted text-xs">·</span>
        <InlineCode>{cap.skill}</InlineCode>
      </div>
      {cap.category && (
        <div className="text-xs muted mt-2">
          分类: <Badge kind="muted">{cap.category}</Badge>
        </div>
      )}

      {/* Safety / risk */}
      <div className="card-title" style={{ marginTop: 14 }}>
        <IconShield size={11} /> Safety
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
        <SafetyRow label="可下发配置">
          {cap.can_generate_deployable ? (
            <Badge kind="warn">true</Badge>
          ) : (
            <Badge kind="ok" withDot>无</Badge>
          )}
        </SafetyRow>
        <SafetyRow label="需要评审">
          {cap.requires_verification ? (
            <Badge kind="warn">true</Badge>
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

      {/* 装饰：规划中 capability 的禁止调用视觉提示 */}
      {isPlanned && (
        <div
          style={{
            position: "absolute",
            top: 8,
            right: 8,
            fontSize: 10,
            color: "var(--warning)",
            opacity: 0.4,
            pointerEvents: "none",
          }}
          aria-hidden
        >
          <IconSparkle size={32} />
        </div>
      )}
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
