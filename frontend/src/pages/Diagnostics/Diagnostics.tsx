/**
 * Diagnostics — 系统诊断仪表盘
 *
 * 设计：手动触发检测，默认显示上一次缓存数据，避免每次进入都 loading。
 * 点击「开始检测」→ 调用全部 API → 缓存到 localStorage → 更新仪表盘。
 * 无缓存时显示空骨架 + 醒目的检测按钮。
 */
import { useEffect, useRef, useState, useCallback } from "react";
import { runtimeApi, agentUsageApi, retentionApi, archiveApi, contextApi, promptsApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { LoadingState } from "../../components/common";
import { IconRefresh } from "../../components/Icon";
import { formatDate } from "../../utils/format";

const CACHE_KEY = "diagnostics_v1";

/* ──────────────────────── Types ──────────────────────── */

type UsageStats = {
  call_count: number; total_tokens: number; input_tokens: number;
  output_tokens: number; estimated_cost: number; last_updated: string;
};

type DiagnosticsCache = {
  ts: string;
  health: any;
  selfcheck: any;
  usage: UsageStats | null;
  contextOk: boolean | null;
  prompts: any[] | null;
  retention: any;
  archive: any;
};

/* ──────────────────────── Cache helpers ──────────────────────── */

function readCache(): DiagnosticsCache | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as DiagnosticsCache;
  } catch {
    return null;
  }
}

function writeCache(data: Omit<DiagnosticsCache, "ts">) {
  try {
    const entry: DiagnosticsCache = { ts: new Date().toISOString(), ...data };
    localStorage.setItem(CACHE_KEY, JSON.stringify(entry));
  } catch { /* quota exceeded — silently ignore */ }
}

/* ──────────────────────── Component ──────────────────────── */

