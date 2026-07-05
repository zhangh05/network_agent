import React, { useState, useRef, useEffect, useCallback, memo } from "react";
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
import { TaskTrackingCard } from "../../components/TaskTrackingCard";

/* ── v3.9 View mode ── */
type ViewMode = "chat" | "timeline";

interface WorkbenchAutoPrompt {
  prompt?: string;
  metadata?: Record<string, unknown>;
}

/* ── safe storage wrappers ── */
function safeGetLocal(key: string): string | null {
  try { return typeof localStorage !== "undefined" ? localStorage.getItem(key) : null; } catch { return null; }
}
function safeSetLocal(key: string, val: string): void {
  try { if (typeof localStorage !== "undefined") localStorage.setItem(key, val); } catch { /* noop */ }
}
function safeRemoveLocal(key: string): void {
  try { if (typeof localStorage !== "undefined") safeRemoveLocal(key); } catch { /* noop */ }
}
function safeGetSession(key: string): string | null {
  try { return typeof sessionStorage !== "undefined" ? sessionStorage.getItem(key) : null; } catch { return null; }
}
function safeRemoveSession(key: string): void {
  try { if (typeof sessionStorage !== "undefined") sessionStorage.removeItem(key); } catch { /* noop */ }
}

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

function retryStats(result?: AgentResult) {
  const summary = result?.metadata?.retry_summary || {};
  const events = result?.metadata?.retry_events || [];
  return {
    summary,
    events,
    attempts: Number(summary.retry_attempts || 0),
    succeeded: Number(summary.retry_succeeded || 0),
    failed: Number(summary.retry_failed || 0),
    blocked: Number(summary.retry_blocked || 0),
  };
}

function trackingStats(result?: AgentResult) {
  const summary = (result?.metadata?.tracking_summary || {}) as Record<string, any>;
  const events = (result?.metadata?.tracking_events || []) as any[];
  return {
    summary,
    events,
    taskId: String(summary.task_id || ""),
    status: String(summary.status || ""),
    done: Boolean(summary.done || summary.terminal),
    mode: String(summary.mode || ""),
    nextPollSeconds: Number(summary.next_poll_seconds || 0),
    suggestedNextAction: String(summary.suggested_next_action || ""),
    progress: (summary.progress || {}) as Record<string, any>,
    taskSummary: (summary.summary || {}) as Record<string, any>,
    stallRisk: Boolean(summary.stall_risk),
  };
}

function buildAlternativePrompt(lastUserInput: string): string {
  return [
    lastUserInput,
    "",
    "上一次执行未完全成功。请先复盘失败原因，再换一种等价方案继续完成任务。",
    "要求：不要重复同一个失败命令或同一组失败参数；如果工具失败是环境缺失，请选择可用的替代命令或说明需要用户补充的信息。",
  ].join("\n");
}

// ── Memoized message row — skips re-render when store updates unrelated messages ──
const MemoMessageRow = memo(function MemoMessageRow({ m, idx, total, renderFn }: {
  m: any; idx: number; total: number;
  renderFn: (m: any, idx: number, total: number) => React.ReactNode;
}) {
  return <>{renderFn(m, idx, total)}</>;
}, (prev, next) => {
  // Only re-render if THIS specific message's content changed
  return prev.m.text === next.m.text
    && prev.m.status === next.m.status
    && prev.m.toolCalls === next.m.toolCalls
    && prev.m.result === next.m.result
    && prev.idx === next.idx;
});

