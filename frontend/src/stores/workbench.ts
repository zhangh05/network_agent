/**
 * Workbench store — chat history + run results keyed by session_id,
 * persisted to localStorage so F5 不会丢历史 (plan-C 方案).
 *
 * 状态:
 *  - bySession: Record<session_id, ChatMsg[]> 持久化到 localStorage
 *  - results:  Record<session_id, AgentResult[]>  各 session 的运行记录
 *  - currentSessionId: 镜像 useSessionStore.currentSessionId
 *  - sending: 是否在等后端
 *
 * 持久化策略:
 *  - 每个会话最多 30 条消息
 *  - 最多保留 5 个最近会话
 *  - 超出 LRU 淘汰 (按会话 ID 字典序简化)
 *  - localStorage key: "na_workbench"
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { AgentResult, SessionMessage, MessageStatus, InlineToolCall } from "../types";
import { sanitizeAssistantText, toolLabel } from "../utils/displayText";

export interface ChatMsg {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  created_at: string;
  /** Message lifecycle status */
  status: MessageStatus;
  /** attached to assistant msgs only */
  result?: AgentResult;
  /** v1.0.3.2: run_id from the backend, used for dedup in mergeFromBackend */
  run_id?: string;
  /** Inline tool calls for structured rendering */
  toolCalls?: InlineToolCall[];
  /** Error message when status === "error" */
  error?: string;
  /** Trace ID for context linking */
  trace_id?: string;
}

const MAX_MSGS_PER_SESSION = 100;
const MAX_SESSIONS = 20;

let msgSeq = 0;
function nextId(): string {
  msgSeq += 1;
  return `msg-${Date.now()}-${msgSeq}`;
}

/**
 * Cap a session's history to MAX_MSGS_PER_SESSION (drop oldest, keep newest).
 * Also cap the entire map to MAX_SESSIONS entries by simple LRU on
 * session_id (good enough — chat sessions are not high-cardinality).
 */
function capHistory(
  map: Record<string, ChatMsg[]>,
  keepSessionId?: string,
): Record<string, ChatMsg[]> {
  if (!map || typeof map !== "object") return {};
  // Per-session cap
  const capped: Record<string, ChatMsg[]> = {};
  for (const [k, v] of Object.entries(map)) {
    if (!Array.isArray(v)) continue;
    if (v.length > MAX_MSGS_PER_SESSION) {
      capped[k] = v.slice(v.length - MAX_MSGS_PER_SESSION);
    } else {
      capped[k] = v;
    }
  }
  // Global cap (LRU: drop keys with lexicographically smallest id)
  const keys = Object.keys(capped);
  if (keys.length > MAX_SESSIONS) {
    const sorted = [...keys]
      .filter((key) => key !== keepSessionId)
      .sort();
    const toDelete = sorted.slice(0, keys.length - MAX_SESSIONS);
    for (const k of toDelete) delete capped[k];
  }
  return capped;
}

interface WorkbenchState {
  bySession: Record<string, ChatMsg[]>;
  currentSessionId: string | null;
  /** Per-session run results (v3.9: persisted, survives session switch) */
  results: Record<string, AgentResult[]>;
  sending: boolean;
  lastUserInput: string;

  switchSession: (session_id: string | null) => void;
  appendUser: (text: string, session_id: string | null) => void;
  /** Create a streaming assistant placeholder before response arrives */
  appendAssistantStreaming: (session_id: string | null) => string;
  /** Finalize a streaming message with full result */
  appendAssistant: (
    text: string,
    result: AgentResult | undefined,
    session_id: string | null,
  ) => void;
  /** Update an existing message (streaming→ready/error, append tool calls) */
  updateAssistant: (
    msgId: string,
    patch: Partial<Pick<ChatMsg, "status" | "text" | "error" | "toolCalls" | "trace_id" | "result">>,
    session_id?: string,
  ) => void;
  setSending: (v: boolean) => void;
  setLatestResult: (r: AgentResult) => void;
  /** Drop local history for current (or specified) session. */
  clear: (session_id?: string) => void;
  mergeFromBackend: (session_id: string, serverMsgs: SessionMessage[]) => void;
}

