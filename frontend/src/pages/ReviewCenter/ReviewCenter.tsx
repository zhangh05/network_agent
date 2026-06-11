import { useState } from "react";
import { reviewsApi } from "../../api";
import { useAsync, AsyncView, Badge, InlineCode } from "../../components/common";
import { useSessionStore } from "../../stores/session";
import { useToastStore } from "../../stores/toast";
import { isApiError } from "../../types";
import type { ReviewItem, ReviewStatus } from "../../types";

const STATUS_OPTIONS: { value: ReviewStatus | "all"; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "pending", label: "待处理" },
  { value: "accepted", label: "已接受" },
  { value: "ignored", label: "已忽略" },
  { value: "modified", label: "已修改" },
];

const STATUS_KIND: Record<ReviewStatus, "s-pending" | "s-accepted" | "s-ignored" | "s-modified"> = {
  pending: "s-pending",
  accepted: "s-accepted",
  ignored: "s-ignored",
  modified: "s-modified",
};

const STATUS_LABEL: Record<ReviewStatus, string> = {
  pending: "待处理",
  accepted: "已接受",
  ignored: "已忽略",
  modified: "已修改",
};

/**
 * Review Center — list / update review items. Never mutates the
 * original artifact; only writes `user_note` and `status`.
 *
 * Real backend endpoints (v1.0.1):
 *   GET /api/workspaces/<ws_id>/review-items?status=
 *   PUT /api/review-items/<item_id>?workspace_id=&artifact_id=
 */
export function ReviewCenter() {
  const { currentWorkspaceId } = useSessionStore();
  const toast = useToastStore((s) => s.show);
  const [filter, setFilter] = useState<ReviewStatus | "all">("pending");
  const [editing, setEditing] = useState<ReviewItem | null>(null);
  const [note, setNote] = useState("");

  const list = useAsync<{ items: ReviewItem[]; count: number }>(
    (s) =>
      currentWorkspaceId
        ? reviewsApi.list(currentWorkspaceId, filter === "all" ? undefined : filter, s)
        : Promise.resolve({ items: [], count: 0 }),
    [currentWorkspaceId, filter],
    (d) => (d.items ?? []).length === 0,
  );

  async function onSave() {
    if (!editing || !currentWorkspaceId) return;
    const artifact_id = (editing as ReviewItem & { artifact_id?: string }).artifact_id;
    if (!artifact_id) {
      toast({
        kind: "error",
        title: "无法更新",
        body: "review item 缺少 artifact_id（后端不提供 list 返回值的 artifact 范围时无法定位）",
      });
      return;
    }
    try {
      await reviewsApi.update(editing.item_id, {
        status: editing.status,
        user_note: note,
        workspace_id: currentWorkspaceId,
        artifact_id,
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
        request_id: isApiError(e) ? e.request_id : undefined,
      });
    }
  }

  return (
    <div className="page" data-testid="page-reviews">
      <div className="page-header">
        <div>
          <h1>
            评审中心{" "}
            <span style={{ color: "var(--ink-mute)", fontWeight: 400, fontSize: 14 }}>
              · Review Center
            </span>
          </h1>
          <div className="subtitle">
            待处理 / 已接受 / 已忽略 / 已修改 — <strong>不</strong>修改原 artifact
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
      <div className="page-body">
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
                  <th>严重度</th>
                  <th>分类</th>
                  <th>状态</th>
                  <th>备注</th>
                  <th style={{ width: 90 }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {(d.items ?? []).map((it) => {
                  const artifactId = (it as ReviewItem & { artifact_id?: string }).artifact_id;
                  return (
                    <tr key={it.item_id} data-testid={`review-${it.item_id}`}>
                      <td className="mono text-xs">{it.item_id}</td>
                      <td>
                        {artifactId ? <InlineCode>{artifactId}</InlineCode> : <span className="muted">—</span>}
                      </td>
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
                          {it.severity === "error" ? "错误" : it.severity === "warning" ? "警告" : "提示"}
                        </Badge>
                      </td>
                      <td>{(it as ReviewItem & { category?: string }).category || <span className="muted">—</span>}</td>
                      <td>
                        <Badge kind={STATUS_KIND[it.status]} withDot>
                          {STATUS_LABEL[it.status]}
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
                  );
                })}
              </tbody>
            </table>
          )}
        </AsyncView>
      </div>

      {editing && (
        <div
          className="modal-backdrop"
          onClick={() => setEditing(null)}
          data-testid="review-modal"
        >
          <div
            className="modal"
            onClick={(e) => e.stopPropagation()}
            style={{ minWidth: 460 }}
          >
            <div className="modal-title">
              <InlineCode>{editing.item_id}</InlineCode>
              <Badge kind={STATUS_KIND[editing.status]} withDot>
                {STATUS_LABEL[editing.status]}
              </Badge>
            </div>
            <div className="text-sm muted mb-3" style={{ padding: 10, background: "var(--bg-soft)", borderRadius: "var(--r-sm)" }}>
              {editing.reason ||
                (editing as ReviewItem & { category?: string }).category ||
                "(无说明)"}
            </div>
            <textarea
              className="input"
              rows={4}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="user_note（可选）"
              data-testid="review-note-input"
            />
            <div className="row-flex mt-3" style={{ gap: 8 }}>
              <select
                className="input"
                value={editing.status}
                onChange={(e) =>
                  setEditing({ ...editing, status: e.target.value as ReviewStatus })
                }
                data-testid="review-status-select"
                style={{ width: 180 }}
              >
                {(["pending", "accepted", "ignored", "modified"] as ReviewStatus[]).map(
                  (s) => (
                    <option key={s} value={s}>
                      {STATUS_LABEL[s]}
                    </option>
                  ),
                )}
              </select>
              <span className="spacer" />
              <div className="modal-actions" style={{ marginTop: 0 }}>
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
        </div>
      )}
    </div>
  );
}
