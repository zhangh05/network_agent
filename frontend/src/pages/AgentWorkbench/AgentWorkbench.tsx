import { useState, useRef, useEffect } from "react";
import { agentApi, knowledgeApi, memoryApi, sessionsApi } from "../../api";
import { useSessionStore } from "../../stores/session";
import { useWorkbenchStore } from "../../stores/workbench";
import { useToastStore } from "../../stores/toast";
import { useUIStore } from "../../stores/session";
import { isApiError } from "../../types";
import type { AgentResult, ToolCallResult } from "../../types";
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
    appendUser, appendAssistant, setSending, switchSession, mergeFromBackend,
  } = useWorkbenchStore();

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
    <div className="wb-shell">
      {/* ── Header bar ── */}
      <div className="wb-header">
        <div className="wb-header-status">
          <span className={"dot " + (llmHealth.connected ? (llmHealth.recentFailure ? "warn" : "ok") : "err")} />
          <span>{llmStatusLabel}</span>
        </div>
      </div>

      {/* ── Chat area ── */}
      <div className="wb-chat" ref={chatRef} data-testid="chat-stream">
        {history.length === 0 && !sending ? (
          <div className="wb-empty" data-testid="workbench-empty">
            <h2>网络任务工作区</h2>
            <p>输入故障现象、配置片段或排查目标，系统会按会话记录、知识证据和工具结果组织输出。</p>
            <div className="wb-empty-chips">
              {QUICK_CHIPS.map((c) => (
                <button key={c} className="wb-input-chip" type="button" onClick={() => pickChip(c)}>
                  {c}
                </button>
              ))}
            </div>
          </div>
        ) : (
          history.map((m) =>
            m.role === "user" ? (
              <div key={m.id} className="message-row user" data-testid="chat-user">
                <div className="message-stack">
                  <div className="chat-bubble user">{m.text}</div>
                </div>
                <div className="message-avatar user">我</div>
              </div>
            ) : (
              <div key={m.id} className="message-row assistant" data-testid="chat-assistant">
                <div className="message-avatar agent">网</div>
                <div className="message-stack">
                  <div className="chat-bubble assistant">
                    {sanitizeAssistantText(m.text) || <span className="muted">(空消息)</span>}
                  </div>
                  {m.result && <ResultInline result={m.result} />}
                </div>
              </div>
            )
          )
        )}

        {sending && (
          <div className="message-row assistant" data-testid="chat-sending">
            <div className="message-avatar agent">网</div>
            <div className="message-stack">
              <div className="chat-bubble assistant sending-line">
                <span className="spinner" />
                <span className="text-sm muted">请求处理中…</span>
                <span className="text-xs faint sending-time">
                  {formatElapsed(elapsed)} / {formatElapsed(TIMEOUTS.agentTurn / 1000)}
                </span>
              </div>
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
            title="发送"
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
  const { currentWorkspaceId } = useSessionStore();
  const toast = useToastStore((s) => s.show);
  const [saving, setSaving] = useState<"" | "memory" | "knowledge">("");
  const summaries = ((result.metadata as any)?.context_sources || (result.metadata as any)?.source_summary || []) as any[];
  const isFailed = !result.ok;

  async function rememberAnswer() {
    if (!currentWorkspaceId || !result.final_response?.trim() || saving) return;
    setSaving("memory");
    try {
      const res = await memoryApi.confirm({
        title: result.final_response.slice(0, 42) || "本次结论",
        content: result.final_response,
        memory_type: "decision",
        tags: ["agent_answer", "confirmed"],
        project_id: currentWorkspaceId,
      });
      if (res.conflict_detected) {
        toast({ kind: "warning", title: "已记录，但发现冲突", body: "这条记忆和已有记忆可能不一致，请稍后在记忆列表核对。" });
      } else {
        toast({ kind: "success", title: "已记住", body: "后续对话会通过 RAG 召回这条结论" });
      }
    } catch (e: unknown) {
      toast({ kind: "error", title: "记忆失败", body: isApiError(e) ? e.message : String(e) });
    } finally {
      setSaving("");
    }
  }

  async function saveAsKnowledge() {
    if (!currentWorkspaceId || !result.final_response?.trim() || saving) return;
    setSaving("knowledge");
    try {
      const title = `对话结论-${new Date().toISOString().slice(0, 10)}`;
      const body = `# ${title}\n\n${result.final_response}\n`;
      const file = new File([body], `${title}.md`, { type: "text/markdown" });
      await knowledgeApi.upload(currentWorkspaceId, file, {
        title,
        tags: "agent_answer,chat",
        source_type: "project_doc",
        scope: "workspace",
        language: "zh",
      });
      toast({ kind: "success", title: "已保存到知识库", body: "这条回答已整理为可检索文档" });
    } catch (e: unknown) {
      toast({ kind: "error", title: "保存失败", body: isApiError(e) ? e.message : String(e) });
    } finally {
      setSaving("");
    }
  }

  return (
    <div className="chat-result-inline">
      {(result.tool_calls ?? []).length > 0 && (
        <div className="chat-tool-summary" data-testid="inline-tool-summary">
          <IconBolt size={10} className="inline-icon-accent" />
          <span>{toolCallSummary(result.tool_calls ?? [])}</span>
          <details className="inline-technical-details">
            <summary>技术详情</summary>
            <div className="chat-tool-calls">
              {result.tool_calls.map((tc: ToolCallResult) => (
                <span key={tc.call_id} className="chat-tool-call">
                  <span className="tc-name">{toolLabel(tc.tool_id)}</span>
                  <span className={"tc-status " + (tc.ok ? "ok" : "err")}>
                    {tc.ok ? "已完成" : "需关注"}
                  </span>
                </span>
              ))}
            </div>
          </details>
        </div>
      )}

      {Array.isArray(summaries) && summaries.length > 0 && (
        <div className="chat-source-summary" data-testid="inline-source-summary">
          <b>参考来源 · {summaries.length} 个</b>
          <div className="chat-source-list">
            {summaries.slice(0, 6).map((s: any, i: number) => (
              <span className="chat-source-chip" key={i}>
                {s.citation_id ? `${s.citation_id} · ` : ""}
                {s.evidence_type === "memory" ? "记忆" : "知识"} · {s.title || s.source_id}
                <span className="score">{s.score != null ? ` ${s.score.toFixed(2)}` : ""}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {!isFailed && (
        <div className="result-actions">
          <button type="button" className="run-detail-button" onClick={toggleInspector}>
            查看运行详情
          </button>
          <button type="button" className="run-detail-button" onClick={() => void rememberAnswer()} disabled={!!saving}>
            {saving === "memory" ? "记录中…" : "记住结论"}
          </button>
          <button type="button" className="run-detail-button" onClick={() => void saveAsKnowledge()} disabled={!!saving}>
            {saving === "knowledge" ? "保存中…" : "存为知识"}
          </button>
          {Array.isArray(summaries) && summaries.length > 0 && (
            <button type="button" className="run-detail-button" onClick={toggleInspector}>来源 ({summaries.length})</button>
          )}
        </div>
      )}

      {isFailed && result.errors?.length > 0 && (
        <details className="mt-2">
          <summary className="wb-run-detail">技术详情</summary>
          <div className="text-xs mono mt-1 technical-error">
            {result.errors.join("\n")}
          </div>
        </details>
      )}
    </div>
  );
}

function toolLabel(toolId: string): string {
  if (toolId.startsWith("config_translation.")) return "配置翻译";
  if (toolId.startsWith("knowledge.")) return "知识检索";
  if (toolId.startsWith("artifact.")) return "制品操作";
  if (toolId.startsWith("review.")) return "评审流转";
  if (toolId.startsWith("runtime.")) return "运行诊断";
  return "工具调用";
}

function toolCallSummary(calls: ToolCallResult[]): string {
  const failed = calls.filter((tc) => !tc.ok).length;
  const recovered = calls.some((tc) => !tc.ok && calls.some((other) => other.ok && other.tool_id === tc.tool_id));
  const primary = calls.find((tc) => tc.ok) ?? calls[0];
  const label = primary ? toolLabel(primary.tool_id) : "工具调用";
  if (failed > 0 && recovered) return `${label}已完成，${failed} 次内部重试已自动恢复`;
  if (failed > 0) return `${label}需要关注，${failed} 次调用未完成`;
  return `${label}已完成`;
}

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m${(seconds % 60).toString().padStart(2, "0")}s`;
}