export const useWorkbenchStore = create<WorkbenchState>()(
  persist(
    (set, get) => ({
      bySession: {},
      currentSessionId: null,
      results: {},
      sending: false,
      lastUserInput: "",

      switchSession: (session_id) => {
        set((s) => {
          if (session_id && !s.bySession[session_id]) {
            return {
              currentSessionId: session_id,
              bySession: { ...s.bySession, [session_id]: [] },
            };
          }
          return { currentSessionId: session_id };
        });
      },

      appendUser: (text, session_id) => {
        const sid = session_id ?? get().currentSessionId ?? "_scratch";
        const msg: ChatMsg = {
          id: nextId(),
          role: "user",
          text,
          status: "ready",
          created_at: new Date().toISOString(),
        };
        set((s) => {
          const cur = s.bySession[sid] ?? [];
          const next = capHistory({ ...s.bySession, [sid]: [...cur, msg] }, sid);
          return { bySession: next, lastUserInput: text };
        });
      },

      appendAssistantStreaming: (session_id) => {
        const sid = session_id ?? get().currentSessionId ?? "_scratch";
        const msgId = nextId();
        const msg: ChatMsg = {
          id: msgId,
          role: "assistant",
          text: "",
          status: "streaming",
          created_at: new Date().toISOString(),
          toolCalls: [],
        };
        set((s) => {
          const cur = s.bySession[sid] ?? [];
          const next = capHistory({ ...s.bySession, [sid]: [...cur, msg] }, sid);
          return { bySession: next };
        });
        return msgId;
      },

      appendAssistant: (text, result, session_id) => {
        const sid = session_id ?? get().currentSessionId ?? "_scratch";
        const cleanText = sanitizeAssistantText(text);
        const cleanResult = result
          ? { ...result, final_response: sanitizeAssistantText(result.final_response ?? "") }
          : undefined;
        // Build inline tool calls from result
        const toolCalls: InlineToolCall[] = (cleanResult?.tool_calls ?? []).map((tc) => ({
          tool_id: tc.tool_id,
          tool_name: toolLabel(tc.tool_id),
          ok: tc.ok,
          summary: tc.summary,
          duration_ms: tc.duration_ms ?? undefined,
          errors: tc.errors,
          artifacts: tc.artifacts,
        }));
        const msg: ChatMsg = {
          id: nextId(),
          role: "assistant",
          text: cleanText,
          status: cleanResult?.ok === false && !cleanText ? "error" : "ready",
          created_at: new Date().toISOString(),
          result: cleanResult,
          toolCalls: toolCalls.length > 0 ? toolCalls : undefined,
          error: !cleanResult?.ok && cleanResult?.errors?.length
            ? cleanResult.errors[0] : undefined,
          trace_id: cleanResult?.trace_id,
          run_id: cleanResult?.turn_id,
        };
        set((s) => {
          const cur = s.bySession[sid] ?? [];
          const next = capHistory({ ...s.bySession, [sid]: [...cur, msg] }, sid);
          // Append run result to session's results array
          const sessResults = s.results[sid] ?? [];
          const maxResults = 50;
          const nextResults = cleanResult
            ? { ...s.results, [sid]: [...sessResults, cleanResult].slice(-maxResults) }
            : s.results;
          return {
            bySession: next,
            results: nextResults,
          };
        });
      },

      updateAssistant: (msgId, patch, session_id) => {
        const sid = session_id ?? get().currentSessionId ?? "_scratch";
        set((s) => {
          const cur = s.bySession[sid] ?? [];
          const idx = cur.findIndex((m) => m.id === msgId);
          if (idx < 0) return s;
          const updated = { ...cur[idx], ...patch };
          const next = capHistory(
            { ...s.bySession, [sid]: [...cur.slice(0, idx), updated, ...cur.slice(idx + 1)] },
            sid,
          );
          return { bySession: next };
        });
      },

      setSending: (v) => set({ sending: v }),
      // v3.9: setLatestResult appends to current session's results
      setLatestResult: (r) => {
        const sid = get().currentSessionId;
        if (!sid) return;
        set((s) => {
          const sessResults = s.results[sid] ?? [];
          const maxResults = 50;
          return {
            results: { ...s.results, [sid]: [...sessResults, r].slice(-maxResults) },
          };
        });
      },

      clear: (session_id) => {
        const sid = session_id ?? get().currentSessionId;
        if (!sid) return;
        set((s) => {
          const nextBySession = { ...s.bySession };
          delete nextBySession[sid];
          const nextResults = { ...s.results };
          delete nextResults[sid];
          return { bySession: nextBySession, results: nextResults };
        });
      },

      mergeFromBackend: (session_id, serverMsgs) => {
        if (!session_id) return;
        const converted: ChatMsg[] = serverMsgs.map((m) => ({
          id:
            m.message_id ??
            `srv-${m.run_id ?? m.created_at}-${Math.random().toString(36).slice(2, 8)}`,
          role: m.role,
          text: m.role === "assistant" ? sanitizeAssistantText(m.content) : m.content,
          status: "ready",
          created_at: m.created_at,
          run_id: m.run_id,
          // `result` 不可从后端还原, 渲染为纯文本气泡 (无 inline 工具调用)
        }));
        set((s) => {
          const persisted = s.bySession[session_id];
          const cur = Array.isArray(persisted)
            ? persisted.filter(
                (message): message is ChatMsg =>
                  !!message &&
                  typeof message.id === "string" &&
                  typeof message.text === "string" &&
                  typeof message.created_at === "string" &&
                  ["user", "assistant", "system"].includes(message.role),
              )
            : [];
          // v1.0.3.2: dual dedup strategy
          // (a) by content+role — catches local vs backend duplicates
          // (b) by message_id — catches server-side self-duplicates
          const contentSeen = new Set(cur.map((m) => `${m.role}:${m.text.slice(0, 200)}`));
          const idSeen = new Set(cur.map((m) => m.id));
          const combined = [...cur];
          for (const m of converted) {
            if (idSeen.has(m.id)) continue;
            const ck = `${m.role}:${m.text.slice(0, 200)}`;
            if (contentSeen.has(ck)) continue;
            idSeen.add(m.id);
            contentSeen.add(ck);
            combined.push(m);
          }
          // 按 created_at 升序
          combined.sort((a, b) => a.created_at.localeCompare(b.created_at));
          const next = capHistory(
            {
              ...s.bySession,
              [session_id]: combined,
            },
            session_id,
          );
          return {
            bySession: next,
          };
        });
      },
    }),
    {
      name: "na_workbench",
      version: 2,
      partialize: (s) => ({
        bySession: s.bySession,
        results: s.results,
        lastUserInput: s.lastUserInput,
      }),
      merge: (persisted: unknown, current: WorkbenchState): WorkbenchState => {
        const p = persisted as Record<string, unknown> | null | undefined;
        const safe = p?.bySession;
        const safeResults = p?.results;
        const merged: Partial<WorkbenchState> = {};
        if (safe && typeof safe === "object" && !Array.isArray(safe)) {
          merged.bySession = safe as Record<string, ChatMsg[]>;
        }
        if (safeResults && typeof safeResults === "object" && !Array.isArray(safeResults)) {
          merged.results = safeResults as Record<string, AgentResult[]>;
        }
        return { ...current, ...merged };
      },
    },
  ),
);
