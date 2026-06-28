import React, { useState, useRef, useEffect, useCallback } from "react";
import { agentApi, knowledgeApi, memoryApi, sessionsApi, settingsApi, sseApi } from "../../api";
import { apiRequest } from "../../api/client";
import { useSessionStore } from "../../stores/session";
import { useWorkbenchStore } from "../../stores/workbench";
import { useToastStore } from "../../stores/toast";
import { isApiError } from "../../types";
import type { AgentResult, ToolCallResult, InlineToolCall } from "../../types";
import { sanitizeAssistantText, renderAssistantHtml, toolLabel, filterStreamingThink } from "../../utils/displayText";
import { beginModelStep, discardToolCallDraft, finalizeStreamText } from "../../utils/agentStream";
import "./WorkbenchHighlight";
import hljs from "highlight.js/lib/core";
import { agentResultFromWsDone } from "../../utils/wsResult";
import { notifyRunCompleted } from "../../utils/appEvents";
import { IconAlert, IconBolt, IconSend } from "../../components/Icon";
import { ApprovalBubble } from "../../components/ApprovalBubble";
import { RuntimeEventTimeline } from "../../components/RuntimeEventTimeline";
import "../../components/RuntimeEventTimeline.css";
import { formatFileSize } from "../../utils/format";
import { QUICK_CHIPS } from "./WorkbenchQuickChips";

/* ── v3.9 View mode ── */
type ViewMode = "chat" | "timeline";

/** Enhanced error classification with recovery hints.
 *  Now uses error_type from AgentResult for precise messaging. */
function _humanFailure(errorType: string | undefined, errorText: string): { msg: string; retryable: boolean } {
  const et = (errorType ?? "").toLowerCase();
  const text = (errorText ?? "").toLowerCase();
  // Provider errors
  if (et.includes("provider_timeout") || text.includes("timed out") || text.includes("超时"))
    return { msg: "模型请求超时，可能是供应商响应慢或网络抖动。可重试或缩短问题。", retryable: true };
  if (et.includes("provider_error") || text.includes("provider"))
    return { msg: "模型服务异常，请稍后重试。", retryable: true };
  // Auth/permission
  if (text.includes("disabled") || text.includes("llm is disabled"))
    return { msg: "LLM 未启用，请前往系统设置开启并配置 API Key。", retryable: false };
  if (text.includes("api_key") || text.includes("authentication"))
    return { msg: "API 密钥未配置或已失效，请重新设置。", retryable: false };
  // Tool sandbox
  if (text.includes("forbidden function") || text.includes("forbidden_import"))
    return { msg: "Agent 尝试使用被限制的操作，系统自动拦截。可重新提问让 Agent 换一种方式。", retryable: true };
  if (text.includes("syntax error") || text.includes("unterminated"))
    return { msg: "Agent 生成的代码有语法错误，重新生成通常可解决。", retryable: true };
  // Caller identity
  if (text.includes("caller_identity") || text.includes("requested_by"))
    return { msg: "系统调用链身份缺失，请刷新页面后重试。", retryable: false };
  // Default
  return { msg: text, retryable: true };
}

