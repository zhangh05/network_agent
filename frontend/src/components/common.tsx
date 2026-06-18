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
      <div className="empty" data-testid="loading-state">
        <div className="empty-icon">
          <span className="spinner" />
        </div>
        <div className="empty-text">{loadingText}</div>
      </div>
    );
  }
  if (isError(state)) {
    return <ErrorState error={state.error} onRetry={onRetry} />;
  }
  if (state.kind === "empty") {
    return <EmptyState text={emptyText} hint={emptyHint} />;
  }
  if (state.kind === "success") {
    return <>{children(state.data)}</>;
  }
  return <div className="empty"><div className="empty-text">未初始化</div></div>;
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
    <div className="empty" data-testid="error-state">
      <div className="empty-icon">
        <span style={{ fontSize: 20, color: "var(--danger)" }}>⚠</span>
      </div>
      <div className="empty-text" style={{ color: "var(--danger)" }}>{error.message}</div>
      <div className="empty-hint">
        {error.code} · {error.status > 0 ? `HTTP ${error.status}` : "无响应"}
        {error.request_id ? ` · ${error.request_id}` : ""}
      </div>
      {onRetry && (
        <button className="btn sm mt-2" onClick={onRetry} type="button">
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
    <div className="empty" data-testid="empty-state">
      <div className="empty-icon">
        <span style={{ fontSize: 18, color: "var(--ink-faint)" }}>∅</span>
      </div>
      <div className="empty-text">{text}</div>
      {hint && <div className="empty-hint">{hint}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

/* ── Loading state ── */

export function LoadingState({ text = "加载中…" }: { text?: string }) {
  return (
    <div className="empty" data-testid="loading-state">
      <div className="empty-icon">
        <span className="spinner" />
      </div>
      <div className="empty-text">{text}</div>
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
  | "planned"
  | "accent"
  | "s-pending"
  | "s-accepted"
  | "s-ignored"
  | "s-modified";

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
  status: "ok" | "warn" | "err" | "idle" | "loading" | "busy";
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
  return <code>{children}</code>;
}

/* ── Field (form row) ── */

export function Field({
  label,
  hint,
  children,
  htmlFor,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="col-flex" style={{ gap: 6 }}>
      <label
        htmlFor={htmlFor}
        style={{
          fontSize: 11,
          color: "var(--ink-mute)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          fontWeight: 500,
        }}
      >
        {label}
      </label>
      {children}
      {hint && (
        <span style={{ fontSize: 11, color: "var(--ink-faint)" }}>{hint}</span>
      )}
    </div>
  );
}

/* ── Collapsible section (used by Inspector) ── */

export function Collapsible({
  title,
  defaultOpen = true,
  count,
  children,
  testid,
}: {
  title: ReactNode;
  defaultOpen?: boolean;
  count?: number;
  children: ReactNode;
  testid?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="inspector-section" data-testid={testid}>
      <button
        className={"inspector-section-title" + (open ? "" : " collapsed")}
        style={{
          width: "100%",
          background: "none",
          border: "none",
          padding: 0,
        }}
        onClick={() => setOpen((o) => !o)}
        data-testid="collapsible-toggle"
        type="button"
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span className="chev">▾</span>
          {title}
          {typeof count === "number" && count > 0 && (
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                color: "var(--ink-mute)",
                background: "var(--bg-soft)",
                padding: "1px 6px",
                borderRadius: 8,
                fontWeight: 400,
                letterSpacing: 0,
                textTransform: "none",
              }}
            >
              {count}
            </span>
          )}
        </span>
      </button>
      {open && <div style={{ marginTop: 4 }}>{children}</div>}
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
