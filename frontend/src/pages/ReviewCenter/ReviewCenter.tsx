import { useState } from "react";
import { reviewsApi } from "../../api";
import { useAsync, AsyncView, Badge, InlineCode } from "../../components/common";
import { useSessionStore } from "../../stores/session";
import { useToastStore } from "../../stores/toast";
import { isApiError } from "../../types";
import type { ReviewItem, ReviewStatus } from "../../types";

const STATUS_OPTIONS: { value: ReviewStatus | "all"; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "pending", label: "pending" },
  { value: "accepted", label: "accepted" },
  { value: "ignored", label: "ignored" },
  { value: "modified", label: "modified" },
];

const STATUS_KIND: Record<ReviewStatus, "warn" | "ok" | "muted" | "info"> = {
  pending: "warn",
  accepted: "ok",
  ignored: "muted",
  modified: "info",
};

/**
 * Review Center — list / update review items. Never mutates the
 * original artifact; only writes `user_note` and `status`.
 */
export function ReviewCenter() {
  const { currentWorkspaceId } = useSessionStore();
  const toast = useToastStore((s) => s.show);
  const [filter, setFilter] = useState<ReviewStatus | "all">("pending");
  const [editing, setEditing] = useState<ReviewItem | null>(null);
  const [note, setNote] = useState("");

  const list = useAsync<{ items: ReviewItem[] }>(
    (s) =>
      currentWorkspaceId
        ? reviewsApi.list(currentWorkspaceId, filter === "all" ? undefined : filter, s)
        : Promise.resolve({ items: [] }),
    [currentWorkspaceId, filter],
    (d) => (d.items ?? []).length === 0,
  );

  async function onSave() {
    if (!editing) return;
    try {
      await reviewsApi.update(editing.item_id, {
        status: editing.status,
        user_note: note,
      });
      toast({ kind: "success", title: "review item 已更新", body: editing.item_id });
      setEditing(null);
      setNote("");
      list.reload();
    } catch (e: unknown) {
      toast({
        kind: "error",
        title: "更新失败",
        body: isApiError(e) ? e.message : String(e),
      });
    }
  }

  return (
    <div
      style={{ display: "flex", flexDirection: "column", height: "100%" }}
      data-testid="page-reviews"
    >
      <div className="page-header">
        <div>
          <h1>Review Center</h1>
          <div className="subtitle">
            pending / accepted / ignored / modified — <strong>不修改原 artifact</strong>
          </div>
        </div>
        <div className="row-flex">
          {STATUS_OPTIONS.map((o) => (
            <button
              key={o.value}
              type="button"
              className={"btn sm " + (filter === o.value ? "primary" : "")}
              onClick={() => setFilter(o.value)}
              data-testid={`filter-${o.value}`}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>
      <div style={{ padding: 16, overflowY: "auto", flex: 1 }}>
        <AsyncView
          state={list.state}
          onRetry={list.reload}
          emptyText="无 review item"
          emptyHint="切换过滤条件或等待 agent run 触发 review"
        >
          {(d) => (
            <table className="tbl" data-testid="review-tbl">
              <thead>
                <tr>
                  <th>item_id</th>
                  <th>artifact</th>
                  <th>severity</th>
                  <th>category</th>
                  <th>status</th>
                  <th>note</th>
                  <th>actions</th>
                </tr>
              </thead>
              <tbody>
                {(d.items ?? []).map((it) => (
                  <tr key={it.item_id} data-testid={`review-${it.item_id}`}>
                    <td className="mono text-xs">{it.item_id}</td>
                    <td><InlineCode>{it.artifact_id}</InlineCode></td>
                    <td>
                      <Badge
                        kind={
                          it.severity === "error"
                            ? "err"
                            : it.severity === "warning"
                              ? "warn"
                              : "info"
                        }
                      >
                        {it.severity}
                      </Badge>
                    </td>
                    <td>{it.category}</td>
                    <td>
                      <Badge kind={STATUS_KIND[it.status]} withDot>
                        {it.status}
                      </Badge>
                    </td>
                    <td className="text-sm muted">
                      {it.user_note || <span className="muted">—</span>}
                    </td>
                    <td>
                      <button
                        className="btn sm"
                        type="button"
                        onClick={() => {
                          setEditing(it);
                          setNote(it.user_note ?? "");
                        }}
                        data-testid={`btn-edit-${it.item_id}`}
                      >
                        编辑
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </AsyncView>
      </div>

      {editing && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.4)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 200,
          }}
          onClick={() => setEditing(null)}
          data-testid="review-modal"
        >
          <div
            className="card"
            style={{ width: 480, padding: 16, background: "var(--bg-elev)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="row-flex" style={{ marginBottom: 8 }}>
              <span className="row-flex">
                <InlineCode>{editing.item_id}</InlineCode>
                <Badge kind={STATUS_KIND[editing.status]} withDot>
                  {editing.status}
                </Badge>
              </span>
            </div>
            <div className="text-sm muted mb-2">{editing.reason}</div>
            <textarea
              className="input"
              rows={4}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="user_note (可选)"
              data-testid="review-note-input"
            />
            <div className="row-flex mt-2">
              <select
                className="input"
                value={editing.status}
                onChange={(e) =>
                  setEditing({ ...editing, status: e.target.value as ReviewStatus })
                }
                data-testid="review-status-select"
                style={{ width: 160 }}
              >
                {(["pending", "accepted", "ignored", "modified"] as ReviewStatus[]).map(
                  (s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ),
                )}
              </select>
              <span className="spacer" />
              <button
                type="button"
                className="btn"
                onClick={() => setEditing(null)}
              >
                取消
              </button>
              <button
                type="button"
                className="btn primary"
                onClick={onSave}
                data-testid="btn-save-review"
              >
                保存
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
