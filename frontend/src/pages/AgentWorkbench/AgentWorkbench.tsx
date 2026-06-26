import React, { useState, useRef, useEffect, useCallback } from "react";
import { agentApi, knowledgeApi, memoryApi, sessionsApi, settingsApi } from "../../api";
import { apiRequest } from "../../api/client";
import { useSessionStore } from "../../stores/session";
import { useWorkbenchStore } from "../../stores/workbench";
import { useToastStore } from "../../stores/toast";
import { isApiError } from "../../types";
import type { AgentResult, ToolCallResult } from "../../types";
import { sanitizeAssistantText, renderAssistantHtml, toolLabel } from "../../utils/displayText";
import { beginModelStep, discardToolCallDraft, finalizeStreamText } from "../../utils/agentStream";
import hljs from "highlight.js/lib/core";
import accesslog from "highlight.js/lib/languages/accesslog";
import bash from "highlight.js/lib/languages/bash";
import css from "highlight.js/lib/languages/css";
import diff from "highlight.js/lib/languages/diff";
import dos from "highlight.js/lib/languages/dos";
import http from "highlight.js/lib/languages/http";
import ini from "highlight.js/lib/languages/ini";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import nginx from "highlight.js/lib/languages/nginx";
import plaintext from "highlight.js/lib/languages/plaintext";
import powershell from "highlight.js/lib/languages/powershell";
import python from "highlight.js/lib/languages/python";
import routeros from "highlight.js/lib/languages/routeros";
import shell from "highlight.js/lib/languages/shell";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";
import "highlight.js/styles/github.min.css";
import { agentResultFromWsDone } from "../../utils/wsResult";
import { notifyRunCompleted } from "../../utils/appEvents";
import { IconAlert, IconBolt, IconSend } from "../../components/Icon";
import { ApprovalBubble } from "../../components/ApprovalBubble";
import { RuntimeEventTimeline } from "../../components/RuntimeEventTimeline";
import "../../components/RuntimeEventTimeline.css";
import { formatFileSize } from "../../utils/format";

/* ── v3.9 View mode ── */
type ViewMode = "chat" | "timeline";

const QUICK_CHIPS = [
  {
    label: "OSPF 邻居不起来",
    prompt: "帮我排查 OSPF 邻居不起来。请先告诉我需要提供哪些现象、配置和日志，我会补充。",
  },
  {
    label: "Cisco 配置转华为",
    prompt: "帮我把 Cisco 配置翻译成华为配置。请提示我粘贴源配置，并说明转换后的配置需要人工复核。",
  },
  {
    label: "出口策略放通检查",
    prompt: "帮我分析出口访问策略是否放通。请告诉我需要提供源地址、目的地址、端口、协议，以及相关 ACL/NAT/路由配置。",
  },
];

for (const [name, language] of Object.entries({
  accesslog,
  bash,
  css,
  diff,
  dos,
  http,
  ini,
  javascript,
  js: javascript,
  json,
  nginx,
  plaintext,
  powershell,
  ps1: powershell,
  python,
  py: python,
  routeros,
  shell,
  sh: shell,
  sql,
  typescript,
  ts: typescript,
  xml,
  yaml,
  yml: yaml,
})) {
  hljs.registerLanguage(name, language);
}

function _humanFailure(text: string): string {
  if (text.includes("provider_timeout") || text.includes("timed out") || text.includes("超时"))
    return "模型请求超过 30 秒未返回，可能是供应商响应慢或网络抖动。可以稍后重试，或缩短问题再试。";
  if (text.includes("disabled") || text.includes("LLM is disabled"))
    return "LLM 功能未启用，请前往系统设置开启并配置 API Key。";
  if (text.includes("api_key") || text.includes("authentication"))
    return "API 密钥未配置或已失效，请前往系统设置重新设置。";
  return text;
}

