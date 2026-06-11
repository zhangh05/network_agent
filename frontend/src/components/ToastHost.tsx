import { useToastStore } from "../stores/toast";

export function ToastHost() {
  const { messages, dismiss } = useToastStore();
  if (messages.length === 0) return null;
  return (
    <div className="toast-host" data-testid="toast-host">
      {messages.map((m) => (
        <div key={m.id} className={`toast ${m.kind}`} role="status">
          <div className="body">
            <div className="title">{m.title}</div>
            {m.body && <div className="hint">{m.body}</div>}
            {m.request_id && (
              <div className="hint mono">req_id: {m.request_id}</div>
            )}
          </div>
          <button
            onClick={() => dismiss(m.id)}
            aria-label="dismiss"
            type="button"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
