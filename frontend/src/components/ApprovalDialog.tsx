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
    <div className="approval-overlay">
      <div className="approval-dialog">
        <div className="approval-header">
          <IconAlert size={18} />
          <span>高风险工具调用需要确认</span>
        </div>

        <div className="approval-body">
          <div className="approval-row">
            <span className="label">工具</span>
            <code className="value">{pending.tool_id}</code>
          </div>
          <div className="approval-row">
            <span className="label">描述</span>
            <span className="value">{pending.description || "(无描述)"}</span>
          </div>
          {pending.arguments_summary && (
            <div className="approval-row">
              <span className="label">参数</span>
              <span className="value text-sm">{pending.arguments_summary}</span>
            </div>
          )}
        </div>

        <div className="approval-actions">
          <button
            className="btn danger"
            onClick={() => handleResolve(false)}
            disabled={resolving}
            type="button"
          >
            <IconClose size={14} /> 拒绝
          </button>
          <button
            className="btn primary"
            onClick={() => handleResolve(true)}
            disabled={resolving}
            type="button"
            autoFocus
          >
            <IconCheck size={14} /> 允许
          </button>
        </div>
      </div>
    </div>
  );
}