export function TaskWorkbench() {
  const { currentWorkspaceId, currentSessionId } = useSessionStore();
  const sending = useWorkbenchStore((s) => s.sending);
  const lastUserInput = useWorkbenchStore((s) => s.lastUserInput);
  const results = useWorkbenchStore((s) => s.results);
  const sessionResults = results[currentSessionId ?? "_scratch"] ?? [];
  const bySession = useWorkbenchStore((s) => s.bySession);
  const appendUser = useWorkbenchStore((s) => s.appendUser);
  const appendAssistant = useWorkbenchStore((s) => s.appendAssistant);
  const setSending = useWorkbenchStore((s) => s.setSending);
  const switchSession = useWorkbenchStore((s) => s.switchSession);
  const mergeFromBackend = useWorkbenchStore((s) => s.mergeFromBackend);
  const setLatestResult = useWorkbenchStore((s) => s.setLatestResult);

  const activeHistoryKey = currentSessionId ?? "_scratch";
  const visibleHistory = bySession?.[activeHistoryKey] ?? [];
  const [viewMode, setViewMode] = useState<ViewMode>("chat");
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<Array<{ id: string; name: string; size: string; file: File; uploading?: boolean }>>([]);
  const [streamingText, setStreamingText] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [llmHealth, setLlmHealth] = useState<{ connected: boolean; provider?: string; model?: string; recentFailure?: string }>({ connected: false });
  const chatRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const toast = useToastStore((s) => s.show);
  const abortRef = useRef<AbortController | null>(null);

  // Stop generation
  const stopGeneration = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setSending(false);
    setStreamingText("");
  }, [setSending]);

  // Clean up abort controller on unmount
  useEffect(() => () => { abortRef.current?.abort(); }, []);

  // LLM health poll
  useEffect(() => {
    const poll = () => {
      settingsApi.llmStatus().then((s) => {
        if (!s) return;
        setLlmHealth({
          connected: s.connected,
          provider: s.provider || s.provider_type || "",
          model: s.model || "",
          recentFailure: s.recent_failure?.error_type ? s.recent_failure.error_summary : undefined,
        });
      }).catch(() => {});
    };
    poll();
    const id = window.setInterval(poll, 30_000);
    return () => window.clearInterval(id);
  }, []);

  // Scroll on new messages / streaming tokens
  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: "smooth" });
  }, [(visibleHistory ?? []).length, sending, streamingText]);

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

    const scratch = currentSessionId;
    appendUser(fullText, scratch);
    setSending(true);
    setStreamingText("");  // Clear previous streaming text

    // Try WebSocket streaming first, fall back to HTTP
    // Dev: proxied through Vite (port 5173). Prod: same-origin.
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsHost = window.location.host; // Includes port (5173 in dev, 8010 in prod)
    const wsUrl = `${protocol}//${wsHost}/ws/agent`;
    let ws: WebSocket | null = null;
    abortRef.current = new AbortController();

    try {
      ws = new WebSocket(wsUrl);

      // Track streaming state
      let streamedText = "";
      let streamState = beginModelStep();
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
                // Real-time token display
                streamState.draft += msg.content || "";
                streamedText = streamState.draft;
                setStreamingText(streamedText);
                break;
              case "event":
                if (msg.data) {
                  streamingResult.events = [...(streamingResult.events || []), msg.data];
                }
                // Log events for debugging
                if (msg.name === "model_started") {
                  streamState = beginModelStep(streamedText);
                  streamedText = "";
                  setStreamingText("");
                }
                if (msg.name === "tool_call" || msg.name === "tool_result") {
                  streamingResult.tool_calls_count = (streamingResult.tool_calls_count || 0) + 1;
                }
                if (msg.name === "tool_call") {
                  discardToolCallDraft(streamState);
                  streamedText = "";
                  setStreamingText("");
                }
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

      // Handle session resolution
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
      appendAssistant(wsResult.final_response, wsResult, resolvedSid);
      notifyRunCompleted();

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
        // Update latestResult so Timeline refreshes
        setLatestResult(res);
        notifyRunCompleted();
        if (res.ok) {
          toast({ kind: "success", title: "回答完成", body: "可切换到时间线视图查看执行详情" });
        } else {
          toast({ kind: "error", title: "请求失败", body: _humanFailure(res.errors?.[0] ?? "") });
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
          tool_calls: [], warnings: [], errors: [msg],
          metadata: { source_count: 0, source_summary: [] },
        };
        appendAssistant(stubResult.final_response, stubResult, fallbackSid);
        toast({ kind: "error", title: "请求失败", body: msg });
      }
    } finally {
      // Defer one frame so that appendAssistant's history message
      // renders BEFORE the streaming bubble disappears — seamless transition.
      requestAnimationFrame(() => {
        setSending(false);
        setStreamingText("");
      });
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

  return (
    <div className="wb-shell">
      {/* ── Header bar ── */}
      <div className="wb-header">
        <div className="wb-header-status">
          <span className={"dot " + (llmHealth.connected ? (llmHealth.recentFailure ? "warn" : "ok") : "err")} />
          <span>{llmStatusLabel}</span>
        </div>
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
      <div className="wb-chat" ref={chatRef} data-testid="chat-stream">
        {viewMode === "timeline" ? (
          /* ── Timeline view ── */
          <RuntimeEventTimeline results={sessionResults} />
        ) : (visibleHistory?.length ?? 0) === 0 && !sending ? (
          /* ── Chat empty state ── */
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
          (visibleHistory ?? []).map((m) =>
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
                  {(() => {
                    const { thinking, body } = parseThinking(m.text);
                    return (
                      <>
                        {thinking && <ThinkingBlock content={thinking} />}
                        {(() => {
                          const html = renderAssistantHtml(body);
                          if (!html) return <span className="muted">(空消息)</span>;
                          // Post-process for code highlighting
                          const highlighted = highlightCode(html);
                          return <div className="chat-bubble assistant markdown-body" onClick={handleCodeCopyClick} dangerouslySetInnerHTML={{ __html: highlighted }} />;
                        })()}
                      </>
                    );
                  })()}
                  <ResultInline result={m.result} fallbackText={sanitizeAssistantText(m.text)} />
                </div>
              </div>
            )
          )
        )}

        {/* ── Streaming indicator ── */}
        {sending && (
          <div className="message-row assistant" data-testid="chat-sending">
            <div className="message-avatar agent">网</div>
            <div className="message-stack">
              <div className="chat-bubble assistant sending-line">
                {streamingText ? (
                  <StreamingContent text={streamingText} />
                ) : (
                  <>
                    <span className="typing-indicator">
                      <span className="typing-dot" />
                      <span className="typing-dot" />
                      <span className="typing-dot" />
                    </span>
                    <span className="text-sm muted" style={{ marginLeft: 8 }}>思考中…</span>
                  </>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── Retry bar ── */}
      {!sending && sessionResults.length > 0 && !sessionResults[sessionResults.length - 1].ok && lastUserInput && (
        <div className="wb-retry-bar">
          <IconAlert size={11} />
          <span>{_humanFailure(sessionResults[sessionResults.length - 1].errors?.[0] ?? "请求失败")}</span>
          <button type="button" onClick={() => onSend(lastUserInput)} data-testid="retry-btn">
            自动重试
          </button>
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
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); onSend(); } }}
            disabled={sending}
            rows={1}
            data-testid="chat-input"
            spellCheck={false}
            style={{ fieldSizing: "content" }}
          />
          {sending ? (
            <button className="wb-stop" onClick={stopGeneration} title="停止生成" type="button" data-testid="btn-stop">
              <span style={{ display: "inline-block", width: 10, height: 10, background: "var(--danger)", borderRadius: 2 }} />
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
   Helpers
   ============================================================== */

/** Parse <thinking>...</thinking> blocks from markdown content */
function parseThinking(text: string): { thinking: string; body: string } {
  const match = text.match(/<thinking>([\s\S]*?)<\/thinking>/i);
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

  async function rememberAnswer() {
    if (!finalText) { toast({ kind: "warning", title: "无法保存", body: "当前回答内容为空" }); return; }
    if (!currentWorkspaceId) { toast({ kind: "warning", title: "未选择工作区", body: "请先在左侧选择工作区" }); return; }
    if (saving) return;
    setSaving("memory");
    try {
      const res = await memoryApi.confirm({
        title: finalText.slice(0, 42) || "本次结论",
        content: finalText,
        memory_type: "decision",
        tags: ["agent_answer", "confirmed"],
        project_id: currentWorkspaceId,
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
