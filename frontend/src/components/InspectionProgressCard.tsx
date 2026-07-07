// frontend/src/components/InspectionProgressCard.tsx
//
// v3.10: when the workbench auto-launches a CMDB inspection
// (intent=cmdb_region_inspection or cmdb_asset_inspection), this
// card sits at the top of the workbench message stream and
// shows the live task state with a cancel button. The backend
// doesn't push a separate SSE channel for inspection yet
// (issue #71) — the card polls /api/inspection/tasks using
// the task tracking policy while a task is live, then fades
// out 8 seconds after the task reaches a terminal state.

import { useCallback, useEffect, useRef, useState } from "react";
import { useSessionStore } from "../stores/session";
import { inspectionApi } from "../api";

const FADE_AFTER_MS = 8000;
const DEFAULT_POLL_MS = 5000;

interface Props {
  taskId: string;
  pollSeconds?: number;
  onDismiss?: () => void;
}

type Phase = "live" | "settling" | "fading";

interface Snapshot {
  status: string;
  total_assets: number;
  succeeded: number;
  failed: number;
  skipped: number;
  partial: number;
  criticals: number;
  warnings: number;
  infos: number;
  duration_ms: number;
  started_at: string;
  finished_at: string;
  cancel_requested_at: string;
  error: string;
}

const STATUS_COLORS: Record<string, string> = {
  succeeded: "#16a34a",
  partial: "#d97706",
  failed: "#b91c1c",
  cancelled: "#475569",
  running: "#2563eb",
  pending: "#64748b",
};

