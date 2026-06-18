/**
 * Diagnostics — system health & observability dashboard.
 *
 * Layout: runtime health bar → selfcheck issues → usage stats →
 *         prompts table → retention/archive policies.
 */

import { useEffect, useRef, useState } from "react";
import { runtimeApi, agentUsageApi, retentionApi, archiveApi, contextApi, promptsApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { LoadingState } from "../../components/common";
import { IconAlert, IconCheck, IconRefresh, IconShield, IconClock, IconBolt } from "../../components/Icon";

/* ──────────────────────── Types ──────────────────────── */

interface ComponentHealth {
  name: string;
  status: "ok" | "warning" | "error";
  message: string;
  details?: Record<string, unknown>;
}

interface RuntimeHealth {
  components: ComponentHealth[];
  summary: { ok: number; warning: number; error: number; total: number };
}

interface SelfcheckIssue {
  code: string;
  severity: string;
  message: string;
  suggested_action?: string;
}

interface SelfcheckResult {
  checks: Record<string, string>;
  issues: SelfcheckIssue[];
  status: string;
}

interface UsageStats {
  call_count: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
  last_updated: string;
}

export function Diagnostics() {
  const currentWorkspaceId = useSessionStore((s) => s.currentWorkspaceId);
  const [health, setHealth] = useState<RuntimeHealth | null>(null);
  const [selfcheck, setSelfcheck] = useState<SelfcheckResult | null>(null);
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const [contextOk, setContextOk] = useState<boolean | null>(null);
  const [prompts, setPrompts] = useState<Array<{ prompt_id: string; version: string; task: string; description: string; status: string }> | null>(null);
  const [retention, setRetention] = useState<{ policy: Record<string, unknown>; candidate_counts: Record<string, number> } | null>(null);
  const [archive, setArchive] = useState<{ policy: Record<string, unknown> } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const mountedRef = useRef(true);
  const seqRef = useRef(0);

  const loadAll = async () => {
    const seq = ++seqRef.current;
    setLoading(true);
    setError(false);
    const ctrl = new AbortController();
    const wsId = currentWorkspaceId || "default";
    try {
      const [rh, sc, us, cs, pr, rp, ap] = await Promise.allSettled([
        runtimeApi.health(ctrl.signal),
        runtimeApi.selfcheck(ctrl.signal),
        agentUsageApi.get(ctrl.signal),
        contextApi.status(ctrl.signal),
        promptsApi.list(ctrl.signal),
        retentionApi.preview(wsId, ctrl.signal),
        archiveApi.preview(wsId, ctrl.signal),
      ]);
      if (!mountedRef.current || seq !== seqRef.current) return;
      if (rh.status === "fulfilled") setHealth(rh.value as RuntimeHealth);
      if (sc.status === "fulfilled") setSelfcheck(sc.value as SelfcheckResult);
      if (us.status === "fulfilled") setUsage(us.value.usage as unknown as UsageStats);
      if (cs.status === "fulfilled") setContextOk((cs.value as { context_runtime_enabled: boolean }).context_runtime_enabled);
      if (pr.status === "fulfilled") setPrompts((pr.value as { prompts: Array<{ prompt_id: string; version: string; task: string; description: string; status: string }> }).prompts);
      if (rp.status === "fulfilled") setRetention(rp.value as unknown as { policy: Record<string, unknown>; candidate_counts: Record<string, number> });
      if (ap.status === "fulfilled") setArchive(ap.value as unknown as { policy: Record<string, unknown> });
      // allSettled never rejects; track rejection count for error state
      const rejected = [rh, sc, us, cs, pr, rp, ap].filter((r) => r.status === "rejected").length;
      if (rejected > 0 && mountedRef.current && seq === seqRef.current) {
        setError(false); // partial data is ok, show what we have
      }
    } catch {
      // Guard against unexpected synchronous errors
      if (mountedRef.current && seq === seqRef.current) setError(true);
    }
    if (mountedRef.current && seq === seqRef.current) setLoading(false);
  };

  useEffect(() => {
    mountedRef.current = true;
    loadAll();
    return () => { mountedRef.current = false; };
  }, [currentWorkspaceId]);

  if (loading) {
    return (
      <div className="page" data-testid="page-diagnostics">
        <PageHeader onRefresh={loadAll} />
        <div className="page-body"><LoadingState text="加载诊断数据…" /></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="page" data-testid="page-diagnostics">
        <PageHeader onRefresh={loadAll} />
        <div className="page-body">
          <div className="card" style={{ borderColor: "var(--danger)", color: "var(--danger)", padding: 16 }}>
            无法加载诊断数据，请确认后端服务正在运行。
            <button className="btn mt-2" onClick={loadAll}>🔄 重试</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="page" data-testid="page-diagnostics">
      <PageHeader onRefresh={loadAll} />
      <div className="page-body">
        {/* Quick tip */}
        <details style={{ marginBottom: 16, fontSize: "var(--fs-12)", color: "var(--text-3)" }}>
          <summary style={{ cursor: "pointer", fontWeight: 680 }}>💡 使用帮助</summary>
          <div style={{ marginTop: 6, padding: "10px 14px", background: "var(--surface-2)", borderRadius: "var(--r-6)", lineHeight: 1.6 }}>
            <strong>运行时健康</strong> — 检查各组件（LLM、知识库、记忆等）是否正常；<br />
            <strong>自检报告</strong> — 数据一致性、路径安全等自动检测结果；<br />
            <strong>用量统计</strong> — Token 消耗和会话数量趋势；<br />
            <strong>数据策略</strong> — 查看/调整自动清理规则。
          </div>
        </details>

        {/* ── Runtime Health Bar ── */}
        {health && (
          <div style={{ marginBottom: 20 }}>
            <SectionTitle icon={<IconShield size={14} />} title="运行时健康" />
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
              <StatBadge label="正常" value={health.summary.ok} color="var(--ok)" />
              {health.summary.warning > 0 && <StatBadge label="警告" value={health.summary.warning} color="var(--warn)" />}
              {health.summary.error > 0 && <StatBadge label="异常" value={health.summary.error} color="var(--danger)" />}
            </div>
            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
              {health.components.map((c, i) => (
                <div
                  key={c.name}
                  style={{
                    display: "flex", alignItems: "center", gap: 10, padding: "10px 14px",
                    borderBottom: i < health.components.length - 1 ? "1px solid var(--line-2, #eee)" : "none",
                    fontSize: 13,
                  }}
                >
                  <span style={{
                    width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
                    background: c.status === "ok" ? "var(--ok)" : c.status === "warning" ? "var(--warn)" : "var(--danger)",
                  }} />
                  <span style={{ fontWeight: 500, minWidth: 100, color: "var(--text)" }}>{c.name}</span>
                  <span style={{ color: "var(--text-3)", flex: 1 }}>{c.message}</span>
                  {c.details && Object.keys(c.details).length > 0 && (
                    <span style={{ fontSize: 11, color: "var(--text-4)", fontFamily: "var(--font-mono)" }}>
                      {Object.entries(c.details).map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join(", ")}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Two-column: Selfcheck + Usage ── */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 20 }}>
          {/* Selfcheck */}
          <div>
            <SectionTitle icon={<IconAlert size={14} />} title="自检" />
            {selfcheck ? (
              <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                <div style={{
                  padding: "10px 14px", display: "flex", alignItems: "center", gap: 8,
                  background: selfcheck.status === "healthy" ? "var(--ok-soft, #e8f5e9)" : "var(--warn-soft, #fff8e1)",
                  borderBottom: selfcheck.issues.length > 0 ? "1px solid var(--line-2, #eee)" : "none",
                }}>
                  <IconCheck size={14} style={{ color: selfcheck.status === "healthy" ? "var(--ok)" : "var(--warn)" }} />
                  <span style={{ fontSize: 13, fontWeight: 600, color: selfcheck.status === "healthy" ? "var(--ok)" : "var(--warn)" }}>
                    {selfcheck.status === "healthy" ? "所有检查通过" : "发现警告"}
                  </span>
                </div>
                {selfcheck.issues.length > 0 && (
                  <div>
                    {selfcheck.issues.map((iss, i) => (
                      <div
                        key={iss.code || i}
                        style={{
                          padding: "10px 14px", fontSize: 12,
                          borderBottom: i < selfcheck.issues.length - 1 ? "1px solid var(--line-2, #eee)" : "none",
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
                          <span style={{
                            fontSize: 10, padding: "1px 5px", borderRadius: 3, fontWeight: 600,
                            background: iss.severity === "error" ? "var(--danger-soft, #f7dfe3)" : "var(--warn-soft, #f7ebca)",
                            color: iss.severity === "error" ? "var(--danger)" : "var(--warn)",
                          }}>
                            {iss.code}
                          </span>
                          <span style={{ color: "var(--text-2)" }}>{iss.message}</span>
                        </div>
                        {iss.suggested_action && (
                          <div style={{ color: "var(--text-4)", paddingLeft: 4 }}>→ {iss.suggested_action}</div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <EmptyCard text="无法获取自检数据" />
            )}
          </div>

          {/* Usage */}
          <div>
            <SectionTitle icon={<IconBolt size={14} />} title="用量统计" />
            {usage ? (
              <div className="card" style={{ padding: 16 }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px 20px" }}>
                  <StatItem label="调用次数" value={usage.call_count.toLocaleString()} />
                  <StatItem label="预估费用" value={`¥${Number(usage?.estimated_cost ?? 0).toFixed(4)}`} accent />
                  <StatItem label="输入 Token" value={usage.input_tokens.toLocaleString()} />
                  <StatItem label="输出 Token" value={usage.output_tokens.toLocaleString()} />
                  <StatItem label="总 Token" value={usage.total_tokens.toLocaleString()} span />
                </div>
                {usage.last_updated && (
                  <div style={{ marginTop: 10, fontSize: 11, color: "var(--text-4)", display: "flex", alignItems: "center", gap: 4 }}>
                    <IconClock size={10} />
                    最后更新: {new Date(usage.last_updated).toLocaleString()}
                  </div>
                )}
              </div>
            ) : (
              <EmptyCard text="无法获取用量数据" />
            )}
          </div>
        </div>

        {/* ── Context Runtime ── */}
        {contextOk !== null && (
          <div style={{ marginBottom: 20 }}>
            <SectionTitle icon={<IconBolt size={14} />} title="上下文运行时" />
            <div className="card" style={{ padding: "12px 16px", display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{
                width: 8, height: 8, borderRadius: "50%",
                background: contextOk ? "var(--ok)" : "var(--danger)",
              }} />
              <span style={{ fontSize: 13, fontWeight: 500 }}>{contextOk ? "已启用" : "未启用"}</span>
              <span style={{ fontSize: 12, color: "var(--text-4)" }}>
                {contextOk ? "上下文引用系统正常运行" : "上下文引用系统不可用"}
              </span>
            </div>
          </div>
        )}

        {/* ── Prompts Table ── */}
        {prompts && prompts.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <SectionTitle icon={<IconBolt size={14} />} title={`提示词库 (${prompts.length})`} />
            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
              <div style={{
                display: "grid", gridTemplateColumns: "2fr 1fr 2fr",
                padding: "8px 14px", fontSize: 11, fontWeight: 600,
                color: "var(--text-4)", borderBottom: "1px solid var(--line-2, #eee)",
                background: "var(--surface-2, #f8fafc)",
              }}>
                <span>Prompt ID</span>
                <span>版本 · 状态</span>
                <span>说明</span>
              </div>
              {prompts.map((p, i) => (
                <div
                  key={p.prompt_id}
                  style={{
                    display: "grid", gridTemplateColumns: "2fr 1fr 2fr", alignItems: "center",
                    padding: "7px 14px", fontSize: 12,
                    borderBottom: i < prompts.length - 1 ? "1px solid var(--line-2, #eee)" : "none",
                  }}
                >
                  <span style={{ fontWeight: 500, fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text)" }}>
                    {p.prompt_id}
                  </span>
                  <span style={{ display: "flex", gap: 4, alignItems: "center" }}>
                    <span style={{
                      fontSize: 10, padding: "1px 5px", borderRadius: 3,
                      background: p.status === "enabled" ? "var(--ok-soft, #e8f5e9)" : "var(--warn-soft, #fff8e1)",
                      color: p.status === "enabled" ? "var(--ok)" : "var(--warn)",
                    }}>
                      {p.version}
                    </span>
                  </span>
                  <span style={{ color: "var(--text-3)", fontSize: 11 }}>{p.description || p.task}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Retention + Archive policies ── */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
          {retention && (
            <div>
              <SectionTitle icon={<IconClock size={14} />} title="数据保留策略" />
              <div className="card" style={{ padding: 16 }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {Object.entries(retention.policy).map(([k, v]) => (
                    <div key={k} style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                      <span style={{ color: "var(--text-3)" }}>{formatPolicyKey(k)}</span>
                      <span style={{ fontWeight: 500, color: "var(--text)", fontVariantNumeric: "tabular-nums" }}>
                        {formatPolicyValue(k, v)}
                      </span>
                    </div>
                  ))}
                </div>
                {retention.candidate_counts && Object.keys(retention.candidate_counts).length > 0 && (
                  <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--line-2, #eee)", fontSize: 11, color: "var(--text-4)" }}>
                    待清理: {Object.entries(retention.candidate_counts).map(([k, v]) => `${formatPolicyKey(k)} ${v}`).join(", ")}
                  </div>
                )}
              </div>
            </div>
          )}
          {archive && (
            <div>
              <SectionTitle icon={<IconClock size={14} />} title="归档策略" />
              <div className="card" style={{ padding: 16 }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {Object.entries(archive.policy).map(([k, v]) => (
                    <div key={k} style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                      <span style={{ color: "var(--text-3)" }}>{formatPolicyKey(k)}</span>
                      <span style={{ fontWeight: 500, color: "var(--text)", fontVariantNumeric: "tabular-nums" }}>
                        {formatPolicyValue(k, v)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}

/* ──────────────────────── Helpers ──────────────────────── */

function formatPolicyKey(key: string): string {
  const map: Record<string, string> = {
    runs_max_age_days: "运行保留天数", runs_max_count: "最大运行数",
    traces_max_age_days: "追踪保留天数", traces_max_count: "最大追踪数",
    jobs_max_age_days: "作业保留天数", artifacts_temp_max_age_days: "临时制品保留天数",
    prune_reports: "清理报告", archive_active_refs: "归档活跃引用",
    archive_quarantine_artifacts: "归档隔离制品", archive_reports: "归档报告",
    archive_temp_artifacts: "归档临时制品", jobs_older_than_days: "作业超过天数",
    runs_keep_latest: "保留最近运行", runs_older_than_days: "运行超过天数",
    traces_keep_latest: "保留最近追踪", traces_older_than_days: "追踪超过天数",
    temp_older_than_days: "临时文件超过天数",
  };
  return map[key] ?? key.replace(/_/g, " ");
}

function formatPolicyValue(key: string, v: unknown): string {
  if (typeof v === "boolean") return v ? "是" : "否";
  if (typeof v === "number") {
    if (key.includes("days") || key.includes("older_than")) return `${v} 天`;
    return v.toLocaleString();
  }
  return String(v);
}

/* ──────────────────────── Sub-components ──────────────────────── */

function PageHeader({ onRefresh }: { onRefresh?: () => void }) {
  return (
    <div className="page-header" style={{ background: "var(--surface)" }}>
      <div>
        <h1>系统诊断<span style={{ color: "var(--ink-mute)", fontWeight: 400, fontSize: 14 }}> · Diagnostics</span></h1>
        <div className="subtitle">运行时健康 · 用量统计 · 提示词库 · 数据策略</div>
      </div>
      {onRefresh && (
        <button className="btn" onClick={onRefresh} style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 4 }}>
          <IconRefresh size={12} /> 刷新
        </button>
      )}
    </div>
  );
}

function SectionTitle({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8, fontSize: 13, fontWeight: 600, color: "var(--text-2)" }}>
      <span style={{ color: "var(--text-4)" }}>{icon}</span>
      {title}
    </div>
  );
}

function StatBadge({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "3px 10px", borderRadius: 6, fontSize: 12, fontWeight: 500,
      background: `${color}14`, border: `1px solid ${color}30`, color,
    }}>
      {label} <strong>{value}</strong>
    </span>
  );
}

function StatItem({ label, value, accent, span }: { label: string; value: string; accent?: boolean; span?: boolean }) {
  return (
    <div style={span ? { gridColumn: "1 / -1" } : undefined}>
      <div style={{ fontSize: 11, color: "var(--text-4)", marginBottom: 2 }}>{label}</div>
      <div style={{
        fontSize: accent ? 16 : 14, fontWeight: 600, color: accent ? "var(--accent)" : "var(--text)",
        fontVariantNumeric: "tabular-nums",
      }}>{value}</div>
    </div>
  );
}

function EmptyCard({ text }: { text: string }) {
  return (
    <div className="card" style={{ padding: 20, textAlign: "center", color: "var(--text-4)", fontSize: 12 }}>
      {text}
    </div>
  );
}