export function TaskWorkbench() {
  const { currentWorkspaceId, currentSessionId } = useSessionStore();
  const sending = useWorkbenchStore((s) => s.sending);
  const lastUserInput = useWorkbenchStore((s) => s.lastUserInput);
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
  const pendingAutoMetadataRef = useRef<Record<string, unknown> | null>(null);
  // v3.10: live inspection task surfaced from the workbench. When
  // the user launches a CMDB inspection via the CMDB page, the
  // auto-prompt hands off the run to the LLM but we also kick off
  // the task ourselves so the UI has a cancel button + progress
  // without waiting for the LLM to issue the tool call.
  const [inspectionTaskId, setInspectionTaskId] = useState<string | null>(null);
  const onSendRef = useRef(onSend);
  useEffect(() => { onSendRef.current = onSend; }, [onSend]);

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
    const saved = safeGetLocal(draftKey);
    if (saved) setInput(saved);
  }, [currentSessionId]);  // eslint-disable-line

  const handleInputChange = useCallback((val: string) => {
    setInput(val);
    safeSetLocal(draftKey, val);
  }, [draftKey]);

  // Clear draft after successful send
  const clearDraft = useCallback(() => {
    safeRemoveLocal(draftKey);
  }, [draftKey]);

  // Auto-grow input
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 140) + "px";
  }, [input]);

  // Pick up cross-page auto prompts (CMDB inspection, etc.)
  useEffect(() => {
    const autoRaw = safeGetSession("workbench_auto_prompt");
    if (autoRaw && currentWorkspaceId) {
      let payload: WorkbenchAutoPrompt;
      try {
        payload = JSON.parse(autoRaw) as WorkbenchAutoPrompt;
      } catch {
        safeRemoveSession("workbench_auto_prompt");
        return;
      }
      const prompt = String(payload.prompt || "").trim();
      if (!prompt) {
        safeRemoveSession("workbench_auto_prompt");
        return;
      }
      pendingAutoMetadataRef.current = payload.metadata || {};
      setInput(prompt);
      safeRemoveSession("workbench_auto_prompt");
      return;
    }
    const prompt = safeGetSession("pcap_ai_prompt");
    if (prompt && currentWorkspaceId) {
      safeRemoveSession("pcap_ai_prompt");
      pendingAutoMetadataRef.current = { source: "packet_analysis" };
      setInput(prompt);
      // Auto-send after a short delay; use ref to avoid stale-closure/cleanup race
      const t = setTimeout(() => onSendRef.current(prompt, { source: "packet_analysis" }), 500);
      return () => clearTimeout(t);
    }
  }, [currentWorkspaceId]); // do NOT include onSend — use ref to avoid re-render killing timeout

  // ── Inspection polling: frontend tracks task, LLM only analyses ──
  useEffect(() => {
    const raw = safeGetLocal("workbench_inspection");
    if (!raw || !currentWorkspaceId) return;
    let payload: { task_id: string; metadata: Record<string, unknown> };
    try { payload = JSON.parse(raw); } catch { safeRemoveLocal("workbench_inspection"); return; }

    const { task_id, metadata } = payload;
    const target = String(metadata.target || "");
    const vendor = String(metadata.vendor || "");
    const typeLabel = String(metadata.typeLabel || "巡检");
    const analysisHints = String(metadata.analysisHints || "");

    // Show bubble via state
    setInspectionTaskId(task_id);
    setInput("");
    let done = false;
    const ac = new AbortController();

    const poll = async () => {
      if (done) return;
      try {
        const { inspectionApi } = await import("../../api/index");
        const resp = await inspectionApi.getTask(currentWorkspaceId, task_id, ac.signal) as { ok: boolean; task?: import("../../api/index").InspectionTaskRecord; error?: string };
        if (!resp.ok || !resp.task) { setTimeout(poll, 3000); return; }
        const t = resp.task;
        if (t.status === "succeeded" || t.status === "partial") {
          done = true;
          setInspectionTaskId(null);
          safeRemoveLocal("workbench_inspection"); // clear on success
          const deviceList = Object.values((t as any).devices || {} as Record<string, any>)
            .filter((d: any) => d.status === "succeeded")
            .map((d: any) => `- ${d.asset_name || d.asset_id} (${d.host})`).join("\n");
          const finalPrompt = [
            `对 ${target}${vendor} ${typeLabel}已完成。`,
            ``,
            `请用 inspection.manage 获取原始命令输出：`,
            `inspection.manage action=report format=md task_id=${task_id}`,
            ``,
            `设备清单：`,
            deviceList,
            ``,
            `拿到输出后逐设备分析，维度：${analysisHints}。`,
            `输出结构化${typeLabel}报告（概览表 + 逐设备要点）。`,
            `不要输出任何中间确认或思考过程。直接开始分析。`,
          ].join("\n");
          setInput(finalPrompt);
          pendingAutoMetadataRef.current = metadata;
          onSendRef.current(finalPrompt, metadata);
        } else if (t.status === "failed" || t.status === "cancelled") {
          done = true;
          setInspectionTaskId(null);
          safeRemoveLocal("workbench_inspection"); // clear on failure
        } else {
          setTimeout(poll, 3000);
        }
      } catch (e: unknown) {
        if (!(e instanceof DOMException && e.name === "AbortError")) {
          done = true;
          setInspectionTaskId(null);
          safeRemoveLocal("workbench_inspection"); // clear on error too
        }
      }
    };
    setTimeout(poll, 2000);

    return () => { done = true; ac.abort(); };
  }, [currentWorkspaceId]); // only re-run on workspace change

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
    if (lastUserInput && !sending) onSendRef.current(lastUserInput);
  }, [lastUserInput, sending]);

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

  async function onSend(textOverride?: string, metadataOverride?: Record<string, unknown>) {
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
    const turnMetadata = metadataOverride || pendingAutoMetadataRef.current || {};
    pendingAutoMetadataRef.current = null;

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

      // P0 fix: stage label table mirrors core.runtime_engine/stage_events.py
      // so we can translate backend events to friendly Chinese text.
      const STAGE_LABELS: Record<string, string> = {
        turn_started:        "轮次开始",
        planner_started:     "正在分析任务…",
        planner_completed:   "已规划执行图",
        graph_compiled:      "构建执行图…",
        structural_validated:"图结构校验通过",
        semantic_validated:  "语义校验通过",
        semantic_invalid:    "语义校验发现问题",
        pre_repair_started:  "自动修复阶段…",
        pre_repair_completed:"已自动修复",
        risk_assessed:       "风险评估完成",
        budget_ok:           "预算检查通过",
        execution_started:   "开始执行工具…",
        execution_completed: "工具执行完成",
        repair_attempt:      "重试节点",
        merge_completed:     "汇总执行结果",
        finalizing_started:  "整理最终回复…",
        finalizing_completed:"回复已就绪",
        turn_completed:      "轮次完成",
        heartbeat:           "仍在处理…",
      };

      // P2 fix: token batching — buffer tokens, flush every 50ms instead
      // of one setState per token. Also pause persist during streaming;
      // we flush the final text on `done` and let persist run once.
      const TOKEN_FLUSH_MS = 50;
      const tokenBufferRef = { pending: "" };
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
        metadata: turnMetadata,
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
        // P2 fix: per-token setState is replaced with a 50ms flush so
        // we only re-render the streaming message ~20 times/sec instead
        // of ~63 times/sec (the provider's actual burst rate).
        const flushTokenBuffer = () => {
          if (!tokenBufferRef.pending) return;
          streamState.draft += tokenBufferRef.pending;
          streamedText = streamState.draft;
          tokenBufferRef.pending = "";
          useWorkbenchStore.getState().updateAssistant(
            streamingMsgId, { text: streamedText }, scratch,
          );
          keepAtBottom();
        };
        const flushTimer = setInterval(flushTokenBuffer, TOKEN_FLUSH_MS);

        // P0 fix: set initial progress text on the assistant message so
        // the user sees "正在分析任务…" instead of an empty bubble.
        useWorkbenchStore.getState().updateAssistant(
          streamingMsgId, { progressText: "等待 SSOT Runtime 调度…" }, scratch,
        );

        ws!.onmessage = (event) => {
          try {
            const msg = JSON.parse(event.data);
            switch (msg.type) {
              case "token":
                // P2 fix: accumulate into buffer, not into the live state.
                // The 50ms timer (flushTokenBuffer) does the actual setState.
                const raw = msg.content || "";
                const visible = filterStreamingThink(raw, thinkFilter.current);
                tokenBufferRef.pending += visible;
                break;
              case "event":
                if (msg.data) {
                  streamingResult.events = [...(streamingResult.events || []), msg.data];
                }
                const stageName = msg.name as string;
                if (stageName === "model_started") {
                  streamState = beginModelStep(streamedText);
                  streamedText = "";
                  useWorkbenchStore.getState().updateAssistant(streamingMsgId, { text: "" }, scratch);
                }
                // P0 fix: live SSOT Runtime stage label — replaces blank "思考中…"
                // with the actual current stage (planner / risk / exec / …)
                // plus an elapsed counter for heartbeats.
                if (STAGE_LABELS[stageName]) {
                  const label = STAGE_LABELS[stageName];
                  const elapsedRaw = msg.data?.elapsed_ms;
                  const elapsedNum = typeof elapsedRaw === "number"
                    ? elapsedRaw
                    : parseInt(String(elapsedRaw || "0"), 10) || 0;
                  useWorkbenchStore.getState().updateAssistant(
                    streamingMsgId,
                    {
                      progressText: label,
                      progressElapsedMs: elapsedNum,
                    },
                    scratch,
                  );
                }
                if (stageName === "tool_call" || stageName === "tool_result") {
                  streamingResult.tool_calls_count = (streamingResult.tool_calls_count || 0) + 1;
                  const tid = msg.data?.tool_id || msg.data?.name || "";
                  if (tid) {
                    // Update live tool calls directly on the streaming message
                    const store = useWorkbenchStore.getState();
                    const curr = store.bySession[scratch]?.find((m) => m.id === streamingMsgId);
                    const prevCalls = (curr?.toolCalls || []) as any[];
                    if (stageName === "tool_result") {
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
                if (stageName === "tool_call") {
                  // Flush pending tokens before discarding the draft.
                  flushTokenBuffer();
                  discardToolCallDraft(streamState);
                  streamedText = "";
                  useWorkbenchStore.getState().updateAssistant(streamingMsgId, { text: "" }, scratch);
                }
                // Keep scrolled to bottom after any event that changes content height
                keepAtBottom();
                break;
              case "done":
                // P2 fix: flush any remaining buffered tokens before
                // the final text is computed.
                flushTokenBuffer();
                clearInterval(flushTimer);
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
                // P0 fix: clear the in-flight progress label since the
                // final assistant text replaces it.
                useWorkbenchStore.getState().updateAssistant(
                  streamingMsgId, { progressText: "" }, scratch,
                );
                resolve();
                break;
              case "error":
                clearInterval(flushTimer);
                // P2 fix: flush whatever we had buffered, then keep
                // the partial text visible to the user.
                flushTokenBuffer();
                streamingResult.errors = [msg.message || msg.error || "Unknown error"];
                useWorkbenchStore.getState().updateAssistant(
                  streamingMsgId, { progressText: "" }, scratch,
                );
                resolve();
                break;
            }
          } catch { /* ignore parse errors */ }
        };

        ws!.onclose = () => {
          clearInterval(flushTimer);
          flushTokenBuffer();
          resolve();
        };
        ws!.onerror = () => {
          clearInterval(flushTimer);
          flushTokenBuffer();
          resolve();
        };
      });

      try { ws.close(); } catch { /* already closed */ }
      ws = null;
      wsRef.current = null;

      // Phase 1: defer session migration to next microtask
      if (!currentSessionId && resolvedSid) {
        queueMicrotask(() => {
          useSessionStore.getState().setCurrentSession(resolvedSid);
          useWorkbenchStore.setState((prev) => {
            const scratchMsgs = prev.bySession["_scratch"] ?? [];
            const existing = prev.bySession[resolvedSid] ?? [];
            return { bySession: { ...prev.bySession, [resolvedSid]: [...existing, ...scratchMsgs], _scratch: [] } };
          });
          useWorkbenchStore.getState().switchSession(resolvedSid);
        });
      }

      const wsResult = agentResultFromWsDone(streamingResult, streamedText, resolvedSid);
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
      // Defer heavy post-processing
      queueMicrotask(() => {
        setLatestResult(wsResult, resolvedSid);
        notifyRunCompleted();
        keepAtBottom();
      });

      if (resolvedSid && currentWorkspaceId) {
        sessionsApi.messages(resolvedSid, currentWorkspaceId)
          .then((r) => { if (r.messages?.length) mergeFromBackend(resolvedSid, r.messages); })
          .catch(() => {});
      }

    } catch {
      // WebSocket failed, fall back to HTTP
      if (ws) { try { ws.close(); } catch {} }
      try {
        const res = await agentApi.run({
          message: fullText,
          workspace_id: currentWorkspaceId,
          session_id: currentSessionId,
          metadata: turnMetadata,
        });
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
        setLatestResult(res, resolvedSid);
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
        setLatestResult(stubResult, fallbackSid);
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
              {/* P0 fix: live progress label — replaces the static
                  "思考中…" so the user sees which SSOT Runtime stage is running
                  (planner / risk / exec / finalizing). Empty when not
                  streaming or before the first event arrives. */}
              {m.progressText && (
                <div className="ssot-runtime-progress-row" data-testid="ssot-runtime-progress">
                  <span className="typing-indicator">
                    <span className="typing-dot" />
                    <span className="typing-dot" />
                    <span className="typing-dot" />
                  </span>
                  <span className="text-sm" style={{ marginLeft: 6 }}>
                    {m.progressText}
                    {m.progressElapsedMs != null && m.progressElapsedMs > 0 ? (
                      <span className="muted" style={{ marginLeft: 6 }}>
                        ({m.progressElapsedMs >= 1000
                          ? `${(m.progressElapsedMs / 1000).toFixed(1)}s`
                          : `${m.progressElapsedMs}ms`})
                      </span>
                    ) : null}
                  </span>
                </div>
              )}
              {m.text ? (
                <StreamingContent text={m.text} />
              ) : !m.progressText ? (
                <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <span className="typing-indicator"><span className="typing-dot" /><span className="typing-dot" /><span className="typing-dot" /></span>
                  <span className="text-sm muted" style={{ marginLeft: 6 }}>思考中…</span>
                </div>
              ) : null}
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
              <ResultInline
                result={m.result}
                fallbackText={sanitizeAssistantText(m.text)}
                onRetryOriginal={idx === total - 1 && lastUserInput ? () => onSendRef.current(lastUserInput) : undefined}
                onRetryAlternative={idx === total - 1 && lastUserInput ? () => onSendRef.current(buildAlternativePrompt(lastUserInput)) : undefined}
              />
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
            <button className="regenerate-btn" onClick={() => onSendRef.current(lastUserInput)} title="重新生成" type="button">🔄 重新生成</button>
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
            setTimeout(() => URL.revokeObjectURL(a.href), 100);
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
          <RuntimeEventTimeline messages={visibleHistory ?? []} />
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
              <MemoMessageRow key={m.message_id || m.run_id || `local-${m.id}`} m={m} idx={idx} total={(visibleHistory ?? []).length} renderFn={renderMsg} />
            ))}
          </div>
        )}

        {/* ── Inspection floating bubble (above input box) ── */}
        {inspectionTaskId && (
          <div style={{
            position: "fixed", bottom: 72, left: "50%", transform: "translateX(-50%)",
            zIndex: 9999, padding: "10px 20px", borderRadius: 10,
            background: "var(--surface)", boxShadow: "0 4px 24px rgba(0,0,0,0.15)",
            border: "1px solid var(--line-2)", display: "flex", alignItems: "center", gap: 10,
            fontSize: 13, fontWeight: 600, color: "var(--text)",
          }}>
            <span style={{ fontSize: 16 }}>⏳</span>
            <span>巡检进行中…</span>
            <span style={{ fontSize: 11, fontWeight: 400, color: "var(--text-4)", fontFamily: "var(--font-mono)" }}>
              {inspectionTaskId}
            </span>
            <span style={{
              width: 8, height: 8, borderRadius: "50%",
              background: "var(--accent)", animation: "pulse 1.2s infinite",
            }} />
          </div>
        )}

        {/* ── Scroll-to-bottom floating bubble ── */}
        {showScrollBtn && (
          <button className="scroll-bottom-btn" onClick={handleScrollBtnClick} title="回到底部" type="button">
            <svg width="14" height="14" viewBox="0 0 16 16"><path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </button>
        )}
      </div>

      {/* ── Retry bar (derive from last assistant message's result) ── */}
      {(() => {
        if (sending || !lastUserInput) return null;
        const lastAssistant = [...(visibleHistory ?? [])].reverse().find((m) => m.role === "assistant");
        const lastResult = lastAssistant?.result;
        if (!lastResult) return null;
        if (lastResult.ok) return null;
        return (
          <div className="wb-retry-bar">
            <IconAlert size={11} />
            <span>{_humanFailure(lastResult.error_type, lastResult.errors?.[0] ?? "请求失败").msg}</span>
            {_humanFailure(lastResult.error_type, lastResult.errors?.[0] ?? "").retryable && (
              <button type="button" onClick={() => onSend(lastUserInput)} data-testid="retry-btn">
                重试原任务
              </button>
            )}
            {_humanFailure(lastResult.error_type, lastResult.errors?.[0] ?? "").retryable && (
              <button type="button" onClick={() => onSend(buildAlternativePrompt(lastUserInput))} data-testid="retry-alt-btn">
                换方案继续
              </button>
            )}
          </div>
        );
      })()}

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