export function TaskWorkbench() {
  const { currentWorkspaceId, currentSessionId } = useSessionStore();
  const sending = useWorkbenchStore((s) => s.sending);
  const lastUserInput = useWorkbenchStore((s) => s.lastUserInput);
  const results = useWorkbenchStore((s) => s.results);
  const sessionResults = results[currentSessionId ?? "_scratch"] ?? [];
  // Granular selector: only re-render when THIS session's messages change
  const visibleHistory = useWorkbenchStore((s) => {
    const msgs = s.bySession?.[currentSessionId ?? "_scratch"];
    return Array.isArray(msgs) ? msgs : [];
  });
  const appendUser = useWorkbenchStore((s) => s.appendUser);
  const appendAssistantStreaming = useWorkbenchStore((s) => s.appendAssistantStreaming);
  const updateAssistant = useWorkbenchStore((s) => s.updateAssistant);
  const setSending = useWorkbenchStore((s) => s.setSending);
  const switchSession = useWorkbenchStore((s) => s.switchSession);
  const mergeFromBackend = useWorkbenchStore((s) => s.mergeFromBackend);
  const setLatestResult = useWorkbenchStore((s) => s.setLatestResult);

  const [viewMode, setViewMode] = useState<ViewMode>("chat");
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<Array<{ id: string; name: string; size: string; file: File; uploading?: boolean }>>([]);

  // ── Scroll architecture (v4.1) ──
  // A plain scroll container is enough for the capped chat history and avoids
  // virtual-list measurement jumps while an assistant answer is streaming.
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  const userScrolledUpRef = useRef(false);    // true = user intentionally scrolled up
  const atBottomRef = useRef(true);
  const sendingRef = useRef(false);

  const chatRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    sendingRef.current = sending;
  }, [sending]);

  const handleChatScroll = useCallback(() => {
    const el = chatRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 32;
    atBottomRef.current = atBottom;
    setShowScrollBtn(!atBottom);
    if (!atBottom && !sendingRef.current) userScrolledUpRef.current = true;
    if (atBottom) userScrolledUpRef.current = false;
  }, []);

  const keepAtBottom = useCallback(() => {
    if (!userScrolledUpRef.current) {
      requestAnimationFrame(() => {
        const el = chatRef.current;
        if (!el) return;
        el.scrollTop = el.scrollHeight;
        atBottomRef.current = true;
        setShowScrollBtn(false);
      });
    }
  }, []);

  const handleScrollBtnClick = useCallback(() => {
    userScrolledUpRef.current = false;
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: "smooth" });
    atBottomRef.current = true;
    setShowScrollBtn(false);
  }, []);

  const thinkFilter = useRef<{ mode: import("../../utils/displayText").ThinkFilterState }>({ mode: "idle" });
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [llmHealth, setLlmHealth] = useState<{ connected: boolean; provider?: string; model?: string; recentFailure?: string }>({ connected: false });
  const toast = useToastStore((s) => s.show);
  const abortRef = useRef<AbortController | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Stop generation: abort active request + close WebSocket
  const stopGeneration = useCallback(() => {
    if (abortRef.current) { abortRef.current.abort(); abortRef.current = null; }
    if (wsRef.current) { try { wsRef.current.close(); } catch {} wsRef.current = null; }
    setSending(false);
  }, []);  // eslint-disable-line

  // Preserve current session id ref for cleanup
  const prevSessionId = useRef(currentSessionId);
  useEffect(() => { prevSessionId.current = currentSessionId; });

  // Clean up abort controller on unmount
  useEffect(() => () => { abortRef.current?.abort(); }, []);

  // LLM health poll
  useEffect(() => {
    const poll = () => {
      settingsApi.llmStatus().then((s) => {
        if (!s) return;
        setLlmHealth({
          connected: s.connected, provider: s.provider || s.provider_type || "",
          model: s.model || "", recentFailure: s.recent_failure?.error_type ? s.recent_failure.error_summary : undefined,
        });
      }).catch(() => {});
    };
    poll();
    const id = window.setInterval(poll, 30_000);
    return () => window.clearInterval(id);
  }, []);

  // Input draft persistence: save to localStorage debounced, restore on mount
  const draftKey = `draft-${currentSessionId ?? "_scratch"}`;
  useEffect(() => {
    const saved = typeof localStorage !== "undefined" ? localStorage.getItem(draftKey) : null;
    if (saved) setInput(saved);
  }, [currentSessionId]);  // eslint-disable-line

  const handleInputChange = useCallback((val: string) => {
    setInput(val);
    if (typeof localStorage !== "undefined") localStorage.setItem(draftKey, val);
  }, [draftKey]);

  // Clear draft after successful send
  const clearDraft = useCallback(() => {
    if (typeof localStorage !== "undefined") localStorage.removeItem(draftKey);
  }, [draftKey]);

  // Auto-grow input
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 140) + "px";
  }, [input]);

  // Pick up pcap analysis prompt from sessionStorage (set by PacketAnalysis "Ask AI")
  useEffect(() => {
    const prompt = sessionStorage.getItem("pcap_ai_prompt");
    if (prompt && currentWorkspaceId) {
      sessionStorage.removeItem("pcap_ai_prompt");
      setInput(prompt);
      // Auto-send after a short delay to let UI settle
      const t = setTimeout(() => onSend(prompt), 500);
      return () => clearTimeout(t);
    }
  }, [currentWorkspaceId]);

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

  // Retry: resend last user input (used by error inline retry and regenerate)
  const retryLast = useCallback(() => {
    if (lastUserInput && !sending) onSend(lastUserInput);
  }, [lastUserInput, sending]);  // eslint-disable-line

  // v3.9: SSE real-time timeline updates
  useEffect(() => {
    if (!currentSessionId || !currentWorkspaceId || typeof EventSource === "undefined") return;
    const es = sseApi.connect(currentSessionId, currentWorkspaceId);
    const refreshMessages = () => {
      sessionsApi.messages(currentSessionId, currentWorkspaceId)
        .then((res) => { if (res.messages?.length) mergeFromBackend(currentSessionId, res.messages); })
        .catch(() => {});
    };
    es.addEventListener("turn_completed", refreshMessages);
    es.onerror = () => { es.close(); };
    return () => {
      es.removeEventListener("turn_completed", refreshMessages);
      es.close();
    };
  }, [currentSessionId, currentWorkspaceId]);

  async function onSend(textOverride?: string) {
    const hasAttachments = attachments.length > 0;
    const raw = typeof textOverride === "string" ? textOverride : input;
    const text = raw.trim();
    if ((!text && !hasAttachments) || sending) return;
    if (!currentWorkspaceId) {
      toast({ kind: "warning", title: "未选择工作区", body: "请在左侧选择一个工作区" });
      return;
    }

    setInput("");
    clearDraft();
    let fullText = text;

    if (hasAttachments) {
      setAttachments((prev) => prev.map((a) => ({ ...a, uploading: true })));
      const results: string[] = [];
      const fileRefs: string[] = [];
      for (const a of attachments) {
        try {
          const form = new FormData();
          form.append("file", a.file);
          form.append("artifact_type", "general");
          form.append("title", a.name);
          form.append("workspace_id", currentWorkspaceId);
          const res = await apiRequest<{ ok: boolean; file: { file_id: string; path?: string; logical_type?: string }; artifact?: unknown; warnings?: string[] }>({
            method: "POST", url: `/workspaces/${currentWorkspaceId}/artifacts/upload`, data: form,
          });
          const fid = res.ok ? res.file?.file_id : "";
          if (fid) {
            results.push(a.name);
            fileRefs.push(`file_id=${fid}`);
          } else {
            results.push(`${a.name}(失败)`);
          }
        } catch { results.push(`${a.name}(失败)`); }
      }
      setAttachments([]);
      if (results.length > 0) {
        let uploadNote = `\n[已上传文件: ${results.join("、")}]`;
        if (fileRefs.length > 0) {
          uploadNote += `\n[文件路径: ${fileRefs.join("; ")}]`;
        }
        fullText = text ? text + uploadNote : uploadNote;
      }
    }

    const scratch = currentSessionId ?? "_scratch";
    appendUser(fullText, scratch);
    const streamingMsgId = appendAssistantStreaming(scratch);
    userScrolledUpRef.current = false; // reset scroll state when sending a new message
    setSending(true);
    // Force initial scroll to bottom so user sees the streaming bubble appear
    requestAnimationFrame(() => keepAtBottom());

    // Try WebSocket streaming first, fall back to HTTP
    // Dev: proxied through Vite (port 5173). Prod: same-origin.
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsHost = window.location.host; // Includes port (5173 in dev, 8010 in prod)
    const wsUrl = `${protocol}//${wsHost}/ws/agent`;
    let ws: WebSocket | null = null;
    abortRef.current = new AbortController();

    try {
      ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      // Track streaming state
      let streamedText = "";
      let streamState = beginModelStep();
      thinkFilter.current = { mode: "idle" };
      let resolvedSid: string = currentSessionId || "";
      const wsReady: Promise<void> = new Promise((resolve, reject) => {
        const timer = setTimeout(() => { reject(new Error("ws_timeout")); }, 3000);
        ws!.onopen = () => { clearTimeout(timer); resolve(); };
        ws!.onerror = () => { clearTimeout(timer); reject(new Error("ws_error")); };
      });
      await wsReady;

      // Send message
      ws.send(JSON.stringify({
        type: "message",
        user_input: fullText,
        session_id: currentSessionId,
        workspace_id: currentWorkspaceId,
        metadata: {},
      }));

      // Receive streaming events
      const streamingResult: {
        session_id?: string;
        turn_id?: string;
        trace_id?: string;
        events?: AgentResult["events"];
        tool_calls_count?: number;
        tool_calls?: ToolCallResult[];
        metadata?: Record<string, unknown>;
        errors?: string[];
        warnings?: string[];
        tool_decision?: AgentResult["tool_decision"];
        no_tool_reason?: string;
      } = {};

      await new Promise<void>((resolve) => {
        ws!.onmessage = (event) => {
          try {
            const msg = JSON.parse(event.data);
            switch (msg.type) {
              case "token":
                // Real-time token display with think-block filtering
                const raw = msg.content || "";
                const visible = filterStreamingThink(raw, thinkFilter.current);
                streamState.draft += visible;
                streamedText = streamState.draft;
                useWorkbenchStore.getState().updateAssistant(streamingMsgId, { text: streamedText }, scratch);
                // Stream tokens don't change item count, so manually keep at bottom
                keepAtBottom();
                break;
              case "event":
                if (msg.data) {
                  streamingResult.events = [...(streamingResult.events || []), msg.data];
                }
                if (msg.name === "model_started") {
                  streamState = beginModelStep(streamedText);
                  streamedText = "";
                  useWorkbenchStore.getState().updateAssistant(streamingMsgId, { text: "" }, scratch);
                }
                if (msg.name === "tool_call" || msg.name === "tool_result") {
                  streamingResult.tool_calls_count = (streamingResult.tool_calls_count || 0) + 1;
                  const tid = msg.data?.tool_id || msg.data?.name || "";
                  if (tid) {
                    // Update live tool calls directly on the streaming message
                    const store = useWorkbenchStore.getState();
                    const curr = store.bySession[scratch]?.find((m) => m.id === streamingMsgId);
                    const prevCalls = (curr?.toolCalls || []) as any[];
                    if (msg.name === "tool_result") {
                      const ok = msg.data?.ok ?? msg.data?.status === "ok";
                      const nextCalls = prevCalls.map((t: any) =>
                        t.tool_id === tid ? { ...t, status: ok ? "done" : "fail", ok, summary: msg.data?.summary } : t
                      );
                      store.updateAssistant(streamingMsgId, { toolCalls: nextCalls }, scratch);
                    } else {
                      if (!prevCalls.find((t: any) => t.tool_id === tid)) {
                        store.updateAssistant(streamingMsgId, {
                          toolCalls: [...prevCalls, { tool_id: tid, tool_name: toolLabel(tid), status: "running" }],
                        }, scratch);
                      }
                    }
                  }
                }
                if (msg.name === "tool_call") {
                  discardToolCallDraft(streamState);
                  streamedText = "";
                  useWorkbenchStore.getState().updateAssistant(streamingMsgId, { text: "" }, scratch);
                }
                // Keep scrolled to bottom after any event that changes content height
                keepAtBottom();
                break;
              case "done":
                resolvedSid = msg.session_id || currentSessionId;
                streamedText = finalizeStreamText(streamState.draft, msg.final_response || "");
                streamingResult.session_id = msg.session_id;
                streamingResult.turn_id = msg.turn_id;
                streamingResult.trace_id = msg.trace_id;
                streamingResult.events = msg.events || streamingResult.events || [];
                streamingResult.tool_calls_count = msg.tool_calls_count || streamingResult.tool_calls_count;
                streamingResult.tool_calls = msg.tool_calls || [];
                streamingResult.metadata = msg.metadata || {};
                streamingResult.errors = msg.errors || [];
                streamingResult.warnings = msg.warnings || [];
                streamingResult.tool_decision = msg.tool_decision;
                streamingResult.no_tool_reason = msg.no_tool_reason;
                resolve();
                break;
              case "error":
                streamingResult.errors = [msg.message || msg.error || "Unknown error"];
                resolve();
                break;
            }
          } catch { /* ignore parse errors */ }
        };

        ws!.onclose = () => resolve();
        ws!.onerror = () => resolve();
      });

      try { ws.close(); } catch { /* already closed */ }
      ws = null;
      wsRef.current = null;

      // Phase 1: migrate _scratch → real session (identity-only, no content dedup).
      // existing is always [] here — resolvedSid is a brand-new session ID.
      // Deduplication is deferred to mergeFromBackend (Phase 2 below), which
      // handles it correctly via message_id / run_id matching.
      if (!currentSessionId && resolvedSid) {
        useSessionStore.getState().setCurrentSession(resolvedSid);
        useWorkbenchStore.setState((prev) => {
          const scratchMsgs = prev.bySession["_scratch"] ?? [];
          const existing = prev.bySession[resolvedSid] ?? [];
          return { bySession: { ...prev.bySession, [resolvedSid]: [...existing, ...scratchMsgs], _scratch: [] } };
        });
        useWorkbenchStore.getState().switchSession(resolvedSid);
      }

      const wsResult = agentResultFromWsDone(streamingResult, streamedText, resolvedSid);
      // Finalize the optimistic streaming message
      const cleanText = sanitizeAssistantText(wsResult.final_response);
      const cleanResult = { ...wsResult, final_response: sanitizeAssistantText(wsResult.final_response ?? "") };
      const toolCalls: InlineToolCall[] = (cleanResult.tool_calls ?? []).map((tc) => ({
        tool_id: tc.tool_id,
        tool_name: toolLabel(tc.tool_id),
        ok: tc.ok,
        summary: tc.summary,
        duration_ms: tc.duration_ms ?? undefined,
        errors: tc.errors,
        artifacts: tc.artifacts as InlineToolCall["artifacts"],
      }));
      updateAssistant(streamingMsgId, {
        status: wsResult.errors?.length ? "error" : "ready",
        text: cleanText,
        result: cleanResult,
        toolCalls: toolCalls.length > 0 ? toolCalls : undefined,
        error: wsResult.errors?.[0],
        trace_id: wsResult.trace_id,
        run_id: wsResult.turn_id,
      }, resolvedSid);
      setLatestResult(wsResult);
      notifyRunCompleted();
      keepAtBottom();

      if (resolvedSid && currentWorkspaceId) {
        sessionsApi.messages(resolvedSid, currentWorkspaceId)
          .then((r) => { if (r.messages?.length) mergeFromBackend(resolvedSid, r.messages); })
          .catch(() => {});
      }

    } catch {
      // WebSocket failed, fall back to HTTP
      if (ws) { try { ws.close(); } catch {} }
      try {
        const res = await agentApi.run({ message: fullText, workspace_id: currentWorkspaceId, session_id: currentSessionId });
        const resolvedSid = (res.session_id && res.session_id !== "—" ? res.session_id : currentSessionId) ?? undefined;
        if (!currentSessionId && resolvedSid) {
          useSessionStore.getState().setCurrentSession(resolvedSid);
          useWorkbenchStore.setState((prev) => {
            const scratchMsgs = prev.bySession["_scratch"] ?? [];
            const existing = prev.bySession[resolvedSid] ?? [];
            return { bySession: { ...prev.bySession, [resolvedSid]: [...existing, ...scratchMsgs], _scratch: [] } };
          });
          useWorkbenchStore.getState().switchSession(resolvedSid);
        }
        const tcArray = (res.tool_calls ?? []).map((tc: ToolCallResult) => ({
          tool_id: tc.tool_id, tool_name: toolLabel(tc.tool_id), ok: tc.ok,
          summary: tc.summary, duration_ms: tc.duration_ms ?? undefined,
          errors: tc.errors, artifacts: tc.artifacts as any,
        }));
        updateAssistant(streamingMsgId, {
          status: res.ok ? "ready" : "error",
          text: sanitizeAssistantText(res.final_response ?? ""),
          result: res,
          toolCalls: tcArray.length > 0 ? tcArray : undefined,
          error: !res.ok ? res.errors?.[0] : undefined,
          trace_id: res.trace_id,
          run_id: res.turn_id,
        }, resolvedSid);
        setLatestResult(res);
        notifyRunCompleted();
        keepAtBottom();
        if (res.ok) {
          toast({ kind: "success", title: "回答完成", body: "可切换到时间线视图查看执行详情" });
        } else {
          toast({ kind: "error", title: "请求失败", body: _humanFailure(res.error_type ?? "", res.errors?.[0] ?? "").msg });
        }
        if (resolvedSid && currentWorkspaceId) {
          sessionsApi.messages(resolvedSid, currentWorkspaceId)
            .then((r) => { if (r.messages?.length) mergeFromBackend(resolvedSid, r.messages); })
            .catch(() => { /* 背景同步为 best-effort，静默失败 */ });
        }
      } catch (err: unknown) {
        const msg = isApiError(err) ? err.message : String(err);
        const fallbackSid = currentSessionId ?? "_scratch";
        const stubResult: AgentResult = {
          ok: false, final_response: sanitizeAssistantText(`(error) ${msg}`),
          events: [], trace_id: isApiError(err) ? err.request_id ?? "—" : "—",
          session_id: fallbackSid ?? "—", turn_id: `turn-${Date.now()}`,
          tool_calls: [], warnings: [], errors: [msg], error_type: "network",
          metadata: { source_count: 0, source_summary: [] },
        };
        updateAssistant(streamingMsgId, {
          status: "error",
          text: stubResult.final_response,
          result: stubResult,
          error: msg,
        }, fallbackSid);
        setLatestResult(stubResult);
        toast({ kind: "error", title: "请求失败", body: msg });
      }
    } finally {
      wsRef.current = null;
      setSending(false);
    }
  }

  function pickChip(prompt: string) {
    setInput(prompt);
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  // ── File upload ──

  function addFiles(files: FileList | File[]) {
    const list = Array.from(files).filter((f) => f.size < 50 * 1024 * 1024);
    if (list.length < (files as any).length) toast({ kind: "warning", title: "部分文件跳过", body: "单文件不能超过 50 MB" });
    setAttachments((prev) => [
      ...prev,
      ...list.map((f) => ({ id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, name: f.name, size: formatFileSize(f.size), file: f })),
    ]);
  }

  function removeAttachment(id: string) {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }

  function pickFile() {
    fileInputRef.current?.click();
  }

  // Drag-drop handler
  const handleDragOver = useCallback((e: React.DragEvent) => { e.preventDefault(); }, []);
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
  }, []);

  // Paste handler — capture images from clipboard
  useEffect(() => {
    const handler = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      const files: File[] = [];
      for (let i = 0; i < items.length; i++) {
        const f = items[i].getAsFile();
        if (f && f.type.startsWith("image/")) files.push(f);
      }
      if (files.length) addFiles(files);
    };
    window.addEventListener("paste", handler);
    return () => window.removeEventListener("paste", handler);
  }, []);

  const llmStatusLabel = llmHealth.connected
    ? llmHealth.recentFailure ? "LLM 可用 · 最近一次请求超时，可重试" : `LLM 可用 · ${llmHealth.model || llmHealth.provider || "在线"}`
    : "LLM 离线";

  useEffect(() => {
    keepAtBottom();
  }, [
    keepAtBottom,
    sending,
    visibleHistory.length,
    visibleHistory[visibleHistory.length - 1]?.text,
    visibleHistory[visibleHistory.length - 1]?.status,
  ]);

  // Message row renderer for the chat list
  const renderMsg = useCallback((m: any, idx: number, total: number) => {
    if (m.role === "user") {
      return (
        <div className="message-row user" data-testid="chat-user">
          <div className="message-stack"><div className="chat-bubble user">{m.text}</div></div>
          <div className="message-avatar user">我</div>
        </div>
      );
    }
    return (
      <div className={`message-row assistant${m.status === "error" ? " error" : ""}${m.status === "streaming" ? " streaming" : ""}`} data-testid="chat-assistant">
        <div className="message-avatar agent">网</div>
        <div className="message-stack">
          {/* Live tool call chips during streaming */}
          {m.status === "streaming" && m.toolCalls && m.toolCalls.length > 0 && (
            <div className="tool-calls-inline">
              {m.toolCalls.map((tc: any, tci: number) => (
                <span key={`${tc.tool_id}-${tci}`} className={`live-tool-chip ${tc.status || "running"}`}>
                  <span className={`live-tool-dot ${tc.status || "running"}`} />
                  {tc.tool_name || toolLabel(tc.tool_id)}
                  {tc.summary && <span className="live-tool-summary">{tc.summary.slice(0, 40)}</span>}
                </span>
              ))}
            </div>
          )}
          {/* Completed tool call cards */}
          {m.status !== "streaming" && m.toolCalls && m.toolCalls.length > 0 && (
            <div className="tool-calls-inline">
              {m.toolCalls.map((tc: any, tci: number) => (
                <InlineToolCallCard key={`${tc.tool_id}-${tci}`} toolCall={tc} seq={tci + 1} />
              ))}
            </div>
          )}
          {m.status === "streaming" ? (
            <div className="chat-bubble assistant sending-line">
              {m.text ? (
                <StreamingContent text={m.text} />
              ) : (
                <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <span className="typing-indicator"><span className="typing-dot" /><span className="typing-dot" /><span className="typing-dot" /></span>
                  <span className="text-sm muted" style={{ marginLeft: 6 }}>思考中…</span>
                </div>
              )}
            </div>
          ) : (
            <>
              {(() => {
                const { thinking, body } = parseThinking(m.text);
                const html = body ? renderAssistantHtml(body) : "";
                return (<>
                  {thinking && <ThinkingBlock content={thinking} />}
                  {html ? (
                    <div className="chat-bubble assistant markdown-body" onClick={handleCodeCopyClick} dangerouslySetInnerHTML={{ __html: highlightCode(html) }} />
                  ) : (!m.text) ? (
                    <span className="muted">(空消息)</span>
                  ) : null}
                </>);
              })()}
              <ResultInline result={m.result} fallbackText={sanitizeAssistantText(m.text)} />
            </>
          )}
          {m.status === "error" && m.error && (
            <div className="msg-error-box">
              <span>⚠️ {_humanFailure(m.result?.error_type, m.error ?? "").msg}</span>
              {_humanFailure(m.result?.error_type, m.error ?? "").retryable && (
                <button onClick={retryLast}>🔄 重试</button>
              )}
            </div>
          )}
          {!sending && idx === total - 1 && lastUserInput && (
            <button className="regenerate-btn" onClick={() => onSend(lastUserInput)} title="重新生成" type="button">🔄 重新生成</button>
          )}
        </div>
      </div>
    );
  }, [sending, lastUserInput, retryLast, handleCodeCopyClick]);  // eslint-disable-line

  return (
    <div className="wb-shell">
      {/* ── Header bar ── */}
      <div className="wb-header">
        <div className="wb-header-status">
          <span className={"dot " + (llmHealth.connected ? (llmHealth.recentFailure ? "warn" : "ok") : "err")} />
          <span>{llmStatusLabel}</span>
        </div>
        {/* v3.9: Export session as Markdown */}
        {currentSessionId && visibleHistory && visibleHistory.length > 0 && (
          <button className="wb-export-btn" title="导出对话" onClick={() => {
            const md = visibleHistory.map((m) =>
              `## ${m.role === "user" ? "🙋 用户" : "🤖 AI"}\n\n${m.text}\n\n---\n`
            ).join("\n");
            const blob = new Blob([md], { type: "text/markdown" });
            const a = document.createElement("a");
            a.href = URL.createObjectURL(blob);
            a.download = `session-${currentSessionId.slice(0, 8)}-${new Date().toISOString().slice(0, 10)}.md`;
            a.click();
          }}>📥 导出</button>
        )}
      </div>

      {/* ── View mode toggle ── */}
      <div className="wb-view-tabs">
        <button
          type="button"
          className={`wb-view-tab ${viewMode === "chat" ? "active" : ""}`}
          onClick={() => setViewMode("chat")}
          data-testid="view-chat"
        >
          💬 对话
        </button>
        <button
          type="button"
          className={`wb-view-tab ${viewMode === "timeline" ? "active" : ""}`}
          onClick={() => setViewMode("timeline")}
          data-testid="view-timeline"
        >
          📋 时间线
        </button>
      </div>

      {/* ── Content area ── */}
      <div className="wb-chat" data-testid="chat-stream">
        {viewMode === "timeline" ? (
          <RuntimeEventTimeline results={sessionResults} />
        ) : (visibleHistory?.length ?? 0) === 0 && !sending ? (
          <div className="wb-empty" data-testid="workbench-empty">
            <h2>任务工作台</h2>
            <p>输入故障现象、配置片段或排查目标，AI Agent 按事件时间线组织执行过程。</p>
            <div className="wb-empty-chips">
              {QUICK_CHIPS.map((c) => (
                <button key={c.label} className="wb-input-chip" type="button" onClick={() => pickChip(c.prompt)} title={c.prompt}>
                  {c.label}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div
            ref={chatRef}
            className="wb-chat-list"
            role="log"
            aria-live={sending ? "polite" : "off"}
            onScroll={handleChatScroll}
          >
            {(visibleHistory ?? []).map((m, idx) => (
              <React.Fragment key={m.message_id || m.run_id || m.id}>
                {renderMsg(m, idx, (visibleHistory ?? []).length)}
              </React.Fragment>
            ))}
          </div>
        )}

        {/* ── Scroll-to-bottom floating bubble ── */}
        {showScrollBtn && (
          <button className="scroll-bottom-btn" onClick={handleScrollBtnClick} title="回到底部" type="button">
            <svg width="14" height="14" viewBox="0 0 16 16"><path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </button>
        )}
      </div>

      {/* ── Retry bar ── */}
      {!sending && sessionResults.length > 0 && !sessionResults[sessionResults.length - 1].ok && lastUserInput && (
        <div className="wb-retry-bar">
          <IconAlert size={11} />
          <span>{_humanFailure(sessionResults[sessionResults.length - 1].error_type, sessionResults[sessionResults.length - 1].errors?.[0] ?? "请求失败").msg}</span>
          {_humanFailure(sessionResults[sessionResults.length - 1].error_type, sessionResults[sessionResults.length - 1].errors?.[0] ?? "").retryable && (
            <button type="button" onClick={() => onSend(lastUserInput)} data-testid="retry-btn">
              自动重试
            </button>
          )}
        </div>
      )}

      {/* ── Input bar ── */}
      <div className="wb-input-bar" onDragOver={handleDragOver} onDrop={handleDrop}>
        {attachments.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 7 }}>
            {attachments.map((a) => (
              <span key={a.id} className="tag" style={{ gap: 4, fontSize: "var(--fs-11)" }}>
                {a.uploading ? <span className="spinner" style={{ width: 10, height: 10, borderWidth: 1 }} /> : "📄"}
                <span style={{ maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name}</span>
                <button onClick={() => removeAttachment(a.id)} style={{ cursor: "pointer", marginLeft: 1, color: "var(--text-4)", fontSize: 13, lineHeight: 1, background: "none", border: "none", padding: 0 }} type="button">&times;</button>
              </span>
            ))}
          </div>
        )}
        <div className="wb-input-row">
          <input ref={fileInputRef} type="file" multiple accept=".txt,.pdf,.md,.json,.csv,.log,.conf,.cfg,.yaml,.yml,.png,.jpg,.jpeg,.gif,.webp" onChange={(e) => { if (e.target.files) { addFiles(e.target.files); e.target.value = ""; } }} style={{ display: "none" }} />
          <button className="wb-attach-btn" onClick={pickFile} disabled={sending} title="上传文件 (Ctrl+V 粘贴图片 / 拖拽)" type="button">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M8.5 1.5v9M5 5l3.5-3.5L12 5M2.5 10v2.5a1 1 0 001 1h9a1 1 0 001-1V10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </button>
          <textarea
            ref={inputRef}
            className="wb-input"
            placeholder="输入主机名、IP 或排查目标… (Enter 发送, Shift+Enter 换行)"
            value={input}
            onChange={(e) => handleInputChange(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); onSend(); } }}
            disabled={sending}
            rows={1}
            data-testid="chat-input"
            spellCheck={false}
            style={{ fieldSizing: "content" }}
          />
          {sending ? (
            <button className="wb-stop" onClick={stopGeneration} title="停止生成" type="button" data-testid="btn-stop">
              <svg width="12" height="12" viewBox="0 0 12 12"><rect x="1" y="1" width="10" height="10" rx="2" fill="currentColor"/></svg>
            </button>
          ) : (
            <button
              className="wb-send"
              onClick={() => onSend()}
              disabled={!input.trim() && attachments.length === 0}
              data-testid="btn-send"
              type="button"
              aria-label="发送"
              title="Enter 发送"
            >
              <IconSend size={14} />
            </button>
          )}
        </div>
      </div>

      {/* ── Inline approval bubble for high-risk tools ── */}
      <ApprovalBubble />
    </div>
  );
}

