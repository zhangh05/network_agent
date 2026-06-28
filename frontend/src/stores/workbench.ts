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
import { sanitizeAssistantText } from "../utils/displayText";

export interface ChatMsg {
  id: string;
  message_id?: string;
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
  // Global cap (LRU: drop sessions with oldest most-recent message)
  const keys = Object.keys(capped);
  if (keys.length > MAX_SESSIONS) {
    // Get timestamp of newest message per session
    const latestTs: Record<string, number> = {};
    for (const k of keys) {
      const msgs = capped[k];
      if (msgs.length === 0) { latestTs[k] = 0; continue; }
      const newest = msgs[msgs.length - 1];
      latestTs[k] = new Date(newest.created_at || 0).getTime();
    }
    const sorted = [...keys]
      .filter((key) => key !== keepSessionId)
      .sort((a, b) => latestTs[a] - latestTs[b]);
    const toDelete = sorted.slice(0, keys.length - MAX_SESSIONS);
    for (const k of toDelete) delete capped[k];
  }
  return capped;
}

function messageKey(m: Pick<ChatMsg, "message_id" | "run_id" | "role" | "text" | "created_at">): string {
  if (m.message_id) return `id:${m.message_id}`;
  if (m.run_id) return `run:${m.run_id}:${m.role}`;
  return `fallback:${m.role}:${m.created_at}:${m.text}`;
}

function dedupeMessages(messages: ChatMsg[]): ChatMsg[] {
  const byStable = new Set<string>();
  const out: ChatMsg[] = [];
  for (const message of messages) {
    const stable = messageKey(message);
    if (byStable.has(stable)) continue;
    byStable.add(stable);
    out.push(message);
  }
  return out;
}

function contentKey(m: Pick<ChatMsg, "role" | "text">): string {
  return `${m.role}:${m.text.trim()}`;
}

function validChatMessage(message: unknown): message is ChatMsg {
  if (!message || typeof message !== "object") return false;
  const m = message as Partial<ChatMsg>;
  return (
    typeof m.id === "string" &&
    typeof m.text === "string" &&
    typeof m.created_at === "string" &&
    typeof m.role === "string" &&
    ["user", "assistant", "system"].includes(m.role)
  );
}

function findLocalForServer(serverMsg: ChatMsg, localMessages: ChatMsg[]): ChatMsg | undefined {
  const stable = messageKey(serverMsg);
  const exact = localMessages.find((m) => messageKey(m) === stable);
  if (exact) return exact;
  if (serverMsg.role === "assistant") {
    return localMessages.find(
      (m) =>
        m.role === "assistant" &&
        !m.message_id &&
        !m.run_id &&
        (m.status === "streaming" || m.text.trim() === ""),
    );
  }
  if (serverMsg.role === "user") {
    return localMessages.find(
      (m) => m.role === "user" && !m.message_id && m.text.trim() === serverMsg.text.trim(),
    );
  }
  return undefined;
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
        const converted: ChatMsg[] = dedupeMessages(serverMsgs.map((m) => ({
          id:
            m.message_id ??
            `srv-${m.run_id ?? `${m.role}-${m.created_at}-${m.content}`}:${m.role}`,
          message_id: m.message_id,
          role: m.role,
          text: m.role === "assistant" ? sanitizeAssistantText(m.content) : m.content,
          status: "ready",
          created_at: m.created_at,
          run_id: m.run_id,
          // `result` 不可从后端还原, 渲染为纯文本气泡 (无 inline 工具调用)
        })));
        set((s) => {
          const persisted = s.bySession[session_id];
          const cur = Array.isArray(persisted)
            ? dedupeMessages(persisted.filter(validChatMessage))
            : [];

          // Merge strategy: server messages are the authoritative timeline.
          // For assistant messages (with run_id): prefer local copy if already
          // rendered (rich toolCalls/result data), fall back to server copy.
          // For user messages without ids: match only local optimistic messages
          // that have not yet received a backend identity.
          const combined: ChatMsg[] = [];
          const seenKeys = new Set<string>();
          const confirmedContent = new Set(converted.map((m) => contentKey(m)));

          for (const serverMsg of converted) {
            const stable = messageKey(serverMsg);
            if (seenKeys.has(stable)) continue;
            const localMatch = findLocalForServer(serverMsg, cur);
            const nextMsg = localMatch
              ? {
                  ...localMatch,
                  message_id: serverMsg.message_id ?? localMatch.message_id,
                  run_id: serverMsg.run_id ?? localMatch.run_id,
                  created_at: serverMsg.created_at || localMatch.created_at,
                  status: localMatch.status === "streaming" ? "ready" : localMatch.status,
                  text:
                    serverMsg.role === "assistant" && serverMsg.text.trim()
                      ? serverMsg.text
                      : localMatch.text,
                }
              : serverMsg;
            combined.push(nextMsg);
            seenKeys.add(stable);
            if (localMatch) {
              seenKeys.add(messageKey(localMatch));
            }
          }

          // Append local-only messages not covered by server (e.g. streaming)
          for (const localMsg of cur) {
            if (seenKeys.has(messageKey(localMsg))) continue;
            if (!localMsg.message_id && !localMsg.run_id && confirmedContent.has(contentKey(localMsg))) continue;
            combined.push(localMsg);
            seenKeys.add(messageKey(localMsg));
          }

          // Sort by created_at ascending
          combined.sort((a, b) => a.created_at.localeCompare(b.created_at));
          const cleaned = dedupeMessages(combined);
          const next = capHistory(
            { ...s.bySession, [session_id]: cleaned },
            session_id,
          );
          return { bySession: next };
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
