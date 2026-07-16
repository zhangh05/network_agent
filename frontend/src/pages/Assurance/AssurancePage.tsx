import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  assuranceApi,
  type AssuranceBaseline,
  type AssuranceCheck,
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
import "./AssurancePage.css";

type View = "overview" | "baseline" | "topology" | "incident" | "change" | "continuous";

const VIEWS: Array<[View, string]> = [
  ["overview", "总览"], ["baseline", "状态基线"], ["topology", "影响范围"],
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

function Status({ value }: { value: string }) {
  const labels: Record<string, string> = {
    stable: "稳定", attention: "需关注", compliant: "一致", drifted: "存在漂移",
    unconfigured: "尚未配置",
    partial: "证据不完整", validated: "已校验", blocked: "已阻断", draft: "草稿",
    collecting_precheck: "采集变更前状态", ready_for_change: "等待实施变更",
    collecting_postcheck: "变更后验收中", verified: "验收通过", rollback_required: "建议回退",
    investigating: "调查中", monitoring: "观察中", resolved: "已解决", closed: "已关闭",
    idle: "等待中", collecting: "采集中", completed: "已完成", failed: "失败", cancelled: "已取消",
    confirmed: "已证实", likely: "较可能",
    unverified: "未验证", evidence_based: "有证据",
  };
  const tone = ["stable", "compliant", "validated", "verified", "resolved", "closed", "idle", "completed", "confirmed", "evidence_based"].includes(value) ? "ok"
    : ["drifted", "blocked", "failed", "attention", "rollback_required"].includes(value) ? "danger" : "warn";
  return <span className={`assurance-status ${tone}`}>{labels[value] || value || "未知"}</span>;
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
  const [checks, setChecks] = useState<AssuranceCheck[]>(initialSnapshot?.checks || []);
  const [drifts, setDrifts] = useState<AssuranceDrift[]>(initialSnapshot?.drifts || []);
  const [topology, setTopology] = useState<AssuranceTopology | null>(initialSnapshot?.topology || null);
  const [incidents, setIncidents] = useState<AssuranceIncident[]>(initialSnapshot?.incidents || []);
  const [changes, setChanges] = useState<AssuranceChange[]>(initialSnapshot?.changes || []);
  const [schedules, setSchedules] = useState<AssuranceSchedule[]>(initialSnapshot?.schedules || []);
  const [operations, setOperations] = useState<AssuranceOperation[]>(initialSnapshot?.operations || []);
  const [impact, setImpact] = useState<Record<string, any> | null>(null);
  const [baselineName, setBaselineName] = useState("");
  const [region, setRegion] = useState("");
  const [impactAssets, setImpactAssets] = useState("");
  const [incidentForm, setIncidentForm] = useState({ title: "", symptom: "", drift_id: "" });
  const [changeForm, setChangeForm] = useState<{ title: string; summary: string; asset_ids: string[] }>({ title: "", summary: "", asset_ids: [] });
  const [scheduleForm, setScheduleForm] = useState({ name: "", baseline_id: "", interval: "60" });
  const loadSequence = useRef(0);

  const fail = useCallback((title: string, error: unknown) => {
    const body = error instanceof Error ? error.message : String(error || "请求失败");
    toast({ kind: "error", title, body });
  }, [toast]);

  const applySnapshot = useCallback((snapshot: AssuranceSnapshot) => {
    setOverview(snapshot.overview);
    setBaselines(snapshot.baselines || []);
    setChecks(snapshot.checks || []);
    setDrifts(snapshot.drifts || []);
    setTopology(snapshot.topology || null);
    setIncidents(snapshot.incidents || []);
    setChanges(snapshot.changes || []);
    setSchedules(snapshot.schedules || []);
    setOperations(snapshot.operations || []);
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
      setOverview(null); setBaselines([]); setChecks([]); setDrifts([]); setTopology(null);
      setIncidents([]); setChanges([]); setSchedules([]); setOperations([]);
      setLoading(true);
    }
    setImpact(null);
    setBaselineName(""); setRegion(""); setImpactAssets("");
    setIncidentForm({ title: "", symptom: "", drift_id: "" });
    setChangeForm({ title: "", summary: "", asset_ids: [] });
    setScheduleForm({ name: "", baseline_id: "", interval: "60" });
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
    const active = checks.filter((item) => item.status === "collecting");
    if (!workspaceId || !active.length) return;
    const timer = window.setInterval(async () => {
      try {
        const results = await Promise.all(active.map((item) => assuranceApi.getCheck(workspaceId, item.check_id)));
        const updates = new Map(results.map((result) => [result.check.check_id, result.check]));
        setChecks((current) => current.map((item) => updates.get(item.check_id) || item));
        if (results.some((result) => result.check.status !== "collecting")) await load(true);
      } catch (error) {
        fail("状态检查跟踪失败", error);
      }
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [checks, workspaceId, load, fail]);

  useEffect(() => {
    const active = operations.filter((item) => item.status === "collecting");
    if (!workspaceId || !active.length) return;
    const timer = window.setInterval(async () => {
      try {
        const results = await Promise.all(active.map((item) => assuranceApi.getOperation(workspaceId, item.operation_id)));
        const updates = new Map(results.map((result) => [result.operation.operation_id, result.operation]));
        setOperations((current) => current.map((item) => updates.get(item.operation_id) || item));
        const completedImpact = results.find((result) => result.operation.kind === "impact" && result.operation.status === "completed");
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

  const startCheck = async (baselineId: string) => {
    setBusy(baselineId);
    try {
      const result = await assuranceApi.check({ workspace_id: workspaceId, baseline_id: baselineId });
      setChecks((current) => [result.check, ...current.filter((item) => item.check_id !== result.check.check_id)]);
      toast({ kind: "info", title: "正在采集设备状态", body: "完成巡检后会自动与正常状态比较。" });
    } catch (error) {
      fail("状态检查启动失败", error);
    } finally {
      setBusy("");
    }
  };

  const clearRecords = async () => {
    if (!workspaceId || busy) return;
    const accepted = window.confirm(
      "清除当前工作区的全部网络保障记录？\n\n将删除：基线、漂移、影响分析、故障调查、变更计划、定期检查和保障任务记录。\n将保留：CMDB 资产、巡检任务、巡检原始制品、会话和报告。",
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
      <div className="page-header assurance-header">
        <div>
          <h1>网络保障 <span>· Assurance</span></h1>
          <p className="subtitle">检查网络是否偏离正常状态，定位影响范围，并持续跟踪异常。</p>
        </div>
        <div className="assurance-header-actions">
          {overview && <Status value={!counts.baselines ? "unconfigured" : overview.health} />}
          {loading && overview && <span className="assurance-refreshing">正在更新</span>}
          <button className="btn sm danger-ghost" onClick={() => void clearRecords()} disabled={loading || !!busy} title="清除保障域记录，保留资产、巡检任务和制品">
            <IconTrash size={14} /> 清除记录
          </button>
          <button className="btn sm ghost" onClick={() => void load()} disabled={loading}><IconRefresh size={14} /> 刷新</button>
        </div>
      </div>

      <div className="assurance-nav" role="tablist" aria-label="网络保障视图">
        {VIEWS.map(([id, label]) => <button type="button" role="tab" aria-selected={view === id} key={id} className={view === id ? "active" : ""} onClick={() => setView(id)}>{label}</button>)}
      </div>

      <main className="assurance-body" aria-busy={loading}>
        {loading && !overview ? <AssuranceSkeleton /> : null}
        {!loading && !overview && loadError ? <div className="assurance-empty"><p>网络保障数据暂时无法读取</p><button className="btn" onClick={() => void load()}>重试</button></div> : null}

        {view === "overview" && overview && <>
          <section className={`assurance-hero ${!counts.baselines ? "unconfigured" : overview.health}`}>
            <div>
              <span className="assurance-eyebrow">当前网络状态</span>
              <h2>{!counts.baselines ? "还没有保存网络的正常状态" : overview.health === "stable" ? "当前未发现需要处理的保障问题" : "当前网络存在需要关注的事项"}</h2>
              <p>{!counts.baselines
                ? "尚未建立正常状态基线。完成一次设备巡检后，就可以把当前状态保存为后续检查的参照。"
                : overview.latest_drift
                  ? `最近一次检查为“${overview.latest_drift.status === "compliant" ? "状态一致" : overview.latest_drift.status === "partial" ? "证据不完整" : "发现变化"}”。`
                  : "已经建立基线，尚未执行状态检查。"}</p>
            </div>
            <button className="btn primary" onClick={() => setView("baseline")}>{!counts.baselines ? "保存当前正常状态" : "开始状态检查"}</button>
          </section>
          <section className="assurance-kpis">
            <Metric label="正常状态" value={counts.baselines || 0} note="已保存参照" />
            <Metric label="漂移记录" value={counts.drifts || 0} note="历次对比" />
            <Metric label="待处理故障" value={counts.open_incidents || 0} note="未关闭" tone="warn" />
            <Metric label="变更计划" value={counts.change_plans || 0} note={`${counts.blocked_changes || 0} 项被阻断`} tone={counts.blocked_changes ? "warn" : ""} />
            <Metric label="持续任务" value={counts.enabled_schedules || 0} note={`${counts.schedule_errors || 0} 项异常`} tone={counts.schedule_errors ? "warn" : "ok"} />
            <Metric label="设备关系" value={`${counts.topology_nodes || 0}/${counts.topology_edges || 0}`} note="设备 / 已确认关系" />
          </section>
          <section className="assurance-band">
            <div className="assurance-section-title"><div><h2>最近一次状态检查</h2><p>检查结果来自设备巡检与基线对比。</p></div></div>
            {overview.latest_drift ? <DriftRow drift={overview.latest_drift} /> : <div className="assurance-empty compact">还没有检查记录</div>}
          </section>
          <section className="assurance-next">
            <button onClick={() => setView("baseline")}><IconCheck size={16} /><b>检查状态变化</b><span>比较设备当前状态与正常基线</span></button>
            <button onClick={() => setView("topology")}><IconBolt size={16} /><b>评估设备影响</b><span>选择设备，查看可能波及的范围</span></button>
            <button onClick={() => setView("incident")}><IconShield size={16} /><b>记录并排查故障</b><span>从症状和现有证据开始调查</span></button>
          </section>
        </>}

        {view === "baseline" && <section className="assurance-split">
          <div className="assurance-pane narrow">
            <div className="assurance-section-title"><div><h2>保存正常状态</h2><p>系统会使用所选范围内最近一次成功巡检作为参照。</p></div></div>
            <label>设备范围<select value={region} onChange={(e) => setRegion(e.target.value)}><option value="">最近一次巡检的全部设备</option>{regions.map((item) => <option key={item} value={item}>{item}区域</option>)}</select></label>
            <label>名称（可选）<input value={baselineName} onChange={(e) => setBaselineName(e.target.value)} placeholder={`${region || "当前网络"}正常状态`} /></label>
            <div className="assurance-help">请先在“设备资产”中完成一次巡检。只有完整成功的巡检才能保存为正常状态。</div>
            <button className="btn primary" disabled={!!busy} onClick={() => { const name = baselineName.trim() || `${region || "当前网络"}正常状态`; void run("baseline", () => assuranceApi.createBaseline({ workspace_id: workspaceId, name, scope: region ? { region } : {} }), "正常状态已保存", () => setBaselineName("")); }}>保存为正常状态</button>
          </div>
          <div className="assurance-pane">
            <div className="assurance-section-title"><div><h2>已保存的正常状态</h2><p>点击检查后，系统会重新连接同一范围的设备、执行通用巡检，再与基线比较。</p></div></div>
            <div className="assurance-list">{baselines.length ? baselines.map((item) => {
              const check = checks.find((entry) => entry.baseline_id === item.baseline_id);
              const scopeLabel = [item.scope?.region, item.scope?.location, item.scope?.vendor].filter(Boolean).join(" · ") || "全部设备";
              const progress = check ? `${check.completed_assets || 0}/${check.total_assets || "?"}` : "";
              return <article className="stack" key={item.baseline_id}>
                <div><b>{item.name}</b><span>{scopeLabel} · 保存于 {dateText(item.created_at)}</span></div>
                <button className="btn sm" disabled={!!busy || check?.status === "collecting"} onClick={() => void startCheck(item.baseline_id)}>{check?.status === "collecting" ? `正在巡检 ${progress}` : "重新采集并检查"}</button>
                {check && <div className="assurance-check-progress"><Status value={check.status} /><span>{check.status === "collecting" ? `已完成 ${progress} 台设备` : check.status === "completed" ? `采集完成：成功 ${check.succeeded_assets || 0}，部分 ${check.partial_assets || 0}，失败 ${check.failed_assets || 0}` : check.error || "检查未完成"}</span>{check.inspection_task_id && <small>巡检任务已建立 · {dateText(check.created_at)}</small>}{check.artifact_ids?.length ? <Link className="btn sm" to={`/artifacts?producer_id=${encodeURIComponent(check.inspection_task_id)}`}>查看 {check.artifact_ids.length} 个证据制品</Link> : null}</div>}
              </article>;
            }) : <div className="assurance-empty compact">还没有保存正常状态</div>}</div>
            <h3 className="assurance-subhead">检查历史</h3>
            <div className="assurance-list">{drifts.length ? drifts.slice(0, 8).map((item) => <DriftRow key={item.drift_id} drift={item} />) : <div className="assurance-empty compact">尚无状态检查记录</div>}</div>
          </div>
        </section>}

        {view === "topology" && <section className="assurance-split">
          <div className="assurance-pane narrow">
            <div className="assurance-section-title"><div><h2>选择需要评估的设备</h2><p>系统只沿已经确认的设备关系计算影响范围。</p></div></div>
            <label>设备<select value="" onChange={(e) => { const id = e.target.value; if (id && !selectedImpactIds.includes(id)) setImpactAssets([...selectedImpactIds, id].join(",")); }}><option value="">选择设备</option>{(topology?.nodes || []).filter((node) => !selectedImpactIds.includes(node.asset_id)).map((node) => <option key={node.asset_id} value={node.asset_id}>{node.name || node.host} · {node.region || "未分区"}</option>)}</select></label>
            <div className="assurance-selection">{selectedImpactIds.map((id) => <button key={id} onClick={() => setImpactAssets(selectedImpactIds.filter((item) => item !== id).join(","))}>{nodeNames.get(id) || id}<span>×</span></button>)}</div>
            <div className="assurance-actions"><button className="btn primary" disabled={!impactAssets.trim() || !!busy} onClick={async () => { setBusy("impact"); setImpact(null); try { const res = await assuranceApi.impact(workspaceId, splitIds(impactAssets)); trackOperation(res.operation); toast({ kind: "info", title: "正在采集影响证据", body: "采集完成后会自动计算影响范围。" }); } catch (error) { fail("影响分析启动失败", error); } finally { setBusy(""); } }}>重新采集并分析</button><button className="btn" disabled={!!busy} onClick={async () => { setBusy("topology"); try { const res = await assuranceApi.buildTopology(workspaceId); trackOperation(res.operation); toast({ kind: "info", title: "正在刷新设备关系" }); } catch (error) { fail("拓扑刷新启动失败", error); } finally { setBusy(""); } }}>刷新关系证据</button></div>
            {latestOperation("impact") && <OperationProgress operation={latestOperation("impact")!} />}
            {latestOperation("topology_refresh") && <OperationProgress operation={latestOperation("topology_refresh")!} />}
            {impact && <div className="assurance-result"><Status value={impact.confidence || "unverified"} /><strong>{(impact.affected_assets || []).length} 台受影响资产</strong>{(impact.affected_assets || []).map((item: any) => <span key={item.asset_id}>{item.name || item.host}</span>)}</div>}
          </div>
          <div className="assurance-pane">
            <div className="assurance-section-title"><div><h2>设备关系</h2><p>{topology?.nodes.length || 0} 个节点，{topology?.edges.length || 0} 条证据链路。</p></div><Status value={(topology?.edges.length || 0) ? "evidence_based" : "unverified"} /></div>
            <div className="assurance-topology-nodes">{(topology?.nodes || []).map((node) => <button key={node.asset_id} onClick={() => setImpactAssets(node.asset_id)}><b>{node.name || node.host}</b><span>{node.region || "未分区"} · {node.type || "unknown"}</span></button>)}</div>
            <div className="assurance-edge-table">{(topology?.edges || []).length ? (topology?.edges || []).map((edge) => <div key={edge.edge_id}><span>{nodeNames.get(edge.source)}</span><i>↔</i><span>{nodeNames.get(edge.target)}</span><Status value={edge.confidence} /></div>) : <div className="assurance-empty compact">尚无经过 CMDB 或巡检证实的设备关系</div>}</div>
          </div>
        </section>}

        {view === "incident" && <section className="assurance-split">
          <div className="assurance-pane narrow">
            <div className="assurance-section-title"><div><h2>描述遇到的问题</h2><p>从用户看到的现象开始，系统会结合已有检查证据组织排查。</p></div></div>
            <label>事件标题<input value={incidentForm.title} onChange={(e) => setIncidentForm({ ...incidentForm, title: e.target.value })} placeholder="例如：华东核心出口抖动" /></label>
            <label>已观察症状<textarea value={incidentForm.symptom} onChange={(e) => setIncidentForm({ ...incidentForm, symptom: e.target.value })} placeholder="时间、范围、现象和已知影响" /></label>
            <label>关联检查记录（可选）<select value={incidentForm.drift_id} onChange={(e) => setIncidentForm({ ...incidentForm, drift_id: e.target.value })}><option value="">不关联检查记录</option>{drifts.map((item) => <option key={item.drift_id} value={item.drift_id}>{dateText(item.created_at)} · {item.status === "drifted" ? "发现变化" : item.status === "partial" ? "证据不完整" : "状态一致"}</option>)}</select></label>
            <button className="btn primary" disabled={!incidentForm.title || !incidentForm.symptom || !!busy} onClick={() => run("incident", () => assuranceApi.createIncident({ workspace_id: workspaceId, ...incidentForm }), "已开始采集故障证据", () => setIncidentForm({ title: "", symptom: "", drift_id: "" }))}>采集证据并排查</button>
          </div>
          <div className="assurance-pane"><div className="assurance-section-title"><div><h2>调查队列</h2><p>每次调查先连接目标设备采集，再按证据证实或排除假设。</p></div></div><div className="assurance-list">{incidents.length ? incidents.map((item) => { const operation = item.operation_id ? operations.find((entry) => entry.operation_id === item.operation_id) : undefined; return <article className="stack" key={item.incident_id}><div><b>{item.title}</b><span>{item.symptom}</span>{item.conclusion && <span>{item.conclusion}</span>}</div><Status value={item.status} />{operation && <OperationProgress operation={operation} />}<div className="assurance-hypotheses">{item.hypotheses?.map((hypothesis) => <p key={hypothesis.hypothesis_id}><Status value={hypothesis.confidence} /> {hypothesis.statement}</p>)}</div>{!['resolved','closed'].includes(item.status) && <button className="btn sm" onClick={() => run(item.incident_id, () => assuranceApi.updateIncident(workspaceId, item.incident_id, { status: "resolved" }), "调查已关闭")}>标记已解决</button>}</article>; }) : <div className="assurance-empty compact">暂无故障调查</div>}</div></div>
        </section>}

        {view === "change" && <section className="assurance-split">
          <div className="assurance-pane narrow"><div className="assurance-section-title"><div><h2>准备一次网络变更</h2><p>系统只生成检查和回退方案，不会向设备下发配置。</p></div></div>
            <label>变更标题<input value={changeForm.title} onChange={(e) => setChangeForm({ ...changeForm, title: e.target.value })} /></label>
            <label>变更摘要<textarea value={changeForm.summary} onChange={(e) => setChangeForm({ ...changeForm, summary: e.target.value })} /></label>
            <label>选择目标设备</label><div className="assurance-device-picker">{(topology?.nodes || []).map((node) => <button type="button" className={changeForm.asset_ids.includes(node.asset_id) ? "selected" : ""} key={node.asset_id} onClick={() => toggleChangeAsset(node.asset_id)}><span>{changeForm.asset_ids.includes(node.asset_id) ? "✓" : ""}</span><b>{node.name || node.host}</b><small>{node.region || "未分区"}</small></button>)}</div>
            <button className="btn primary" disabled={!changeForm.title || !changeForm.summary || !changeForm.asset_ids.length || !!busy} onClick={() => run("change", () => assuranceApi.createChange({ workspace_id: workspaceId, title: changeForm.title, summary: changeForm.summary, asset_ids: changeForm.asset_ids }), "变更验证方案已创建", () => setChangeForm({ title: "", summary: "", asset_ids: [] }))}>生成验证方案</button>
          </div>
          <div className="assurance-pane"><div className="assurance-section-title"><div><h2>变更验证闭环</h2><p>先采集变更前状态，实施变更后再采集同一范围并自动比较；系统不会下发配置。</p></div></div><div className="assurance-list">{changes.length ? changes.map((item) => { const pre = item.precheck_operation_id ? operations.find((entry) => entry.operation_id === item.precheck_operation_id) : undefined; const post = item.postcheck_operation_id ? operations.find((entry) => entry.operation_id === item.postcheck_operation_id) : undefined; const active = [pre, post].find((entry) => entry?.status === "collecting"); const visibleOperation = active || post || pre; return <article className="stack" key={item.change_id}><div><b>{item.title}</b><span>{item.summary}</span><span>目标设备：{item.asset_ids.map((id) => nodeNames.get(id) || "未知设备").join("、")}</span></div><Status value={item.status} />{visibleOperation && <OperationProgress operation={visibleOperation} />}<div className="assurance-check-columns"><List title="变更前检查" items={item.prechecks} /><List title="变更后验证" items={item.postchecks} /><List title="需要回退的情况" items={item.rollback_conditions} /></div><div className="assurance-row-actions">{!item.pre_snapshot_id && <button className="btn sm" disabled={!!busy || !!active} onClick={() => run(item.change_id, async () => { const res = await assuranceApi.validateChange(workspaceId, item.change_id); trackOperation(res.operation); }, "正在采集变更前状态")}>采集变更前状态</button>}{item.pre_snapshot_id && !item.post_snapshot_id && <button className="btn sm primary" disabled={!!busy || !!active} onClick={() => run(item.change_id, async () => { const res = await assuranceApi.postcheckChange(workspaceId, item.change_id); trackOperation(res.operation); }, "正在执行变更后验收")}>变更已实施，开始验收</button>}{item.post_snapshot_id && <span>{item.validation?.passed ? "验收通过" : "发现偏差，建议回退或复核"}</span>}</div></article>; }) : <div className="assurance-empty compact">暂无变更验证方案</div>}</div></div>
        </section>}

        {view === "continuous" && <section className="assurance-split">
          <div className="assurance-pane narrow"><div className="assurance-section-title"><div><h2>设置定期检查</h2><p>系统按周期巡检设备，并自动和正常状态比较。</p></div></div>
            <label>任务名称<input value={scheduleForm.name} onChange={(e) => setScheduleForm({ ...scheduleForm, name: e.target.value })} /></label>
            <label>比较基准<select value={scheduleForm.baseline_id} onChange={(e) => setScheduleForm({ ...scheduleForm, baseline_id: e.target.value })}><option value="">选择已保存的正常状态</option>{baselines.map((item) => <option key={item.baseline_id} value={item.baseline_id}>{item.name}</option>)}</select></label>
            <label>检查频率<select value={scheduleForm.interval} onChange={(e) => setScheduleForm({ ...scheduleForm, interval: e.target.value })}><option value="15">每 15 分钟</option><option value="60">每小时</option><option value="360">每 6 小时</option><option value="1440">每天</option><option value="10080">每周</option></select></label>
            <button className="btn primary" disabled={!scheduleForm.baseline_id || !!busy} onClick={() => run("schedule", () => assuranceApi.createSchedule({ workspace_id: workspaceId, name: scheduleForm.name || "定期网络状态检查", baseline_id: scheduleForm.baseline_id, interval_minutes: Number(scheduleForm.interval) }), "定期检查已启用", () => setScheduleForm({ name: "", baseline_id: "", interval: "60" }))}>启用定期检查</button>
          </div>
          <div className="assurance-pane"><div className="assurance-section-title"><div><h2>定期检查任务</h2><p>每次执行都会重新巡检、比较基线并记录结果；查询不会重复创建任务。</p></div></div><div className="assurance-list">{schedules.length ? schedules.map((item) => <article key={item.schedule_id}><div><b>{item.name}</b><span>每 {item.interval_minutes} 分钟 · 下次检查 {dateText(item.next_run_at)}</span><span>已运行 {item.run_count || 0} 次 · 最近结果 {item.last_status || "尚未执行"}{item.consecutive_failures ? ` · 连续异常 ${item.consecutive_failures} 次` : ""}</span>{item.error && <em>最近一次运行异常，请查看系统诊断</em>}</div><div className="assurance-row-actions"><Status value={item.state} />{item.last_artifact_ids?.length && item.last_task_id ? <Link className="btn sm" to={`/artifacts?producer_id=${encodeURIComponent(item.last_task_id)}`}>查看最近证据</Link> : null}<button className="btn sm" disabled={item.state === "collecting" || !!busy} onClick={() => run(`run-${item.schedule_id}`, () => assuranceApi.runSchedule(workspaceId, item.schedule_id), "定期检查已启动")}>立即检查</button><button className="btn sm" onClick={() => run(item.schedule_id, () => assuranceApi.updateSchedule(workspaceId, item.schedule_id, { enabled: !item.enabled }), item.enabled ? "定期检查已暂停" : "定期检查已启用")}>{item.enabled ? "暂停" : "启用"}</button></div></article>) : <div className="assurance-empty compact">暂无定期检查任务</div>}</div></div>
        </section>}
      </main>
    </div>
  );
}

function Metric({ label, value, note, tone = "" }: { label: string; value: string | number; note: string; tone?: string }) {
  return <div className={tone}><span>{label}</span><strong>{value}</strong><small>{note}</small></div>;
}

function AssuranceSkeleton() {
  return <div className="assurance-skeleton" aria-label="正在读取保障状态">
    <div className="assurance-skeleton-hero"><i /><i /><i /></div>
    <div className="assurance-skeleton-kpis">{Array.from({ length: 6 }, (_, index) => <i key={index} />)}</div>
    <div className="assurance-skeleton-band"><i /><i /><i /></div>
  </div>;
}

function DriftRow({ drift }: { drift: AssuranceDrift }) {
  const informational = drift.status === "compliant" && (drift.changes?.length || 0) > 0;
  const title = drift.status === "partial" ? "本次检查证据不完整" : drift.status === "drifted" ? "发现需要关注的设备状态变化" : informational ? "关键状态一致，运行数据有轻微变化" : "设备状态与基线一致";
  return <article className="assurance-drift"><div><b>{title}</b><span>{dateText(drift.created_at)} · {drift.changes?.length || 0} 项观测变化</span></div><div className="assurance-drift-counts"><span className="critical">{drift.summary?.critical || 0} 严重</span><span>{drift.summary?.warning || 0} 警告</span><Status value={drift.status} /></div></article>;
}

function List({ title, items = [] }: { title: string; items?: string[] }) {
  return <div><b>{title}</b>{items.map((item) => <span key={item}>{item}</span>)}</div>;
}

function OperationProgress({ operation }: { operation: AssuranceOperation }) {
  const total = operation.total_assets || 0;
  const completed = operation.completed_assets || 0;
  const label = operation.status === "completed" ? `证据采集已完成 ${completed}/${total || completed}`
    : operation.status === "failed" || operation.status === "cancelled" ? `证据采集${operation.status === "failed" ? "失败" : "已取消"}`
    : operation.phase === "analyzing_evidence" ? "正在分析采集证据" : `正在采集设备状态 ${completed}/${total || "?"}`;
  return <div className="assurance-check-progress"><Status value={operation.status} /><span>{label}</span><small>成功 {operation.succeeded_assets || 0} · 部分 {operation.partial_assets || 0} · 失败 {operation.failed_assets || 0}{operation.artifact_ids?.length ? ` · 证据制品 ${operation.artifact_ids.length}` : ""}</small>{operation.artifact_ids?.length ? <Link className="btn sm" to={`/artifacts?producer_id=${encodeURIComponent(operation.inspection_task_id)}`}>查看本次证据</Link> : null}</div>;
}
