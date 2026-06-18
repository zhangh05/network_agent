import { useToastStore } from "../stores/toast";
import { IconClose } from "./Icon";

export function ToastHost() {
  const { messages, dismiss } = useToastStore();
  if (messages.length === 0) return null;
  return (
    <div
      className="toast-host"
      data-testid="toast-host"
      role="status"
      aria-live="polite"
    >
      {messages.map((m) => (
        <div key={m.id} className={`toast ${m.kind}`} role="alert">
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="toast-title">{m.title}</div>
            {m.body && <div className="toast-body">{m.body}</div>}
            {m.request_id && (
              <div className="toast-req">req_id: {m.request_id}</div>
            )}
          </div>
          <button
            onClick={() => dismiss(m.id)}
            aria-label="关闭通知"
            type="button"
            style={{
              background: "none",
              border: "none",
              padding: 2,
              cursor: "pointer",
              color: "var(--ink-mute)",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <IconClose size={12} />
          </button>
        </div>
      ))}
    </div>
  );
}
