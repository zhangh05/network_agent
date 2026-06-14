/**
 * RunsPage — v2.1.3: Run history list and full trace detail.
 *
 * Uses TraceDetailPanel for complete event timeline with filters, search,
 * and expandable JSON (not just first 5 events).
 */
import { useEffect, useState, useCallback } from "react";
import { workspacesApi, runtimeAuditApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { Badge, EmptyState, LoadingState, StatusDot } from "../../components/common";
import { IconRefresh } from "../../components/Icon";
import { TraceDetailPanel } from "../../components/TraceDetailPanel";
import type { RuntimeAuditTurn, RuntimeEvent } from "../../types";

export function RunsPage() {
  const { currentWorkspaceId } = useSessionStore();
  const wsId = currentWorkspaceId || "default";
  const [runs, setRuns] = useState<RuntimeAuditTurn[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<RuntimeAuditTurn | null>(null);
  const [traceEvents, setTraceEvents] = useState<RuntimeEvent[] | null>(null);

  const loadRuns = useCallback(async () => {
    setLoading(true); setError(null);
    try { const data = await workspacesApi.recentRuns(wsId); setRuns(data.runs || []); }
    catch (e: any) { setError(e?.message || "Failed"); }
    setLoading(false);
  }, [wsId]);

  const loadTrace = async (run: RuntimeAuditTurn) => {
    const rid = run.run_id || run.turn_id;
    if (!rid) return;
    try {
      const data = await runtimeAuditApi.trace(wsId, rid);
      setTraceEvents(data.events || []);
    } catch { setTraceEvents(null); }
  };

  useEffect(() => { loadRuns(); }, [loadRuns]);

  const statusBadge = (status: string): "ok" | "err" | "warn" | "muted" => {
    const map: Record<string, "ok" | "err" | "warn" | "muted"> = { completed: "ok", ok: "ok", success: "ok", failed: "err", error: "err", running: "warn", pending: "warn", cancelled: "muted", archived: "muted" };
    return map[status] || "muted";
  };

  const statusDot = (s: string): "ok" | "err" | "warn" | "idle" => {
    if (s === "completed" || s === "ok") return "ok";
    if (s === "failed" || s === "error") return "err";
    if (s === "running" || s === "pending") return "warn";
    return "idle";
  };

  const selectRun = (run: RuntimeAuditTurn) => {
    if (selectedRun?.run_id === run.run_id) {
      setSelectedRun(null); setTraceEvents(null);
    } else {
      setSelectedRun(run);
      setTraceEvents(null); // Reset while loading
      loadTrace(run);
    }
  };

  return (
    <div className="page-runs" style={{ padding: 16 }}>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <h2>运行记录</h2>
        <button className="btn-sm" onClick={loadRuns} title="刷新"><IconRefresh size={14} /></button>
      </div>

      {error && <div style={{ color: "var(--err)", padding: 8 }}>{error}</div>}
      {loading && <LoadingState />}
      {!loading && !error && runs.length === 0 && <EmptyState text="暂无运行记录" />}

      <div style={{ display: "flex", gap: 16 }}>
        <div style={{ flex: 1, maxWidth: 340 }}>
          {runs.map((run) => (
            <div key={run.run_id || run.turn_id}
              style={{ padding: 10, marginBottom: 6, border: selectedRun?.run_id === run.run_id ? "1px solid var(--accent)" : "1px solid var(--border)", borderRadius: 6, cursor: "pointer" }}
              onClick={() => selectRun(run)}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <StatusDot status={statusDot(run.status || "")} />
                <span>{run.user_input_summary || run.intent || "(无摘要)"}</span>
                <Badge kind={statusBadge(run.status || "unknown")}>{run.status || "unknown"}</Badge>
              </div>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>{run.session_id?.substring(0, 8)} {run.created_at}</div>
            </div>
          ))}
        </div>

        {selectedRun && (
          <div style={{ flex: 1, overflow: "auto" }}>
            <h3>运行详情</h3>
            <table className="detail-table" style={{ width: "100%", fontSize: 13 }}>
              <tbody>
                <tr><td>status</td><td><Badge kind={statusBadge(selectedRun.status || "")}>{selectedRun.status}</Badge></td></tr>
                <tr><td>session_id</td><td style={{ fontFamily: "monospace", fontSize: 11 }}>{selectedRun.session_id || "-"}</td></tr>
                <tr><td>turn_id</td><td style={{ fontFamily: "monospace", fontSize: 11 }}>{selectedRun.turn_id || selectedRun.run_id || "-"}</td></tr>
                <tr><td>trace_id</td><td style={{ fontFamily: "monospace", fontSize: 11 }}>{selectedRun.trace_id || "-"}</td></tr>
                <tr><td>started_at</td><td>{selectedRun.started_at || "-"}</td></tr>
                <tr><td>finished_at</td><td>{selectedRun.finished_at || "-"}</td></tr>
                <tr><td>intent</td><td>{selectedRun.intent || "-"}</td></tr>
                <tr><td>tool_calls</td><td>{selectedRun.tool_call_count}</td></tr>
              </tbody>
            </table>

            {/* v2.1.3: Full TraceDetailPanel replaces inline trace preview */}
            <TraceDetailPanel traceEvents={traceEvents} selectedRun={selectedRun} />

            {selectedRun.selected_skills?.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <strong>skills:</strong>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
                  {selectedRun.selected_skills.map((s, i) => <Badge key={i} kind="info">{s}</Badge>)}
                </div>
              </div>
            )}

            {(!traceEvents || traceEvents.length === 0) && !selectedRun.tool_call_count && (
              <div style={{ color: "var(--text-muted)", fontSize: 12, marginTop: 12 }}>(无更多详情)</div>
            )}
          </div>
        )}
      </div>

      <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 8 }}>共 {runs.length} 条运行记录</div>
    </div>
  );
}
