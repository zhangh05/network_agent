import { useEffect, useState, useCallback, useRef, type ReactNode } from "react";
import { PortalModal } from "./PortalModal";
import { Button } from "./ui/Button";

/**
 * Pre-built confirm dialog state stored in a global ref so any component can
 * `confirm({ title, body, ... })` and get a Promise<boolean> back. The dialog
 * itself is rendered once at the application root via <ConfirmHost />. Replaces
 * the global `window.confirm` calls that used to bypass the React tree (and
 * fail in jsdom / Electron-style contexts).
 */
export interface ConfirmSpec {
  title: string;
  body?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
}

interface ConfirmState extends ConfirmSpec {
  resolve: (value: boolean) => void;
}

const listeners = new Set<(state: ConfirmState | null) => void>();

function emit(state: ConfirmState | null) {
  for (const listener of listeners) listener(state);
}

export function confirm(spec: ConfirmSpec): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    emit({ ...spec, resolve });
  });
}

/** Mount once at the app root. Renders nothing when no confirm is pending. */
export function ConfirmHost() {
  const [state, setState] = useState<ConfirmState | null>(null);
  useEffect(() => {
    const listener = (next: ConfirmState | null) => setState(next);
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  }, []);

  if (!state) return null;

  const close = (value: boolean) => {
    state.resolve(value);
    emit(null);
  };

  const onCloseRef = useRef(close);
  onCloseRef.current = close;
  const onClose = useCallback(() => onCloseRef.current(false), []);

  return (
    <PortalModal open onClose={onClose} testId="confirm-dialog">
      <div className="confirm-dialog">
        <h3 className="confirm-dialog-title">{state.title}</h3>
        {state.body && <div className="confirm-dialog-body">{state.body}</div>}
        <div className="row-flex-sm confirm-dialog-actions">
          <Button onClick={() => close(false)} size="sm">{state.cancelLabel ?? "取消"}</Button>
          <Button
            variant={state.destructive ? "danger" : "primary"}
            size="sm"
            onClick={() => close(true)}
            data-testid="confirm-dialog-confirm"
          >
            {state.confirmLabel ?? "确认"}
          </Button>
        </div>
      </div>
    </PortalModal>
  );
}
