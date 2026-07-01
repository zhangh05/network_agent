// frontend/src/pages/Inspection/InspectionPage.tsx
//
// v3.10: standalone inspection page that surfaces the existing
// `/api/inspection/*` endpoints without going through the LLM.
// The CMDB page already wires a "launch inspection" intent that
// goes to the workbench, but the operator has no way to (a)
// inspect the running task list, (b) cancel a task mid-flight,
// or (c) download the report without parsing the LLM transcript.
//
// This page is the place for all three.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { inspectionApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import type { InspectionTaskRecord, InspectionScope } from "../../api";
import { IconBolt, IconHistory, IconLayers, IconShield } from "../../components/Icon";

const SEV_COLORS: Record<string, string> = {
  critical: "#b91c1c",
  warning: "#92400e",
  info: "#1d4ed8",
};
const STATUS_COLORS: Record<string, string> = {
  succeeded: "#16a34a",
  partial: "#d97706",
  failed: "#b91c1c",
  cancelled: "#475569",
  running: "#2563eb",
  pending: "#64748b",
  skipped: "#94a3b8",
};

const POLL_INTERVAL_MS = 2000;

function fmtTime(iso: string) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function fmtDuration(ms: number) {
  if (!ms || ms <= 0) return "—";
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s - m * 60)}s`;
}

export function InspectionPage() {
  const currentWorkspaceId = useSessionStore((s) => s.currentWorkspaceId);
  const navigate = useNavigate();
  const [scope, setScope] = useState<InspectionScope>({
    region: "",
    location: "",
    type: "",
    vendor: "",
    tags: [],
    asset_ids: [],
    limit: 50,
  });
  const [maxConcurrency, setMaxConcurrency] = useState(3);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string>("");
  const [tasks, setTasks] = useState<InspectionTaskRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [cancelling, setCancelling] = useState<string>("");
  const [reportUrl, setReportUrl] = useState<string>("");
  const [reportTaskId, setReportTaskId] = useState<string>("");
  const pollingRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    if (!currentWorkspaceId) return;
    setLoading(true);
    try {
      const res = await inspectionApi.listTasks(currentWorkspaceId, 50);
      if (res.ok) {
        setTasks((res.items as InspectionTaskRecord[]) || []);
      }
    } catch {
      // best-effort
    } finally {
      setLoading(false);
    }
  }, [currentWorkspaceId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Polling for in-flight tasks. v3.10: this is the only way the
  // UI learns task progress today (no SSE channel yet, see
  // inspection issue #71).
  useEffect(() => {
    if (pollingRef.current) {
      window.clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    const hasLive = tasks.some((t) =>
      t.status === "running" || t.status === "pending",
    );
    if (hasLive && currentWorkspaceId) {
      pollingRef.current = window.setInterval(() => {
        refresh();
      }, POLL_INTERVAL_MS);
    }
    return () => {
      if (pollingRef.current) {
        window.clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [tasks, currentWorkspaceId, refresh]);

  const onCreate = useCallback(async () => {
    if (!currentWorkspaceId) return;
    setCreating(true);
    setCreateError("");
    try {
      // v3.10: send async_run=true so the backend fires the task
      // on a daemon thread and the operator doesn't sit on a
      // 60-second HTTP request. The route returns 202 + a
      // placeholder task_id we can't immediately track from this
      // page; we just refresh the list after a short delay.
      const res = await inspectionApi.createTask({
        workspace_id: currentWorkspaceId,
        scope,
        max_concurrency: maxConcurrency,
        async_run: true,
      } as any);
      if (!(res as any).ok) {
        setCreateError((res as any).error || "create_failed");
        return;
      }
      window.setTimeout(() => refresh(), 1500);
    } catch (e: any) {
      setCreateError(String(e?.message || e));
    } finally {
      setCreating(false);
    }
  }, [currentWorkspaceId, scope, maxConcurrency, refresh]);

  const onCancel = useCallback(async (taskId: string) => {
    if (!currentWorkspaceId) return;
    if (!window.confirm(`取消巡检任务 ${taskId}? 正在运行的设备会跑完, 剩余设备会跳过。`)) {
      return;
    }
    setCancelling(taskId);
    try {
      const res = await inspectionApi.cancelTask(currentWorkspaceId, taskId);
      if ((res as any).ok) {
        window.setTimeout(() => refresh(), 800);
      } else {
        setCreateError((res as any).error || "cancel_failed");
      }
    } catch (e: any) {
      setCreateError(String(e?.message || e));
    } finally {
      setCancelling("");
    }
  }, [currentWorkspaceId, refresh]);

  const onOpenReport = useCallback(async (taskId: string, fmt: "md" | "html") => {
    if (!currentWorkspaceId) return;
    if (fmt === "html") {
      // /api/inspection/tasks/<id>/report.html serves the viewable
      // page inline.
      const url = `/api/inspection/tasks/${encodeURIComponent(taskId)}/report.html?workspace_id=${encodeURIComponent(currentWorkspaceId)}`;
      window.open(url, "_blank", "noopener");
      return;
    }
    try {
      const res = await inspectionApi.getReport(currentWorkspaceId, taskId, fmt);
      if ((res as any).ok && (res as any).content) {
        const blob = new Blob([(res as any).content], { type: "text/markdown;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        setReportUrl(url);
        setReportTaskId(taskId);
      }
    } catch {
      // best-effort
    }
  }, [currentWorkspaceId]);

  const sortedTasks = useMemo(() => {
    return [...tasks].sort((a, b) => (b.started_at || "").localeCompare(a.started_at || ""));
  }, [tasks]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: 16 }}>
      <div className="hero" style={{ padding: "16px 20px" }}>
        <div className="hero-mark"><IconLayers size={28} /></div>
        <div style={{ flex: 1 }}>
          <h1 className="hero-title" style={{ fontSize: 22, margin: 0 }}>巡检任务</h1>
          <p className="hero-sub" style={{ marginTop: 4 }}>
            不走 LLM, 直接在 UI 发起、查看、取消、下载报告。所有命令都走设备资产配置, 凭据服务端解析。
          </p>
        </div>
      </div>

      <section style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr 1fr 1fr", gap: 10 }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 600 }}>区域</span>
          <input
            placeholder="例: 北京-朝阳"
            value={scope.region || ""}
            onChange={(e) => setScope((s) => ({ ...s, region: e.target.value }))}
            style={inputStyle}
          />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 600 }}>位置</span>
          <input
            placeholder="物理位置 (可选)"
            value={scope.location || ""}
            onChange={(e) => setScope((s) => ({ ...s, location: e.target.value }))}
            style={inputStyle}
          />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 600 }}>设备类型</span>
          <select
            value={scope.type || ""}
            onChange={(e) => setScope((s) => ({ ...s, type: e.target.value }))}
            style={inputStyle}
          >
            <option value="">(不限)</option>
            <option value="switch">switch</option>
            <option value="router">router</option>
            <option value="firewall">firewall</option>
            <option value="server">server</option>
            <option value="load_balancer">load_balancer</option>
            <option value="wireless">wireless</option>
            <option value="other">other</option>
          </select>
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 600 }}>厂商</span>
          <input
            placeholder="h3c / huawei / cisco ..."
            value={scope.vendor || ""}
            onChange={(e) => setScope((s) => ({ ...s, vendor: e.target.value }))}
            style={inputStyle}
          />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 600 }}>并发</span>
          <input
            type="number"
            min={1}
            max={16}
            value={maxConcurrency}
            onChange={(e) => setMaxConcurrency(Math.max(1, Math.min(16, Number(e.target.value) || 1)))}
            style={inputStyle}
          />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 600 }}>Limit</span>
          <input
            type="number"
            min={1}
            max={500}
            value={scope.limit || 50}
            onChange={(e) => setScope((s) => ({ ...s, limit: Math.max(1, Math.min(500, Number(e.target.value) || 50)) }))}
            style={inputStyle}
          />
        </label>
      </section>

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button
          type="button"
          onClick={onCreate}
          disabled={!currentWorkspaceId || creating}
          style={{
            background: "var(--accent)", color: "white", border: 0,
            padding: "8px 16px", borderRadius: 6, fontSize: 13, fontWeight: 600,
            cursor: !currentWorkspaceId || creating ? "not-allowed" : "pointer",
            opacity: !currentWorkspaceId || creating ? 0.6 : 1,
          }}
        >
          {creating ? "排队中…" : "发起巡检"}
        </button>
        <button
          type="button"
          onClick={() => navigate("/cmdb")}
          style={btnGhost}
        >
          <IconBolt size={14} /> 跳到设备资产
        </button>
        <span style={{ flex: 1 }} />
        {createError && (
          <span style={{ color: "var(--warn, #b91c1c)", fontSize: 12 }}>
            {createError}
          </span>
        )}
      </div>

      {reportUrl && (
        <div style={{ ...card, display: "flex", alignItems: "center", gap: 10 }}>
          <IconShield size={14} />
          <span style={{ fontSize: 12 }}>报告 {reportTaskId} 已生成 Markdown。</span>
          <a href={reportUrl} download={`inspection_${reportTaskId}.md`} style={{ color: "var(--accent)" }}>
            下载
          </a>
          <button
            type="button"
            onClick={() => {
              URL.revokeObjectURL(reportUrl);
              setReportUrl("");
              setReportTaskId("");
            }}
            style={btnGhost}
          >
            关闭
          </button>
        </div>
      )}

      <section style={card}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
          <IconHistory size={14} />
          <strong style={{ fontSize: 13 }}>最近任务</strong>
          <span style={{ flex: 1 }} />
          {loading && <span style={{ fontSize: 11, color: "var(--text-4)" }}>加载中…</span>}
        </div>
        {sortedTasks.length === 0 ? (
          <div style={{ fontSize: 12, color: "var(--text-4)", padding: 12 }}>
            还没有巡检任务。上面选个 scope, 点「发起巡检」。
          </div>
        ) : (
          <table style={tbl}>
            <thead>
              <tr>
                <th style={th}>任务 ID</th>
                <th style={th}>状态</th>
                <th style={th}>设备</th>
                <th style={th}>耗时</th>
                <th style={th}>开始</th>
                <th style={th}>发现</th>
                <th style={th}>操作</th>
              </tr>
            </thead>
            <tbody>
              {sortedTasks.map((t) => {
                const live = t.status === "running" || t.status === "pending";
                const totalDevices = (t as any).total_assets || 0;
                const succ = t.succeeded || 0;
                const fail = t.failed || 0;
                const skip = t.skipped || 0;
                const partial = (t as any).partial || 0;
                const findings = (t.criticals || 0) + (t.warnings || 0) + (t.infos || 0);
                return (
                  <tr key={t.task_id}>
                    <td style={tdMono}>{t.task_id}</td>
                    <td style={td}>
                      <span style={{
                        ...chip,
                        background: STATUS_COLORS[t.status] || "#64748b",
                      }}>{t.status}</span>
                    </td>
                    <td style={td}>
                      {succ}✓ / {fail}✗ / {partial}½ / {skip}· / {totalDevices}
                    </td>
                    <td style={td}>
                      {(t as any).duration_ms ? fmtDuration((t as any).duration_ms) : "—"}
                    </td>
                    <td style={td}>{fmtTime(t.started_at)}</td>
                    <td style={td}>
                      {(t.criticals || 0) > 0 && (
                        <span style={{ ...chip, background: SEV_COLORS.critical }}>
                          crit {t.criticals}
                        </span>
                      )}{" "}
                      {(t.warnings || 0) > 0 && (
                        <span style={{ ...chip, background: SEV_COLORS.warning }}>
                          warn {t.warnings}
                        </span>
                      )}{" "}
                      {(t.infos || 0) > 0 && (
                        <span style={{ ...chip, background: SEV_COLORS.info }}>
                          info {t.infos}
                        </span>
                      )}
                      {findings === 0 && <span style={{ fontSize: 11, color: "var(--text-4)" }}>—</span>}
                    </td>
                    <td style={td}>
                      <button
                        type="button"
                        onClick={() => onOpenReport(t.task_id, "md")}
                        style={btnGhost}
                        title="下载 Markdown 报告"
                      >
                        MD
                      </button>{" "}
                      <button
                        type="button"
                        onClick={() => onOpenReport(t.task_id, "html")}
                        style={btnGhost}
                        title="浏览器内打开 HTML 报告"
                      >
                        HTML
                      </button>{" "}
                      {live && (
                        <button
                          type="button"
                          onClick={() => onCancel(t.task_id)}
                          disabled={cancelling === t.task_id}
                          style={{ ...btnGhost, color: "#b91c1c" }}
                        >
                          {cancelling === t.task_id ? "取消中…" : "取消"}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  padding: "7px 10px", fontSize: 13, borderRadius: 6,
  border: "1px solid var(--line)", background: "var(--surface)", color: "var(--text)",
};
const card: React.CSSProperties = {
  background: "var(--surface)", border: "1px solid var(--line)",
  borderRadius: 8, padding: 14,
};
const tbl: React.CSSProperties = {
  width: "100%", borderCollapse: "collapse", fontSize: 12,
};
const th: React.CSSProperties = {
  textAlign: "left", padding: "6px 8px", borderBottom: "1px solid var(--line)",
  color: "var(--text-4)", fontWeight: 600, fontSize: 11,
};
const td: React.CSSProperties = {
  padding: "6px 8px", borderBottom: "1px solid var(--line)",
  verticalAlign: "top",
};
const tdMono: React.CSSProperties = {
  ...td, fontFamily: "var(--font-mono)",
};
const chip: React.CSSProperties = {
  display: "inline-block", padding: "1px 6px", borderRadius: 999,
  fontSize: 10, fontWeight: 600, color: "white",
};
const btnGhost: React.CSSProperties = {
  background: "transparent", color: "var(--text)", border: "1px solid var(--line)",
  padding: "4px 10px", borderRadius: 4, fontSize: 11, cursor: "pointer",
  display: "inline-flex", alignItems: "center", gap: 4,
};
