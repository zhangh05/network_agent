// frontend/src/components/InspectionProgressCard.tsx
//
// When the workbench auto-launches a CMDB inspection
// (intent=cmdb_region_inspection or cmdb_asset_inspection), this
// card sits at the top of the workbench message stream and
// shows the live task state with a cancel button.
//
// Update: the backend pushes `inspection_progress` over the per-session
// agent WebSocket (dispatched as a window "ws-event"), so refresh() already
// fires on every server-side update. Polling /api/inspection/tasks is only a
// safety net now, and it is paused while the tab is hidden to avoid wasted
// requests. The card fades out 8s after the task reaches a terminal state.

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { useSessionStore } from "../stores/session";
import { inspectionApi } from "../api";
import { confirm } from "./ConfirmDialog";

const FADE_AFTER_MS = 8000;
const DEFAULT_POLL_MS = 5000;
type CssVars = CSSProperties & Record<`--${string}`, string>;

interface InspectionTaskSnapshot {
  status?: string;
  total_assets?: number;
  succeeded?: number;
  failed?: number;
  skipped?: number;
  partial?: number;
  criticals?: number;
  warnings?: number;
  infos?: number;
  duration_ms?: number;
  started_at?: string;
  finished_at?: string;
  cancel_requested_at?: string;
  error?: string;
}

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
      const task = "task" in res ? res.task : undefined;
      const t: InspectionTaskSnapshot = task ?? {};
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

    // The backend already pushes inspection_progress over the agent WebSocket, so
    // refresh() fires on every server event. Polling is only a safety net, and we
    // pause it while the tab is hidden to avoid wasted requests.
    const startPolling = () => {
      if (pollRef.current == null) pollRef.current = window.setInterval(refresh, pollMs);
    };
    const stopPolling = () => {
      if (pollRef.current != null) { window.clearInterval(pollRef.current); pollRef.current = null; }
    };
    const onVisibility = () => { if (document.hidden) stopPolling(); else startPolling(); };
    document.addEventListener("visibilitychange", onVisibility);
    if (!document.hidden) startPolling();

    return () => {
      window.removeEventListener("ws-event", handler);
      document.removeEventListener("visibilitychange", onVisibility);
      stopPolling();
      if (settleRef.current) window.clearTimeout(settleRef.current);
      if (fadeRef.current) window.clearTimeout(fadeRef.current);
    };
  }, [refresh, taskId, pollMs]);

  const onCancel = useCallback(async () => {
    if (!currentWorkspaceId) return;
    const ok = await confirm({
      title: `取消巡检 ${taskId}?`,
      body: "正在跑的设备会跑完, 剩余设备会跳过。",
      destructive: true,
      confirmLabel: "取消巡检",
    });
    if (!ok) return;
    setCancelling(true);
    setCancelError("");
    try {
      const res = await inspectionApi.cancelTask(currentWorkspaceId, taskId);
      if (!res.ok) {
        setCancelError(res.error || "cancel_failed");
      } else {
        window.setTimeout(() => refresh(), 600);
      }
    } catch (e: unknown) {
      setCancelError(e instanceof Error ? e.message : String(e));
    } finally {
      setCancelling(false);
    }
  }, [currentWorkspaceId, taskId, refresh]);

  if (!snap) {
    return (
      <div className="inspection-progress-card">
        <div className="inspection-progress-note">
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
  const statusClass = snap.status || "pending";
  const progressStyle: CssVars = { "--inspection-progress": `${progressPct}%` };

  return (
    <div className={`inspection-progress-card ${phase === "fading" ? "inspection-progress-card--fading" : ""}`}>
      <div className="inspection-progress-card-header">
        <span
          className={`inspection-progress-chip inspection-progress-chip--${statusClass}`}
        >{snap.status}</span>
        <strong className="inspection-progress-title">巡检任务 {taskId}</strong>
        <span className="inspection-progress-spacer" />
        {live && (
          <button
            type="button"
            onClick={onCancel}
            disabled={cancelling}
            className="inspection-cancel-btn"
          >
            {cancelling ? "取消中…" : "取消"}
          </button>
        )}
      </div>
      <div className="inspection-progress-meta">
        设备: {snap.succeeded}✓ / {snap.failed}✗ / {snap.partial}½ / {snap.skipped}· / {snap.total_assets}
        {"  "}
        发现: {snap.criticals} critical · {snap.warnings} warning · {snap.infos} info
        {snap.duration_ms > 0 && (
          <>{"  "}· 耗时 {Math.round(snap.duration_ms / 1000)}s</>
        )}
      </div>
      <div className="inspection-progress-bar-bg">
        <div
          className={`inspection-progress-bar-fill inspection-progress-bar-fill--${statusClass}`}
          style={progressStyle}
        />
      </div>
      {snap.cancel_requested_at && (
        <div className="inspection-progress-note">
          已请求取消 @ {snap.cancel_requested_at}
        </div>
      )}
      {cancelError && (
        <div className="inspection-progress-error">
          {cancelError}
        </div>
      )}
      {snap.error && phase !== "live" && (
        <div className="inspection-progress-note">
          error: {snap.error}
        </div>
      )}
    </div>
  );
}
