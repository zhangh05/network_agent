import { create } from "zustand";
import type { AgentResult } from "../types";

interface ChatMsg {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  created_at: string;
  result?: AgentResult; // attached on assistant msgs
}

interface WorkbenchState {
  history: ChatMsg[];
  latestResult: AgentResult | null;
  sending: boolean;

  appendUser: (text: string) => void;
  appendAssistant: (text: string, result?: AgentResult) => void;
  setSending: (v: boolean) => void;
  setLatestResult: (r: AgentResult) => void;
  clear: () => void;
}

let msgSeq = 0;
function nextId(): string {
  msgSeq += 1;
  return `msg-${Date.now()}-${msgSeq}`;
}

export const useWorkbenchStore = create<WorkbenchState>((set, get) => ({
  history: [],
  latestResult: null,
  sending: false,
  appendUser: (text) =>
    set({
      history: [
        ...get().history,
        { id: nextId(), role: "user", text, created_at: new Date().toISOString() },
      ],
    }),
  appendAssistant: (text, result) =>
    set({
      history: [
        ...get().history,
        {
          id: nextId(),
          role: "assistant",
          text,
          created_at: new Date().toISOString(),
          result,
        },
      ],
      latestResult: result ?? get().latestResult,
    }),
  setSending: (v) => set({ sending: v }),
  setLatestResult: (r) => set({ latestResult: r }),
  clear: () => set({ history: [], latestResult: null }),
}));
