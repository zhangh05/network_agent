/**
 * InspectionPage — CMDB-driven device health inspection.
 *
 * UX shape (v3.9.13 follow-up):
 *   - Top section: profile cards (5 presets).
 *   - Middle section: scope form (region / location / type / vendor / tag / limit).
 *   - Bottom section: trigger button + task list with summary stats.
 *
 * Refuses to expose device passwords — the runner resolves them
 * server-side via exec.run(asset_id=...). The LLM and the page
 * never touch credentials.
 */

import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import { useSessionStore } from "../../stores/session";
import {
  inspectionApi,
  type InspectionProfile,
  type InspectionScope,
} from "../../api";

const TYPE_LABEL: Record<string, string> = {
  "": "所有类型", switch: "交换机", router: "路由器", firewall: "防火墙",
  server: "服务器", load_balancer: "负载均衡", wireless: "无线", other: "其他",
};

// Common CMDB tag chips (the operator can still type a custom one).
const TAG_PRESETS = ["核心", "汇聚", "接入", "边缘", "DMZ", "备份", "灾备"];

const SEVERITY_COLOR: Record<string, string> = {
  critical: "var(--danger)",
  warning: "#d97706",
  info: "var(--info)",
  ok: "var(--ok)",
};

const STATUS_COLOR: Record<string, string> = {
  pending: "var(--text-3)", running: "var(--info)", succeeded: "var(--ok)",
  partial: "#d97706", failed: "var(--danger)", cancelled: "var(--text-3)",
};

const STATUS_LABEL: Record<string, string> = {
  pending: "等待中", running: "运行中", succeeded: "已完成",
  partial: "部分完成", failed: "已失败", cancelled: "已取消",
};

// Profile id → human category chip
const PROFILE_TINT: Record<string, string> = {
  basic_health: "var(--info-soft)",
  interface_health: "#dbeafe",
  routing_health: "#ede9fe",
  config_backup: "#fef3c7",
  full_basic: "#fce7f3",
};

const PROFILE_TINT_TEXT: Record<string, string> = {
  basic_health: "var(--info)",
  interface_health: "#1e40af",
  routing_health: "#7e22ce",
  config_backup: "#92400e",
  full_basic: "#be185d",
};

// ── tiny summary cell ──────────────────────────────────────────────
function SummaryCell({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ textAlign: "center", minWidth: 64, padding: "4px 8px" }}>
      <div style={{ fontSize: 18, fontWeight: 700, color, lineHeight: 1.2 }}>{value}</div>
      <div style={{ fontSize: 11, color: "var(--text-4)", marginTop: 2 }}>{label}</div>
    </div>
  );
}

interface TaskRow {
  task_id: string;
  profile_id: string;
  profile_display_name: string;
  status: string;
  started_at: string;
  finished_at: string;
  total_assets: number;
  succeeded: number;
  failed: number;
  skipped: number;
  warnings: number;
  criticals: number;
  infos: number;
  error: string;
  scope: InspectionScope;
}

interface ProfileList {
  ok: boolean;
  profiles: InspectionProfile[];
  count: number;
}

