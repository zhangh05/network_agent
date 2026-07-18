import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  assuranceApi,
  type AssuranceBaseline,
  type AssuranceAlarm,
  type AssuranceChange,
  type AssuranceDrift,
  type AssuranceIncident,
  type AssuranceOverview,
  type AssuranceOperation,
  type AssuranceSchedule,
  type AssuranceSnapshot,
  type AssuranceTopology,
} from "../../api";
import { IconBolt, IconCheck, IconRefresh, IconShield, IconTrash } from "../../components/Icon";
import { useSessionStore } from "../../stores/session";
import { useToastStore } from "../../stores/toast";
import { PageHeader } from "../../components/ui";
import "./AssurancePage.css";

type View = "overview" | "baseline" | "topology" | "incident" | "change" | "continuous";

const VIEWS: Array<[View, string]> = [
  ["overview", "总览"], ["baseline", "状态基线"], ["topology", "故障传播分析"],
  ["incident", "故障排查"], ["change", "变更验证"], ["continuous", "定期检查"],
];

const SNAPSHOT_CACHE_PREFIX = "network-agent:assurance:snapshot:";

function readSnapshotCache(workspaceId: string): AssuranceSnapshot | null {
  if (!workspaceId) return null;
  try {
    const value = JSON.parse(window.localStorage.getItem(`${SNAPSHOT_CACHE_PREFIX}${workspaceId}`) || "null");
    return value?.workspace_id === workspaceId && value?.overview ? value as AssuranceSnapshot : null;
  } catch {
    return null;
  }
}

function writeSnapshotCache(snapshot: AssuranceSnapshot) {
  try {
    window.localStorage.setItem(`${SNAPSHOT_CACHE_PREFIX}${snapshot.workspace_id}`, JSON.stringify(snapshot));
  } catch {
    // Storage can be unavailable in privacy mode; live data still works.
  }
}

function dateText(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("zh-CN", { hour12: false });
}

function splitIds(value: string) {
  return [...new Set(value.split(/[\s,，]+/).map((item) => item.trim()).filter(Boolean))];
}

function relationshipLabel(value: string) {
  return ({
    bgp_peer: "BGP 邻居",
    route_next_hop: "路由下一跳",
    connected_subnet: "直连网段",
    cmdb_link: "CMDB 关系",
    observed_neighbor: "巡检邻居",
  } as Record<string, string>)[value] || value;
}

function Status({ value }: { value: string }) {
  const labels: Record<string, string> = {
    stable: "稳定", attention: "需关注", compliant: "一致", drifted: "当前状态偏离权威基线",
    unconfigured: "尚未配置",
    partial: "证据不完整", validated: "已校验", blocked: "已阻断", draft: "草稿",
    collecting_precheck: "采集变更前状态", ready_for_change: "等待实施变更",
    collecting_postcheck: "变更后验收中", verified: "验收通过", rollback_required: "建议回退",
    investigating: "调查中", monitoring: "观察中", resolved: "已解决", closed: "已关闭",
    idle: "等待中", collecting: "采集中", completed: "已完成", failed: "失败", cancelled: "已取消",
    pending: "待确认", open: "告警中",
    critical: "严重", warning: "警告", info: "信息",
    confirmed: "已证实", likely: "较可能",
    unverified: "未验证", evidence_based: "有证据", hypothetical: "故障假设",
    not_confirmed: "本次未确认", alternate_dependency_observed: "发现其他同类依赖（切换未验证）",
    single_dependency_observed: "未发现其他同类依赖", unavailable: "缺少业务映射",
  };
  const tone = ["stable", "compliant", "validated", "verified", "resolved", "closed", "idle", "completed", "confirmed", "evidence_based"].includes(value) ? "ok"
    : ["drifted", "blocked", "failed", "attention", "rollback_required"].includes(value) ? "danger" : "warn";
  return <span className={`assurance-status ${tone}`}>{labels[value] || value || "未知"}</span>;
}

