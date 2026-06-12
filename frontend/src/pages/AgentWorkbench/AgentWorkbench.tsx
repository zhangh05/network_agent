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
} from "../../components/Icon";

const SUGGESTIONS = [
  "翻译 Cisco BGP 配置为 Huawei 命令",
  "OSPF 邻居状态从 FULL 变为 INIT，可能的原因？",
  "如何为分支节点选择出口策略？",
  "把这条配置做翻译 + 静态风险扫描",
];

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
  const [llmHealth, setLlmHealth] = useState<{ connected: boolean; recentFailure?: string }>({ connected: false });
  // LLM health indicator — poll every 30s so users see recent_failure without
  // navigating to Settings. Only visual, never blocks interaction.
  useEffect(() => {
    const poll = () => {
      import("../../api").then(({ settingsApi }) => {
        settingsApi.llmStatus().then((s) => {
          if (!s) return;
          setLlmHealth({
            connected: s.connected,
            recentFailure: s.recent_failure?.error_type ? `近期失败: ${s.recent_failure.error_summary}` : undefined,
          });
        }).catch(() => {});
      });
    };
    poll();
    const id = window.setInterval(poll, 30_000);
    return () => window.clearInterval(id);
  }, []);
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

  async function onSend(textOverride?: string) {
    // textOverride is a string when called from retry; a MouseEvent when
    // called from onClick={onSend}. Normalize to text.
    const raw = typeof textOverride === "string" ? textOverride : input;
    const text = raw.trim();
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
      if (res.ok) {
        toast({ kind: "success", title: "回答完成", body: res.trace_id });
      } else {
        const friendly = _humanFailure(res.errors?.[0] ?? res.final_response ?? "");
        toast({ kind: "error", title: "请求失败", body: friendly, request_id: res.trace_id });
      }
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
            工作台{" "}
            <span style={{ color: "var(--ink-mute)", fontWeight: 400, fontSize: 14 }}>
              · Workbench
            </span>
          </h1>
          <div className="subtitle">
            面向网络工程任务的对话、运行和审计入口
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
          <span
            className="status-pill"
            data-testid="wb-llm-indicator"
            data-tip={llmHealth.recentFailure || (llmHealth.connected ? "LLM 已连接" : "LLM 未连接")}
          >
            <span
              className="dot"
              style={{
                background: llmHealth.recentFailure
                  ? "var(--warn)"
                  : llmHealth.connected
                    ? "var(--ok)"
                    : "var(--danger)",
              }}
            />
            <span>
              {llmHealth.connected
                ? llmHealth.recentFailure
                  ? "LLM 可用 · 最近一次请求超时，可重试"
                  : "LLM 可用"
                : "LLM 离线"}
            </span>
          </span>
        </div>
      </div>

      <div className="chat-shell">
        <div className="chat-stream" ref={streamRef} data-testid="chat-stream">
          <WorkbenchOverview
            llmConnected={llmHealth.connected}
            llmFailure={llmHealth.recentFailure}
            runtimeSummary={runtimeSummary}
            historyCount={history.length}
            sending={sending}
            onPickSuggestion={(s) => {
              setInput(s);
              inputRef.current?.focus();
            }}
          />
          {history.length === 0 ? (
            <div className="chat-empty">
              <div className="hello">
                从一个网络问题开始
              </div>
              <div className="sub">
                输入排障、配置翻译或知识检索需求，也可以点上方常用问题。
              </div>
              <div className="chat-suggestions">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    className="chat-suggestion"
                    type="button"
                    aria-label={`建议问题：${s}`}
                    onClick={() => {
                      setInput(s);
                      inputRef.current?.focus();
                    }}
                  >
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
              <div className="chat-avatar">网</div>
              <div className="chat-bubble" style={{ minWidth: 200 }}>
                <div className="row-flex" style={{ gap: 8, alignItems: "center" }}>
                  <span className="spinner" />
                  <span className="muted text-sm">请求处理中…</span>
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
                    本次请求较慢（包含模型响应、工具调用或检索），
                    最长可等 {formatElapsed(TIMEOUTS.agentTurn / 1000)}
                  </div>
                )}
              </div>
            </div>
          )}
          {!sending && latestResult && !latestResult.ok && lastUserInput && (
            <div className="card" style={{ padding: "8px 14px", display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
              <span className="text-sm" style={{ color: "var(--danger)" }}>上次请求失败</span>
              <button
                className="btn btn-sm btn-outline"
                onClick={() => { setInput(lastUserInput); void onSend(lastUserInput); }}
                data-testid="retry-btn"
              >
                自动重试
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
              onClick={() => void onSend()}
              disabled={sending || !input.trim()}
              data-testid="btn-send"
              type="button"
              aria-label="发送"
            >
              {sending ? <span className="spinner" /> : <IconSend size={14} />}
            </button>
          </div>
          <div className="chat-hint" data-testid="runtime-summary-hint">
            本地服务 · {runtimeSummary}
          </div>
        </div>
      </div>
    </div>
  );
}

function WorkbenchOverview({
  llmConnected,
  llmFailure,
  runtimeSummary,
  historyCount,
  sending,
  onPickSuggestion,
}: {
  llmConnected: boolean;
  llmFailure?: string;
  runtimeSummary: string;
  historyCount: number;
  sending: boolean;
  onPickSuggestion: (s: string) => void;
}) {
  const stats = parseRuntimeSummary(runtimeSummary);
  return (
    <section className="workbench-overview" aria-label="工作台概览">
      <div className="workbench-greeting">
        <div>
          <div className="eyebrow">工作台</div>
          <h2>近期处理</h2>
          <p>对话、工具调用和运行记录集中在这里，方便接着排查。</p>
        </div>
        <div className="workbench-status-card">
          <span className={"status-dot " + (sending ? "busy" : llmConnected ? "ok" : "err")} />
          <div>
            <strong>
              {llmConnected
                ? llmFailure
                  ? "LLM 可用 · 最近一次请求超时，可重试"
                  : "LLM 可用"
                : "LLM 离线"}
            </strong>
            <span>{sending ? "当前请求处理中" : "MiniMax-M3 · 服务在线"}</span>
          </div>
        </div>
      </div>

      <div className="ops-strip">
        <OverviewStat label="工具可见" value={stats.tools || "70 / 73"} />
        <OverviewStat label="能力已启用" value={stats.capabilities || "4 / 7"} />
        <OverviewStat label="规划中" value={stats.planned || "3"} />
        <OverviewStat label="本会话消息" value={String(historyCount)} />
      </div>

      <div className="recent-questions">
        <div className="section-head">最近问题</div>
        <div className="recent-question-list">
          {SUGGESTIONS.map((s, i) => (
            <button
              key={s}
              type="button"
              className="recent-question-row"
              onClick={() => onPickSuggestion(s)}
            >
              <span className={"question-state " + (i === 0 ? "ok" : i === 3 ? "warn" : "idle")} />
              <span className="question-title">{s}</span>
              <span className="question-meta">{i === 0 ? "常用" : "排查"}</span>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

function OverviewStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="overview-stat">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function parseRuntimeSummary(summary: string): {
  tools?: string;
  capabilities?: string;
  planned?: string;
} {
  const tools = summary.match(/工具\s+(\d+)\/(\d+)/);
  const capabilities = summary.match(/能力\s+(\d+)\/(\d+)/);
  const planned = summary.match(/规划中\s+(\d+)/);
  return {
    tools: tools ? `${tools[1]} / ${tools[2]}` : undefined,
    capabilities: capabilities ? `${capabilities[1]} / ${capabilities[2]}` : undefined,
    planned: planned?.[1],
  };
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
        {role === "user" ? "我" : "网"}
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

  const isFailed = !result.ok;
  const friendlyError = isFailed ? _humanFailure(result.errors?.[0] ?? "") : "";

  return (
    <div className="chat-result-inline" data-testid="result-inline" style={{ marginTop: 8 }}>
      {/* Failure explanation — human readable */}
      {isFailed && (
        <div
          className="chat-warnings"
          data-testid="inline-failure"
          style={{ background: "var(--danger-soft)", color: "var(--danger)", marginBottom: 6 }}
        >
          <IconAlert size={11} /> {friendlyError || "请求失败，请重试"}
        </div>
      )}

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

      {/* Next actions */}
      {result.ok && (
        <details className="collapse mt-2" open>
          <summary style={{ color: "var(--accent)", fontWeight: 500 }}>
            后续操作
          </summary>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
            <span className="status-pill" style={{ cursor: "pointer", opacity: 0.85 }}>
              继续追问
            </span>
            {summaries.length > 0 && (
              <span className="status-pill" style={{ cursor: "pointer", opacity: 0.85 }}>
                查看知识源 ({summaries.length})
              </span>
            )}
            <span className="status-pill" style={{ cursor: "pointer", opacity: 0.85 }}>
              查看本次运行审计
            </span>
          </div>
        </details>
      )}

      {isFailed && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
          <span className="status-pill" style={{ cursor: "pointer", opacity: 0.85 }}>
            缩短问题重试
          </span>
          <span className="status-pill" style={{ cursor: "pointer", opacity: 0.85 }}>
            检查 LLM 设置
          </span>
        </div>
      )}

      {/* Errors — diagnostics, collapsed by default */}
      {result.errors && result.errors.length > 0 && (
        <details className="collapse mt-2">
          <summary style={{ fontSize: 11, color: "var(--ink-mute)" }}>
            开发诊断 · {result.errors.length} 条 ({result.trace_id})
          </summary>
          <div className="text-xs mono" style={{ color: "var(--ink-mute)", whiteSpace: "pre-wrap", marginTop: 4 }}>
            {result.errors.join("\n")}
          </div>
        </details>
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
