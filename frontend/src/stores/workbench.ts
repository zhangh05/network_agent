/**
 * Workbench store — chat history keyed by session_id, persisted to
 * localStorage so F5 不会丢历史 (plan-C 方案).
 *
 * 状态:
 *  - bySession: Record<session_id, ChatMsg[]> 持久化到 localStorage
 *  - history: 当前会话的历史视图 (derived from bySession[currentSessionId])
 *  - currentSessionId: 镜像 useSessionStore.currentSessionId
 *  - latestResult: 右侧检查器 (Inspector) 用
 *  - sending: 是否在等后端
 *
 * 持久化策略:
 *  - 每个会话最多 30 条消息
 *  - 最多保留 5 个最近会话
 *  - 超出 LRU 淘汰 (按会话 ID 字典序简化)
 *  - localStorage key: "na_workbench"
 *
 * 后台同步:
 *  - 切会话时, 先从 local 立即渲染, 再背景拉 /api/sessions/<id>/messages
 *  - merge 模式: 不覆盖本地, 只追加新消息 (避免丢失用户刚发的 turn)
 *  - 后端修复了 run_ids bug 后, 跨设备/跨 tab 刷新会自动同步
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { AgentResult, SessionMessage } from "../types";
import { sanitizeAssistantText } from "../utils/displayText";

export interface ChatMsg {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  created_at: string;
  /** attached to assistant msgs only */
  result?: AgentResult;
  /** v1.0.3.2: run_id from the backend, used for dedup in mergeFromBackend */
  run_id?: string;
}

const MAX_MSGS_PER_SESSION = 30;
const MAX_SESSIONS = 5;

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
function capHistory(map: Record<string, ChatMsg[]>): Record<string, ChatMsg[]> {
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
    const sorted = [...keys].sort();
    const toDelete = sorted.slice(0, sorted.length - MAX_SESSIONS);
    for (const k of toDelete) delete capped[k];
  }
  return capped;
}

interface WorkbenchState {
  bySession: Record<string, ChatMsg[]>;
  currentSessionId: string | null;
  history: ChatMsg[];
  latestResult: AgentResult | null;
  sending: boolean;
  /** v1.0.3.3: last user input for retry */
  lastUserInput: string;

  switchSession: (session_id: string | null) => void;
  appendUser: (text: string, session_id: string | null) => void;
  appendAssistant: (
    text: string,
    result: AgentResult | undefined,
    session_id: string | null,
  ) => void;
  setSending: (v: boolean) => void;
  setLatestResult: (r: AgentResult) => void;
  /** Drop local history for current (or specified) session. */
  clear: (session_id?: string) => void;
  /**
   * Merge backend messages into the bySession map. Never deletes local
   * entries; only adds new ones. Dedup by message id.
   */
  mergeFromBackend: (session_id: string, serverMsgs: SessionMessage[]) => void;
}

export const useWorkbenchStore = create<WorkbenchState>()(
  persist(
    (set, get) => ({
      bySession: {},
      currentSessionId: null,
      history: [],
      latestResult: null,
      sending: false,
      lastUserInput: "",

      switchSession: (session_id) => {
        // Always update history from bySession, even if id hasn't changed —
        // persist hydration can restore bySession while currentSessionId stays null.
        const history = session_id ? (get().bySession[session_id] ?? []) : [];
        set({ currentSessionId: session_id, history });
      },

      appendUser: (text, session_id) => {
        // null/undefined → _scratch 池 (等后端返回 session_id 后由页面层迁过去)
        const sid = session_id ?? get().currentSessionId ?? "_scratch";
        const msg: ChatMsg = {
          id: nextId(),
          role: "user",
          text,
          created_at: new Date().toISOString(),
        };
        set((s) => {
          const cur = s.bySession[sid] ?? [];
          const next = capHistory({ ...s.bySession, [sid]: [...cur, msg] });
          // Update history when this is the active session, including _scratch fallback
          const isActive = s.currentSessionId === sid || (!s.currentSessionId && sid === "_scratch");
          return {
            bySession: next,
            history: isActive ? next[sid] : s.history,
            lastUserInput: text,
          };
        });
      },

      appendAssistant: (text, result, session_id) => {
        const sid = session_id ?? get().currentSessionId ?? "_scratch";
        const cleanText = sanitizeAssistantText(text);
        const cleanResult = result
          ? { ...result, final_response: sanitizeAssistantText(result.final_response ?? "") }
          : undefined;
        const msg: ChatMsg = {
          id: nextId(),
          role: "assistant",
          text: cleanText,
          created_at: new Date().toISOString(),
          result: cleanResult,
        };
        set((s) => {
          const cur = s.bySession[sid] ?? [];
          const next = capHistory({ ...s.bySession, [sid]: [...cur, msg] });
          const isActive = s.currentSessionId === sid || (!s.currentSessionId && sid === "_scratch");
          return {
            bySession: next,
            history: isActive ? next[sid] : s.history,
            latestResult: cleanResult ?? s.latestResult,
          };
        });
      },

      setSending: (v) => set({ sending: v }),
      setLatestResult: (r) => set({ latestResult: r }),

      clear: (session_id) => {
        const sid = session_id ?? get().currentSessionId;
        if (!sid) {
          set({ history: [], latestResult: null });
          return;
        }
        set((s) => {
          const next = { ...s.bySession };
          delete next[sid];
          return {
            bySession: next,
            history: s.currentSessionId === sid ? [] : s.history,
            latestResult: s.currentSessionId === sid ? null : s.latestResult,
          };
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
          created_at: m.created_at,
          run_id: m.run_id,
          // `result` 不可从后端还原, 渲染为纯文本气泡 (无 inline 工具调用)
        }));
        set((s) => {
          const cur = s.bySession[session_id] ?? [];
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
          const next = capHistory({
            ...s.bySession,
            [session_id]: combined,
          });
          return {
            bySession: next,
            history: s.currentSessionId === session_id ? next[session_id] : s.history,
          };
        });
      },
    }),
    {
      name: "na_workbench",
      version: 2,
      partialize: (s) => ({
        bySession: s.bySession,
        lastUserInput: s.lastUserInput,
      }),
      merge: (persisted: unknown, current: WorkbenchState): WorkbenchState => {
        const safe = (persisted as Record<string, unknown> | null | undefined)?.bySession;
        if (safe && typeof safe === "object" && !Array.isArray(safe)) {
          return { ...current, bySession: safe as Record<string, ChatMsg[]> };
        }
        return current;
      },
    },
  ),
);
