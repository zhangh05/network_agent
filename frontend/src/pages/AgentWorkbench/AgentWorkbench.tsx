import { useState, useRef, useEffect } from "react";
import { agentApi, runtimeApi, sessionsApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { useWorkbenchStore } from "../../stores/workbench";
import { useToastStore } from "../../stores/toast";
import { useUIStore } from "../../stores/session";
import { isApiError } from "../../types";
import type { AgentResult, SourceSummary, ToolCallResult } from "../../types";
import { sanitizeAssistantText } from "../../utils/displayText";
import { notifyRunCompleted } from "../../utils/appEvents";
import { TIMEOUTS } from "../../api/client";
import { IconAlert, IconBolt, IconSend } from "../../components/Icon";

const QUICK_CHIPS = ["排查 OSPF 邻居", "翻译配置", "分析出口策略"];

function _humanFailure(text: string): string {
  if (text.includes("provider_timeout") || text.includes("timed out") || text.includes("超时"))
    return "模型请求超过 30 秒未返回，可能是供应商响应慢或网络抖动。可以稍后重试，或缩短问题再试。";
  if (text.includes("disabled") || text.includes("LLM is disabled"))
    return "LLM 功能未启用，请前往系统设置开启并配置 API Key。";
  if (text.includes("api_key") || text.includes("authentication"))
    return "API 密钥未配置或已失效，请前往系统设置重新设置。";
  return text;
}

export function AgentWorkbench() {
  const { currentWorkspaceId, currentSessionId } = useSessionStore();
  const {
    history, sending, lastUserInput, latestResult,
    appendUser, appendAssistant, setSending, clear, switchSession, mergeFromBackend,
  } = useWorkbenchStore();
  const inspectorOpen = useUIStore((s) => s.inspectorOpen);
  const toggleInspector = useUIStore((s) => s.toggleInspector);

  const [input, setInput] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [llmHealth, setLlmHealth] = useState<{ connected: boolean; recentFailure?: string }>({ connected: false });
  const chatRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const toast = useToastStore((s) => s.show);

  // LLM health poll
  useEffect(() => {
    const poll = () => {
      import("../../api").then(({ settingsApi }) => {
        settingsApi.llmStatus().then((s) => {
          if (!s) return;
          setLlmHealth({
            connected: s.connected,
            recentFailure: s.recent_failure?.error_type ? s.recent_failure.error_summary : undefined,
          });
        }).catch(() => {});
      });
    };
    poll();
    const id = window.setInterval(poll, 30_000);
    return () => window.clearInterval(id);
  }, []);

  // Elapsed timer
  useEffect(() => {
    if (!sending) { setElapsed(0); return; }
    setElapsed(0);
    const t0 = Date.now();
    const id = window.setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => window.clearInterval(id);
  }, [sending]);

  // Scroll on new messages
  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: "smooth" });
  }, [history.length, sending]);

  // Auto-grow input
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 140) + "px";
  }, [input]);

  // Session switch + sync
  useEffect(() => {
    switchSession(currentSessionId);
    if (!currentSessionId || !currentWorkspaceId) return;
    const ctrl = new AbortController();
    sessionsApi.messages(currentSessionId, currentWorkspaceId, ctrl.signal)
      .then((res) => { if (res.messages?.length) mergeFromBackend(currentSessionId, res.messages); })
      .catch(() => {});
    return () => ctrl.abort();
  }, [currentSessionId, currentWorkspaceId]);

  async function onSend(textOverride?: string) {
    const raw = typeof textOverride === "string" ? textOverride : input;
    const text = raw.trim();
    if (!text || sending) return;
    if (!currentWorkspaceId) {
      toast({ kind: "warning", title: "未选择工作区", body: "请在左侧选择一个工作区" });
      return;
    }
    setInput("");
    const scratch = currentSessionId;
    appendUser(text, scratch);
    setSending(true);
    try {
      const res = await agentApi.run({ message: text, workspace_id: currentWorkspaceId, session_id: currentSessionId });
      const resolvedSid = res.session_id && res.session_id !== "—" ? res.session_id : currentSessionId;
      if (!currentSessionId && resolvedSid) {
        useSessionStore.getState().setCurrentSession(resolvedSid);
        useWorkbenchStore.setState((prev) => {
          const scratchMsgs = prev.bySession["_scratch"] ?? [];
          const existing = prev.bySession[resolvedSid] ?? [];
          return { bySession: { ...prev.bySession, [resolvedSid]: [...existing, ...scratchMsgs], _scratch: [] } };
        });
        useWorkbenchStore.getState().switchSession(resolvedSid);
      }
      appendAssistant(sanitizeAssistantText(res.final_response ?? ""), res, resolvedSid);
      notifyRunCompleted();
      if (res.ok) {
        toast({ kind: "success", title: "回答完成", body: "可在右侧检查器查看详情" });
      } else {
        toast({ kind: "error", title: "请求失败", body: _humanFailure(res.errors?.[0] ?? "") });
      }
      if (resolvedSid && currentWorkspaceId) {
        sessionsApi.messages(resolvedSid, currentWorkspaceId)
          .then((r) => { if (r.messages?.length) mergeFromBackend(resolvedSid, r.messages); })
          .catch((e) => console.warn("背景同步未命中:", e?.message ?? "未知错误"));
      }
    } catch (err: unknown) {
      const msg = isApiError(err) ? err.message : String(err);
      const stubResult: AgentResult = {
        ok: false, final_response: sanitizeAssistantText(`(error) ${msg}`),
        events: [], trace_id: isApiError(err) ? err.request_id ?? "—" : "—",
        session_id: currentSessionId ?? "—", turn_id: `turn-${Date.now()}`,
        tool_calls: [], warnings: [], errors: [msg],
        metadata: { source_count: 0, source_summary: [] },
      };
      appendAssistant(stubResult.final_response, stubResult, scratch);
      toast({ kind: "error", title: "请求失败", body: msg });
    } finally {
      setSending(false);
    }
  }

  function pickChip(chip: string) {
    setInput(chip);
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  const llmStatusLabel = llmHealth.connected
    ? llmHealth.recentFailure ? "LLM 可用 · 最近一次请求超时，可重试" : "LLM 可用 · MiniMax-M3"
    : "LLM 离线";

  return (
    <div className="wb-shell" style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* ── Header bar ── */}
      <div className="wb-header">
        <div className="wb-header-status">
          <span className={"dot " + (llmHealth.connected ? (llmHealth.recentFailure ? "warn" : "ok") : "err")} />
          <span>{llmStatusLabel}</span>
        </div>
        <div className="wb-quick-chips">
          {QUICK_CHIPS.map((c) => (
            <button key={c} className="wb-quick-chip" type="button" onClick={() => pickChip(c)}>
              {c}
            </button>
          ))}
        </div>
      </div>

      {/* ── Chat area ── */}
      <div className="wb-chat" ref={chatRef} data-testid="chat-stream">
        {history.length === 0 && !sending ? (
          <div className="wb-empty" data-testid="workbench-empty">
            <h2>网络工程 AI 工作台</h2>
            <p>描述网络问题、粘贴配置或输入排查目标，即可开始。</p>
            <div className="wb-empty-chips">
              {QUICK_CHIPS.map((c) => (
                <button key={c} className="wb-input-chip" type="button" onClick={() => pickChip(c)}>
                  {c}
                </button>
              ))}
            </div>
          </div>
        ) : (
          history.map((m) => (
            <div key={m.id} className={`chat-msg ${m.role}`} data-testid={`chat-${m.role}`}>
              <div className="msg-inner">
                <div className="chat-bubble">
                  {sanitizeAssistantText(m.text) || <span className="muted">(空消息)</span>}
                </div>
                {m.result && m.role === "assistant" && <ResultInline result={m.result} />}
              </div>
            </div>
          ))
        )}

        {sending && (
          <div className="wb-sending" data-testid="chat-sending">
            <div className="bubble">
              <span className="spinner" />
              <span>agent 正在分析…</span>
              <span className="text-xs" style={{ color: "var(--ink-faint)", marginLeft: "auto" }}>
                {formatElapsed(elapsed)} / {formatElapsed(TIMEOUTS.agentTurn / 1000)}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* ── Retry bar ── */}
      {!sending && latestResult && !latestResult.ok && lastUserInput && (
        <div className="wb-retry-bar">
          <IconAlert size={11} />
          <span>{_humanFailure(latestResult.errors?.[0] ?? "请求失败")}</span>
          <button type="button" onClick={() => onSend(lastUserInput)} data-testid="retry-btn">
            自动重试
          </button>
        </div>
      )}

      {/* ── Input bar ── */}
      <div className="wb-input-bar">
        <div className="wb-input-chips">
          {QUICK_CHIPS.map((c) => (
            <button key={c} className="wb-input-chip" type="button" onClick={() => pickChip(c)}>
              {c}
            </button>
          ))}
        </div>
        <div className="wb-input-row">
          <textarea
            ref={inputRef}
            className="wb-input"
            placeholder="描述网络问题、粘贴配置或输入排查目标…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); } }}
            disabled={sending}
            rows={1}
            data-testid="chat-input"
            spellCheck={false}
          />
          <button
            className="wb-send"
            onClick={() => onSend()}
            disabled={sending || !input.trim()}
            data-testid="btn-send"
            type="button"
            aria-label="发送"
          >
            <IconSend size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}

/* ==============================================================
   Sub-components
   ============================================================== */

function ResultInline({ result }: { result: AgentResult }) {
  const toggleInspector = useUIStore((s) => s.toggleInspector);
  const summaries = (result.metadata as any)?.source_summary || [];
  const isFailed = !result.ok;

  return (
    <div className="chat-result-inline">
      {(result.tool_calls ?? []).length > 0 && (
        <div className="chat-tool-calls">
          {result.tool_calls.map((tc: ToolCallResult) => (
            <span key={tc.call_id} className="chat-tool-call">
              <IconBolt size={10} style={{ color: "var(--accent)" }} />
              <span className="tc-name">{tc.tool_id}</span>
              <span className={"tc-status " + (tc.ok ? "ok" : "err")}>{tc.ok ? "ok" : "fail"}</span>
            </span>
          ))}
        </div>
      )}

      {!isFailed && (
        <div className="next-actions">
          <span className="next-action" onClick={toggleInspector}>查看运行详情</span>
          {Array.isArray(summaries) && summaries.length > 0 && (
            <span className="next-action">知识源 ({summaries.length})</span>
          )}
        </div>
      )}

      {isFailed && result.errors?.length > 0 && (
        <details className="mt-2">
          <summary className="wb-run-detail">技术详情</summary>
          <div className="text-xs mono mt-1" style={{ color: "var(--ink-mute)", whiteSpace: "pre-wrap" }}>
            {result.errors.join("\n")}
          </div>
        </details>
      )}
    </div>
  );
}

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m${(seconds % 60).toString().padStart(2, "0")}s`;
}
