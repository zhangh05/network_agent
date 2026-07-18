/**
 * Diagnostics — 系统诊断仪表盘
 *
 * 设计：手动触发检测，默认显示上一次缓存数据，避免每次进入都 loading。
 * 点击「开始检测」→ 调用全部 API → 缓存到 localStorage → 更新仪表盘。
 * 无缓存时显示空骨架 + 醒目的检测按钮。
 */
import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { runtimeApi, agentUsageApi, retentionApi, archiveApi, contextApi, promptsApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { LoadingState } from "../../components/common";
import { IconRefresh } from "../../components/Icon";
import { formatDate } from "../../utils/format";
import { PageHeader, DataTable } from "../../components/ui";

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

/* ── 内部组件名 → 用户友好名称 ── */
const COMP_LABELS: Record<string, string> = {
  workspace: "工作空间", registry: "能力注册", runs: "运行记录",
  artifacts: "制品管理", jobs: "作业调度", agent: "智能体核心",
  tool_runtime: "工具引擎", llm: "大模型服务", archive: "归档存储",
  memory: "记忆系统", context: "上下文", knowledge: "知识库",
  network: "网络探测", packet: "报文分析", cmdb: "配置台账",
};

const COMP_DESC: Record<string, string> = {
  workspace: "当前工作区配置与状态", registry: "模块与技能注册表",
  runs: "历史执行记录追踪", artifacts: "配置产物与输出文件",
  jobs: "定时/触发作业管理", agent: "Agent 主进程状态",
  tool_runtime: "外部工具调用引擎", llm: "LLM 连通性与配额",
  archive: "历史数据归档策略", memory: "长期记忆存储状态",
  context: "对话上下文窗口", knowledge: "知识检索服务",
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
      const raw = us.value;
      newUsage = {
        call_count: raw.call_count ?? 0, total_tokens: raw.total_tokens ?? 0,
        input_tokens: raw.input_tokens ?? 0, output_tokens: raw.output_tokens ?? 0,
        estimated_cost: raw.estimated_cost ?? 0, last_updated: raw.last_updated ?? "",
      };
      setUsage(newUsage);
    }
    if (cs.status === "fulfilled") {
      newContextOk = (cs.value).context_runtime_enabled;
      setContextOk(newContextOk);
    }
    if (pr.status === "fulfilled") { newPrompts = (pr.value).prompts ?? []; setPrompts(newPrompts); }
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

  /* ── 概览摘要数据 ── */
  const summaryStats = useMemo(() => {
    if (!health && !usage) return null;
    const comps = health?.components ?? [];
    const okCount = comps.filter((c: any) => c.status === "ok").length;
    const warnCount = comps.filter((c: any) => c.status === "warning").length;
    const errCount = comps.filter((c: any) => c.status === "error").length;
    return {
      totalComps: comps.length,
      okCount, warnCount, errCount,
      calls: usage?.call_count ?? 0,
      cost: usage?.estimated_cost ?? 0,
      tokens: usage?.total_tokens ?? 0,
      selfOk: selfcheck?.status === "healthy",
      issueCount: selfcheck?.issues?.length ?? 0,
    };
  }, [health, usage, selfcheck]);

  /* ══════════════════════════════════════════
     RENDER
     ══════════════════════════════════════════ */

  return (
    <div className="page" data-testid="page-diagnostics">
      <PageHeader
        title="系统诊断"
        subtitle={
          <span>
            健康跟踪 · 用量 · 自检 · 策略
            {lastCheck && (
              <span className="ml-2 faint">上次检测：{formatDate(lastCheck, "compact")}</span>
            )}
            {hasData && (
              <span className={`ml-2 ${allOk ? "success-text" : "warning-text"}`}>
                {allOk ? "● 正常" : "● 注意"}
              </span>
            )}
          </span>
        }
      >
        <button
          className="btn sm"
          onClick={runDetection}
          disabled={detecting}
          style={{ fontWeight: 680, minWidth: 100, justifyContent: "center" }}
        >
          {detecting ? (
            <>⏳ 检测中…</>
          ) : (
            <><IconRefresh size={12} /> {hasData ? "重新检测" : "开始检测"}</>
          )}
        </button>
      </PageHeader>

      {/* Loading overlay during detection */}
      {detecting ? (
        <div className="page-body"><LoadingState text="检测中…" /></div>
      ) : (
        <div className="page-body page-body-flex">
          {/* ═══ 概览摘要卡（用户3秒看懂系统状态） ═══ */}
          {summaryStats && (
            <div className="diag-summary">
              <div className="diag-summary-icon" data-healthy={String(allOk)}>
                {allOk ? "✓" : "!"}
              </div>
              <div className="diag-summary-text">
                <h2>{allOk ? "系统运行正常" : "需要注意"}</h2>
                <p>
                  {summaryStats.okCount}/{summaryStats.totalComps} 项服务正常
                  {summaryStats.warnCount > 0 && `，${summaryStats.warnCount} 项警告`}
                  {summaryStats.errCount > 0 && `，${summaryStats.errCount} 项异常`}
                  {summaryStats.calls > 0 && ` · 累计调用 ${summaryStats.calls.toLocaleString()} 次`}
                  {summaryStats.cost > 0 && ` · 花费 ¥${summaryStats.cost.toFixed(4)}`}
                </p>
              </div>
              {!summaryStats.selfOk && summaryStats.issueCount > 0 && (
                <div className="diag-summary-alert">
                  自检发现 {summaryStats.issueCount} 个问题
                </div>
              )}
            </div>
          )}

          {/* ═══ 行1: 运行时健康（全宽） ═══ */}
          <div>
            <Section title="运行时健康" badge={
              health ? (
                <span style={{ fontSize: 12 }}>
                  {allOk ? <span style={{ color: "var(--ok, #2e7d32)" }}>● 全部正常</span> : `${hs.ok} 正常` + (hs.warning ? ` / ${hs.warning} 警告` : "") + (hs.error ? ` / ${hs.error} 异常` : "")}
                </span>
              ) : null
            }>
              {health ? (
                <div className="diag-health-grid">
                  {(health.components ?? []).map((c: any) => {
                    const label = COMP_LABELS[c.name] || c.name;
                    const desc = COMP_DESC[c.name] || "";
                    return (
                      <div key={c.name} className={`diag-health-card diag-health-${c.status}`}>
                        <div className="diag-health-head">
                          <span className={`diag-status-dot diag-status-${c.status}`} />
                          <span className="diag-comp-name">{label}</span>
                          <span className={`diag-status-tag diag-status-tag-${c.status}`}>{c.status === "ok" ? "正常" : c.status === "warning" ? "警告" : "异常"}</span>
                        </div>
                        {desc && <div className="diag-comp-desc">{desc}</div>}
                        {c.message && <div className="diag-comp-msg">{c.message}</div>}
                      </div>
                    );
                  })}
                </div>
              ) : <Dim>点击上方「开始检测」获取运行时健康数据</Dim>}
            </Section>
          </div>

          {/* ═══ 行2: 用量 + 自检 + 提示词 ═══ */}
          <div className="diag-row-3col">
            <Section title="用量统计">
              {usage ? (
                <div className="diag-usage-body">
                  <div className="diag-usage-big">
                    <span className="diag-usage-number">{usage.call_count.toLocaleString()}</span>
                    <span className="diag-usage-unit">次调用</span>
                  </div>
                  <div className="diag-usage-rows">
                    <Row label="Token 总量" value={usage.total_tokens.toLocaleString()} />
                    <Row label="输入 / 输出" value={`${usage.input_tokens.toLocaleString()} / ${usage.output_tokens.toLocaleString()}`} dim />
                    <div style={{ borderTop: "1px solid var(--line-2)", paddingTop: 10, display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                      <span style={{ fontSize: 11, color: "var(--text-4)" }}>预估费用</span>
                      <b className="diag-cost">¥{Number(usage.estimated_cost ?? 0).toFixed(4)}</b>
                    </div>
                  </div>
                </div>
              ) : <Dim>暂无数据</Dim>}
            </Section>

            <Section title="自检结果" badge={selfcheck?.status === "healthy" ? <span style={{ color: "var(--ok, #2e7d32)", fontSize: 12 }}>通过</span> : selfcheck?.issues?.length > 0 ? <span style={{ color: "var(--warn, #ed6c02)", fontSize: 12 }}>{selfcheck.issues.length} 项问题</span> : null}>
              {selfcheck ? (
                selfcheck.issues?.length > 0 ? (
                  <div className="diag-issues-list">
                    {selfcheck.issues.map((iss: any, i: number) => (
                      <div key={i} className={`diag-issue-item diag-issue-${iss.severity}`}>
                        <span className="diag-issue-sev">{iss.severity === "error" ? "错误" : "警告"}</span>
                        <div className="diag-issue-body">
                          <span className="diag-issue-msg">{iss.message}</span>
                          {iss.suggested_action && <span className="diag-issue-action">建议：{iss.suggested_action}</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : <Dim>✓ 未发现问题</Dim>
              ) : <Dim>无数据</Dim>}
            </Section>

            <Section title="提示词库" badge={prompts?.length != null ? <span className="faint">{prompts.length} 条</span> : null}>
              {prompts && prompts.length > 0 ? (
                <div style={{ maxHeight: 260, overflowY: "auto" }}>
                  <DataTable
                    rows={prompts}
                    keyExtractor={(p) => p.prompt_id}
                    columns={[
                      { key: "desc", header: "用途说明", render: (p) => <span className="diag-prompt-desc">{p.description || p.task || p.prompt_id}</span> },
                      { key: "version", header: "版本", width: 70, align: "center", render: (p) => <span className="diag-ver-badge">{p.version}</span> },
                      { key: "id", header: "ID", width: 180, render: (p) => <span className="diag-prompt-id">{p.prompt_id}</span> },
                    ]}
                  />
                </div>
              ) : <Dim>暂无</Dim>}
            </Section>
          </div>

          {/* ═══ 行3: 上下文 + 数据策略 ═══ */}
          <div className="diag-row-2col">
            <Section title="上下文运行时">
              {contextOk !== null ? (
                <div className="diag-context-info">
                  <div className={`diag-context-status ${contextOk ? "diag-context-on" : "diag-context-off"}`}>
                    <span className={`diag-status-dot diag-status-${contextOk ? "ok" : "error"}`} />
                    {contextOk ? "已启用" : "未启用"}
                  </div>
                  <p className="diag-context-desc">
                    {contextOk
                      ? "上下文运行时已开启，智能体可在多轮对话中维护完整的工作记忆与任务状态。"
                      : "上下文运行时未启用，部分跨轮次的功能可能受限。如需完整体验，请在后端配置中启用。"}
                  </p>
                </div>
              ) : <Dim>无数据</Dim>}
            </Section>

            <Section title="数据策略">
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                {retention?.policy && (
                  <div className="diag-policy-block">
                    <div className="diag-policy-title">📥 数据保留</div>
                    {Object.entries(retention.policy).slice(0, 5).map(([k, v]) => (
                      <Row key={k} label={fmtKey(k)} value={fmtVal(k, v)} compact />
                    ))}
                  </div>
                )}
                {archive?.policy && (
                  <div className="diag-policy-block">
                    <div className="diag-policy-title">📤 数据归档</div>
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

/* ─── Sub-components ─── */

function Section({ title, badge, children }: { title: string; badge?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="diag-section">
      <div className="diag-section-head">
        <h3 className="diag-section-title">{title}</h3>
        {badge}
      </div>
      {children}
    </div>
  );
}

function Row({ label, value, dim, compact }: { label: string; value: string; dim?: boolean; compact?: boolean }) {
  return (
    <div className={`diag-row ${compact ? "diag-row-compact" : "diag-row-normal"}`}>
      <span className="diag-row-label">{label}</span>
      <span className={`diag-row-value ${dim ? "dim" : "normal"}`}>{value}</span>
    </div>
  );
}

function Dim({ children }: { children: React.ReactNode }) {
  return <div className="diag-dim">{children}</div>;
}

/* ─── Small helpers ─── */

function fmtKey(k: string): string {
  const m: Record<string, string> = {
    runs_max_age_days: "运行保留", runs_max_count: "最大运行",
    traces_max_age_days: "追踪保留", traces_max_count: "最大追踪",
    jobs_max_age_days: "作业保留", artifacts_temp_max_age_days: "临时制品",
    prune_reports: "清理报告",
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