const ResultInline = React.memo(function ResultInline({
  result,
  fallbackText,
  onRetryOriginal,
  onRetryAlternative,
}: {
  result: AgentResult | undefined;
  fallbackText: string;
  onRetryOriginal?: () => void;
  onRetryAlternative?: () => void;
}) {
  const { currentWorkspaceId } = useSessionStore();
  const toast = useToastStore((s) => s.show);
  const [saving, setSaving] = useState<"" | "memory" | "knowledge">("");
  const summaries = ((result?.metadata as any)?.context_sources || (result?.metadata as any)?.source_summary || []) as any[];
  const isFailed = !result?.ok;
  const hasFailedTool = ((result?.tool_calls) ?? []).some((tc) => !tc.ok);
  const finalText = (result?.final_response || fallbackText || "").trim();
  const retry = retryStats(result);
  const tracking = trackingStats(result);
  const toolCalls = result?.tool_calls ?? [];
  const actionCount = toolCalls.length;
  const failedToolCount = toolCalls.filter((tc) => !tc.ok).length;
  const successToolCount = toolCalls.filter((tc) => tc.ok).length;
  const showActionTrace = !!result && (actionCount > 0 || retry.events.length > 0 || tracking.taskId || isFailed);

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

      {showActionTrace && (
        <div className="action-trace-panel" data-testid="action-trace-panel">
          <div className="action-trace-head">
            <span className="action-trace-title">动作跟踪</span>
            <span className="action-trace-pill">{actionCount} 个工具</span>
            <span className="action-trace-pill ok">{successToolCount} 成功</span>
            {failedToolCount > 0 && <span className="action-trace-pill danger">{failedToolCount} 需关注</span>}
            {retry.attempts > 0 && <span className="action-trace-pill warn">{retry.attempts} 次自动重试</span>}
            {retry.blocked > 0 && <span className="action-trace-pill muted">{retry.blocked} 次未重试</span>}
          </div>
          {retry.events.length > 0 ? (
            <div className="action-retry-list">
              {retry.events.slice(0, 4).map((ev, i) => (
                <div className="action-retry-row" key={`${ev.node_id || ev.tool_id || "retry"}-${i}`}>
                  <span className={`action-retry-dot ${ev.retry_allowed ? (ev.final_status === "succeeded" ? "ok" : "warn") : "muted"}`} />
                  <span className="action-retry-main">
                    <b>{toolLabel(String(ev.tool_id || ev.node_id || "工具"))}</b>
                    {ev.retry_allowed
                      ? ev.final_status === "succeeded"
                        ? " 首次失败后已恢复"
                        : " 已重试但仍失败"
                      : ` 未重试：${ev.reason || "不满足安全重试条件"}`}
                  </span>
                  {ev.backoff_ms ? <span className="action-retry-meta">{ev.backoff_ms}ms</span> : null}
                </div>
              ))}
            </div>
          ) : actionCount > 0 ? (
            <div className="action-trace-note">
              本轮没有触发自动重试；危险命令和有副作用动作不会自动重试。
            </div>
          ) : (
            <div className="action-trace-note">
              本轮失败发生在工具调用前，未触发可重试动作。
            </div>
          )}
          {tracking.taskId && (
            <div className="action-trace-note">
              <b>任务跟踪 · {tracking.taskId}</b>
              <span style={{ marginLeft: 8 }}>
                状态 {tracking.status || "unknown"}
                {tracking.mode ? ` · ${tracking.mode}` : ""}
                {tracking.progress?.percent != null ? ` · ${tracking.progress.percent}%` : ""}
              </span>
              {tracking.stallRisk && <span className="action-trace-pill warn" style={{ marginLeft: 8 }}>可能停滞</span>}
              {!tracking.done && (
                <div style={{ marginTop: 8 }}>
                  <TaskTrackingCard tracking={tracking.summary} />
                </div>
              )}
              {tracking.done && (
                <div style={{ marginTop: 6 }}>
                  设备 {tracking.taskSummary.succeeded_devices || 0} 成功 / {tracking.taskSummary.failed_devices || 0} 失败 / {tracking.taskSummary.skipped_devices || 0} 跳过；
                  发现 {tracking.taskSummary.findings_critical || 0} critical · {tracking.taskSummary.findings_warning || 0} warning · {tracking.taskSummary.findings_info || 0} info。
                  {tracking.suggestedNextAction === "fetch_report" ? " 下一步：获取 HTML 报告。" : ""}
                </div>
              )}
            </div>
          )}
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
          {hasFailedTool && onRetryAlternative && (
            <button type="button" className="run-detail-button" onClick={onRetryAlternative}>
              换方案继续
            </button>
          )}
          {isFailed && onRetryOriginal && (
            <button type="button" className="run-detail-button" onClick={onRetryOriginal}>
              重试原任务
            </button>
          )}
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
