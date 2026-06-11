import { useState, useRef, useEffect } from "react";
import { agentApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { useWorkbenchStore } from "../../stores/workbench";
import { useToastStore } from "../../stores/toast";
import { Badge } from "../../components/common";
import { isApiError } from "../../types";
import type { AgentResult, SourceSummary, ToolCallResult } from "../../types";
import {
  IconAlert,
  IconBolt,
  IconClose,
  IconRefresh,
  IconSend,
  IconSparkle,
} from "../../components/Icon";

const SUGGESTIONS = [
  "翻译 Cisco BGP 配置为 Huawei 命令",
  "OSPF 邻居状态从 FULL 变为 INIT，可能的原因？",
  "如何为分支节点选择出口策略？",
  "把这条配置做翻译 + 静态风险扫描",
];

export function AgentWorkbench() {
  const { currentWorkspaceId, currentSessionId } = useSessionStore();
  const { history, sending, appendUser, appendAssistant, setSending, clear } =
    useWorkbenchStore();
  const [input, setInput] = useState("");
  const streamRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const toast = useToastStore((s) => s.show);

  useEffect(() => {
    const el = streamRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [history.length, sending]);

  // Auto-grow the input
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, [input]);

  async function onSend() {
    const text = input.trim();
    if (!text || sending) return;
    if (!currentWorkspaceId) {
      toast({ kind: "warning", title: "未选择工作区", body: "请在左侧选择一个工作区" });
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
      const stubResult: AgentResult = {
        ok: false,
        final_response: `(error) ${msg}`,
        events: [],
        trace_id: isApiError(err) ? err.request_id ?? "—trace-failed" : "—trace-failed",
        session_id: currentSessionId ?? "—",
        turn_id: `turn-${Date.now()}`,
        tool_calls: [],
        warnings: [],
        errors: [msg],
        metadata: { source_count: 0, source_summary: [] },
      };
      appendAssistant(stubResult.final_response, stubResult);
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
    <div className="page" data-testid="page-workbench">
      <div className="page-header">
        <div>
          <h1>
            智能对话{" "}
            <span style={{ color: "var(--ink-mute)", fontWeight: 400, fontSize: 14 }}>
              · Agent Workbench
            </span>
          </h1>
          <div className="subtitle">
            发送一条消息；右侧 <em>检查器</em> 展示本次 turn 的执行细节
          </div>
        </div>
        <div className="row-flex">
          {sending && (
            <Badge kind="info" withDot>
              running
            </Badge>
          )}
          <button
            className="btn ghost sm"
            onClick={clear}
            disabled={history.length === 0}
            data-testid="btn-clear-history"
            type="button"
          >
            <IconRefresh size={12} /> 清空
          </button>
        </div>
      </div>

      <div className="chat-shell">
        <div className="chat-stream" ref={streamRef} data-testid="chat-stream">
          {history.length === 0 ? (
            <div className="chat-empty">
              <div className="hello">
                欢迎使用 <span>网工智枢</span>
              </div>
              <div className="sub">
                本地运行的 CodeX-style 网络工程 Agent。
                <br />
                在下方输入框中发送一条消息，或选择一个建议开始你的第一次 turn。
              </div>
              <div className="chat-suggestions">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    className="chat-suggestion"
                    type="button"
                    onClick={() => {
                      setInput(s);
                      inputRef.current?.focus();
                    }}
                  >
                    <IconSparkle
                      size={12}
                      style={{ marginRight: 6, color: "var(--accent)" }}
                    />
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            history.map((m) => (
              <ChatBubble key={m.id} role={m.role} text={m.text} result={m.result} />
            ))
          )}
          {sending && (
            <div className="chat-msg assistant">
              <div className="chat-avatar">智</div>
              <div className="chat-bubble" style={{ minWidth: 120 }}>
                <div className="row-flex" style={{ gap: 8 }}>
                  <span className="spinner" />
                  <span className="muted text-sm">agent 正在思考…</span>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="chat-input-shell">
          <div className="chat-input-wrap">
            <textarea
              ref={inputRef}
              className="chat-input"
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
              spellCheck={false}
              rows={1}
            />
            {input.length > 0 && (
              <button
                type="button"
                className="collapse-btn"
                onClick={() => setInput("")}
                aria-label="清空输入"
                style={{ width: 24, height: 24 }}
              >
                <IconClose size={12} />
              </button>
            )}
            <button
              className="chat-send-btn"
              onClick={onSend}
              disabled={sending || !input.trim()}
              data-testid="btn-send"
              type="button"
              aria-label="发送"
            >
              {sending ? <span className="spinner" /> : <IconSend size={14} />}
            </button>
          </div>
          <div className="chat-hint">
            本地 agent · Tool count 73 · planned (topology / inspection / cmdb) 仍 0 可见
          </div>
        </div>
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
      <div className="chat-avatar" aria-hidden>
        {role === "user" ? "U" : "智"}
      </div>
      <div style={{ flex: 1, minWidth: 0, maxWidth: "calc(100% - 44px)" }}>
        <div className="chat-bubble">{text || <span className="muted">(空消息)</span>}</div>
        {result && <ResultInline result={result} />}
      </div>
    </div>
  );
}

function ResultInline({ result }: { result: AgentResult }) {
  const summaries = Array.isArray(
    (result.metadata as { source_summary?: SourceSummary[] } | undefined)
      ?.source_summary,
  )
    ? ((result.metadata as { source_summary: SourceSummary[] }).source_summary ?? [])
    : [];

  return (
    <div className="chat-result-inline" data-testid="result-inline" style={{ marginTop: 8 }}>
      {/* Tool calls */}
      {(result.tool_calls ?? []).length > 0 && (
        <div className="chat-tool-calls">
          {result.tool_calls.map((tc) => (
            <ToolCallInline key={tc.call_id} tc={tc} />
          ))}
        </div>
      )}

      {/* Source summary */}
      {summaries.length > 0 && (
        <div className="chat-source-summary" data-testid="inline-source-summary">
          <b>知识源引用 · {summaries.length} 个</b>
          <div style={{ marginTop: 4 }}>
            {summaries.slice(0, 6).map((s, i) => (
              <span className="chat-source-chip" key={i}>
                {s.title || s.source_id}
                <span className="score">
                  {s.score != null ? ` ${s.score.toFixed(2)}` : ""}
                </span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Errors */}
      {result.errors && result.errors.length > 0 && (
        <div
          className="chat-warnings"
          data-testid="inline-errors"
          style={{ background: "var(--danger-soft)", color: "var(--danger)" }}
        >
          <IconAlert size={11} /> {result.errors.length} 个错误：{result.errors.join("；")}
        </div>
      )}
    </div>
  );
}

function ToolCallInline({ tc }: { tc: ToolCallResult }) {
  return (
    <div className="chat-tool-call" data-testid="inline-toolcall">
      <IconBolt size={11} style={{ color: "var(--accent)", flexShrink: 0 }} />
      <span className="tc-name">{tc.tool_id}</span>
      {tc.duration_ms != null && (
        <span className="tc-arg">· {tc.duration_ms}ms</span>
      )}
      <span className={"tc-status " + (tc.ok ? "ok" : "err")}>
        {tc.ok ? "ok" : "failed"}
      </span>
    </div>
  );
}