/* ==============================================================
   Inline tool call card
   ============================================================== */

function InlineToolCallCard({ toolCall, seq }: { toolCall: InlineToolCall; seq: number }) {
  const [open, setOpen] = useState(false);
  const errText = toolCall.errors?.join(", ");
  return (
    <div className={`tool-call-card ${toolCall.ok ? "ok" : "fail"}`} onClick={() => setOpen(!open)}>
      <div className="tool-call-card-header">
        <span className="tc-seq">#{seq}</span>
        <span className="tc-icon">{toolCall.ok ? "✅" : "❌"}</span>
        <span className="tc-name">{toolCall.tool_name}</span>
        <span className="tc-chev">{open ? "▾" : "▸"}</span>
      </div>
      {open && (
        <div className="tool-call-card-body">
          {toolCall.summary && <div className="tc-summary">{toolCall.summary}</div>}
          {errText && <div className="tc-error">{errText}</div>}
          {toolCall.duration_ms != null && (
            <div className="tc-duration">{(toolCall.duration_ms / 1000).toFixed(1)}s</div>
          )}
          {toolCall.artifacts && toolCall.artifacts.length > 0 && (
            <div className="tc-artifacts">
              {toolCall.artifacts.map((a) => (
                <span key={a.artifact_id} className="tc-artifact-tag">📄 {a.title || a.artifact_id}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ==============================================================
   Helpers
   ============================================================== */

/** Parse <think>...</think> and <thinking>...</thinking> blocks from content */
function parseThinking(text: string): { thinking: string; body: string } {
  const pat = /<(?:think|thinking)>([\s\S]*?)<\/(?:think|thinking)>/i;
  const match = text.match(pat);
  if (match) {
    return { thinking: match[1].trim(), body: text.replace(match[0], "").trim() };
  }
  return { thinking: "", body: text };
}

/** Highlight code blocks in rendered HTML */
function highlightCode(html: string): string {
  return html.replace(/<pre><code class="language-(\w+)?">([\s\S]*?)<\/code><\/pre>/g, (_, lang, code) => {
    try {
      const decoded = new DOMParser().parseFromString(code, "text/html").body.textContent || "";
      const langClass = lang && hljs.getLanguage(lang) ? lang : "plaintext";
      const result = hljs.highlight(decoded, { language: langClass }).value;
      return `<div class="code-block-wrap"><div class="code-block-header"><span>${lang || "code"}</span><button class="code-copy-btn" type="button" data-code-copy="1">复制</button></div><pre><code class="hljs language-${langClass}">${result}</code></pre></div>`;
    } catch {
      return `<pre><code>${code}</code></pre>`;
    }
  });
}

function handleCodeCopyClick(event: React.MouseEvent<HTMLDivElement>) {
  const target = event.target as HTMLElement | null;
  const button = target?.closest("[data-code-copy]") as HTMLButtonElement | null;
  if (!button) return;
  const code = button.closest(".code-block-wrap")?.querySelector("code")?.textContent || "";
  void navigator.clipboard?.writeText(code);
  button.textContent = "已复制";
  window.setTimeout(() => {
    button.textContent = "复制";
  }, 2000);
}

/** Streaming content with live thinking block support */
function StreamingContent({ text }: { text: string }) {
  const { thinking, body } = parseThinking(text);
  return (
    <>
      {thinking && <ThinkingBlock content={thinking} defaultOpen />}
      {body && <span className="text-sm">{body}</span>}
      {!body && !thinking && <span className="text-sm">{text}</span>}
    </>
  );
}

/** Collapsible thinking/reasoning block */
function ThinkingBlock({ content, defaultOpen }: { content: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen ?? false);
  return (
    <div className="thinking-block">
      <div className={`thinking-header ${open ? "open" : ""}`} onClick={() => setOpen(!open)}>
        <span className="chev">▸</span>
        <span>💭 思考过程</span>
        <span style={{ fontSize: 9, color: "var(--text-4)", marginLeft: "auto" }}>点击{open ? "收起" : "展开"}</span>
      </div>
      {open && <div className="thinking-body">{content}</div>}
    </div>
  );
}

/* ==============================================================
   Sub-components
   ============================================================== */

const ResultInline = React.memo(function ResultInline({ result, fallbackText }: { result: AgentResult | undefined; fallbackText: string }) {
  const { currentWorkspaceId } = useSessionStore();
  const toast = useToastStore((s) => s.show);
  const [saving, setSaving] = useState<"" | "memory" | "knowledge">("");
  const summaries = ((result?.metadata as any)?.context_sources || (result?.metadata as any)?.source_summary || []) as any[];
  const isFailed = !result?.ok;
  const finalText = (result?.final_response || fallbackText || "").trim();

  // Nothing to show — no result and no fallback text
  if (!result && !fallbackText) return null;

  async function rememberAnswer() {
    if (!finalText) { toast({ kind: "warning", title: "无法保存", body: "当前回答内容为空" }); return; }
    if (!currentWorkspaceId) { toast({ kind: "warning", title: "未选择工作区", body: "请先在左侧选择工作区" }); return; }
    if (saving) return;
    setSaving("memory");
    try {
      const res = await memoryApi.create({
        workspace_id: currentWorkspaceId,
        title: finalText.slice(0, 42) || "本次结论",
        content: finalText,
        memory_type: "decision",
        tags: ["agent_answer", "confirmed"],
        user_confirmed: true,
      });
      // Also save to unified files for File Manager visibility
      try {
        const file = new File([finalText], `${finalText.slice(0, 30)}.txt`, { type: "text/plain" });
        const form = new FormData();
        form.append("file", file);
        form.append("artifact_type", "memory");
        form.append("title", finalText.slice(0, 42) || "本次结论");
        form.append("workspace_id", currentWorkspaceId);
        await apiRequest({ method: "POST", url: `/workspaces/${currentWorkspaceId}/artifacts/upload`, data: form });
      } catch {}
      if (res.conflict) {
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
    if (!finalText) { toast({ kind: "warning", title: "无法保存", body: "当前回答内容为空" }); return; }
    if (!currentWorkspaceId) { toast({ kind: "warning", title: "未选择工作区", body: "请先在左侧选择工作区" }); return; }
    if (saving) return;
    setSaving("knowledge");
    try {
      const title = `对话结论-${new Date().toISOString().slice(0, 10)}`;
      const body = `# ${title}\n\n${finalText}\n`;
      const file = new File([body], `${title}.md`, { type: "text/markdown" });
      await knowledgeApi.upload(currentWorkspaceId, file, {
        title,
        tags: "agent_answer,chat",
        source_type: "project_doc",
        scope: "workspace",
        language: "zh",
      });
      // Also save to unified files for File Manager visibility
      try {
        const form = new FormData();
        form.append("file", file);
        form.append("artifact_type", "knowledge");
        form.append("title", title);
        form.append("workspace_id", currentWorkspaceId);
        await apiRequest({ method: "POST", url: `/workspaces/${currentWorkspaceId}/artifacts/upload`, data: form });
      } catch {}
      toast({ kind: "success", title: "已保存到知识库", body: "这条回答已整理为可检索文档" });
    } catch (e: unknown) {
      toast({ kind: "error", title: "保存失败", body: isApiError(e) ? e.message : String(e) });
    } finally {
      setSaving("");
    }
  }

  return (
    <div className="chat-result-inline">
      {((result?.tool_calls) ?? []).length > 0 && (
        <div className="chat-tool-summary" data-testid="inline-tool-summary">
          <IconBolt size={10} className="inline-icon-accent" />
          <span>{toolCallSummary(result?.tool_calls ?? [])}</span>
          <details className="inline-technical-details">
            <summary>技术详情</summary>
            <div className="chat-tool-calls">
              {(result?.tool_calls ?? []).map((tc: ToolCallResult, idx: number) => (
                <span key={tc.call_id || `${tc.tool_id}-${idx}`} className="chat-tool-call">
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
              <span className="chat-source-chip" key={s.citation_id || s.chunk_id || s.source_id || i}>
                {s.citation_id ? `${s.citation_id} · ` : ""}
                {s.evidence_type === "memory" ? "记忆" : "知识"} · {s.title || s.source_id}
                <span className="score">{s.score != null ? ` ${Number(s.score).toFixed(2)}` : ""}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="result-actions">
          <button type="button" className="run-detail-button" onClick={() => void rememberAnswer()} disabled={!!saving}>
            {saving === "memory" ? "记录中…" : "记住结论"}
          </button>
          <button type="button" className="run-detail-button" onClick={() => void saveAsKnowledge()} disabled={!!saving}>
            {saving === "knowledge" ? "保存中…" : "存为知识"}
          </button>
          {Array.isArray(summaries) && summaries.length > 0 && (
            <span className="run-detail-info">来源 ({summaries.length})</span>
          )}
        </div>

      {isFailed && result?.errors && result.errors.length > 0 && (
        <details className="mt-2">
          <summary className="wb-run-detail">技术详情</summary>
          <div className="text-xs mono mt-1 technical-error">
            {(result?.errors ?? []).join("\n")}
          </div>
        </details>
      )}
    </div>
  );
});

function toolCallSummary(calls: ToolCallResult[]): string {
  const failed = calls.filter((tc) => !tc.ok).length;
  const recovered = calls.some((tc) => !tc.ok && calls.some((other) => other.ok && other.tool_id === tc.tool_id));
  const primary = calls.find((tc) => tc.ok) ?? calls[0];
  const label = primary ? toolLabel(primary.tool_id) : "工具调用";
  if (failed > 0 && recovered) return `${label}已完成，${failed} 次内部重试已自动恢复`;
  if (failed > 0) return `${label}需要关注，${failed} 次调用未完成`;
  return `${label}已完成`;
}
