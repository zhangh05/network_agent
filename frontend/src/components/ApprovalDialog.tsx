import { useEffect, useState } from "react";
import { useSessionStore } from "../stores/session";
import { IconAlert, IconCheck, IconClose } from "./Icon";

interface PendingApproval {
  approval_id: string;
  tool_id: string;
  description: string;
  risk_level: string;
  arguments_summary: string;
}

/**
 * ApprovalDialog — shows when a high-risk tool call needs user approval.
 * Polls /api/agent/approvals/pending and renders Allow/Deny buttons.
 */
export function ApprovalDialog({ onResolved }: { onResolved?: () => void }) {
  const { currentSessionId } = useSessionStore();
  const [pending, setPending] = useState<PendingApproval | null>(null);
  const [resolving, setResolving] = useState(false);

  useEffect(() => {
    if (!currentSessionId) return;

    const poll = async () => {
      try {
        const res = await fetch(
          `/api/agent/approvals/pending?session_id=${currentSessionId}`
        );
        const data = await res.json();
        if (data.ok && data.pending?.length > 0) {
          setPending(data.pending[0]);
        }
      } catch {
        /* polling — ignore errors */
      }
    };

    const interval = setInterval(poll, 1000);
    poll(); // immediate first poll
    return () => clearInterval(interval);
  }, [currentSessionId]);

  const handleResolve = async (allowed: boolean) => {
    if (!pending || resolving) return;
    setResolving(true);
    try {
      await fetch(`/api/agent/approvals/${pending.approval_id}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ allowed }),
      });
    } catch {
      /* ignore */
    }
    setPending(null);
    setResolving(false);
    onResolved?.();
  };

  if (!pending) return null;

  return (
    <div className="approval-bubble">
      <div className="approval-bubble-header">
        <IconAlert size={14} />
        <span>需要确认</span>
      </div>

      <div className="approval-bubble-body">
        <code>{pending.tool_id}</code>
        {pending.arguments_summary && (
          <span className="approval-bubble-args">
            {pending.arguments_summary}
          </span>
        )}
      </div>

      <div className="approval-bubble-actions">
        <button
          className="btn sm ghost"
          onClick={() => handleResolve(false)}
          disabled={resolving}
          type="button"
        >
          <IconClose size={12} /> 拒绝
        </button>
        <button
          className="btn sm primary"
          onClick={() => handleResolve(true)}
          disabled={resolving}
          type="button"
          autoFocus
        >
          <IconCheck size={12} /> 允许
        </button>
      </div>
    </div>
  );
}

/* ── Bubble styles (co-located) ── */
const STYLE = `
.approval-bubble {
  position: fixed; bottom: 120px; left: 50%; transform: translateX(-50%);
  z-index: 100;
  background: var(--bg-card, #fff);
  border: 1px solid var(--border, #e0d6c2);
  border-radius: 10px;
  padding: 12px 16px;
  min-width: 320px; max-width: 480px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.12);
  animation: approvalSlideUp 0.25s ease-out;
  display: flex; flex-direction: column; gap: 8px;
}
@keyframes approvalSlideUp {
  from { opacity: 0; transform: translateX(-50%) translateY(16px); }
  to { opacity: 1; transform: translateX(-50%) translateY(0); }
}
.approval-bubble-header {
  display: flex; align-items: center; gap: 6px;
  font-size: 13px; font-weight: 600; color: var(--danger, #c0392b);
}
.approval-bubble-body {
  display: flex; flex-wrap: wrap; gap: 6px; align-items: baseline;
  font-size: 12px;
}
.approval-bubble-body code {
  background: var(--bg-soft, #f5f0e8); padding: 2px 6px;
  border-radius: 4px; font-size: 11px;
}
.approval-bubble-args {
  color: var(--fg-muted, #999); font-size: 11px;
  max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.approval-bubble-actions {
  display: flex; gap: 8px; justify-content: flex-end;
}
.approval-bubble-actions .btn.primary {
  background: var(--primary, #2563eb); color: #fff; border: none;
  padding: 4px 14px; border-radius: 6px; font-size: 12px; cursor: pointer;
}
.approval-bubble-actions .btn.primary:hover { opacity: 0.9; }
`;
if (typeof document !== 'undefined' && !document.getElementById('approval-bubble-style')) {
  const el = document.createElement('style');
  el.id = 'approval-bubble-style';
  el.textContent = STYLE;
  document.head.appendChild(el);
}
