import { useEffect, useState, type ReactNode } from "react";
import type { ApiError, AsyncState } from "../types";
import { isApiError, isError, isLoading } from "../types";

/* ── AsyncState renderer ── */

export interface AsyncViewProps<T> {
  state: AsyncState<T>;
  children: (data: T) => ReactNode;
  emptyText?: string;
  emptyHint?: string;
  loadingText?: string;
  onRetry?: () => void;
}

export function AsyncView<T>({
  state,
  children,
  emptyText = "暂无数据",
  emptyHint,
  loadingText = "加载中…",
  onRetry,
}: AsyncViewProps<T>) {
  if (isLoading(state)) {
    return (
      <div className="state">
        <div className="icon">
          <span className="status-dot loading" />
        </div>
        <div className="text">{loadingText}</div>
      </div>
    );
  }
  if (isError(state)) {
    return <ErrorState error={state.error} onRetry={onRetry} />;
  }
  if (state.kind === "empty") {
    return (
      <EmptyState text={emptyText} hint={emptyHint} />
    );
  }
  if (state.kind === "success") {
    return <>{children(state.data)}</>;
  }
  return <div className="state"><div className="text">未初始化</div></div>;
}

/* ── Error state ── */

export function ErrorState({
  error,
  onRetry,
}: {
  error: ApiError;
  onRetry?: () => void;
}) {
  return (
    <div className="state error" data-testid="error-state">
      <div className="icon">⚠</div>
      <div className="text">{error.message}</div>
      <div className="hint">
        {error.code} · {error.status > 0 ? `HTTP ${error.status}` : "no response"}
        {error.request_id ? ` · ${error.request_id}` : ""}
      </div>
      {onRetry && (
        <button className="btn sm mt-2" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  );
}

/* ── Empty state ── */

export function EmptyState({
  text = "暂无数据",
  hint,
  action,
}: {
  text?: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="state" data-testid="empty-state">
      <div className="icon">∅</div>
      <div className="text">{text}</div>
      {hint && <div className="hint">{hint}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

/* ── Loading state ── */

export function LoadingState({ text = "加载中…" }: { text?: string }) {
  return (
    <div className="state" data-testid="loading-state">
      <div className="icon">
        <span className="status-dot loading" />
      </div>
      <div className="text">{text}</div>
    </div>
  );
}

/* ── Badges & Status ── */

export type BadgeKind =
  | "ok"
  | "warn"
  | "err"
  | "info"
  | "pri"
  | "muted"
  | "planned";

export function Badge({
  kind = "muted",
  children,
  withDot = false,
}: {
  kind?: BadgeKind;
  children: ReactNode;
  withDot?: boolean;
}) {
  return (
    <span className={`badge ${kind}`} data-testid={`badge-${kind}`}>
      {withDot && <span className="dot" />}
      {children}
    </span>
  );
}

export function StatusDot({
  status,
  label,
}: {
  status: "ok" | "warn" | "err" | "idle" | "loading";
  label?: string;
}) {
  return (
    <span className="row-flex text-sm">
      <span className={`status-dot ${status}`} />
      {label && <span>{label}</span>}
    </span>
  );
}

/* ── Code block ── */

export function CodeBlock({
  children,
  language,
}: {
  children: string;
  language?: string;
}) {
  return (
    <pre data-testid="code-block" data-language={language}>
      {children}
    </pre>
  );
}

export function InlineCode({ children }: { children: ReactNode }) {
  return <code className="inline">{children}</code>;
}

/* ── Collapsible section ── */

export function Collapsible({
  title,
  defaultOpen = true,
  count,
  children,
}: {
  title: ReactNode;
  defaultOpen?: boolean;
  count?: number;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="inspector-section">
      <button
        className="row-flex"
        style={{ width: "100%", justifyContent: "space-between" }}
        onClick={() => setOpen((o) => !o)}
        data-testid="collapsible-toggle"
      >
        <h4 style={{ margin: 0 }}>
          {open ? "▾" : "▸"} {title}
          {typeof count === "number" && (
            <span className="muted text-xs" style={{ marginLeft: 6 }}>
              ({count})
            </span>
          )}
        </h4>
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  );
}

/* ── Hook: useAsync ── */

export function useAsync<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  deps: ReadonlyArray<unknown> = [],
  isEmpty?: (data: T) => boolean,
): {
  state: AsyncState<T>;
  reload: () => void;
} {
  const [state, setState] = useState<AsyncState<T>>({ kind: "idle" });
  const [reloadSeq, setReloadSeq] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    setState({ kind: "loading" });
    fn(ctrl.signal)
      .then((data) => {
        if (ctrl.signal.aborted) return;
        if (isEmpty && isEmpty(data)) {
          setState({ kind: "empty", reason: "predicate" });
        } else if (Array.isArray(data) && data.length === 0) {
          setState({ kind: "empty", reason: "list is empty" });
        } else {
          setState({ kind: "success", data });
        }
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (isApiError(err)) {
          setState({ kind: "error", error: err });
        } else {
          setState({
            kind: "error",
            error: {
              ok: false,
              status: 0,
              code: "unknown",
              message: String(err),
              timestamp: new Date().toISOString(),
            },
          });
        }
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadSeq]);

  return { state, reload: () => setReloadSeq((s) => s + 1) };
}
