import { useState, useRef, useEffect } from "react";
import { agentApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { useWorkbenchStore } from "../../stores/workbench";
import { useToastStore } from "../../stores/toast";
import {
  Badge,
  CodeBlock,
  EmptyState,
  InlineCode,
  LoadingState,
} from "../../components/common";
import { isApiError } from "../../types";
import type { AgentResult, SourceSummary, ToolCallResult } from "../../types";

/**
 * Agent Workbench — main entry. Center column is the chat / result stream.
 * Right column (Inspector) is rendered by AppLayout.
 */
export function AgentWorkbench() {
  const { currentWorkspaceId, currentSessionId } = useSessionStore();
  const { history, sending, appendUser, appendAssistant, setSending, clear } =
    useWorkbenchStore();
  const [input, setInput] = useState("");
  const streamRef = useRef<HTMLDivElement>(null);
  const toast = useToastStore((s) => s.show);

  // Auto-scroll on new messages.
  useEffect(() => {
    streamRef.current?.scrollTo({
      top: streamRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [history.length]);

  async function onSend() {
    const text = input.trim();
    if (!text || sending) return;
    if (!currentWorkspaceId) {
      toast({ kind: "warning", title: "未选择 workspace", body: "请在左侧选择 workspace" });
      return;
    }
    setInput("");
    appendUser(text);
    setSending(true);
    try {
      const res = await agentApi.run({
        message: text,
        workspace_id: currentWorkspaceId,
        session_id: currentSessionId,
      });
      appendAssistant(res.final_response ?? "", res);
      toast({ kind: "success", title: "turn 完成", body: res.trace_id });
    } catch (err: unknown) {
      const msg = isApiError(err) ? err.message : String(err);
      appendAssistant(`(error) ${msg}`);
      toast({
        kind: "error",
        title: "agent.run 失败",
        body: msg,
        request_id: isApiError(err) ? err.request_id : undefined,
      });
    } finally {
      setSending(false);
    }
  }

  return (
    <div
      style={{ display: "flex", flexDirection: "column", height: "100%" }}
      data-testid="page-workbench"
    >
      <div className="page-header">
        <div>
          <h1>Agent Workbench</h1>
          <div className="subtitle">
            选中 capability / skill / tool 后，发送一条消息；右侧 Inspector 展示 turn 细节
          </div>
        </div>
        <div className="row-flex">
          {sending && <Badge kind="info" withDot>running</Badge>}
          <button
            className="btn ghost sm"
            onClick={clear}
            disabled={history.length === 0}
            data-testid="btn-clear-history"
            type="button"
          >
            清空
          </button>
        </div>
      </div>

      <div className="chat-stream" ref={streamRef} data-testid="chat-stream">
        {history.length === 0 ? (
          <EmptyState
            text="尚无消息"
            hint="在下方输入框中发送一条消息开始一次 turn"
          />
        ) : (
          history.map((m) => <ChatBubble key={m.id} role={m.role} text={m.text} result={m.result} />)
        )}
        {sending && (
          <div className="chat-msg assistant">
            <div className="avatar">A</div>
            <div className="bubble">
              <LoadingState text="agent 正在思考…" />
            </div>
          </div>
        )}
      </div>

      <div className="chat-input">
        <textarea
          className="input"
          placeholder="输入消息…（Enter 发送，Shift+Enter 换行）"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void onSend();
            }
          }}
          disabled={sending}
          data-testid="chat-input"
        />
        <button
          className="btn primary"
          onClick={onSend}
          disabled={sending || !input.trim()}
          data-testid="btn-send"
          type="button"
        >
          发送
        </button>
      </div>
    </div>
  );
}

function ChatBubble({
  role,
  text,
  result,
}: {
  role: "user" | "assistant" | "system";
  text: string;
  result?: AgentResult;
}) {
  return (
    <div className={`chat-msg ${role}`} data-testid={`chat-${role}`}>
      <div className="avatar">{role === "user" ? "U" : "A"}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="bubble">{text || <span className="muted">(empty)</span>}</div>
        {result && <ResultInline result={result} />}
      </div>
    </div>
  );
}

function ResultInline({ result }: { result: AgentResult }) {
  return (
    <div className="mt-2" data-testid="result-inline">
      {(result.tool_calls ?? []).map((tc) => (
        <ToolCallInline key={tc.call_id} tc={tc} />
      ))}
      {result.metadata && result.metadata.source_count ? (
        <SourceSummaryInline
          summaries={Array.isArray((result.metadata as { source_summary?: SourceSummary[] })
            .source_summary) ? (result.metadata as { source_summary: SourceSummary[] })
            .source_summary : []}
        />
      ) : null}
      {result.errors && result.errors.length > 0 && (
        <div className="card" style={{ borderColor: "var(--danger)" }}>
          <div className="card-title" style={{ color: "var(--danger)" }}>Errors</div>
          <ul className="text-sm">
            {result.errors.map((e, i) => <li key={i}>{e}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function ToolCallInline({ tc }: { tc: ToolCallResult }) {
  return (
    <div className="card" data-testid="inline-toolcall" style={{ padding: 10 }}>
      <div className="row-flex" style={{ justifyContent: "space-between" }}>
        <span className="row-flex">
          <InlineCode>{tc.tool_id}</InlineCode>
          {tc.ok ? <Badge kind="ok" withDot>ok</Badge> : <Badge kind="err" withDot>failed</Badge>}
        </span>
        {typeof tc.duration_ms === "number" && (
          <span className="muted text-xs">{tc.duration_ms}ms</span>
        )}
      </div>
      {typeof tc.result === "string" && tc.result.length > 0 && (
        <details className="mt-2">
          <summary className="text-xs muted">result</summary>
          <CodeBlock>{tc.result}</CodeBlock>
        </details>
      )}
    </div>
  );
}

function SourceSummaryInline({ summaries }: { summaries: SourceSummary[] }) {
  if (summaries.length === 0) return null;
  return (
    <div className="card" data-testid="inline-source-summary">
      <div className="card-title">Knowledge Source Summary</div>
      {summaries.slice(0, 5).map((s, i) => (
        <div key={i} className="text-sm" style={{ marginBottom: 6 }}>
          <Badge kind="info">src {i + 1}</Badge>{" "}
          <InlineCode>{s.title || s.source_id}</InlineCode>
          {s.chapter && <span className="muted"> · {s.chapter}</span>}
          {s.section && <span className="muted"> / {s.section}</span>}
          <div className="muted text-sm mt-2">{s.snippet}</div>
        </div>
      ))}
    </div>
  );
}