function factValue(value: unknown) {
  if (value === null || value === undefined) return "无";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function deviceText(value: unknown, nodeNames: Map<string, string>) {
  let text = String(value ?? "");
  [...nodeNames.entries()]
    .filter(([assetId, name]) => assetId && name && assetId !== name)
    .sort(([left], [right]) => right.length - left.length)
    .forEach(([assetId, name]) => { text = text.split(assetId).join(name); });
  return text;
}

function IncidentCard({ incident, operation, baselineName, nodeNames, onClose }: {
  incident: AssuranceIncident;
  operation?: AssuranceOperation;
  baselineName: string;
  nodeNames: Map<string, string>;
  onClose: () => void;
}) {
  const analysis = incident.analysis;
  const changes = analysis?.changes || [];
  const llm = analysis?.llm;
  const counts = {
    critical: changes.filter((item) => item.severity === "critical").length,
    warning: changes.filter((item) => item.severity === "warning").length,
    info: changes.filter((item) => item.severity === "info").length,
  };
  const llmMessage = llm?.status === "completed" ? "LLM 已完成证据分析"
    : llm?.status === "skipped" ? `LLM 未调用：${llm.error === "no_structured_anomaly" ? "没有结构化异常可供分析" : llm.error || "不满足调用条件"}`
      : llm?.status ? `LLM 调用失败：${llm.error || llm.status}` : "尚无 LLM 分析结果";
  const llmTone = llm?.status === "completed" ? "ok" : llm?.status === "skipped" ? "warn" : "danger";
  return <article className="stack incident-card">
    <div className="incident-heading">
      <b>{incident.title}</b>
      <span>{incident.symptom}</span>
      {incident.conclusion && <strong>{incident.conclusion}</strong>}
    </div>
    <Status value={incident.status} />
    {operation && <OperationProgress operation={operation} />}

    {analysis ? <div className="incident-analysis">
      <section>
        <h4>比较对象</h4>
        {analysis.baseline_id
          ? <p><b>{baselineName || "正常状态基线"}</b> → 本次故障采集</p>
          : <p className="incident-warning">未找到可用的正常状态基线，本次不能进行状态差异比较。</p>}
        <div className="incident-counts"><span className="critical">严重 {counts.critical}</span><span className="warning">警告 {counts.warning}</span><span>信息 {counts.info}</span></div>
      </section>

      <section className={`incident-llm ${llmTone}`}>
        <h4>{llmMessage}</h4>
        {llm?.status === "completed" && <>
          <p>{deviceText(llm.summary || "LLM 未返回摘要。", nodeNames)}</p>
          {!!llm.ranked_hypotheses?.length && <div className="incident-ranked">
            {llm.ranked_hypotheses.map((hypothesis, index) => <div key={`${index}-${hypothesis.statement}`}>
              <Status value={hypothesis.confidence} />
              <span>{deviceText(hypothesis.statement, nodeNames)}</span>
              {!!hypothesis.evidence_refs?.length && <small>依据：{hypothesis.evidence_refs.join("、")}</small>}
            </div>)}
          </div>}
        </>}
      </section>

      {!!changes.length && <details>
        <summary>查看基线差异明细（{changes.length} 项）</summary>
        <div className="incident-changes">{changes.slice(0, 100).map((change, index) => <div key={`${change.key}-${index}`}>
          <Status value={change.severity || "info"} />
          <span><b>{nodeNames.get(String(change.asset_id)) || change.asset_id || "未知设备"}</b> · {change.resource_id || change.key}</span>
          <small>{change.rationale || "状态发生变化"}：{factValue(change.before)} → {factValue(change.after)}</small>
          {change.evidence_ref && <code>{change.evidence_ref}</code>}
        </div>)}</div>
      </details>}

      {!!incident.hypotheses?.length && <details>
        <summary>规则确认与调查假设（{incident.hypotheses.length} 项）</summary>
        <div className="assurance-hypotheses">{incident.hypotheses.map((hypothesis) => <p key={hypothesis.hypothesis_id}><Status value={hypothesis.confidence} /> {deviceText(hypothesis.statement, nodeNames)}{hypothesis.evidence_ref && <code>{hypothesis.evidence_ref}</code>}</p>)}</div>
      </details>}

      {!!incident.next_actions?.length && <section>
        <h4>下一步排查动作</h4>
        <ol>{incident.next_actions.map((action, index) => <li key={`${index}-${action}`}>{deviceText(action, nodeNames)}</li>)}</ol>
      </section>}

      <div className="incident-evidence-actions">
        {incident.inspection_task_id && <Link className="btn sm" to={`/artifacts?producer_id=${encodeURIComponent(incident.inspection_task_id)}`}>查看本次巡检制品</Link>}
        <span>{incident.evidence_refs?.length || 0} 条证据引用</span>
      </div>
    </div> : operation?.status !== "collecting" ? <div className="incident-warning">本次调查没有生成分析结果。</div> : null}
    {!['resolved', 'closed'].includes(incident.status) && <button className="btn sm" onClick={onClose}>标记已解决</button>}
  </article>;
}

export function AssurancePage() {
  const workspaceId = useSessionStore((state) => state.currentWorkspaceId);
  const toast = useToastStore((state) => state.show);
  const initialSnapshot = useRef(readSnapshotCache(workspaceId)).current;
  const [view, setView] = useState<View>("overview");
  const [loading, setLoading] = useState(!initialSnapshot);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState("");
  const [overview, setOverview] = useState<AssuranceOverview | null>(initialSnapshot?.overview || null);
  const [baselines, setBaselines] = useState<AssuranceBaseline[]>(initialSnapshot?.baselines || []);
  const [drifts, setDrifts] = useState<AssuranceDrift[]>(initialSnapshot?.drifts || []);
  const [topology, setTopology] = useState<AssuranceTopology | null>(initialSnapshot?.topology || null);
  const [incidents, setIncidents] = useState<AssuranceIncident[]>(initialSnapshot?.incidents || []);
  const [changes, setChanges] = useState<AssuranceChange[]>(initialSnapshot?.changes || []);
  const [schedules, setSchedules] = useState<AssuranceSchedule[]>(initialSnapshot?.schedules || []);
  const [alarms, setAlarms] = useState<AssuranceAlarm[]>(initialSnapshot?.alarms || []);
  const [operations, setOperations] = useState<AssuranceOperation[]>(initialSnapshot?.operations || []);
  const [impact, setImpact] = useState<Record<string, any> | null>(null);
  const [baselineName, setBaselineName] = useState("");
  const [region, setRegion] = useState("");
  const [impactAssets, setImpactAssets] = useState("");
  const [impactDriftId, setImpactDriftId] = useState("");
  const [incidentForm, setIncidentForm] = useState({ title: "", symptom: "", drift_id: "" });
  const [changeForm, setChangeForm] = useState<{ title: string; summary: string; asset_ids: string[]; expected: string; invariants: string }>({ title: "", summary: "", asset_ids: [], expected: "", invariants: "" });
  const [scheduleForm, setScheduleForm] = useState({ name: "", baseline_id: "", interval: "60", confirm_after: "2", recover_after: "2" });
  const loadSequence = useRef(0);

  const fail = useCallback((title: string, error: unknown) => {
    const body = error instanceof Error ? error.message : String(error || "请求失败");
    toast({ kind: "error", title, body });
  }, [toast]);

  const applySnapshot = useCallback((snapshot: AssuranceSnapshot) => {
    setOverview(snapshot.overview);
    setBaselines(snapshot.baselines || []);
    setDrifts(snapshot.drifts || []);
    setTopology(snapshot.topology || null);
    setIncidents(snapshot.incidents || []);
    setChanges(snapshot.changes || []);
    setSchedules(snapshot.schedules || []);
    setAlarms(snapshot.alarms || []);
    setOperations(snapshot.operations || []);
    const latestImpact = (snapshot.operations || []).find((item) => item.kind === "fault_propagation" && item.status === "completed");
    setImpact(latestImpact?.result || null);
  }, []);

  const load = useCallback(async (silent = false) => {
    const sequence = ++loadSequence.current;
    if (!workspaceId) {
      setLoading(false);
      return;
    }
    if (!silent) setLoading(true);
    if (!silent) setLoadError("");
    try {
      const response = await assuranceApi.snapshot(workspaceId);
      if (sequence !== loadSequence.current) return;
      applySnapshot(response.snapshot);
      writeSnapshotCache(response.snapshot);
    } catch (error) {
      if (sequence === loadSequence.current) {
        const message = error instanceof Error ? error.message : String(error || "请求失败");
        setLoadError(message);
        if (!silent) fail("网络保障数据加载失败", error);
      }
    } finally {
      if (sequence === loadSequence.current && !silent) setLoading(false);
    }
  }, [workspaceId, fail, applySnapshot]);

  useEffect(() => {
    const cached = readSnapshotCache(workspaceId);
    if (cached) {
      applySnapshot(cached);
      setLoading(false);
    } else {
      setOverview(null); setBaselines([]); setDrifts([]); setTopology(null);
      setIncidents([]); setChanges([]); setSchedules([]); setAlarms([]); setOperations([]);
      setLoading(true);
    }
    setImpact(null);
    setBaselineName(""); setRegion(""); setImpactAssets(""); setImpactDriftId("");
    setIncidentForm({ title: "", symptom: "", drift_id: "" });
    setChangeForm({ title: "", summary: "", asset_ids: [], expected: "", invariants: "" });
    setScheduleForm({ name: "", baseline_id: "", interval: "60", confirm_after: "2", recover_after: "2" });
    void load(Boolean(cached));
    return () => { loadSequence.current += 1; };
  }, [workspaceId, load, applySnapshot]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible" && !busy) void load(true);
    }, 20_000);
    return () => window.clearInterval(timer);
  }, [load, busy]);

  useEffect(() => {
    const active = operations.filter((item) => item.status === "collecting");
    if (!workspaceId || !active.length) return;
    const timer = window.setInterval(async () => {
      try {
        const results = await Promise.all(active.map((item) => assuranceApi.getOperation(workspaceId, item.operation_id)));
        const updates = new Map(results.map((result) => [result.operation.operation_id, result.operation]));
        setOperations((current) => current.map((item) => updates.get(item.operation_id) || item));
        const completedImpact = results.find((result) => result.operation.kind === "fault_propagation" && result.operation.status === "completed");
        if (completedImpact) setImpact(completedImpact.operation.result);
        if (results.some((result) => result.operation.status !== "collecting")) await load(true);
      } catch (error) {
        fail("保障任务跟踪失败", error);
      }
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [operations, workspaceId, load, fail]);

  const run = async (key: string, task: () => Promise<unknown>, success: string, after?: () => void) => {
    setBusy(key);
    try { await task(); after?.(); toast({ kind: "success", title: success }); await load(); }
    catch (error) { fail("操作失败", error); }
    finally { setBusy(""); }
  };

  const clearRecords = async () => {
    if (!workspaceId || busy) return;
    const accepted = window.confirm(
      "清除当前工作区的全部网络保障记录？\n\n将删除：权威基线、异常记录、故障传播分析、故障调查、变更计划、定期检查和保障任务记录。\n将保留：CMDB 资产、巡检任务、巡检原始制品、会话和报告。",
    );
    if (!accepted) return;
    setBusy("clear-records");
    try {
      const result = await assuranceApi.clearRecords(workspaceId);
      setView("overview");
      setImpact(null);
      toast({ kind: "success", title: "保障记录已清除", body: `共清除 ${result.deleted} 条，巡检原始证据与资产未受影响。` });
      await load();
    } catch (error) {
      fail("保障记录清除失败", error);
    } finally {
      setBusy("");
    }
  };

  const trackOperation = (operation: AssuranceOperation) => {
    setOperations((current) => [operation, ...current.filter((item) => item.operation_id !== operation.operation_id)]);
  };

  const counts = overview?.counts || {};
  const nodeNames = useMemo(() => new Map((topology?.nodes || []).map((node) => [node.asset_id, node.name || node.host || node.asset_id])), [topology]);
  const regions = useMemo(() => [...new Set((topology?.nodes || []).map((node) => String(node.region || "").trim()).filter(Boolean))].sort(), [topology]);
  const selectedImpactIds = splitIds(impactAssets);
  const latestOperation = (kind: AssuranceOperation["kind"], refId = "") => operations.find((item) => item.kind === kind && (!refId || item.ref_id === refId));
  const toggleChangeAsset = (assetId: string) => setChangeForm((current) => ({
    ...current,
    asset_ids: current.asset_ids.includes(assetId)
      ? current.asset_ids.filter((item) => item !== assetId)
      : [...current.asset_ids, assetId],
  }));

  return (
    <div className="assurance-page">
      <PageHeader
        title={<>网络保障 <span className="title-suffix">· Assurance</span></>}
        subtitle="确立权威状态，分析故障如何传播，验证变更，并持续跟踪异常。"
        className="assurance-header"
      >
        <div className="assurance-header-actions">
          {overview && <Status value={!counts.baselines ? "unconfigured" : overview.health} />}
          {loading && overview && <span className="assurance-refreshing">正在更新</span>}
          <button className="btn sm danger-ghost" onClick={() => void clearRecords()} disabled={loading || !!busy} title="清除保障域记录，保留资产、巡检任务和制品">
            <IconTrash size={14} /> 清除记录
          </button>
          <button className="btn sm ghost" onClick={() => void load()} disabled={loading}><IconRefresh size={14} /> 刷新</button>
        </div>
      </PageHeader>

      <div className="assurance-nav" role="tablist" aria-label="网络保障视图">
        {VIEWS.map(([id, label]) => <button type="button" role="tab" aria-selected={view === id} key={id} className={view === id ? "active" : ""} onClick={() => setView(id)}>{label}</button>)}
      </div>

      <main className="assurance-body" aria-busy={loading}>
        {loading && !overview ? <AssuranceSkeleton /> : null}
        {!loading && !overview && loadError ? <div className="assurance-empty"><p>网络保障数据暂时无法读取</p><button className="btn" onClick={() => void load()}>重试</button></div> : null}

        {view === "overview" && overview && <>
          <section className={`assurance-hero ${!counts.baselines ? "unconfigured" : overview.health}`}>
            <div>
              <span className="assurance-eyebrow">权威状态基调</span>
              <h2>{!counts.baselines ? "还没有确立权威状态基线" : "权威状态基线已经确立"}</h2>
              <p>{!counts.baselines
                ? "完成一次设备巡检并确认结果后，把该批状态保存为网络保障的权威基调。"
                : "状态基线只负责定调，不执行复检或比较；其他保障功能以它作为权威参照。"}</p>
            </div>
            <button className="btn primary" onClick={() => setView("baseline")}>{!counts.baselines ? "确立权威基线" : "查看权威基线"}</button>
          </section>
          <section className="assurance-kpis">
            <Metric label="权威基线" value={counts.baselines || 0} note="当前状态基调" />
            <Metric label="事实告警" value={counts.open_alarms || 0} note="定期检查确认" tone={counts.open_alarms ? "warn" : "ok"} />
            <Metric label="待处理故障" value={counts.open_incidents || 0} note="未关闭" tone="warn" />
            <Metric label="变更计划" value={counts.change_plans || 0} note={`${counts.blocked_changes || 0} 项被阻断`} tone={counts.blocked_changes ? "warn" : ""} />
            <Metric label="持续任务" value={counts.enabled_schedules || 0} note={`${counts.schedule_errors || 0} 项异常`} tone={counts.schedule_errors ? "warn" : "ok"} />
            <Metric label="设备关系" value={`${counts.topology_nodes || 0}/${counts.topology_edges || 0}`} note={`${counts.topology_evidence_claims || 0} 项关系证据`} />
          </section>
          <section className="assurance-next">
            <button onClick={() => setView("baseline")}><IconCheck size={16} /><b>查看权威状态</b><span>确认状态基调、覆盖范围与来源证据</span></button>
            <button onClick={() => setView("topology")}><IconBolt size={16} /><b>分析故障传播</b><span>从已确认故障或设备故障假设出发，查看传播路径</span></button>
            <button onClick={() => setView("incident")}><IconShield size={16} /><b>记录并排查故障</b><span>从症状和现有证据开始调查</span></button>
          </section>
        </>}

        {view === "baseline" && <section className="assurance-split">
          <div className="assurance-pane narrow">
            <div className="assurance-section-title"><div><h2>确立权威状态基线</h2><p>选择一次已确认的成功巡检，将其设备状态定为网络保障的权威基调。</p></div></div>
            <label>设备范围<select value={region} onChange={(e) => setRegion(e.target.value)}><option value="">最近一次巡检的全部设备</option>{regions.map((item) => <option key={item} value={item}>{item}区域</option>)}</select></label>
            <label>名称（可选）<input value={baselineName} onChange={(e) => setBaselineName(e.target.value)} placeholder={`${region || "当前网络"}正常状态`} /></label>
            <div className="assurance-help">状态基线只负责定调。保存后不会自动复检、比较或产生所谓“基线漂移”；故障传播、故障排查、变更验证和定期检查只能引用它。</div>
            <button className="btn primary" disabled={!!busy || latestOperation("baseline_capture")?.status === "collecting"} onClick={async () => {
              const name = baselineName.trim() || `${region || "当前网络"}正常状态`;
              setBusy("baseline");
              try {
                const response = await assuranceApi.createBaseline({ workspace_id: workspaceId, name, scope: region ? { region } : {} });
                trackOperation(response.operation);
                setBaselineName("");
                toast({ kind: "info", title: "正在采集权威基线", body: "本次将重新巡检所选范围，全部成功并形成完整证据后才会定调。" });
              } catch (error) { fail("权威基线采集启动失败", error); }
              finally { setBusy(""); }
            }}>{latestOperation("baseline_capture")?.status === "collecting" ? "正在采集权威基线" : "重新巡检并确立基线"}</button>
            {latestOperation("baseline_capture") && <OperationProgress operation={latestOperation("baseline_capture")!} />}
          </div>
          <div className="assurance-pane">
            <div className="assurance-section-title"><div><h2>权威状态基线</h2><p>这里只展示已经定调的权威状态、覆盖范围和来源证据，不执行任何比较。</p></div></div>
            <div className="assurance-list">{baselines.length ? baselines.map((item) => {
              const scopeLabel = [item.scope?.region, item.scope?.location, item.scope?.vendor].filter(Boolean).join(" · ") || "全部设备";
              return <article className="stack" key={item.baseline_id}>
                <div><span className="assurance-status ok">权威基线</span><b>{item.name}</b><span>{scopeLabel} · 定调于 {dateText(item.created_at)}</span><span>结构化事实 {item.quality?.typed_fact_count ?? 0} 项 · 覆盖 {(item.quality?.categories || []).join("、") || "暂无分类"}</span><span>来源巡检任务：{item.source_task_id}</span>{item.quality?.evidence_complete === false ? <em>该权威基线的原始证据覆盖不完整：{item.quality.fallback_assets || 0} 台设备仅保留截断片段。后续功能不得把未覆盖事实判成异常。</em> : null}</div>
                {item.source_task_id && <Link className="btn sm" to={`/artifacts?producer_id=${encodeURIComponent(item.source_task_id)}`}>查看基线来源证据</Link>}
              </article>;
            }) : <div className="assurance-empty compact">还没有保存正常状态</div>}</div>
          </div>
        </section>}

        {view === "topology" && <section className="assurance-split">
          <div className="assurance-pane narrow">
            <div className="assurance-section-title"><div><h2>故障从哪里开始</h2><p>选择已确认的故障，或者假设某台设备故障。系统会重新巡检源设备，再沿有证据的依赖关系计算传播。</p></div></div>
            <label>分析方式<select value={impactDriftId} onChange={(e) => { setImpactDriftId(e.target.value); if (e.target.value) setImpactAssets(""); }}><option value="">假设某台设备发生故障</option>{drifts.filter((item) => item.status === "drifted").map((item) => <option key={item.drift_id} value={item.drift_id}>使用已确认异常 · {dateText(item.created_at)} · {item.changes.length} 项</option>)}</select></label>
            {!impactDriftId && <div className="assurance-analysis-note"><b>故障假设</b><span>结果只表示“如果该设备故障，可能传播到哪里”，不会宣称设备当前真的故障。</span></div>}
            {!impactDriftId && <label>假设故障设备<select aria-label="假设故障设备" value="" onChange={(e) => { const id = e.target.value; if (id && !selectedImpactIds.includes(id)) setImpactAssets([...selectedImpactIds, id].join(",")); }}><option value="">选择设备</option>{(topology?.nodes || []).filter((node) => !selectedImpactIds.includes(node.asset_id)).map((node) => <option key={node.asset_id} value={node.asset_id}>{node.name || node.host} · {node.region || "未分区"}</option>)}</select></label>}
            <div className="assurance-selection">{selectedImpactIds.map((id) => <button key={id} onClick={() => setImpactAssets(selectedImpactIds.filter((item) => item !== id).join(","))}>{nodeNames.get(id) || id}<span>×</span></button>)}</div>
            <div className="assurance-actions"><button className="btn primary" disabled={(!impactAssets.trim() && !impactDriftId) || !!busy} onClick={async () => { setBusy("fault-propagation"); setImpact(null); try { const res = await assuranceApi.analyzeFaultPropagation(workspaceId, splitIds(impactAssets), 2, impactDriftId, impactDriftId ? "confirmed" : "hypothetical"); trackOperation(res.operation); toast({ kind: "info", title: "正在分析故障传播", body: "先采集源设备当前证据，再计算传播路径、资源和冗余情况。" }); } catch (error) { fail("故障传播分析启动失败", error); } finally { setBusy(""); } }}>{impactDriftId ? "验证故障并分析传播" : "分析可能传播到哪里"}</button><button className="btn" disabled={!!busy} onClick={async () => { setBusy("topology"); try { const res = await assuranceApi.buildTopology(workspaceId); trackOperation(res.operation); toast({ kind: "info", title: "正在刷新设备依赖", body: "本次采集完成后会形成一份新快照，不会累加到当前关系中。" }); } catch (error) { fail("设备依赖刷新失败", error); } finally { setBusy(""); } }}>重新采集传播依据</button></div>
            {latestOperation("fault_propagation") && <OperationProgress operation={latestOperation("fault_propagation")!} />}
            {latestOperation("topology_refresh") && <OperationProgress operation={latestOperation("topology_refresh")!} />}
            {impact && <ImpactResult result={impact} nodeNames={nodeNames} />}
          </div>
          <div className="assurance-pane">
            <div className="assurance-section-title"><div><h2>传播依据</h2><p>{topology?.nodes.length || 0} 台设备，{topology?.edges.length || 0} 组设备关系，{topology?.evidence_claims?.length || 0} 项原始证据。它只用于计算传播，不会改写权威基线。</p></div><Status value={(topology?.edges.length || 0) ? "evidence_based" : "unverified"} /></div>
            <div className="assurance-analysis-note"><b>LLM 未调用</b><span>设备关系由 BGP 邻居、路由下一跳、直连网段和 CMDB 证据确定性建图，LLM 不参与创造或确认链路。</span></div>
            <div className="assurance-topology-nodes">{(topology?.nodes || []).map((node) => <button key={node.asset_id} onClick={() => setImpactAssets(node.asset_id)}><b>{node.name || node.host}</b><span>{node.region || "未分区"} · {node.type || "unknown"}</span></button>)}</div>
            <div className="assurance-edge-table">{(topology?.edges || []).length ? (topology?.edges || []).map((edge) => <div key={edge.edge_id}><span>{nodeNames.get(edge.source)}</span><i>↔</i><span>{nodeNames.get(edge.target)}</span><Status value={edge.confidence} /><small>{(edge.relationship_types || []).map(relationshipLabel).join(" · ") || "设备关系"} · {edge.claim_count || 0} 项证据</small></div>) : <div className="assurance-empty compact">尚无经过 CMDB 或巡检证实的设备关系</div>}</div>
          </div>
        </section>}

        {view === "incident" && <section className="assurance-split">
          <div className="assurance-pane narrow">
            <div className="assurance-section-title"><div><h2>描述遇到的问题</h2><p>从用户看到的现象开始，系统会结合已有检查证据组织排查。</p></div></div>
            <label>事件标题<input value={incidentForm.title} onChange={(e) => setIncidentForm({ ...incidentForm, title: e.target.value })} placeholder="例如：华东核心出口抖动" /></label>
            <label>已观察症状<textarea value={incidentForm.symptom} onChange={(e) => setIncidentForm({ ...incidentForm, symptom: e.target.value })} placeholder="时间、范围、现象和已知影响" /></label>
            <label>关联检查记录（可选）<select value={incidentForm.drift_id} onChange={(e) => setIncidentForm({ ...incidentForm, drift_id: e.target.value })}><option value="">不关联检查记录</option>{drifts.map((item) => <option key={item.drift_id} value={item.drift_id}>{dateText(item.created_at)} · {item.status === "drifted" ? "发现变化" : item.status === "partial" ? "证据不完整" : "状态一致"}</option>)}</select></label>
            {!baselines.length && <div className="assurance-help">请先建立状态基线。没有 B0，调查只能记录现象，无法判断当前事实是否异常。</div>}
            <button className="btn primary" disabled={!baselines.length || !incidentForm.title || !incidentForm.symptom || !!busy} onClick={() => run("incident", () => assuranceApi.createIncident({ workspace_id: workspaceId, ...incidentForm }), "已开始采集故障证据", () => setIncidentForm({ title: "", symptom: "", drift_id: "" }))}>采集证据并排查</button>
          </div>
          <div className="assurance-pane"><div className="assurance-section-title"><div><h2>调查队列</h2><p>展示基线差异、规则判断、LLM 分析、证据和下一步动作。</p></div></div><div className="assurance-list incident-list">{incidents.length ? incidents.map((item) => <IncidentCard
            key={item.incident_id}
            incident={item}
            operation={item.operation_id ? operations.find((entry) => entry.operation_id === item.operation_id) : undefined}
            baselineName={baselines.find((entry) => entry.baseline_id === item.analysis?.baseline_id)?.name || ""}
            nodeNames={nodeNames}
            onClose={() => run(item.incident_id, () => assuranceApi.updateIncident(workspaceId, item.incident_id, { status: "resolved" }), "调查已关闭")}
          />) : <div className="assurance-empty compact">暂无故障调查</div>}</div></div>
        </section>}

        {view === "change" && <section className="assurance-split">
          <div className="assurance-pane narrow"><div className="assurance-section-title"><div><h2>准备一次网络变更</h2><p>系统只生成检查和回退方案，不会向设备下发配置。</p></div></div>
            <label>变更标题<input value={changeForm.title} onChange={(e) => setChangeForm({ ...changeForm, title: e.target.value })} /></label>
            <label>变更摘要<textarea value={changeForm.summary} onChange={(e) => setChangeForm({ ...changeForm, summary: e.target.value })} /></label>
            <label>预期会变化的事实（每行一个键，可用 *）<textarea value={changeForm.expected} onChange={(e) => setChangeForm({ ...changeForm, expected: e.target.value })} placeholder="例如：asset.asset_id.route.20.0.0.0_24" /></label>
            <label>绝不能变化的事实（每行一个键，可用 *）<textarea value={changeForm.invariants} onChange={(e) => setChangeForm({ ...changeForm, invariants: e.target.value })} placeholder="例如：asset.asset_id.protocol.bgp.peer.*.state" /></label>
            <label>选择目标设备</label><div className="assurance-device-picker">{(topology?.nodes || []).map((node) => <button type="button" className={changeForm.asset_ids.includes(node.asset_id) ? "selected" : ""} key={node.asset_id} onClick={() => toggleChangeAsset(node.asset_id)}><span>{changeForm.asset_ids.includes(node.asset_id) ? "✓" : ""}</span><b>{node.name || node.host}</b><small>{node.region || "未分区"}</small></button>)}</div>
            <button className="btn primary" disabled={!changeForm.title || !changeForm.summary || !changeForm.asset_ids.length || !!busy} onClick={() => run("change", () => assuranceApi.createChange({ workspace_id: workspaceId, title: changeForm.title, summary: changeForm.summary, asset_ids: changeForm.asset_ids, expected_changes: changeForm.expected.split("\n").map((key_pattern) => key_pattern.trim()).filter(Boolean).map((key_pattern) => ({ key_pattern, required: true })), invariants: changeForm.invariants.split("\n").map((key_pattern) => key_pattern.trim()).filter(Boolean).map((key_pattern) => ({ key_pattern, required: true })) }), "变更验证方案已创建", () => setChangeForm({ title: "", summary: "", asset_ids: [], expected: "", invariants: "" }))}>生成验证方案</button>
          </div>
          <div className="assurance-pane"><div className="assurance-section-title"><div><h2>变更验证闭环</h2><p>B0 判断变更前是否健康，P0/P1 按预期变化契约验收；规则、LLM 与证据结果全部展示。</p></div></div><div className="assurance-list">{changes.length ? changes.map((item) => {
            const pre = item.precheck_operation_id ? operations.find((entry) => entry.operation_id === item.precheck_operation_id) : undefined;
            const post = item.postcheck_operation_id ? operations.find((entry) => entry.operation_id === item.postcheck_operation_id) : undefined;
            const active = [pre, post].find((entry) => entry?.status === "collecting");
            return <ChangeCard key={item.change_id} item={item} operation={active || post || pre} active={Boolean(active)} busy={Boolean(busy)} hasBaseline={Boolean(baselines.length)} nodeNames={nodeNames} baselineName={baselines.find((entry) => entry.baseline_id === item.validation?.baseline_id)?.name || ""} onPrecheck={() => run(item.change_id, async () => { const res = await assuranceApi.validateChange(workspaceId, item.change_id); trackOperation(res.operation); }, "正在采集变更前状态")} onPostcheck={() => run(item.change_id, async () => { const res = await assuranceApi.postcheckChange(workspaceId, item.change_id); trackOperation(res.operation); }, "正在执行变更后验收")} />;
          }) : <div className="assurance-empty compact">暂无变更验证方案</div>}</div></div>
        </section>}

        {view === "continuous" && <section className="assurance-split">
          <div className="assurance-pane narrow"><div className="assurance-section-title"><div><h2>设置定期检查</h2><p>系统按周期巡检设备，并自动和正常状态比较。</p></div></div>
            <label>任务名称<input value={scheduleForm.name} onChange={(e) => setScheduleForm({ ...scheduleForm, name: e.target.value })} /></label>
            <label>比较基准<select value={scheduleForm.baseline_id} onChange={(e) => setScheduleForm({ ...scheduleForm, baseline_id: e.target.value })}><option value="">选择已保存的正常状态</option>{baselines.map((item) => <option key={item.baseline_id} value={item.baseline_id}>{item.name}</option>)}</select></label>
            <label>检查频率<select value={scheduleForm.interval} onChange={(e) => setScheduleForm({ ...scheduleForm, interval: e.target.value })}><option value="15">每 15 分钟</option><option value="60">每小时</option><option value="360">每 6 小时</option><option value="1440">每天</option><option value="10080">每周</option></select></label>
            <label>连续异常几次后告警<select value={scheduleForm.confirm_after} onChange={(e) => setScheduleForm({ ...scheduleForm, confirm_after: e.target.value })}><option value="1">1 次</option><option value="2">2 次</option><option value="3">3 次</option></select></label>
            <label>连续恢复几次后关闭<select value={scheduleForm.recover_after} onChange={(e) => setScheduleForm({ ...scheduleForm, recover_after: e.target.value })}><option value="1">1 次</option><option value="2">2 次</option><option value="3">3 次</option></select></label>
            <button className="btn primary" disabled={!scheduleForm.baseline_id || !!busy} onClick={() => run("schedule", () => assuranceApi.createSchedule({ workspace_id: workspaceId, name: scheduleForm.name || "定期网络状态检查", baseline_id: scheduleForm.baseline_id, interval_minutes: Number(scheduleForm.interval), confirm_after: Number(scheduleForm.confirm_after), recover_after: Number(scheduleForm.recover_after) }), "持续保障已启用", () => setScheduleForm({ name: "", baseline_id: "", interval: "60", confirm_after: "2", recover_after: "2" }))}>启用持续保障</button>
          </div>
          <div className="assurance-pane"><div className="assurance-section-title"><div><h2>持续保障任务</h2><p>每轮重新采集并与指定 B0 对比；最近结果、差异、证据与告警均可追溯。</p></div></div><div className="assurance-list">{schedules.length ? schedules.map((item) => <ScheduleCard key={item.schedule_id} item={item} baselineName={baselines.find((entry) => entry.baseline_id === item.baseline_id)?.name || ""} drift={drifts.find((entry) => entry.drift_id === item.last_drift_id)} nodeNames={nodeNames} busy={Boolean(busy)} onRun={() => run(`run-${item.schedule_id}`, () => assuranceApi.runSchedule(workspaceId, item.schedule_id), "持续检查已启动")} onToggle={() => run(item.schedule_id, () => assuranceApi.updateSchedule(workspaceId, item.schedule_id, { enabled: !item.enabled }), item.enabled ? "持续保障已暂停" : "持续保障已启用")} />) : <div className="assurance-empty compact">暂无持续保障任务</div>}</div><h3 className="assurance-subhead">事实告警</h3><div className="assurance-list">{alarms.filter((item) => item.state !== "resolved").map((item) => <article className="alarm-card" key={item.alarm_id}><div><b>{nodeNames.get(item.asset_id) || item.asset_id} · {item.fact_key}</b><span>连续命中 {item.consecutive_hits} 次 · 连续恢复 {item.consecutive_clears} 次 · {dateText(item.last_seen_at)}</span><span>{factValue(item.latest_change?.before)} → {factValue(item.latest_change?.after)}</span>{item.latest_change?.evidence_ref && <code>{String(item.latest_change.evidence_ref)}</code>}</div><Status value={item.state} /></article>)}</div></div>
        </section>}
      </main>
    </div>
  );
}

function Metric({ label, value, note, tone = "" }: { label: string; value: string | number; note: string; tone?: string }) {
  return <div className={tone}><span>{label}</span><strong>{value}</strong><small>{note}</small></div>;
}

function LlmResult({ llm, nodeNames = new Map(), emptyText = "该环节由确定性规则计算，当前未调用 LLM。" }: { llm?: Record<string, any>; nodeNames?: Map<string, string>; emptyText?: string }) {
  if (!llm) return <div className="assurance-analysis-note"><b>LLM 未调用</b><span>{emptyText}</span></div>;
  const skippedReason = llm.error === "no_confirmed_open_alarm" ? emptyText
    : llm.error === "no_structured_changes" ? "没有结构化变化可供分析。"
      : llm.error === "no_evidence_based_propagation" ? "没有基于证据的传播路径可供分析。" : llm.error;
  if (llm.status !== "completed") return <div className="assurance-analysis-note warn"><b>{llm.status === "skipped" ? "LLM 未调用" : "LLM 调用未完成"}</b><span>{skippedReason || llm.status || "没有返回结果"}</span></div>;
  return <div className="assurance-analysis-note ok"><b>LLM 已完成证据分析</b><span>{deviceText(llm.summary || "已完成，但没有返回摘要。", nodeNames)}</span>{(llm.ranked_hypotheses || []).map((item: any, index: number) => <small key={`${index}-${item.statement}`}>{index + 1}. {deviceText(item.statement, nodeNames)}{item.evidence_refs?.length ? `（依据：${item.evidence_refs.join("、")}）` : ""}</small>)}</div>;
}

function EvidenceChanges({ changes = [], nodeNames, title = "查看差异明细" }: { changes?: Array<Record<string, any>>; nodeNames: Map<string, string>; title?: string }) {
  if (!changes.length) return <div className="assurance-analysis-note"><b>没有状态差异</b><span>规则引擎未发现可展示的事实变化。</span></div>;
  return <details className="assurance-evidence-details"><summary>{title}（{changes.length} 项）</summary><div className="incident-changes">{changes.slice(0, 100).map((change, index) => <div key={`${change.key}-${index}`}><Status value={String(change.severity || "info")} /><span><b>{nodeNames.get(String(change.asset_id)) || change.asset_id || "未知设备"}</b> · {change.resource_id || change.key}</span><small>{change.rationale || "状态发生变化"}：{factValue(change.before)} → {factValue(change.after)}</small>{change.evidence_ref && <code>{String(change.evidence_ref)}</code>}</div>)}</div></details>;
}

function ImpactResult({ result, nodeNames }: { result: Record<string, any>; nodeNames: Map<string, string> }) {
  const validation = result.source_validation || {};
  const resources = result.affected_resources || [];
  const services = result.business_services || [];
  return <div className="assurance-result impact-result">
    <div className="assurance-result-heading"><Status value={validation.status || result.confidence || "unverified"} /><strong>{(result.affected_assets || []).length} 台可能受传播设备</strong></div>
    <span>{result.conclusion}</span>
    <span>故障源：{(result.source_assets || []).map((id: string) => nodeNames.get(id) || id).join("、") || "未指定"}</span>
    <div className="assurance-analysis-note"><b>{validation.mode === "hypothetical" ? "假设分析" : "故障确认"}</b><span>{validation.message || "尚无源设备验证结果"}{validation.baseline_id ? ` · 权威基线 ${validation.baseline_id}` : ""}</span></div>
    <span>传播计算使用 {result.edge_count || 0} 组设备关系、{result.evidence_claim_count || 0} 项关系证据、{result.dependency_count || 0} 条有向依赖。</span>
    {(result.propagation || []).map((item: any) => <div className="impact-path" key={`${item.asset_id}-${item.layer}`}><b>{item.layer === 1 ? "直接传播" : `间接传播 ${item.layer}`}</b><span>{(item.path || []).map((id: string) => nodeNames.get(id) || id).join(" → ")}</span><small>{(item.via || []).map(relationshipLabel).join("、")} · 证据 {item.evidence_refs?.length || 0} 项 · <Status value={item.redundancy?.status || "unverified"} />{item.redundancy?.alternate_sources?.length ? `：${item.redundancy.alternate_sources.map((id: string) => nodeNames.get(id) || id).join("、")}` : ""}</small></div>)}
    <EvidenceChanges changes={result.trigger_changes || []} nodeNames={nodeNames} title="查看故障源确认事实" />
    <details className="assurance-evidence-details"><summary>查看可能受影响的网络资源（{resources.length} 项）</summary><div className="incident-changes">{resources.length ? resources.slice(0, 100).map((item: any, index: number) => <div key={`${item.asset_id}-${item.resource_type}-${item.resource_id}-${index}`}><Status value="info" /><span><b>{nodeNames.get(String(item.asset_id)) || item.asset_id}</b> · {item.resource_type}</span><small>{item.resource_id}</small>{item.evidence_refs?.[0] && <code>{item.evidence_refs[0]}</code>}</div>) : <p>没有从巡检证据中提取到资源。</p>}</div></details>
    <div className="assurance-analysis-note"><b>业务影响</b><span>{services.length ? `CMDB 映射到 ${services.length} 项业务：${services.map((item: any) => item.service).join("、")}` : result.business_impact?.reason || "没有业务映射，不能判断客户或业务影响。"}</span></div>
    <LlmResult llm={result.llm} nodeNames={nodeNames} emptyText="没有足够的故障传播证据，LLM 未参与解释。" />
  </div>;
}

function AssuranceSkeleton() {
  return <div className="assurance-skeleton" aria-label="正在读取保障状态">
    <div className="assurance-skeleton-hero"><i /><i /><i /></div>
    <div className="assurance-skeleton-kpis">{Array.from({ length: 6 }, (_, index) => <i key={index} />)}</div>
    <div className="assurance-skeleton-band"><i /><i /><i /></div>
  </div>;
}

function ChangeCard({ item, operation, active, busy, hasBaseline, nodeNames, baselineName, onPrecheck, onPostcheck }: {
  item: AssuranceChange;
  operation?: AssuranceOperation;
  active: boolean;
  busy: boolean;
  hasBaseline: boolean;
  nodeNames: Map<string, string>;
  baselineName: string;
  onPrecheck: () => void;
  onPostcheck: () => void;
}) {
  const validation = item.validation || {};
  const postChecked = Boolean(item.post_snapshot_id);
  const expected = validation.expected_results || [];
  return <article className="stack change-card">
    <div><b>{item.title}</b><span>{item.summary}</span><span>目标设备：{item.asset_ids.map((id) => nodeNames.get(id) || "未知设备").join("、")}</span><span>预期变化 {item.expected_changes?.length || 0} 条 · 不变量 {item.invariants?.length || 0} 条</span></div>
    <Status value={item.status} />
    {operation && <OperationProgress operation={operation} />}
    <div className="assurance-check-columns"><List title="变更前检查" items={item.prechecks} /><List title="变更后验证" items={item.postchecks} /><List title="需要回退的情况" items={item.rollback_conditions} /></div>
    {!!Object.keys(validation).length && <div className="change-analysis">
      <section><h4>比较对象</h4><p>{postChecked ? "变更前状态 → 变更后状态" : `${baselineName || "正常状态基线"} → 变更前状态`}</p></section>
      {!postChecked && <>
        <div className="incident-counts"><span className="critical">阻断项 {(validation.blockers || []).length}</span><span>基线差异 {(validation.baseline_deviations || []).length}</span></div>
        <EvidenceChanges changes={validation.baseline_deviations || []} nodeNames={nodeNames} title="查看变更前基线差异" />
        <LlmResult emptyText="变更前准入只按基线偏差和阻断规则判断，LLM 不参与放行。" />
      </>}
      {postChecked && <>
        <div className="change-contract-result">
          <span>预期契约 {expected.length} 条</span><span>缺失预期 {(validation.missing_expected || []).length} 条</span><span>不变量违例 {(validation.invariant_violations || []).length} 条</span><span>非预期变化 {(validation.unexpected_changes || []).length} 条</span>
        </div>
        {!!expected.length && <details className="assurance-evidence-details"><summary>查看预期变化匹配结果</summary>{expected.map((contract: any, index: number) => <p key={`${index}-${contract.key_pattern}`}><code>{contract.key_pattern}</code>：匹配 {(contract.matched_changes || []).length} 项{contract.required ? " · 必须发生" : ""}</p>)}</details>}
        <EvidenceChanges changes={validation.changes || []} nodeNames={nodeNames} title="查看变更前后全部差异" />
        <LlmResult llm={validation.llm} nodeNames={nodeNames} emptyText="没有结构化变化，因此未调用 LLM。" />
      </>}
    </div>}
    <div className="assurance-row-actions">
      {!item.pre_snapshot_id && <button className="btn sm" disabled={busy || active || !hasBaseline} onClick={onPrecheck}>采集变更前状态</button>}
      {item.pre_snapshot_id && item.status === "ready_for_change" && !item.post_snapshot_id && <button className="btn sm primary" disabled={busy || active} onClick={onPostcheck}>变更已实施，开始验收</button>}
      {postChecked && <span>{validation.passed ? "验收通过" : `验收未通过：不变量违例 ${(validation.invariant_violations || []).length}，非预期变化 ${(validation.unexpected_changes || []).length}`}</span>}
    </div>
  </article>;
}

function ScheduleCard({ item, baselineName, drift, nodeNames, busy, onRun, onToggle }: {
  item: AssuranceSchedule;
  baselineName: string;
  drift?: AssuranceDrift;
  nodeNames: Map<string, string>;
  busy: boolean;
  onRun: () => void;
  onToggle: () => void;
}) {
  return <article className="stack schedule-card">
    <div><b>{item.name}</b><span>比较基准：{baselineName || item.baseline_id}</span><span>每 {item.interval_minutes} 分钟 · 下次检查 {dateText(item.next_run_at)}</span><span>告警确认 {item.confirm_after || 2} 次 · 恢复确认 {item.recover_after || 2} 次 · 当前打开 {item.open_alarm_count || 0} 条</span><span>已运行 {item.run_count || 0} 次 · 最近结果 {item.last_status || "尚未执行"}</span>{item.error && <em>最近一次运行失败：{item.error}</em>}</div>
    <Status value={item.state} />
    {drift && <div className="schedule-latest"><b>最近一轮：{dateText(drift.created_at)}</b><span>严重 {drift.summary?.critical || 0} · 警告 {drift.summary?.warning || 0} · 信息 {drift.summary?.info || 0}</span><EvidenceChanges changes={drift.changes as Array<Record<string, any>>} nodeNames={nodeNames} title="查看最近一轮基线差异" /><LlmResult llm={item.last_analysis} nodeNames={nodeNames} emptyText="正常轮次不调用 LLM；告警达到连续确认门槛后才调用 LLM 归纳关联和处置优先级。" /></div>}
    {!drift && item.run_count > 0 && <div className="incident-warning">最近检查没有可读取的基线差异记录。</div>}
    <div className="assurance-row-actions">{item.last_artifact_ids?.length && item.last_task_id ? <Link className="btn sm" to={`/artifacts?producer_id=${encodeURIComponent(item.last_task_id)}`}>查看最近证据</Link> : null}<button className="btn sm" disabled={item.state === "collecting" || busy} onClick={onRun}>立即检查</button><button className="btn sm" onClick={onToggle}>{item.enabled ? "暂停" : "启用"}</button></div>
  </article>;
}

function List({ title, items = [] }: { title: string; items?: string[] }) {
  return <div><b>{title}</b>{items.map((item) => <span key={item}>{item}</span>)}</div>;
}

function OperationProgress({ operation }: { operation: AssuranceOperation }) {
  const total = operation.total_assets || 0;
  const completed = operation.completed_assets || 0;
  const subject = operation.kind === "baseline_capture" ? "权威基线采集" : "证据采集";
  const label = operation.status === "completed" ? `${subject}已完成 ${completed}/${total || completed}`
    : operation.status === "failed" || operation.status === "cancelled" ? (operation.error || `${subject}${operation.status === "failed" ? "失败" : "已取消"}`)
    : operation.phase === "analyzing_evidence" ? "正在分析采集证据" : `正在重新巡检设备 ${completed}/${total || "?"}`;
  return <div className="assurance-check-progress"><Status value={operation.status} /><span>{label}</span><small>成功 {operation.succeeded_assets || 0} · 部分 {operation.partial_assets || 0} · 失败 {operation.failed_assets || 0}{operation.artifact_ids?.length ? ` · 证据制品 ${operation.artifact_ids.length}` : ""}</small>{operation.artifact_ids?.length ? <Link className="btn sm" to={`/artifacts?producer_id=${encodeURIComponent(operation.inspection_task_id)}`}>查看本次证据</Link> : null}</div>;
}
