import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "center",
          justifyContent: "center", height: "100vh", gap: 16,
          padding: 40, fontFamily: "system-ui, sans-serif",
          background: "var(--surface, #fff)", color: "var(--text, #333)",
        }}>
          <div style={{ fontSize: 48, opacity: 0.3 }}>⚠</div>
          <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>应用发生错误</h1>
          <p style={{ fontSize: 14, color: "var(--text-3, #888)", maxWidth: 480, textAlign: "center", lineHeight: 1.6 }}>
            请刷新页面 (Cmd+Shift+R) 重试。如持续出现，请在系统设置的 LLM 配置中确认设置后，清除浏览器 localStorage 数据。
          </p>
          <details style={{ maxWidth: 560, width: "100%" }}>
            <summary style={{ cursor: "pointer", fontSize: 12, color: "var(--text-2, #666)" }}>错误详情</summary>
            <pre style={{
              marginTop: 8, padding: 12, background: "var(--surface-2, #f5f5f5)",
              borderRadius: 6, fontSize: 11, whiteSpace: "pre-wrap",
              wordBreak: "break-all", maxHeight: 300, overflow: "auto",
            }}>
              {this.state.error?.message ?? "Unknown"}
              {"\n\n"}
              {this.state.error?.stack ?? ""}
            </pre>
          </details>
          <button
            onClick={() => window.location.reload()}
            style={{
              padding: "8px 24px", fontSize: 14, cursor: "pointer",
              background: "var(--accent)", color: "#fff", border: "none",
              borderRadius: 6, fontWeight: 600,
            }}
            type="button"
          >
            刷新页面
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