export function Diagnostics() {
  const currentWorkspaceId = useSessionStore((s) => s.currentWorkspaceId);
  const cache = readCache();

  // State: init from cache or null
  const [health, setHealth] = useState<any>(cache?.health ?? null);
  const [selfcheck, setSelfcheck] = useState<any>(cache?.selfcheck ?? null);
  const [usage, setUsage] = useState<UsageStats | null>(cache?.usage ?? null);
  const [contextOk, setContextOk] = useState<boolean | null>(cache?.contextOk ?? null);
  const [prompts, setPrompts] = useState<any[] | null>(cache?.prompts ?? null);
  const [retention, setRetention] = useState<any>(cache?.retention ?? null);
  const [archive, setArchive] = useState<any>(cache?.archive ?? null);
  const [lastCheck, setLastCheck] = useState<string | null>(cache?.ts ?? null);

  const [detecting, setDetecting] = useState(false);
  const mountedRef = useRef(true);
  const seqRef = useRef(0);

  const runDetection = useCallback(async () => {
    const seq = ++seqRef.current;
    setDetecting(true);
    const ctrl = new AbortController();
    const wsId = currentWorkspaceId;
    if (!wsId) {
      setDetecting(false);
      return;
    }
    const [rh, sc, us, cs, pr, rp, ap] = await Promise.allSettled([
      runtimeApi.health(wsId, ctrl.signal),
      runtimeApi.selfcheck(wsId, ctrl.signal),
      agentUsageApi.get(wsId, ctrl.signal),
      contextApi.status(ctrl.signal),
      promptsApi.list(ctrl.signal),
      retentionApi.preview(wsId, ctrl.signal),
      archiveApi.preview(wsId, ctrl.signal),
    ]);
    if (!mountedRef.current || seq !== seqRef.current) return;

    let newHealth = health, newSelfcheck = selfcheck, newUsage = usage;
    let newContextOk = contextOk, newPrompts = prompts, newRetention = retention, newArchive = archive;

    if (rh.status === "fulfilled") { newHealth = rh.value; setHealth(rh.value); }
    if (sc.status === "fulfilled") { newSelfcheck = sc.value; setSelfcheck(sc.value); }
    if (us.status === "fulfilled") {
      const raw = us.value as any;
      newUsage = {
        call_count: raw.call_count ?? 0, total_tokens: raw.total_tokens ?? 0,
        input_tokens: raw.input_tokens ?? 0, output_tokens: raw.output_tokens ?? 0,
        estimated_cost: raw.estimated_cost ?? 0, last_updated: raw.last_updated ?? "",
      };
      setUsage(newUsage);
    }
    if (cs.status === "fulfilled") {
      newContextOk = (cs.value as any).context_runtime_enabled;
      setContextOk(newContextOk);
    }
    if (pr.status === "fulfilled") { newPrompts = (pr.value as any).prompts ?? []; setPrompts(newPrompts); }
    if (rp.status === "fulfilled") { newRetention = rp.value; setRetention(rp.value); }
    if (ap.status === "fulfilled") { newArchive = ap.value; setArchive(ap.value); }

    // Save to cache
    writeCache({
      health: newHealth, selfcheck: newSelfcheck, usage: newUsage,
      contextOk: newContextOk, prompts: newPrompts,
      retention: newRetention, archive: newArchive,
    });
    setLastCheck(new Date().toISOString());

    setDetecting(false);
  }, [currentWorkspaceId, health, selfcheck, usage, contextOk, prompts, retention, archive]);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const hs = health?.summary ?? {};
  const allOk = (hs.ok ?? 0) > 0 && (hs.warning ?? 0) === 0 && (hs.error ?? 0) === 0;
  const hasData = health !== null || selfcheck !== null || usage !== null;

  /* ══════════════════════════════════════════
     RENDER
     ══════════════════════════════════════════ */

  return (
    <div className="page" data-testid="page-diagnostics">
      <PageHeader
        onDetect={runDetection}
        detecting={detecting}
        lastCheck={lastCheck}
        allOk={allOk}
        hasData={hasData}
      />

      {/* Loading overlay during detection */}
      {detecting ? (
        <div className="page-body"><LoadingState text="检测中…" /></div>
      ) : (
        <div className="page-body" style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 20 }}>
          {/* ═══ 行1: 运行时健康（全宽） ═══ */}
          <div>
            <Section title="运行时健康" badge={
              health ? (
                <span style={{ fontSize: 12 }}>
                  {allOk ? <span style={{ color: "#2e7d32" }}>● 全部正常</span> : `${hs.ok} ok` + (hs.warning ? ` / ${hs.warning} warn` : "") + (hs.error ? ` / ${hs.error} err` : "")}
                </span>
              ) : null
            }>
              {health ? (
                <div style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))",
                  gap: 10,
                }}>
                  {(health.components ?? []).map((c: any) => (
                    <div key={c.name} style={{
                      padding: "10px 12px",
                      background: c.status === "ok" ? "var(--surface-2)" : c.status === "warning" ? "#fff3e0" : "#fce4ec",
                      borderRadius: "var(--r-6)",
                      border: `1px solid ${c.status === "ok" ? "var(--line-2)" : c.status === "warning" ? "#ffcc02" : "#ef5350"}40`,
                    }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                        <span style={{
                          width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
                          background: c.status === "ok" ? "#2e7d32" : c.status === "warning" ? "#ed6c02" : "#d32f2f",
                        }} />
                        <span style={{ fontWeight: 680, fontSize: 12 }}>{c.name}</span>
                        <span style={{
                          marginLeft: "auto", fontSize: 10,
                          padding: "1px 5px", borderRadius: 3,
                          background: c.status === "ok" ? "#e8f5e9" : c.status === "warning" ? "#fff3e0" : "#fce4ec",
                          color: c.status === "ok" ? "#2e7d32" : c.status === "warning" ? "#e65100" : "#c62828",
                        }}>{c.status}</span>
                      </div>
                      {c.message && (
                        <div style={{ fontSize: 11, color: "var(--text-3)" }}>{c.message}</div>
                      )}
                    </div>
                  ))}
                </div>
              ) : <Dim>点击上方「开始检测」获取运行时健康数据</Dim>}
            </Section>
          </div>

          {/* ═══ 行2: 用量 + 自检 + 提示词 ═══ */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 20 }}>
            <Section title="用量">
              {usage ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <Row label="调用次数" value={usage.call_count.toLocaleString()} />
                  <Row label="总 Token" value={usage.total_tokens.toLocaleString()} />
                  <Row label="输入 / 输出" value={`${usage.input_tokens.toLocaleString()} / ${usage.output_tokens.toLocaleString()}`} dim />
                  <div style={{ borderTop: "1px solid var(--line-2)", paddingTop: 10, display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                    <span style={{ fontSize: 11, color: "var(--text-4)" }}>预估费用</span>
                    <b style={{ fontSize: 18, color: "#b388ff", fontVariantNumeric: "tabular-nums" }}>¥{Number(usage.estimated_cost ?? 0).toFixed(4)}</b>
                  </div>
                </div>
              ) : <Dim>暂无数据</Dim>}
            </Section>

            <Section title="自检" badge={selfcheck?.status === "healthy" ? <span style={{ color: "#2e7d32", fontSize: 12 }}>通过</span> : selfcheck?.issues?.length > 0 ? <span style={{ color: "#ed6c02", fontSize: 12 }}>{selfcheck.issues.length} 项</span> : null}>
              {selfcheck ? (
                selfcheck.issues?.length > 0 ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {selfcheck.issues.map((iss: any, i: number) => (
                      <div key={i} style={{ fontSize: 12, padding: "4px 0", borderBottom: i < selfcheck.issues.length - 1 ? "1px solid var(--line-2)" : "none" }}>
                        <code style={{ fontSize: 10, padding: "1px 5px", borderRadius: 3, background: iss.severity === "error" ? "#fce4ec" : "#fff3e0", color: iss.severity === "error" ? "#c62828" : "#e65100", marginRight: 6 }}>{iss.code}</code>
                        {iss.message}
                        {iss.suggested_action && <div style={{ color: "var(--text-4)", fontSize: 11, marginTop: 2 }}>→ {iss.suggested_action}</div>}
                      </div>
                    ))}
                  </div>
                ) : <Dim>未发现问题</Dim>
              ) : <Dim>无数据</Dim>}
            </Section>

            <Section title="提示词库" badge={prompts?.length != null ? <span style={{ fontSize: 12, color: "var(--text-4)" }}>{prompts.length}</span> : null}>
              {prompts && prompts.length > 0 ? (
                <div style={{ maxHeight: 240, overflow: "auto" }}>
                  <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ position: "sticky", top: 0, background: "var(--surface)", color: "var(--text-4)", textTransform: "uppercase", fontSize: 10, letterSpacing: ".5px" }}>
                        <th style={{ textAlign: "left", padding: "4px 8px", fontWeight: 600, borderBottom: "1px solid var(--line)" }}>ID</th>
                        <th style={{ textAlign: "left", padding: "4px 8px", fontWeight: 600, borderBottom: "1px solid var(--line)" }}>Ver</th>
                        <th style={{ textAlign: "left", padding: "4px 8px", fontWeight: 600, borderBottom: "1px solid var(--line)" }}>Description</th>
                      </tr>
                    </thead>
                    <tbody>
                      {prompts.map((p: any) => (
                        <tr key={p.prompt_id}>
                          <td style={{ padding: "3px 8px", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-2)" }}>{p.prompt_id}</td>
                          <td style={{ padding: "3px 8px", color: "var(--text-2)" }}><span style={{ padding: "1px 4px", borderRadius: 3, background: "var(--surface-2)", fontSize: 10 }}>{p.version}</span></td>
                          <td style={{ padding: "3px 8px", fontSize: 11, color: "var(--text-2)" }}>{p.description || p.task}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <Dim>暂无</Dim>}
            </Section>
          </div>

          {/* ═══ 行3: 上下文 + 数据策略 ═══ */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
            <Section title="上下文运行时">
              {contextOk !== null ? (
                <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: contextOk ? "#2e7d32" : "#d32f2f" }} />
                  {contextOk ? "已启用" : "未启用"}
                </div>
              ) : <Dim>无数据</Dim>}
            </Section>

            <Section title="数据策略">
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                {retention?.policy && (
                  <div>
                    <div style={{ fontSize: 10, color: "var(--text-4)", fontWeight: 600, letterSpacing: ".5px", marginBottom: 6 }}>保留</div>
                    {Object.entries(retention.policy).slice(0, 5).map(([k, v]) => (
                      <Row key={k} label={fmtKey(k)} value={fmtVal(k, v)} compact />
                    ))}
                  </div>
                )}
                {archive?.policy && (
                  <div>
                    <div style={{ fontSize: 10, color: "var(--text-4)", fontWeight: 600, letterSpacing: ".5px", marginBottom: 6 }}>归档</div>
                    {Object.entries(archive.policy).slice(0, 5).map(([k, v]) => (
                      <Row key={k} label={fmtKey(k)} value={fmtVal(k, v)} compact />
                    ))}
                  </div>
                )}
                {!retention?.policy && !archive?.policy && <Dim>无数据</Dim>}
              </div>
            </Section>
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── Page Header ─── */

function PageHeader({
  onDetect, detecting, lastCheck, allOk, hasData,
}: {
  onDetect: () => void;
  detecting: boolean;
  lastCheck: string | null;
  allOk: boolean;
  hasData: boolean;
}) {
  return (
    <div className="page-header" style={{ background: "var(--surface)", borderBottom: "1px solid var(--line-2)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: "var(--fs-18)" }}>系统诊断</h1>
          <p style={{ margin: "2px 0 0", fontSize: 12, color: "var(--text-4)" }}>
            健康跟踪 · 用量 · 自检 · 策略
            {lastCheck && (
              <span style={{ marginLeft: 10, color: "var(--text-3)", fontSize: 11 }}>
                上次检测：{formatDate(lastCheck, "compact")}
              </span>
            )}
            {hasData && (
              <span style={{ marginLeft: 10, color: allOk ? "#2e7d32" : "#ed6c02", fontWeight: 600, fontSize: 11 }}>
                {allOk ? "● 正常" : "● 注意"}
              </span>
            )}
          </p>
        </div>
        <button
          className="btn sm"
          onClick={onDetect}
          disabled={detecting}
          style={{ marginLeft: "auto", fontWeight: 680, minWidth: 100, justifyContent: "center" }}
        >
          {detecting ? (
            <>⏳ 检测中…</>
          ) : (
            <><IconRefresh size={12} /> {hasData ? "重新检测" : "开始检测"}</>
          )}
        </button>
      </div>
    </div>
  );
}

/* ─── Sub-components ─── */

function Section({ title, badge, children }: { title: string; badge?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div style={{ padding: "16px 20px", background: "var(--surface)", borderRadius: 8, border: "1px solid var(--line-2)" }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 13, fontWeight: 700, color: "var(--text)" }}>{title}</h3>
        {badge}
      </div>
      {children}
    </div>
  );
}

function Row({ label, value, dim, compact }: { label: string; value: string; dim?: boolean; compact?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", fontSize: compact ? 11 : 12, padding: compact ? "2px 0" : undefined }}>
      <span style={{ color: "var(--text-4)" }}>{label}</span>
      <span style={{ fontWeight: 500, color: dim ? "var(--text-3)" : "var(--text)", fontVariantNumeric: "tabular-nums" }}>{value}</span>
    </div>
  );
}

function Dim({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: 12, color: "var(--text-4)", textAlign: "center", padding: "20px 0" }}>{children}</div>;
}

/* ─── Small helpers ─── */

function fmtKey(k: string): string {
  const m: Record<string, string> = {
    runs_max_age_days: "运行保留", runs_max_count: "最大运行",
    traces_max_age_days: "追踪保留", traces_max_count: "最大追踪",
    jobs_max_age_days: "作业保留", artifacts_temp_max_age_days: "临时制品",
    prune_reports: "清理报告", archive_active_refs: "活跃引用",
    runs_older_than_days: "运行>天数", traces_older_than_days: "追踪>天数",
    temp_older_than_days: "临时>天数", runs_keep_latest: "保留最近运行",
  };
  return m[k] ?? k.replace(/_/g, " ");
}

function fmtVal(k: string, v: unknown): string {
  if (typeof v === "boolean") return v ? "是" : "否";
  if (typeof v === "number") { if (k.includes("days") || k.includes("older_than")) return `${v}天`; return v.toLocaleString(); }
  return String(v);
}