export function InspectionProgressCard({ taskId, pollSeconds, onDismiss }: Props) {
  const currentWorkspaceId = useSessionStore((s) => s.currentWorkspaceId);
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [phase, setPhase] = useState<Phase>("live");
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string>("");
  const pollRef = useRef<number | null>(null);
  const settleRef = useRef<number | null>(null);
  const fadeRef = useRef<number | null>(null);
  const pollMs = Math.max(
    DEFAULT_POLL_MS,
    Math.min(60000, Math.round((Number(pollSeconds) || DEFAULT_POLL_MS / 1000) * 1000)),
  );

  const refresh = useCallback(async () => {
    if (!currentWorkspaceId) return;
    try {
      const res = await inspectionApi.getTask(currentWorkspaceId, taskId);
      if (!("ok" in res) || !res.ok) {
        setSnap((s) => s || null);
        return;
      }
      const t: any = (res as any).task || {};
      const next: Snapshot = {
        status: t.status || "pending",
        total_assets: t.total_assets || 0,
        succeeded: t.succeeded || 0,
        failed: t.failed || 0,
        skipped: t.skipped || 0,
        partial: t.partial || 0,
        criticals: t.criticals || 0,
        warnings: t.warnings || 0,
        infos: t.infos || 0,
        duration_ms: t.duration_ms || 0,
        started_at: t.started_at || "",
        finished_at: t.finished_at || "",
        cancel_requested_at: t.cancel_requested_at || "",
        error: t.error || "",
      };
      setSnap(next);
      const terminal = ["succeeded", "failed", "cancelled", "partial"].includes(next.status);
      if (terminal) {
        setPhase((p) => (p === "live" ? "settling" : p));
        if (settleRef.current == null) {
          settleRef.current = window.setTimeout(() => {
            setPhase("fading");
            fadeRef.current = window.setTimeout(() => {
              onDismiss?.();
            }, FADE_AFTER_MS);
          }, 1500);
        }
      }
    } catch {
      // best-effort
    }
  }, [currentWorkspaceId, taskId, onDismiss]);

  useEffect(() => {
    refresh();
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.name === "inspection_progress" && detail?.data?.task_id === taskId) {
        refresh();
      }
    };
    window.addEventListener("ws-event", handler);
    // Background polling while a task is live (see file header: the card
    // polls /api/inspection/tasks because there is no dedicated SSE channel yet).
    pollRef.current = window.setInterval(refresh, pollMs);
    return () => {
      window.removeEventListener("ws-event", handler);
      if (pollRef.current) window.clearInterval(pollRef.current);
      if (settleRef.current) window.clearTimeout(settleRef.current);
      if (fadeRef.current) window.clearTimeout(fadeRef.current);
    };
  }, [refresh, taskId, pollMs]);

  const onCancel = useCallback(async () => {
    if (!currentWorkspaceId) return;
    if (!window.confirm(`取消巡检 ${taskId}? 正在跑的设备会跑完, 剩余设备会跳过。`)) return;
    setCancelling(true);
    setCancelError("");
    try {
      const res = await inspectionApi.cancelTask(currentWorkspaceId, taskId);
      if (!(res as any).ok) {
        setCancelError((res as any).error || "cancel_failed");
      } else {
        window.setTimeout(() => refresh(), 600);
      }
    } catch (e: any) {
      setCancelError(String(e?.message || e));
    } finally {
      setCancelling(false);
    }
  }, [currentWorkspaceId, taskId, refresh]);

  if (!snap) {
    return (
      <div style={cardStyle}>
        <div style={{ fontSize: 12, color: "var(--text-4)" }}>
          正在拉取巡检 {taskId} 状态…
        </div>
      </div>
    );
  }

  const live = snap.status === "running" || snap.status === "pending";
  const progressPct = snap.total_assets > 0
    ? Math.min(100, Math.round(
        ((snap.succeeded + snap.failed + snap.partial + snap.skipped) / snap.total_assets) * 100,
      ))
    : 0;
  const styleWithFade = phase === "fading" ? { ...cardStyle, opacity: 0.55 } : cardStyle;

  return (
    <div style={styleWithFade}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{
          ...chip,
          background: STATUS_COLORS[snap.status] || "#64748b",
        }}>{snap.status}</span>
        <strong style={{ fontSize: 13 }}>巡检任务 {taskId}</strong>
        <span style={{ flex: 1 }} />
        {live && (
          <button
            type="button"
            onClick={onCancel}
            disabled={cancelling}
            style={{
              background: "transparent", color: "#b91c1c", border: "1px solid #b91c1c",
              padding: "4px 12px", borderRadius: 4, fontSize: 11, cursor: cancelling ? "not-allowed" : "pointer",
            }}
          >
            {cancelling ? "取消中…" : "取消"}
          </button>
        )}
      </div>
      <div style={{ marginTop: 8, fontSize: 12, color: "var(--text-4)" }}>
        设备: {snap.succeeded}✓ / {snap.failed}✗ / {snap.partial}½ / {snap.skipped}· / {snap.total_assets}
        {"  "}
        发现: {snap.criticals} critical · {snap.warnings} warning · {snap.infos} info
        {snap.duration_ms > 0 && (
          <>{"  "}· 耗时 {Math.round(snap.duration_ms / 1000)}s</>
        )}
      </div>
      <div style={barBg}>
        <div
          style={{
            ...barFill,
            width: `${progressPct}%`,
            background: STATUS_COLORS[snap.status] || "#2563eb",
          }}
        />
      </div>
      {snap.cancel_requested_at && (
        <div style={{ fontSize: 11, color: "var(--text-4)", marginTop: 4 }}>
          已请求取消 @ {snap.cancel_requested_at}
        </div>
      )}
      {cancelError && (
        <div style={{ fontSize: 11, color: "#b91c1c", marginTop: 4 }}>
          {cancelError}
        </div>
      )}
      {snap.error && phase !== "live" && (
        <div style={{ fontSize: 11, color: "var(--text-4)", marginTop: 4 }}>
          error: {snap.error}
        </div>
      )}
    </div>
  );
}

const cardStyle: React.CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--line)",
  borderLeft: "4px solid #2563eb",
  borderRadius: 8,
  padding: "10px 14px",
  margin: "8px 0",
  fontSize: 12,
};
const chip: React.CSSProperties = {
  display: "inline-block",
  padding: "2px 8px",
  borderRadius: 999,
  fontSize: 11,
  fontWeight: 600,
  color: "white",
};
const barBg: React.CSSProperties = {
  marginTop: 6,
  height: 4,
  width: "100%",
  background: "var(--line)",
  borderRadius: 999,
  overflow: "hidden",
};
const barFill: React.CSSProperties = {
  height: "100%",
  borderRadius: 999,
  transition: "width .5s",
};
