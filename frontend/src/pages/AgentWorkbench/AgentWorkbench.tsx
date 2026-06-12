import { useState, useRef, useEffect } from "react";
import { agentApi, runtimeApi, sessionsApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { useWorkbenchStore } from "../../stores/workbench";
import { useToastStore } from "../../stores/toast";
import { Badge } from "../../components/common";
import { isApiError } from "../../types";
import type { AgentResult, SourceSummary, ToolCallResult } from "../../types";
import { sanitizeAssistantText } from "../../utils/displayText";
import { notifyRunCompleted } from "../../utils/appEvents";
import { TIMEOUTS } from "../../api/client";
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
  const {
    history,
    sending,
    lastUserInput,
    latestResult,
    appendUser,
    appendAssistant,
    setSending,
    clear,
    switchSession,
    mergeFromBackend,
  } = useWorkbenchStore();
  const [input, setInput] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [runtimeSummary, setRuntimeSummary] = useState<string>(
    "工具状态加载中 · 能力状态加载中",
  );
  const streamRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const toast = useToastStore((s) => s.show);

  useEffect(() => {
    const ctrl = new AbortController();
    runtimeApi
      .summary(ctrl.signal)
      .then((res) => {
        setRuntimeSummary(
          `工具 ${res.tools.model_visible}/${res.tools.registered} 可见 · ` +
          `能力 ${res.capabilities.enabled}/${res.capabilities.total} 已启用 · ` +
          `规划中 ${res.capabilities.planned}`,
        );
      })
      .catch(() => {
        setRuntimeSummary("工具状态不可用 · 能力状态不可用");
      });
    return () => ctrl.abort();
  }, []);

  // Elapsed-time ticker — gives the user a sense of "still working"
  // for long agent turns (web search, multi-tool, LLM slow).
  useEffect(() => {
    if (!sending) {
      setElapsed(0);
      return;
    }
    const t0 = Date.now();
    setElapsed(0);
    const id = window.setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => window.clearInterval(id);
  }, [sending]);

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

  // Session switch + background fetch (plan-C)
  // 1) 切到新会话时, 立刻从 localStorage 恢复历史 (instant render)
  // 2) 后台拉 /api/sessions/<id>/messages, merge 到 local (跨设备/跨 tab)
  useEffect(() => {
    switchSession(currentSessionId);
    if (!currentSessionId || !currentWorkspaceId) return;
    const ctrl = new AbortController();
    sessionsApi
      .messages(currentSessionId, currentWorkspaceId, ctrl.signal)
      .then((res) => {
        const list = res.messages ?? [];
        if (list.length > 0) {
          mergeFromBackend(currentSessionId, list);
        }
      })
      .catch(() => {
        /* 静默 — local 足够好 */
      });
    return () => ctrl.abort();
  }, [currentSessionId, currentWorkspaceId, switchSession, mergeFromBackend]);

  async function onSend() {
    const text = input.trim();
    if (!text || sending) return;
    if (!currentWorkspaceId) {
      toast({ kind: "warning", title: "未选择工作区", body: "请在左侧选择一个工作区" });
      return;
    }
    setInput("");
    // plan-C: 用 scratch 池存放「无 session 时的瞬时消息」, 等后端返回
    // session_id 后再迁移到正式 bySession. 避免 UI 看起来消息「消失」.
    const scratch = currentSessionId;
    appendUser(text, scratch);
    setSending(true);
    try {
      const res = await agentApi.run({
        message: text,
        workspace_id: currentWorkspaceId,
        session_id: currentSessionId,
      });
      // 后端可能在 session_id=null 时自动新建会话 (agent.run 的 fallback)
      // 此时把 scratch 池迁到真正的 session_id 下
      const resolvedSid =
        res.session_id && res.session_id !== "—"
          ? res.session_id
          : currentSessionId;
      if (!currentSessionId && resolvedSid) {
        useSessionStore.getState().setCurrentSession(resolvedSid);
        // 把 _scratch 池里这次 onSend 累积的两条消息迁过去
        // 用 functional updater 避免与 mergeFromBackend 产生竞态
        useWorkbenchStore.setState((prev) => {
          const scratchMsgs = (prev.bySession["_scratch"] ?? []);
          const existing = prev.bySession[resolvedSid] ?? [];
          return {
            bySession: { ...prev.bySession, [resolvedSid]: [...existing, ...scratchMsgs], _scratch: [] },
          };
        });
        useWorkbenchStore.getState().switchSession(resolvedSid);
      }
      appendAssistant(sanitizeAssistantText(res.final_response ?? ""), res, resolvedSid);
      notifyRunCompleted();
      toast({ kind: "success", title: "turn 完成", body: res.trace_id });
      // 拉一次 backend 让云端历史落地 (后端修了 run_ids bug 才有效)
      if (resolvedSid && currentWorkspaceId) {
        sessionsApi
          .messages(resolvedSid, currentWorkspaceId)
          .then((r) => {
            if (r.messages && r.messages.length > 0) {
              mergeFromBackend(resolvedSid, r.messages);
            }
          })
          .catch((e) => {
            console.warn("背景同步未命中:", e?.message ?? "未知错误");
          });
      }
    } catch (err: unknown) {
      const msg = isApiError(err) ? err.message : String(err);
      const stubResult: AgentResult = {
        ok: false,
        final_response: sanitizeAssistantText(`(error) ${msg}`),
        events: [],
        trace_id: isApiError(err) ? err.request_id ?? "—trace-failed" : "—trace-failed",
        session_id: currentSessionId ?? "—",
        turn_id: `turn-${Date.now()}`,
        tool_calls: [],
        warnings: [],
        errors: [msg],
        metadata: { source_count: 0, source_summary: [] },
      };
      appendAssistant(stubResult.final_response, stubResult, scratch);
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
          {/* 持久化指示: 当前会话有本地历史 → 显示 "本地缓存" */}
          {history.length > 0 && (
            <span
              className="status-pill"
              data-testid="wb-persisted-indicator"
              data-tip="本会话历史已写入 localStorage, F5 刷新不丢"
            >
              <span className="dot" />
              <span>本地缓存 {history.length}</span>
            </span>
          )}
          <button
            className="btn ghost sm"
            onClick={() => clear()}
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
                本地运行的 Codex-style 网络工程 Agent。
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
            <div className="chat-msg assistant" data-testid="chat-sending">
              <div className="chat-avatar">智</div>
              <div className="chat-bubble" style={{ minWidth: 200 }}>
                <div className="row-flex" style={{ gap: 8, alignItems: "center" }}>
                  <span className="spinner" />
                  <span className="muted text-sm">agent 正在思考…</span>
                  <span
                    className="mono text-xs"
                    style={{ marginLeft: "auto", color: "var(--ink-faint)" }}
                    data-testid="chat-elapsed"
                  >
                    {formatElapsed(elapsed)} / {formatElapsed(TIMEOUTS.agentTurn / 1000)}
                  </span>
                </div>
                {elapsed > 30 && (
                  <div
                    className="text-xs mt-2"
                    style={{ color: "var(--ink-mute)" }}
                  >
                    Agent turn 较慢（含 LLM 推理 / 工具调用 / 可选 web search），
                    最长可等 {formatElapsed(TIMEOUTS.agentTurn / 1000)}
                  </div>
                )}
              </div>
            </div>
          )}
          {!sending && latestResult && !latestResult.ok && lastUserInput && (
            <div className="card" style={{ padding: "8px 14px", display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
              <span className="text-sm" style={{ color: "var(--danger)" }}>上次回复失败</span>
              <button
                className="btn btn-sm btn-outline"
                onClick={() => { setInput(lastUserInput); }}
                data-testid="retry-btn"
              >
                一键重试
              </button>
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
          <div className="chat-hint" data-testid="runtime-summary-hint">
            本地 agent · {runtimeSummary}
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
        <div className="chat-bubble">{sanitizeAssistantText(text) || <span className="muted">(空消息)</span>}</div>
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
      <span className={"tc-status " + (tc.ok ? "ok" : "err")}>
        {tc.ok ? "ok" : "failed"}
      </span>
    </div>
  );
}

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m${s.toString().padStart(2, "0")}s`;
}
