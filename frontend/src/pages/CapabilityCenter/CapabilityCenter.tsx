import { capabilitiesApi } from "../../api";
import { useAsync, AsyncView, Badge, InlineCode } from "../../components/common";
import type { CapabilityManifest, CapabilityStatus, RiskLevel } from "../../types";

const STATUS_KIND: Record<CapabilityStatus, "ok" | "planned" | "muted"> = {
  enabled: "ok",
  planned: "planned",
  disabled: "muted",
};

const RISK_KIND: Record<RiskLevel, "ok" | "info" | "warn" | "err"> = {
  low: "ok",
  medium: "info",
  high: "warn",
  forbidden: "err",
};

/**
 * Capability Center — dynamically reads CapabilityManifest.
 * Planned capabilities are SHOWN with their status; NO invoke
 * button is rendered (per spec).
 */
export function CapabilityCenter() {
  const list = useAsync<{ capabilities: CapabilityManifest[] }>((s) =>
    capabilitiesApi.manifest(s),
  );

  return (
    <div
      style={{ display: "flex", flexDirection: "column", height: "100%" }}
      data-testid="page-capabilities"
    >
      <div className="page-header">
        <div>
          <h1>Capability Center</h1>
          <div className="subtitle">
            从后端 CapabilityManifest 动态读取 · planned capability 仅展示状态，不提供调用入口
          </div>
        </div>
      </div>
      <div style={{ padding: 16, overflowY: "auto", flex: 1 }}>
        <AsyncView
          state={list.state}
          onRetry={list.reload}
          emptyText="后端无 capabilities"
          emptyHint="CapabilityRegistry 未注册任何 capability"
        >
          {(d) => (
            <div data-testid="capability-list">
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
    <div className="cap-card" data-testid={`cap-${cap.capability_id}`} data-status={cap.status}>
      <div className="cap-head">
        <div>
          <h3>{cap.name || cap.capability_id}</h3>
          <div className="cap-id mono">{cap.capability_id}</div>
        </div>
        <div className="row-flex" data-testid={`cap-status-${cap.capability_id}`}>
          <Badge kind={STATUS_KIND[cap.status]} withDot>
            {cap.status}
          </Badge>
          {/* planned: NO invoke button per spec */}
          {isPlanned && (
            <span className="text-xs muted" data-testid={`cap-planned-tag-${cap.capability_id}`}>
              (not callable)
            </span>
          )}
        </div>
      </div>
      {cap.description && <div className="cap-desc">{cap.description}</div>}

      <div className="card-title" style={{ marginTop: 12 }}>Module</div>
      <div className="text-sm">
        <InlineCode>{cap.module.module_id || "(none)"}</InlineCode>{" "}
        <Badge kind={STATUS_KIND[cap.module.status]}>{cap.module.status}</Badge>
        {cap.module.service_path && (
          <div className="text-xs muted">{cap.module.service_path}</div>
        )}
      </div>

      <div className="card-title" style={{ marginTop: 12 }}>Skills</div>
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

      <div className="card-title" style={{ marginTop: 12 }}>Tools</div>
      {cap.tools.length === 0 ? (
        <div className="muted text-sm">无 tool</div>
      ) : (
        <table className="tbl" data-testid={`cap-tools-${cap.capability_id}`}>
          <thead>
            <tr>
              <th>tool_id</th>
              <th>status</th>
              <th>callable_by_llm</th>
              <th>risk</th>
            </tr>
          </thead>
          <tbody>
            {cap.tools.map((t) => (
              <tr key={t.tool_id} data-testid={`cap-tool-${cap.capability_id}-${t.tool_id}`}>
                <td><InlineCode>{t.tool_id}</InlineCode></td>
                <td><Badge kind={STATUS_KIND[t.status as CapabilityStatus]}>{t.status}</Badge></td>
                <td>
                  {t.callable_by_llm
                    ? <Badge kind="ok">true</Badge>
                    : <Badge kind="muted">false</Badge>}
                </td>
                <td><Badge kind={RISK_KIND[t.risk_level]}>{t.risk_level}</Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="card-title" style={{ marginTop: 12 }}>Safety</div>
      <div className="text-sm" data-testid={`cap-safety-${cap.capability_id}`}>
        <div>real_device_access: {renderBool(cap.safety.real_device_access)}</div>
        <div>allows_config_push: {renderBool(cap.safety.allows_config_push)}</div>
        <div>produces_deployable_config: {renderBool(cap.safety.produces_deployable_config)}</div>
        <div>may_fabricate_sources: {renderBool(cap.safety.may_fabricate_sources)}</div>
        <div>requires_human_review: {renderBool(cap.safety.requires_human_review)}</div>
        {cap.safety.notes && (
          <div className="text-xs muted mt-2">notes: {cap.safety.notes}</div>
        )}
      </div>
    </div>
  );
}

function renderBool(b: boolean) {
  return b ? <Badge kind="warn">true</Badge> : <Badge kind="ok">false</Badge>;
}