export function InspectionPage() {
  const wsId = useSessionStore((s) => s.currentWorkspaceId);

  const [profileResp, setProfileResp] = useState<ProfileList | null>(null);
  const [profileErr, setProfileErr] = useState<string>("");
  const [selectedProfile, setSelectedProfile] = useState<string>("basic_health");

  const [scope, setScope] = useState<InspectionScope>({
    region: "",
    location: "",
    type: "",
    vendor: "",
    tags: [],
    asset_ids: [],
    limit: 20,
  });
  const uScope = (k: keyof InspectionScope, v: string) => {
    setScope((p) => ({ ...p, [k]: k === "limit" ? Math.max(1, parseInt(v || "1", 10) || 20) : v }));
  };

  const [tag, setTag] = useState("");
  const toggleTag = (t: string) => {
    setScope((p) => ({
      ...p,
      tags: p.tags.includes(t) ? p.tags.filter((x) => x !== t) : [...p.tags, t],
    }));
  };

  const [running, setRunning] = useState(false);
  const [createErr, setCreateErr] = useState<string>("");
  const [lastTaskId, setLastTaskId] = useState<string>("");

  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [tasksErr, setTasksErr] = useState<string>("");
  const [openReportTaskId, setOpenReportTaskId] = useState<string>("");
  const [reportMd, setReportMd] = useState<string>("");
  const [reportErr, setReportErr] = useState<string>("");

  // ── load profiles on workspace change ──
  useEffect(() => {
    if (!wsId) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await inspectionApi.listProfiles(wsId);
        if (cancelled) return;
        if (r.ok) {
          setProfileResp(r);
          setProfileErr("");
          const ids = r.profiles.map((p) => p.profile_id);
          if (!ids.includes(selectedProfile) && ids.length > 0) {
            setSelectedProfile(ids[0]);
          }
        } else {
          setProfileErr("后端未返回 profile 列表");
        }
      } catch (e) {
        if (!cancelled) setProfileErr(String(e));
      }
    })();
    return () => { cancelled = true; };
  }, [wsId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── load recent tasks ──
  const loadTasks = useCallback(async () => {
    if (!wsId) return;
    try {
      const r = await inspectionApi.listTasks(wsId, 30);
      if (r.ok) {
        setTasks(r.items as TaskRow[]);
        setTasksErr("");
      } else {
        setTasksErr("加载任务列表失败");
      }
    } catch (e) {
      setTasksErr(String(e));
    }
  }, [wsId]);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  // ── run trigger ──
  const run = useCallback(async () => {
    if (!wsId || !selectedProfile) return;
    setRunning(true);
    setCreateErr("");
    try {
      const r = await inspectionApi.createTask({
        workspace_id: wsId,
        profile_id: selectedProfile,
        scope,
      });
      if (!r.ok) {
        setCreateErr(r.error || "巡检任务创建失败");
        setRunning(false);
        return;
      }
      setLastTaskId(r.task_id);
      setOpenReportTaskId(r.task_id);
      setRunning(false);
      // refresh list — runner is sync so the task is already done
      await loadTasks();
      // auto-open report
      try {
        const rep = await inspectionApi.getReport(wsId, r.task_id, "md");
        if (rep.ok) {
          setReportMd(rep.content || "");
          setReportErr("");
        } else {
          setReportErr(rep.error || "报告获取失败");
        }
      } catch (e) {
        setReportErr(String(e));
      }
    } catch (e) {
      setCreateErr(String(e));
      setRunning(false);
    }
  }, [wsId, selectedProfile, scope, loadTasks]);

  // ── open report for an existing task ──
  const openReport = useCallback(async (taskId: string) => {
    if (!wsId) return;
    setOpenReportTaskId(taskId);
    try {
      const rep = await inspectionApi.getReport(wsId, taskId, "md");
      if (rep.ok) {
        setReportMd(rep.content || "");
        setReportErr("");
      } else {
        setReportErr(rep.error || "报告获取失败");
      }
    } catch (e) {
      setReportErr(String(e));
    }
  }, [wsId]);

  const selectedProfileObj = useMemo(
    () => profileResp?.profiles.find((p) => p.profile_id === selectedProfile),
    [profileResp, selectedProfile],
  );

  if (!wsId) {
    return (
      <div style={container}>
        <div style={empty}>请先选择工作区</div>
      </div>
    );
  }

  return (
    <div style={container}>
      {/* ── Header ── */}
      <header style={header}>
        <div>
          <h1 style={title}>设备巡检</h1>
          <p style={sub}>
            基于 CMDB 的设备健康检查 · 配置备份 · 实时跑命令· 服务器端解析认证信息
          </p>
        </div>
        <div style={headerStats}>
          {tasks.length > 0 && (
            <span style={{ fontSize: 12, color: "var(--text-3)" }}>
              共 {tasks.length} 条任务
            </span>
          )}
        </div>
      </header>

      {/* ── Section 1: Profile cards ── */}
      <section style={section}>
        <h2 style={sectionTitle}>① 选择 Profile</h2>
        <p style={sectionDesc}>
          Profile 决定要执行哪些命令。命令来源于固定厂家映射，禁止 LLM 拼写高危命令；认证信息在服务端解析。
        </p>
        {profileErr && <div style={errBlock}>{profileErr}</div>}
        {!profileResp && !profileErr && <div style={empty}>加载 Profile 中…</div>}
        <div style={profileGrid}>
          {profileResp?.profiles.map((p) => {
            const active = selectedProfile === p.profile_id;
            const tint = PROFILE_TINT[p.profile_id] || "var(--surface-2)";
            const text = PROFILE_TINT_TEXT[p.profile_id] || "var(--text-1)";
            return (
              <button
                key={p.profile_id}
                type="button"
                onClick={() => setSelectedProfile(p.profile_id)}
                data-testid={`profile-${p.profile_id}`}
                style={{
                  ...profileCard,
                  ...(active ? profileCardActive : {}),
                  borderColor: active ? "var(--primary)" : "var(--border)",
                  background: active ? "var(--primary-soft)" : "var(--surface)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{p.display_name}</div>
                  <span style={{ ...tagPill, background: tint, color: text, fontSize: 10 }}>
                    {p.checks.length} 项检查
                  </span>
                </div>
                <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 6, lineHeight: 1.5 }}>
                  {p.description}
                </div>
              </button>
            );
          })}
        </div>
        {selectedProfileObj && (
          <div style={checksBlock}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
              本 Profile 包含的检查项
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {selectedProfileObj.checks.map((c) => (
                <span
                  key={c.check_id}
                  style={{
                    ...tagPill,
                    background: "var(--surface-2)",
                    color: "var(--text-2)",
                    fontSize: 11,
                  }}
                >
                  {c.display_name}
                  <span style={{ marginLeft: 6, color: "var(--text-4)", fontSize: 10 }}>
                    [{c.severity_default}]
                  </span>
                </span>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* ── Section 2: Scope ── */}
      <section style={section}>
        <h2 style={sectionTitle}>② 选择 CMDB 范围</h2>
        <p style={sectionDesc}>
          范围越宽，巡检设备越多。留空 = 不限制该维度。认证信息由 runner 通过 CMDB 服务端解析，无需在此输入。
        </p>
        <div style={scopeGrid}>
          <Field label="区域">
            <input
              type="text"
              placeholder="例如: 华东"
              value={scope.region}
              onChange={(e) => uScope("region", e.target.value)}
              style={inp}
            />
          </Field>
          <Field label="位置">
            <input
              type="text"
              placeholder="例如: 上海-DC1"
              value={scope.location}
              onChange={(e) => uScope("location", e.target.value)}
              style={inp}
            />
          </Field>
          <Field label="设备类型">
            <select
              value={scope.type}
              onChange={(e) => uScope("type", e.target.value)}
              style={inp}
            >
              {Object.entries(TYPE_LABEL).map(([k, v]) => (
                <option key={k || "_all"} value={k}>{v}</option>
              ))}
            </select>
          </Field>
          <Field label="厂商">
            <input
              type="text"
              placeholder="例如: H3C"
              value={scope.vendor}
              onChange={(e) => uScope("vendor", e.target.value)}
              style={inp}
            />
          </Field>
          <Field label="设备上限">
            <input
              type="number"
              min={1}
              max={500}
              value={scope.limit}
              onChange={(e) => uScope("limit", e.target.value)}
              style={inp}
            />
          </Field>
        </div>

        <Field label="标签 (可多选)">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 6 }}>
            {TAG_PRESETS.map((t) => {
              const on = scope.tags.includes(t);
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => toggleTag(t)}
                  style={{
                    ...chip,
                    background: on ? "var(--primary)" : "var(--surface-2)",
                    color: on ? "white" : "var(--text-2)",
                    border: on ? "1px solid var(--primary)" : "1px solid var(--border)",
                  }}
                >
                  {t}
                </button>
              );
            })}
          </div>
          <input
            type="text"
            placeholder="或手动输入新标签，回车添加"
            value={tag}
            onChange={(e) => setTag(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && tag.trim()) {
                toggleTag(tag.trim());
                setTag("");
                e.preventDefault();
              }
            }}
            style={inp}
          />
          {scope.tags.length > 0 && (
            <div style={{ marginTop: 6, fontSize: 11, color: "var(--text-3)" }}>
              已选: {scope.tags.join(" · ")}
            </div>
          )}
        </Field>

        <Field label="资产 ID (可选，多个逗号分隔；留空则走上述维度)">
          <input
            type="text"
            placeholder="asset_id_1, asset_id_2"
            value={scope.asset_ids.join(", ")}
            onChange={(e) => {
              const ids = e.target.value.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean);
              setScope((p) => ({ ...p, asset_ids: ids }));
            }}
            style={inp}
          />
        </Field>
      </section>

      {/* ── Section 3: Run ── */}
      <section style={section}>
        <h2 style={sectionTitle}>③ 启动巡检</h2>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <button
            type="button"
            onClick={run}
            disabled={running || !selectedProfile}
            style={{
              ...runBtn,
              background: running ? "var(--text-3)" : "var(--primary)",
              cursor: running ? "not-allowed" : "pointer",
            }}
            data-testid="run-inspection"
          >
            {running ? "运行中…" : `启动 Profile “${selectedProfileObj?.display_name || selectedProfile}”`}
          </button>
          <span style={{ fontSize: 12, color: "var(--text-3)" }}>
            Runner 通过 CMDB 服务端解析 SSH 认证，不会暴露密码给页面 / LLM。
          </span>
        </div>
        {createErr && <div style={errBlock}>{createErr}</div>}
        {lastTaskId && !createErr && (
          <div style={{ marginTop: 10, fontSize: 12, color: "var(--ok)" }}>
            已生成巡检任务 <code>{lastTaskId}</code>，详情见下方报告。
          </div>
        )}
      </section>

      {/* ── Section 4: Recent tasks + report ── */}
      <section style={section}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={sectionTitle}>④ 历史任务 & 报告</h2>
          <button
            type="button"
            onClick={loadTasks}
            style={refreshBtn}
            data-testid="refresh-tasks"
          >
            ↻ 刷新
          </button>
        </div>
        {tasksErr && <div style={errBlock}>{tasksErr}</div>}
        {tasks.length === 0 && !tasksErr && (
          <div style={empty}>暂无历史任务。</div>
        )}
        {tasks.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {tasks.map((t) => {
              const opened = openReportTaskId === t.task_id;
              return (
                <div key={t.task_id} style={taskCard}>
                  <button
                    type="button"
                    onClick={() => openReport(t.task_id)}
                    style={{
                      ...taskSummaryBtn,
                      background: opened ? "var(--primary-soft)" : "transparent",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                      <span style={{ fontFamily: "ui-monospace, monospace", fontSize: 12, color: "var(--text-2)" }}>
                        {t.task_id}
                      </span>
                      <span style={{ fontSize: 13, fontWeight: 600 }}>{t.profile_display_name || t.profile_id}</span>
                      <span style={{
                        ...tagPill,
                        background: STATUS_COLOR[t.status] || "var(--text-3)",
                        color: "white",
                      }}>
                        {STATUS_LABEL[t.status] || t.status}
                      </span>
                      <span style={{ fontSize: 11, color: "var(--text-3)" }}>
                        {(t.started_at || "").slice(0, 19).replace("T", " ")} → {(t.finished_at || "").slice(0, 19).replace("T", " ") || "进行中"}
                      </span>
                    </div>
                    <div style={{
                      display: "flex",
                      borderLeft: "1px solid var(--border)",
                      paddingLeft: 12,
                      marginLeft: 4,
                    }}>
                      <SummaryCell label="设备" value={t.total_assets} color="var(--text-1)" />
                      <SummaryCell label="成功" value={t.succeeded} color={SEVERITY_COLOR.ok} />
                      <SummaryCell label="失败" value={t.failed} color={SEVERITY_COLOR.critical} />
                      <SummaryCell label="严重" value={t.criticals} color={SEVERITY_COLOR.critical} />
                      <SummaryCell label="告警" value={t.warnings} color={SEVERITY_COLOR.warning} />
                    </div>
                  </button>
                  {opened && (
                    <div style={reportBox}>
                      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: "var(--text-2)" }}>
                        巡检报告
                      </div>
                      {reportErr && <div style={errBlock}>{reportErr}</div>}
                      {!reportErr && (
                        <pre style={reportPre}>{reportMd}</pre>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 12, color: "var(--text-3)", marginBottom: 4 }}>{label}</div>
      {children}
    </div>
  );
}

// ── styles ──

const container: CSSProperties = {
  padding: "20px 24px",
  maxWidth: 1280,
  margin: "0 auto",
  color: "var(--text-1)",
};
const header: CSSProperties = {
  display: "flex", alignItems: "flex-end", justifyContent: "space-between",
  marginBottom: 18, gap: 12,
};
const headerStats: CSSProperties = { fontSize: 12, color: "var(--text-3)" };
const title: CSSProperties = {
  fontSize: 22, fontWeight: 700, margin: 0, color: "var(--text-1)",
};
const sub: CSSProperties = {
  fontSize: 13, color: "var(--text-3)", margin: "4px 0 0 0",
};
const section: CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  padding: "16px 18px",
  marginBottom: 14,
};
const sectionTitle: CSSProperties = {
  fontSize: 14, fontWeight: 600, margin: 0, marginBottom: 4,
  color: "var(--text-1)",
};
const sectionDesc: CSSProperties = {
  fontSize: 12, color: "var(--text-3)", margin: "0 0 12px 0", lineHeight: 1.5,
};
const empty: CSSProperties = {
  padding: "16px 0", color: "var(--text-3)", fontSize: 13, textAlign: "center",
};
const errBlock: CSSProperties = {
  marginTop: 10, padding: "8px 12px", background: "var(--danger-soft)",
  color: "var(--danger)", borderRadius: 6, fontSize: 12,
};
const profileGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
  gap: 10,
};
const profileCard: CSSProperties = {
  textAlign: "left",
  padding: "12px 14px",
  border: "1px solid var(--border)",
  borderRadius: 8,
  background: "var(--surface)",
  cursor: "pointer",
  transition: "all 120ms ease",
};
const profileCardActive: CSSProperties = {
  borderColor: "var(--primary)",
  boxShadow: "0 0 0 2px var(--primary-soft)",
};
const tagPill: CSSProperties = {
  display: "inline-flex", alignItems: "center",
  padding: "2px 8px", borderRadius: 999,
  background: "var(--surface-2)", color: "var(--text-2)",
  fontSize: 11, lineHeight: 1.5,
};
const chip: CSSProperties = {
  padding: "4px 10px", borderRadius: 999, fontSize: 12,
  background: "var(--surface-2)", color: "var(--text-2)",
  border: "1px solid var(--border)",
  cursor: "pointer", transition: "all 120ms ease",
};
const checksBlock: CSSProperties = {
  marginTop: 12, padding: "10px 12px", background: "var(--surface-2)",
  borderRadius: 6, border: "1px solid var(--border)",
};
const scopeGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 12,
};
const inp: CSSProperties = {
  width: "100%", boxSizing: "border-box",
  padding: "6px 10px",
  border: "1px solid var(--border)",
  borderRadius: 6,
  background: "var(--surface)",
  color: "var(--text-1)",
  fontSize: 13, fontFamily: "inherit",
  outline: "none",
};
const runBtn: CSSProperties = {
  padding: "8px 18px", borderRadius: 6, border: "none",
  background: "var(--primary)", color: "white",
  fontSize: 14, fontWeight: 600,
};
const refreshBtn: CSSProperties = {
  padding: "4px 10px", borderRadius: 6,
  background: "var(--surface-2)", color: "var(--text-2)",
  border: "1px solid var(--border)", fontSize: 12, cursor: "pointer",
};
const taskCard: CSSProperties = {
  border: "1px solid var(--border)", borderRadius: 6, overflow: "hidden",
  background: "var(--surface)",
};
const taskSummaryBtn: CSSProperties = {
  display: "flex", width: "100%", padding: "10px 12px",
  background: "transparent", border: "none", cursor: "pointer",
  alignItems: "center", justifyContent: "space-between", gap: 12,
  textAlign: "left", color: "inherit",
};
const reportBox: CSSProperties = {
  borderTop: "1px solid var(--border)",
  padding: "12px 14px",
  background: "var(--surface-2)",
};
const reportPre: CSSProperties = {
  margin: 0, padding: 12,
  background: "var(--surface)",
  border: "1px solid var(--border)", borderRadius: 6,
  fontFamily: "ui-monospace, monospace", fontSize: 12,
  whiteSpace: "pre-wrap", wordBreak: "break-word",
  maxHeight: 480, overflow: "auto",
  color: "var(--text-1)",
};
